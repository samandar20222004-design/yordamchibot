# Mini App API (`/api/v1`)

Manba: `telegram_bot/miniapp_api/app.py` (marshrutlar), `service.py` (o'qish), `writes.py` (yozish), `errors.py` (xatolar).
`MINIAPP_ENABLED=0` bo'lsa marshrutlar umuman ulanmaydi.

## Autentifikatsiya

Har so'rovda `Authorization: tma <initData>` (Telegram WebApp `initData` xom satri). Server `miniapp_api/auth.py` da rasmiy
bot-token usulida tekshiradi (`secret = HMAC_SHA256("WebAppData", BOT_TOKEN)`, `hash` mosligi, `auth_date` yoshi ≤ `MINIAPP_AUTH_MAX_AGE_SECONDS`).
`user_id` FAQAT tekshirilgan initData'dan olinadi; frontend yuborgan `user_id` hech qayerda ishlatilmaydi. Foydalanuvchi botda
ro'yxatdan o'tmagan bo'lsa — `not_registered`. HTTPS majburiy (`MINIAPP_REQUIRE_HTTPS`), proksi ishonchi — `MINIAPP_TRUSTED_PROXY_CIDRS`.
Limitlar: auth / foydalanuvchi / yozuv / AI / yuklash (`MINIAPP_RATE_*`), Redis orqali, xatoda 503 (fail-closed).

## O'qish

| Marshrut | Javob |
|---|---|
| `GET /health` | holat |
| `GET /me` | foydalanuvchi, tarif+limitlar, `tiers` (narx/davr), foydalanish, post sonlari, `settings.notifications`, `bot.username` |
| `GET /channels` | foydalanuvchi kanallari (faqat o'ziniki) |
| `GET /channels/{channel_id}/analytics` | kanal tahlili (faqat egasi) |
| `GET /scheduled-posts?limit&offset&status=history` | rejalangan/tarixiy postlar |
| `GET /scheduled-posts/calendar?from&to` | oraliqdagi postlar |
| `GET /posts/{id}` | to'liq post (matn, tugma, takrorlanish, `media_items`) — faqat egasi |
| `GET /posts/{id}/media[?i=N]` | media baytlari (tur baytlardan aniqlanadi), faqat egasi |
| `GET /draft` | botdan kelgan qoralama (`media.items`, `file_id` YO'Q) |
| `GET /draft/media[?i=N]` | qoralama mediasi |
| `GET /templates` | shablonlar |

## Yozish (hammasi yozuv-limiti bilan; qayta urinilmaydi)

| Marshrut | Tana / izoh |
|---|---|
| `POST /posts` | `channel_id, text, scheduled_at \| send_now, button_text, button_url, use_draft, recurrence` — rejalaydi; yuborishni bot scheduler'i bajaradi; 30 s ichida takroriy post qaytariladi |
| `PATCH /posts/{id}` | `text, scheduled_at, button_text, button_url, recurrence_time, recurrence_time2` (faqat `pending`) |
| `DELETE /posts/{id}` | bekor qilish |
| `POST /posts/{id}/media[?add=1]` | multipart `file`; `add=1` — albomga qo'shish (≤10), aks holda almashtirish |
| `DELETE /posts/{id}/media[?i=N]` | bittasini yoki hammasini olib tashlash |
| `POST /draft/media[?add=1]` | qoralamaga fayl (multipart) |
| `DELETE /draft/media?i=N` | qoralamadan bitta media |
| `DELETE /draft` | qoralamani o'chirish |
| `PATCH /me/settings` | `language` va/yoki `notifications` (`notify_scheduled, notify_news, notify_morning_digest, notify_uzbek_calendar`: bool) |
| `POST /ai/generate` | `text, style` — AI kvota/byudjet botdagi bilan bir xil, xatoda bron qaytariladi |
| `POST /schedule/parse` | `text, default_time` — tabiiy tildagi rejani tuzilmaga o'giradi (hech narsa yozmaydi) |
| `POST /templates`, `DELETE /templates/{id}` | shablon |

Yuklash: rasm ≤ 10 MB, video/GIF ≤ 50 MB (`MAX_UPLOAD_*`), albom ≤ 10; rasm+video aralash mumkin, GIF/hujjat/audio faqat alohida.
Yuklash HTTP chegarasi `MINIAPP_UPLOAD_TIMEOUT_SECONDS` (240 s).

## Xato formati

```json
{"error": {"code": "...", "message": "<uz|ru|en>", "request_id": "...", "retry_after": null, "field": "text"}}
```

Kodlar → HTTP: `bad_request 400`, `https_required 400`, `unauthorized 401`, `auth_expired 401`, `not_registered 403`, `not_found 404`,
`method_not_allowed 405`, `payload_too_large 413`, `unsupported_media_type 415`, `invalid_input 422`, `schedule_in_past 422`,
`caption_too_long 422`, `album_full 422`, `album_mixed 422`, `not_editable 409`, `queue_limit_reached 403`, `ai_limit_reached 403`,
`templates_limit_reached 403`, `channel_not_found 404`, `draft_not_found 404`, `media_unavailable 404`, `rate_limited 429`,
`internal_error 500`, `service_unavailable 503`, `auth_unavailable 503`, `ai_unavailable 503`, `upload_failed 503`, `save_failed 503`.
Frontend kod ro'yxati: `miniapp/src/api/types.ts` (`ErrorCode`) va `client.ts` (`KNOWN_CODES`) — ikkalasi `errors.py` bilan mos bo'lishi shart.
