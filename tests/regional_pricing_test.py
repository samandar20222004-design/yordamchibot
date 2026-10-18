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

print("\n== 2. Mintaqani aniqlash: TILGA BOG'LIQ EMAS ==")
store = {"region": "intl", "eligible": False}
calls = []
verify_calls = []


async def fake_run_db(fn, *a, **k):
    name = getattr(fn, "__name__", "")
    if name == "get_pay_region":
        return store["region"]
    if name == "is_uz_eligible":
        return store["eligible"]
    if name == "set_pay_region":
        calls.append(a)
        if a[1] == "uz" and not store["eligible"]:
            return False
        store["region"] = a[1]
        return True
    if name == "verify_uz_phone":
        verify_calls.append(a)
        return store["eligible"] or (a[2] == a[0] and "".join(c for c in str(a[1]) if c.isdigit()).startswith("998"))
    raise AssertionError(f"kutilmagan DB chaqiruvi: {name}")


sub.db.run_db = fake_run_db
run = asyncio.run
store["region"] = "intl"
check("tasdiqlanmagan: o'zbek tilida ham dollar (til mintaqani belgilamaydi)",
      all(run(sub._user_region(1, lang)) == INTL for lang in ("uz", "ru", "en")))
store["region"] = "uz"
check("tasdiqlangan (+998): hamma tilda so'm", all(run(sub._user_region(1, lang)) == UZ for lang in ("uz", "ru", "en")))
store["region"] = "intl"

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

print("\n== 4. Mintaqa almashtirish va +998 tasdiqlash (handler) ==")


class Q:
    def __init__(self, data, uid=42):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.edits = []
        self.replies = []

        async def reply_text(text, **kw):
            self.replies.append((text, kw.get("reply_markup")))

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


store.update(region="intl", eligible=False)
calls.clear()
q, ctx, _ = press("sub_setreg:uz:pro")
markup = q.replies[0][1] if q.replies else None
btn = markup.keyboard[0][0] if markup else None
check("tasdiqlanmagan «So'mda to'lash»: so'm kartasi YO'Q, +998 tasdiqlash so'raladi (kontakt ulashish tugmasi)",
      not q.edits and q.replies and "+998" in q.replies[0][0] and btn is not None and btn.request_contact is True
      and ctx.user_data.get("uz_verify", {}).get("tier") == "pro", str((q.replies, q.edits)))
check("... va mintaqa 'uz' ga O'ZGARTIRILMADI", store["region"] == "intl")
q, ctx, _ = press("sub_setreg:intl:pro")
check("dollarga o'tish har doim mumkin", calls[-1] == (42, "intl") and "$3.90" in q.edits[0][0])
store.update(region="intl", eligible=True)
q, ctx, _ = press("sub_setreg:uz:ultra")
check("tasdiqlangan foydalanuvchi so'mga qayta o'ta oladi (qayta tasdiqlash so'ralmaydi)",
      store["region"] == "uz" and "69 000" in q.edits[0][0] and not q.replies, str((q.edits, q.replies)))
calls.clear()
for bad in ("sub_setreg:mars:pro", "sub_setreg:uz:enterprise", "sub_setreg:uz", "sub_setreg::"):
    q, _, _ = press(bad)
    check(f"yaroqsiz '{bad}' rad etiladi (saqlanmaydi)", calls == [] and not q.edits)
store.update(region="intl", eligible=False)
q, _, _ = press("sub_tier:pro")
check("sub_tier: tasdiqlanmagan -> dollar (o'zbek tilida ham)", "$3.90" in q.edits[0][0] and "29 000" not in q.edits[0][0])
store.update(region="uz", eligible=True)
q, _, _ = press("sub_tier:pro")
check("sub_tier: tasdiqlangan -> so'm", "29 000" in q.edits[0][0] and "$" not in q.edits[0][0])

print("\n== 4b. Kontakt (+998) qabul qilish ==")
import time  # noqa: E402


stopped = [False]


def send_contact(phone, contact_uid, uid=42, pending=True, age=0):
    replies = []

    async def reply_text(text, **kw):
        replies.append(text)

    msg = SimpleNamespace(contact=SimpleNamespace(phone_number=phone, user_id=contact_uid), reply_text=reply_text)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid))
    ud = {"lang": "uz"}
    if pending:
        ud["uz_verify"] = {"tier": "pro", "ts": time.time() - age}
    ctx = SimpleNamespace(user_data=ud, bot=SimpleNamespace())
    from telegram.ext import ApplicationHandlerStop

    try:
        run(sub.uz_contact_callback(upd, ctx))
        stopped[0] = False
    except ApplicationHandlerStop:
        stopped[0] = True
    return replies, ctx


