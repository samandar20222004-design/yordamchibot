import asyncio
import json
import logging
import os
import time as _time
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

REQUEST_TIMEOUT = 30
MAX_429_RETRIES = 2
# Foydalanuvchi promptining maksimal uzunligi (token byudjetini himoya qiladi)
MAX_PROMPT_CHARS = 3000
# Bir vaqtda ko'pi bilan 2 ta AI so'rovi ishlaydi (bepul RPM limitlarini himoya qiladi)
MAX_CONCURRENT_AI = max(1, int(os.getenv("MAX_CONCURRENT_AI", "2")))
# Provayder 3 marta ketma-ket xato bersa — shuncha daqiqaga o'tkazib yuboriladi
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 600  # 10 daqiqa

# Modellarni runtime'da aniqlash (yoqilgan bo'lsa). Provayderlar modellarni
# tez-tez almashtiradi (decommission), shuning uchun qo'lda yozilgan ro'yxat
# doim eskirib qoladi. Discovery buni avtomatik hal qiladi.
AI_MODEL_DISCOVERY = os.getenv("AI_MODEL_DISCOVERY", "1") == "1"
MODEL_CACHE_TTL = 6 * 3600  # aniqlangan ro'yxat 6 soat eslab qolinadi

# Afzal (preferred) modellar — discovery ishlamasa yoki aniqlanmasa ishlatiladi.
# 2026-08 holatiga ko'ra bepul (free tier) modellar.
GEMINI_PREFERRED = [
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]
GROQ_PREFERRED = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "moonshotai/kimi-k2-instruct",
    "minimaxai/minimax-m2.7",
    "groq/compound",
    "groq/compound-mini",
]
OPENROUTER_PREFERRED = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-7b-instruct:free",
    "google/gemma-2-9b-it:free",
]
MISTRAL_PREFERRED = [
    "mistral-small-latest",
    "open-mistral-nemo",
    "ministral-8b-latest",
]
CEREBRAS_PREFERRED = [
    "gpt-oss-120b",
    "llama3.1-8b",
    "llama-3.3-70b",
]

# Discovery ishlamasa ishlatiladigan zaxira ro'yxatlar
GEMINI_MODELS = list(GEMINI_PREFERRED)
GROQ_MODELS = list(GROQ_PREFERRED)
OPENROUTER_MODELS = list(OPENROUTER_PREFERRED)
MISTRAL_MODELS = list(MISTRAL_PREFERRED)
CEREBRAS_MODELS = list(CEREBRAS_PREFERRED)

# Bitta umumiy aiohttp sessiya — har so'rovda yangi sessiya ochish o'rniga
# qayta ishlatiladi (TCP ulanishlar soni va xotira kamayadi).
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()

# Discovery natijalari keshida: key -> (timestamp, [model_id, ...])
_model_cache: dict = {}

# Circuit breaker: provider_name -> {"fails": int, "until": float}
_BREAKERS: dict = {}

