#!/usr/bin/env python3
"""💳 To'lov mintaqasi tanlovi (payment region) — HUDUDIY, TILGA BOG'LIQ EMAS.

PostAssist V2 to'lov arxitekturasi shartnomalari:

  1. Barcha tillarda (UZ / RU / EN) to'lov mintaqasini tanlash tugmalari
     to'g'ri chiqadi: 🇺🇿 (Uzcard / Humo) va 🌍 (Stars / Crypto / Card).
     Til FAQAT yorliqlarni tarjima qiladi — callback_data bir xil, ya'ni
     hech qanday til uchun HECH QANDAY cheklov yo'q.
  2. Rus tilidagi foydalanuvchi 'Uzcard/Humo'ni tanlaganda MAHALLIY to'lov
     ekrani (so'mdagi narx + karta rekvizitlari + chek oqimi) chiqadi.
  3. 'International' tanlanganda Uzcard / Humo BUTUNLAY ko'rinmaydi va
     xalqaro oqim (Telegram Stars invoice, ~$ ekvivalent) ishlaydi.
  4. Ledger: payment_method='uzcard_humo' (UZS) va 'international_stars'
     (XTR) ajratilgan; idempotency (charge_id/receipt:<id> UNIQUE), audit
     va to'lov+grant BIR tranzaksiyada.

DB talab qilinmaydi (handler oqimlari fake update/context bilan, servislar
mock tranzaksiya bilan sinovdan o'tadi).

Ishga tushirish:
    cd telegram_bot && python tests/payment_region_selection_test.py
"""
import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:PAYMENT_REGION_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
# Karta rekvizitlari (.env o'rniga) — mahalliy ekran matnini tekshirish uchun.
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Sayitqulov S.")

ROOT = Path(__file__).resolve().parent.parent  # telegram_bot/
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0
LANGS = ("uz", "ru", "en")


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {('| ' + str(extra)) if extra else ''}")


# ---------------------------------------------------------------------------
# Fake PTB obyektlari — subscription_callback'ni real handler sifatida
# ishga tushirish uchun (DB/Telegram'siz).
# ---------------------------------------------------------------------------

class _Query:
    def __init__(self, data, user_id, message):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.edits = []
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((str(text), kwargs))


class _Message:
    def __init__(self, chat_id=555001):
        self.chat_id = chat_id
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((str(text), kwargs))

    async def delete(self):
        pass


class _Bot:
    def __init__(self):
        self.invoices = []
        self.messages = []

    async def send_invoice(self, **kwargs):
        self.invoices.append(kwargs)

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class _Ctx:
    def __init__(self, bot, lang="ru"):
        self.bot = bot
        self.user_data = {"lang": lang}


def _update(query):
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=query.from_user.id),
        effective_chat=SimpleNamespace(id=query.message.chat_id),
    )


def _flat_kb(markup):
    return [b for row in markup.inline_keyboard for b in row]


def _kb_texts_kb(markup):
    flat = _flat_kb(markup)
    return " ".join(f"{b.text} {b.callback_data or ''} {b.url or ''}" for b in flat)


def _run_region_flow(lang, steps, uid=555001):
    """subscription_callback'ni ketma-ket callback'lar bilan yurgizadi.

    Returns: (bot, last_query, all_texts, context) — all_texts = barcha
    ko'rsatilgan ekran matnlari + markup hujjatlarining to'liq auditingi.
    """
    import handlers.subscription as sub

    bot = _Bot()
    ctx = _Ctx(bot, lang=lang)
    all_texts = []
    all_markups = []
    last_q = None
    for data in steps:
        msg = _Message()
        q = _Query(data, uid, msg)
        last_q = q
        asyncio.run(sub.subscription_callback(_update(q), ctx))
        for text, kwargs in q.edits + msg.replies:
            all_texts.append(text)
            if kwargs.get("reply_markup") is not None:
                all_markups.append(kwargs["reply_markup"])
    return bot, last_q, all_texts, all_markups, ctx


# ============================================================
# 1) Barcha tillarda (UZ/RU/EN) hududiy tanlov tugmalari to'g'ri
# ============================================================

