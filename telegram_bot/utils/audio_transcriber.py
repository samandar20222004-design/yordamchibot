"""🎙 VOICE → POST — BEPUL STT (Speech-to-Text) moduli ($0 xarajat).

Foydalanuvchining ovozli xabari (``.ogg``/``.oga`` — Telegram Voice) yoki
audio fayli (``.mp3``, ``.m4a``, ...) matnga aylantiriladi:

  1) BIRLAMCHI: **Groq Cloud — Whisper Large v3** (``whisper-large-v3``)
     — bepul tier, juda tez (60s audio ≈ 1–2s transkripsiya).
  2) ZAXIRA (fallback): **Gemini multimodal audio** — Groq ishlamasa yoki
     kalit bo'lmasa Gemini orqali transkripsiya.

RESURS HIMOYASI (resurs-tejamkor dizayn):
  * davomiyligi: FREE ≤ 60s (1 daqiqa), PRO ≤ 180s (3 daqiqa);
  * fayl hajmi: ≤ 20 MB (Telegram Bot API download limiti ham 20 MB);
  * timeout: har bir provayder alohida qat'iy timeout (connect/total);
  * transkripsiya BEPUL — hech qanday AI limiti/krediti YECHILMAYDI.
    Kredit faqat foydalanuvchi uslub tanlagach, post generatsiyasida
    yechiladi (``handlers/voice_post.py``).

Foydalanish::

    from utils.audio_transcriber import transcribe_voice, check_duration

    ok, limit = check_duration(voice.duration, is_pro=False)
    if not ok:
        ...  # «Iltimos, g'oyangizni qisqaroq (1 daqiqa ichida) ...»
    result = await transcribe_voice(data, "voice.ogg")
    # {"text": "...", "provider": "groq"}  yoki  {"error": "stt_unavailable"}

MUHIM: kalitlar (``GROQ_API_KEY`` / ``GEMINI_API_KEY``) CHAQIRUV PAYTIDA
``os.getenv`` orqali o'qiladi — modul import paytida emas. Shu sababli
testlar muhitni importdan oldin ham, keyin ham erkin boshqara oladi va
modul ``config`` ga bog'liq EMAS (aylanma import xavfi yo'q).
"""

import base64
import logging
import os
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

# ============================================================
# ⛑ RESURS CHEKLOVLARI (topshiriq talablari — resurs himoyasi)
# ============================================================
#: FREE tarif: maksimal audio davomiyligi (soniya) — 1 daqiqa.
VOICE_MAX_DURATION_FREE = 60
#: PRO tarif: maksimal audio davomiyligi (soniya) — 3 daqiqa.
VOICE_MAX_DURATION_PRO = 180
#: Maksimal fayl hajmi — 20 MB (Telegram Bot API download limiti).
VOICE_MAX_BYTES = 20 * 1024 * 1024
#: Gemini inline so'rov xavfsiz chegarasi (base64 +33% → <20MB API limiti).
_GEMINI_INLINE_AUDIO_MAX_BYTES = 14 * 1024 * 1024

# ============================================================
# SOZLAMALAR (env orqali almashtirish mumkin)
# ============================================================
GROQ_STT_ENDPOINT = os.getenv(
    "GROQ_STT_ENDPOINT",
    "https://api.groq.com/openai/v1/audio/transcriptions",
).strip()
GROQ_STT_MODEL = (os.getenv("GROQ_STT_MODEL", "") or "").strip() or "whisper-large-v3"
GEMINI_AUDIO_MODEL = (os.getenv("GEMINI_AUDIO_MODEL", "") or "").strip() or "gemini-1.5-flash"
GEMINI_BASE = os.getenv(
    "GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta/models"
).strip()

# STT uchun alohida (chat AI'dan uzunroq) timeout — audio yuklash+transkripsiya.
STT_CONNECT_TIMEOUT = max(1, float(os.getenv("STT_CONNECT_TIMEOUT", "8") or 8))
STT_TOTAL_TIMEOUT = max(5, float(os.getenv("STT_TOTAL_TIMEOUT", "45") or 45))

#: Groq Whisper qo'llab-quvvatlaydigan asosiy formatlar (ma'lumot uchun).
SUPPORTED_EXTENSIONS = (".ogg", ".oga", ".mp3", ".m4a", ".wav", ".webm", ".opus", ".flac")

_MIME_BY_EXT = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}

_GEMINI_PROMPT = (
    "Transcribe the spoken audio in this recording exactly as spoken, in the "
    "same language the speaker uses. Return ONLY the transcription text — "
    "no commentary, no markdown, no quotes."
)