# Bir vaqtda 2 tadan ortiq AI so'rovi ishlamasligi uchun semafor
_AI_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_AI)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=10)
                _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def close_ai_session():
    """Bot to'xtatilganda AI sessiyasini yopish."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


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
    """Intent routing: har qanday xabarni 3 yo'nalishdan biriga ajratadi."""
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    return (
        f"Siz Telegram kanallarni boshqarish va postlarni rejalashtirish bo'yicha professional, "
        f"xushmuomala, o'zbek tilida javob beradigan aqlli yordamchisiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, joriy yil: {current_year}.\n\n"
        f"Vazifangiz — foydalanuvchining xabarini tahlil qilib, UNING NIYATINI aniqlash. "
        f"Javobni FAQAT bitta JSON obyekti sifatida qaytaring. Niyat turlari:\n\n"
        f'1) "faq" — SAVOL-JAVOB / SUHBAT:\n'
        f"   • Foydalanuvchi bot imkoniyatlari, post rejalashtirish, ballar (AI so'rovlari), "
        f"kanal ulash, reaksiyalar, avto-o'chirish, kunlik bonus, ball ulashish yoki botning "
        f"boshqa funksiyalari haqida so'rasa, salomlashsa yoki yordam so'rasa — to'g'ridan-to'g'ri "
        f"aniq, foydali va muloyim javob bering. Javobni \"reply\" maydoniga yozing.\n"
        f"   • Mavzu botga mutlaqo aloqador bo'lmasa (siyosat, ob-havo, dasturlash, shaxsiy "
        f"suhbat va h.k.) — \"reply\" maydoniga quyidagicha yozing: "
        f"\"Kechirasiz, men faqat Telegram kanallarni boshqarish va postlarni rejalashtirish "
        f"bo'yicha yordam bera olaman. Post rejalashtirish uchun menga post matnini yoki "
        f"rasm/forward xabarni yuboring yoki savolingizni bering.\"\n\n"
        f'2) "post" — YANGI POST YARATISH yoki TAYYOR POST QABUL QILISH:\n'
        f"   • Yangi post/tabrik/she'r/e'lon yozish so'ralsa — jozibador, professional post tayyorlang. "
        f"Matnni \"post_text\" maydoniga yozing.\n"
        f"   • Tayyor post, yangilik yoki e'lon forward qilingan / yuborilgan bo'lsa — uning "
        f"matnini BUZMASDAN, to'liq, asl ko'rinishida \"post_text\" ga ko'chiring.\n"
        f"   • Aniq chiqish vaqti aytilgan bo'lsa ('bugun 15:45 ga', 'ertaga ertalab 9 da', "
        f"'10 daqiqadan keyin') — uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatida "
        f'"scheduled_time" ga yozing va "has_explicit_time" ni true qiling. Vaqt aniq '
        f"ko'rsatilmagan bo'lsa — scheduled_time: null, has_explicit_time: false.\n"
        f"   • 'Barcha kanallarga', 'hamma guruhlarga', 'hamma kanalga' deyilgan bo'lsa — "
        f'"target_all": true, aks holda false.\n\n'
        f'3) "edit" — MAVJUD POSTNI TAHRIRLASH:\n'
        f"   • Foydalanuvchi oldin yuborgan postni o'zgartirishni so'rasa (masalan: 'oxiriga "
        f"telefon raqam qo'sh', 'sarlavhasini o'zgartir', 'matnni qisqartir', 'emoji qo'sh') — "
        f"tahrirlangan, TAYYOR post matnini \"post_text\" ga yozing. Vaqt ma'lumoti saqlanadi.\n\n"
        f"QOIDALAR:\n"
        f"• Vaqt hisobini faqat Toshkent vaqti (UTC+5) bo'yicha qiling.\n"
        f"• Niyat faqat bitta bo'ladi. Savol va post aralash kelsa, asosiy niyatni tanlang.\n"
        f"• JSON dan boshqa hech narsa yozmang. Majburiy format:\n"
        f"{{\n"
        f'  "intent": "faq | post | edit",\n'
        f'  "reply": "faq niyatidagi javob matni (boshqa hollarda bo\'sh satr)",\n'
        f'  "post_text": "post/edit niyatidagi post matni (boshqa hollarda bo\'sh satr)",\n'
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
        f"Siz Telegram post rejalashtiruvchi botning yordamchisisiz. Hozirgi Toshkent vaqti: "
        f"{now_str}, joriy yil: {current_year}.\n\n"
        f"Foydalanuvchining xabarini tahlil qiling va FAQAT bitta JSON qaytaring:\n"
        f"• Agar xabarda post chiqish VAQTI ko'rsatilgan bo'lsa (masalan: '15:45 ga', 'ertaga "
        f"ertalab 9 da', 'bugun kechqurun 20:00', '1 soatdan keyin', '5 daqiqadan keyin', "
        f"'2-sentyabr 10:00') — vaqtni Toshkent vaqti bo'yicha hisoblab 'YYYY-MM-DD HH:MM' "
        f'formatida "scheduled_time" ga yozing, "has_explicit_time": true.\n'
        f"• Agar xabar vaqt emas, balki savol yoki boshqa gap bo'lsa — "
        f'"has_explicit_time": false, "scheduled_time": null, "reply" maydoniga qisqa, '
        f"muloyim javob yozing.\n"
        f"• 'Barcha kanallarga' deyilgan bo'lsa \"target_all\": true.\n\n"
        f"JSON formati:\n"
        f"{{\n"
        f'  "intent": "faq | post",\n'
        f'  "reply": "savol bo\'lsa javob, aks holda bo\'sh satr",\n'
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


async def _call_gemini(prompt: str, api_key: str, system_instruction: str) -> dict:
    session = await _get_session()
    models = await _discover_gemini_models(api_key) or GEMINI_MODELS
    last_err = ""

    for model in models:
        url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\nFoydalanuvchi so'rovi va kontent:\n{prompt}\n\nJavobni FAQAT toza JSON formatida yozing."}
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2},
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
                    resp_txt = await resp.text()
                    last_err = f"Gemini ({model}) HTTP {resp.status}: {resp_txt[:100]}"
            except asyncio.TimeoutError:
                last_err = f"Gemini ({model}) timeout"
                continue
            except Exception as e:
                last_err = f"Gemini ({model}): {e}"
                continue

    raise RuntimeError(last_err or "Gemini noma'lum xato")


