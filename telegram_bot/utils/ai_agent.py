import json
import logging
from datetime import datetime
import pytz
import aiohttp
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

def _clean_json_string(raw_str: str) -> str:
    """Markdown bloklarni tozalash (```json ... ```)."""
    raw_str = raw_str.strip()
    if raw_str.startswith("```json"):
        raw_str = raw_str[7:]
    elif raw_str.startswith("```"):
        raw_str = raw_str[3:]
    if raw_str.endswith("```"):
        raw_str = raw_str[:-3]
    return raw_str.strip()

async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Foydalanuvchi matnini Groq API orqali tahlil qiladi va post/she'r yaratadi.
    """
    api_key = (GROQ_API_KEY or "").strip().replace('"', '').replace("'", "")
    
    if not api_key:
        logger.error("GROQ_API_KEY topilmadi!")
        return {"error": "GROQ_API_KEY topilmadi. Render Environment bo'limida kalitni tekshiring."}

    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    system_instruction = (
        f"Siz Telegram kanallar uchun professional SMM mutaxassisi va shoirsiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, yil: {current_year}.\n"
        f"Vazifangiz: Foydalanuvchi so'roviga asosan chiroyli she'r yoki post tayyorlash va agar vaqt aytilgan bo'lsa uni aniqlash.\n"
        f"MUHIM: Javobingizni FAQAT quyidagi JSON formatida qaytaring:\n"
        f"{{\n"
        f'  "post_text": "Tayyor post yoki she\'r matni...",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "has_schedule": true\n'
        f"}}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Bepul tarifda 100% ishlaydigan modellar ro'yxati
    models_to_try = [
        "llama-3.3-70b-versatile",
        "llama3-70b-8192",
        "llama3-8b-8192"
    ]
    last_err_msg = ""

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"JSON formatida javob bering: {prompt}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7
        }

        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_ENDPOINT, headers=headers, json=payload) as resp:
                    resp_text = await resp.text()
                    
                    if resp.status == 200:
                        res_json = json.loads(resp_text)
                        raw_content = res_json["choices"][0]["message"]["content"]
                        clean_content = _clean_json_string(raw_content)
                        parsed = json.loads(clean_content)
                        return parsed
                    else:
                        logger.warning(f"Groq ({model}) xatosi {resp.status}: {resp_text}")
                        last_err_msg = f"HTTP {resp.status}: {resp_text[:100]}"
        except Exception as e:
            logger.warning(f"Model {model} ulanish xatosi: {e}")
            last_err_msg = str(e)
            continue

    return {"error": f"AI server xatosi: {last_err_msg}"}
