# -*- coding: utf-8 -*-
"""
=====================================================================
 🗂 REPOSITORIES — domain bo'yicha ma'lumotlar bazasi kirish qatlami
=====================================================================

Modul                Domain
===================== ==========================================
  ``settings `` Global bot sozlamalari (``settings`` jadvali): kalit-qiymat yozish/o'qish, topshiriq bo'yicha guruhlash va o'chirish. Kichik TTL kesh bilan.
  ``users    `` Foydalanuvchi profili, til (uz/ru/en), onboarding holati, seriya raqami, referral o'yini, AI krediti/quotasi, PRO obuna (tier) va barcha foydalanuvchi-guruh limitlari (``check_*_limit``).
  ``channels `` Kanal ro'yxati va monitoringi, Channel Intelligence (post event ingestion) va Channel DNA profillari, kanal sozlamalari/toni, reklama dvigateli, sponsor kanallar, kontent manbalari (RSS/ATOM), qoralamalar va recycle.
  ``posts    `` Postlar yaratish/o'qish/tahrirlash, status o'tishlari, media/reaksiyalar, auto-delete jadvali, navbat (queue) slotlari va shablonlar (post_templates).
  ``analytics`` Kanal tahlili uchun BATCH (N+1'siz) o'qishlari: postlar metrikasi bitta JOIN/GROUP BY'da, kanal xulosasi (o'rtacha ko'rishlar, eng yaxshi formatlar) DB darajasida — ``= ANY(%s)`` bilan ko'p kanal bitta so'rovda.
  ``scheduler`` Haftalik rejalashtirish, Telegram delivery joblari (idempotency, backoff, dead-letter), 'processing' holatidan tiklash, eskirgan ma'lumotlarni tozalash va bo'sh navbat slotini topish.
  ``teams    `` Kanal a'zolari va ularning rollari (owner/editor/scheduler/analyst), post taklif -> tasdiq -> nashr ish jarayoni va audens savollari insightlari.
  ``payments `` To'lov holatlari va usullari, Telegram Stars payment orderlari, karta chek (payment_receipts) tasdiqlash/rad etish oqimi va to'lov sog'ligi hisobotlari.
  ``audit    `` Admin rollari (RBAC), xavfsizlik/audit loglari (``admin_audit_logs``), bot bo'yicha tizim statistikasi va qo'llab-quvvatlash murojaatlari (ticket).
===================== ==========================================
Import tartibi: avval yadorni (``database``) to'liq yuklaymiz, keyin
repository modullarini. Bu ``import repositories.*`` va
``import database`` tartiblarining IKKALASI ham xavfsiz ishlashini
ta'minlaydi (import sikli yo'q).
"""
#: Yadro avval yuklanishi SHART: repository modullari undan
#: ``repositories.runtime`` orqali bog'lanadi.
import database as _database_core  # noqa: F401

from repositories import runtime  # noqa: F401
from repositories.runtime import *  # noqa: F401,F403

#: Diagnostika / monitoring uchun ro'yxat.
REPOSITORIES = (
    "repositories.settings_repository",
    "repositories.users_repository",
    "repositories.channels_repository",
    "repositories.posts_repository",
    "repositories.scheduler_repository",
    "repositories.teams_repository",
    "repositories.payments_repository",
    "repositories.audit_repository",
)

__all__ = ["REPOSITORIES", "runtime"]

#: Diagnostika / monitoring uchun QO'SHIMCHA (ixtiyoriy) repository modullari.
#: ``REPOSITORIES`` (asosiy 8 ta domain moduli) tarixiy shartnoma bo'lib,
#: ``tests/repository_layering_test.py`` uni AYNAN 8 talik deb qulflaydi —
#: shuning uchun yangi qatlamlar shu alohida ro'yxatda e'lon qilinadi.
#: ``repositories.analytics_repository`` — P1 (5-qadam) batch analitika
#: qatlami: N+1 query'siz kanal tahlili (bitta JOIN/GROUP BY + bitta
#: DB darajasidagi agregatsiya). ``database`` facade'i ham uning barcha
#: eksportlarini qayta chiqaradi (``database.get_channel_analytics_bundle``).
OPTIONAL_REPOSITORIES = (
    "repositories.analytics_repository",
)