async def _call_groq(prompt: str, api_key: str, system_instruction: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    models = await _discover_groq_models(api_key) or GROQ_MODELS
    last_err = ""

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": f"{system_instruction}\nJavobni faqat JSON formatida yozing."},
                {"role": "user", "content": f"{prompt}\n\nJavobni JSON formatida qaytaring."}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
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


async def _call_openrouter(prompt: str, api_key: str, system_instruction: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    models = await _discover_openrouter_models(api_key) or OPENROUTER_MODELS
    last_err = ""

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT quyidagi JSON formatida qaytaring:\n{{\"post_text\": \"...\", \"scheduled_time\": \"YYYY-MM-DD HH:MM yoki null\", \"has_explicit_time\": true, \"target_all\": false}}"},
            ],
            "temperature": 0.2,
        }
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


async def _call_mistral(prompt: str, api_key: str, system_instruction: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_err = ""

    for model in MISTRAL_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
            "temperature": 0.2,
            "safe_prompt": False,
        }
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


async def _call_cerebras(prompt: str, api_key: str, system_instruction: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_err = ""

    for model in CEREBRAS_MODELS:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
            ],
            "temperature": 0.2,
        }
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


async def _call_pollinations(prompt: str, system_instruction: str) -> dict:
    """Kalitsiz bepul zaxira (Pollinations) — oxirgi chora."""
    payload = {
        "model": "openai",
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"{prompt}\n\nJavobni FAQAT JSON formatida qaytaring."},
        ],
        "temperature": 0.2,
    }
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
    - Prompt MAX_PROMPT_CHARS (3000) belgidan oshsa kesiladi.
    Muvaffaqiyatda provayder qaytargan JSON dict qaytadi; xatolikda {"error": ...}.
    """
    # Prompt uzunligini cheklash (bepul token byudjetini himoya qilish)
    prompt = (prompt or "").strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n…(matn juda uzun edi, kesildi)"

    gemini_key = _clean_key(GEMINI_API_KEY)
    groq_key = _clean_key(GROQ_API_KEY)
    openrouter_key = _clean_key(OPENROUTER_API_KEY)
    mistral_key = _clean_key(MISTRAL_API_KEY)
    cerebras_key = _clean_key(CEREBRAS_API_KEY)

    providers = [
        ("Gemini", _call_gemini, (prompt, gemini_key, system_instruction), bool(gemini_key)),
        ("Groq", _call_groq, (prompt, groq_key, system_instruction), bool(groq_key)),
        ("OpenRouter", _call_openrouter, (prompt, openrouter_key, system_instruction), bool(openrouter_key)),
        ("Mistral", _call_mistral, (prompt, mistral_key, system_instruction), bool(mistral_key)),
        ("Cerebras", _call_cerebras, (prompt, cerebras_key, system_instruction), bool(cerebras_key)),
        ("Pollinations", _call_pollinations, (prompt, system_instruction), True),
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