# ============================================================
# CHEKLOV TEKSHIRUVLARI (sof funksiyalar — testlash oson)
# ============================================================
def duration_limit_for(is_pro: bool) -> int:
    """Tarif bo'yicha maksimal audio davomiyligi (soniya)."""
    return VOICE_MAX_DURATION_PRO if is_pro else VOICE_MAX_DURATION_FREE


def check_duration(duration_seconds, is_pro: bool) -> tuple[bool, int]:
    """Audio davomiyligi tarif limitiga mosligini tekshiradi.

    Returns:
        (ok, limit) — ``ok=False`` bo'lsa audio rad etiladi va ``limit``
        (soniya) xabar matnida ko'rsatiladi.

    Eslatma: ``duration`` bo'sh/aniqlanmagan (0/None) bo'lsa — o'tkazamiz
    (Telegram Voice'da doim bor; audio ba'zi clientlarda yo'q bo'lishi mumkin).
    """
    try:
        duration = float(duration_seconds or 0)
    except (TypeError, ValueError):
        duration = 0.0
    limit = duration_limit_for(is_pro)
    if duration <= 0:
        return True, limit
    return duration <= limit, limit


def check_size(size_bytes) -> bool:
    """Fayl hajmi ≤ 20 MB ekanini tekshiradi (None → hajmi noma'lum, o'tadi)."""
    try:
        size = int(size_bytes or 0)
    except (TypeError, ValueError):
        return True
    return size <= VOICE_MAX_BYTES if size > 0 else True


def mime_for_filename(filename: str) -> str:
    """Fayl kengaytmasi bo'yicha MIME turi (noma'lum → audio/ogg)."""
    ext = str(filename or "").lower().rsplit(".", 1)
    ext = f".{ext[-1]}" if len(ext) == 2 else ""
    return _MIME_BY_EXT.get(ext, "audio/ogg")


def sanitize_transcript(text) -> str:
    """Transkripsiya matnini tozalaydi: ortiqcha bo'shliqlar, \r, 3+ \n."""
    if not isinstance(text, str):
        return ""
    cleaned = text.replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    # Yangi qatorlar atrofidagi ortiqcha bo'shliqlar ham tozalanadi.
    cleaned = re.sub(r" ?\n ?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _groq_key() -> str:
    return (os.getenv("GROQ_API_KEY", "") or "").strip()


def _gemini_key() -> str:
    return (os.getenv("GEMINI_API_KEY", "") or "").strip()


def stt_http_timeout() -> aiohttp.ClientTimeout:
    """STT so'rovi uchun qat'iy HTTP timeout (har bir provayderga alohida)."""
    return aiohttp.ClientTimeout(
        total=float(STT_TOTAL_TIMEOUT),
        connect=float(STT_CONNECT_TIMEOUT),
        sock_connect=float(STT_CONNECT_TIMEOUT),
        sock_read=float(STT_TOTAL_TIMEOUT),
    )


# ============================================================
# PROVAYDERLAR
# ============================================================
async def _groq_transcribe(session, data: bytes, filename: str) -> str:
    """Groq Cloud Whisper Large v3 — multipart/form-upload orqali.

    Muvaffaqiyatda transkripsiya matnini qaytaradi; aks holda istisno.
    """
    form = aiohttp.FormData()
    form.add_field(
        "file", data, filename=filename or "voice.ogg",
        content_type=mime_for_filename(filename),
    )
    form.add_field("model", GROQ_STT_MODEL)
    form.add_field("response_format", "json")
    headers = {"Authorization": f"Bearer {_groq_key()}"}
    async with session.post(
        GROQ_STT_ENDPOINT, headers=headers, data=form,
        timeout=stt_http_timeout(),
    ) as resp:
        if resp.status != 200:
            body = ""
            try:
                body = (await resp.text())[:300]
            except Exception:  # pragma: no cover — himoya
                pass
            raise RuntimeError(f"Groq STT HTTP {resp.status}: {body}")
        payload = await resp.json(content_type=None)
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("text") or "").strip()
    if not text:
        raise RuntimeError("Groq STT bo'sh matn qaytardi")
    return text


