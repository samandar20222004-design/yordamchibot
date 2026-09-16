"""AI Providers & Resilient Provider Chain.

PHASE 3: AI Engine va SMM Orkestratsiyasi.

Barcha provayderlar uchun yagona AIProvider abstract interfeysi:
- Gemini 2.5 Flash (Primary)
- Groq (Secondary)
- OpenRouter (Tertiary)
- MockProvider (FAQAT dev/test muhitida — P0-A)

P0-A — MOCK PRODUCTION SIYOSATI (Phase 0 auditi)
------------------------------------------------
Auditda topilgan eng xavfli P0 muammo: API kalitlari bo'lmaganda
``ProviderChain`` jimgina ``MockProvider`` ga tushib qolardi va
foydalanuvchi SOXTA (deterministik shablon) postni haqiqiy AI javobi deb
olardi — kvota esa yechilardi.

Endi Mock faqat quyidagi hollarda zanjirda qatnashadi:

    ENVIRONMENT in ("development", "dev", "test", "testing", "local")
    YOKI AI_ALLOW_MOCK=1

Aks holda (default: ``ENVIRONMENT=production``, ``AI_ALLOW_MOCK=0``) real
provayderlar ishlamasa, zanjir OSHKORA xato bilan tugaydi:
:class:`NoConfiguredProviderError` yoki :class:`AllProvidersFailedError`.
Bunday holatda orkestrator foydalanuvchiga xavfsiz xabar qaytaradi va
bron qilingan kvotani TO'LIQ qaytaradi — soxta generatsiya YO'Q.
"""

from __future__ import annotations
import logging
import os
from abc import ABC, abstractmethod

from .prompt_guard import sanitize_output, strip_instruction_leaks

logger = logging.getLogger(__name__)


class AIProviderError(RuntimeError):
    """Provayder darajasidagi xatolik (timeout, 429, 5xx, kalit yo'qligi)."""
    pass


# ---------------------------------------------------------------------------
# P0-A — Muhit siyosati (ENVIRONMENT / AI_ALLOW_MOCK)
# ---------------------------------------------------------------------------
#: Muhit nomini beruvchi o'zgaruvchi. Default — ``production`` (fail-closed).
ENVIRONMENT_VAR = "ENVIRONMENT"
#: Mock'ni production'da ham ataylab yoqish uchun o'zgaruvchi (default: 0).
AI_ALLOW_MOCK_VAR = "AI_ALLOW_MOCK"
DEFAULT_ENVIRONMENT = "production"

#: Mock ishlashga ruxsat etilgan muhitlar — PHASE A spec bo'yicha qat'iy 2 ta.
MOCK_ALLOWED_ENVIRONMENTS = frozenset({"development", "test"})
#: ``AI_ALLOW_MOCK`` uchun haqiqat deb hisoblanadigan qiymatlar.
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on", "y", "ha"})

#: AI umuman ishlamaganda foydalanuvchiga ko'rsatiladigan YAGONA xavfsiz xabar.
AI_UNAVAILABLE_MESSAGES: dict[str, str] = {
    "uz": "⚠️ AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring.",
    "ru": "⚠️ AI сейчас недоступен, попробуйте позже.",
    "en": "⚠️ AI is currently unavailable, please try again later.",
}


class NoConfiguredProviderError(AIProviderError):
    """Hech qanday HAQIQIY AI provayderi sozlanmagan (kalitlar yo'q / Mock taqiqlangan).

    Production'da bu — kutilgan fail-closed natija: soxta generatsiya o'rniga
    oshkora xato qaytariladi.
    """
    pass


class AllProvidersFailedError(AIProviderError):
    """Mavjud HAQIQIY provayderlarning barchasi xato berdi (yoki sifat talabiga javob bermadi).

    Mock zaxira sifatida ishlatilmaydi (production siyosati, P0-A).
    """
    pass


def get_environment() -> str:
    """Joriy muhit nomi (default: ``production`` — fail-closed)."""
    value = (os.getenv(ENVIRONMENT_VAR) or "").strip().lower()
    return value or DEFAULT_ENVIRONMENT


