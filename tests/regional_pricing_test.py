#!/usr/bin/env python3
"""Mintaqaga qarab narx: O'zbekiston — so'm (karta/Payme), chet el — dollar (Telegram Stars), O'zbekiston narxidan 1,7 baravar qimmat.

DB talab qilinmaydi (handler fake'lar bilan). Tekshiradi: narx matematikasi, tarif kartasi/tugmalar uz/ru/en,
mintaqa almashtirish va saqlash, saqlangan mintaqada menyu so'ralmasligi, Mini App mintaqasi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ADMIN_ID", "111")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import config  # noqa: E402
from handlers import subscription as sub  # noqa: E402
from locales.translations import get_text  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


UZ, INTL = "uz", "intl"
cat = config.TARIFF_CATALOG

print("== 1. Narx matematikasi ==")
BASE = {"1m": 115, "3m": 300, "6m": 535, "1y": 970, "u1m": 275, "u3m": 695, "u6m": 1330, "u1y": 2460}
UZS = {"1m": 29000, "3m": 75000, "6m": 135000, "1y": 245000, "u1m": 69000, "u3m": 175000, "u6m": 335000, "u1y": 620000}
check("ko'paytirgich 1,7", abs(config.INTL_PRICE_MULTIPLIER - 1.7) < 1e-9)
for key, info in cat.items():
    ratio = info["stars"] / BASE[key]
    check(f"{key}: xalqaro {info['stars']}★ = ${info['usd']} (O'zbekiston ekvivalentidan {ratio:.2f}x), so'm {info['uzs']} O'ZGARMAGAN",
          1.68 <= ratio <= 1.72 and info["stars"] % 5 == 0 and abs(float(info["usd"]) - info["stars"] * 0.02) < 0.005
          and info["uzs"] == UZS[key])
check("STARS_PLANS (precheckout) katalogdagi xalqaro summa bilan bir xil",
      all(config.STARS_PLANS[i["stars_key"]]["stars"] == i["stars"] for i in cat.values()))

print("\n== 2. Mintaqani aniqlash ==")
check("o'zbek tili -> uz; ru/en -> intl", sub._derive_region("uz") == UZ and sub._derive_region("ru") == INTL and sub._derive_region("en") == INTL)

store = {"region": ""}
calls = []


async def fake_run_db(fn, *a, **k):
    name = getattr(fn, "__name__", "")
    if name == "get_pay_region":
        return store["region"]
    if name == "set_pay_region":
        calls.append(a)
        store["region"] = a[1]
        return True
    raise AssertionError(f"kutilmagan DB chaqiruvi: {name}")


sub.db.run_db = fake_run_db
run = asyncio.run
check("saqlanmagan: tildan (uz -> uz, ru -> intl)", run(sub._user_region(1, "uz")) == UZ and run(sub._user_region(1, "ru")) == INTL)
store["region"] = "uz"
check("saqlangan tanlov tildan USTUN (ru + uz)", run(sub._user_region(1, "ru")) == UZ)
store["region"] = "intl"
check("saqlangan tanlov tildan USTUN (uz + intl)", run(sub._user_region(1, "uz")) == INTL)
store["region"] = ""

print("\n== 3. Tarif kartasi va tugmalar (uz/ru/en) ==")
for lang in ("uz", "ru", "en"):
    for tier in ("pro", "ultra"):
        keys = config.tariff_keys_for(tier)
        card_uz = sub._build_tier_card(tier, lang, UZ)
        card_in = sub._build_tier_card(tier, lang, INTL)
        check(f"[{lang}/{tier}] so'm kartasi: so'm narxlari bor, dollar/Stars YO'Q",
              all(sub._fmt_uzs(cat[k]["uzs"]) in card_uz for k in keys) and "$" not in card_uz)
        check(f"[{lang}/{tier}] xalqaro karta: dollar va Stars bor, so'm narxi YO'Q",
              all(f"${cat[k]['usd']}" in card_in and f"⭐️ {cat[k]['stars']}" in card_in for k in keys)
              and not any(sub._fmt_uzs(cat[k]["uzs"]) in card_in for k in keys))
        kb_uz = sub._get_tier_keyboard(tier, lang, UZ)
        kb_in = sub._get_tier_keyboard(tier, lang, INTL)
        labels_uz = [b.text for r in kb_uz.inline_keyboard for b in r]
        labels_in = [b.text for r in kb_in.inline_keyboard for b in r]
        check(f"[{lang}/{tier}] tugmalar: UZda so'm, xalqaroda $", all("$" not in t for t in labels_uz[:4]) and all("$" in t for t in labels_in[:4]),
              str((labels_uz, labels_in)))
        toggles = [(kb_uz.inline_keyboard[-2][0], INTL), (kb_in.inline_keyboard[-2][0], UZ)]
        check(f"[{lang}/{tier}] almashtirish tugmasi: callback sub_setreg:<mintaqa>:{tier}, yorliq <= 18 belgi",
              all(b.callback_data == f"sub_setreg:{r}:{tier}" and len(b.text) <= 18 for b, r in toggles), str([(b.text, b.callback_data) for b, _ in toggles]))
        check(f"[{lang}/{tier}] callback_data 64 baytdan oshmaydi", all(len(b.callback_data.encode()) <= 64 for r in kb_in.inline_keyboard for b in r))
    plan_info = {"plan_type": "free", "expires_at": None, "ai_used": 0}
    check(f"[{lang}] obuna kartasi: UZda so'm, xalqaroda $", "$" not in sub._build_subscription_card(plan_info, lang, UZ)
          and "$3.90" in sub._build_subscription_card(plan_info, lang, INTL) and "$9.40" in sub._build_subscription_card(plan_info, lang, INTL))
    intl_kb = sub.get_intl_tariffs_keyboard(lang)
    check(f"[{lang}] xalqaro paketlar tugmasi: dollar + Stars", "$3.90" in intl_kb.inline_keyboard[0][0].text and "195★" in intl_kb.inline_keyboard[0][0].text,
          intl_kb.inline_keyboard[0][0].text)

print("\n== 4. Mintaqa almashtirish va saqlash (handler) ==")


class Q:
    def __init__(self, data, uid=42):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.edits = []
        self.replies = []

        async def reply_text(text, **kw):
            self.replies.append(text)

        async def edit_message_text(text, **kw):
            self.edits.append((text, kw.get("reply_markup")))

        self.message = SimpleNamespace(chat_id=uid, reply_text=reply_text, delete=lambda: None)
        self.edit_message_text = edit_message_text

    async def answer(self, *a, **k):
        return None


async def fake_lang(context, uid):
    return "uz"


sub.ensure_user_lang = fake_lang


def press(data, ud=None):
    q = Q(data)
    ctx = SimpleNamespace(user_data=ud if ud is not None else {"lang": "uz"}, bot=SimpleNamespace())
    res = run(sub.subscription_callback(SimpleNamespace(callback_query=q, effective_user=q.from_user), ctx))
    return q, ctx, res


store["region"] = ""
calls.clear()
q, ctx, _ = press("sub_setreg:intl:pro")
check("sub_setreg:intl:pro -> mintaqa SAQLANDI va dollar kartasi chizildi",
      calls == [(42, "intl")] and q.edits and "$3.90" in q.edits[0][0], str((calls, q.edits[:1])))
q, ctx, _ = press("sub_setreg:uz:ultra")
check("sub_setreg:uz:ultra -> so'm kartasi", calls[-1] == (42, "uz") and "69 000" in q.edits[0][0] and "$" not in q.edits[0][0])
calls.clear()
for bad in ("sub_setreg:mars:pro", "sub_setreg:uz:enterprise", "sub_setreg:uz", "sub_setreg::"):
    q, _, _ = press(bad)
    check(f"yaroqsiz '{bad}' rad etiladi (saqlanmaydi)", calls == [] and not q.edits)
store["region"] = "intl"
q, _, _ = press("sub_tier:pro")
check("sub_tier: saqlangan 'intl' bo'yicha dollar narxi", "$3.90" in q.edits[0][0])
store["region"] = ""
q, _, _ = press("sub_tier:pro")
check("sub_tier: saqlanmagan, til 'uz' -> so'm", "29 000" in q.edits[0][0] and "$" not in q.edits[0][0])

print("\n== 5. To'lovga o'tish: saqlangan mintaqada menyu so'ralmaydi ==")
shown = []


async def fake_intl(query, context, uid, lang, plan_key):
    shown.append(("intl", plan_key))


async def fake_local(query, context, uid, lang, plan_key):
    shown.append(("uz", plan_key))


sub._show_intl_payment, sub._show_local_card_payment = fake_intl, fake_local
for saved, expect in (("intl", [("intl", "1y")]), ("uz", [("uz", "1y")])):
    store["region"] = saved
    shown.clear()
    q, _, _ = press("sub_pay:stars_1y")
    check(f"saqlangan '{saved}': menyu YO'Q, to'g'ridan-to'g'ri {saved} to'lovi", shown == expect and not q.edits, str((shown, q.edits)))
store["region"] = ""
shown.clear()
q, ctx, _ = press("sub_pay:stars_1y")
check("saqlanmagan: mintaqa menyusi so'raladi (eski xulq)", shown == [] and q.edits and "Uzcard" in q.edits[0][0], str(q.edits[:1]))
calls.clear()
q, _, _ = press("sub_region:intl:1y")
check("menyudan tanlangan mintaqa ham saqlanadi", calls == [(42, "intl")] and shown == [("intl", "1y")], str((calls, shown)))

print("\n== 6. Mini App ==")
from miniapp_api.service import pay_region, tier_catalog  # noqa: E402

check("Mini App mintaqa: saqlangan > til", pay_region({"pay_region": "intl", "language_code": "uz"}) == "intl"
      and pay_region({"pay_region": "uz", "language_code": "en"}) == "uz")
check("Mini App mintaqa: til (uz -> uz, ru/en -> intl, noma'lum -> uz)", pay_region({"language_code": "uz"}) == "uz"
      and pay_region({"language_code": "ru"}) == "intl" and pay_region({"language_code": "en"}) == "intl" and pay_region({}) == "uz")
tc = tier_catalog()
check("Mini App /me tiers: usd va Stars katalogdan (PRO 3.9/195, ULTRA 83.6/4180)",
      tc["pro"]["periods"][0]["usd"] == 3.9 and tc["pro"]["periods"][0]["stars"] == 195
      and tc["ultra"]["periods"][3]["usd"] == 83.6 and tc["ultra"]["periods"][3]["stars"] == 4180
      and tc["pro"]["periods"][0]["uzs"] == 29000, str(tc["pro"]["periods"][0]))
check("get_text kalitlari uch tilda mavjud", all(get_text(k, lang) != k for lang in ("uz", "ru", "en") for k in
      ("tier_prices_head_uz", "tier_prices_head_usd", "tier_price_line_uz", "tier_price_line_usd", "tier_region_note_uz",
       "tier_region_note_usd", "tariff_btn_usd_tpl", "price_uzs_tpl", "btn_region_usd", "btn_region_uzs")))

print(f"\nNATIJA: [OK]={passed} [XATO]={failed}")
sys.exit(1 if failed else 0)
