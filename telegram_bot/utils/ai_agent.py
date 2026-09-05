import asyncio
import base64
import html as _html
import json
import logging
import os
import re
import tempfile
import time as _time
from collections import deque
from datetime import datetime
import pytz
import aiohttp
from config import (
    BOT_TOKEN,
    GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY,
    MISTRAL_API_KEY, CEREBRAS_API_KEY,
    SAMBANOVA_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID,
)

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = os.getenv("GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
GEMINI_BASE = os.getenv("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta/models")
OPENROUTER_ENDPOINT = os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
MISTRAL_ENDPOINT = os.getenv("MISTRAL_ENDPOINT", "https://api.mistral.ai/v1/chat/completions")
CEREBRAS_ENDPOINT = os.getenv("CEREBRAS_ENDPOINT", "https://api.cerebras.ai/v1/chat/completions")
# SambaNova Cloud (OpenAI-mos) — RDU chiplarida tez inference
SAMBANOVA_ENDPOINT = os.getenv("SAMBANOVA_ENDPOINT", "https://api.sambanova.ai/v1/chat/completions")
# Cloudflare Workers AI (OpenAI-mos) — account_id URL ichida ketadi,
# shuning uchun endpoint shu yerda yig'iladi (env bilan to'liq almashtirish mumkin).
CLOUDFLARE_ENDPOINT = os.getenv(
    "CLOUDFLARE_ENDPOINT",
    f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions",
)
# Kalitsiz bepul zaxira (Pollinations) — oxirgi chora sifatida
POLLINATIONS_ENDPOINT = os.getenv("POLLINATIONS_ENDPOINT", "https://text.pollinations.ai/openai")

# Model ro'yxati endpointlari (discovery uchun)
GROQ_MODELS_ENDPOINT = os.getenv("GROQ_MODELS_ENDPOINT", GROQ_ENDPOINT.replace("/chat/completions", "/models"))
GEMINI_MODELS_ENDPOINT = os.getenv("GEMINI_MODELS_ENDPOINT", GEMINI_BASE)
OPENROUTER_MODELS_ENDPOINT = os.getenv("OPENROUTER_MODELS_ENDPOINT", "https://openrouter.ai/api/v1/models")

# Timeout sozlamalari:
# - connect: birinchi ulanish uchun
# - sock_read: javob oqimini o'qish uchun (sekin modellar ham shu muddat ichida kelishi kerak)
# Eskirgan sozlama (orqaga moslik uchun saqlanadi) — amaldagi chegara
# AI_TOTAL_TIMEOUT / AI_HTTP_TIMEOUT tomonidan belgilanadi.
REQUEST_TIMEOUT = max(30, int(os.getenv("AI_REQUEST_TIMEOUT", "45")))
CONNECT_TIMEOUT = max(5, int(os.getenv("AI_CONNECT_TIMEOUT", "10")))

# 🛡 TASHQI AI SO'ROVLARI UCHUN QAT'IY TIMEOUT (soniya).
# HAR BIR tashqi HTTP so'rovi (Gemini / Groq / OpenRouter / Mistral /
# Cerebras / SambaNova / Cloudflare / Pollinations + model discovery) shu
# ClientTimeout bilan yuboriladi. Bitta osilib qolgan provayder butun
# bot event-loopini yoki foydalanuvchi sessiyasini bloklab qo'ymaydi.
AI_TOTAL_TIMEOUT = max(5, int(os.getenv("AI_TOTAL_TIMEOUT", "35")))
MAX_429_RETRIES = 2

# Foydalanuvchi promptining maksimal uzunligi (token byudjetini himoya qiladi)
MAX_PROMPT_CHARS = max(500, int(os.getenv("AI_MAX_PROMPT_CHARS", "3000")))
# Bir vaqtda ko'pi bilan 2 ta AI so'rovi ishlaydi (bepul RPM limitlarini himoya qiladi)
MAX_CONCURRENT_AI = max(1, int(os.getenv("MAX_CONCURRENT_AI", "2")))
# Provayder 3 marta ketma-ket xato bersa — shuncha daqiqaga o'tkazib yuboriladi
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 600  # 10 daqiqa
# AI chaqiruvlarining QAT'IY umumiy muddati (soniya): butun provayder zanjiri
# shu vaqt ichida javob berishi shart — aks holda asyncio.wait_for bekor qiladi.
# Har bir alohida HTTP urinish uchun AI_HTTP_TIMEOUT (total=35s) alohida ishlaydi.
AI_HARD_TIMEOUT = max(5.0, float(os.getenv("AI_HARD_TIMEOUT", "25")))

# === AI parametr defaultlari ===
AI_TEMPERATURE = max(0.0, min(2.0, float(os.getenv("AI_TEMPERATURE", "0.7"))))
AI_MAX_TOKENS = max(128, int(os.getenv("AI_MAX_TOKENS", "2048")))
AI_TOP_P = max(0.0, min(1.0, float(os.getenv("AI_TOP_P", "0.95"))))
AI_CONTEXT_MESSAGES = max(0, int(os.getenv("AI_CONTEXT_MESSAGES", "6")))
AI_MAX_CONTEXT_CHARS = max(500, int(os.getenv("AI_MAX_CONTEXT_CHARS", "4000")))
AI_EXTRA_CONTEXT = os.getenv("AI_EXTRA_CONTEXT", "").strip()

# Runtime'da o'zgaradigan AI parametrlar. Admin panel ularni DB'dan o'qib,
# ai_agent.reload_runtime_params() bilan shu yerda yangilaydi — bot qayta
# ishga tushirilmasa ham darhol kuchga kiradi.
_RUNTIME_PARAMS = {
    "temperature": AI_TEMPERATURE,
    "max_tokens": AI_MAX_TOKENS,
    "top_p": AI_TOP_P,
    "max_prompt_chars": MAX_PROMPT_CHARS,
    "context_messages": AI_CONTEXT_MESSAGES,
    "context_chars": AI_MAX_CONTEXT_CHARS,
    "extra_context": AI_EXTRA_CONTEXT,
}
# Admin "reset" qilganda / qiymat bo'sh bo'lganda qaytadigan defaultlar.
_RUNTIME_DEFAULTS = dict(_RUNTIME_PARAMS)

# Ixtiyoriy (o'chirib qo'yish mumkin bo'lgan) parametrlar. Admin ularni
# "off"/"none"/"-" deb belgilasa, so'rov payload'iga UMUMAN qo'shilmaydi —
# ba'zi provayderlar `null` qiymatga 400 xatosi qaytaradi.
_OPTIONAL_PARAMS = ("max_tokens", "top_p", "temperature")
_UNSET_WORDS = ("off", "none", "null", "-", "yo'q", "yoq", "o'chir", "ochir")


def _optional_param(params: dict, key: str):
    """Ixtiyoriy parametr qiymati; o'chirilgan (None) bo'lsa — None."""
    value = (params or {}).get(key, _RUNTIME_DEFAULTS.get(key))
    return value


def _apply_optional_params(payload: dict, params: dict, keys=_OPTIONAL_PARAMS) -> dict:
    """`None` bo'lmagan parametrlarnigina payload'ga qo'shadi (null yubormaydi)."""
    for key in keys:
        value = _optional_param(params, key)
        if value is not None:
            payload[key] = value
    return payload


# Har bir foydalanuvchi uchun so'nggi AI suhbati konteksti (qisqa).
# Bu "qisqartir", "vaqtni o'zgartir", "oxiriga qo'sh" kabi ergash buyruqlarda
# modelga oldingi xabar mazmunini eslatish uchun ishlatiladi.
_AI_CONTEXT: dict = {}
_AI_CONTEXT_MAX_USERS = 5000

# Modellarni runtime'da aniqlash (yoqilgan bo'lsa). Provayderlar modellarni
# tez-tez almashtiradi (decommission), shuning uchun qo'lda yozilgan ro'yxat
# doim eskirib qoladi. Discovery buni avtomatik hal qiladi.
AI_MODEL_DISCOVERY = os.getenv("AI_MODEL_DISCOVERY", "1") == "1"
MODEL_CACHE_TTL = 6 * 3600  # aniqlangan ro'yxat 6 soat eslab qolinadi

# === Afzal (preferred) modellar — yuqori sifat uchun ===
# Birinchi model eng muhim (asosiy), qolganlar zaxira.
# Gemini: gemini-2.5-flash — hozirgi barqaror (GA) model, rasm kirishini
# qo'llab-quvvatlaydi va o'zbek tilini yaxshi tushunadi.
GEMINI_PREFERRED = [
    "gemini-2.5-flash",           # 1M kontekst, eng kuchli barqaror model
    "gemini-flash-latest",        # Flash'ning doim yangilanib turadigan aliasi
    "gemini-2.5-flash-lite",      # Tez va arzon
    "gemini-2.5-pro",             # Pro versiya (limit bor, lekin sifat yuqori)
    "gemini-flash-lite-latest",   # Flash-Lite aliasi (zaxira)
]

# === Google O'CHIRIB QO'YGAN (retired) modellar ===
# Bunday modelga so'rov yuborilsa API 404 qaytaradi va foydalanuvchi
# "modeli mavjud emas" xatosini ko'radi. Shu sababli ular ro'yxatlardan
# avtomatik chiqarib tashlanadi (admin GEMINI_VISION_MODEL bilan qo'lda
# belgilamaguncha).
#   • gemini-1.5-* → 2025-09-29 da o'chirildi
#   • gemini-2.0-flash / -lite → 2026-06-01 da o'chirildi
GEMINI_RETIRED = frozenset({
    "gemini-1.5-flash", "gemini-1.5-flash-001", "gemini-1.5-flash-002",
    "gemini-1.5-flash-8b", "gemini-1.5-flash-8b-001", "gemini-1.5-flash-latest",
    "gemini-1.5-pro", "gemini-1.5-pro-001", "gemini-1.5-pro-002",
    "gemini-1.5-pro-latest", "gemini-pro", "gemini-pro-vision",
    "gemini-1.0-pro", "gemini-1.0-pro-vision-latest",
    "gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001", "gemini-2.0-flash-thinking-exp",
    "gemini-2.0-flash-thinking-exp-1219", "gemini-2.0-flash-exp",
})


def _is_retired_gemini(model: str) -> bool:
    """Model Google tomonidan o'chirilganmi (404 qaytaradimi)?"""
    return (model or "").strip().lower() in GEMINI_RETIRED
# Groq: Llama 3.3 70B (eng kuchli, tez va aniq), LLaMA 4 va gemma modellari
GROQ_PREFERRED = [
    "llama-3.3-70b-versatile",                    # Llama 3.3 70B — eng sifatli va bepul
    "llama3-70b-8192",                            # Llama 3 70B tezkor
    "meta-llama/llama-4-scout-17b-16e-instruct",  # LLaMA 4
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "gemma2-9b-it",                               # Kichik va tez
    "llama3-8b-8192",                             # Zaxira
]
# OpenRouter: bepul (:free) kuchli modellar
OPENROUTER_PREFERRED = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-4-scout:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-14b:free",
    "mistralai/mistral-7b-instruct:free",
]
MISTRAL_PREFERRED = [
    "mistral-small-latest",    # Bepul tier, ko'p tilli
    "open-mistral-nemo",       # 128k kontekst
    "ministral-8b-latest",
]
CEREBRAS_PREFERRED = [
    "llama-3.3-70b",           # Eng tez inference (Cerebras chip)
    "llama3.1-70b",
    "llama3.1-8b",
]
# SambaNova Cloud: katta ochiq modellar (RDU'da tez ishlaydi)
SAMBANOVA_PREFERRED = [
    "Meta-Llama-3.3-70B-Instruct",          # Eng barqaror, ko'p tilli
    "Qwen3-32B",                            # Yangi avlod, sifatli
    "Llama-4-Maverick-17B-128E-Instruct",   # Katta MoE model
    "DeepSeek-V3-0324",                     # Zaxira (kuchli, lekin sekinroq)
    "Meta-Llama-3.1-8B-Instruct",           # Eng tez zaxira
]
# Cloudflare Workers AI: model id'lari '@cf/...' ko'rinishida bo'ladi
CLOUDFLARE_PREFERRED = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",   # fp8 — tez va arzon
    "@cf/meta/llama-4-scout-17b-16e-instruct",    # LLaMA 4 (kontekst katta)
    "@cf/meta/llama-3.1-8b-instruct",             # Eng tez zaxira
    "@cf/mistral/mistral-7b-instruct-v0.1",
    "@cf/qwen/qwq-32b",                           # Zaxira
]

