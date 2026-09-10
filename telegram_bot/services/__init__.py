"""Service Layer — biznes mantiqni DB CRUD dan ajratadi.

Har bir servis o'z domeniga tegishli qoidalarni boshqaradi:
  - SubscriptionService: tariflar, obuna muddati, admin bonus
  - PaymentService: Stars to'lov, karta chek tasdiqlash
  - PromoService: promo-kod yaratish va faollashtirish
  - AIFallbackService: AI multi-provider fallback (4-BOSQICH) —
    Gemini → Groq → OpenRouter → zaxira zanjir, qat'iy timeout

database.py faqat CRUD (ma'lumotlar bazasi so'rovlari) bajaradi;
biznes qoidalar shu paketdagi servislar orqali amalga oshiriladi.

Eski chaqiruvlar (``db.set_user_plan``, ``db.redeem_promo_code`` va h.k.)
backward compatibility uchun shu servicelarga delegatsiya qiladi.
"""

from services.subscription_service import SubscriptionService  # noqa: F401
from services.payment_service import PaymentService  # noqa: F401
from services.promo_service import PromoService  # noqa: F401
from services.scheduler_service import SchedulerService  # noqa: F401
from services.ai_service import AIFallbackService  # noqa: F401

__all__ = [
    "SubscriptionService",
    "PaymentService",
    "PromoService",
    "SchedulerService",
    "AIFallbackService",
]
