#!/usr/bin/env python3
"""🗓 SMART CONTENT CALENDAR — KONTRAKT TESTLARI (deterministik, tarmoqsiz).

Qamrov (kontent-kalendar shartnomasi bo'yicha):

  TEST 1:  FREE foydalanuvchi 7 kunlik reja TUZISHI mumkin ((True, "ok")) va
           reja matnida soha (biznes) hamda kunlar («1-kun» … «7-kun»)
           aks etadi (render_calendar).
  TEST 2:  30 kunlik reja FAQAT PRO uchun — FREE da (False, "pro_required").
           Noto'g'ri davomiylik (masalan 14 kun) RAD etiladi ("invalid_duration").
           PRO foydalanuvchi 30 kunlik reja oladi ((True, "ok")).
  TEST 3:  FREE haftalik limiti — 1 ta 7 kunlik reja; ikkinchisi
           (False, "weekly_limit").
  TEST 4:  Tanlangan kun mavzusi «✨ Magic Post» oqimiga AYNAN shu topic
           sifatida uzatiladi (selected_topic_for_magic_post), bo'sh/yaroqsiz
           qiymatlarda xavfsiz bo'sh satr qaytadi.
  TEST 5:  🌐 I18N — translations/content_calendar.py UZ/RU/EN 100% paritet
           (kalitlar to'plami bir xil).
  TEST 6:  🛡 XAVFSIZLIK — is_pro_user database xatosida FAIL-CLOSED (PRO
           berilmaydi); AI javobi (normalize_items) faqat lug'at shaklidagi
           yozuvlarni o'tkazadi, kunlar sonidan ortiq kesiladi; render_calendar
           ishonchsiz matnni HTML-escape qiladi (<script> o'tib ketmaydi).

Ishga tushirish:
    PYTHON=/home/user/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/content_calendar_flow_test.py
"""
import os
import sys
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
#    (config.py BOT_TOKEN va DATABASE_URL bo'lmasa RuntimeError beradi.)
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:CONTENT_CALENDAR_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10007")

warnings.filterwarnings("ignore")

# Mutlaq yo'l — test istalgan CWD dan ishga tushirilganda ham topiladi.
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

from handlers.content_calendar import (
    can_create_calendar,
    is_pro_user,
    normalize_items,
    render_calendar,
    selected_topic_for_magic_post,
)
from translations.content_calendar import content_calendar_parity


class DB:
    """Minimal entitlement stub: PRO holatini qaytaradi."""

    def __init__(self, pro=False):
        self.pro = pro

    def is_premium(self, _):
        return self.pro


class BoomDB:
    """Database xatosini modellaydi — entitlement FAIL-CLOSED bo'lishi shart."""

    def is_premium(self, _):
        raise RuntimeError("database unavailable")


PASSED = 0
FAILURES = 0


def check(condition, label):
    """Bitta tekshiruv natijasini hisobga oladi va chop etadi."""
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label}")
    return bool(condition)


# ---------------------------------------------------------------------------
# TEST 1 — 7 kunlik reja (FREE) va render
# ---------------------------------------------------------------------------
def test_seven_day_calendar_for_business():
    print("== 1) 7 kunlik reja (FREE) + render ==")
    check(can_create_calendar(1, 7, DB(False), 0) == (True, "ok"),
          "FREE foydalanuvchi 7 kunlik reja tuza oladi")
    text = render_calendar(
        [{"rubric": "Foyda", "topic": "5 maslahat", "tip": "Misol keltiring"}] * 7,
        "Ayollar kiyimi",
    )
    check("1-kun" in text, "rejada «1-kun» mavjud")
    check("Ayollar kiyimi" in text, "rejada soha (business) aks etgan")
    check(all(f"{n}-kun" in text for n in range(1, 8)),
          "barcha 7 kun ketma-ket chizilgan (1-kun … 7-kun)")


# ---------------------------------------------------------------------------
# TEST 2 — PRO entitlement va davomiylik validatsiyasi
# ---------------------------------------------------------------------------
def test_free_cannot_create_thirty_days():
    print("== 2) 30 kunlik reja faqat PRO + davomiylik validatsiyasi ==")
    check(can_create_calendar(1, 30, DB(False)) == (False, "pro_required"),
          "FREE foydalanuvchiga 30 kunlik reja yopiq (pro_required)")
    check(can_create_calendar(1, 30, DB(True)) == (True, "ok"),
          "PRO foydalanuvchi 30 kunlik reja tuza oladi")
    check(can_create_calendar(1, 14, DB(True)) == (False, "invalid_duration"),
          "noto'g'ri davomiylik (14 kun) rad etiladi (invalid_duration)")


