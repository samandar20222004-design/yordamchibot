"""SMART CONTENT CALENDAR matnlari (UZ/RU/EN, bir xil kalitlar)."""
from locales.translations import normalize_lang

CONTENT_CALENDAR_I18N = {
 "uz": {"button":"🗓 Kontent Reja", "ask_business":"Biznes yoki sohangizni kiriting (masalan: Ayollar kiyimi, Fast food, Kurslar):", "choose_duration":"Reja davomiyligini tanlang:", "seven":"🗓 7 kunlik reja", "thirty":"🗓 30 kunlik reja", "pro":"🟣 30 kunlik reja faqat PRO foydalanuvchilar uchun. PRO ga o'ting.", "limit":"FREE tarifida haftasiga faqat 1 ta 7 kunlik reja mavjud.", "header":"🗓 <b>SMART CONTENT CALENDAR</b>\n\nSohangiz: <b>{business}</b>\n", "day":"<b>{n}-kun</b> — {rubric}\n<b>Mavzu:</b> {topic}\n<i>Tavsiya:</i> {tip}\n\n", "create":"✨ Post yaratish", "error":"Reja hozircha tuzilmadi. Keyinroq qayta urinib ko‘ring."},
 "ru": {"button":"🗓 Контент-план", "ask_business":"Введите бизнес или сферу (например: Женская одежда, Fast food, Курсы):", "choose_duration":"Выберите длительность плана:", "seven":"🗓 План на 7 дней", "thirty":"🗓 План на 30 дней", "pro":"🟣 План на 30 дней доступен только PRO. Оформите PRO.", "limit":"На тарифе FREE доступен только 1 план на 7 дней в неделю.", "header":"🗓 <b>SMART CONTENT CALENDAR</b>\n\nСфера: <b>{business}</b>\n", "day":"<b>День {n}</b> — {rubric}\n<b>Тема:</b> {topic}\n<i>Совет:</i> {tip}\n\n", "create":"✨ Создать пост", "error":"Не удалось создать план. Попробуйте позже."},
 "en": {"button":"🗓 Content calendar", "ask_business":"Enter your business or niche (for example: Women’s clothing, Fast food, Courses):", "choose_duration":"Choose the plan duration:", "seven":"🗓 7-day plan", "thirty":"🗓 30-day plan", "pro":"🟣 The 30-day plan is available for PRO users only. Upgrade to PRO.", "limit":"FREE users can create only 1 seven-day plan per week.", "header":"🗓 <b>SMART CONTENT CALENDAR</b>\n\nNiche: <b>{business}</b>\n", "day":"<b>Day {n}</b> — {rubric}\n<b>Topic:</b> {topic}\n<i>Tip:</i> {tip}\n\n", "create":"✨ Create post", "error":"The plan could not be created. Please try again later."}}
KEYS = tuple(sorted(CONTENT_CALENDAR_I18N['uz']))
def calendar_t(key, lang='uz', **kwargs):
    text = CONTENT_CALENDAR_I18N.get(normalize_lang(lang), CONTENT_CALENDAR_I18N['uz']).get(key, CONTENT_CALENDAR_I18N['uz'][key])
    return text.format(**kwargs)
def content_calendar_parity():
    return {lang: tuple(sorted(values)) == KEYS for lang, values in CONTENT_CALENDAR_I18N.items()}