def mock_is_allowed() -> bool:
    """P0-A: Mock zanjirda qatnashishi mumkinmi?

    ``True`` faqat dev/test muhitida yoki ``AI_ALLOW_MOCK=1`` bo'lganda.
    Qiymat har chaqiruvda o'qiladi (testlar va runtime'da o'zgartirish mumkin).
    """
    flag = (os.getenv(AI_ALLOW_MOCK_VAR) or "0").strip().lower()
    if flag in _TRUTHY_VALUES:
        return True
    return get_environment() in MOCK_ALLOWED_ENVIRONMENTS


def ai_unavailable_message(lang: str | None = "uz") -> str:
    """AI ishlamaganda foydalanuvchiga ko'rsatiladigan xavfsiz xabar (uz/ru/en)."""
    code = str(lang or "uz").strip().lower()[:2]
    return AI_UNAVAILABLE_MESSAGES.get(code, AI_UNAVAILABLE_MESSAGES["uz"])


class AIProvider(ABC):
    """Barcha AI provayderlar uchun asosiy abstrakt interfeys."""

    name: str = "BaseProvider"

    @abstractmethod
    async def generate(self, prompt: str, context: dict | None = None) -> str:
        """Berilgan prompt va context asosida matn generatsiya qiladi."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Provayder mavjudligi (API kaliti sozlanganligi) ni tekshiradi."""
        return True


class GeminiProvider(AIProvider):
    """Google Gemini (Gemini 2.5 Flash) provayderi."""

    name = "Gemini 2.5 Flash"

    def is_available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        if not self.is_available():
            raise AIProviderError("Gemini API kaliti topilmadi")

        ctx = context or {}
        lang = ctx.get("lang", "uz")

        try:
            from services.ai_service import GeminiProvider as CoreGemini
            provider = CoreGemini()
            result = await provider.call(prompt, system_prompt=ctx.get("system_prompt", ""), lang=lang)
            if isinstance(result, dict):
                text = result.get("content") or result.get("post_text") or result.get("response") or ""
            else:
                text = str(result or "")

            if not text.strip():
                raise AIProviderError("Gemini bo'sh javob qaytardi")
            return text.strip()
        except Exception as e:
            if isinstance(e, AIProviderError):
                raise
            raise AIProviderError(f"Gemini xatosi: {e}") from e


