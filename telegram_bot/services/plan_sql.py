"""Tarif berishning YAGONA SQL qoidasi (to'lov, karta cheki, Payme, admin berishi bir xil ishlaydi).

* ``enterprise`` (muddatsiz admin bergan) HECH QACHON o'zgarmaydi;
* faol ``ultra`` foydalanuvchi PRO xarid qilsa tarifi PASAYMAYDI (muddat qo'shiladi — to'langan pul yo'qolmaydi);
* PRO -> ULTRA xarid: tarif darhol ULTRA bo'ladi, muddat ``max(joriy, hozir) + kunlar`` (qolgan PRO kunlari yo'qolmaydi);
* aks holda xarid qilingan tarif.
Tarif nomi FAQAT oq ro'yxatdan SQL matniga qo'yiladi (foydalanuvchi qiymati emas).
"""
from __future__ import annotations

_TIERS = ("pro", "ultra")


def grant_plan_case(tier: str) -> str:
    """``plan_type`` uchun ``CASE`` ifodasi (qo'shimcha parametrsiz)."""
    if tier not in _TIERS:
        raise ValueError("noma'lum tarif")
    keep_ultra = "WHEN plan_type = 'ultra' THEN plan_type " if tier == "pro" else ""
    return f"CASE WHEN plan_type = 'enterprise' THEN plan_type {keep_ultra}ELSE '{tier}' END"


def grant_expiry_case() -> str:
    """``subscription_expires_at`` uchun ``CASE``: bitta ``%s`` (kunlar) parametri; muddatsiz enterprise o'zgarmaydi."""
    return ("CASE WHEN plan_type = 'enterprise' AND subscription_expires_at IS NULL THEN NULL ELSE "
            "GREATEST(COALESCE(subscription_expires_at, NOW()), NOW()) + (%s || ' days')::INTERVAL END")
