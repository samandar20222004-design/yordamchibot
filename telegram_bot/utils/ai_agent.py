import json
import logging
from datetime import datetime
import pytz
import aiohttp
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Foydalanuvchi matnini aiohttp orqali to'g'ridan-to'g'ri Groq REST API ga yuboradi.
    Httpx yoki proxies kutubxonalari ziddiyatidan mutlaqo xoli va juda tez ishlaydi.
    """
    if not GROQ_API_KEY or GROQ_API_KEY.strip() == "":
        logger.error("GROQ_API_KEY topilmadi!")
        return {"error": "GROQ_API_KEY sozlanmagan. Iltimos, Render boshqaruv panelida (Environment) kalitni kiriting."}

    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    system_instruction = f"""
Siz professional Telegram SMM mutaxassisi, shoir va ijodiy yordamchisisiz.
Hozirgi sana va vaqt: {now_str} (Toshkent vaqti, joriy yil: {current_year}).

Foydalanuvchi sizga erkin matn yozadi (she'r, tabrik, e'lon, reklama yoki yangilik haqida).

Sizning vazifangiz:
1. Foydalanuvchi so'ragan mavzuda (agar she'r so'ralsa chiroyli, qofiyali she'r; agar post so'ralsa emojilarga boy, xatboshili jozibali post) yozib berish.
2. Agar foydalanuvchi chiqish vaqtini aytgan bo'lsa (masalan: "bugun soat 18:50 ga", "ertaga 10:00 da"), uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatiga o'tkazing. Agar vaqt aytilmagan bo'lsa, scheduled_time ni null qiling.

Javobni FAQAT quyidagi toza JSON formatida qaytaring, hech qanday boshqa matn qo'shmang:
{{
    "post_text": "Tayyorlangan she'r yoki post matni...",
    "scheduled_time": "YYYY-MM-DD HH:MM" yoki null,
    "has_schedule": true yoki false
}}
"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    logger.error(f"Groq API HTTP {resp.status}: {err_body}")
                    return {"error": f"Groq serveridan xatolik (HTTP {resp.status})"}

                res_json = await resp.json()
                content = res_json["choices"][0]["message"]["content"]
                return json.loads(content)
    except Exception as e:
        logger.error(f"AI so'rovida xatolik: {e}")
        return {"error": f"AI bilan bog'lanishda xatolik: {e}"}