class GroqProvider(AIProvider):
    """Groq Cloud Llama-3 / Mixtral provayderi."""

    name = "Groq"

    def is_available(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        if not self.is_available():
            raise AIProviderError("Groq API kaliti topilmadi")

        ctx = context or {}
        lang = ctx.get("lang", "uz")

        try:
            from services.ai_service import GroqProvider as CoreGroq
            provider = CoreGroq()
            result = await provider.call(prompt, system_prompt=ctx.get("system_prompt", ""), lang=lang)
            if isinstance(result, dict):
                text = result.get("content") or result.get("post_text") or result.get("response") or ""
            else:
                text = str(result or "")

            if not text.strip():
                raise AIProviderError("Groq bo'sh javob qaytardi")
            return text.strip()
        except Exception as e:
            if isinstance(e, AIProviderError):
                raise
            raise AIProviderError(f"Groq xatosi: {e}") from e


class OpenRouterProvider(AIProvider):
    """OpenRouter Free Router (:free) provayderi."""

    name = "OpenRouter"

    def is_available(self) -> bool:
        return bool(os.getenv("OPENROUTER_API_KEY"))

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        if not self.is_available():
            raise AIProviderError("OpenRouter API kaliti topilmadi")

        ctx = context or {}
        lang = ctx.get("lang", "uz")

        try:
            from services.ai_service import OpenRouterProvider as CoreOpenRouter
            provider = CoreOpenRouter()
            result = await provider.call(prompt, system_prompt=ctx.get("system_prompt", ""), lang=lang)
            if isinstance(result, dict):
                text = result.get("content") or result.get("post_text") or result.get("response") or ""
            else:
                text = str(result or "")

            if not text.strip():
                raise AIProviderError("OpenRouter bo'sh javob qaytardi")
            return text.strip()
        except Exception as e:
            if isinstance(e, AIProviderError):
                raise
            raise AIProviderError(f"OpenRouter xatosi: {e}") from e


class MockProvider(AIProvider):
    """Offline, sandbox va test muhitlari uchun deterministik SMM provayderi.

    P0-A: production muhitida Mock SOXTA generatsiya manbai hisoblanadi —
    ``ENVIRONMENT=production`` + ``AI_ALLOW_MOCK=0`` bo'lganda u mavjud emas
    deb qaraladi va chaqirilsa ham xato beradi.
    """

    name = "Mock"

    def is_available(self) -> bool:
        """Mock faqat dev/test muhitida (yoki AI_ALLOW_MOCK=1) mavjud."""
        return mock_is_allowed()

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        # P0-A himoyasi: to'g'ridan-to'g'ri chaqiruv ham production'da taqiqlangan.
        if not mock_is_allowed():
            raise AIProviderError(
                "MockProvider production muhitida o'chirilgan "
                f"({ENVIRONMENT_VAR}={get_environment()}, {AI_ALLOW_MOCK_VAR}=0): "
                "soxta generatsiya taqiqlanadi."
            )

        ctx = context or {}
        lang = (ctx.get("lang") or "uz").lower()
        intent = str(ctx.get("intent") or "CREATE_POST").upper()

        # Test nazorati: majburiy nosozlik yoki yupqa javob simulyatsiyasi
        if ctx.get("force_fail"):
            raise AIProviderError("MockProvider: majburiy xatolik simulyatsiyasi")
        if ctx.get("force_thin_output"):
            return "Qisqa"  # Validator rad etadi

        # P0-C: prompt ichidagi tizim/retry ko'rsatmalari javobga ko'chib
        # ketmasligi uchun AVVAL tozalanadi (Mock promptni sarlavha qilib
        # qo'yadi — aynan shu yo'l bilan ko'rsatma sizib chiqardi).
        clean_prompt = strip_instruction_leaks(prompt.strip() if prompt else "") or "Ajoyib mavzu"

        # 🚀 PHASE 11 & 12 — advanced SMM rejimlari (48/49/33+50/51-bandlar):
        # multi-variant, repurpose, deep audit va content plan. Bu rejimlar
        # FAQAT services/ai/* xizmatlari ctx["smm_mode"] ni yoqqanda ishlaydi,
        # shu sababli quyidagi CREATE_POST / POST_AUDIT / ... javoblari (va
        # ularni tekshiruvchi mavjud testlar) O'ZGARMAYDI.
        try:
            from .smm_mock import smm_mock_reply
            smm_text = smm_mock_reply(ctx, clean_prompt)
            if smm_text:
                return smm_text
        except Exception as smm_err:  # noqa: BLE001 — mock hech qachon yiqilmaydi
            logger.debug("MockProvider SMM banki o'tkazib yuborildi: %s", smm_err)

        if lang == "ru":
            if intent == "GENERATE_VARIANTS":
                return (
                    "<b>3 Варианта рекламного поста:</b>\n\n"
                    "<b>Вариант 1 (Эмоциональный):</b>\n"
                    f"✨ Откройте для себя {clean_prompt}! Уникальное качество и стиль.\n\n"
                    "<b>Вариант 2 (Деловой):</b>\n"
                    f"💼 {clean_prompt} — надежное решение для вашего бизнеса и задач.\n\n"
                    "<b>Вариант 3 (Скидочный):</b>\n"
                    f"🔥 Только сегодня! Закажите {clean_prompt} с максимальной выгодой.\n\n"
                    "👉 Переходите по ссылке и выбирайте!\n"
                    "#варианты #smm #маркетинг #бизнес"
                )
            elif intent == "CONTENT_IDEAS":
                return (
                    "💡 <b>Идеи для контента на эту неделю:</b>\n\n"
                    f"1. 📌 Как правильно выбрать {clean_prompt}: советы эксперта.\n"
                    "2. 🔍 За кулисами нашего процесса: как все создается.\n"
                    "3. 📊 Кейс клиента: результаты до и после внедрения.\n"
                    "4. ❓ Ответы на самые частые вопросы подписчиков.\n\n"
                    "Сохраняйте в закладки, чтобы не потерять! 🚀\n"
                    "#контент #идеи #smm #продвижение"
                )
            elif intent == "POST_AUDIT":
                return (
                    "📊 <b>Аудит и экспертный разбор поста:</b>\n\n"
                    "✅ <b>Сильные стороны:</b> Понятная тема, живой и дружелюбный тон.\n"
                    "⚠️ <b>Точки роста:</b> Заголовок можно сделать ярче, добавить четкий CTA.\n"
                    "🎯 <b>Оценка качества:</b> 88 / 100.\n\n"
                    "💡 <b>Рекомендация:</b> Добавьте интерактивный вопрос в конце.\n"
                    "#аудит #smm #разбор"
                )
            else:
                return (
                    f"🔥 <b>{clean_prompt}</b>\n\n"
                    "Качественный контент — залог успешного продвижения вашего канала. "
                    "Мы предлагаем комплексный и продуманный подход к каждому клиенту.\n\n"
                    "📌 Главные преимущества:\n"
                    "• Надежность и проверенное качество\n"
                    "• Быстрая поддержка и профессионализм\n\n"
                    "👉 Напишите нам прямо сейчас, чтобы узнать подробности!\n\n"
                    "#новости #бизнес #качество #результат"
                )

        elif lang == "en":
            if intent == "GENERATE_VARIANTS":
                return (
                    "<b>3 Post Variations:</b>\n\n"
                    "<b>Option 1:</b>\n"
                    f"✨ Elevate your game with {clean_prompt}! Don't miss out.\n\n"
                    "<b>Option 2:</b>\n"
                    f"💼 Need better results? {clean_prompt} is the proven choice.\n\n"
                    "<b>Option 3:</b>\n"
                    f"🔥 Limited time offer: Get started with {clean_prompt} today!\n\n"
                    "👉 Click the link to learn more!\n"
                    "#marketing #smm #strategy #growth"
                )
            elif intent == "CONTENT_IDEAS":
                return (
                    "💡 <b>Top Content Ideas:</b>\n\n"
                    f"1. 📌 5 reasons why you need {clean_prompt}.\n"
                    "2. 🔍 Behind the scenes: Our daily routine.\n"
                    "3. 📊 Customer spotlight: Overcoming big challenges.\n\n"
                    "Save this post for later inspiration! 🚀\n"
                    "#content #ideas #smm #creator"
                )
            elif intent == "POST_AUDIT":
                return (
                    "📊 <b>Post Audit & Review:</b>\n\n"
                    "✅ <b>Strengths:</b> Clear message, good readability.\n"
                    "⚠️ <b>Areas to Improve:</b> Stronger call-to-action needed.\n"
                    "🎯 <b>Score:</b> 85 / 100.\n\n"
                    "#audit #review #optimization"
                )
            else:
                return (
                    f"🚀 <b>Exciting Update: {clean_prompt}</b>\n\n"
                    "Consistency and value are the keys to building a loyal audience. "
                    "Discover the easiest way to take your social media to the next level.\n\n"
                    "📌 Key Highlights:\n"
                    "• Premium standards and fast execution\n"
                    "• Built for creators and brands\n\n"
                    "👉 Join us today and see the difference for yourself!\n\n"
                    "#marketing #business #growth #smm"
                )

        else:
            # Standart: O'zbek tili
            if intent == "GENERATE_VARIANTS":
                return (
                    "<b>3 xil post varianti:</b>\n\n"
                    "<b>1-variant (Sotuvbop):</b>\n"
                    f"🔥 {clean_prompt} — qulay narx va yuqori sifat! Hoziroq xarid qiling.\n\n"
                    "<b>2-variant (Tavsiya/Ekspert):</b>\n"
                    f"💡 Nega aynan {clean_prompt}? Mutaxassislar tanlovi va amaliy tavsiyalar.\n\n"
                    "<b>3-variant (Qisqa va lo'nda):</b>\n"
                    f"⚡️ {clean_prompt} — siz kutgan natija bir qadam narida!\n\n"
                    "👉 Batafsil ma'lumot olish uchun profil havolasiga o'ting!\n"
                    "#variantlar #smm #marketing #toshkent"
                )
            elif intent == "CONTENT_IDEAS":
                return (
                    "💡 <b>Bu hafta uchun kontent g'oyalari:</b>\n\n"
                    f"1. 📌 {clean_prompt} haqida eng ko'p beriladigan 3 ta savolga javob.\n"
                    "2. 🔍 Jarayon ortida: Biz qanday qilib mahsulot/xizmat tayyorlaymiz.\n"
                    "3. 📊 Mijozimiz natijasi: Muammo va uning oson yechimi.\n"
                    "4. 💡 Hafta maslahati: O'zingiz mustaqil sinab ko'rishingiz mumkin bo'lgan lifehack.\n\n"
                    "G'oyalarni saqlab oling va kanalingizda qo'llang! 🚀\n"
                    "#goyalar #kontent #smm #reja"
                )
            elif intent == "POST_AUDIT":
                return (
                    "📊 <b>Post tahlili va ekspert xulosasi:</b>\n\n"
                    "✅ <b>Kuchli tomonlari:</b> Mavzu dolzarb, uslub ravon va tushunarli.\n"
                    "⚠️ <b>Yaxshilash mumkin bo'lgan joylar:</b> Hook (birinchi jumla)ni kuchaytirish va harakatga chaqiriq (CTA) qo'shish tavsiya etiladi.\n"
                    "🎯 <b>Umumiy ball:</b> 89 / 100.\n\n"
                    "#audit #tahlil #smm #maslahat"
                )
            elif intent == "IMPROVE_POST":
                return (
                    f"✨ <b>Sayqallangan va yaxshilangan post:</b>\n\n"
                    f"🎯 {clean_prompt}\n\n"
                    "📌 Endi post ancha qiziqarli, o'qilishi oson va harakatga undovchi shaklga keltirildi.\n\n"
                    "👉 Fikringizni izohlarda qoldiring yoki bizga yozing!\n"
                    "#yaxshilangan #post #smm #tavsiya"
                )
            elif intent == "SHORTEN":
                return (
                    f"⚡️ <b>{clean_prompt}</b>\n\n"
                    "Qisqa va aniq: eng muhim afzalliklar va siz uchun qulay yechim.\n\n"
                    "👉 Batafsil profil havolasida!\n"
                    "#qisqa #lo'nda #muhim"
                )
            elif intent == "EXPAND":
                return (
                    f"📖 <b>Batafsil ma'lumot: {clean_prompt}</b>\n\n"
                    "Ushbu yo'nalish har birimiz uchun muhim ahamiyatga ega. Keling, har bir jihatni batafsil tahlil qilamiz:\n\n"
                    "1. <b>Boshlanishi va mohiyati:</b> Har qanday muvaffaqiyat to'g'ri rejalashtirishdan boshlanadi.\n"
                    "2. <b>Asosiy xususiyatlar:</b> Amaliyotda qo'llash orqali vaqtingizni va mablag'ingizni tejaysiz.\n"
                    "3. <b>Natijalar:</b> To'g'ri tanlov sizga uzoq muddatli foyda keltiradi.\n\n"
                    "👉 Savollaringiz bormi? Hoziroq murojaat qiling!\n"
                    "#batafsil #maqola #foydali #bilim"
                )
            else:
                # CREATE_POST
                return (
                    f"🔥 <b>{clean_prompt}</b>\n\n"
                    "Har bir jiddiy loyiha puxta o'ylangan yondashuvni talab qiladi. "
                    "Biz mijozlarimizga faqat eng yaxshi va sinalgan yechimlarni taqdim etamiz.\n\n"
                    "📌 Siz nimalarga ega bo'lasiz?\n"
                    "• Qulay va tezkor xizmat ko'rsatish;\n"
                    "• 100% kafolatlangan yuqori natija;\n"
                    "• Malakali mutaxassislarning doimiy yordami.\n\n"
                    "👉 Hoziroq bog'laning va maxsus chegirmaga ega bo'ling!\n\n"
                    "#yangilik #smm #toshkent #biznes #rivojlanish"
                )


class ProviderChain:
    """Zaxira provayderlar zanjiri (Fallback Chain).

    Gemini 2.5 Flash -> Groq -> OpenRouter (-> Mock, faqat dev/test muhitida).

    P0-A: Mock zaxira provayderi FAQAT ``mock_is_allowed()`` rost bo'lganda
    (``ENVIRONMENT`` dev/test yoki ``AI_ALLOW_MOCK=1``) zanjirga qo'shiladi va
    chaqiriladi. Production'da esa zanjir oshkora xato bilan tugaydi.
    """

    def __init__(self, providers: list[AIProvider] | None = None):
        if providers is not None:
            self.providers = list(providers)
        else:
            self.providers = [
                GeminiProvider(),
                GroqProvider(),
                OpenRouterProvider(),
            ]
            if mock_is_allowed():
                self.providers.append(MockProvider())

    def usable_providers(self) -> list[AIProvider]:
        """Zanjirdagi haqiqatda ishlatilishi mumkin bo'lgan provayderlar.

        - kaliti yo'q (``is_available() is False``) provayderlar o'tkazib yuboriladi;
        - P0-A: Mock production siyosatiga bo'ysunadi — ruxsat etilmagan muhitda
          zanjirdan BUTUNLAY chiqarib tashlanadi (hatto aniq uzatilgan bo'lsa ham).
        """
        allowed_mock = mock_is_allowed()
        usable: list[AIProvider] = []
        for provider in self.providers:
            if isinstance(provider, MockProvider) and not allowed_mock:
                logger.debug(
                    "MockProvider zanjirdan chiqarildi: %s=%s, %s=0 (P0-A)",
                    ENVIRONMENT_VAR, get_environment(), AI_ALLOW_MOCK_VAR,
                )
                continue
            if not provider.is_available():
                logger.debug("Provayder %s mavjud emas (kalit yo'q), o'tkazib yuborilmoqda",
                             provider.name)
                continue
            usable.append(provider)
        return usable

    async def execute(self, prompt: str, context: dict | None = None) -> tuple[str, str]:
        """Provayderlarni navbat bilan chaqiradi.
        Birinchi muvaffaqiyatli natija va provayder nomini (content, provider_name) qaytaradi.

        P0-A: hech bir HAQIQIY provayder ishlamasa, Mock FAQAT ruxsat etilgan
        muhitda (dev/test yoki ``AI_ALLOW_MOCK=1``) zaxira sifatida chaqiriladi;
        aks holda :class:`NoConfiguredProviderError` /
        :class:`AllProvidersFailedError` ko'tariladi (soxta generatsiya YO'Q).
        """
        errors: list[str] = []
        providers = self.usable_providers()

        for provider in providers:
            try:
                logger.info("AI Provider chaqirilmoqda: %s", provider.name)
                result = await provider.generate(prompt, context)
                # P0-C: javobdagi tizim/retry ko'rsatmalari tozalanadi
                clean_result, leak_found = sanitize_output(result)
                if leak_found:
                    logger.warning("P0-C: %s javobidan tizim ko'rsatmasi tozalandi",
                                   provider.name)
                if clean_result:
                    return clean_result, provider.name
                errors.append(f"{provider.name}: bo'sh javob")
            except Exception as e:
                logger.warning("Provayder %s xatosi: %s. Keyingisiga o'tilmoqda...",
                               provider.name, e)
                errors.append(f"{provider.name}: {e}")

        # P0-A: Mock zaxira faqat ruxsat etilgan muhitda va zanjirda
        # hali sinalmagan bo'lsa.
        already_tried_mock = any(isinstance(p, MockProvider) for p in providers)
        if mock_is_allowed() and not already_tried_mock:
            mock = MockProvider()
            try:
                res = await mock.generate(prompt, context)
                clean_res, leak_found = sanitize_output(res)
                if leak_found:
                    logger.warning("P0-C: Mock javobidan tizim ko'rsatmasi tozalandi")
                if clean_res:
                    return clean_res, mock.name
                errors.append("Mock: bo'sh javob")
            except Exception as e:
                errors.append(f"Mock: {e}")

        detail = "; ".join(errors) or "sabab noma'lum"
        if not providers:
            raise NoConfiguredProviderError(
                "Hech qanday AI provayderi sozlanmagan "
                f"({ENVIRONMENT_VAR}={get_environment()}, Mock taqiqlangan). Xato: {detail}"
            )
        raise AllProvidersFailedError(f"Barcha AI provayderlari ishlamadi: {detail}")
