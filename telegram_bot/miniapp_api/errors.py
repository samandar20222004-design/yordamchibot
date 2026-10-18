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
    "album_full": (422, {
        "uz": "Albomga ko'pi bilan 10 ta media qo'shish mumkin (Telegram chegarasi). Avval bittasini olib tashlang.",
        "ru": "В альбом можно добавить не более 10 медиа (лимит Telegram). Сначала удалите одно.",
        "en": "An album holds at most 10 media (Telegram limit). Remove one first.",
    }),
    "album_mixed": (422, {
        "uz": "Rasm va videoni bitta albomda birlashtirish mumkin; GIF, hujjat va audio esa faqat alohida.",
        "ru": "В одном альбоме можно сочетать фото и видео; GIF, документы и аудио — только отдельно.",
        "en": "Photos and videos can share an album; GIFs, documents and audio can only be sent on their own.",
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
    "upload_failed": (503, {
        "uz": "Faylni Telegram'ga yuklab bo'lmadi. Botni ishga tushirib (/start), qayta urinib ko'ring.",
        "ru": "Не удалось загрузить файл в Telegram. Запустите бота (/start) и попробуйте снова.",
        "en": "The file could not be uploaded to Telegram. Start the bot (/start) and try again.",
    }),
    "templates_limit_reached": (403, {
        "uz": "Shablonlar limiti to'ldi. Keraksizini o'chirib, qayta urinib ko'ring.",
        "ru": "Лимит шаблонов исчерпан. Удалите ненужный и попробуйте снова.",
        "en": "The templates limit is reached. Delete one you no longer need and try again.",
    }),
    "market_private": (422, {
        "uz": "Kanalda username yo'q (yopiq kanal). Birjada faqat ochiq kanallar bo'ladi.",
        "ru": "У канала нет username (закрытый канал). На бирже только открытые каналы.",
        "en": "The channel has no username (private). Only public channels can be listed.",
    }),
    "market_not_admin": (403, {
        "uz": "Egalikni tasdiqlab bo'lmadi: siz ham, bot ham kanalda admin bo'lishingiz kerak.",
        "ru": "Не удалось подтвердить владение: вы и бот должны быть админами канала.",
        "en": "Ownership could not be verified: both you and the bot must be channel admins.",
    }),
    "market_limit": (403, {
        "uz": "Bitta hisobdan ko'pi bilan 5 ta kanal qo'yish mumkin.",
        "ru": "С одного аккаунта можно разместить не более 5 каналов.",
        "en": "One account can list at most 5 channels.",
    }),
    "market_blocked": (403, {
        "uz": "E'lon shikoyatlar tufayli bloklangan. Tekshiruv uchun qo'llab-quvvatlashga yozing.",
        "ru": "Объявление заблокировано из-за жалоб. Для проверки напишите в поддержку.",
        "en": "This listing was blocked because of reports. Contact support for a review.",
    }),
    "inquiry_limit": (429, {
        "uz": "Kuniga 5 tadan ko'p yangi so'rov yuborib bo'lmaydi. Ertaga urinib ko'ring.",
        "ru": "Нельзя отправлять больше 5 новых заявок в сутки. Попробуйте завтра.",
        "en": "You can't send more than 5 new requests per day. Try again tomorrow.",
    }),
    "inquiry_blocked": (403, {
        "uz": "Bu kanal egasi sizdan so'rov qabul qilmaydi.",
        "ru": "Владелец этого канала не принимает заявки от вас.",
        "en": "This channel's owner does not accept requests from you.",
    }),
    "inquiry_own": (422, {
        "uz": "Bu sizning kanalingiz.",
        "ru": "Это ваш канал.",
        "en": "This is your channel.",
    }),
    "inquiry_exists": (409, {
        "uz": "Bu kanal bilan ochiq suhbatingiz bor — «Suhbatlar» bo'limidan davom eting.",
        "ru": "У вас уже есть открытый диалог с этим каналом — продолжите в «Диалогах».",
        "en": "You already have an open chat with this channel — continue in Chats.",
    }),
    "thread_closed": (409, {
        "uz": "Bu suhbat yopilgan.",
        "ru": "Этот диалог закрыт.",
        "en": "This chat is closed.",
    }),
    "thread_full": (409, {
        "uz": "Suhbat xabar limiti tugadi. Botda «Kontakt berish» orqali shaxsiy gaplashing.",
        "ru": "Лимит сообщений исчерпан. Передайте контакт в боте и общайтесь лично.",
        "en": "The chat message limit is reached. Share your contact in the bot to continue privately.",
    }),
    "message_card": (422, {
        "uz": "Xabarda karta raqami bor. Xavfsizlik uchun karta va hamyon raqamlarini yuborish mumkin emas.",
        "ru": "В сообщении номер карты. В целях безопасности номера карт и кошельков отправлять нельзя.",
        "en": "The message contains a card number. For safety, card and wallet numbers can't be sent.",
    }),
    "message_wallet": (422, {
        "uz": "Xabarda kripto-hamyon manzili bor. Xavfsizlik uchun yuborish mumkin emas.",
        "ru": "В сообщении адрес криптокошелька. В целях безопасности отправлять нельзя.",
        "en": "The message contains a crypto wallet address. It can't be sent for safety.",
    }),
    "message_link": (422, {
        "uz": "Birinchi xabarda (yoki yangi hisobdan) havola yuborish mumkin emas — fishingdan himoya.",
        "ru": "В первом сообщении (или с нового аккаунта) нельзя отправлять ссылки — защита от фишинга.",
        "en": "Links can't be sent in a first message (or from a new account) — phishing protection.",
    }),
    "message_spam": (429, {
        "uz": "Bir xil xabarni qayta-qayta yuborish mumkin emas. Matnni o'zgartiring.",
        "ru": "Одинаковое сообщение нельзя отправлять повторно. Измените текст.",
        "en": "The same message can't be sent repeatedly. Change the text.",
    }),
    "user_banned": (403, {
        "uz": "Hisobingiz shikoyatlar sababli birjadan chetlatilgan. Qo'llab-quvvatlashga yozing.",
        "ru": "Ваш аккаунт отстранён от биржи из-за жалоб. Напишите в поддержку.",
        "en": "Your account is suspended from the exchange because of reports. Contact support.",
    }),
    "owner_busy": (429, {
        "uz": "Bu kanal egasiga bugun juda ko'p so'rov kelgan. Ertaga urinib ko'ring.",
        "ru": "Этому владельцу сегодня пришло слишком много заявок. Попробуйте завтра.",
        "en": "This owner has received too many requests today. Try again tomorrow.",
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
