import asyncio
import json
import logging
import os
import time as _time
from collections import deque
from datetime import datetime
import pytz
import aiohttp
from config import (
    GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY,
    MISTRAL_API_KEY, CEREBRAS_API_KEY,
)

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = os.getenv("GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
GEMINI_BASE = os.getenv("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta/models")
OPENROUTER_ENDPOINT = os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
MISTRAL_ENDPOINT = os.getenv("MISTRAL_ENDPOINT", "https://api.mistral.ai/v1/chat/completions")
CEREBRAS_ENDPOINT = os.getenv("CEREBRAS_ENDPOINT", "https://api.cerebras.ai/v1/chat/completions")
# Kalitsiz bepul zaxira (Pollinations) — oxirgi chora sifatida
POLLINATIONS_ENDPOINT = os.getenv("POLLINATIONS_ENDPOINT", "https://text.pollinations.ai/openai")

# Model ro'yxati endpointlari (discovery uchun)
GROQ_MODELS_ENDPOINT = os.getenv("GROQ_MODELS_ENDPOINT", GROQ_ENDPOINT.replace("/chat/completions", "/models"))
GEMINI_MODELS_ENDPOINT = os.getenv("GEMINI_MODELS_ENDPOINT", GEMINI_BASE)
OPENROUTER_MODELS_ENDPOINT = os.getenv("OPENROUTER_MODELS_ENDPOINT", "https://openrouter.ai/api/v1/models")

# Timeout sozlamalari:
# - connect: birinchi ulanish uchun
# - sock_read: javob oqimini o'qish uchun (sekin modellar ham shu muddat ichida kelishi kerak)
REQUEST_TIMEOUT = max(30, int(os.getenv("AI_REQUEST_TIMEOUT", "45")))
CONNECT_TIMEOUT = max(5, int(os.getenv("AI_CONNECT_TIMEOUT", "10")))
MAX_429_RETRIES = 2
# Foydalanuvchi promptining maksimal uzunligi (token byudjetini himoya qiladi)
MAX_PROMPT_CHARS = max(500, int(os.getenv("AI_MAX_PROMPT_CHARS", "3000")))
# Bir vaqtda ko'pi bilan 2 ta AI so'rovi ishlaydi (bepul RPM limitlarini himoya qiladi)
MAX_CONCURRENT_AI = max(1, int(os.getenv("MAX_CONCURRENT_AI", "2")))
# Provayder 3 marta ketma-ket xato bersa — shuncha daqiqaga o'tkazib yuboriladi
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 600  # 10 daqiqa

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
# Gemini: gemini-2.5-flash — 2026-yil eng yaxshi bepul model (o'zbek tilini yaxshi tushunadi)
GEMINI_PREFERRED = [
    "gemini-2.5-flash",           # 1M kontekst, eng kuchli bepul model
    "gemini-2.5-flash-lite",      # Tez va bepul
    "gemini-2.0-flash",           # Tez ishora modeli
    "gemini-2.5-pro",             # Pro versiya (limit bor, lekin sifat yuqori)
    "gemini-1.5-flash",           # Zaxira (keng mavjud)
]
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

# Discovery ishlamasa ishlatiladigan zaxira ro'yxatlar
GEMINI_MODELS = list(GEMINI_PREFERRED)
GROQ_MODELS = list(GROQ_PREFERRED)
OPENROUTER_MODELS = list(OPENROUTER_PREFERRED)
MISTRAL_MODELS = list(MISTRAL_PREFERRED)
CEREBRAS_MODELS = list(CEREBRAS_PREFERRED)

# === Bitta umumiy aiohttp sessiya (singleton) ===
# Har so'rovda yangi sessiya ochish +300-800ms kechikish va TCP socket isrof qiladi.
# Singleton: ulanish qayta ishlatiladi, DNS keshlanadi, TCP handshake bir marta bo'ladi.
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()

# Discovery natijalari keshida: key -> (timestamp, [model_id, ...])
_model_cache: dict = {}

# Circuit breaker: provider_name -> {"fails": int, "until": float}
_BREAKERS: dict = {}

# Bir vaqtda 2 tadan ortiq AI so'rovi ishlamasligi uchun semafor
_AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI)