def test_region_buttons_all_languages():
    print("== 1. Mintaqa tanlov tugmalari: UZ / RU / EN ==")
    from keyboards.inline import (
        PAYMENT_REGION_INTL,
        PAYMENT_REGION_UZ,
        get_payment_region_keyboard,
    )
    from locales.translations import get_text

    check("Mintaqa konstantalari", PAYMENT_REGION_UZ == "uz" and PAYMENT_REGION_INTL == "intl")

    for lang in LANGS:
        kb = get_payment_region_keyboard(lang)
        rows = kb.inline_keyboard
        check(f"[{lang}] 3 qator (UZ mintaqasi, Intl, orqaga)", len(rows) == 3, len(rows))
        flat = _flat_kb(kb)
        labels = [b.text for b in flat]
        cbs = [b.callback_data for b in flat]
        check(f"[{lang}] 🇺🇿 tugma mahalliy usulni ko'rsatadi",
              labels[0] == get_text("pay_region_uz", lang)
              and "Uzcard" in labels[0] and "Humo" in labels[0], labels)
        check(f"[{lang}] 🌍 tugma xalqaro usullarni ko'rsatadi",
              labels[1] == get_text("pay_region_intl", lang)
              and "Stars" in labels[1] and "Crypto" in labels[1], labels)
        check(f"[{lang}] callback_data routing", cbs == ["sub_region:uz", "sub_region:intl", "sub_back"], cbs)
        check(f"[{lang}] callback_data 64 baytdan oshmaydi",
              all(len(str(c).encode("utf-8")) <= 64 for c in cbs), cbs)

    # Til — FAQAT yorliq: RU tugma matni RU, UZ tugma matni UZ, lekin
    # callback_data uchala tilda HAM bir xil (cheklov yo'q).
    labels_by_lang = {
        lang: [b.text for b in _flat_kb(get_payment_region_keyboard(lang))]
        for lang in LANGS
    }
    cbs_by_lang = {
        lang: [b.callback_data for b in _flat_kb(get_payment_region_keyboard(lang))]
        for lang in LANGS
    }
    check("Uchala til yorlig'i tarjimasi har xil (tilga mos chiqadi)",
          len({tuple(labels_by_lang[c]) for c in LANGS}) == 3, labels_by_lang)
    check("Callback_data 3 tilda IDENTIK (til bo'yicha taqiq YO'Q)",
          len({tuple(cbs_by_lang[c]) for c in LANGS}) == 1, cbs_by_lang)
    check("RU foydalanuvchi ham Uzcard/Humo tugmasini oladi (mahalliy cheklov yo'q)",
          "Узбекистан" in labels_by_lang["ru"][0] and "Uzcard" in labels_by_lang["ru"][0])
    check("EN foydalanuvchi ham xalqaro tugmani oladi",
          "International" in labels_by_lang["en"][1])

    # Tarif konteksti bilan (sub_pay:stars_X → sub_region:*:<plan>).
    kb_plan = get_payment_region_keyboard("ru", "3m")
    cbs_plan = [b.callback_data for b in _flat_kb(kb_plan)]
    check("Plan konteksti bilan callback'lar",
          cbs_plan[:2] == ["sub_region:uz:3m", "sub_region:intl:3m"], cbs_plan)

    # Matnlar: placeholder/HTML pariteti (3 til bir xil {tarif}).
    from locales.translations import format_args

    for key in ("pay_region_title", "pay_region_uz", "pay_region_intl",
                "pay_region_selected", "intl_payment_title",
                "intl_payment_selected", "intl_payment_hint",
                "intl_tariff_1m", "intl_tariff_3m", "intl_tariff_1y"):
        vals = {c: get_text(key, c) for c in LANGS}
        check(f"lug'at kaliti [{key}]: 3 tilda mavjud va bo'sh emas",
              all(v and v != key for v in vals.values()), vals)
        argsets = {frozenset(format_args(v)) for v in vals.values()}
        check(f"kalit [{key}] placeholder'lari 3 tilda bir xil",
              len(argsets) == 1, argsets)

    # Mintaqa menyusida TO'LOV REKVIZITLARI (karta raqami/summa) bo'lmasligi kerak.
    import handlers.subscription as sub
    text_uz = sub._build_pay_region_text("uz", "1m")
    text_ru = sub._build_pay_region_text("ru", "1m")
    for lang_text in (text_uz, text_ru):
        check("Mintaqa menyusida rekvizit yo'q (faqat tanlov)",
              "8600 0609 5082 5589" not in lang_text and "19 000" not in lang_text,
              lang_text[:80])
    check("Mintaqa menyusida tanlangan tarif eslatiladi (RU)",
          "1 месяц" in text_ru, text_ru)