async def _gemini_transcribe(session, data: bytes, filename: str) -> str:
    """Gemini multimodal audio — inline_data (base64) orqali transkripsiya.

    Zaxira provayder: Groq ishlamasa yoki kalit bo'lmasa ishlatiladi.
    """
    url = f"{GEMINI_BASE}/{GEMINI_AUDIO_MODEL}:generateContent?key={_gemini_key()}"
    payload = {
        "contents": [{
            "parts": [
                {"text": _GEMINI_PROMPT},
                {
                    "inline_data": {
                        "mime_type": mime_for_filename(filename),
                        "data": base64.b64encode(data).decode("ascii"),
                    }
                },
            ]
        }],
        "generationConfig": {"temperature": 0.0},
    }
    async with session.post(url, json=payload, timeout=stt_http_timeout()) as resp:
        if resp.status != 200:
            body = ""
            try:
                body = (await resp.text())[:300]
            except Exception:  # pragma: no cover — himoya
                pass
            raise RuntimeError(f"Gemini STT HTTP {resp.status}: {body}")
        result = await resp.json(content_type=None)
    text = ""
    try:
        candidates = (result or {}).get("candidates") or []
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        text = "".join(
            str(p.get("text") or "") for p in parts if isinstance(p, dict)
        ).strip()
    except Exception:  # pragma: no cover — himoya
        text = ""
    if not text:
        raise RuntimeError("Gemini STT bo'sh matn qaytardi")
    return text


async def _transcribe_with_session(session, data: bytes, filename: str,
                                   started: float) -> dict:
    """Groq → Gemini zanjiri (bir session ichida, har biriga alohida timeout)."""
    errors = []

    # 1) Groq Whisper Large v3 (bepul, tezkor) — birinchi navbatda.
    if _groq_key():
        try:
            text = await _groq_transcribe(session, data, filename)
            return {
                "text": sanitize_transcript(text),
                "provider": "groq",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception as e:  # noqa: BLE001 — fallback'ga o'tamiz
            logger.warning("Groq STT muvaffaqiyatsiz: %s", e)
            errors.append(f"groq: {e}")
    else:
        errors.append("groq: kalit yo'q")

    # 2) Zaxira: Gemini multimodal audio.
    if _gemini_key():
        if len(data) <= _GEMINI_INLINE_AUDIO_MAX_BYTES:
            try:
                text = await _gemini_transcribe(session, data, filename)
                return {
                    "text": sanitize_transcript(text),
                    "provider": "gemini",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            except Exception as e:  # noqa: BLE001
                logger.warning("Gemini STT muvaffaqiyatsiz: %s", e)
                errors.append(f"gemini: {e}")
        else:
            logger.warning(
                "Gemini STT o'tkazib yuborildi: audio %.1f MB (inline limit)",
                len(data) / (1024 * 1024),
            )
            errors.append("gemini: audio juda katta")
    else:
        errors.append("gemini: kalit yo'q")

    return {"error": "stt_unavailable", "details": errors[-3:]}


async def transcribe_voice(data, filename: str = "voice.ogg", session=None) -> dict:
    """Ovoz/audio baytlarini matnga aylantiradi (Groq Whisper → Gemini fallback).

    Args:
        data: audio fayl mazmuni (bytes/bytearray/memoryview);
        filename: kengaytmani aniqlash uchun (``voice.ogg``, ``audio.mp3``...);
        session: ixtiyoriy ``aiohttp.ClientSession`` (testlar uchun DI);
            ``None`` bo'lsa ichki session ochiladi va yopiladi.

    Returns:
        Muvaffaqiyatda::

            {"text": "...", "provider": "groq" | "gemini", "elapsed_ms": 1234}

        Xatolikda (hech qachon istisno BERMAYDI)::

            {"error": "too_large"}        # >20 MB
            {"error": "empty_audio"}      # bo'sh baytlar
            {"error": "stt_unavailable"}  # provayderlar/kalitlar ishlamadi
    """
    started = time.monotonic()
    try:
        raw = bytes(data or b"")
    except (TypeError, ValueError):
        raw = b""
    if not raw:
        return {"error": "empty_audio"}
    if len(raw) > VOICE_MAX_BYTES:
        logger.warning(
            "STT rad etildi: audio %.1f MB > %.0f MB limit",
            len(raw) / (1024 * 1024), VOICE_MAX_BYTES / (1024 * 1024),
        )
        return {"error": "too_large"}

    if session is not None:
        return await _transcribe_with_session(session, raw, filename, started)
    try:
        async with aiohttp.ClientSession() as own_session:
            return await _transcribe_with_session(own_session, raw, filename, started)
    except Exception as e:  # noqa: BLE001 — handler xushmuomala xabar ko'rsatadi
        logger.error("STT zanjiri xatosi: %s", e)
        return {"error": "stt_unavailable"}
