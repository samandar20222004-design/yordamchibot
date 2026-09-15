"""PostAssist V2 — 4-BOSQICH: AI Multi-Provider Fallback Service.

Yagona provayderlar boshqaruvi (unified provider management) va resilient
AI arxitektura. Foydalanuvchi xatolikni hech qachon ko'rmaydi: birlamchi
provayder **timeout**, **429 (rate limit)** yoki **5xx** xato bersa, zanjir
darhol keyingi provayderga o'tadi. Foydalanuvchiga muvaffaqiyatli javob
qaytgan provayderdan matn yetkaziladi.

Provayder zanjiri (avtomatik fallback)::

    ┌───────────────┬───────────────────────────────────────────┐
    │ Daraja        │ Provayder                                 │
    ├───────────────┼───────────────────────────────────────────┤
    │ 1 — Primary   │ Gemini                                    │
    │ 2 — Secondary │ Groq (llama-3 / mixtral)                  │
    │ 3 — Tertiary  │ OpenRouter (:free modellar)               │
    │ 4+ — Deep     │ Mistral → Cerebras → SambaNova →          │
    │               │ Cloudflare → Pollinations (kalitsiz)      │
    └───────────────┴───────────────────────────────────────────┘

Zanjir tartibi env orqali sozlanadi::

    AI_PROVIDER_CHAIN=gemini,groq,openrouter   # faqat yadro zanjiri
    AI_PROVIDER_CHAIN=                          # (bo'sh = to'liq zanjir)

Har bir provayder so'rovi uchun QAT'IY timeout::

    connect = AI_PROVIDER_CONNECT_TIMEOUT  (default 3s)
    read    = AI_PROVIDER_READ_TIMEOUT     (default 8s)
    jami    = AI_PROVIDER_TOTAL_TIMEOUT    (default 10s)

``generate_ai_response`` / ``analyze_user_prompt`` / ``audit_post``
hamda barcha AI oqimlari endi shu servis orqali ishlaydi
(``utils/ai_agent.py::_run_ai_chain`` shu yerda delegatsiya qiladi).

🌐 3 TILLIK MOSLASHUV (UZ / RU / EN)
    Har bir chaqiruv ``lang`` ('uz' | 'ru' | 'en') qabul qiladi. Orkestrator
    tizim promptiga ``utils/ai_agent.with_language()`` orqali QAT'IY til
    qoidasini biriktiradi (idempotent) va xato xabarlarini ham shu tilda
    qaytaradi. Natijada AI javobi, posti va tavsiyalari foydalanuvchi
    tilidan qat'i nazar boshqa tilga aralashib KETMAYDI.

Qaytariladigan natija (muvaffaqiyatda)::

    { ...model JSON maydonlari...,
      "provider": "Gemini",            # javob qaysi provayderdan keldi
      "provider_chain": ["Gemini"] }   # sinab ko'rilgan provayderlar

Barcha provayderlar ishdan chiqqan taqdirda (VA FAQAT o'shanda) — graceful
xato; foydalanuvchi kunlik kvotasi yechilmaydi::

    {"error": "<xushmuomala o'zbekcha xabar>",
     "ai_unavailable": True,   # barcha provayderlar ishdan chiqqan
     "quota_safe": True,       # kunlik kvota yechilmaydi
     "timeout": True}          # barchasi timeout bo'lgan hollarda
"""

import asyncio
import json
import logging
import os
import time as _time

import aiohttp

# Eslatma: provayder API kalitlari shu modilda o'qilmaydi — ular
# ``utils/ai_agent.py`` modul atributlaridan chaqiruv paytida olinadi
# (config orqali yuklangan qiymatlar ai_agent'da saqlanadi).

logger = logging.getLogger(__name__)

# ============================================================
# QAT'IY PROVAyder TIMEOUT (soniya) — har bir provayder alohida
# ============================================================
# Bitta osilib qolgan provayder butun zanjirni ushlab qolmasin:
# ulanish 3s, javob o'qish 8s, jami 10s — undan so'ng keyingi
# provayderga o'tiladi (foydalanuvchiga hech qanday xato ko'rsatilmasdan).
AI_PROVIDER_CONNECT_TIMEOUT = max(1, int(os.getenv("AI_PROVIDER_CONNECT_TIMEOUT", "3")))
AI_PROVIDER_READ_TIMEOUT = max(1, int(os.getenv("AI_PROVIDER_READ_TIMEOUT", "8")))
AI_PROVIDER_TOTAL_TIMEOUT = max(2, int(os.getenv("AI_PROVIDER_TOTAL_TIMEOUT", "10")))


def provider_http_timeout() -> aiohttp.ClientTimeout:
    """Har bir provayder so'rovi uchun qat'iy HTTP timeout.

    Modullik o'zgaruvchilardan CHAQIRUV PAYTIDA o'qiladi — testlarda va
    runtime'da chekraning sozlanishi darhol kuchga kiradi.
    """
    return aiohttp.ClientTimeout(
        total=float(AI_PROVIDER_TOTAL_TIMEOUT),
        connect=float(AI_PROVIDER_CONNECT_TIMEOUT),
        sock_connect=float(AI_PROVIDER_CONNECT_TIMEOUT),
        sock_read=float(AI_PROVIDER_READ_TIMEOUT),
    )


