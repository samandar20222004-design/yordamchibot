import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime
import pytz
import aiohttp
from config import GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = os.getenv("GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
GEMINI_BASE = os.getenv("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta/models")
OPENROUTER_ENDPOINT = os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
# Kalitsiz bepul zaxira (Pollinations) — oxirgi chora sifatida
POLLINATIONS_ENDPOINT = os.getenv("POLLINATIONS_ENDPOINT", "https://text.pollinations.ai/openai")

# Model ro'yxati endpointlari (discovery uchun)
GROQ_MODELS_ENDPOINT = os.getenv("GROQ_MODELS_ENDPOINT", GROQ_ENDPOINT.replace("/chat/completions", "/models"))
GEMINI_MODELS_ENDPOINT = os.getenv("GEMINI_MODELS_ENDPOINT", GEMINI_BASE)
OPENROUTER_MODELS_ENDPOINT = os.getenv("OPENROUTER_MODELS_ENDPOINT", "https://openrouter.ai/api/v1/models")

REQUEST_TIMEOUT = 30
MAX_429_RETRIES = 2

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

# Discovery ishlagan taqdirda ishlatiladigan zaxira ro'yxatlar
GEMINI_MODELS = list(GEMINI_PREFERRED)
GROQ_MODELS = list(GROQ_PREFERRED)
OPENROUTER_MODELS = list(OPENROUTER_PREFERRED)

# Bitta umumiy aiohttp sessiya — har so'rovda yangi sessiya ochish o'rniga
# qayta ishlatiladi (TCP ulanishlar soni va xotira kamayadi).
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()

# Discovery natijalari keshida: key -> (timestamp, [model_id, ...])
_model_cache: dict = {}


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


def _get_system_instruction() -> str:
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    return (
        f"Siz Telegram kanallar uchun professional, aqlli SMM yordamchisiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, joriy yil: {current_year}.\n\n"
        f"Vazifangiz:\n"
        f"1. Foydalanuvchi yuborgan kontentni (matn, rasm izohi yoki forward post) tahlil qiling.\n"
        f"2. Agar tayyor post yoki yangilik forward qilingan bo'lsa, uning matnini buzmasdan, to'liq va asl holicha saqlang.\n"
        f"3. Agar yangi post yoki she'r yozish buyurilgan bo'lsa, jozibador post tayyorlang.\n"
        f"4. VAQTNI ANIQLASH: Agar xabarda aniq chiqish vaqti aytilgan bo'lsa (masalan: 'bugun 13:00 ga', 'ertaga 10:00 da', '15 daqiqadan keyin'), "
        f"uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatida yozing va has_explicit_time qiymatini true qiling.\n"
        f"5. Agar xabarda aniq vaqt aytilmagan bo'lsa, scheduled_time qiymatini null qiling va has_explicit_time qiymatini false qiling.\n"
        f"6. Agar xabarda 'barcha kanallarga' yoki 'hamma guruhlarga' deyilgan bo'lsa, target_all qiymatini true qiling, aks holda false.\n"
        f"7. MUHIM: Javobni FAQAT quyidagi JSON formatida qaytaring, boshqa hech narsa yozmang:\n"
        f"{{\n"
        f'  "post_text": "Post matni...",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "has_explicit_time": true,\n'
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


async def _call_pollinations(prompt: str, system_instruction: str) -> dict:
    """Kalitsiz bepul zaxira (Pollinations) — oxirgi chora.

    Agar bu ham ishlamasa, faqat log yoziladi va xato hisobotga qo'shiladi.
    """
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


async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    gemini_key = _clean_key(GEMINI_API_KEY)
    groq_key = _clean_key(GROQ_API_KEY)
    openrouter_key = _clean_key(OPENROUTER_API_KEY)

    system_instruction = _get_system_instruction()
    errors = []

    # 1. Gemini (bepul, eng keng limitlar)
    if gemini_key:
        try:
            result = await _call_gemini(prompt, gemini_key, system_instruction)
            if isinstance(result, dict) and "post_text" in result:
                return result
            errors.append("Gemini: javob formati noto'g'ri")
        except Exception as e:
            errors.append(f"Gemini: {e}")
            logger.warning("Gemini ishlamadi (%s). Keyingi zaxiraga o'tilmoqda...", e)
    else:
        errors.append("Gemini: kalit topilmadi")

    # 2. Groq (bepul, tez)
    if groq_key:
        try:
            result = await _call_groq(prompt, groq_key, system_instruction)
            if isinstance(result, dict) and "post_text" in result:
                return result
            errors.append("Groq: javob formati noto'g'ri")
        except Exception as e:
            errors.append(f"Groq: {e}")
            logger.warning("Groq ishlamadi (%s). Keyingi zaxiraga o'tilmoqda...", e)
    else:
        errors.append("Groq: kalit topilmadi")

    # 3. OpenRouter (ixtiyoriy, :free modellar)
    if openrouter_key:
        try:
            result = await _call_openrouter(prompt, openrouter_key, system_instruction)
            if isinstance(result, dict) and "post_text" in result:
                return result
            errors.append("OpenRouter: javob formati noto'g'ri")
        except Exception as e:
            errors.append(f"OpenRouter: {e}")
            logger.warning("OpenRouter ishlamadi (%s). Keyingi zaxiraga o'tilmoqda...", e)
    else:
        errors.append("OpenRouter: kalit topilmadi (ixtiyoriy)")

    # 4. Kalitsiz bepul zaxira — Pollinations (oxirgi chora)
    try:
        result = await _call_pollinations(prompt, system_instruction)
        if isinstance(result, dict) and "post_text" in result:
            return result
        errors.append("Pollinations: javob formati noto'g'ri")
    except Exception as e:
        errors.append(f"Pollinations: {e}")
        logger.warning("Pollinations ishlamadi (%s)", e)

    detail = "\n".join(f"• {e}" for e in errors if e)
    return {
        "error": (
            "⚠️ AI xizmatlarining hech biri javob bermadi:\n"
            f"{detail}\n\n"
            "💡 <b>Bepul kalit olish:</b>\n"
            "• Gemini: aistudio.google.com → API key (kuniga 1500 so'rov bepul)\n"
            "• Groq: console.groq.com → API key (kuniga 1000 so'rov bepul)\n"
            "Kalitni Render → Environment → GEMINI_API_KEY / GROQ_API_KEY ga qo'shing."
        )
    }
