"""Yagona xato formati va uz/ru/en xabarlar.

Javob::

    {"error": {"code": "...", "message": "...", "request_id": "...",
               "retry_after": null | int}}

Xabarlar texnik tafsilotsiz; foydalanuvchi yuborgan qiymatlar hech qachon
xabarga qo'shilmaydi.
"""
from __future__ import annotations

from aiohttp import web

SUPPORTED_LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"

# code -> (status, {lang: message})
_CATALOG: dict[str, tuple[int, dict[str, str]]] = {
    "bad_request": (400, {
        "uz": "So'rov noto'g'ri tuzilgan.",
        "ru": "Некорректный запрос.",
        "en": "The request is not valid.",
    }),
    "https_required": (400, {
        "uz": "Xavfsiz (HTTPS) ulanish talab qilinadi.",
        "ru": "Требуется защищённое соединение (HTTPS).",
        "en": "A secure (HTTPS) connection is required.",
    }),
    "unauthorized": (401, {
        "uz": "Kirish tasdiqlanmadi. Ilovani Telegram ichida qayta oching.",
        "ru": "Не удалось подтвердить вход. Откройте приложение в Telegram заново.",
        "en": "Sign-in could not be verified. Reopen the app inside Telegram.",
    }),
    "auth_expired": (401, {
        "uz": "Sessiya muddati tugadi. Ilovani Telegram ichida qayta oching.",
        "ru": "Сессия истекла. Откройте приложение в Telegram заново.",
        "en": "Your session has expired. Reopen the app inside Telegram.",
    }),
    "not_registered": (403, {
        "uz": "Avval botda ro'yxatdan o'ting: botga /start yuboring.",
        "ru": "Сначала зарегистрируйтесь в боте: отправьте боту /start.",
        "en": "Please register in the bot first: send /start to the bot.",
    }),
    "beta_access_required": (403, {
        "uz": "Sizda hali kirish ruxsati yo'q. Botdagi ko'rsatmalarga qarang.",
        "ru": "У вас пока нет доступа. Следуйте инструкциям в боте.",
        "en": "You do not have access yet. Follow the instructions in the bot.",
    }),
    "not_found": (404, {
        "uz": "Topilmadi.",
        "ru": "Не найдено.",
        "en": "Not found.",
    }),
    "method_not_allowed": (405, {
        "uz": "Bu usul qo'llab-quvvatlanmaydi.",
        "ru": "Метод не поддерживается.",
        "en": "Method not allowed.",
    }),
    "rate_limited": (429, {
        "uz": "So'rovlar juda ko'p. Birozdan so'ng urinib ko'ring.",
        "ru": "Слишком много запросов. Попробуйте чуть позже.",
        "en": "Too many requests. Please try again shortly.",
    }),
    "internal_error": (500, {
        "uz": "Kutilmagan xatolik yuz berdi. Keyinroq urinib ko'ring.",
        "ru": "Непредвиденная ошибка. Попробуйте позже.",
        "en": "Something went wrong. Please try again later.",
    }),
    "service_unavailable": (503, {
        "uz": "Xizmat vaqtincha mavjud emas. Birozdan so'ng urinib ko'ring.",
        "ru": "Сервис временно недоступен. Попробуйте чуть позже.",
        "en": "The service is temporarily unavailable. Please try again shortly.",
    }),
    "auth_unavailable": (503, {
        "uz": "Kirish xizmati vaqtincha ishlamayapti.",
        "ru": "Сервис входа временно недоступен.",
        "en": "Sign-in is temporarily unavailable.",
    }),
    "invalid_input": (422, {
        "uz": "Kiritilgan ma'lumot noto'g'ri. Maydonlarni tekshirib qayta urinib ko'ring.",
        "ru": "Некорректные данные. Проверьте поля и попробуйте снова.",
        "en": "Some of the data is not valid. Check the fields and try again.",
    }),
    "schedule_in_past": (422, {
        "uz": "Vaqt kelajakda bo'lishi kerak (kamida 1 daqiqadan keyin).",
        "ru": "Время должно быть в будущем (не раньше чем через 1 минуту).",
        "en": "The time must be in the future (at least 1 minute ahead).",
    }),
    "unsupported_media_type": (415, {
        "uz": "So'rov JSON (application/json) ko'rinishida bo'lishi kerak.",
        "ru": "Запрос должен быть в формате JSON (application/json).",
        "en": "The request must be JSON (application/json).",
    }),
    "payload_too_large": (413, {
        "uz": "So'rov hajmi juda katta.",
        "ru": "Слишком большой запрос.",
        "en": "The request is too large.",
    }),
    "channel_not_found": (404, {
        "uz": "Kanal topilmadi yoki sizga tegishli emas.",
        "ru": "Канал не найден или не принадлежит вам.",
        "en": "The channel was not found or does not belong to you.",
    }),
    "caption_too_long": (422, {
        "uz": "Rasm/video ostidagi matn 1024 belgidan oshmasligi kerak.",
        "ru": "Подпись к фото/видео не должна превышать 1024 символа.",
        "en": "A caption under a photo/video must be at most 1024 characters.",
    }),
    "draft_not_found": (404, {
        "uz": "Qoralama topilmadi yoki muddati tugagan. Postni botda qayta yuboring.",
        "ru": "Черновик не найден или устарел. Отправьте пост боту ещё раз.",
        "en": "The draft was not found or has expired. Send the post to the bot again.",
    }),
    "media_unavailable": (404, {
        "uz": "Media ko'rsatib bo'lmadi.",
        "ru": "Не удалось показать медиа.",
        "en": "The media could not be shown.",
    }),
    "not_editable": (409, {
        "uz": "Bu postni o'zgartirib bo'lmaydi: u allaqachon yuborilgan yoki bekor qilingan.",
        "ru": "Этот пост нельзя изменить: он уже отправлен или отменён.",
        "en": "This post can no longer be changed: it was already sent or cancelled.",
    }),
    "queue_limit_reached": (403, {
        "uz": "Navbatdagi postlar limiti to'ldi. PRO tarifda limit kengroq.",
        "ru": "Лимит очереди постов исчерпан. На PRO лимит выше.",
        "en": "The scheduled-posts limit is reached. PRO has a higher limit.",
    }),
    "ai_limit_reached": (403, {
        "uz": "AI uchun kunlik limit yoki kredit tugadi.",
        "ru": "Дневной лимит или кредиты для AI закончились.",
        "en": "The daily AI limit or credits are used up.",
    }),
    "ai_unavailable": (503, {
        "uz": "AI hozir javob bera olmadi. Limit qaytarildi, birozdan so'ng urinib ko'ring.",
        "ru": "AI сейчас не смог ответить. Лимит возвращён, попробуйте чуть позже.",
        "en": "The AI could not respond right now. Your limit was refunded; please try again shortly.",
    }),
    "templates_limit_reached": (403, {
        "uz": "Shablonlar limiti to'ldi. Keraksizini o'chirib, qayta urinib ko'ring.",
        "ru": "Лимит шаблонов исчерпан. Удалите ненужный и попробуйте снова.",
        "en": "The templates limit is reached. Delete one you no longer need and try again.",
    }),
    "save_failed": (503, {
        "uz": "Saqlab bo'lmadi. Birozdan so'ng qayta urinib ko'ring.",
        "ru": "Не удалось сохранить. Попробуйте чуть позже.",
        "en": "Could not save. Please try again shortly.",
    }),
}