# ============================================================
# 2) Rus tilidagi foydalanuvchi 'Uzcard/Humo' → mahalliy to'lov
# ============================================================

def test_ru_user_local_flow():
    print("== 2. RU foydalanuvchi → 🇺🇿 Uzcard/Humo (mahalliy to'lov) ==")

    bot, last_q, texts, markups, ctx = _run_region_flow(
        "ru", ["sub_pay:stars_1m", "sub_region:uz:1m"]
    )
    joined = "\n".join(texts)
    first_screen = texts[0] + "\n" + (_kb_texts_kb(markups[0]) if markups else "")
    check("Tarif tanlangach avval mintaqa menyusi (2 tugma) chiqadi",
          "Выберите регион оплаты" in first_screen
          and "Узбекистан" in first_screen and "Международная" in first_screen,
          first_screen[:160])
    check("Tarif tanlashda REKVIZIT DARHOL chiqmaydi: mintaqa tanlovigacha invoice yo'q",
          not bot.invoices, bot.invoices)
    check("RU tanlovdan so'ng mahalliy ekran: so'mdagi narx 19 000",
          "19 000" in joined, joined[:200])
    check("RU tanlovdan so'ng karta rekviziti ko'rsatiladi",
          "8600 0609 5082 5589" in joined and "Sayitqulov S." in joined,
          joined[:200])
    check("Mahalliy ekran RU tilida (til cheklamaydi — ruscha karta to'lovi)",
          "Оплата картой" in joined, joined[:160])
    kb_cb_all = [b.callback_data for m in markups for b in _flat_kb(m) if b.callback_data]
    check("Chek yuborish tugmasi mavjud (mahalliy Admin Approval Flow)",
          "sub_send_receipt" in kb_cb_all, kb_cb_all)
    check("Mahalliy ekranda Stars invoice tugmalari YO'Q (faqat mahalliy usullar)",
          not any("sub_pay" in c or "sub_intl_plan" in c for c in kb_cb_all), kb_cb_all)
    check("Kontekstda mintaqa qayd etildi", ctx.user_data.get("pay_region") == "uz",
          ctx.user_data)

    # sub_card_pay tugmasi ham RU'da ishlaydi (mahalliy tarif tanlagichi, so'm).
    bot2, _, texts2, markups2, _ = _run_region_flow("ru", ["sub_card_pay"])
    flat2 = _flat_kb(markups2[0]) if markups2 else []
    labels2 = [b.text for b in flat2]
    check("sub_card_pay → RU tarif tanlagichi (so'mdagi narxlar)",
          any("1 месяц" in t and "19 000" in t for t in labels2), labels2)
    check("sub_card_pay hali ham invoice YUBORMAYDI", not bot2.invoices)


# ============================================================
# 3) International → Uzcard/Humo butunlay ko'rinmaydi + intl oqim
# ============================================================

