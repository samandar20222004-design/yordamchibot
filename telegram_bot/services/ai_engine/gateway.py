"""YAGONA KANONIK AI SHLYUZ — AI ENGINE V2 (Faza 1, 2, 3).

DEEP AUDIT muammosi: AI chaqiruvlari IKKIGA bo'lingan edi — eski modullar
``utils/ai_agent.py`` ga, yangilari ``services/ai/*`` ga murojaat qilar,
yagona marshrutlash va tezkor kesh yo'q edi.

Endi barcha AI so'rovlari uchun Bitta kirish nuqtasi — shu modul:

    from services.ai_engine import gateway

    res = await gateway.generate("kofe do'koni uchun post", task="simple_post")
    res.text, res.provider, res.lane, res.cached

Arxitektura (qatlamlar):

    handler / xizmat
        └─ gateway.generate / analyze / vision_analyze   ← YAGONA KIRISH
             ├─ cache.get (FAST lane — deterministik kalit)
             ├─ router.resolve_lane → FAST/QUALITY/REASONING/VISION
             ├─ health.healthy_order (circuit breaker — 429/timeout/5xx)
             ├─ providers.execute_provider (services/ai_service adapterlari)
             └─ cache.set (muvaffaqiyatda)

    Eski chaqiruvlar (backward compatibility):
        utils/ai_agent._run_ai_chain → gateway.legacy_chain →
        services.ai_service.run_ai_chain (8-provayderli legacy zanjir,
        O'ZGARMAGAN — barcha mavjud testlar va chaqiruvchilar ishlaydi).

Qat'iy qoidalar:

* **Fast Path** — oddiy so'rovlar (FAST lane) og'ir modellar navbatida
  qotib qolmaydi: qat'iy umumiy timeout (default 12s) + kesh tekshiruvi
  va keshga yozish; navbat menejeri (``services.ai.concurrency``) FAQAT
  og'ir orchestratsiya uchun qoladi.
* **Hech qachon istisno otilmaydi** — barcha xatolar
  :class:`GatewayResult(ok=False, error=...)` bilan qaytadi (fail-soft,
  foydalanuvchiga tayyor muloyim xabar).
* **P0-A siyosati buzilmaydi** — shlyuz HAQIQIY provayderlargagina
  murojaat qiladi; Mock faqat legacy zanjir siyosatida qoladi.
* **Yagona sog'liq holati** — health monitori legacy ``_BREAKERS`` ni
  mirror qiladi (legacy va gateway bitta breaker siyosatida).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from .cache import cache_key, default_cache
from .health import classify_exception, default_health_monitor
from .router import TASK_LANES, Lane, LaneSpec, LANE_SPECS, provider_order, resolve_lane

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sozlash (ENV — .env.example'da hujjatlangan; chaqiruv paytida o'qiladi,
# shuning uchun testlar/runtime'da o'zgartirish mumkin).
# ---------------------------------------------------------------------------
#: Fast Path qat'iy umumiy timeout'i (soniya) — spetsifikatsiya: 10-15s.


def fast_path_timeout() -> float:
    try:
        return max(1.0, float(os.getenv("AI_FAST_PATH_TIMEOUT", "12")))
    except (TypeError, ValueError):
        return 12.0


def lane_default_timeout(lane: Lane) -> float:
    """Lane standart timeout'i (``AI_<LANE>_TIMEOUT`` env bilan bekor qilinadi)."""
    env_name = f"AI_{lane.value}_TIMEOUT"
    try:
        return max(1.0, float(os.getenv(env_name, str(LANE_SPECS[lane].default_timeout))))
    except (TypeError, ValueError):
        return LANE_SPECS[lane].default_timeout


# ---------------------------------------------------------------------------
# Lane standart tizim promptlari (qisqa, til yo'nalishi bilan mustahkamlanadi)
# ---------------------------------------------------------------------------
_LANE_SYSTEMS: dict[Lane, str] = {
    Lane.FAST: (
        "Siz professional SMM copywriter'siz. Faqat tayyor post matnini "
        "qaytaring — izoh, sarlavha va qo'shimcha tushuntirishsiz."
    ),
    Lane.QUALITY: (
        "Siz professional SMM copywriter va tahlilchisiz. Sifatli, aniq va "
        "foydalanuvchi tilida javob qaytaring."
    ),
    Lane.REASONING: (
        "Siz tajribali SMM kontent-strateg va analitiksisz. Chuqur, asoslangan "
        "tahlil va reja qaytaring; umumiy 'suv' gaplardan qoching."
    ),
    Lane.VISION: (
        "Siz vizual kontent tahlilchisisiz. Rasm mazmunini aniq va ixcham "
        "tahlil qiling."
    ),
}