async def _get_session() -> aiohttp.ClientSession:
    """Singleton aiohttp sessiyasi — har so'rovda yangi sessiya ochilmaydi."""
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                timeout = aiohttp.ClientTimeout(
                    total=REQUEST_TIMEOUT,
                    connect=CONNECT_TIMEOUT,
                    sock_read=REQUEST_TIMEOUT,
                )
                connector = aiohttp.TCPConnector(
                    limit=20,           # maksimal parallel ulanishlar
                    ttl_dns_cache=300,  # DNS keshi — har so'rovda DNS so'rovi yo'q
                    enable_cleanup_closed=True,
                )
                _session = aiohttp.ClientSession(
                    timeout=timeout,
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

def clear_ai_context(user_id: int):
    """Yangi AI sessiyada u/agar so'ralsa, suhbat kontekstini tozalash."""
    if user_id is not None:
        _AI_CONTEXT.pop(user_id, None)


def _store_ai_context(user_id: int, text: str):
    if not user_id:
        return
    max_len = int(_RUNTIME_PARAMS.get("context_messages", 8) or 0)
    if max_len <= 0:
        return
    text = (text or "").strip()
    if not text:
        return
    # Xotirani cheklash: har bitta eslatilgan xabarni qisqartiramiz
    text = text[:2000]
    if len(_AI_CONTEXT) > _AI_CONTEXT_MAX_USERS:
        # Qadimgi foydalanuvchilardan tozalash
        for uid in list(_AI_CONTEXT.keys())[:_AI_CONTEXT_MAX_USERS // 10]:
            _AI_CONTEXT.pop(uid, None)
    entries = _AI_CONTEXT.setdefault(user_id, deque(maxlen=max_len))
    if not entries or entries[-1] != text:
        entries.append(text)


def _get_ai_context_text(user_id: int, budget: int) -> str:
    """So'nggi xabarlarni budget belgidan oshirmasdan qaytaradi."""
    if int(_RUNTIME_PARAMS.get("context_messages", 8) or 0) <= 0:
        return ""
    entries = _AI_CONTEXT.get(user_id)
    if not entries:
        return ""
    lines = [f"• {e}" for e in entries]
    block = "💬 <b>So'nggi suhbat (AI konteksti):</b>\n" + "\n".join(lines)
    return block[:max(0, int(budget))]


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

    chat_only=True bo'lsa, chat uchun yaroqsiz modellar (audio, guard va h.k.)
    filtrlangan holda afzal ro'yxatga kirmagan faol modellar ham qo'shiladi.
    """
    avail_set = set(available)
    picked = [m for m in preferred if m in avail_set]
    if chat_only:
        for m in available:
            if len(picked) >= 6:
                break
            if m in picked:
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
        async with session.get(f"{GEMINI_MODELS_ENDPOINT}?key={api_key}") as resp:
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
        async with session.get(GROQ_MODELS_ENDPOINT, headers=headers) as resp:
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
        async with session.get(OPENROUTER_MODELS_ENDPOINT) as resp:
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
            async with session.post(endpoint, headers=headers, json=payload) as resp:
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
        generation_config = {
            "temperature": params.get("temperature", 0.7),
            "topP": params.get("top_p", 0.95),
        }
        if params.get("max_tokens"):
            generation_config["maxOutputTokens"] = params["max_tokens"]

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
                async with session.post(url, json=payload) as resp:
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
            "temperature": params.get("temperature", 0.7),
        }
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("max_tokens") is not None:
            payload["max_tokens"] = params["max_tokens"]
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
            "temperature": params.get("temperature", 0.7),
        }
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("max_tokens") is not None:
            payload["max_tokens"] = params["max_tokens"]
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
            "temperature": params.get("temperature", 0.7),
            "safe_prompt": False,
        }
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("max_tokens") is not None:
            payload["max_tokens"] = params["max_tokens"]
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
            "temperature": params.get("temperature", 0.7),
        }
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("max_tokens") is not None:
            payload["max_tokens"] = params["max_tokens"]
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


async def _call_pollinations(prompt: str, system_instruction: str, params: dict = None) -> dict:
    """Kalitsiz bepul zaxira (Pollinations) — oxirgi chora."""
    params = params or get_runtime_params()
    payload = {
        "model": "openai-large",   # openai → openai-large (sifat yaxshilandi)
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
        ],
        "temperature": params.get("temperature", 0.7),
    }
    if params.get("top_p") is not None:
        payload["top_p"] = params["top_p"]
    if params.get("max_tokens") is not None:
        payload["max_tokens"] = params["max_tokens"]
    result = await _post_chat_completion(POLLINATIONS_ENDPOINT, None, payload)
    return _extract_json(result["content"])


def _clean_key(value: str) -> str:
    return (value or "").strip().replace('"', '').replace("'", "")


async def _run_ai_chain(prompt: str, system_instruction: str) -> dict:
    """6 ta provayderni navbat bilan sinaydi: Gemini → Groq → OpenRouter →
    Mistral → Cerebras → Pollinations (kalitsiz).

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

    providers = [
        ("Gemini", _call_gemini, (prompt, gemini_key, system_instruction, params), bool(gemini_key)),
        ("Groq", _call_groq, (prompt, groq_key, system_instruction, params), bool(groq_key)),
        ("OpenRouter", _call_openrouter, (prompt, openrouter_key, system_instruction, params), bool(openrouter_key)),
        ("Mistral", _call_mistral, (prompt, mistral_key, system_instruction, params), bool(mistral_key)),
        ("Cerebras", _call_cerebras, (prompt, cerebras_key, system_instruction, params), bool(cerebras_key)),
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
            "Kalitlarni Render → Environment bo'limiga qo'shing va botni qayta ishga tushiring."
        )
    }


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
    _store_ai_context(user_id, raw_prompt)

    # Suhbat kontekstini joriy xabarga qo'shamiz. Byudjetni shunday hisoblaymiz:
    # kontekst joriy xabarni kesib tashlamasligi kerak.
    max_chars = int(params.get("max_prompt_chars") or MAX_PROMPT_CHARS)
    budget = max(200, max_chars - len(raw_prompt) - 300)
    ctx_text = _get_ai_context_text(user_id, budget)
    if ctx_text:
        prompt = f"{ctx_text}\n\nHozirgi xabar:\n{raw_prompt}"

    result = await _run_ai_chain(prompt, _get_router_system_instruction())
    if "error" in result:
        return result
    return _normalize_router_result(result)


async def extract_schedule_time(prompt: str, user_id: int = 0) -> dict:
    """Yengil AI rejimi — faqat erkin tildagi vaqtni (yoki savolni) ajratadi.

    Postni qaytadan tahlil qilmaydi, kam token sarflaydi. Qaytargan maydonlar:
      - has_explicit_time: True bo'lsa scheduled_time mavjud
      - scheduled_time: 'YYYY-MM-DD HH:MM' yoki None
      - reply: foydalanuvchi savol bergan bo'lsa, qisqa javob
      - target_all: bool
    """
    result = await _run_ai_chain(prompt, _get_time_system_instruction())
    if "error" in result:
        return result
    norm = _normalize_router_result(result)
    norm["intent"] = "time"
    return norm
