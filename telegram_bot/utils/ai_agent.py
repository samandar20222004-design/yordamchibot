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
    """Markdown JSON bloklarini tozalash."""
    raw_str = raw_str.strip()
    if raw_str.startswith("```json"):
        raw_str = raw_str[7:]
    elif raw_str.startswith("```"):
        raw_str = raw_str[3:]
    if raw_str.endswith("```"):
        raw_str = raw_str[:-3]
    return raw_str.strip()

def _get_system_instruction() -> str:
    now_dt = datetime.now(tashkent_tz)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")
    current_year = now_dt.year

    return (
        f"Siz Telegram kanallar uchun professional, o'ta aqlli SMM yordamchisiz. "
        f"Hozirgi Toshkent vaqti: {now_str}, joriy yil: {current_year}.\n\n"
        f"Vazifangiz:\n"
        f"1. Foydalanuvchining buyrug'i va yuborilgan kontentni (matn, forward post yoki rasm) tahlil qiling.\n"
        f"2. Agar foydalanuvchi tayyor postni kanalga qo'yishni so'ragan bo'lsa (masalan: 'shuni 13:00 ga qo'y'), post matnini o'zgartirmasdan, asl holicha saqlang.\n"
        f"3. Agar yangi post yoki she'r yozishni so'ragan bo'lsa, mavzuga mos, chiroyli post tayyorlang.\n"
        f"4. Chiqish vaqti aytilgan bo'lsa (masalan: 'bugun 13:00 ga', 'ertaga 18:00 da', '5 daqiqadan keyin'), uni Toshkent vaqti bo'yicha 'YYYY-MM-DD HH:MM' formatida aniqlang. Agar vaqt aytilmagan bo'lsa, scheduled_time null bo'lsin.\n"
        f"5. Agar xabarda 'barcha guruhlarga' yoki 'hamma kanallarga' deyilgan bo'lsa, target_all qiymatini true qiling, aks holda false.\n"
        f"6. MUHIM: Javobni FAQAT quyidagi JSON formatida qaytaring:\n"
        f"{{\n"
        f'  "post_text": "Post matni...",\n'
        f'  "scheduled_time": "YYYY-MM-DD HH:MM yoki null",\n'
        f'  "target_all": false\n'
        f"}}"
    )

async def _call_gemini(prompt: str, api_key: str, system_instruction: str) -> dict:
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=){api_key}"
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_instruction}\n\nFoydalanuvchi so'rovi va kontent:\n{prompt}\n\nJavobni JSON formatida qaytaring."}
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.3
        }
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = _clean_json_string(raw_text)
                return json.loads(cleaned)
            else:
                err_text = await resp.text()
                raise RuntimeError(f"Gemini HTTP {resp.status}: {err_text[:100]}")

async def _call_groq(prompt: str, api_key: str, system_instruction: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    last_err = ""
    
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"{prompt}\n\nIltimos, javobni faqat JSON formatida qaytaring."}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3
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
                        resp_txt = await resp.text()
                        last_err = f"HTTP {resp.status}: {resp_txt[:100]}"
        except Exception as e:
            last_err = str(e)
            continue

    raise RuntimeError(f"Groq xatosi: {last_err}")

async def analyze_user_prompt(prompt: str, user_id: int = 0) -> dict:
    gemini_key = (GEMINI_API_KEY or "").strip().replace('"', '').replace("'", "")
    groq_key = (GROQ_API_KEY or "").strip().replace('"', '').replace("'", "")
    
    system_instruction = _get_system_instruction()

    # 1. Google Gemini orqali urinish
    if gemini_key:
        try:
            result = await _call_gemini(prompt, gemini_key, system_instruction)
            if "post_text" in result:
                return result
        except Exception as e:
            logger.warning(f"Google Gemini ishlamadi ({e}). Groq zaxirasiga o'tilmoqda...")

    # 2. Groq orqali urinish (Zaxira)
    if groq_key:
        try:
            result = await _call_groq(prompt, groq_key, system_instruction)
            if "post_text" in result:
                return result
        except Exception as e:
            logger.error(f"Groq API xatosi: {e}")
            return {"error": f"AI xizmatlarida xatolik yuz berdi: {e}"}

    return {"error": "AI API kalitlari topilmadi yoki barchasi band."}