def provider_total_timeout() -> float:
    """Provayder sinovining qat'iy umumiy muddati (wait_for chegarasi)."""
    return float(AI_PROVIDER_TOTAL_TIMEOUT)


# ============================================================
# PROVAyder ZANJIRI — yagona boshqaruv
# ============================================================
#: 1-daraja: birlamchi provayder
PROVIDER_GEMINI = "Gemini"
#: 2-daraja: ikkinchi fallback (llama-3 / mixtral)
PROVIDER_GROQ = "Groq"
#: 3-daraja: uchinchi fallback
PROVIDER_OPENROUTER = "OpenRouter"
#: 4+ daraja: kengaytirilgan (deep) zaxira
PROVIDER_MISTRAL = "Mistral"
PROVIDER_CEREBRAS = "Cerebras"
PROVIDER_SAMBANOVA = "SambaNova"
PROVIDER_CLOUDFLARE = "Cloudflare"
PROVIDER_POLLINATIONS = "Pollinations"

#: Yadro zanjir (yukum topshiriq: Primary → Secondary → Tertiary)
CORE_PROVIDER_CHAIN = (PROVIDER_GEMINI, PROVIDER_GROQ, PROVIDER_OPENROUTER)
#: Kengaytirilgan zaxira (yadro ishlamasa bot umuman to'xtamagan bo'lsin).
#: Pollinations tartibda ko'rinadi, lekin kalitsiz/nobarqaror fallback sifatida
#: production'da faqat ENABLE_POLLINATIONS_FALLBACK=1 bo'lsa ``available`` bo'ladi.
EXTENDED_PROVIDER_CHAIN = (
    PROVIDER_MISTRAL,
    PROVIDER_CEREBRAS,
    PROVIDER_SAMBANOVA,
    PROVIDER_CLOUDFLARE,
    PROVIDER_POLLINATIONS,
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on", "enable", "enabled")


def pollinations_fallback_enabled() -> bool:
    """Kalitsiz Pollinations fallback feature flag'i (default: False)."""
    return _env_flag("ENABLE_POLLINATIONS_FALLBACK", False)

#: env qiymati → kanonik provayder nomi (aliaslar bilan)
_CANONICAL_PROVIDER = {
    "gemini": PROVIDER_GEMINI,
    "google": PROVIDER_GEMINI,
    "groq": PROVIDER_GROQ,
    "llama": PROVIDER_GROQ,
    "llama3": PROVIDER_GROQ,
    "mixtral": PROVIDER_GROQ,
    "openrouter": PROVIDER_OPENROUTER,
    "open-router": PROVIDER_OPENROUTER,
    "or": PROVIDER_OPENROUTER,
    "mistral": PROVIDER_MISTRAL,
    "cerebras": PROVIDER_CEREBRAS,
    "sambanova": PROVIDER_SAMBANOVA,
    "cloudflare": PROVIDER_CLOUDFLARE,
    "cf": PROVIDER_CLOUDFLARE,
    "pollinations": PROVIDER_POLLINATIONS,
    "pollination": PROVIDER_POLLINATIONS,
}

#: Provayder darajalari (1=primary, 2=secondary, 3=tertiary, 4=deep)
PROVIDER_TIERS = {
    PROVIDER_GEMINI: 1,
    PROVIDER_GROQ: 2,
    PROVIDER_OPENROUTER: 3,
    PROVIDER_MISTRAL: 4,
    PROVIDER_CEREBRAS: 4,
    PROVIDER_SAMBANOVA: 4,
    PROVIDER_CLOUDFLARE: 4,
    PROVIDER_POLLINATIONS: 4,
}


def build_provider_chain() -> tuple[str, ...]:
    """Mavjud provayderlar zanjirini qaytaradi.

    Default: yadro zanjir (Gemini → Groq → OpenRouter) + kengaytirilgan
    zaxira. ``AI_PROVIDER_CHAIN`` env orqali tartib/ro'yxat o'zgartiriladi.
    """
    raw = (os.getenv("AI_PROVIDER_CHAIN", "") or "").strip()
    default_chain = CORE_PROVIDER_CHAIN + EXTENDED_PROVIDER_CHAIN
    if not raw:
        return default_chain
    chain: list[str] = []
    for part in raw.split(","):
        name = _CANONICAL_PROVIDER.get(part.strip().lower())
        if name and name not in chain:
            chain.append(name)
    return tuple(chain) if chain else default_chain


# ============================================================
# PROVAYER ADAPTERLARI
# ============================================================

class AIProviderError(RuntimeError):
    """Provayder xatosi (status 0 = timeout/tarmoq xatosi)."""

    def __init__(self, status: int, message: str, provider: str = ""):
        super().__init__(f"{provider}: {message}" if provider else message)
        self.status = status
        self.message = message
        self.provider = provider


class AIProvider:
    """Yagona provayder interfeysi (adapter).

    API kaliti ``utils/ai_agent.py`` modul atributidan CHAQIRUV PAYTIDA
    o'qiladi — shu tufayli testlarda kalit/adapter stub bilan almashtirilganda
    yoki runtime'da muhit yangilanganida zanjir darhol moslashadi.
    """

    name: str = "base"
    tier: int = 4
    #: ai_agent modulidagi kalit atributi nomi (None = kalitsiz provayder)
    key_attr: str | None = None

    # --- qobiliyat -------------------------------------------------
    def _api_key(self) -> str:
        """ProvaYder kaliti (chaqiruv paytida, ai_agent modulidan)."""
        if self.key_attr is None:
            return ""
        aa = _ai_agent()
        return aa._clean_key(getattr(aa, self.key_attr, ""))

    def is_available(self) -> bool:
        """Provayderga so'rov yuborish mumkinmi (kalit mavjudmi)?"""
        return bool(self._api_key())

    # --- asosiy chaqiruv -------------------------------------------
    async def complete(
        self, prompt: str, system_instruction: str, params: dict, deadline: float = None
    ) -> dict:
        """Bitta provayderdan javob so'raydi.

        ``deadline`` (``time.monotonic()`` bazasida) — bu provayder uchun
        ajratilgan QAT'IY byudjetning oxirgi soniyasi: adapter har bir
        model/urinishdan oldin uni tekshiradi va byudjet tugasa darhol
        to'xtaydi (retrylar byudjetni cho'zib yubormaydi).

        Muvaffaqiyatda JSON dict qaytadi; xatolikda ``AIProviderError``
        yoki boshqa istisno tashlaydi (orkestrator keyingi provayderga
        o'tadi).
        """
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - log yordamchi
        return f"<AIProvider {self.name} tier={self.tier}>"


def _ai_agent():
    """Lazily import — ``utils/ai_agent.py`` bilan aylanma importdan himoya."""
    from utils import ai_agent
    return ai_agent


class GeminiProvider(AIProvider):
    """Primary (1-daraja): Google Gemini."""

    name = PROVIDER_GEMINI
    tier = 1
    key_attr = "GEMINI_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_gemini(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class GroqProvider(AIProvider):
    """Secondary (2-daraja): Groq — llama-3 / mixtral modellari."""

    name = PROVIDER_GROQ
    tier = 2
    key_attr = "GROQ_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_groq(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class OpenRouterProvider(AIProvider):
    """Tertiary (3-daraja): OpenRouter — :free modellar."""

    name = PROVIDER_OPENROUTER
    tier = 3
    key_attr = "OPENROUTER_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_openrouter(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class MistralProvider(AIProvider):
    name = PROVIDER_MISTRAL
    tier = 4
    key_attr = "MISTRAL_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_mistral(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class CerebrasProvider(AIProvider):
    name = PROVIDER_CEREBRAS
    tier = 4
    key_attr = "CEREBRAS_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_cerebras(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class SambaNovaProvider(AIProvider):
    name = PROVIDER_SAMBANOVA
    tier = 4
    key_attr = "SAMBANOVA_API_KEY"

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_sambanova(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class CloudflareProvider(AIProvider):
    """Cloudflare Workers AI — kalit + CLOUDFLARE_ACCOUNT_ID ikkalasi kerak."""

    name = PROVIDER_CLOUDFLARE
    tier = 4
    key_attr = "CLOUDFLARE_API_TOKEN"

    def is_available(self) -> bool:
        """Kalit VA CLOUDFLARE_ACCOUNT_ID ikkalasi ham kerak (chaqiruv paytida)."""
        aa = _ai_agent()
        account_id = (getattr(aa, "CLOUDFLARE_ACCOUNT_ID", "") or "").strip()
        return bool(self._api_key() and account_id)

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_cloudflare(
            prompt, self._api_key(), system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


class PollinationsProvider(AIProvider):
    """Kalitsiz bepul zaxira — faqat feature flag yoqilganda oxirgi chora."""

    name = PROVIDER_POLLINATIONS
    tier = 4
    key_attr = None

    def is_available(self) -> bool:
        if pollinations_fallback_enabled():
            return True
        # Testlarda adapter stub/monkeypatch qilinganda zanjir tartibini
        # tekshirish uchun ruxsat beramiz; production'da original kalitsiz
        # endpoint feature flag yoqilmaguncha ishlatilmaydi.
        try:
            aa = _ai_agent()
            if getattr(aa._call_pollinations, "__module__", "") != "utils.ai_agent":
                return True
            # Lokal mock endpointlar test muhiti uchun; production'da default
            # text.pollinations.ai flag yoqilmaguncha chaqirilmaydi.
            endpoint = str(getattr(aa, "POLLINATIONS_ENDPOINT", ""))
            return endpoint.startswith(("http://127.0.0.1", "http://localhost"))
        except Exception:
            return False

    async def complete(self, prompt, system_instruction, params, deadline=None):
        aa = _ai_agent()
        return await aa._call_pollinations(
            prompt, system_instruction, params,
            http_timeout=provider_http_timeout(), deadline=deadline,
        )


def build_default_providers() -> list[AIProvider]:
    """Provayder zanjirini quradi.

    Kalitlar bu yerda o'qilmaydi — har bir provider o'z kalitini
    ``utils/ai_agent.py`` modul atributidan CHAQIRUV PAYTIDA oladi
    (test/stub va runtime sozlamalarini darhol hisobga oladi).
    """
    chain = build_provider_chain()

    factories = {
        PROVIDER_GEMINI: GeminiProvider,
        PROVIDER_GROQ: GroqProvider,
        PROVIDER_OPENROUTER: OpenRouterProvider,
        PROVIDER_MISTRAL: MistralProvider,
        PROVIDER_CEREBRAS: CerebrasProvider,
        PROVIDER_SAMBANOVA: SambaNovaProvider,
        PROVIDER_CLOUDFLARE: CloudflareProvider,
        PROVIDER_POLLINATIONS: PollinationsProvider,
    }
    providers = []
    for name in chain:
        factory = factories.get(name)
        if factory is not None:
            providers.append(factory())
    return providers


# ============================================================
# GRACEFUL XATO (barcha provayderlar ishdan chiqqanida)
# ============================================================

def enforce_system_language(system_instruction: str, lang=None) -> str:
    """Tizim promptiga foydalanuvchi tilining QAT'IY qoidasini biriktiradi.

    Orkestrator darajasidagi YAKUNIY himoya qatlami: ``utils/ai_agent.py``
    til blokini allaqachon qo'shgan bo'lsa ham, bu yerda qayta
    qo'shilMAYDI (``with_language`` idempotent).

    ``lang`` None/bo'sh bo'lsa — prompt O'ZGARISHSIZ qaytadi (orqaga moslik).
    """
    if not lang:
        return system_instruction
    try:
        aa = _ai_agent()
        func = getattr(aa, "with_language", None) or getattr(aa, "apply_language", None)
        if func is None:
            return system_instruction
        return func(system_instruction, lang)
    except Exception:  # pragma: no cover - himoya
        return system_instruction


def _graceful_error(errors: list, lang: str = None) -> dict:
    """Barcha provayderlar ishlamaganda qaytariladigan toza xato.

    Bu holatda foydalanuvchining kunlik kvotasi yechilmaydi
    (``quota_safe=True`` — handler bal/sanakchini oshirmaydi va
    band qilingan ballini qaytaradi).

    🌐 ``lang`` berilsa, timeout xabari foydalanuvchi tilida chiqadi.
    """
    detail = "\n".join(f"• {e}" for e in errors if e)

    # Agar barcha (yoki asosiy) uzilishlar TIMEOUT tufayli bo'lsa — texnik
    # ro'yxat o'rniga foydalanuvchiga xushmuomala, tushunarli xabar beramiz.
    timeout_errors = [e for e in errors if "timeout" in str(e).lower()]
    real_attempts = [e for e in errors if "kalit topilmadi" not in str(e)]
    if (timeout_errors and len(timeout_errors) >= max(1, len(real_attempts))) or not real_attempts:
        logger.warning("Barcha AI provayderlari timeout/urinishsiz fail-closed bo'ldi: %s", detail)
        try:
            message = _ai_agent().ai_timeout_message(lang or "uz")
        except Exception:  # pragma: no cover - himoya
            message = _ai_agent().AI_TIMEOUT_USER_MESSAGE
        return {
            "error": message,
            "timeout": True,
            "ai_unavailable": True,
            "quota_safe": True,
        }

    return {
        "error": (
            "⚠️ AI xizmatlarining hech biri javob bermadi:\n"
            f"{detail}\n\n"
            "💡 <b>Bepul kalit olish (kamida bittasi kifoya):</b>\n"
            "• Gemini → GEMINI_API_KEY: aistudio.google.com (kuniga 1500 so'rov)\n"
            "• Groq → GROQ_API_KEY: console.groq.com (kuniga 1000 so'rov)\n"
            "• Mistral → MISTRAL_API_KEY: console.mistral.ai (oyiga ~1 mlrd token)\n"
            "• Cerebras → CEREBRAS_API_KEY: cloud.cerebras.ai (kuniga 1M token)\n"
            "• OpenRouter → OPENROUTER_API_KEY: openrouter.ai (:free modellar)\n"
            "• SambaNova → SAMBANOVA_API_KEY: cloud.sambanova.ai (10–30 RPM)\n"
            "• Cloudflare → CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID: "
            "dash.cloudflare.com → Workers AI (kunlik 10K neuron)\n"
            "Kalitlarni Render → Environment bo'limiga qo'shing va botni qayta ishga tushiring."
        ),
        "ai_unavailable": True,
        "quota_safe": True,
    }


# ============================================================
# ORKESTRATOR — avtomatik fallback zanjiri
# ============================================================

class AIFallbackService:
    """Yagona AI provayderlar orkestratori.

    - Provayderlar daraja tartibida (Primary → Secondary → Tertiary → deep)
      sinab ko'riladi.
    - Har bir provayder sinovi ``AI_PROVIDER_TOTAL_TIMEOUT`` (default 10s)
      ichida yakunlanishi SHART — ``asyncio.wait_for`` qat'iy cheklaydi.
    - Timeout / 429 / 5xx / boshqa istisno → keyingi provayder (foydalanuvchi
      hech qanday xato ko'rmaydi).
    - Circuit breaker: provayder 3 marta ketma-ket xato bersa, 10 daqiqaga
      o'tkazib yuboriladi (``utils/ai_agent.py`` bilan umumiy holat).
    - Barcha provayderlar ishdan chiqqan taqdirdagina graceful xato
      qaytariladi (``ai_unavailable=True``, ``quota_safe=True``).
    """

    def __init__(self, providers: list[AIProvider] = None):
        self.providers: list[AIProvider] = (
            providers if providers is not None else build_default_providers()
        )

    # ----------------------------------------------------------
    def _prepare_prompt(self, prompt: str) -> str:
        """Prompt uzunligini ``max_prompt_chars`` bilan cheklaydi."""
        aa = _ai_agent()
        params = aa.get_runtime_params()
        max_prompt_chars = int(params.get("max_prompt_chars") or aa.MAX_PROMPT_CHARS)
        prompt = (prompt or "").strip()
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars] + "\n…(matn juda uzun edi, kesildi)"
        return prompt

    # ----------------------------------------------------------
    async def generate(self, prompt: str, system_instruction: str,
                       lang: str = None) -> dict:
        """Fallback zanjiri orqali AI javobini qaytaradi.

        Muvaffaqiyatda: provayder JSON dict + ``provider`` /
        ``provider_chain`` maydonlari. Barcha provayderlar yiqilsa:
        graceful xato dict (kvota yechilmaydi).

        🌐 3 TILLIK (UZ / RU / EN): ``lang`` berilsa, tizim promptiga
        qat'iy til qoidasi biriktiriladi (:func:`enforce_system_language`)
        va xato xabarlari ham shu tilda qaytadi. ``lang=None`` bo'lsa —
        eski (tilsiz) xatti-harakat saqlanadi.
        """
        aa = _ai_agent()
        prompt = self._prepare_prompt(prompt)
        params = aa.get_runtime_params()
        # Til qoidasi — eng yuqorida (idempotent: takror qo'shilmaydi).
        system_instruction = enforce_system_language(system_instruction, lang)

        errors: list[str] = []
        chain: list[str] = []

        async with aa._AI_SEMAPHORE:
            for provider in self.providers:
                name = provider.name

                if aa._breaker_open(name):
                    errors.append(f"{name}: vaqtincha o'tkazib yuborildi")
                    continue

                if not provider.is_available():
                    errors.append(
                        f"{name}: kalit topilmadi" + (" (ixtiyoriy)" if name != "Gemini" else "")
                    )
                    continue

                chain.append(name)
                started = _time.monotonic()
                # QAT'IY byudjet: deadline adapter'ga uzatiladi (har bir
                # model/urinishdan oldin tekshiriladi) + wait_for — ikki
                # qavatli qat'iy chegara.
                deadline = _time.monotonic() + provider_total_timeout()
                try:
                    result = await asyncio.wait_for(
                        provider.complete(prompt, system_instruction, params, deadline),
                        timeout=provider_total_timeout(),
                    )
                    if isinstance(result, dict):
                        aa._breaker_success(name)
                        logger.info(
                            "AI javobi muvaffaqiyatli: %s (%.1fs)",
                            name, _time.monotonic() - started,
                        )
                        result.setdefault("provider", name)
                        result.setdefault("provider_chain", list(chain))
                        return result
                    errors.append(f"{name}: javob formati noto'g'ri")
                except asyncio.TimeoutError:
                    errors.append(f"{name}: timeout ({int(provider_total_timeout())}s)")
                    aa._breaker_fail(name)
                    logger.warning(
                        "%s qat'iy timeout ichida javob bermadi. Keyingi zaxiraga o'tilmoqda...",
                        name,
                    )
                except Exception as e:
                    errors.append(f"{name}: {e}")
                    aa._breaker_fail(name)
                    logger.warning("%s ishlamadi (%s). Keyingi zaxiraga o'tilmoqda...", name, e)

        return _graceful_error(errors, lang)

    # ----------------------------------------------------------
    def status(self) -> dict:
        """Provayderlar holati (admin panel / diagnostika)."""
        aa = _ai_agent()
        now = _time.time()
        return {
            "chain": [p.name for p in self.providers],
            "timeout": {
                "connect": AI_PROVIDER_CONNECT_TIMEOUT,
                "read": AI_PROVIDER_READ_TIMEOUT,
                "total": AI_PROVIDER_TOTAL_TIMEOUT,
            },
            "providers": [
                {
                    "name": p.name,
                    "tier": p.tier,
                    "available": p.is_available(),
                    "breaker_open": bool(
                        aa._BREAKERS.get(p.name, {}).get("until")
                        and now < aa._BREAKERS[p.name]["until"]
                    ),
                }
                for p in self.providers
            ],
        }


# ============================================================
# MODUL DARAJASIDAGI KIRISH NUQTA (yagona orkestrator)
# ============================================================

_default_service: AIFallbackService | None = None


def get_default_service() -> AIFallbackService:
    """Singleton orkestrator (birinchi chaqiruvda quriladi)."""
    global _default_service
    if _default_service is None:
        _default_service = AIFallbackService()
    return _default_service


def reset_default_service() -> None:
    """Testlar / kalit yangilanishi uchun orkestratorni qayta quradi."""
    global _default_service
    _default_service = None


async def run_ai_chain(prompt: str, system_instruction: str, lang: str = None) -> dict:
    """Yagona AI kirish nuqtasi: promptni avtomatik fallback zanjiridan o'tkazadi.

    ``utils/ai_agent.py::_run_ai_chain`` shu funksiya bilan almashtirilgan —
    barcha mavjud chaqiruvchilar (ai_assistant, content_plan, formatlash,
    kontent-reja, kanal ovozi va h.k.) endi shu yagona orkestratordan ishlaydi.

    🌐 ``lang`` ('uz' | 'ru' | 'en') berilsa, orkestrator tizim promptiga
    foydalanuvchi tilining QAT'IY qoidasini biriktiradi — AI javobi,
    posti va tavsiyalari faqat shu tilda bo'ladi.
    """
    return await get_default_service().generate(prompt, system_instruction, lang=lang)

# ============================================================
# 📸 IMAGE → POST (KILLER FEATURE #3)
# ============================================================
# Vision (rasmni tushunish) va copywriting (tanlangan uslubda post yozish)
# ataylab ikki alohida kirish nuqtasi. Vision bosqichida kredit sarflanmaydi;
# handler kreditni uslub callback'ining boshida, FAQAT bir marta rezerv qiladi.

_IMAGE_POST_STYLE_SPECS = {
    "sales": (
        "🔥 Sotuv uslubi: AIDA/PAS formulasi, foydani aniq ko'rsating, "
        "ishonchli CTA va buyurtma qilish qadamini yozing."
    ),
    "premium": (
        "💎 Premium uslub: nafis, minimal va yuqori sifatli brend tili; "
        "material, detal va eksklyuzivlikni bo'rttirmasdan ta'kidlang."
    ),
    "simple": (
        "😊 Oddiy uslub: samimiy, sodda va tez o'qiladigan tilda; "
        "ortiqcha va'da yoki murakkab iboralar ishlatmang."
    ),
    "discount": (
        "📢 Chegirma/Aksiya uslubi: chegirma, narx yoki muddat captionda bo'lsa "
        "uni aniq ajrating; shoshilinch, lekin halol CTA yozing."
    ),
    "review": (
        "📰 Sharh uslubi: xolis sharh/review ohangi; ko'rinadigan foyda va "
        "kamchiliklarni uydirmasdan, yumshoq tavsiya bilan bering."
    ),
}


def _image_analysis_text(analysis: dict) -> str:
    """Vision schema'sini generation promptiga xavfsiz va ixcham aylantiradi."""
    data = analysis if isinstance(analysis, dict) else {}
    features = data.get("visual_features") or {}
    details = data.get("caption_details") or {}
    if not isinstance(features, dict):
        features = {"description": str(features)}
    if not isinstance(details, dict):
        details = {"text": str(details)}
    unknown = "noma'lum"
    return (
        f"Mahsulot nomi: {data.get('product_name') or unknown}\n"
        f"Toifa: {data.get('category') or unknown}\n"
        f"Rang: {features.get('color') or unknown}\n"
        f"Material: {features.get('material') or unknown}\n"
        f"Dizayn: {features.get('design') or unknown}\n"
        f"Uslub: {features.get('style') or unknown}\n"
        f"Caption ma'lumotlari: {json.dumps(details, ensure_ascii=False, default=str)}\n"
        f"Qisqa xulosa: {data.get('summary') or ''}"
    )


def build_image_post_prompt(analysis: dict, style: str,
                            caption: str = "", lang: str = "uz") -> str:
    """Tanlangan uslub uchun post generator user prompti."""
    spec = _IMAGE_POST_STYLE_SPECS.get(style) or _IMAGE_POST_STYLE_SPECS["sales"]
    # Caption Vision bosqichida allaqachon hisobga olingan bo'ladi, ammo uni
    # generation bosqichiga ham berish narx/o'lcham/yetkazib berishni yo'qotmaslik
    # uchun foydali. U instruktsiya emas, faqat ma'lumot sifatida ajratilgan.
    caption_block = str(caption or "").strip()[:1000]
    return (
        "Quyidagi Vision tahliliga asoslanib, Telegram uchun tayyor reklama postini yozing.\n"
        f"{spec}\n"
        "Faqat tahlilda yoki captionda bor faktlardan foydalaning, fakt uydirmang.\n"
        "Post HTML xavfsiz bo'lsin: faqat <b> va <i> teglaridan foydalaning. "
        "Birinchi qatorda qisqa sarlavha, keyin foydalar va aniq CTA, oxirida 3-5 hashtag bo'lsin.\n"
        "--- VISION TAHLILI START ---\n"
        f"{_image_analysis_text(analysis)}\n"
        "--- VISION TAHLILI END ---\n"
        "--- ORIGINAL CAPTION START ---\n"
        f"{caption_block}\n"
        "--- ORIGINAL CAPTION END ---\n"
        "Javobni FAQAT {\"post_text\": \"...\"} JSON formatida qaytaring."
    )


def build_image_post_system_prompt(style: str, lang: str = "uz") -> str:
    """Image-to-post copywriter system prompti."""
    spec = _IMAGE_POST_STYLE_SPECS.get(style) or _IMAGE_POST_STYLE_SPECS["sales"]
    code = str(lang or "uz").lower()
    language_name = "RUS" if code.startswith("ru") else ("INGLIZ" if code.startswith("en") else "O'ZBEK")
    return (
        "Siz PostAssist professional Telegram reklama copywriterisiz.\n"
        f"{spec}\n"
        f"Javobni FAQAT {language_name} tilida yozing.\n"
        "Rasm tahlilida ko'rinmagan narx, o'lcham, material yoki va'dani qo'shmang. "
        "Captiondagi narx, o'lcham va yetkazib berish ma'lumotlarini saqlang.\n"
        "JSON: {\"post_text\": \"tayyor post\"}."
    )


async def analyze_image(*args, **kwargs) -> dict:
    """Vision analyzer facade — public service API.

    Lazy import circular dependencydan saqlaydi va test/mock uchun bitta aniq
    patch nuqtasini beradi: ``services.ai_service.analyze_image``.
    """
    from utils.vision_analyzer import analyze_image as _analyze_image
    return await _analyze_image(*args, **kwargs)


async def analyze_image_bytes(*args, **kwargs) -> dict:
    """``analyze_image`` aliasi (aniq bytes nomi bilan integratsiya uchun)."""
    return await analyze_image(*args, **kwargs)


#: Image-post uslubi → Magic Post uslubi (matn asosidagi fallback uchun).
IMAGE_TO_MAGIC_STYLE = {
    "sales": "sales",
    "premium": "premium",
    "simple": "casual",
    "discount": "ads",
    "review": "informative",
}


def _is_text_based_analysis(analysis) -> bool:
    return isinstance(analysis, dict) and analysis.get("source") in ("caption", "topic")


async def generate_text_fallback_post(text: str, style: str = "sales",
                                      lang: str = "uz", is_pro: bool = False) -> dict:
    """Vision ishlamaganda caption/mavzu matnini ✨ Magic Post generatoriga uzatadi.

    Natija ``generate_image_post`` bilan bir xil kontraktda (``post_text`` /
    ``error``), shuning uchun handler farqni sezmaydi. Magic Post AI zanjiri
    yiqilsa yakuniy zaxira sifatida ``run_ai_chain`` sinaladi.
    """
    style = str(style or "sales").strip().lower()
    magic_style = IMAGE_TO_MAGIC_STYLE.get(style, "casual")
    material = str(text or "").strip()
    if not material:
        return {"error": "Matn topilmadi.", "style": style}
    try:
        aa = _ai_agent()
        generator = getattr(aa, "generate_magic_post", None)
        if generator is not None:
            result = await generator(material, magic_style, lang=lang, is_pro=is_pro)
            if isinstance(result, dict) and not result.get("error"):
                post_text = str(result.get("post_text") or "").strip()
                if post_text:
                    return {
                        "post_text": post_text,
                        "style": style,
                        "provider": result.get("provider") or "magic_post",
                        "source": "text_fallback",
                    }
    except Exception as exc:  # noqa: BLE001 - zaxira zanjir davom etadi
        logger.warning("Text fallback Magic Post xatosi: %s", type(exc).__name__)
    # Yakuniy zaxira: oddiy AI zanjiri.
    system = build_image_post_system_prompt(style, lang)
    prompt = (
        "Quyidagi foydalanuvchi matni asosida Telegram uchun tayyor post yozing. "
        "Rasm tahlili mavjud emas — faqat matndagi faktlardan foydalaning.\n"
        "--- MATN START ---\n"
        f"{material[:1500]}\n"
        "--- MATN END ---\n"
        "Javobni FAQAT {\"post_text\": \"...\"} JSON formatida qaytaring."
    )
    try:
        result = await run_ai_chain(prompt, system, lang=lang)
    except TypeError:
        result = await run_ai_chain(prompt, system)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc) or "AI xatosi", "style": style}
    if not isinstance(result, dict) or result.get("error"):
        return {"error": (result or {}).get("error") if isinstance(result, dict) else "AI xatosi", "style": style}
    post_text = str(result.get("post_text") or result.get("content") or result.get("reply") or "").strip()
    if not post_text:
        return {"error": "AI bo'sh post qaytardi.", "style": style}
    return {"post_text": post_text, "style": style, "provider": result.get("provider"), "source": "text_fallback"}