def test_international_flow_hides_local_cards():
    print("== 3. 🌍 International: Uzcard/Humo YASHIRIN, Stars oqimi ishlaydi ==")

    # 3.1 Mintaqa menyusi (RU tilida!) — international tanlandi: tariflar.
    bot, q, texts, markups, ctx = _run_region_flow("ru", ["sub_region:intl"])
    joined = "\n".join(texts)
    kb_all = _kb_texts_kb(markups[0]) if markups else ""
    check("Intl ekranida 'Uzcard' SO'ZI UMUMAN YO'Q",
          "Uzcard" not in joined and "Uzcard" not in kb_all, (joined + kb_all)[:160])
    check("Intl ekranida 'Humo' SO'ZI UMUMAN YO'Q",
          "Humo" not in joined and "Humo" not in kb_all, (joined + kb_all)[:160])
    check("Intl ekranida karta raqami YO'Q",
          "8600 0609 5082 5589" not in joined + kb_all)
    check("Intl ekranida so'm narxlari ko'rsatilmaydi", "19 000" not in joined)
    cb_all = [b.callback_data for b in _flat_kb(markups[0])] if markups else []
    check("Intl tarif tanlagichi: faqat 3 Stars paketi + orqaga (mintaqa menyusiga)",
          cb_all == ["sub_intl_plan:1m", "sub_intl_plan:3m", "sub_intl_plan:1y",
                     "sub_region"], cb_all)

    # 3.2 To'g'ridan-to'g'ri plan bilan: sub_region:intl:1y → Stars invoice.
    bot2, q2, texts2, markups2, ctx2 = _run_region_flow("en", ["sub_region:intl:1y"])
    check("Intl plan tanlangach invoice YUBORILDI", len(bot2.invoices) == 1, bot2.invoices)
    inv = bot2.invoices[0] if bot2.invoices else {}
    check("Invoice: valuta XTR (Stars), summa 550",
          inv.get("currency") == "XTR" and inv.get("prices")
          and inv["prices"][0].amount == 550, inv)
    check("Invoice payload eski kontrakt bilan mos (sub_stars_<plan>_<uid>)",
          inv.get("payload") == "sub_stars_1y_555001", inv.get("payload"))
    check("Invoice sarlavha/tavsif foydalanuvchi TILIDA (en)",
          "1 year" in str(inv.get("title")) and "1 year" in str(inv.get("description")),
          f"{inv.get('title')} / {inv.get('description')}")
    joined2 = "\n".join(texts2)
    check("Intl ekran: ekvivalent valyuta — Stars + ~$11.0 ko'rsatiladi",
          "550 Stars" in joined2 and "$11.0" in joined2, joined2[:200])
    kb_all2 = _kb_texts_kb(markups2[-1]) if markups2 else ""
    check("Intl to'lov ekranida ham Uzcard/Humo YO'Q",
          "Uzcard" not in joined2 + kb_all2 and "Humo" not in joined2 + kb_all2,
          (joined2 + kb_all2)[:160])
    flat2 = [b.callback_data for b in _flat_kb(markups2[-1])] if markups2 else []
    check("Intl ekranida chek/mahalliy tugmalar YO'Q, orqa — mintaqa menyusiga",
          flat2 == ["sub_region"] and "sub_send_receipt" not in flat2, flat2)
    check("Kontekstda intl mintaqasi qayd etildi", ctx2.user_data.get("pay_region") == "intl")

    # 3.3 sub_intl_plan:3m ham invoice yuboradi (tanlagich tugmasi).
    bot3, _, texts3, _, _ = _run_region_flow("uz", ["sub_intl_plan:3m"])
    inv3 = bot3.invoices[0] if bot3.invoices else {}
    check("sub_intl_plan:3m → 175 Stars XTR invoice",
          len(bot3.invoices) == 1 and inv3.get("prices")
          and inv3["prices"][0].amount == 175 and inv3.get("currency") == "XTR",
          inv3)
    check("sub_intl_plan ekranida Uzcard/Humo yo'q",
          all("Uzcard" not in t and "Humo" not in t for t in texts3), texts3)

    # 3.4 Stars invoice payload'i validator + servis kontraktidan o'tadi.
    from services.payment_service import PaymentService
    import handlers.subscription as sub
    plan, err = PaymentService.validate_payload("sub_stars_3m_555001", 555001, 175, "XTR")
    check("validate_payload: intl invoice payload qabul qilindi",
          plan is not None and err is None, err)
    vp, verr = sub._validate_stars_payload("sub_stars_3m_555001", 555001, 175, "XTR", "uz")
    check("_validate_stars_payload: handler validatori ham qabul qiladi",
          vp is not None and verr is None, verr)

    # 3.5 Yaroqsiz mintaqa tokeni → menyu qaytadi, rekvizit/invoice chiqmaydi.
    bot4, _, texts4, markups4, _ = _run_region_flow("uz", ["sub_region:paypal:1m"])
    joined4 = "\n".join(texts4)
    check("Noma'lum mintaqa → menyuni qayta ko'rsatish (xavfsiz fallback)",
          not bot4.invoices and "pay_region" not in (texts4[0][:30] or "")
          and "8600" not in joined4, joined4[:120])

    # 3.6 Obuna kartasidagi Stars tugmasi ENDI rekvizit emas, mintaqa menyusini
    # ochadi (to'lov rekvizitlari to'g'ridan-to'g'ri chiqmasligi sharti).
    bot5, q5, texts5, markups5, _ = _run_region_flow("en", ["sub_pay:stars_1m"])
    screen5 = texts5[0] + "\n" + (_kb_texts_kb(markups5[0]) if markups5 else "")
    check("Stars tarif tugmasi bosilganda invoice yo'q — avval mintaqa so'raladi",
          not bot5.invoices and len(q5.edits) == 1
          and "Select your payment region" in screen5
          and "Uzbekistan (Uzcard / Humo)" in screen5
          and "International (Stars / Crypto / Card)" in screen5,
          screen5[:160])