def default_system_instruction(lane: Lane) -> str:
    """Lane uchun standart tizim prompti (chaqiruvchi bermasa)."""
    return _LANE_SYSTEMS.get(lane, _LANE_SYSTEMS[Lane.QUALITY])


# ---------------------------------------------------------------------------
# Natija konteyneri
# ---------------------------------------------------------------------------
@dataclass
class GatewayResult:
    """Shlyuz javobi — xato ham ISTISNO EMAS, qat'iy qiymat."""

    ok: bool
    text: str = ""
    #: Muvaffaqiyatli provayder (kanonik nom) yoki "cache" / "none".
    provider: str = "none"
    lane: Lane = Lane.QUALITY
    task: str = ""
    #: Javob keshdan kelganmi?
    cached: bool = False
    #: Umumiy ketgan vaqt (soniya).
    elapsed: float = 0.0
    #: Ok bo'lmasa — foydalanuvchiga tayyor muloyim xabar (uz/ru/en).
    error: str | None = None
    #: Provayder qaytargan to'liq dict (legacy shakl) — bo'lishi mumkin.
    raw: dict = field(default_factory=dict)
    #: Sinovdan o'tgan provayderlar (tartib bilan, diagnostika).
    provider_chain: list[str] = field(default_factory=list)

    def json_result(self) -> dict | None:
        """Javob matnidan JSON dict ajratadi (bo'lmasa ``None``).

        Tahlil (analyze) natijalari uchun qulaylik; hech qachon yiqilmaydi.
        """
        import json

        text = (self.text or "").strip()
        if not text:
            return None
        # ```json ... ``` fence'ini yechish.
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Yordamchi: provayder javobidan matn ajratish (legacy shakllar bilan mos)
# ---------------------------------------------------------------------------
_TEXT_FIELDS = ("post_text", "content", "text", "reply", "response")


def extract_text(result: dict) -> str:
    """Provayder dict'idan asosiy matnni ajratadi (legacy maydonlar)."""
    if not isinstance(result, dict):
        return ""
    for field_name in _TEXT_FIELDS:
        value = result.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _graceful_error(lang: str, timeout: bool = False) -> str:
    """Foydalanuvchiga tayyor xavfsiz xabar (legacy xabarlar bilan bir xil)."""
    try:
        if timeout:
            from utils.ai_agent import ai_timeout_message

            return ai_timeout_message(lang or "uz")
        from services.ai.providers import ai_unavailable_message

        return ai_unavailable_message(lang or "uz")
    except Exception:  # pragma: no cover — himoya
        return "⚠️ AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring."


def _language_directive(system_instruction: str, lang: str | None) -> str:
    """Til qoidasini biriktirish (legacy ``with_language`` — yagona manba)."""
    if not lang:
        return system_instruction
    try:
        from utils.ai_agent import normalize_ai_lang, with_language

        return with_language(system_instruction, normalize_ai_lang(lang))
    except Exception:  # pragma: no cover — himoya
        return system_instruction