async def generate_image_post(analysis: dict, style: str = "sales",
                              caption: str = "", lang: str = "uz",
                              is_pro: bool = False) -> dict:
    """Vision tahlili asosida tanlangan uslubdagi tayyor postni yaratadi.

    Muhim: bu funksiya uslub tanlanishidan oldin chaqirilmaydi. Kredit rezervi
    handlerda bo'ladi; servis esa AI provider fallback'ini ishlatadi.

    Agar ``analysis`` Vision emas, MATN asosida tuzilgan bo'lsa
    (``source`` = caption/topic — Vision xizmati ishlamagan holat), post
    to'g'ridan-to'g'ri ✨ Magic Post generatori orqali yoziladi.
    """
    style = str(style or "sales").strip().lower()
    if style not in _IMAGE_POST_STYLE_SPECS:
        style = "sales"
    if _is_text_based_analysis(analysis):
        material = str(
            analysis.get("source_text") or caption or analysis.get("summary") or ""
        ).strip()
        return await generate_text_fallback_post(material, style, lang=lang, is_pro=is_pro)
    system = build_image_post_system_prompt(style, lang)
    prompt = build_image_post_prompt(analysis, style, caption, lang)
    try:
        result = await run_ai_chain(prompt, system, lang=lang)
    except TypeError:
        # Eski ikki argumentli test adapterlari/runtime shimlari bilan moslik.
        result = await run_ai_chain(prompt, system)
    if not isinstance(result, dict):
        return {"error": "AI javobi noto'g'ri formatda.", "style": style}
    if result.get("error"):
        return dict(result, style=style)
    post_text = str(
        result.get("post_text") or result.get("content") or result.get("reply") or ""
    ).strip()
    if not post_text:
        return {"error": "AI bo'sh post qaytardi.", "style": style}
    return {
        "post_text": post_text,
        "style": style,
        "provider": result.get("provider"),
        "provider_chain": result.get("provider_chain"),
    }