# ============================================================
# 4) Ledger / servis: payment_method + valyuta ajratilgan
# ============================================================

class _FakeCur:
    """payment_service.transaction() ichidagi minimal psycopg2 cursor."""

    def __init__(self, fetch_rows=None, rowcount=1):
        self._rows = list(fetch_rows or [])
        self.rowcount = rowcount
        self.queries = []
        self.params = []

    def execute(self, query, params=None):
        self.queries.append(" ".join(str(query).split()))
        self.params.append(params)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


def _tx_with(cur):
    @contextmanager
    def _tx(commit=True):
        yield cur
    return _tx


def test_ledger_method_currency_split():
    print("== 4. Ledger: 'uzcard_humo' (UZS) vs 'international_stars' (XTR) ==")
    from services import payment_service as ps

    check("Konstantalar", ps.PAYMENT_METHOD_UZCARD_HUMO == "uzcard_humo"
          and ps.PAYMENT_METHOD_INTERNATIONAL_STARS == "international_stars")
    check("normalize_payment_method: case/bo'shliq bardoshli",
          ps.normalize_payment_method(" UZCARD_Humo ") == "uzcard_humo")
    check("normalize_payment_method: noma'lum → international_stars",
          ps.normalize_payment_method("paypal") == "international_stars"
          and ps.normalize_payment_method(None) == "international_stars")
    check("currency_for_method: uzcard_humo → UZS, stars → XTR",
          ps.currency_for_method("uzcard_humo") == "UZS"
          and ps.currency_for_method("international_stars") == "XTR")

    # 4.1 Stars to'lovi → ledger: XTR + international_stars (default).
    cur1 = _FakeCur(fetch_rows=[(1,), (4242,)])
    with patch.object(ps, "transaction", _tx_with(cur1)), \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        res1 = ps.PaymentService.process_stars_payment(
            777001, "ch_intl_1", 550, "sub_stars_1y_777001", "pro", 365)
    check("Stars ledger yozuvi: XTR + international_stars parametrlari",
          res1.get("ok") is True and res1.get("payment_method") == "international_stars"
          and res1.get("currency") == "XTR"
          and any("INSERT INTO payments" in q for q in cur1.queries)
          and cur1.params[-2] == (777001, 550, "XTR", "sub_stars_1y_777001",
                                  "ch_intl_1", "succeeded", "international_stars"),
          f"{res1} {cur1.params}")
    check("Stars to'lovi ham davomida GREATEST/COALESCE bilan uzaytiradi (regression)",
          any("GREATEST" in q and "COALESCE" in q for q in cur1.queries))

    # 4.2 Xato payment_method → normalizatsiya (audit tozaligi).
    cur2 = _FakeCur(fetch_rows=[(1,), (4243,)])
    with patch.object(ps, "transaction", _tx_with(cur2)), \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        ps.PaymentService.process_stars_payment(
            777002, "ch_norm_1", 75, "sub_stars_1m_777002", "pro", 30,
            payment_method="BIT_NOTUSUV_USUL")
    check("Noma'lum usul ledger'da international_stars bo'lib qoladi",
          cur2.params[-2][-1] == "international_stars", cur2.params)

    # 4.3 Mahalliy usul bilan chaqirilsa — valyuta UZS bo'ladi.
    cur3 = _FakeCur(fetch_rows=[(1,), (4244,)])
    with patch.object(ps, "transaction", _tx_with(cur3)), \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        res3 = ps.PaymentService.process_stars_payment(
            777003, "ch_uz_1", 19000, "receipt:88", "pro", 30,
            payment_method="uzcard_humo")
    check("uzcard_humo → UZS ledger yozuvi",
          res3.get("payment_method") == "uzcard_humo" and res3.get("currency") == "UZS"
          and cur3.params[-2] == (777003, 19000, "UZS", "receipt:88",
                                  "ch_uz_1", "succeeded", "uzcard_humo"),
          cur3.params)

    # 4.4 Idempotency: takroriy charge → duplicate (PRO ikki marta bermaydi).
    cur4 = _FakeCur(fetch_rows=[(1,), None])
    with patch.object(ps, "transaction", _tx_with(cur4)), \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        res4 = ps.PaymentService.process_stars_payment(
            777001, "ch_intl_1", 550, "sub_stars_1y_777001", "pro", 365)
    check("Takroriy Stars to'lovi: duplicate=True, days=0",
          res4.get("ok") is True and res4.get("duplicate") is True
          and res4.get("days") == 0, res4)

    # 4.5 record_card_payment — alohida ledger yozuvi (idempotent, receipt:<id>).
    cur5 = _FakeCur(fetch_rows=[], rowcount=1)
    with patch.object(ps, "transaction", _tx_with(cur5)):
        res5 = ps.PaymentService.record_card_payment(777004, 55, 45000)
    check("record_card_payment: UZS + uzcard_humo + receipt:55 charge kaliti",
          res5.get("ok") is True and res5.get("duplicate") is False
          and cur5.params[0] == (777004, 45000, "UZS", "receipt:55", "receipt:55",
                                 "succeeded", "uzcard_humo"), f"{res5} {cur5.params}")
    cur6 = _FakeCur(fetch_rows=[], rowcount=0)  # ON CONFLICT → rowcount 0
    with patch.object(ps, "transaction", _tx_with(cur6)):
        res6 = ps.PaymentService.record_card_payment(777004, 55, 45000)
    check("record_card_payment: takroriy yozuv duplicate (yangi qator YO'Q)",
          res6.get("ok") is True and res6.get("duplicate") is True, res6)
    check("record_card_payment: yaroqsiz receipt_id rad etiladi",
          ps.PaymentService.record_card_payment(1, 0)["ok"] is False
          and ps.PaymentService.record_card_payment(1, "abc")["ok"] is False)

    # 4.6 Chekni tasdiqlash — PRO grant + audit + ledger BIR tranzaksiyada.
    cur7 = _FakeCur(fetch_rows=[("pending", 777005, 90, 45000), ("ru",)])
    with patch.object(ps, "transaction", _tx_with(cur7)), \
         patch.object(ps.AuditService, "log_receipt_decision") as mock_audit, \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        res7 = ps.PaymentService.process_receipt(55, 999, True)
    ledger_params = [p for q, p in zip(cur7.queries, cur7.params)
                     if "INSERT INTO payments" in q]
    check("Approve: ok + user til qaytadi (regression)",
          res7.get("ok") is True and res7.get("user_id") == 777005
          and res7.get("days") == 90, res7)
    check("Approve: UZS/45000 + uzcard_humo ledger yozuvi shu tranzaksiyada",
          ledger_params and ledger_params[0] == (777005, 45000, "UZS", "receipt:55",
                                                 "receipt:55", "succeeded", "uzcard_humo"),
          cur7.params)
    check("Approve: audit yozuvi chaqirildi (6-bosqich kontrakti)", mock_audit.called)
    check("Approve: payment_receipts UPDATE 'approved' + FOR UPDATE qulfi",
          any("UPDATE payment_receipts SET status = 'approved'" in q for q in cur7.queries)
          and any("FOR UPDATE" in q for q in cur7.queries))
    # Eski 3 ustunli satr (migratsiyagacha) ham qulatmaydi — backward compat.
    cur8 = _FakeCur(fetch_rows=[("pending", 777006, 30), ("uz",)])
    with patch.object(ps, "transaction", _tx_with(cur8)), \
         patch.object(ps.AuditService, "log_receipt_decision"), \
         patch.object(ps, "_invalidate_user"), patch.object(ps, "_cache_clear"):
        res8 = ps.PaymentService.process_receipt(56, 999, True)
    ledger8 = [p for q, p in zip(cur8.queries, cur8.params) if "INSERT INTO payments" in q]
    check("Approve (eski chek, amount_uzs yo'q): crash yo'q, ledger amount=0",
          res8.get("ok") is True and ledger8 and ledger8[0][1] == 0
          and ledger8[0][2] == "UZS" and ledger8[0][-1] == "uzcard_humo",
          f"{res8} {ledger8}")