class ApiError(Exception):
    """Mijozga xavfsiz ko'rsatiladigan xato (matn katalogdan olinadi)."""

    def __init__(self, code: str, *, retry_after: int | None = None,
                 headers: dict | None = None, field: str | None = None):
        super().__init__(code)
        if code not in _CATALOG:
            code = "internal_error"
        self.code = code
        self.status = _CATALOG[code][0]
        self.retry_after = retry_after
        self.headers = dict(headers or {})
        # Faqat maydon NOMI (qiymat hech qachon emas): forma xatosini ko'rsatish uchun.
        self.field = field if field and field.isidentifier() else None


def pick_lang(accept_language: str | None, preferred: str | None = None) -> str:
    """Til: ``preferred`` (profil) > ``Accept-Language`` > ``uz``."""
    if preferred in SUPPORTED_LANGS:
        return preferred  # type: ignore[return-value]
    for part in (accept_language or "").split(",")[:5]:
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in SUPPORTED_LANGS:
            return tag
    return DEFAULT_LANG


def message_for(code: str, lang: str) -> str:
    entry = _CATALOG.get(code) or _CATALOG["internal_error"]
    return entry[1].get(lang) or entry[1][DEFAULT_LANG]


def error_response(err: ApiError, *, request_id: str, lang: str) -> web.Response:
    headers = {"Cache-Control": "no-store", "X-Request-Id": request_id}
    headers.update(err.headers)
    if err.retry_after is not None:
        headers["Retry-After"] = str(int(err.retry_after))
    return web.json_response(
        {"error": {
            "code": err.code,
            "message": message_for(err.code, lang),
            "request_id": request_id,
            "retry_after": err.retry_after,
            "field": err.field,
        }},
        status=err.status,
        headers=headers,
    )


def catalog_codes() -> tuple[str, ...]:
    return tuple(_CATALOG)