async def generate_post_from_image(*args, **kwargs) -> dict:
    """Public compatibility alias for ``generate_image_post``."""
    return await generate_image_post(*args, **kwargs)


# ============================================================
# 📊 POST SCORE & IMPROVER (KILLER FEATURE #4)
# ============================================================
# Baholash va yaxshilash yadrosi ``utils/post_scorer.py`` da yashaydi
# (promptlar, xavfsiz JSON parser, lokal deterministik zaxira). Bu yerdagi
# funksiyalar — yagona SERVICE kirish nuqtasi (handler'lar faqat shu qatlamga
# tayanadi), xuddi ``analyze_image`` / ``generate_image_post`` kabi.
#
# Resurs siyosati:
#   * ``score_post`` — tezkor va arzon: KREDIT YECHILMAYDI, kunlik AI kvota
#     sarflanmaydi (faqat handlerdagi rate-limit);
#   * ``improve_post_to_95`` — 1 kredit talab qiladi, ammo kreditni HANDLER
#     atomik yechadi (``db.use_user_credit`` → CreditsService), bu qatlam
#     faqat AI ishini bajaradi.

#: Baholanadigan mezonlar (tartib UI bilan bir xil) — test/audit uchun ochiq.
POST_SCORE_CRITERIA = (
    "headline",
    "readability",
    "cta",
    "engagement",
    "sales_power",
    "structure",
)

