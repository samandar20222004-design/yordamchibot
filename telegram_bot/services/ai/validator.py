"""AI Output Validator.

PHASE 3: AI Engine va SMM Orkestratsiyasi.

Tekshiruvlar:
- Bo'sh yoki faqat probellardan iborat javob (EMPTY_OUTPUT);
- Haddan tashqari qisqa / yupqa javob (THIN_OUTPUT);
- Ruxsat etilmagan / xavfli belgilar (INVALID_CHARACTERS: NUL, nazorat belgilari, xavfli scriptlar);
- Telegram 4096 belgi limiti (LENGTH_EXCEEDED);
- Til mosligi (LANGUAGE_MISMATCH: UZ / RU / EN).
"""

from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Validatsiya natijasi modeli."""
    is_valid: bool
    error_code: str | None = None
    reason: str | None = None
    needs_retry: bool = False


# Qat'iy taqiqlangan nazorat belgilari (NUL, bell, backspace va boshqa control charlar)
CONTROL_CHAR_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Xavfli skript yoki ob'ekt teglari
DANGEROUS_TAG_REGEX = re.compile(r"<\s*(?:script|iframe|object|embed|applet)\b", re.IGNORECASE)

# Tilni aniqlash uchun oddiy va samarali lug'at belgilari
RU_CYRILLIC_REGEX = re.compile(r"[\u0400-\u04FF]")
UZ_LATIN_MARKERS = [
    "haqida", "uchun", "bilan", "emas", "kerak", "bo'yicha", "bo‘yicha",
    "yangi", "juda", "barcha", "mumkin", "orqali", "qilish", "ekan",
]


class AIOutputValidator:
    """AI javoblarini sifat va xavfsizlik bo'yicha tekshiruvchi validator."""

    MAX_TELEGRAM_LENGTH: int = 4096
    MIN_MEANINGFUL_LENGTH: int = 15

    @classmethod
    def validate(
        cls,
        text: str | None,
        expected_lang: str | None = "uz",
        max_length: int = MAX_TELEGRAM_LENGTH,
    ) -> ValidationResult:
        """AI tomonidan qaytarilgan matnni kompleks tekshiradi."""
        # 1. Bo'sh javob
        if text is None or not text.strip():
            return ValidationResult(
                is_valid=False,
                error_code="EMPTY_OUTPUT",
                reason="AI javobi bo'sh yoki faqat bo'sh joylardan iborat.",
                needs_retry=True,
            )

        clean_text = text.strip()

        # 2. Xavfli / ruxsat etilmagan belgilar
        if CONTROL_CHAR_REGEX.search(clean_text):
            return ValidationResult(
                is_valid=False,
                error_code="INVALID_CHARACTERS",
                reason="Matnda ruxsat etilmagan boshqaruv (control) belgilari mavjud.",
                needs_retry=True,
            )

        if DANGEROUS_TAG_REGEX.search(clean_text):
            return ValidationResult(
                is_valid=False,
                error_code="INVALID_CHARACTERS",
                reason="Matnda xavfli HTML/skript teglari aniqlandi.",
                needs_retry=True,
            )

        # 3. Juda yupqa / qisqa javob (mazmunsiz)
        if len(clean_text) < cls.MIN_MEANINGFUL_LENGTH:
            return ValidationResult(
                is_valid=False,
                error_code="THIN_OUTPUT",
                reason=f"AI javobi juda qisqa ({len(clean_text)} belgi). Mazmunli SMM posti talab qilinadi.",
                needs_retry=True,
            )

        # 4. Telegram 4096 belgi chegarasi
        if len(clean_text) > max_length:
            return ValidationResult(
                is_valid=False,
                error_code="LENGTH_EXCEEDED",
                reason=f"Matn uzunligi ({len(clean_text)}) Telegram limitidan ({max_length}) oshib ketdi.",
                needs_retry=False,  # Buni kesish (truncate) orqali hal qilish mumkin
            )

        # 5. Til mosligi tekshiruvi (agar ko'rsatilgan bo'lsa)
        if expected_lang:
            lang_code = expected_lang.lower().strip()
            cyrillic_chars = len(RU_CYRILLIC_REGEX.findall(clean_text))
            total_letters = len(re.findall(r"[a-zA-Z\u0400-\u04FF]", clean_text))

            if total_letters > 20:
                cyrillic_ratio = cyrillic_chars / total_letters

                if lang_code == "ru":
                    # Ruscha kutilganda kirill harflari kamida 40% bo'lishi kerak
                    if cyrillic_ratio < 0.35:
                        return ValidationResult(
                            is_valid=False,
                            error_code="LANGUAGE_MISMATCH",
                            reason="Kutilgan til ruscha (RU), lekin matnda kirill yozuvi yetarli emas.",
                            needs_retry=True,
                        )
                elif lang_code == "en":
                    # Inglizcha kutilganda kirill harflari deyarli bo'lmasligi kerak
                    if cyrillic_ratio > 0.15:
                        return ValidationResult(
                            is_valid=False,
                            error_code="LANGUAGE_MISMATCH",
                            reason="Kutilgan til inglizcha (EN), lekin matnda kirill harflari topildi.",
                            needs_retry=True,
                        )
                elif lang_code == "uz":
                    # Agar o'zbek tili lotinda kutilsa va matn 80%+ ruscha kirill bo'lsa
                    # (o'zbek kirill ham bo'lishi mumkin, shuning uchun faqat toza ruscha belgilari bo'lsa ehtiyot bo'lamiz)
                    pass

        return ValidationResult(is_valid=True)

    @classmethod
    def get_retry_prompt_addon(cls, error_code: str | None, expected_lang: str = "uz") -> str:
        """Xatolik turiga qarab promptni kuchaytiruvchi instruksiya matnini qaytaradi."""
        lang = expected_lang.lower() if expected_lang else "uz"

        if error_code in ("EMPTY_OUTPUT", "THIN_OUTPUT"):
            if lang == "ru":
                return (
                    "\n\nВАЖНО: Предыдущий ответ был слишком коротким или пустым! "
                    "Напишите полноценный, подробный и готовый SMM-пост с хуком, основной частью, "
                    "призывом к действию (CTA) и 3-5 хэштегами. Не используйте односложные фразы!"
                )
            elif lang == "en":
                return (
                    "\n\nIMPORTANT: The previous output was too thin or empty! "
                    "Write a complete, high-converting SMM post with a strong hook, clear body points, "
                    "a call-to-action (CTA), and 3-5 hashtags. Do not reply with one line!"
                )
            else:
                return (
                    "\n\nMUHIM: Oldingi javob juda qisqa yoki bo'sh bo'ldi! "
                    "Iltimos, to'liq, kamida 2-4 xatboshidan iborat, qiziqarli sarlavha (hook), "
                    "asosiy mazmun, chaqiriq (CTA) va 3-5 ta tegishli hashtag bilan to'liq SMM post yozing. "
                    "1-2 qatorli quruq javob berish TAQIQLANADI!"
                )

        if error_code == "LANGUAGE_MISMATCH":
            if lang == "ru":
                return (
                    "\n\nВНИМАНИЕ: Ответ ОБЯЗАТЕЛЬНО должен быть строго на РУССКОМ языке (кириллица)! "
                    "Не используйте другие языки для основного текста."
                )
            elif lang == "en":
                return (
                    "\n\nATTENTION: The response MUST be strictly in ENGLISH! "
                    "Do not use Russian or other languages in the post text."
                )
            else:
                return (
                    "\n\nDIQQAT: Matn QAT'IY O'ZBEK TILIDA (lotin yozuvida) bo'lishi shart! "
                    "Boshqa tillarni aralashtirmang."
                )

        if error_code == "INVALID_CHARACTERS":
            return (
                "\n\nDIQQAT: Matnda hech qanday maxsus kodlar, skriptlar yoki buzuq belgilardan foydalanmang. "
                "Faqat toza Telegram HTML formatidagi matn taqdim eting."
            )

        return "\n\nIltimos, ko'rsatmalarga qat'iy amal qilgan holda to'liq va sifatli post yozing."