store.update(region="intl", eligible=False)
verify_calls.clear()
r, ctx = send_contact("+998 90 123 45 67", 42)
check("o'z +998 kontakti: tasdiqlandi, so'm kartasi yuborildi, kutish belgisi o'chdi",
      len(r) == 2 and "tasdiqlandi" in r[0] and "29 000" in r[1] and "uz_verify" not in ctx.user_data, str(r))
verify_calls.clear()
r, _ = send_contact("+998901234567", 99)
check("BOSHQA odamning kontakti rad etiladi (va «noma'lum xabar» javobi chiqmaydi)", stopped[0] is True and len(r) == 1 and "Tasdiqlanmadi" in r[0] and verify_calls[0][2] == 99, str(r))
store["eligible"] = False
r, _ = send_contact("+79001234567", 42)
check("chet el raqami (+7) rad etiladi", len(r) == 1 and "Tasdiqlanmadi" in r[0], str(r))
verify_calls.clear()
r, _ = send_contact("+998901234567", 42, pending=False)
check("«So'mda to'lash» bosilmagan bo'lsa kontakt e'tiborsiz (DB'ga tegilmaydi, boshqa handlerlar to'smaydi)",
      r == [] and verify_calls == [] and stopped[0] is False)
r, _ = send_contact("+998901234567", 42, age=sub.UZ_VERIFY_TTL_SECONDS + 5)
check("10 daqiqadan eski so'rov e'tiborsiz", r == [] and verify_calls == [])

print("\n== 5. To'lovga o'tish: til emas, tasdiqlash hal qiladi ==")
shown = []


async def fake_intl(query, context, uid, lang, plan_key):
    shown.append(("intl", plan_key))


async def fake_local(query, context, uid, lang, plan_key):
    shown.append(("uz", plan_key))


sub._show_intl_payment, sub._show_local_card_payment = fake_intl, fake_local
for region, eligible, expect in (("uz", True, [("uz", "1y")]), ("intl", False, [("intl", "1y")]), ("intl", True, [("intl", "1y")])):
    store.update(region=region, eligible=eligible)
    shown.clear()
    q, _, _ = press("sub_pay:stars_1y")
    check(f"mintaqa '{region}' (tasdiqlangan={eligible}): menyu YO'Q, to'g'ridan-to'g'ri {expect[0][0]} to'lovi", shown == expect and not q.edits, str((shown, q.edits)))
store.update(region="intl", eligible=False)
q, _, _ = press("sub_region:uz:1m")
check("menyudan 'uz' tanlovi tasdiqlanmagan foydalanuvchiga so'm to'lovini OCHMAYDI", shown == [("intl", "1y")] and not q.edits
      and q.replies and "+998" in q.replies[0][0], str((shown, q.replies)))
shown.clear()
calls.clear()
q, _, _ = press("sub_region:intl:1y")
check("menyudan 'intl' tanlovi saqlanadi va dollar to'lovi ochiladi", calls == [(42, "intl")] and shown == [("intl", "1y")], str((calls, shown)))

print("\n== 6. Mini App ==")
from miniapp_api.service import pay_region, tier_catalog  # noqa: E402

check("Mini App mintaqa (til hisobga olinmaydi): tasdiqlangan -> uz; tasdiqlanmagan/til qanday bo'lmasin -> intl",
      pay_region({"uz_eligible": True}) == "uz" and pay_region({"uz_eligible": True, "pay_region": "intl"}) == "intl"
      and pay_region({"language_code": "uz"}) == "intl" and pay_region({"language_code": "uz", "pay_region": "uz"}) == "intl"
      and pay_region({}) == "intl")
tc = tier_catalog()
check("Mini App /me tiers: usd va Stars katalogdan (PRO 3.9/195, ULTRA 83.6/4180)",
      tc["pro"]["periods"][0]["usd"] == 3.9 and tc["pro"]["periods"][0]["stars"] == 195
      and tc["ultra"]["periods"][3]["usd"] == 83.6 and tc["ultra"]["periods"][3]["stars"] == 4180
      and tc["pro"]["periods"][0]["uzs"] == 29000, str(tc["pro"]["periods"][0]))
check("get_text kalitlari uch tilda mavjud", all(get_text(k, lang) != k for lang in ("uz", "ru", "en") for k in
      ("tier_prices_head_uz", "tier_prices_head_usd", "tier_price_line_uz", "tier_price_line_usd", "tier_region_note_uz",
       "tier_region_note_usd", "tariff_btn_usd_tpl", "price_uzs_tpl", "btn_region_usd", "btn_region_uzs", "btn_share_phone",
       "uz_verify_prompt", "uz_verify_ok", "uz_verify_fail")))

print(f"\nNATIJA: [OK]={passed} [XATO]={failed}")
sys.exit(1 if failed else 0)