# ---------------------------------------------------------------------------
# TEST 3 — haftalik limit (qo'shimcha: i18n bilan birga asl testda)
# ---------------------------------------------------------------------------
def test_free_weekly_limit():
    print("== 3) FREE haftalik limiti (1 ta 7 kunlik reja) ==")
    check(can_create_calendar(1, 7, DB(False), 1) == (False, "weekly_limit"),
          "FREE da haftasiga 2-reja rad etiladi (weekly_limit)")
    check(can_create_calendar(1, 7, DB(True), 5) == (True, "ok"),
          "PRO foydalanuvchida haftalik limit qo'llanilmaydi")


# ---------------------------------------------------------------------------
# TEST 4 — tanlangan kun → Magic Post mavzusi
# ---------------------------------------------------------------------------
def test_selected_day_is_magic_post_topic():
    print("== 4) Tanlangan kun → «✨ Magic Post» mavzusi ==")
    check(selected_topic_for_magic_post({"topic": "Yangi chegirma", "rubric": "Chegirma"})
          == "Yangi chegirma", "topic aynan uzatiladi")
    check(selected_topic_for_magic_post({"title": "Sarlavha"}) == "Sarlavha",
          "topic yo'q bo'lsa title zaxirasi ishlaydi")
    check(selected_topic_for_magic_post({}) == "", "bo'sh yozuv → bo'sh satr")
    check(selected_topic_for_magic_post(None) == "", "yaroqsiz (None) yozuv → bo'sh satr")


# ---------------------------------------------------------------------------
# TEST 5 — i18n paritet (UZ/RU/EN)
# ---------------------------------------------------------------------------
def test_i18n_parity_and_weekly_limit():
    print("== 5) UZ/RU/EN 100% paritet ==")
    parity = content_calendar_parity()
    check(bool(parity), "paritet tekshiruvi natija qaytardi")
    check(all(parity.values()), f"uchala tilda kalitlar bir xil: {parity}")
    check(can_create_calendar(1, 7, DB(False), 1) == (False, "weekly_limit"),
          "haftalik limit regressiya qo'riqoni")


# ---------------------------------------------------------------------------
# TEST 6 — xavfsizlik: fail-closed entitlement, AI javobi, HTML escape
# ---------------------------------------------------------------------------
def test_security_fail_closed_and_escaping():
    print("== 6) Xavfsizlik: fail-closed + AI javobi + HTML escape ==")
    check(is_pro_user(1, DB(True)) is True, "PRO entitlement to'g'ri aniqlanadi")
    check(is_pro_user(1, BoomDB()) is False,
          "database xatosida PRO berilmaydi (FAIL-CLOSED)")
    check(can_create_calendar(1, 30, BoomDB()) == (False, "pro_required"),
          "DB xatosida 30 kunlik reja rad etiladi")

    check(len(normalize_items([{"topic": str(i)} for i in range(10)], 7)) == 7,
          "AI javobi kunlar sonidan ortiq kengaytirilmaydi (kesiladi)")
    check(normalize_items(["x", "y"], 7) == [],
          "lug'at bo'lmagan yozuvlar filtrlanadi")
    check(normalize_items([{}], 1) == [{"rubric": "Foydali maslahat",
                                        "topic": "", "tip": ""}],
          "yetishmayotgan kalitlar xavfsiz standart qiymat oladi")

    escaped = render_calendar(
        [{"rubric": "R", "topic": "<script>alert(1)</script>", "tip": "t"}],
        "<b>biz</b>",
    )
    check("<script>" not in escaped, "xom <script> matnga o'tib ketmaydi")
    check("&lt;script&gt;" in escaped, "ishonchsiz matn HTML-escape qilingan")
    check("&lt;b&gt;" in escaped, "soha (business) ham escape qilingan")


def main():
    print("=" * 62)
    print(" 🗓 SMART CONTENT CALENDAR — KONTRAKT TESTLARI")
    print("=" * 62)

    test_seven_day_calendar_for_business()
    test_free_cannot_create_thirty_days()
    test_free_weekly_limit()
    test_selected_day_is_magic_post_topic()
    test_i18n_parity_and_weekly_limit()
    test_security_fail_closed_and_escaping()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] KONTENT KALENDAR TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA KONTENT KALENDAR TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