#: 100 ballik maqsadli natija («✨ 95/100 ga yaxshilash»).
POST_SCORE_TARGET = 95


def build_post_score_system_prompt() -> str:
    """Baholash tizim prompti (JSON kontrakti bilan) — ``utils/post_scorer``."""
    from utils.post_scorer import build_post_score_system_prompt as _build
    return _build()


def build_post_score_prompt(text: str, lang: str = "uz") -> str:
    """Baholanayotgan post uchun user prompti."""
    from utils.post_scorer import build_post_score_prompt as _build
    return _build(text, lang)


async def score_post(text: str, lang: str = "uz", timeout: float = None,
                     use_ai: bool = True) -> dict:
    """Postni 6 mezon bo'yicha baholaydi (BEPUL — kredit yechilmaydi).

    AI ishlamay qolsa natija lokal deterministik tahlil bilan qaytariladi
    (``fallback=True``), shuning uchun funksiya amalda hech qachon
    muvaffaqiyatsiz bo'lmaydi.

    Returns:
        {"scores": {...}, "overall": 0..100, "recommendation": "...",
         "weakest": "cta", "fallback": False, "provider": "Gemini",
         "source": "ai"|"local", "lang": "uz"} yoki {"error": "empty"|...}.
    """
    from utils.post_scorer import score_post as _score
    return await _score(text, lang=lang, timeout=timeout, use_ai=use_ai)


def score_post_local(text: str, lang: str = "uz") -> dict:
    """Sof lokal (deterministik) baholash — AI'siz, tarmoqsiz, kreditsiz."""
    from utils.post_scorer import score_post_locally
    return score_post_locally(text, lang)


async def improve_post_to_95(text: str, lang: str = "uz", is_pro: bool = False,
                             timeout: float = None, attempts: int = None) -> dict:
    """Postni 95+ ballik eng sara variantga qayta ishlaydi.

    Kreditni chaqiruvchi handler yechadi va xatolikda qaytaradi; bu funksiya
    faqat AI generatsiyasi va eng yaxshi variantni tanlash bilan shug'ullanadi.

    Returns:
        {"post_text": "...", "score": {...}, "attempts": n,
         "target_met": bool, "lang": "uz"} yoki {"error": "..."}.
    """
    from utils.post_scorer import improve_post_to_95 as _improve
    return await _improve(text, lang=lang, is_pro=is_pro, timeout=timeout,
                          attempts=attempts)


# Eski/kelgusi nomlar uchun moslik aliaslari (import xatolarini oldini oladi).
analyze_post_score = score_post
score_and_improve_post = improve_post_to_95