# ============================================================
# 5) DB/sxema statik kontraktlari (additive migratsiyalar)
# ============================================================

def test_schema_and_database_additive():
    print("== 5. Schema/database: payment_method va amount_uzs (additive) ==")
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    import database as db_mod
    import inspect

    check("schema.sql: payments.payment_method (DEFAULT international_stars)",
          "payment_method VARCHAR(32) NOT NULL DEFAULT 'international_stars'" in schema)
    check("schema.sql: payments ALTER idempotent",
          "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_method" in schema)
    check("schema.sql: payment_receipts.amount_uzs",
          "amount_uzs INT DEFAULT 0" in schema
          and "ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS amount_uzs" in schema)
    check("schema.sql: indekslar soni o'zgarmadi (18 — schema_test paralleligi)",
          schema.count("CREATE INDEX IF NOT EXISTS") == 18,
          schema.count("CREATE INDEX IF NOT EXISTS"))
    check("database.py: ichki fallback DDL ham payment_method'ni oladi",
          "payment_method VARCHAR(32) NOT NULL DEFAULT 'international_stars'"
          in (ROOT / "database.py").read_text(encoding="utf-8"))

    check("database.PAYMENT_METHODS konstantalari",
          db_mod.PAYMENT_METHODS == ("uzcard_humo", "international_stars"))
    check("database._normalize_payment_method",
          db_mod._normalize_payment_method("UzCard_Humo") == "uzcard_humo"
          and db_mod._normalize_payment_method("crypto") == "international_stars")

    sig = inspect.signature(db_mod.save_payment_receipt)
    check("save_payment_receipt: amount_uzs qo'shimcha parametri bor",
          "amount_uzs" in sig.parameters
          and sig.parameters["amount_uzs"].default == 0)
    log_sig = inspect.signature(db_mod.log_stars_payment)
    check("log_stars_payment: payment_method parametri bor (default None → infer)",
          "payment_method" in log_sig.parameters)
    # log_stars_payment UZS valyutaga ko'ra avtomatik uzcard_humo deb oladi.
    calls = []

    class _CapCur:
        def __init__(self):
            self.rowcount = 1

        def execute(self, q, params=None):
            calls.append((" ".join(str(q).split()), params))

    from contextlib import contextmanager as _cm

    @_cm
    def _fake_dc(commit=False):
        yield _CapCur()

    with patch.object(db_mod, "db_cursor", _fake_dc), \
         patch.object(db_mod, "_cache_clear"):
        db_mod.log_stars_payment(1, 19000, "UZS", "receipt:9", "receipt:9")
        db_mod.log_stars_payment(1, 75, "XTR", "sub_stars_1m_1", "ch_x")
    check("log_stars_payment: UZS → uzcard_humo, XTR → international_stars",
          len(calls) == 2 and calls[0][1][-1] == "uzcard_humo"
          and calls[1][1][-1] == "international_stars", calls)

    # database.process_stars_payment wrapper servisga delegat (API saqlangan).
    src = (ROOT / "database.py").read_text(encoding="utf-8")
    check("database.process_stars_payment → PaymentService delegati saqlangan",
          "PaymentService.process_stars_payment" in src)
    # Handler routing: yangi callback'lar ^sub_ patterni ostida.
    init_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("sub_region/sub_intl_plan 'sub_' pattern routing ostida",
          'CallbackQueryHandler(subscription_callback, pattern=r"^sub_")' in init_src
          and 'sub_region'.startswith("sub_"))
    sub_src = (ROOT / "handlers" / "subscription.py").read_text(encoding="utf-8")
    check("subscription.py: mintaqa menyusigacha invoice YO'Q (gate mavjud)",
          "get_payment_region_keyboard" in sub_src
          and "_show_intl_payment" in sub_src
          and "payment_region_from_callback" in sub_src)


def main():
    test_region_buttons_all_languages()
    test_ru_user_local_flow()
    test_international_flow_hides_local_cards()
    test_ledger_method_currency_split()
    test_schema_and_database_additive()

    print()
    print("=" * 60)
    total = passed + failures
    print(f"payment_region_selection: o'tdi={passed}, xato={failures} (jami {total})")
    if failures:
        print("FAIL — to'lov mintaqasi testlari yashil EMAS ✘")
        sys.exit(1)
    print("Barcha to'lov mintaqasi testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
