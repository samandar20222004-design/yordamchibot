import json
import logging
import time
from datetime import datetime
import pytz
from groq import Groq
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Foydalanuvchi matnini Groq orqali tezkor tahlil qiladi va post/she'r tayyorlaydi.
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

    # Modellarni navbat bilan sinab ko'ramiz (asosiy va zaxira)
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    last_error = ""

    for model_name in models:
        try:
            client = Groq(api_key=GROQ_API_KEY.strip(), timeout=15.0)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return data
        except Exception as e:
            logger.warning(f"Model {model_name} xatosi: {e}")
            last_error = str(e)
            continue

    return {"error": f"AI bilan bog'lanishda xatolik: {last_error}"}