# ---------------------------------------------------------------------------
# YAGONA KIRISH NUQTALARI
# ---------------------------------------------------------------------------
async def generate(
    prompt: str,
    *,
    task: str | None = None,
    lane: Lane | str | None = None,
    lang: str = "uz",
    system_instruction: str | None = None,
    timeout: float | None = None,
    use_cache: bool | None = None,
    force_refresh: bool = False,
    tone: str = "",
    is_pro: bool = False,
) -> GatewayResult:
    """Barcha AI matn so'rovlari uchun YAGONA kirish nuqtasi.

    Args:
        prompt: foydalanuvchi mavzusi/matni.
        task: kanonik vazifa nomi (``router.TASK_LANES``) — lane tanlanadi.
        lane: aniq lane (task'dan ustun).
        lang: foydalanuvchi tili (uz/ru/en) — qat'iy til qoidasi biriktiriladi.
        system_instruction: maxsus tizim prompti (bo'lmasa lane standarti).
        timeout: umumiy qat'iy muddat (bo'lmasa lane standarti; FAST —
            ``AI_FAST_PATH_TIMEOUT``, default 12s).
        use_cache: keshdan foydalanish (bo'lmasa lane siyosati: FAST — ha).
        force_refresh: keshni e'tiborsiz qoldirib qayta generatsiya.
        tone: kanal uslubi (ixtiyoriy, kesh kalitiga kiradi).
        is_pro: PRO tarif belgisi (kesk kalitiga kiradi).

    Returns:
        :class:`GatewayResult` — xatoda ham istisno YO'Q (``ok=False``).
    """
    started = time.monotonic()
    resolved_lane = resolve_lane(task=task, lane=lane, prompt=prompt)
    cache_enabled = resolved_lane.default_cache if use_cache is None else bool(use_cache)

    # 1) KESH TEKSHIRUVI (Fast Path birinchi qadam — provayderga chiqmasdan).
    key = ""
    if cache_enabled:
        key = cache_key(
            prompt=prompt, lane=resolved_lane.value, task=str(task or ""),
            lang=lang, tone=tone, is_pro=is_pro,
            system_instruction=system_instruction or "",
        )
        if not force_refresh:
            cached_value = default_cache().get(key)
            if cached_value is not None:
                logger.info("AI Engine [FAST-HIT]: lane=%s task=%s (%.3fs)",
                            resolved_lane.value, task or "-", time.monotonic() - started)
                return GatewayResult(
                    ok=True, text=extract_text(cached_value) or str(cached_value.get("text", "")),
                    provider="cache", lane=resolved_lane, task=str(task or ""),
                    cached=True, elapsed=time.monotonic() - started, raw=cached_value,
                )

    # 2) TIZIM PROMPTI + QAT'IY TIL QOIDASI.
    sys_instr = system_instruction or default_system_instruction(resolved_lane)
    sys_instr = _language_directive(sys_instr, lang)

    # 3) QAT'IY UMUMIY MUDDAT.
    overall = float(timeout) if timeout else (
        fast_path_timeout() if resolved_lane is Lane.FAST
        else lane_default_timeout(resolved_lane)
    )

    # 4) GLOBAL KONKURENTLIK — legacy bilan bir xil semaphore
    #    (MAX_CONCURRENT_AI; bepul RPM limitlarini himoya qiladi).
    try:
        from utils import ai_agent as aa

        semaphore = aa._AI_SEMAPHORE
    except Exception:  # pragma: no cover — izolyatsiyalangan muhit
        semaphore = None

    async def _run() -> GatewayResult:
        return await _generate_via_chain(
            prompt, sys_instr, resolved_lane, lang,
            overall=overall, started=started, task=str(task or ""),
        )

    try:
        if semaphore is not None:
            async with semaphore:
                result = await asyncio.wait_for(_run(), timeout=overall)
        else:
            result = await asyncio.wait_for(_run(), timeout=overall)
    except asyncio.TimeoutError:
        logger.warning("AI Engine [%s]: %.0fs umumiy muddat oshdi (task=%s)",
                       resolved_lane.value, overall, task or "-")
        return GatewayResult(
            ok=False, lane=resolved_lane, task=str(task or ""),
            elapsed=time.monotonic() - started,
            error=_graceful_error(lang, timeout=True),
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft kafolati
        logger.warning("AI Engine [%s] kutilmagan xato: %s", resolved_lane.value, exc)
        return GatewayResult(
            ok=False, lane=resolved_lane, task=str(task or ""),
            elapsed=time.monotonic() - started, error=_graceful_error(lang),
        )

    # 5) MUVAFFAQIYAT → KESHGA YOZISH (deterministik kalit).
    if result.ok and cache_enabled and key:
        default_cache().set(key, result.raw or {"text": result.text})
    return result


async def _generate_via_chain(
    prompt: str,
    system_instruction: str,
    lane: Lane,
    lang: str,
    *,
    overall: float,
    started: float,
    task: str = "",
) -> GatewayResult:
    """Lane tartibida provayderlar zanjiri + circuit breaker avto-fallback.

    Provayderlar ``services.ai_engine.health`` monitori bo'yicha sog'lom
    tartibda sinab ko'riladi: 429/timeout/5xx → keyingi SOG'LOM provayder.
    """
    from services.ai_engine import providers as _providers

    monitor = default_health_monitor()
    wanted = provider_order(lane)
    order = monitor.healthy_order(wanted)
    handles = _providers.build_provider_handles()

    per_provider_cap = lane_default_timeout(lane)
    chain_tried: list[str] = []
    last_errors: list[str] = []

    for name in order:
        handle = handles.get(name)
        if handle is None:
            continue
        if monitor.is_open(name):
            continue  # breaker ochiq — avto-fallback allaqachon surilgan
        if not handle.provider.is_available():
            continue  # kalit yo'q (chaqiruv paytida tekshiriladi)

        remaining = overall - (time.monotonic() - started)
        if remaining <= 0.2:
            break  # umumiy muddat tugadi — foydalanuvchi kutmasin
        per_provider = min(per_provider_cap, remaining)
        chain_tried.append(name)
        try:
            result = await _providers.execute_provider(
                handle, prompt, system_instruction, lang=lang, timeout=per_provider,
            )
            text = extract_text(result)
            if not text:
                raise RuntimeError(f"{name}: bo'sh javob")
            monitor.record_success(name)
            logger.info("AI Engine [%s]: javob %s provayderidan (%.2fs)",
                        lane.value, name, time.monotonic() - started)
            return GatewayResult(
                ok=True, text=text, provider=name, lane=lane, task=task,
                elapsed=time.monotonic() - started,
                raw=dict(result), provider_chain=list(chain_tried),
            )
        except Exception as exc:  # noqa: BLE001 — keyingi provayderga
            kind = classify_exception(exc)
            monitor.record_failure(name, kind, str(exc))
            last_errors.append(f"{name}:{kind}")
            logger.warning("AI Engine [%s]: %s xato (%s) → keyingi provayder",
                           lane.value, name, kind)

    detail = "; ".join(last_errors) or "mavjud provayder yo'q"
    logger.warning("AI Engine [%s]: barcha provayderlar ishlamadi (%s)",
                   lane.value, detail)
    return GatewayResult(
        ok=False, lane=lane, task=task, elapsed=time.monotonic() - started,
        error=_graceful_error(lang), provider_chain=list(chain_tried),
    )


async def analyze(
    prompt: str,
    *,
    task: str | None = None,
    lang: str = "uz",
    system_instruction: str | None = None,
    timeout: float | None = None,
    lane: Lane | str | None = None,
    **kwargs,
) -> GatewayResult:
    """Tahlil so'rovlari uchun shlyuz kirishi (default: QUALITY lane).

    ``task`` aniq ko'rsatilsa — shu vazifa lane'i ishlatiladi (masalan
    ``task="channel_analysis"`` → REASONING). Natijani dict ko'rinishida
    olish uchun ``result.json_result()``.
    """
    resolved = resolve_lane(task=task, lane=lane, prompt=prompt)
    if system_instruction is None and resolved is Lane.QUALITY and not task:
        # analyze() default — tahlilga yo'naltirilgan tizim prompti.
        system_instruction = (
            "Siz professional SMM tahlilchisisiz. Javobni ixcham va aniq bering."
        )
    return await generate(
        prompt, task=task, lane=resolved, lang=lang,
        system_instruction=system_instruction, timeout=timeout, **kwargs,
    )


async def vision_analyze(
    data: bytes | bytearray | memoryview,
    *,
    caption: str = "",
    lang: str = "uz",
    timeout: float | None = None,
) -> GatewayResult:
    """Rasm tahlili — VISION lane (yagona shlyuz orqali).

    Haqiqiy Vision ishlari sinovdan o'tgan ``utils.vision_analyzer`` da
    qoladi (model zanjiri, 404/429/timeout fallback) — bu yerda ular
    QAYTA YOZILMAYDI, faqat shlyuz kontraktiga o'raladi.
    """
    started = time.monotonic()
    lane = Lane.VISION
    try:
        from utils import vision_analyzer as va

        analysis = await va.analyze_image(data, caption=caption, lang=lang,
                                          timeout=timeout)
        if isinstance(analysis, dict) and analysis.get("error"):
            return GatewayResult(
                ok=False, lane=lane, task="vision",
                elapsed=time.monotonic() - started, raw=dict(analysis),
                error=str(analysis.get("error")) or None,
            )
        return GatewayResult(
            ok=True, lane=lane, task="vision",
            text=str(analysis.get("description") or analysis.get("summary") or ""),
            provider=f"Vision:{analysis.get('model', '')}".strip(":"),
            elapsed=time.monotonic() - started,
            raw=dict(analysis),
        )
    except Exception as exc:  # noqa: BLE001 — Vision xatosi handler fallback'i
        logger.warning("AI Engine [VISION]: tahlil xatosi: %s", exc)
        return GatewayResult(
            ok=False, lane=lane, task="vision", elapsed=time.monotonic() - started,
            raw={"error": str(exc)}, error=str(exc) or None,
        )


# ---------------------------------------------------------------------------
# LEGACY ADAPTER — utils/ai_agent.py ning kanonik shlyuzga ulanishi
# ---------------------------------------------------------------------------
async def legacy_chain(prompt: str, system_instruction: str, lang: str | None = None) -> dict:
    """Legacy zanjir adapteri (``utils.ai_agent._run_ai_chain`` delegati).

    Eski 8-provayderli zanjir (``services.ai_service.run_ai_chain``) O'ZGARISHSIZ
    qoladi — shu adapter orqali chaqiriladi. Shu tufayli:

    * ``generate_ai_response``/``audit_post``/``generate_magic_post`` va barcha
      boshqa eski funksiyalar endi kanonik shlyuz KANALIGA tushadi;
    * ``provider``/``provider_chain`` maydonlari va test monkeypatch
      nuqtalari (``ai_agent._run_ai_chain``) o'zgarmaydi — backward compat.
    """
    from services import ai_service

    return await ai_service.run_ai_chain(prompt, system_instruction, lang=lang)


# ---------------------------------------------------------------------------
# KANONIK OPERATSIYALAR — handler'lar AI uchun FAQAT shu sirttan import oladi
# ---------------------------------------------------------------------------
# Audit qoidasi: "Hech bir handler provayderga to'g'ridan-to'g'ri
# bog'lanmasin!" — shu sababli handler'lar ``services.ai_service`` /
# ``services.ai.providers`` import QILMAYDI. Ushbu delegatlar xuddi shu
# sinovdan o'tgan funksiyalarni (hech narsa noldan yozilmagan) kechikkan
# bog'lanish (late binding) bilan chaqiradi: ``services.ai_service.X``
# testlarda monkeypatch qilinsa — delegat ham yangi qiymatni ko'radi.
def _late_bind_service_op(name: str):
    async def _op(*args, **kwargs):
        from services import ai_service

        return await getattr(ai_service, name)(*args, **kwargs)
    _op.__name__ = name
    _op.__qualname__ = f"gateway.{name}"
    _op.__doc__ = (
        f"Yagona shlyuz delegati: ``services.ai_service.{name}`` "
        "(kechikkan bog'lanish — test monkeypatch'lari ishlashda davom etadi)."
    )
    return _op


#: Post baholash (6 mezon, bepul) — ``handlers.post_score``.
score_post = _late_bind_service_op("score_post")
#: Postni 95+ ballik variantga qayta ishlash — ``handlers.post_score``.
improve_post_to_95 = _late_bind_service_op("improve_post_to_95")
#: Rasm tahlilidan post generatsiya — ``handlers.image_post``.
generate_image_post = _late_bind_service_op("generate_image_post")


# ---------------------------------------------------------------------------
# Diagnostika (admin/health panel uchun)
# ---------------------------------------------------------------------------
def gateway_status() -> dict:
    """Shlyuz holati: lane'lar, kesh va provayderlar sog'lig'i."""
    monitor = default_health_monitor()
    try:
        cache_stats = default_cache().stats()
    except Exception:  # pragma: no cover
        cache_stats = {}
    lanes_status: dict[str, dict] = {}
    for lane, spec in LANE_SPECS.items():
        lanes_status[lane.value] = {
            "label": spec.label,
            "description": spec.description,
            "default_timeout": spec.default_timeout,
            "cache_by_default": spec.cache_by_default,
            "provider_order": list(spec.provider_order),
            "tasks": sorted(t for t, l in TASK_LANES.items() if l is lane),
        }
    return {
        "lanes": lanes_status,
        "fast_path_timeout": fast_path_timeout(),
        "cache": cache_stats,
        "health": monitor.snapshot(),
    }


__all__ = [
    "GatewayResult",
    "generate",
    "analyze",
    "vision_analyze",
    "legacy_chain",
    "gateway_status",
    "extract_text",
    "default_system_instruction",
    "fast_path_timeout",
    "lane_default_timeout",
    "score_post",
    "improve_post_to_95",
    "generate_image_post",
    "Lane",
    "LaneSpec",
]
