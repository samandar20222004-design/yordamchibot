import json
import logging
from datetime import datetime
import pytz
import aiohttp
from config import GEMINI_API_KEY, GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

def _clean_json_string(raw_str: str) -> str:
    """JSON matnidan Markdown bloklarini tozalash."""
    raw_str = raw_str.strip()
    if raw_str.startswith("```json"):
        raw_str = raw_str[7:]
    elif raw_str.startswith("```"):
        raw_str = raw_str[3:]
    if raw_str.endswith("```"):
        raw_str = raw_str[:-3]
    return raw_str.strip()

def _get_system_instruction() -> str:
    """Ikkala sun'iy intellekt uchun yagona va aqlli ko'rsatma."""
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    return (
        f"Siz Telegram kanallar uchun professional SMM mutaxassisi va aqlli ijodiy yordamchisiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, joriy yil: {current_year}.\n\n"
        f"Vazifangiz:\n"
        f"1. Foydalanuvchi yuborgan xabar (matn, rasm izohi, reklama loyihasi, taklifnoma yoki buyruq)ni to'liq tushuning.\n"
        f"2. Agar post tayyorlash so'ralgan bo'lsa yoki reklama/xizmat haqida yozilgan bo'lsa, uni Telegram kanalga moslab, "
        f"chiroyli paragraflar, mos emojilar va aniq aloqa ma'lumotlari bilan tayyorlang.\n"
        f"3. Agar xabarda aniq chiqish vaqti ko'rsatilgan bo'lsa (masalan: 'bugun 18:00 ga', 'ertaga soat 10 da', '15 daqiqadan keyin'), "
        f"uni hisoblab 'YYYY-MM-DD HH:MM' formatida yozing. Agar vaqt aytilmagan bo'lsa, scheduled_time qiymatini null qiling.\n"
        f"4. MUHIM: Javobni FAQAT quyidagi JSON formatida qaytaring, boshqa hech qanday ortiqcha gap yozmang:\n"
        f"{{\n"
        f'  "post_text": "Kanal uchun tayyor chiroyli post matni...",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "is_post": true\n'
        f"}}"
    )

async def _call_gemini(prompt: str, api_key: str, system_instruction: str) -> dict:
    """1-bosqich: Google Gemini API orqali so'rov yuborish."""
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=){api_key}"
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_instruction}\n\nFoydalanuvchi so'rovi:\n{prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.7
        }
    }

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = _clean_json_string(raw_text)
                return json.loads(cleaned)
            else:
                err_text = await resp.text()
                raise RuntimeError(f"Gemini HTTP {resp.status}: {err_text[:120]}")

async def _call_groq(prompt: str, api_key: str, system_instruction: str) -> dict:
    """2-bosqich (Zaxira): Groq API orqali so'rov yuborish."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    models = ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile"]
    last_err = ""
    
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.6
        }

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_ENDPOINT, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        raw_content = res_json["choices"][0]["message"]["content"]
                        clean_content = _clean_json_string(raw_content)
                        return json.loads(clean_content)
                    else:
                        last_err = f"HTTP {resp.status}"
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(f"Groq xatosi: {last_err}")

async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Asosiy funksiya:
    1. Avval Google Gemini API orqali ishlaydi.
    2. Agar Gemini band bo'lsa yoki limiti tugasa, avtomatik Groq zaxirasiga o'tadi.
    """
    gemini_key = (GEMINI_API_KEY or "").strip().replace('"', '').replace("'", "")
    groq_key = (GROQ_API_KEY or "").strip().replace('"', '').replace("'", "")
    
    system_instruction = _get_system_instruction()

    # 1. Google Gemini bilan sinash
    if gemini_key:
        try:
            logger.info("AI so'rovi Google Gemini API ga yuborilmoqda...")
            result = await _call_gemini(prompt, gemini_key, system_instruction)
            if "post_text" in result:
                return result
        except Exception as e:
            logger.warning(f"Google Gemini ishlamadi ({e}). Groq zaxirasiga o'tilmoqda...")

    # 2. Groq bilan sinash (Zaxira)
    if groq_key:
        try:
            logger.info("AI so'rovi Groq API ga yuborilmoqda...")
            result = await _call_groq(prompt, groq_key, system_instruction)
            if "post_text" in result:
                return result
        except Exception as e:
            logger.error(f"Groq API ham ishlamadi: {e}")
            return {"error": f"AI xizmatlarida xatolik yuz berdi: {e}"}

    return {"error": "AI kalitlari (GEMINI_API_KEY yoki GROQ_API_KEY) topilmadi yoki barchasi band."}
