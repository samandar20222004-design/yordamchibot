import json
import logging
from datetime import datetime
import pytz
import aiohttp
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Foydalanuvchi matnini aiohttp orqali Groq API ga yuboradi va JSON formatida javob oladi.
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
1. Foydalanuvchi so'ragan mavzuda (she'r so'ralsa qofiyali chiroyli she'r, post so'ralsa emojilarga boy, xatboshili jozibali post) yozib berish.
2. Agar foydalanuvchi chiqish vaqtini aytgan bo'lsa (masalan: "bugun soat 18:50 ga", "ertaga 10:00 da"), uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatiga o'tkazing. Agar vaqt aytilmagan bo'lsa, scheduled_time ni null qiling.

Javobni FAQAT quyidagi toza JSON formatida qaytaring, ortiqcha hech qanday matn qo'shmang:
{{
    "post_text": "Tayyorlangan she'r yoki post matni...",
    "scheduled_time": "YYYY-MM-DD HH:MM" yoki null,
    "has_schedule": true yoki false
}}
"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json",
    }

    models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7
        }

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(GROQ_ENDPOINT, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        content = res_json["choices"][0]["message"]["content"]
                        return json.loads(content)
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Groq API ({model}) xatosi HTTP {resp.status}: {err_text}")
        except Exception as e:
            logger.warning(f"Model {model} so'rovida xato: {e}")
            continue

    return {"error": "AI serveri javob bermadi. Iltimos, bir ozdan so'ng qayta urinib ko'ring."}