# Discovery ishlamasa ishlatiladigan zaxira ro'yxatlar
GEMINI_MODELS = list(GEMINI_PREFERRED)
GROQ_MODELS = list(GROQ_PREFERRED)
OPENROUTER_MODELS = list(OPENROUTER_PREFERRED)
MISTRAL_MODELS = list(MISTRAL_PREFERRED)
CEREBRAS_MODELS = list(CEREBRAS_PREFERRED)
SAMBANOVA_MODELS = list(SAMBANOVA_PREFERRED)
CLOUDFLARE_MODELS = list(CLOUDFLARE_PREFERRED)

# === Bitta umumiy aiohttp sessiya (singleton) ===
# Har so'rovda yangi sessiya ochish +300-800ms kechikish va TCP socket isrof qiladi.
# Singleton: ulanish qayta ishlatiladi, DNS keshlanadi, TCP handshake bir marta bo'ladi.
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()

# 🛡 Har bir tashqi AI so'rovi uchun QAT'IY timeout (total=35s).
# Sessiya darajasidagi umumiy timeout yetarli emas: `session.post(...)` ga
# aniq `timeout=` berilmasa, sessiya sozlamasi o'zgartirilib qolsa yoki
# mock/test sessiyasi ishlatilsa chegara yo'qolishi mumkin. Shu sababli
# TIMEOUT HAR BIR SO'ROVGA ALOHIDA uzatiladi.
AI_HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=AI_TOTAL_TIMEOUT,
    connect=CONNECT_TIMEOUT,
    sock_connect=CONNECT_TIMEOUT,
    sock_read=AI_TOTAL_TIMEOUT,
)

# Model discovery — yordamchi so'rov, javobi tez kelishi kerak.
AI_DISCOVERY_TIMEOUT = aiohttp.ClientTimeout(
    total=min(15, AI_TOTAL_TIMEOUT),
    connect=CONNECT_TIMEOUT,
)

# Telegram'dan media yuklab olish (AI so'rovi emas — katta fayl oqimi).
MEDIA_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(
    total=max(60, AI_TOTAL_TIMEOUT),
    connect=CONNECT_TIMEOUT,
)

#: Timeout yuz berganda foydalanuvchiga ko'rsatiladigan XUSHMUOMALA xabar.
AI_TIMEOUT_USER_MESSAGE = (
    "⏳ <b>AI xizmati hozir javob bermayapti.</b>\n\n"
    f"So'rov {AI_TOTAL_TIMEOUT} soniyada yakunlanmadi — ehtimol server band yoki "
    "internet aloqasi sekinlashgan.\n\n"
    "Iltimos, bir daqiqadan so'ng qayta urinib ko'ring. "
    "Matningiz saqlanib qoldi. 🙏"
)


def ai_timeout_message(lang: str = "uz") -> str:
    """Timeout uchun foydalanuvchi tilidagi xushmuomala xabar (uz/ru)."""
    if str(lang or "").lower().startswith("ru"):
        return (
            "⏳ <b>Сервис ИИ сейчас не отвечает.</b>\n\n"
            f"Запрос не завершился за {AI_TOTAL_TIMEOUT} секунд — возможно, сервер "
            "загружен или соединение медленное.\n\n"
            "Пожалуйста, попробуйте ещё раз через минуту. "
            "Ваш текст сохранён. 🙏"
        )
    return AI_TIMEOUT_USER_MESSAGE


# Discovery natijalari keshida: key -> (timestamp, [model_id, ...])
_model_cache: dict = {}

# Circuit breaker: provider_name -> {"fails": int, "until": float}
_BREAKERS: dict = {}

# Bir vaqtda 2 tadan ortiq AI so'rovi ishlamasligi uchun semafor
_AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI)


async def _get_session() -> aiohttp.ClientSession:
    """Singleton aiohttp sessiyasi — har so'rovda yangi sessiya ochilmaydi.

    Sessiya darajasidagi timeout ``AI_HTTP_TIMEOUT`` (total=35s) bo'ladi;
    bundan tashqari har bir so'rov ham aniq ``timeout=`` bilan yuboriladi.
    """
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                connector = aiohttp.TCPConnector(
                    limit=20,           # maksimal parallel ulanishlar
                    ttl_dns_cache=300,  # DNS keshi — har so'rovda DNS so'rovi yo'q
                    enable_cleanup_closed=True,
                )
                _session = aiohttp.ClientSession(
                    timeout=AI_HTTP_TIMEOUT,
                    connector=connector,
                    headers={"User-Agent": "PostAssistBot/2.0"},
                )
    return _session


