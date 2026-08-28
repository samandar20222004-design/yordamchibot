import json
import logging
import time
from datetime import datetime
import pytz
from groq import Groq
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

# Foydalanuvchilarning oxirgi so'rov vaqtini xotirada saqlash (Anti-Flood)
_USER_LAST_REQUEST = {}

def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    """
    Foydalanuvchi matnini Groq orqali tahlil qiladi.
    Anti-flood himoyasi bilan ortiqcha yuklamaning oldini oladi.
    """
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY topilmadi!")
        return {"error": "GROQ_API_KEY sozlanmagan. Iltimos, kalitni kiriting."}

    # Anti-Flood tekshiruvi: 1 ta foydalanuvchi har 3 soniyada ko'pi bilan 1 ta AI so'rov bera oladi
    now_ts = time.time()
    last_ts = _USER_LAST_REQUEST.get(user_id, 0)
    if now_ts - last_ts < 3:
        return {"error": "Juda ko'p so'rov yubordingiz. Iltimos, 3 soniya kuting."}
    _USER_LAST_REQUEST[user_id] = now_ts

    client = Groq(api_key=GROQ_API_KEY)
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    system_instruction = f"""
Siz professional Telegram SMM mutaxassisi va yordamchisisiz.
Hozirgi sana va vaqt: {now_str} (Toshkent vaqti, joriy yil: {current_year}).

Foydalanuvchi sizga erkin matn yozadi (o'zbek tilida, shevalar yoki qisqartmalar 'h.k.', 'va h.k.', 'ertaga', 'bugun kechki payt', 'aksiya' va h.k. bo'lishi mumkin).

Sizning vazifangiz:
1. Foydalanuvchi so'ragan mavzuda Telegram uchun chiroyli, emojilarga boy, xatboshilarga ega va mos heshteglari bor jozibali post matnini yozish.
2. Agar foydalanuvchi post chiqish vaqtini aytgan bo'lsa (masalan: "ertaga soat 10 da", "bugun 18:00 ga", "2 kundan keyin"), uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatiga o'tkazish. Agar vaqt aytilmagan bo'lsa, scheduled_time ni null qiling.

Javobni FAQAT quyidagi JSON formatida qaytaring, ortiqcha hech qanday matn qo'shmang:
{{
    "post_text": "Tayyorlangan chiroyli post matni...",
    "scheduled_time": "YYYY-MM-DD HH:MM" yoki null,
    "has_schedule": true yoki false
}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.6,
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        return data
    except Exception as e:
        logger.error(f"Groq AI xatosi: {e}")
        err_msg = str(e)
        if "429" in err_msg:
            return {"error": "AI serverida so'rovlar limiti to'ldi. Iltimos, 1 daqiqadan so'ng qayta urinib ko'ring."}
        return {"error": f"AI xatolik berdi: {err_msg}"}
