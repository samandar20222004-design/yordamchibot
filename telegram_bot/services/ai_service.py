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
#: Kengaytirilgan zaxira (yadro ishlamasa bot umuman to'xtamagan bo'lsin)
EXTENDED_PROVIDER_CHAIN = (
    PROVIDER_MISTRAL,
    PROVIDER_CEREBRAS,
    PROVIDER_SAMBANOVA,
    PROVIDER_CLOUDFLARE,
    PROVIDER_POLLINATIONS,
)

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
    if not raw:
        return CORE_PROVIDER_CHAIN + EXTENDED_PROVIDER_CHAIN
    chain: list[str] = []
    for part in raw.split(","):
        name = _CANONICAL_PROVIDER.get(part.strip().lower())
        if name and name not in chain:
            chain.append(name)
    return tuple(chain) if chain else CORE_PROVIDER_CHAIN + EXTENDED_PROVIDER_CHAIN


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
    """Kalitsiz bepul zaxira — oxirgi chora (API kalit talab qilmaydi)."""

    name = PROVIDER_POLLINATIONS
    tier = 4
    key_attr = None

    def is_available(self) -> bool:
        return True

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

def _graceful_error(errors: list) -> dict:
    """Barcha provayderlar ishlamaganda qaytariladigan toza xato.

    Bu holatda foydalanuvchining kunlik kvotasi yechilmaydi
    (``quota_safe=True`` — handler bal/sanakchini oshirmaydi va
    band qilingan ballini qaytaradi).
    """
    detail = "\n".join(f"• {e}" for e in errors if e)

    # Agar barcha (yoki asosiy) uzilishlar TIMEOUT tufayli bo'lsa — texnik
    # ro'yxat o'rniga foydalanuvchiga xushmuomala, tushunarli xabar beramiz.
    timeout_errors = [e for e in errors if "timeout" in str(e).lower()]
    real_attempts = [e for e in errors if "kalit topilmadi" not in str(e)]
    if timeout_errors and len(timeout_errors) >= max(1, len(real_attempts)):
        logger.warning("Barcha AI provayderlari timeout berdi: %s", detail)
        return {
            "error": _ai_agent().AI_TIMEOUT_USER_MESSAGE,
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
    async def generate(self, prompt: str, system_instruction: str) -> dict:
        """Fallback zanjiri orqali AI javobini qaytaradi.

        Muvaffaqiyatda: provayder JSON dict + ``provider`` /
        ``provider_chain`` maydonlari. Barcha provayderlar yiqilsa:
        graceful xato dict (kvota yechilmaydi).
        """
        aa = _ai_agent()
        prompt = self._prepare_prompt(prompt)
        params = aa.get_runtime_params()

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

        return _graceful_error(errors)

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


async def run_ai_chain(prompt: str, system_instruction: str) -> dict:
    """Yagona AI kirish nuqtasi: promptni avtomatik fallback zanjiridan o'tkazadi.

    ``utils/ai_agent.py::_run_ai_chain`` shu funksiya bilan almashtirilgan —
    barcha mavjud chaqiruvchilar (ai_assistant, content_plan, formatlash,
    kontent-reja, kanal ovozi va h.k.) endi shu yagona orkestratordan ishlaydi.
    """
    return await get_default_service().generate(prompt, system_instruction)