async def close_ai_session():
    """Bot to'xtatilganda AI sessiyasini yopish."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


# ---------------- Runtime AI parametrlar ----------------

def get_runtime_params() -> dict:
    """Hozirgi AI parametrlar nusxasini qaytaradi."""
    return dict(_RUNTIME_PARAMS)


def _set_runtime_param(key: str, raw_value) -> bool:
    """``raw_value`` str berilgan key validatsiya bilan queyamiz.

    True qaytsa qiymat qo'yildi, False — noma'lum kalit yoki noto'g'ri qiymat.
    """
    key = (key or "").strip().lower()
    raw = (raw_value or "").strip()
    if key not in _RUNTIME_PARAMS:
        return False
    if not raw:
        _RUNTIME_PARAMS[key] = _RUNTIME_DEFAULTS.get(key)
        return True
    # Ixtiyoriy parametrlarni butunlay o'chirish (provayderga umuman yuborilmaydi).
    if key in _OPTIONAL_PARAMS and raw.lower() in _UNSET_WORDS:
        _RUNTIME_PARAMS[key] = None
        return True
    try:
        if key == "temperature":
            _RUNTIME_PARAMS[key] = max(0.0, min(2.0, float(raw)))
        elif key == "max_tokens":
            _RUNTIME_PARAMS[key] = max(128, int(raw))
        elif key == "top_p":
            _RUNTIME_PARAMS[key] = max(0.0, min(1.0, float(raw)))
        elif key == "max_prompt_chars":
            _RUNTIME_PARAMS[key] = max(500, int(raw))
        elif key == "context_chars":
            _RUNTIME_PARAMS[key] = max(500, int(raw))
        elif key == "context_messages":
            _RUNTIME_PARAMS[key] = max(0, int(raw))
        else:
            _RUNTIME_PARAMS[key] = raw
        return True
    except (TypeError, ValueError):
        logger.warning("AI parametr noto'g'ri: %s=%r", key, raw)
        return False


_SETTINGS_TO_PARAMS = {
    "ai_temperature": "temperature",
    "ai_max_tokens": "max_tokens",
    "ai_top_p": "top_p",
    "ai_max_prompt_chars": "max_prompt_chars",
    "ai_context_chars": "context_chars",
    "ai_context_messages": "context_messages",
    "ai_extra_context": "extra_context",
}


def load_runtime_params_from_db():
    """DB'dagi admin sozlamalarini runtime paramlarga yuklaydi.

    This is synchronous (DB keshli o'qish) — main bot startida `to_thread`
    bilan ichidan chaqiriladi yoki admin o'zgarishidan keyin.
    """
    from database import get_setting
    for setting_key, param_key in _SETTINGS_TO_PARAMS.items():
        value = get_setting(setting_key, "")
        _set_runtime_param(param_key, value)


async def reload_runtime_params():
    """AI parametrlarni DB'dan qayta yuklash (async wrapper)."""
    await asyncio.to_thread(load_runtime_params_from_db)


# ---------------- Qisqa suhbat konteksti ----------------

_HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
# Kontekstda saqlanadigan bitta xabarning maksimal uzunligi
_CONTEXT_ENTRY_MAX_CHARS = 1000


def clear_ai_context(user_id: int):
    """Yangi AI sessiyada u/agar so'ralsa, suhbat kontekstini tozalash."""
    if user_id is not None:
        _AI_CONTEXT.pop(user_id, None)


def _plain_text(text: str) -> str:
    """Kontekstga HTML teglari tushmasligi uchun tozalaydi.

    Model bilan suhbat tarixida <b>, <i>, <code> kabi teglar faqat tokenni
    yeydi va javob sifatini pasaytiradi — shuning uchun olib tashlanadi.
    """
    if not text:
        return ""
    cleaned = _HTML_TAG_RE.sub("", str(text))
    cleaned = _html.unescape(cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def _context_limit() -> int:
    return int(_RUNTIME_PARAMS.get("context_messages", 0) or 0)


def _store_ai_context(user_id: int, text: str, role: str = "user"):
    """Suhbat tarixiga bitta xabar qo'shadi.

    ``role`` — "user" (foydalanuvchi) yoki "bot" (AI javobi). Bot javoblari ham
    saqlanadi, aks holda "qisqartir", "oxiriga qo'sh" kabi ergash buyruqlarda
    model o'zi nima yozganini bilmay qoladi.
    """
    if not user_id:
        return
    max_len = _context_limit()
    if max_len <= 0:
        return
    text = _plain_text(text)
    if not text:
        return
    # Xotirani cheklash: har bitta eslatilgan xabarni qisqartiramiz
    text = text[:_CONTEXT_ENTRY_MAX_CHARS]
    label = "Bot" if role == "bot" else "Foydalanuvchi"
    entry = f"{label}: {text}"
    if len(_AI_CONTEXT) > _AI_CONTEXT_MAX_USERS:
        # Qadimgi foydalanuvchilardan tozalash
        for uid in list(_AI_CONTEXT.keys())[:_AI_CONTEXT_MAX_USERS // 10]:
            _AI_CONTEXT.pop(uid, None)
    entries = _AI_CONTEXT.get(user_id)
    if entries is None or entries.maxlen != max_len:
        # context_messages admin tomonidan o'zgargan bo'lsa — deque'ni moslaymiz
        old = list(entries) if entries else []
        entries = deque(old[-max_len:], maxlen=max_len)
        _AI_CONTEXT[user_id] = entries
    if not entries or entries[-1] != entry:
        entries.append(entry)


def _get_ai_context_text(user_id: int, budget: int) -> str:
    """So'nggi xabarlarni budget belgidan oshirmasdan qaytaradi.

    Byudjet ``context_chars`` admin sozlamasi bilan ham cheklanadi va eng
    so'nggi xabarlar ustuvor bo'ladi (eskilari sig'masa tushib qoladi).
    """
    if _context_limit() <= 0:
        return ""
    entries = _AI_CONTEXT.get(user_id)
    if not entries:
        return ""
    ctx_chars = int(_RUNTIME_PARAMS.get("context_chars") or AI_MAX_CONTEXT_CHARS)
    budget = min(int(budget or 0), ctx_chars)
    if budget <= 0:
        return ""

    header = "So'nggi suhbat (AI konteksti):"
    lines = []
    used = len(header)
    # Oxirgi xabardan boshlab to'ldiramiz — eng muhim (yangi) kontekst saqlanadi
    for entry in reversed(list(entries)):
        line = f"- {entry}"
        if used + len(line) + 1 > budget:
            continue
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    lines.reverse()
    return header + "\n" + "\n".join(lines)


# ---------------- Circuit breaker ----------------

def _breaker_open(name: str) -> bool:
    entry = _BREAKERS.get(name)
    # until=0 → cooldown yo'q (ochiq emas); faqat kelajakdagi vaqt bo'lsa ochiq
    return bool(entry and entry.get("until") and _time.time() < entry["until"])


def _breaker_fail(name: str):
    now = _time.time()
    entry = _BREAKERS.get(name)
    if entry is None:
        _BREAKERS[name] = {"fails": 1, "until": 0}
        return
    if entry.get("until") and now > entry["until"]:
        # Cooldown tugagan — qaytadan hisoblashni boshlaymiz
        _BREAKERS[name] = {"fails": 1, "until": 0}
        return
    entry["fails"] = entry.get("fails", 0) + 1
    if entry["fails"] >= BREAKER_THRESHOLD:
        entry["until"] = now + BREAKER_COOLDOWN
        entry["fails"] = 0
        logger.warning("Provayder %s %ds ga o'tkazib yuborildi (3 marta ketma-ket xato)",
                       name, BREAKER_COOLDOWN)


def _breaker_success(name: str):
    _BREAKERS.pop(name, None)


# ---------------- Model discovery ----------------

def _cached_models(key: str):
    entry = _model_cache.get(key)
    if entry and _time.time() - entry[0] < MODEL_CACHE_TTL:
        return entry[1]
    return None


def _set_cached_models(key: str, models: list):
    _model_cache[key] = (_time.time(), models)


def _pick_models(available: list, preferred: list, chat_only: bool = False) -> list | None:
    """Mavjud modellardan afzal ro'yxat bo'yicha tanlab oladi.

    Google o'chirib qo'ygan (404 qaytaradigan) modellar hech qachon
    tanlanmaydi. chat_only=True bo'lsa, chat uchun yaroqsiz modellar (audio,
    guard va h.k.) filtrlangan holda afzal ro'yxatga kirmagan faol modellar
    ham qo'shiladi.
    """
    avail_set = set(available)
    picked = [
        m for m in preferred
        if m in avail_set and not _is_retired_gemini(m)
    ]
    if chat_only:
        for m in available:
            if len(picked) >= 6:
                break
            if m in picked or _is_retired_gemini(m):
                continue
            low = m.lower()
            if any(x in low for x in (
                "whisper", "audio", "tts", "embedding", "rerank",
                "guard", "safeguard", "image", "vision", "speech",
            )):
                continue
            picked.append(m)
    return picked or None


async def _discover_gemini_models(api_key: str) -> list | None:
    """Gemini'ning jonli model ro'yxatini oladi (generateContent qo'llab-quvvatlanadiganlar)."""
    if not AI_MODEL_DISCOVERY:
        return None
    cached = _cached_models("gemini")
    if cached:
        return cached
    session = await _get_session()
    try:
        async with session.get(
            f"{GEMINI_MODELS_ENDPOINT}?key={api_key}", timeout=AI_DISCOVERY_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        available = []
        for m in data.get("models", []):
            name = m.get("name", "")
            methods = m.get("supportedGenerationMethods", [])
            if name.startswith("models/") and "generateContent" in methods:
                available.append(name[len("models/"):])
        picked = _pick_models(available, GEMINI_PREFERRED)
        if picked:
            _set_cached_models("gemini", picked)
            logger.info("Gemini modellari aniqlandi: %s", picked)
            return picked
    except Exception as e:
        logger.warning("Gemini model discovery xatosi: %s", e)
    return None


async def _discover_groq_models(api_key: str) -> list | None:
    """Groq'ning jonli model ro'yxatini oladi (chat modellari)."""
    if not AI_MODEL_DISCOVERY:
        return None
    cached = _cached_models("groq")
    if cached:
        return cached
    session = await _get_session()
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        async with session.get(
            GROQ_MODELS_ENDPOINT, headers=headers, timeout=AI_DISCOVERY_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        available = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        picked = _pick_models(available, GROQ_PREFERRED, chat_only=True)
        if picked:
            _set_cached_models("groq", picked)
            logger.info("Groq modellari aniqlandi: %s", picked)
            return picked
    except Exception as e:
        logger.warning("Groq model discovery xatosi: %s", e)
    return None


async def _discover_openrouter_models(api_key: str) -> list | None:
    if not AI_MODEL_DISCOVERY:
        return None
    cached = _cached_models("openrouter")
    if cached:
        return cached
    session = await _get_session()
    try:
        async with session.get(
            OPENROUTER_MODELS_ENDPOINT, timeout=AI_DISCOVERY_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
        free_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id", "").endswith(":free")]
        picked = _pick_models(free_ids, OPENROUTER_PREFERRED)
        if picked:
            _set_cached_models("openrouter", picked)
            logger.info("OpenRouter modellari aniqlandi: %s", picked)
            return picked
    except Exception as e:
        logger.warning("OpenRouter model discovery xatosi: %s", e)
    return None


# ---------------- JSON yordamchilari ----------------

def _clean_json_string(raw_str: str) -> str:
    """Markdown JSON bloklarini tozalash."""
    raw_str = raw_str.strip()
    if raw_str.startswith("```json"):
        raw_str = raw_str[7:]
    elif raw_str.startswith("```"):
        raw_str = raw_str[3:]
    if raw_str.endswith("```"):
        raw_str = raw_str[:-3]
    return raw_str.strip()


def _extract_json(text: str) -> dict:
    """AI javobidan JSON obyektni ishonchli ajratib olish.

    Ba'zi modellar JSON atrofiga matn qo'shib yuboradi — eng birinchi '{'
    va eng oxirgi '}' oralig'ini olamiz.
    """
    cleaned = _clean_json_string(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Javobda JSON obyekti topilmadi")
    return json.loads(cleaned[start:end + 1])


def _get_router_system_instruction() -> str:
    """Intent routing: har qanday xabarni 3 yo'nalishdan biriga ajratadi.

    Sifat oshirildi:
    - O'zbek tili uchun aniq ko'rsatmalar va uslub talablari
    - Post yaratishda professional, jozibador til talab qilinadi
    - Kontekst (avvalgi xabarlar) to'g'ri ishlatiladi
    """
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year
    current_day = now_dt.strftime("%A")  # hafta kuni

    extra = (_RUNTIME_PARAMS.get("extra_context") or "").strip()
    extra_block = f"\n\nQo'shimcha ko'rsatma: {extra}" if extra else ""
    return (
        f"Siz PostAssist — professional Telegram kanallar boshqaruvchisi va post muharriri botisiz.\n"
        f"Hozirgi vaqt: {now_str} (Toshkent, UTC+5), {current_day}, {current_year}-yil.{extra_block}\n\n"
        f"TIL VA USLUB TALABLARI (juda muhim):\n"
        f"• Barcha javoblar O'ZBEK tilida bo'lishi SHART. Ruscha, inglizcha aralashtirilmasin.\n"
        f"• Post yaratishda: jonli, jozibador, emotsional O'zbek tili ishlating.\n"
        f"• Emoji'lardan oqilona foydalaning (har gapga emas, asosiy nuqtalarga).\n"
        f"• Telegram HTML formatlash: <b>qalin</b>, <i>kursiv</i>, <code>kod</code>.\n"
        f"• Post matni kamida 3-5 qator, mazmunan to'liq bo'lsin.\n\n"
        f"Vazifangiz — foydalanuvchining xabarini tahlil qilib, UNING NIYATINI aniqlash. "
        f"Javobni FAQAT bitta JSON obyekti sifatida qaytaring. Niyat turlari:\n\n"
        f'1) "faq" — SAVOL-JAVOB / SUHBAT:\n'
        f"   • Bot imkoniyatlari, post rejalashtirish, ballar, kanal ulash, reaksiyalar, "
        f"avto-o'chirish, kunlik bonus haqida savol bo'lsa — aniq, foydali, do'stona javob bering.\n"
        f"   • Salomlashsa — iliq javob bering va yordam taklif qiling.\n"
        f"   • Mavzu botga mutlaqo aloqasiz bo'lsa — qisqa, muloyim rad qiling va postga o'tishni taklif qiling.\n"
        f"   • Javobni 'reply' maydoniga yozing. HTML formatlash mumkin.\n\n"
        f'2) "post" — YANGI POST YARATISH yoki TAYYOR POST QABUL QILISH:\n'
        f"   • Mavzu/sarlavha berilsa — PROFESSIONAL, JOZIBADOR, TO'LIQ post tayyorlang.\n"
        f"     Aniq faktlar, chaqiriq (CTA), kerakli hashtaglar qo'shing.\n"
        f"   • Tayyor post/forward/e'lon yuborilsa — matnni BUZMASDAN, to'liq ko'chiring.\n"
        f"   • Vaqt ko'rsatilsa ('bugun 15:45', 'ertaga 9 da') — Toshkent bo'yicha 'YYYY-MM-DD HH:MM' da yozing.\n"
        f"   • 'Barcha kanallarga' deyilsa — target_all: true.\n\n"
        f'3) "edit" — MAVJUD POSTNI TAHRIRLASH:\n'
        f"   • Foydalanuvchi oldingi postni o'zgartirishni so'rasa — TAHRIRLANGAN to'liq postni yozing.\n"
        f"   • Faqat so'ralgan o'zgarishni qiling, qolganini saqlab qoldiring.\n\n"
        f"MUHIM QOIDALAR:\n"
        f"• Vaqt hisobini FAQAT Toshkent vaqti (UTC+5) bo'yicha qiling.\n"
        f"• JSON dan boshqa hech narsa yozmang. Toza JSON formati:\n"
        f"{{\n"
        f'  "intent": "faq | post | edit",\n'
        f'  "reply": "faq niyatida to\'liq, HTML formatlangan javob (boshqa hollarda bo\'sh satr)",\n'
        f'  "post_text": "post/edit niyatida tayyor post matni (faqat post matni, boshqa narsa yo\'q)",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "has_explicit_time": false,\n'
        f'  "target_all": false\n'
        f"}}"
    )


def _get_time_system_instruction() -> str:
    """Yengil rejim: faqat erkin tildagi vaqtni yoki savolni ajratadi."""
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year
    return (
        f"Siz Telegram post rejalashtiruvchi botning yordamchisisiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, joriy yil: {current_year}.\n\n"
        f"Foydalanuvchining xabarini tahlil qiling va FAQAT bitta JSON qaytaring:\n"
        f"• Agar xabarda post chiqish VAQTI ko'rsatilgan bo'lsa (masalan: '15:45 ga', 'ertaga "
        f"ertalab 9 da', 'bugun kechqurun 20:00', '1 soatdan keyin', '5 daqiqadan keyin', "
        f"'2-sentyabr 10:00') — vaqtni Toshkent vaqti bo'yicha hisoblab 'YYYY-MM-DD HH:MM' "
        f'formatida "scheduled_time" ga yozing, "has_explicit_time": true.\n'
        f"• Agar xabar vaqt emas, balki savol yoki boshqa gap bo'lsa — "
        f'"has_explicit_time": false, "scheduled_time": null, "reply" maydoniga qisqa, '
        f"muloyim O'ZBEK tilida javob yozing.\n"
        f"• 'Barcha kanallarga' deyilgan bo'lsa \"target_all\": true.\n\n"
        f"JSON formati:\n"
        f"{{\n"
        f'  "intent": "faq | post",\n'
        f'  "reply": "savol bo\'lsa O\'zbek tilida javob, aks holda bo\'sh satr",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "has_explicit_time": false,\n'
        f'  "target_all": false\n'
        f"}}"
    )


def _retry_after_seconds(resp: aiohttp.ClientResponse, fallback: float = 3.0) -> float:
    """429 javobidagi Retry-After vaqtini o'qish (1–10 soniya oralig'ida)."""
    try:
        raw = resp.headers.get("Retry-After")
        if raw:
            return min(max(float(raw), 1.0), 10.0)
    except (TypeError, ValueError):
        pass
    return fallback


class ProviderError(RuntimeError):
    """Provayder xatosi — status kodi va matni bilan (model almashtirish uchun)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def _post_chat_completion(endpoint: str, headers: dict | None, payload: dict) -> dict:
    """OpenAI-compatible chat/completions so'rovini 429-retry bilan yuborish.

    Muvaffaqiyatda: {"content": "..."} qaytaradi.
    Muvaffaqiyatsizda: ProviderError(status, matn) tashlaydi.
    """
    session = await _get_session()

    for attempt in range(MAX_429_RETRIES + 1):
        try:
            async with session.post(
                endpoint, headers=headers, json=payload, timeout=AI_HTTP_TIMEOUT
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        raise ProviderError(200, "Bo'sh javob")
                    return {"content": content}
                if resp.status == 429 and attempt < MAX_429_RETRIES:
                    wait = _retry_after_seconds(resp)
                    logger.warning("AI rate-limit (429); %ss dan keyin qayta uriniladi", wait)
                    await asyncio.sleep(wait)
                    continue
                # 429'dan boshqa barcha holatlar (400, 404, 500...) darhol xato
                resp_txt = await resp.text()
                raise ProviderError(resp.status, resp_txt[:200] or f"HTTP {resp.status}")
        except asyncio.TimeoutError:
            raise ProviderError(0, "timeout")
        except aiohttp.ClientError as e:
            raise ProviderError(0, str(e)[:200])
        except KeyError:
            raise ProviderError(0, "javob formati noto'g'ri (choices topilmadi)")
        except ProviderError:
            raise


async def _call_gemini(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    session = await _get_session()
    models = await _discover_gemini_models(api_key) or GEMINI_MODELS
    params = params or get_runtime_params()
    last_err = ""

    for model in models:
        url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
        # Faqat o'chirilmagan (None bo'lmagan) parametrlar yuboriladi —
        # `null` qiymat ba'zi provayderlarda 400 xatosiga olib keladi.
        generation_config = {}
        _gem_temp = _optional_param(params, "temperature")
        if _gem_temp is not None:
            generation_config["temperature"] = _gem_temp
        _gem_top_p = _optional_param(params, "top_p")
        if _gem_top_p is not None:
            generation_config["topP"] = _gem_top_p
        _gem_max_tokens = _optional_param(params, "max_tokens")
        if _gem_max_tokens is not None:
            generation_config["maxOutputTokens"] = _gem_max_tokens

        # Gemini API: system instruction alohida, content foydalanuvchi matni
        payload = {
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{prompt}\n\nJavobni FAQAT toza JSON formatida yozing."}]
                }
            ],
            "generationConfig": generation_config,
        }

        for attempt in range(MAX_429_RETRIES + 1):
            try:
                async with session.post(
                    url, json=payload, timeout=AI_HTTP_TIMEOUT
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                        return _extract_json(raw_text)
                    if resp.status == 429 and attempt < MAX_429_RETRIES:
                        wait = _retry_after_seconds(resp)
                        logger.warning("Gemini rate-limit (429); %ss dan keyin qayta uriniladi", wait)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status in (400, 404):
                        # Bu model mavjud emas yoki yaroqsiz — keyingisiga o'tamiz
                        resp_txt = await resp.text()
                        last_err = f"Gemini ({model}) HTTP {resp.status}: {resp_txt[:100]}"
                        break
                    resp_txt = await resp.text()
                    last_err = f"Gemini ({model}) HTTP {resp.status}: {resp_txt[:100]}"
            except asyncio.TimeoutError:
                last_err = f"Gemini ({model}) timeout"
                continue
            except Exception as e:
                last_err = f"Gemini ({model}): {e}"
                continue

    raise RuntimeError(last_err or "Gemini noma'lum xato")


async def _call_groq(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    models = await _discover_groq_models(api_key) or GROQ_MODELS
    params = params or get_runtime_params()
    last_err = ""

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": f"{system_instruction}\nJavobni faqat JSON formatida yozing."},
                {"role": "user", "content": f"{prompt}\n\nJavobni JSON formatida qaytaring."}
            ],
            "response_format": {"type": "json_object"},
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(GROQ_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            # 1) Model o'chirilgan / topilmagan → keyingi modelga o'tamiz (retry'siz)
            if e.status == 400 and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated",
            )):
                last_err = f"Groq ({model}): {e.message}"
                continue
            # 2) response_format qo'llab-quvvatlanmaydi → unsiz qayta urinamiz
            if e.status == 400 and ("response_format" in msg or "unsupported parameter" in msg):
                try:
                    payload_no_json = {k: v for k, v in payload.items() if k != "response_format"}
                    result = await _post_chat_completion(GROQ_ENDPOINT, headers, payload_no_json)
                    return _extract_json(result["content"])
                except Exception as e2:
                    last_err = f"Groq ({model}): {e2}"
                    continue
            last_err = f"Groq ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"Groq ({model}): {e}"
            continue

    raise RuntimeError(last_err or "Groq noma'lum xato")


async def _call_openrouter(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/postassistrobot",  # OpenRouter ranking uchun
        "X-Title": "PostAssist Telegram Bot",
    }
    models = await _discover_openrouter_models(api_key) or OPENROUTER_MODELS
    params = params or get_runtime_params()
    last_err = ""

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT quyidagi JSON formatida qaytaring:\n{{\"intent\": \"...\", \"reply\": \"...\", \"post_text\": \"...\", \"scheduled_time\": null, \"has_explicit_time\": false, \"target_all\": false}}"},
            ],
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(OPENROUTER_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            if e.status == 400 and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated", "no such model",
            )):
                last_err = f"OpenRouter ({model}): {e.message}"
                continue
            last_err = f"OpenRouter ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"OpenRouter ({model}): {e}"
            continue

    raise RuntimeError(last_err or "OpenRouter noma'lum xato")


async def _call_mistral(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = params or get_runtime_params()
    last_err = ""

    for model in MISTRAL_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
            "safe_prompt": False,
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(MISTRAL_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            if e.status == 400 and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated",
            )):
                last_err = f"Mistral ({model}): {e.message}"
                continue
            if e.status == 400 and "safe_prompt" in msg:
                # safe_prompt parametri qo'llab-quvvatlanmasa — unsiz qayta urinamiz
                try:
                    payload_no_safe = {k: v for k, v in payload.items() if k != "safe_prompt"}
                    result = await _post_chat_completion(MISTRAL_ENDPOINT, headers, payload_no_safe)
                    return _extract_json(result["content"])
                except Exception as e2:
                    last_err = f"Mistral ({model}): {e2}"
                    continue
            last_err = f"Mistral ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"Mistral ({model}): {e}"
            continue

    raise RuntimeError(last_err or "Mistral noma'lum xato")


async def _call_cerebras(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = params or get_runtime_params()
    last_err = ""

    for model in CEREBRAS_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(CEREBRAS_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            if e.status == 400 and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated", "no such model",
            )):
                last_err = f"Cerebras ({model}): {e.message}"
                continue
            last_err = f"Cerebras ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"Cerebras ({model}): {e}"
            continue

    raise RuntimeError(last_err or "Cerebras noma'lum xato")


async def _call_sambanova(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = params or get_runtime_params()
    last_err = ""

    for model in SAMBANOVA_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(SAMBANOVA_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            if e.status == 400 and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated", "no such model",
            )):
                # Bu model mavjud emas — keyingi modelga o'tamiz
                last_err = f"SambaNova ({model}): {e.message}"
                continue
            last_err = f"SambaNova ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"SambaNova ({model}): {e}"
            continue

    raise RuntimeError(last_err or "SambaNova noma'lum xato")


async def _call_cloudflare(prompt: str, api_key: str, system_instruction: str, params: dict = None) -> dict:
    """Cloudflare Workers AI (OpenAI-mos /v1/chat/completions).

    Endpoint ichida CLOUDFLARE_ACCOUNT_ID bo'lishi shart — bo'lmasa darhol
    xato qaytaramiz (zanjir keyingi provayderga o'tadi).
    """
    if not CLOUDFLARE_ACCOUNT_ID:
        raise RuntimeError("Cloudflare: CLOUDFLARE_ACCOUNT_ID sozlanmagan")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = params or get_runtime_params()
    last_err = ""

    for model in CLOUDFLARE_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
        }
        _apply_optional_params(payload, params)
        try:
            result = await _post_chat_completion(CLOUDFLARE_ENDPOINT, headers, payload)
            return _extract_json(result["content"])
        except ProviderError as e:
            msg = (e.message or "").lower()
            if e.status in (400, 404) and any(k in msg for k in (
                "decommissioned", "does not exist", "not found", "deprecated",
                "no such model", "unknown model", "unsupported model",
            )):
                # Bu model mavjud emas — keyingi modelga o'tamiz
                last_err = f"Cloudflare ({model}): {e.message}"
                continue
            last_err = f"Cloudflare ({model}): {e.message}"
            continue
        except Exception as e:
            last_err = f"Cloudflare ({model}): {e}"
            continue

    raise RuntimeError(last_err or "Cloudflare noma'lum xato")


async def _call_pollinations(prompt: str, system_instruction: str, params: dict = None) -> dict:
    """Kalitsiz bepul zaxira (Pollinations) — oxirgi chora."""
    params = params or get_runtime_params()
    payload = {
        "model": "openai-large",   # openai → openai-large (sifat yaxshilandi)
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
        ],
    }
    _apply_optional_params(payload, params)
    result = await _post_chat_completion(POLLINATIONS_ENDPOINT, None, payload)
    return _extract_json(result["content"])


def _clean_key(value: str) -> str:
    return (value or "").strip().replace('"', '').replace("'", "")


async def _run_ai_chain(prompt: str, system_instruction: str) -> dict:
    """8 ta provayderni navbat bilan sinaydi: Gemini → Groq → OpenRouter →
    Mistral → Cerebras → SambaNova → Cloudflare → Pollinations (kalitsiz).

    - Har bir provayder 3 marta ketma-ket xato bersa, 10 daqiqaga o'tkazib
      yuboriladi (circuit breaker) — o'lik provayderga vaqt sarflanmaydi.
    - Bir vaqtda ko'pi bilan MAX_CONCURRENT_AI (2) ta so'rov ishlaydi.
    - Prompt max_prompt_chars belgidan oshsa kesiladi (admin sozlashi mumkin).
    Muvaffaqiyatda provayder qaytargan JSON dict qaytadi; xatolikda {"error": ...}.
    """
    params = get_runtime_params()
    max_prompt_chars = int(params.get("max_prompt_chars") or MAX_PROMPT_CHARS)

    # Prompt uzunligini cheklash (bepul token byudjetini himoya qilish)
    prompt = (prompt or "").strip()
    if len(prompt) > max_prompt_chars:
        prompt = prompt[:max_prompt_chars] + "\n…(matn juda uzun edi, kesildi)"

    gemini_key = _clean_key(GEMINI_API_KEY)
    groq_key = _clean_key(GROQ_API_KEY)
    openrouter_key = _clean_key(OPENROUTER_API_KEY)
    mistral_key = _clean_key(MISTRAL_API_KEY)
    cerebras_key = _clean_key(CEREBRAS_API_KEY)
    sambanova_key = _clean_key(SAMBANOVA_API_KEY)
    cloudflare_key = _clean_key(CLOUDFLARE_API_TOKEN)

    providers = [
        ("Gemini", _call_gemini, (prompt, gemini_key, system_instruction, params), bool(gemini_key)),
        ("Groq", _call_groq, (prompt, groq_key, system_instruction, params), bool(groq_key)),
        ("OpenRouter", _call_openrouter, (prompt, openrouter_key, system_instruction, params), bool(openrouter_key)),
        ("Mistral", _call_mistral, (prompt, mistral_key, system_instruction, params), bool(mistral_key)),
        ("Cerebras", _call_cerebras, (prompt, cerebras_key, system_instruction, params), bool(cerebras_key)),
        ("SambaNova", _call_sambanova, (prompt, sambanova_key, system_instruction, params), bool(sambanova_key)),
        # Cloudflare: kalit + account_id ikkalasi ham kerak (endpoint shu ikkisidan yig'iladi)
        ("Cloudflare", _call_cloudflare, (prompt, cloudflare_key, system_instruction, params),
         bool(cloudflare_key and CLOUDFLARE_ACCOUNT_ID)),
        ("Pollinations", _call_pollinations, (prompt, system_instruction, params), True),
    ]

    errors = []
    async with _AI_SEMAPHORE:
        for name, func, args, has_key in providers:
            if _breaker_open(name):
                errors.append(f"{name}: vaqtincha o'tkazib yuborildi")
                continue
            if not has_key:
                errors.append(f"{name}: kalit topilmadi" + (" (ixtiyoriy)" if name != "Gemini" else ""))
                continue
            try:
                result = await func(*args)
                if isinstance(result, dict):
                    _breaker_success(name)
                    return result
                errors.append(f"{name}: javob formati noto'g'ri")
            except Exception as e:
                errors.append(f"{name}: {e}")
                _breaker_fail(name)
                logger.warning("%s ishlamadi (%s). Keyingi zaxiraga o'tilmoqda...", name, e)

    detail = "\n".join(f"• {e}" for e in errors if e)

    # Agar barcha (yoki asosiy) uzilishlar TIMEOUT tufayli bo'lsa — texnik
    # ro'yxat o'rniga foydalanuvchiga xushmuomala, tushunarli xabar beramiz.
    timeout_errors = [e for e in errors if "timeout" in str(e).lower()]
    real_attempts = [e for e in errors if "kalit topilmadi" not in str(e)]
    if timeout_errors and len(timeout_errors) >= max(1, len(real_attempts)):
        logger.warning("Barcha AI provayderlari timeout berdi: %s", detail)
        return {"error": AI_TIMEOUT_USER_MESSAGE, "timeout": True}

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
        )
    }


async def _run_with_hard_timeout(coro, timeout: float = None) -> dict:
    """AI zanjirini QAT'IY vaqt chegarasi (default 25s) bilan ishga tushiradi.

    Provayderlar zanjiri (Gemini → Groq → ...) eng yomon holatda daqiqalar
    olishi mumkin — foydalanuvchi cheksiz "AI yozmoqda..." holatida qolib
    ketmasligi uchun butun zanjir ``asyncio.wait_for`` bilan cheklanadi.
    Timeout bo'lsa {"error": ...} qaytaradi (handler doimiy nav-tugma ko'rsatadi).
    """
    hard = float(timeout or AI_HARD_TIMEOUT)
    try:
        return await asyncio.wait_for(coro, timeout=hard)
    except asyncio.TimeoutError:
        logger.warning("AI javobi %.0fs ichida kelmadi (hard timeout)", hard)
        # XUSHMUOMALA xabar: aybdor foydalanuvchi emas, matni ham yo'qolmaydi.
        return {"error": AI_TIMEOUT_USER_MESSAGE, "timeout": True}


async def generate_ai_response(
    prompt: str,
    system_instruction: str = None,
    timeout: float = None,
    tone: str = None,
) -> dict:
    """Umumiy AI chaqiruv (AI Studio) — 25 soniyalik qat'iy timeout bilan.

    Args:
        prompt: foydalanuvchi xabari/mavzusi
        system_instruction: None bo'lsa standart intent-router prompt ishlatiladi
        timeout: qat'iy timeout (None → AI_HARD_TIMEOUT, default 25s)
        tone: kanal uslubi ("formal" | "friendly" | "concise" | "engaging")

    Returns:
        Provayder qaytargan JSON dict; xato/timeout bo'lsa {"error": "..."}.
    """
    if system_instruction is None:
        system_instruction = _get_router_system_instruction()
    if tone:
        system_instruction = _inject_tone(system_instruction, tone)
    try:
        return await _run_with_hard_timeout(
            _run_ai_chain(prompt, system_instruction), timeout
        )
    except Exception as e:
        logger.warning("AI chaqiruv xatosi: %s", e)
        return {"error": f"⚠️ AI xizmatida xatolik yuz berdi: {e}"}


def _normalize_router_result(result: dict) -> dict:
    """AI javobidagi turli maydonlarni yagona shaklga keltiradi va
    backward-compatibility uchun eski 'post_text' sxemasini saqlaydi."""
    if not isinstance(result, dict):
        return {"error": "Javob formati noto'g'ri"}
    if "error" in result:
        return result

    raw_intent = str(result.get("intent", "")).strip().lower()
    reply = str(result.get("reply", "") or "").strip()
    post_text = str(result.get("post_text", "") or "").strip()
    sched_time = result.get("scheduled_time")
    if sched_time in ("null", "None", "", 0):
        sched_time = None
    if sched_time:
        sched_time = str(sched_time).strip()
    has_explicit = bool(result.get("has_explicit_time", False))
    target_all = bool(result.get("target_all", False))

    # Intent ko'rsatilmagan bo'lsa — mavjud maydonlardan aniqlaymiz
    if not raw_intent:
        raw_intent = "faq" if (reply and not post_text) else "post"

    # Eski schema bilan muvofiqlik: intent post/edit + post_text bo'lsa ham
    # 'post_text' maydoni saqlanadi (testlar va eski kod uchun).
    return {
        "intent": raw_intent if raw_intent in ("faq", "post", "edit") else "post",
        "reply": reply,
        "post_text": post_text,
        "scheduled_time": sched_time,
        "has_explicit_time": has_explicit and bool(sched_time),
        "target_all": target_all,
    }


async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """Asosiy intent router: xabarni tahlil qilib yo'naltiradi.

    Qaytargan maydonlar:
      - intent: "faq" (savol-javob), "post" (yangi post), "edit" (tahrir)
      - reply: FAQ rejimidagi javob matni
      - post_text: post rejimida tayyorlangan post
      - scheduled_time: 'YYYY-MM-DD HH:MM' yoki None
      - has_explicit_time: bool
      - target_all: bool
    Eski kod bilan muvofiqlik uchun post_text/scheduled_time maydonlari saqlanadi.
    """
    params = get_runtime_params()
    raw_prompt = (prompt or "").strip()

    # MUHIM: kontekst joriy xabar SAQLANISHIDAN OLDIN olinadi — aks holda
    # joriy xabar promptga ikki marta (kontekstda ham, "Hozirgi xabar" da ham)
    # tushib, model uni takroriy buyruq deb tushunardi.
    max_chars = int(params.get("max_prompt_chars") or MAX_PROMPT_CHARS)
    budget = max(200, max_chars - len(raw_prompt) - 300)
    ctx_text = _get_ai_context_text(user_id, budget)
    if ctx_text:
        prompt = f"{ctx_text}\n\nHozirgi xabar:\n{raw_prompt}"

    # 25 soniyalik QAT'IY timeout — foydalanuvchi cheksiz kutib qolmaydi.
    result = await _run_with_hard_timeout(
        _run_ai_chain(prompt, _get_router_system_instruction())
    )
    if "error" in result:
        # Muvaffaqiyatsiz chaqiruv kontekstga yozilmaydi — aks holda keyingi
        # so'rovda javobsiz qolgan xabar takrorlanib, sifatni pasaytiradi.
        return result

    normalized = _normalize_router_result(result)
    # Muvaffaqiyatli suhbatgina eslab qolinadi: foydalanuvchi xabari + bot javobi.
    _store_ai_context(user_id, raw_prompt, role="user")
    bot_answer = normalized.get("post_text") or normalized.get("reply") or ""
    _store_ai_context(user_id, bot_answer, role="bot")
    return normalized


async def extract_schedule_time(prompt: str, user_id: int = 0) -> dict:
    """Yengil AI rejimi — faqat erkin tildagi vaqtni (yoki savolni) ajratadi.

    Postni qaytadan tahlil qilmaydi, kam token sarflaydi. Qaytargan maydonlar:
      - has_explicit_time: True bo'lsa scheduled_time mavjud
      - scheduled_time: 'YYYY-MM-DD HH:MM' yoki None
      - reply: foydalanuvchi savol bergan bo'lsa, qisqa javob
      - target_all: bool
    """
    # 25 soniyalik QAT'IY timeout — vaqt aniqlash ham yopishib qolmaydi.
    result = await _run_with_hard_timeout(
        _run_ai_chain(prompt, _get_time_system_instruction())
    )
    if "error" in result:
        return result
    norm = _normalize_router_result(result)
    norm["intent"] = "time"
    return norm


# ============================================================
# AI POST FORMATTING ACTIONS
# ============================================================

_FORMAT_ACTION_PROMPTS = {
    "grammar": (
        "Siz professional O'zbek tili muharririsiz. Quyidagi post matnini imlo, "
        "grammatika va tinish belgilari jihatidan tuzating. MA'NONI O'ZGARTIRMANG, "
        "faqat xatolarni to'g'irlang. Matn strukturasini (paragraflar, emoji) saqlab "
        "qoling. Javobni FAQAT to'g'irilgan matnni qaytaring, hech qanday izoh yozmang."
    ),
    "emoji": (
        "Siz professional Telegram post dizaynerisiz. Quyidagi post matniga mos "
        "emojilar qo'shing va chiroyli formatlang. Paragraflarga ajrating, har bir "
        "asosiy fikrga mos emoji qo'ying. Matn mazmunini O'ZGARTIRMANG. "
        "Telegram HTML formatlash ishlating: <b>qalin</b>, <i>kursiv</i>. "
        "Javobni FAQAT formatlangan matnni qaytaring."
    ),
    "hashtags": (
        "Siz professional SMM mutaxassisisiz. Quyidagi post matniga: "
        "1) Diqqat tortuvchi sarlavha (emoji bilan) qo'shing. "
        "2) Matnga mos 3-5 ta hashtag yarating (oxiriga). "
        "3) Sarlavha va hashtaglar O'zbek tilida bo'lsin. "
        "Matn mazmunini O'ZGARTIRMANG. Javobni FAQAT to'liq postni qaytaring."
    ),
    "tldr": (
        "Siz matn qisqartirish mutaxassisisiz. Quyidagi post matnini asosiy "
        "mazmunini saqlab, qisqa va lo'nda qilib qisqartiring. Eng muhim "
        "ma'lumotlarni qoldiring, takroriy gaplarni olib tashlang. "
        "Javobni FAQAT qisqartirilgan matnni qaytaring."
    ),
}


async def format_post_text(text: str, action: str) -> dict:
    """Post matnini AI yordamida formatlaydi.

    Args:
        text: formatlanadigan post matni
        action: "grammar" | "emoji" | "hashtags" | "tldr"

    Returns:
        {"formatted": "..."} yoki {"error": "..."}
    """
    if not text or not text.strip():
        return {"error": "Matn bo'sh."}

    if action not in _FORMAT_ACTION_PROMPTS:
        return {"error": f"Noma'lum harakat: {action}"}

    system_instruction = _FORMAT_ACTION_PROMPTS[action]
    prompt = f"Post matni:\n\n{text}"

    try:
        result = await _run_ai_chain(prompt, system_instruction)
    except Exception as e:
        logger.warning("AI format xatosi (%s): %s", action, e)
        return {"error": f"⚠️ AI xizmatida vaqtinchalik uzilish. Asl matningiz saqlab qolindi.\n\n{e}"}

    if "error" in result:
        return {"error": result["error"]}

    # AI javobidan matnni ajratib olish
    formatted = ""
    if isinstance(result, dict):
        # JSON javob bo'lsa — turli maydonlardan qidiramiz
        formatted = (
            result.get("formatted")
            or result.get("text")
            or result.get("post_text")
            or result.get("reply")
            or result.get("content")
            or ""
        )
        # Agar hech narsa topilmasa — barcha string qiymatlarni birlashtiramiz
        if not formatted:
            for v in result.values():
                if isinstance(v, str) and len(v) > 10:
                    formatted = v
                    break

    if not formatted or not formatted.strip():
        return {"error": "⚠️ AI javobi bo'sh qaytdi. Asl matningiz saqlab qolindi."}

    return {"formatted": formatted.strip()}


# ============================================================
# TONE OF VOICE INTEGRATION
# ============================================================

_TONE_DESCRIPTIONS = {
    "formal": "Rasmiy, professional va biznes uslubida. Qisqa, aniq va hurmatli ohangda yozing. Emoji kamroq ishlating.",
    "friendly": "Do'stona, samimiy va iliq ohangda yozing. O'quvchiga murojaat qiling, emoji oqilona ishlating.",
    "concise": "Qisqa, yangiliklar uslubida. Har bir jumlada aniq ma'lumot bering. Sarlavha va sub-sarlavhalar bilan ajrating.",
    "engaging": "Ko'ngilochar, emotsional va diqqat tortuvchi uslubda. Savollar bering, emoji ko'proq ishlating, CTA qo'shing.",
}


def get_tone_instruction(tone: str) -> str:
    """Kanal uslubiga mos system instruction qaytaradi."""
    desc = _TONE_DESCRIPTIONS.get(tone, _TONE_DESCRIPTIONS["friendly"])
    return f"\n\nKANAL USLUBI (Tone of Voice): {desc}"


def _inject_tone(system_instruction: str, tone: str) -> str:
    """System instructionga kanal uslubini qo'shadi."""
    if tone and tone != "friendly":
        return system_instruction + get_tone_instruction(tone)
    return system_instruction


async def format_post_text_with_tone(text: str, action: str, tone: str = "friendly") -> dict:
    """Post matnini kanal uslubini hisobga olgan holda formatlaydi.

    Args:
        text: formatlanadigan post matni
        action: "grammar" | "emoji" | "hashtags" | "tldr"
        tone: kanal uslubi ("formal" | "friendly" | "concise" | "engaging")

    Returns:
        {"formatted": "..."} yoki {"error": "..."}
    """
    if not text or not text.strip():
        return {"error": "Matn bo'sh."}

    if action not in _FORMAT_ACTION_PROMPTS:
        return {"error": f"Noma'lum harakat: {action}"}

    system_instruction = _inject_tone(_FORMAT_ACTION_PROMPTS[action], tone)
    prompt = f"Post matni:\n\n{text}"

    try:
        result = await _run_ai_chain(prompt, system_instruction)
    except Exception as e:
        logger.warning("AI format xatosi (%s, tone=%s): %s", action, tone, e)
        return {"error": f"⚠️ AI xizmatida vaqtinchalik uzilish. Asl matningiz saqlab qolindi.\n\n{e}"}

    if "error" in result:
        return {"error": result["error"]}

    formatted = ""
    if isinstance(result, dict):
        formatted = (
            result.get("formatted")
            or result.get("text")
            or result.get("post_text")
            or result.get("reply")
            or result.get("content")
            or ""
        )
        if not formatted:
            for v in result.values():
                if isinstance(v, str) and len(v) > 10:
                    formatted = v
                    break

    if not formatted or not formatted.strip():
        return {"error": "⚠️ AI javobi bo'sh qaytdi. Asl matningiz saqlab qolindi."}

    return {"formatted": formatted.strip()}


# ============================================================
# CONTENT PLAN GENERATOR
# ============================================================

_CONTENT_PLAN_SYSTEM = (
    "Siz professional SMM va kontent-strategiya mutaxassisisiz. "
    "Telegram kanali uchun 7 kunlik kontent-reja tuzasiz.\n\n"
    "QOIDALAR:\n"
    "- Barcha javoblar O'ZBEK tilida bo'lishi SHART.\n"
    "- Har bir kun uchun: kun nomi, format (Maslahat/Keys/Savol-Javob/Aksiya/Yangilik), "
    "qisqa sarlavha va g'oya tavsifi.\n"
    "- Kunlarni Dushanbadan Yakshanbagacha tartiblang.\n"
    "- Formatlarni har xil qiling (barchasi bir xil bo'lmasin).\n"
    "- Har bir g'oya amaliy va qiziqarli bo'lsin.\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    "{\n"
    '  "plan": [\n'
    '    {"day": "Dushanba", "format": "Maslahat", "title": "sarlavha", "idea": "g\'oya tavsifi"},\n'
    '    {"day": "Seshanba", "format": "Keys/Fakt", "title": "sarlavha", "idea": "g\'oya tavsifi"},\n'
    "    ... 7 ta kun\n"
    "  ]\n"
    "}"
)


async def generate_content_plan(topic: str, channel_title: str, tone: str = "friendly", recent_posts: list = None) -> dict:
    """7 kunlik kontent-reja generatsiya qiladi.

    Args:
        topic: kanal mavzusi (masalan: "Ingliz tili noldan")
        channel_title: kanal nomi
        tone: kanal uslubi
        recent_posts: kanalning oxirgi postlari tarixi (kontekst uchun)

    Returns:
        {"plan": [...]} yoki {"error": "..."}
    """
    if not topic or not topic.strip():
        return {"error": "⚠️ Mavzu kiritilmadi."}

    system_instruction = _inject_tone(_CONTENT_PLAN_SYSTEM, tone)
    prompt = (
        f"Kanal nomi: {channel_title}\n"
        f"Mavzu: {topic}\n"
    )
    if recent_posts:
        posts_context = "\n".join(f"- {p[:150]}" for p in recent_posts[:3] if p)
        if posts_context:
            prompt += f"\nKanalning so'nggi postlari (kontekst va uslub uchun):\n{posts_context}\n"
    prompt += "\n7 kunlik kontent-reja tuzing."

    try:
        result = await _run_ai_chain(prompt, system_instruction)
    except Exception as e:
        logger.warning("Content plan AI xatosi: %s", e)
        return {"error": f"⚠️ AI xizmatida vaqtinchalik uzilish.\n\n{e}"}

    if "error" in result:
        return result

    plan = result.get("plan", [])
    if not plan or not isinstance(plan, list):
        return {"error": "⚠️ AI reja tuza olmadi. Qaytadan urinib ko'ring."}

    return {"plan": plan}


_POST_FROM_PLAN_SYSTEM = (
    "Siz professional Telegram post muharririsiz. "
    "Berilgan g'oya asosida to'liq, tayyor Telegram post matni yozasiz.\n\n"
    "QOIDALAR:\n"
    "- O'zbek tilida, jonli va jozibador yozing.\n"
    "- Telegram HTML formatlash: <b>qalin</b>, <i>kursiv</i>.\n"
    "- Emoji oqilona ishlating.\n"
    "- Kamida 3-5 qator, mazmunan to'liq.\n"
    "- CTA (chaqiriq) qo'shing.\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"post_text": "tayyor post matni"}'
)


async def generate_post_from_plan(topic: str, title: str, idea: str, tone: str = "friendly") -> dict:
    """Kontent-reja g'oyasidan to'liq post yaratadi.

    Args:
        topic: umumiy mavzu
        title: post sarlavhasi
        idea: g'oya tavsifi
        tone: kanal uslubi

    Returns:
        {"post_text": "..."} yoki {"error": "..."}
    """
    system_instruction = _inject_tone(_POST_FROM_PLAN_SYSTEM, tone)
    prompt = (
        f"Umumiy mavzu: {topic}\n"
        f"Post sarlavhasi: {title}\n"
        f"G'oya: {idea}\n\n"
        f"Shu g'oya asosida to'liq Telegram post yozing."
    )

    try:
        result = await _run_ai_chain(prompt, system_instruction)
    except Exception as e:
        logger.warning("Post from plan AI xatosi: %s", e)
        return {"error": f"⚠️ AI xizmatida vaqtinchalik uzilish.\n\n{e}"}

    if "error" in result:
        return result

    post_text = (
        result.get("post_text")
        or result.get("text")
        or result.get("reply")
        or ""
    )
    if not post_text:
        for v in result.values():
            if isinstance(v, str) and len(v) > 20:
                post_text = v
                break

    if not post_text:
        return {"error": "⚠️ AI post matni tayyorlay olmadi."}

    return {"post_text": post_text.strip()}


# ============================================================
# PUBLIC CHANNEL POST RE-WRITER
# ============================================================

_REWRITE_SYSTEM = (
    "Siz professional Telegram post muharririsiz. Berilgan yangilik matnini "
    "qayta yozasiz (re-write). QAT'IY QOIDALAR:\n"
    "1. Yangi yolg'on fakt QO'SHMANG — faqat asl matndagi ma'lumotga tayaning.\n"
    "2. Faktlarni o'zgartirmang, qisqartirmasdan to'liq saqlang.\n"
    "3. O'zbek tilida, jonli va jozibador yozing.\n"
    "4. Telegram HTML formatlash: <b>qalin</b>, <i>kursiv</i>.\n"
    "5. Emoji oqilona ishlating.\n"
    "6. Post oxiriga MANBA havolasini qo'shing (foydalanuvchi beradi).\n"
    "7. Post kamida 3-5 qator bo'lsin.\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"post_text": "qayta yozilgan to\'liq post matni"}'
)


async def rewrite_channel_post(
    original_text: str,
    channel_username: str,
    post_link: str = "",
    tone: str = "friendly",
) -> dict:
    """Ochiq kanal postini AI orqali qayta yozadi.

    Args:
        original_text: asl post matni
        channel_username: kanal niki (manba uchun)
        post_link: asl post havolasi
        tone: kanal uslubi

    Returns:
        {"post_text": "..."} yoki {"error": "..."}
    """
    if not original_text or not original_text.strip():
        return {"error": "⚠️ Post matni bo'sh."}

    system_instruction = _inject_tone(_REWRITE_SYSTEM, tone)

    source_line = f"📌 Manba: @{channel_username}"
    if post_link:
        source_line += f"\n🔗 {post_link}"

    prompt = (
        f"Asl post matni:\n\n{original_text}\n\n"
        f"Manba: @{channel_username}\n"
        f"Post havolasi: {post_link}\n\n"
        f"Post oxiriga quyidagi manba qatorini QO'SHING:\n{source_line}\n\n"
        f"Matnni qayta yozing."
    )

    try:
        result = await _run_ai_chain(prompt, system_instruction)
    except Exception as e:
        logger.warning("Rewrite AI xatosi: %s", e)
        return {"error": f"⚠️ AI xizmatida vaqtinchalik uzilish.\n\n{e}"}

    if "error" in result:
        return result

    post_text = (
        result.get("post_text")
        or result.get("text")
        or result.get("reply")
        or ""
    )
    if not post_text:
        for v in result.values():
            if isinstance(v, str) and len(v) > 20:
                post_text = v
                break

    if not post_text:
        return {"error": "⚠️ AI post matni tayyorlay olmadi."}

    # Manba qatorini tekshirish — agar AI qo'shmagan bo'lsa, biz qo'shamiz
    if f"@{channel_username}" not in post_text:
        post_text = post_text.rstrip() + f"\n\n{source_line}"

    return {"post_text": post_text.strip()}


# ============================================================
# 🖼 VISION — RASMDAN POST YARATISH (Photo-to-Post)
# ============================================================
# Gemini vision orqali rasm chuqur tahlil qilinib, Telegram kanallari uchun
# professional SMM posti tayyorlanadi.
#
# XOTIRA HIMOYASI (Render xotirasi to'lib qolmasligi uchun):
# - Rasm hech qachon RAM'da USHLAB TURILMAYDI: Telegram CDN'dan diskka
#   STREAM (64KB chunk) qilinadi — vaqtinchalik temp fayl.
# - Faqat API so'rovi paytida base64 (zarur) zanjirli quriladi va ish
#   tugagach temp fayl `cleanup_temp_media()` bilan o'chiriladi.
# - Yuklanish hajmi VISION_MAX_FILE_BYTES bilan cheklanadi.
VISION_MAX_FILE_BYTES = max(
    1024 * 1024, int(os.getenv("VISION_MAX_FILE_BYTES", str(10 * 1024 * 1024)))
)
VISION_HARD_TIMEOUT = max(10.0, float(os.getenv("VISION_HARD_TIMEOUT", "45")))
VISION_TEMP_PREFIX = "postassist_vision_"

# === VISION MODELI ===
# Rasm tahlili uchun BARQAROR (stable/GA) Gemini modeli. Ilgari bu oqim
# chat-modellar ro'yxatini (model discovery) ishlatar edi — natijada rasmni
# qabul qilmaydigan yoki Google o'chirib qo'ygan model tanlanib, foydalanuvchi
# "Gemini vision modeli hozircha mavjud emas" (HTTP 404) xatosini ko'rardi.
#
# Endi vision oqimi O'Z modelini qat'iy belgilaydi:
#   • GEMINI_VISION_MODEL — admin xohlagan modelni shu yerda almashtiradi;
#   • agar u javob bermasa, quyidagi barqaror zaxira zanjiri sinaladi.
# Eslatma: `gemini-1.5-flash` Google tomonidan 2025-09-29 da o'chirilgan va
# unga yuborilgan har qanday so'rov 404 qaytaradi, shuning uchun standart
# qiymat sifatida amaldagi barqaror model olingan.
GEMINI_VISION_MODEL = (os.getenv("GEMINI_VISION_MODEL") or "").strip() or "gemini-2.5-flash"

# Gemini vision uchun afzal modellar (barchasi image input qo'llab-quvvatlaydi).
# Birinchi element — admin belgilagan model (GEMINI_VISION_MODEL).
VISION_GEMINI_PREFERRED = [
    GEMINI_VISION_MODEL,         # admin belgilagan barqaror model
    "gemini-2.5-flash",          # barqaror, rasm kirishini qo'llaydi
    "gemini-flash-latest",       # Flash aliasi — o'chirilsa ham yangisi keladi
    "gemini-2.5-flash-lite",     # tez va arzon
    "gemini-flash-lite-latest",  # Flash-Lite aliasi
    "gemini-2.5-pro",            # eng yuqori sifat (limit bor)
]

# Rasm tahliliga YAROQSIZ model oilalari (discovery ro'yxatidan filtrlanadi).
_VISION_UNSUPPORTED_HINTS = (
    "embedding", "tts", "speech", "audio", "live", "imagen", "veo",
    "aqa", "learnlm", "guard", "safeguard", "transcribe", "robotics",
    "omni", "banana", "gemma", "lite-translate",
)


def _is_vision_capable(model: str) -> bool:
    """Model rasm kirishini qabul qila oladimi (generativ matn modeli)?"""
    low = (model or "").strip().lower()
    if not low or _is_retired_gemini(model):
        return False
    if "gemini" not in low:
        return False
    return not any(hint in low for hint in _VISION_UNSUPPORTED_HINTS)


def _vision_model_chain(discovered: list = None) -> list:
    """Rasm tahlili uchun sinab chiqiladigan modellar zanjiri.

    Tartib: admin belgilagan model → barqaror afzallar → discovery'dan
    topilgan vision-yaroqli modellar. Takrorlanishlar va Google o'chirib
    qo'ygan modellar chiqarib tashlanadi (admin qo'lda belgilagani bundan
    mustasno — u doim birinchi sinovdan o'tkaziladi).
    """
    chain: list[str] = []
    explicit = (GEMINI_VISION_MODEL or "").strip()
    if explicit:
        chain.append(explicit)
    for model in VISION_GEMINI_PREFERRED:
        model = (model or "").strip()
        if not model or model in chain:
            continue
        if _is_retired_gemini(model):
            continue
        chain.append(model)
    for model in (discovered or []):
        model = (model or "").strip()
        if not model or model in chain:
            continue
        if not _is_vision_capable(model):
            continue
        chain.append(model)
    return chain


async def _discover_vision_models(api_key: str) -> list:
    """Vision oqimi uchun model zanjiri (discovery bilan birgalikda)."""
    discovered = None
    try:
        discovered = await _discover_gemini_models(api_key)
    except Exception as e:  # discovery ishlamasa — barqaror zanjir yetarli
        logger.warning("Vision model discovery xatosi: %s", e)
    return _vision_model_chain(discovered)


VISION_SAFETY_ERROR = (
    "🚫 Kechirasiz, bu rasm kontent xavfsizligi talablariga mos kelmaydi. "
    "Iltimos, boshqa rasm yuboring."
)
VISION_EMPTY_ERROR = (
    "⚠️ AI rasmni tahlil qila olmadi (bo'sh javob). "
    "Iltimos, qayta urinib ko'ring."
)


class VisionError(RuntimeError):
    """Rasm tahlilidagi foydalanuvchiga tushunarli o'zbekcha xato."""


_VISION_SYSTEM = (
    "Siz professional SMM-mutaxassis va Telegram kanallar uchun kontent yozuvchisisiz. "
    "Sizga yuborilgan rasmni CHUQUR tahlil qilasiz va shu rasm asosida Telegram "
    "kanali uchun TO'LIQ TAYYOR post yozasiz (faqat rasm tahlil qilinadi — "
    "video tahlil qilinmaydi).\n\n"
    "QAT'IY TALABLAR:\n"
    "- Barcha matn O'ZBEK tilida bo'lsin (ruscha/inglizcha aralashmasin).\n"
    "- 1-QATOR — SARLAVHA: diqqat tortuvchi, qisqa sarlavha <b>...</b> HTML "
    "bilan qalin qilib yozilsin.\n"
    "- Rasm mazmunini chuqur tahlil qiling: nima tasvirlangan, kimga mo'ljallangan, "
    "qanday his-tuyg'u yoki aksiya uyg'otadi.\n"
    "- JOZIBADOR MATN: kamida 3-6 qator, qisqa bandlar (•) bilan, o'quvchini "
    "ushlab turadigan sodda va ta'sirli uslubda.\n"
    "- EMOJILAR: mos emojilarni oqilona ishlating (3-6 dona, har gapga emas).\n"
    "- Oxirida aniq harakatga chaqiruv (CTA) qo'shing (masalan: '👉 ...').\n"
    "- Eng oxirida ALOHIDA qatorda 3-5 ta mos XESHTEG (#... bilan).\n"
    "- Telegram HTML: faqat <b> va <i> ruxsat etiladi — boshqa teglar YO'Q.\n"
    "- Yolg'on fakt QO'SHMANG: faqat rasmda ko'rinadigan yoki asosli xulosa "
    "qilish mumkin bo'lgan narsalarga tayaning.\n"
    "- Izoh/tushuntirish YOZMANG — javob bevosita kanalga joylanadigan tayyor "
    "post bo'lsin.\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"post_text": "to\'liq tayyor post matni"}'
)

_VISION_REWRITE_SYSTEM = (
    "Siz professional SMM-mutaxassis va Telegram post muharririsiz. Berilgan "
    "rasmni YANA BIR BOR chuqur tahlil qilib, avvalgi postni butunlay BOSHQA "
    "uslubda qayta yozasiz (yangi sarlavha, yangi CTA va yangi hashtaglar bilan).\n\n"
    "QAT'IY TALABLAR:\n"
    "- O'ZBEK tilida, <b>...</b> sarlavha bilan, (•) bandlar va mos emojilar bilan.\n"
    "- Faktlarni saqlang, yolg'on ma'lumot QO'SHMANG.\n"
    "- Oxirida harakatga chaqiruv (CTA) va 3-5 ta mos hashtag.\n"
    "- Telegram HTML: faqat <b> va <i>.\n\n"
    "Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
    '{"post_text": "qayta yozilgan to\'liq post"}'
)


def detect_image_mime(path: str) -> str | None:
    """Fayl boshidagi magic-bytes orqali rasm MIME turini aniqlaydi.

    JPG / PNG / GIF / WEBP / BMP qo'llab-quvvatlanadi; rasm bo'lmasa None.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except (OSError, IOError):
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:2] == b"BM":
        return "image/bmp"
    return None


def _encode_image_base64(path: str) -> str:
    """Faylni RAM'ga butunlay yuklamasdan, zanjirli base64 ga o'tkazadi.

    Har bir 3MB chunk alohida kodlanadi — xom (raw) tasvir hech qachon to'liq
    xotiraga olinmaydi (faqat API uchun zarur base64 matn quriladi).
    """
    chunks = []
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(3 * 1024 * 1024)
            if not chunk:
                break
            chunks.append(base64.b64encode(chunk))
    return b"".join(chunks).decode("ascii")


def vision_friendly_error(status: int = None, message: str = "") -> str:
    """Gemini API xatolari uchun foydalanuvchiga tushunarli o'zbekcha xabar."""
    low = (message or "").lower()
    if status in (401, 403) and any(k in low for k in (
        "api key", "invalid key", "unauthorized", "permission",
    )):
        return (
            "🔑 Gemini API kaliti noto'g'ri yoki yaroqsiz. "
            "Iltimos, admin bilan bog'laning."
        )
    if status in (400, 403) and any(k in low for k in (
        "safety", "blocked", "harmful", "sexual", "violent", "policy",
    )):
        return VISION_SAFETY_ERROR
    if status == 429 or any(k in low for k in (
        "rate limit", "quota", "resource exhausted", "429",
    )):
        return (
            "⏳ Gemini API hozircha band (rate limit / kvota). "
            "Iltimos, 1-2 daqiqa kuting va qayta urinib ko'ring."
        )
    if status == 404 or "not found" in low or "does not exist" in low:
        # Bu xatoning sababi — so'ralgan model Google tomonidan o'chirilgan.
        # Vision zanjiri barqaror modellar bilan qayta qurilgani uchun bu holat
        # amalda uchramaydi; uchrasa admin uchun aniq ko'rsatma beriladi.
        return (
            "🤖 Rasm tahlili modeli yangilanishi kerak (server sozlamasi). "
            "Iltimos, birozdan so'ng qayta urinib ko'ring yoki admin bilan "
            "bog'laning."
        )
    if status == 413 or ("payload" in low and "large" in low) or "too large" in low:
        return "📦 Rasm hajmi juda katta. Iltimos, kichikroq rasm yuboring."
    if (status == 400 or status == 422) and any(k in low for k in (
        "mime", "inline", "image", "format",
    )):
        return (
            "🖼 Rasm formati qo'llab-quvvatlanmaydi. "
            "JPG, PNG yoki WEBP formatidagi rasm yuboring."
        )
    if status == 0 or "timeout" in low:
        return (
            "⏱ AI rasmni tahlil qilishda vaqt tugadi. "
            "Tarmoq holatini tekshirib, qayta urinib ko'ring."
        )
    return (
        f"⚠️ AI rasmni tahlil qila olmadi (Gemini: HTTP {status or 'xato'}). "
        "Iltimos, birozdan so'ng qayta urinib ko'ring."
    )


def _parse_vision_text(raw_text: str) -> dict:
    """Gemini vision javobidan post matnini ishonchli ajratib oladi."""
    text = (raw_text or "").strip()
    if not text:
        return {"error": VISION_EMPTY_ERROR}
    try:
        obj = _extract_json(text)
        if isinstance(obj, dict):
            post = (
                obj.get("post_text")
                or obj.get("text")
                or obj.get("reply")
                or obj.get("content")
                or ""
            )
            if post and str(post).strip():
                return {"post_text": str(post).strip()}
    except Exception:
        pass
    # JSON bo'lmagan to'g'ri matn — to'g'ridan-to'g'ri qaytaramiz
    return {"post_text": text}


def _gemini_parts_text(content: dict) -> str:
    parts = (content or {}).get("parts", []) or []
    return "\n".join(
        p.get("text", "") for p in parts if isinstance(p, dict)
    ).strip()


async def _call_gemini_vision(
    image_b64: str,
    mime_type: str,
    prompt: str,
    system_instruction: str,
    api_key: str,
    params: dict = None,
) -> dict:
    """Gemini `generateContent` ga rasm (inline_data) bilan so'rov yuboradi.

    1) Vision uchun BARQAROR model zanjiri (GEMINI_VISION_MODEL → afzallar →
       discovery'dan topilgan vision-yaroqli modellar).
    2) 429 → MAX_429_RETRIES marta Retry-After bilan qayta urinish.
    3) Model 400/404 → keyingi modelga o'tish (o'chirilgan model zanjirni
       to'xtatmaydi).
    4) Barcha modellar 404 bersa — barqaror model GA (`v1`) endpointida
       bir marta qayta sinaladi (ba'zi kalitlarda `v1beta` 404 qaytaradi).
    Xatolikda foydalanuvchiga mos {"error": ...} qaytaradi (crash emas).
    """
    session = await _get_session()
    models = await _discover_vision_models(api_key)
    params = params or get_runtime_params()
    state = {"status": None, "text": "", "rate_limited": False}

    generation_config = {}
    _v_temp = _optional_param(params, "temperature")
    if _v_temp is not None:
        generation_config["temperature"] = _v_temp
    _v_top_p = _optional_param(params, "top_p")
    if _v_top_p is not None:
        generation_config["topP"] = _v_top_p
    _v_max_tokens = _optional_param(params, "max_tokens")
    if _v_max_tokens is not None:
        generation_config["maxOutputTokens"] = _v_max_tokens

    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                ],
            }
        ],
        "generationConfig": generation_config,
    }

    async def _try_model(model: str, base_url: str):
        """Bitta modelga so'rov: natija dict yoki None (keyingi modelga o'tish)."""
        url = f"{base_url}/{model}:generateContent?key={api_key}"
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                async with session.post(
                    url, json=payload, timeout=AI_HTTP_TIMEOUT
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        feedback = data.get("promptFeedback") or {}
                        if feedback.get("blockReason"):
                            return {"error": VISION_SAFETY_ERROR}
                        candidates = data.get("candidates") or []
                        if not candidates:
                            return {"error": VISION_EMPTY_ERROR}
                        raw_text = _gemini_parts_text(candidates[0].get("content") or {})
                        return _parse_vision_text(raw_text)
                    if resp.status == 429 and attempt < MAX_429_RETRIES:
                        wait = _retry_after_seconds(resp)
                        logger.warning(
                            "Gemini vision rate-limit (429); %ss dan keyin qayta uriniladi",
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    state["status"] = resp.status
                    state["text"] = (await resp.text())[:400]
                    if resp.status == 429:
                        state["rate_limited"] = True
                        return None
                    # 400/404 → bu model yaroqsiz, keyingisiga o'tamiz
                    return None
            except asyncio.TimeoutError:
                state["status"] = 0
                state["text"] = "timeout"
                return None
            except aiohttp.ClientError as e:
                state["status"] = 0
                state["text"] = str(e)
                return None
            except Exception as e:
                state["status"] = 0
                state["text"] = str(e)
                return None
        return None

    for model in models:
        result = await _try_model(model, GEMINI_BASE)
        if result is not None:
            return result
        if state["rate_limited"]:
            break  # kvota tugadi — zanjirni uzamiz

    # Barcha modellar 404 qaytardi: ba'zi API kalitlarida model `v1beta` da
    # ko'rinmaydi, lekin barqaror `v1` da ishlaydi — shu yerda bir marta
    # asosiy (barqaror) model qayta sinaladi.
    if state["status"] == 404 and models and "/v1beta/" in GEMINI_BASE:
        ga_base = GEMINI_BASE.replace("/v1beta/", "/v1/", 1)
        logger.warning(
            "Gemini vision: barcha modellar 404 berdi (%s) — GA endpoint sinatiladi",
            models[:3],
        )
        result = await _try_model(models[0], ga_base)
        if result is not None:
            return result

    if state["status"] == 404:
        logger.error(
            "Gemini vision modellari topilmadi (404). Sinovdan o'tganlar: %s. "
            "GEMINI_VISION_MODEL ni amaldagi barqaror modelga o'zgartiring.",
            models,
        )
    return {"error": vision_friendly_error(state["status"], state["text"])}



async def download_telegram_media_to_temp(
    file_id: str,
    max_bytes: int = None,
    bot_token: str = None,
) -> str:
    """Telegram faylini RAM'ga yuklamasdan vaqtinchalik diskka stream qiladi.

    - `getFile` orqali file_path olinadi (kichik JSON).
    - Fayl 64KB chunklarda diskka yoziladi (xotira deyarli ishlatilmaydi).
    - Hajm `max_bytes` (default VISION_MAX_FILE_BYTES) dan oshsa `VisionError`.
    Qaytargan yo'l ishlatilgach `cleanup_temp_media()` bilan o'chiriladi.
    """
    token = (bot_token or BOT_TOKEN or "").strip()
    if not token:
        raise VisionError("⚠️ BOT_TOKEN topilmadi — rasmni yuklab bo'lmadi.")
    limit = int(max_bytes or VISION_MAX_FILE_BYTES)
    session = await _get_session()

    get_url = f"https://api.telegram.org/bot{token}/getFile"
    try:
        async with session.get(
            get_url, params={"file_id": file_id}, timeout=AI_HTTP_TIMEOUT
        ) as resp:
            if resp.status != 200:
                raise VisionError("⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.")
            data = await resp.json()
    except VisionError:
        raise
    except Exception as e:
        raise VisionError("⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.") from e

    result = data.get("result") or {}
    file_path = result.get("file_path")
    if not data.get("ok") or not file_path:
        raise VisionError("⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.")

    tmp_dir = tempfile.mkdtemp(prefix=VISION_TEMP_PREFIX)
    ext = os.path.splitext(file_path)[1] or ".media"
    tmp_path = os.path.join(tmp_dir, f"media{ext}")
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    size = 0
    try:
        async with session.get(url, timeout=MEDIA_DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                raise VisionError(
                    f"⚠️ Rasmni yuklab bo'lmadi (server HTTP {resp.status})."
                )
            with open(tmp_path, "wb") as fh:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise VisionError(
                            f"📦 Rasm hajmi {limit // (1024 * 1024)} MB dan oshib ketdi. "
                            "Iltimos, kichikroq rasm yuboring."
                        )
                    fh.write(chunk)
        if size == 0:
            raise VisionError("⚠️ Rasm fayli bo'sh. Boshqa rasm yuboring.")
    except VisionError:
        cleanup_temp_media(tmp_path)
        raise
    except Exception as e:
        cleanup_temp_media(tmp_path)
        raise VisionError("⚠️ Rasmni yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.") from e
    return tmp_path


def cleanup_temp_media(path: str):
    """Vaqtinchalik rasm faylini va uning katalogini xavfsiz o'chiradi."""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
        parent = os.path.dirname(os.path.abspath(path))
        if (
            os.path.basename(parent).startswith(VISION_TEMP_PREFIX)
            and os.path.isdir(parent)
        ):
            os.rmdir(parent)
    except Exception:
        pass


async def generate_vision_post(
    image_path: str,
    extra_prompt: str = "",
    tone: str = None,
    rewrite_context: str = "",
    timeout: float = None,
) -> dict:
    """Rasmni Gemini vision bilan chuqur tahlil qilib professional post yozadi.

    Args:
        image_path: vaqtinchalik diskdagi rasm yo'li
        extra_prompt: foydalanuvchining qo'shimcha izohi (ixtiyoriy)
        tone: kanal uslubi ("formal" | "friendly" | ...)
        rewrite_context: "Qayta yozish" rejimida oldingi post matni
        timeout: qat'iy vaqt chegarasi (default VISION_HARD_TIMEOUT=45s)

    Returns:
        {"post_text": "..."} yoki {"error": "o'zbekcha tushunarli xabar"}
    """
    if not image_path or not os.path.exists(image_path):
        return {"error": "⚠️ Rasm faylini topib bo'lmadi. Rasmni qaytadan yuboring."}
    try:
        size = os.path.getsize(image_path)
    except OSError:
        return {"error": "⚠️ Rasm faylini o'qib bo'lmadi. Rasmni qaytadan yuboring."}
    if size > VISION_MAX_FILE_BYTES:
        mb = VISION_MAX_FILE_BYTES // (1024 * 1024)
        return {
            "error": f"📦 Rasm hajmi {mb} MB dan oshib ketdi — kichikroq rasm yuboring."
        }

    mime_type = detect_image_mime(image_path)
    if not mime_type:
        return {
            "error": "🖼 Bu fayl rasm emas yoki formati qo'llab-quvvatlanmaydi. "
            "JPG, PNG yoki WEBP yuboring."
        }

    gemini_key = _clean_key(GEMINI_API_KEY)
    if not gemini_key:
        return {
            "error": (
                "🔑 Rasm tahlili uchun Gemini API kaliti kerak: <b>GEMINI_API_KEY</b> "
                "o'rnatilmagan. Iltimos, keyinroq qayta urinib ko'ring."
            )
        }

    if rewrite_context:
        system_instruction = _inject_tone(_VISION_REWRITE_SYSTEM, tone or "friendly")
        prompt_parts = [
            "Quyidagi rasm asosida tayyorlangan postni qayta yozing:",
            rewrite_context,
        ]
        if extra_prompt:
            prompt_parts.append(f"Qo'shimcha talab: {extra_prompt}")
        prompt = "\n\n".join(prompt_parts)
    else:
        system_instruction = _inject_tone(_VISION_SYSTEM, tone or "friendly")
        prompt = (
            f"Qo'shimcha ko'rsatma: {extra_prompt}"
            if extra_prompt
            else "Rasmni chuqur tahlil qiling va professional Telegram post tayyorlang."
        )

    try:
        image_b64 = _encode_image_base64(image_path)
        return await asyncio.wait_for(
            _call_gemini_vision(
                image_b64, mime_type, prompt, system_instruction, gemini_key
            ),
            timeout=float(timeout or VISION_HARD_TIMEOUT),
        )
    except asyncio.TimeoutError:
        logger.warning("Vision javobi %.0fs ichida kelmadi (hard timeout)", VISION_HARD_TIMEOUT)
        return {
            "error": (
                "⏳ <b>AI rasmni tahlil qilishga ulgurmadi.</b>\n\n"
                "Server hozir band ko'rinadi. Iltimos, bir daqiqadan so'ng "
                "qayta urinib ko'ring yoki kichikroq rasm yuboring. 🙏"
            ),
            "timeout": True,
        }
    except VisionError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.warning("Vision xatosi: %s", e)
        return {
            "error": "⚠️ AI rasmni tahlil qila olmadi. "
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        }
