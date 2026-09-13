#!/usr/bin/env python3
"""✨ PRO 2-BOSQICHLI AUDIT OQIMI + FREE PROMPT STRUKTURASI testi.

Tekshiriladigan kontraktlar:

  A) PRO (``is_pro=True``) — 2 bosqichli AVTOMATIK audit:
     • 1-bosqich: post AIDA/PAS (PRO prompti) asosida generatsiya qilinadi;
     • 2-bosqich: olingan matn ``utils.ai_agent._AUDIT_PRO_SYSTEM`` tizim
       prompti bilan IKKINCHI AI so'roviga yuboriladi;
     • natija: foydalanuvchiga FAQAT 2-bosqichning yaxshilangan varianti
       ko'rsatiladi (``post_text`` == audited), 1-bosqich matni esa
       ``post_text_stage1`` da saqlanib qoladi.

  B) FREE (``is_pro=False``): 2-bosqich UMUMAN chaqirilmaydi — bitta AI
     so'rovi (tezlik va hisoblash resurslari tejaladi).

  C) 2-bosqich XATOSI (timeout, tarmoq uzilishi, ``{"error": ...}``,
     tahlil-matni yoki bo'sh javob) → 1-bosqich posti XAVFSIZ qaytadi,
     oqim to'xtab qolmaydi (``error`` kaliti paydo bo'lmaydi).

  D) FREE tarif prompti minimal strukturani TALAB qiladi:
     Hook → Value (1 ta aniq fikr) → Call to Action → 3-5 tematik hashtag
     (uz / ru / en — har bir tilda o'z tilida, aralashuvsiz).

  E) ``handlers/post_enhancer.py`` integratsiyasi: "✨ AI audit (PRO)"
     tugmasi faqat PRO + matnli postda ko'rinadi; bosilganda post matni
     auditor varianti bilan almashtiriladi; auditor javob bermasa ASL matn
     saqlanadi; FREE foydalanuvchida auditor chaqirilmaydi.

Mock bilan ishlaydi — real AI API, PostgreSQL yoki Telegram chaqirilmaydi.

Ishga tushirish:
    cd telegram_bot && python tests/post_enhancer_audit_test.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# MUHIM: import qilishdan OLDIN env sozlash (config shularni talab qiladi).
os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("ADMIN_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")

passed = 0
failures = 0

CYRILLIC = re.compile(r"[\u0400-\u04FF]")


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def section(title):
    print(f"\n== {title} ==")


import database as db
import handlers.post_enhancer as pe
from utils import ai_agent

# ------------------------------------------------------------
# Test Fixture'lari
# ------------------------------------------------------------

STAGE1_POST = (
    "<b>Kofe</b>\n\nYangi kofe yetib keldi. Sifatli va arzon.\n"
    "CTA: xarid qiling.\n\n#kofe #yangi #uzum"
)
AUDITED_POST = (
    "<b>☕ Ertalabki energiya — bir finjonda</b>\n\n"
    "Yangi qovurilgan kofe kunni butunlay o'zgartiradi: birinchi xushbo'y "
    "hiddayoq kayfiyat ko'tariladi.\n\n"
    "👉 Hoziroq buyurtma bering — birinchi 50 ta qadoq 20% chegirma bilan.\n\n"
    "#kofe #yangiqovurilgan #energiya #toshkent #uzum"
)
#: Auditor tahlili (post EMAS) — bunday javob rad etilishi kerak.
ANALYSIS_ONLY = (
    "Reyting: 7/10. Kuchli tomonlari: aniq hook. Yaxshilash bo'yicha "
    "punktlar: CTA kuchsiz, hashtaglar kam. Tahlil tugadi."
)


class FakeChain:
    """``ai_agent._run_ai_chain`` o'rnini bosuvchi mock.

    ``stage2_mode``: "ok" | "raise" | "error" | "timeout" | "analysis" |
    "empty" | "short" — 2-bosqich (auditor) javobini boshqaradi.
    """

    def __init__(self, stage2_mode="ok"):
        self.mode = stage2_mode
        self.calls = []          # [{"prompt":..., "sys":..., "stage":1|2}]
        self.audit_systems = []  # 2-bosqichda ishlatilgan tizim promptlari

    async def __call__(self, prompt, system_instruction, lang=None):
        is_audit = ai_agent._AUDIT_PRO_SYSTEM.strip()[:40] in (system_instruction or "")
        self.calls.append({
            "prompt": prompt,
            "sys": system_instruction or "",
            "stage": 2 if is_audit else 1,
            "lang": lang,
        })
        if is_audit:
            self.audit_systems.append(system_instruction or "")
            if self.mode == "raise":
                raise RuntimeError("tarmoq uzildi (mock)")
            if self.mode == "timeout":
                await asyncio.sleep(5)
            if self.mode == "error":
                return {"error": "AI xizmatida xatolik", "timeout": True}
            if self.mode == "analysis":
                return {"audit": ANALYSIS_ONLY}
            if self.mode == "empty":
                return {"rating": 5, "improved_post": "   "}
            if self.mode == "short":
                return {"rating": 8, "improved_post": "Qisqa xulosa."}
            return {"rating": 9, "improved_post": AUDITED_POST}
        # 1-bosqich: intent-router javobi (post).
        return {
            "intent": "post",
            "reply": "",
            "post_text": STAGE1_POST,
            "scheduled_time": None,
            "has_explicit_time": False,
            "target_all": False,
        }

    @property
    def stage1_calls(self):
        return [c for c in self.calls if c["stage"] == 1]

    @property
    def stage2_calls(self):
        return [c for c in self.calls if c["stage"] == 2]


class _Ctx:
    """ContextTypes.DEFAULT_TYPE o'rnini bosuvchi minimal fake."""

    def __init__(self, user_data, bot=None):
        self.user_data = user_data
        self.bot = bot if bot is not None else _Bot()


async def _run_with_chain(mode, coro_fn):
    """``_run_ai_chain`` ni mock bilan almashtirib, ``coro_fn(chain)`` ni bajaradi."""
    chain = FakeChain(mode)
    original = ai_agent._run_ai_chain
    original_timeout = ai_agent.PRO_AUDIT_TIMEOUT
    ai_agent._run_ai_chain = chain
    if mode == "timeout":
        ai_agent.PRO_AUDIT_TIMEOUT = 0.3   # test tez tugashi uchun
    try:
        result = await coro_fn(chain)
    finally:
        ai_agent._run_ai_chain = original
        ai_agent.PRO_AUDIT_TIMEOUT = original_timeout
    return chain, result


# ============================================================
# A) PRO — 2-BOSQICHLI AVTOMATIK AUDIT
# ============================================================

def test_pro_two_stage_audit():
    section("A) PRO (is_pro=True): 2-bosqichli avtomatik audit")

    async def call(chain):
        return await ai_agent.analyze_user_prompt(
            "Kofe haqida post yoz", user_id=1, is_pro=True, lang="uz")

    chain, res = asyncio.run(_run_with_chain("ok", call))

    check("PRO: 2 ta AI so'rovi bo'ldi (1-bosqich + 2-bosqich)",
          len(chain.calls) == 2, str(len(chain.calls)))
    check("PRO: 1-bosqich chaqiruvi mavjud", len(chain.stage1_calls) == 1)
    check("PRO: 2-bosqich chaqiruvi mavjud", len(chain.stage2_calls) == 1)

    # 2-bosqich aynan mavjud _AUDIT_PRO_SYSTEM tizim prompti bilan ketdi.
    audit_sys = chain.stage2_calls[0]["sys"] if chain.stage2_calls else ""
    check("PRO: 2-bosqichda _AUDIT_PRO_SYSTEM ishlatildi",
          "SMM auditor" in audit_sys and "reytingi" in audit_sys,
          audit_sys[:120])
    check("PRO: auditor prompti _AUDIT_PRO_SYSTEM matnini o'z ichiga oladi",
          ai_agent._AUDIT_PRO_SYSTEM.strip().splitlines()[0] in audit_sys)
    check("PRO: 2-bosqich promptiga 1-bosqich matni kiritilgan",
          STAGE1_POST in chain.stage2_calls[0]["prompt"])
    check("PRO: 2-bosqichda JSON kontrakti (improved_post) so'ralgan",
          "improved_post" in chain.stage2_calls[0]["prompt"])
    check("PRO: auditor tizim prompti FREE audit prompti EMAS",
          ai_agent._AUDIT_FREE_SYSTEM.strip() not in audit_sys)

    # Foydalanuvchiga FAQAT yakuniy (auditor) varianti ko'rsatiladi.
    check("PRO: post_text == 2-bosqichning yaxshilangan varianti",
          res.get("post_text") == AUDITED_POST, str(res.get("post_text"))[:90])
    check("PRO: 1-bosqich matni post_text'da QOLMADI",
          res.get("post_text") != STAGE1_POST)
    check("PRO: post_text_stage1 — 1-bosqich matni saqlandi",
          res.get("post_text_stage1") == STAGE1_POST)
    check("PRO: audit_applied=True", res.get("audit_applied") is True,
          str(res.get("audit_applied")))
    check("PRO: audit_error yo'q", not res.get("audit_error"), str(res.get("audit_error")))
    check("PRO: audit_rating saqlandi (9)", res.get("audit_rating") == 9,
          str(res.get("audit_rating")))
    check("PRO: intent saqlandi (post)", res.get("intent") == "post")
    check("PRO: natijada 'error' kaliti yo'q (oqim to'xtamadi)",
          "error" not in res, str(res.get("error")))

    # Ochiq (tashqi) API orqali ham bir xil oqim.
    async def call_two(chain):
        return await ai_agent.generate_post_two_stage(
            "Kofe haqida post yoz", user_id=1, is_pro=True, lang="uz")

    chain2, res2 = asyncio.run(_run_with_chain("ok", call_two))
    check("PRO: generate_post_two_stage — 2 ta chaqiruv", len(chain2.calls) == 2,
          str(len(chain2.calls)))
    check("PRO: generate_post_two_stage — yakuniy variant qaytadi",
          res2.get("post_text") == AUDITED_POST)
    check("PRO: generate_post_two_stage — audit ikki marta QILINMAYDI",
          len(chain2.stage2_calls) == 1, str(len(chain2.stage2_calls)))


def test_pro_audit_skipped_for_faq():
    section("A2) PRO: FAQ/javob intentida audit chaqirilmaydi")

    async def faq_chain(prompt, system_instruction, lang=None):
        return {"intent": "faq", "reply": "Bot qanday ishlaydi?", "post_text": ""}

    original = ai_agent._run_ai_chain
    ai_agent._run_ai_chain = faq_chain
    try:
        res = asyncio.run(
            ai_agent.analyze_user_prompt("Bot qanday ishlaydi?", user_id=1,
                                         is_pro=True, lang="uz"))
    finally:
        ai_agent._run_ai_chain = original

    check("FAQ: audit qo'llanmadi (post_text_stage1 yo'q)",
          "post_text_stage1" not in res, str(res)[:80])
    check("FAQ: reply saqlandi", res.get("reply") == "Bot qanday ishlaydi?")
    check("FAQ: xato yo'q", "error" not in res)


# ============================================================
# B) FREE — 2-BOSQICH CHAQIRILMAYDI
# ============================================================

def test_free_single_stage():
    section("B) FREE (is_pro=False): auditor umuman chaqirilmaydi")

    async def call(chain):
        return await ai_agent.analyze_user_prompt(
            "Kofe haqida post yoz", user_id=1, is_pro=False, lang="uz")

    chain, res = asyncio.run(_run_with_chain("ok", call))

    check("FREE: FAQAT 1 ta AI so'rovi", len(chain.calls) == 1, str(len(chain.calls)))
    check("FREE: 2-bosqich chaqiruvi yo'q", len(chain.stage2_calls) == 0)
    check("FREE: auditor tizim prompti hech qayerda ishlatilmadi",
          all("SMM auditor" not in c["sys"] for c in chain.calls))
    check("FREE: _AUDIT_PRO_SYSTEM matni chaqiruvlarda yo'q",
          all(ai_agent._AUDIT_PRO_SYSTEM.strip()[:40] not in c["sys"]
              for c in chain.calls))
    check("FREE: post_text == 1-bosqich natijasi",
          res.get("post_text") == STAGE1_POST)
    check("FREE: post_text_stage1 yo'q (audit bo'lmagan)",
          "post_text_stage1" not in res)
    check("FREE: audit_applied yo'q/False", not res.get("audit_applied"))
    check("FREE: xato yo'q", "error" not in res)

    # generate_post_two_stage FREE uchun ham bitta bosqich.
    async def call_two(chain):
        return await ai_agent.generate_post_two_stage(
            "Kofe haqida post yoz", user_id=1, is_pro=False, lang="uz")

    chain2, res2 = asyncio.run(_run_with_chain("ok", call_two))
    check("FREE: generate_post_two_stage — 1 ta chaqiruv", len(chain2.calls) == 1,
          str(len(chain2.calls)))
    check("FREE: generate_post_two_stage — audit_applied=False",
          res2.get("audit_applied") is False, str(res2.get("audit_applied")))
    check("FREE: generate_post_two_stage — post 1-bosqichdan",
          res2.get("post_text") == STAGE1_POST)


# ============================================================
# C) 2-BOSQICH XATOSI → 1-BOSQICH XAVFSIZ QAYTADI
# ============================================================

def test_stage2_failure_fallback():
    section("C) 2-bosqich xatosi: 1-bosqich posti xavfsiz qaytadi")

    modes = (
        ("raise", "tarmoq uzilishi (istisno)"),
        ("error", "provayder xato qaytardi (zaxira modellar ham)"),
        ("timeout", "hard timeout"),
        ("analysis", "auditor tahlil matnini qaytardi (post emas)"),
        ("empty", "improved_post bo'sh"),
        ("short", "juda qisqa javob (xulosa)"),
    )
    for mode, title in modes:
        async def call(chain):
            return await ai_agent.analyze_user_prompt(
                "Kofe haqida post yoz", user_id=1, is_pro=True, lang="uz")

        _chain, res = asyncio.run(_run_with_chain(mode, call))
        check(f"C[{mode}] {title}: 1-bosqich posti qaytdi",
              res.get("post_text") == STAGE1_POST, str(res.get("post_text"))[:70])
        check(f"C[{mode}] {title}: 'error' kaliti yo'q (oqim davom etadi)",
              "error" not in res, str(res.get("error")))
        check(f"C[{mode}] {title}: audit_applied=False",
              res.get("audit_applied") is False, str(res.get("audit_applied")))
        check(f"C[{mode}] {title}: sabab audit_error'da saqlandi",
              bool(res.get("audit_error")), str(res.get("audit_error")))
        check(f"C[{mode}] {title}: intent/post turi saqlandi",
              res.get("intent") == "post")

    # Bo'sh matn bilan auditor chaqirilmasin (xato ham bo'lmasin).
    res_empty = asyncio.run(ai_agent.refine_post_pro("", lang="uz"))
    check("refine_post_pro(''): bo'sh natija + xato (chaqiruvchi fallback qiladi)",
          res_empty.get("post_text") == "" and bool(res_empty.get("error")),
          str(res_empty))


def test_two_stage_disabled_by_env_flag():
    section("C2) AI_PRO_TWO_STAGE=0 → 2-bosqich butunlay o'chadi")
    original_flag = ai_agent.PRO_TWO_STAGE_ENABLED
    ai_agent.PRO_TWO_STAGE_ENABLED = False
    try:
        async def call(chain):
            return await ai_agent.analyze_user_prompt(
                "Kofe haqida post yoz", user_id=1, is_pro=True, lang="uz")

        chain, res = asyncio.run(_run_with_chain("ok", call))
    finally:
        ai_agent.PRO_TWO_STAGE_ENABLED = original_flag

    check("o'chirilgan: FAQAT 1 ta chaqiruv", len(chain.calls) == 1, str(len(chain.calls)))
    check("o'chirilgan: post 1-bosqichdan", res.get("post_text") == STAGE1_POST)


# ============================================================
# D) FREE PROMPT STRUKTURASI (Hook / Value / CTA / hashtag)
# ============================================================

def test_free_prompt_structure():
    section("D) FREE tarif prompti: minimal struktura talabi (uz/ru/en)")

    expectations = {
        "uz": ("Hook", "Value", "Call to Action", "hashtag", "3-5"),
        "ru": ("Hook", "Value", "Call to Action", "хештег", "3-5"),
        "en": ("Hook", "Value", "Call to Action", "hashtag", "3-5"),
    }
    prompts = {}
    for code, words in expectations.items():
        prompt = ai_agent._get_router_system_instruction(is_pro=False, lang=code)
        prompts[code] = prompt
        missing = [w for w in words if w not in prompt]
        check(f"FREE[{code}]: struktura talablari bor ({', '.join(words)})",
              not missing, str(missing))

    # Har bir qism alohida band sifatida yozilgan.
    uz_hint = ai_agent._FREE_POST_HINT_BY_LANG["uz"]
    for part in ("1) Hook", "2) Value", "3) Call to Action", "4) Oxirida 3-5"):
        check(f"FREE[uz] hint: '{part}' bandi bor", part in uz_hint, uz_hint[:80])

    # Til tozaligi: uz/en — kirillsiz, ru — kirillda.
    check("FREE[uz] prompt kirilldan xoli", not CYRILLIC.search(prompts["uz"]),
          str(CYRILLIC.findall(prompts["uz"])[:5]))
    check("FREE[en] prompt kirilldan xoli", not CYRILLIC.search(prompts["en"]),
          str(CYRILLIC.findall(prompts["en"])[:5]))
    check("FREE[ru] prompt kirillda", bool(CYRILLIC.search(prompts["ru"])))
    check("3 tilning FREE promptlari farqli", len(set(prompts.values())) == 3)

    # FREE'da ham JSON kontrakti saqlanadi (router ishlashi uchun).
    for code, prompt in prompts.items():
        for field in ("intent", "reply", "post_text", "scheduled_time"):
            check(f"FREE[{code}]: JSON kontraktida '{field}' bor", f'"{field}"' in prompt)

    # FREE hint generatsiya chaqiruviga ham kiradi (is_pro=False bilan).
    async def call(chain):
        return await ai_agent.generate_ai_response("Mavzu: kofe", is_pro=False, lang="uz")

    chain, _ = asyncio.run(_run_with_chain("ok", call))
    check("FREE: generatsiya promptida Hook talabi bor",
          chain.calls and "Hook" in chain.calls[0]["sys"],
          (chain.calls[0]["sys"][:80] if chain.calls else "chaqiruv yo'q"))

    # PRO prompti AIDA/PAS'ni saqlab qoladi (2-bosqich asosi).
    pro_prompt = ai_agent._get_router_system_instruction(is_pro=True, lang="uz")
    check("PRO: prompt AIDA/PAS formulalarini talab qiladi",
          "AIDA" in pro_prompt and "PAS" in pro_prompt)
    check("PRO: audit tizim prompti 'yaxshilangan variant'ni talab qiladi",
          "yaxshilangan varianti" in ai_agent._AUDIT_PRO_SYSTEM)


def test_audit_request_contract_i18n():
    section("D2) 2-bosqich JSON kontrakti — 3 tilda va til tozaligi")
    for code in ("uz", "ru", "en"):
        req = ai_agent._AUDIT_FINAL_REQUEST_BY_LANG[code]
        check(f"audit kontrakti[{code}]: improved_post so'raladi",
              "improved_post" in req and "rating" in req, req[:80])
        check(f"audit kontrakti[{code}]: FAQAT tayyor post talab qilinadi",
              "improved_post" in req and ("faqat" in req.lower() or "только" in req.lower()
                                          or "only" in req.lower()))
        check(f"audit kontrakti[{code}]: faktlar o'zgarmasligi aytilgan",
              ("O'ZGARTIRILMAYDI" in req or "НЕ меняются" in req or "MUST NOT change" in req))
    check("audit kontrakti[uz] kirillsiz",
          not CYRILLIC.search(ai_agent._AUDIT_FINAL_REQUEST_BY_LANG["uz"]))
    check("audit kontrakti[en] kirillsiz",
          not CYRILLIC.search(ai_agent._AUDIT_FINAL_REQUEST_BY_LANG["en"]))
    check("audit kontrakti[ru] kirillda",
          bool(CYRILLIC.search(ai_agent._AUDIT_FINAL_REQUEST_BY_LANG["ru"])))
    check("3 tilning kontraktlari farqli",
          len({ai_agent._AUDIT_FINAL_REQUEST_BY_LANG[c] for c in ("uz", "ru", "en")}) == 3)


# ============================================================
# E) EKSTRAKTOR — auditor javobidan tayyor postni ajratish
# ============================================================

def test_extract_improved_post():
    section("E) _extract_improved_post: tahlil emas, tayyor post ajratiladi")
    original = STAGE1_POST
    check("improved_post kaliti ustuvor",
          ai_agent._extract_improved_post(
              {"improved_post": AUDITED_POST, "reply": "boshqa"}, original) == AUDITED_POST)
    check("final_post zaxira kaliti",
          ai_agent._extract_improved_post({"final_post": AUDITED_POST}, original) == AUDITED_POST)
    check("post_text kaliti ham qabul qilinadi",
          ai_agent._extract_improved_post({"post_text": AUDITED_POST}, original) == AUDITED_POST)
    check("tahlil matni RAD etiladi (bo'sh qaytadi)",
          ai_agent._extract_improved_post({"audit": ANALYSIS_ONLY}, original) == "",
          ai_agent._extract_improved_post({"audit": ANALYSIS_ONLY}, original)[:60])
    check("bo'sh improved_post rad etiladi",
          ai_agent._extract_improved_post({"improved_post": "   "}, original) == "")
    check("juda qisqa javob rad etiladi",
          ai_agent._extract_improved_post({"improved_post": "Qisqa."}, original) == "")
    check("dict bo'lmagan javob → bo'sh", ai_agent._extract_improved_post(None, original) == "")
    check("JSON ko'rinishidagi matn rad etiladi",
          ai_agent._extract_improved_post(
              {"improved_post": '{"rating": 9, "improved_post": "x"}'}, original) == "")
    check("eng uzun qiymat zaxira sifatida olinadi (tayyor post bo'lsa)",
          ai_agent._extract_improved_post({"note": "ok", "text": AUDITED_POST}, original)
          == AUDITED_POST)


# ============================================================
# F) handlers/post_enhancer.py INTEGRATSIYASI
# ============================================================

class _Msg:
    def __init__(self, message_id=1, chat_id=111, text=""):
        self.message_id = message_id
        self.chat_id = chat_id
        self.text = text

    async def reply_text(self, *args, **kwargs):
        return _Msg(2, self.chat_id)

    async def delete(self):
        return None


class _User:
    def __init__(self, uid):
        self.id = uid


class _Query:
    def __init__(self, data, message=None, uid=424400):
        self.data = data
        self.message = message or _Msg(500, 111)
        self.from_user = _User(uid)
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class _Bot:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self._next_id = 600

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kwargs):
        self._next_id += 1
        self.sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return _Msg(self._next_id, chat_id)

    async def delete_message(self, chat_id=None, message_id=None):
        self.deleted.append(message_id)


class _Upd:
    def __init__(self, query):
        self.callback_query = query
        self.effective_user = query.from_user
        self.message = None


IS_PRO = {"value": False}


async def _fake_run_db(fn, *args, **kwargs):
    """DB'ni to'liq taqlid qiladi (real PostgreSQL chaqirilmaydi)."""
    name = getattr(fn, "__name__", "")
    if name == "is_premium":
        return IS_PRO["value"]
    if name == "get_user_channels":
        return []
    return None


db.run_db = _fake_run_db


def _hub_callbacks(enh, lang="uz"):
    _, markup = pe._hub_view(_Ctx({"enh": enh, "lang": lang}), "", lang)
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _text_enh(is_pro=None, content=STAGE1_POST, post_type="text"):
    return {
        **pe._fresh_enh(),
        "step": "hub",
        "hub_msg_id": 500,
        "post": {"type": post_type, "file_id": None if post_type == "text" else "F",
                 "content": content},
        "is_pro": is_pro,
    }


def test_enhancer_audit_button_visibility():
    section("F1) Enhancer: '✨ AI audit (PRO)' tugmasi ko'rinishi")
    check("is_pro=None (aniqlanmagan) → tugma YO'Q",
          "enh:audit" not in _hub_callbacks(_text_enh(is_pro=None)))
    check("is_pro=False (FREE) → tugma YO'Q",
          "enh:audit" not in _hub_callbacks(_text_enh(is_pro=False)))
    check("is_pro=True + matnli post → tugma BOR",
          "enh:audit" in _hub_callbacks(_text_enh(is_pro=True)))
    check("is_pro=True + rasm post → tugma YO'Q (faqat matn)",
          "enh:audit" not in _hub_callbacks(_text_enh(is_pro=True, post_type="photo")))
    check("is_pro=True + bo'sh matn → tugma YO'Q",
          "enh:audit" not in _hub_callbacks(_text_enh(is_pro=True, content="   ")))
    check("tugma 10 qator chegarasini buzmaydi",
          len(_hub_callbacks(_text_enh(is_pro=True))) <= pe.MAX_KEYBOARD_ROWS * 2)
    for code in ("uz", "ru", "en"):
        label = pe.get_text("enh_btn_ai_audit", code)
        check(f"tugma yozuvi [{code}] mavjud va PRO'ni ko'rsatadi",
              bool(label) and "PRO" in label, label)
    check("uz/en yozuvlari farqli (tarjima qilingan)",
          pe.get_text("enh_btn_ai_audit", "uz") != pe.get_text("enh_btn_ai_audit", "en"))


def test_enhancer_audit_flow():
    section("F2) Enhancer: audit bosilganda post mukammallashtiriladi")

    async def run():
        IS_PRO["value"] = True
        bot = _Bot()
        enh = _text_enh(is_pro=True)
        ctx = _Ctx({"enh": enh, "lang": "uz", "content": STAGE1_POST}, bot)
        upd = _Upd(_Query("enh:audit", _Msg(500, 111)))

        chain = FakeChain("ok")
        original_chain = ai_agent._run_ai_chain
        ai_agent._run_ai_chain = chain
        try:
            out = await pe.enh_callback(upd, ctx)
        finally:
            ai_agent._run_ai_chain = original_chain

        check("enh:audit → suhbat holati saqlandi (ENH_POST)", out == pe.ENH_POST, str(out))
        check("enh:audit → auditor chaqirildi (2-bosqich)",
              len(chain.stage2_calls) == 1, str(len(chain.stage2_calls)))
        check("enh:audit → post matni yaxshilangan variant bilan almashtirildi",
              enh["post"]["content"] == AUDITED_POST, str(enh["post"]["content"])[:70])
        check("enh:audit → user_data['content'] ham yangilandi",
              ctx.user_data["content"] == AUDITED_POST)
        check("enh:audit → panel qayta chizildi (yangi xabar yuborildi)",
              len(bot.sent) >= 1, str(len(bot.sent)))
        check("enh:audit → 'bajarildi' eslatmasi ko'rsatildi",
              any("bajarildi" in (s["text"] or "") for s in bot.sent),
              str([(s["text"] or "")[:40] for s in bot.sent]))
        check("enh:audit → kutish xabari o'chirildi", len(bot.deleted) >= 1,
              str(bot.deleted))
        check("enh:audit → query.answer() chaqirildi",
              bool(upd.callback_query.answers))

    asyncio.run(run())


def test_enhancer_audit_fallback_keeps_original():
    section("F3) Enhancer: 2-bosqich xatosida ASL post saqlanadi")

    for mode in ("raise", "error", "timeout", "analysis", "empty"):
        async def run(mode=mode):
            IS_PRO["value"] = True
            bot = _Bot()
            enh = _text_enh(is_pro=True)
            ctx = _Ctx({"enh": enh, "lang": "uz", "content": STAGE1_POST}, bot)
            upd = _Upd(_Query("enh:audit", _Msg(500, 111)))
            chain = FakeChain(mode)
            original_chain = ai_agent._run_ai_chain
            original_timeout = ai_agent.PRO_AUDIT_TIMEOUT
            ai_agent._run_ai_chain = chain
            if mode == "timeout":
                ai_agent.PRO_AUDIT_TIMEOUT = 0.3
            try:
                out = await pe.enh_callback(upd, ctx)
            finally:
                ai_agent._run_ai_chain = original_chain
                ai_agent.PRO_AUDIT_TIMEOUT = original_timeout
            return out, bot, enh, ctx

        out, bot, enh, ctx = asyncio.run(run())
        check(f"fallback[{mode}]: oqim to'xtamadi (ENH_POST)", out == pe.ENH_POST, str(out))
        check(f"fallback[{mode}]: ASL post matni saqlandi",
              enh["post"]["content"] == STAGE1_POST, str(enh["post"]["content"])[:60])
        check(f"fallback[{mode}]: user_data['content'] saqlandi",
              ctx.user_data["content"] == STAGE1_POST)
        check(f"fallback[{mode}]: foydalanuvchiga sabab aytildi",
              any("javob bermadi" in (s["text"] or "") for s in bot.sent),
              str([(s["text"] or "")[:40] for s in bot.sent]))


def test_enhancer_audit_guards():
    section("F4) Enhancer: FREE/matnsiz postda auditor chaqirilmaydi")

    async def run(is_pro_db, enh, cb="enh:audit"):
        IS_PRO["value"] = is_pro_db
        bot = _Bot()
        ctx = _Ctx({"enh": enh, "lang": "uz", "content": enh["post"]["content"]}, bot)
        upd = _Upd(_Query(cb, _Msg(500, 111)))
        chain = FakeChain("ok")
        original_chain = ai_agent._run_ai_chain
        ai_agent._run_ai_chain = chain
        try:
            out = await pe.enh_callback(upd, ctx)
        finally:
            ai_agent._run_ai_chain = original_chain
        return out, bot, enh, ctx, chain, upd.callback_query

    # 1) FREE foydalanuvchi (kesh yo'q → DB'dan so'raladi) → auditor chaqirilmaydi
    out, bot, enh, ctx, chain, q = asyncio.run(run(False, _text_enh(is_pro=None)))
    check("FREE: auditor chaqirilmadi (0 ta AI so'rovi)", len(chain.calls) == 0,
          str(len(chain.calls)))
    check("FREE: post matni o'zgarmadi", enh["post"]["content"] == STAGE1_POST)
    check("FREE: PRO talabi haqida ogohlantirish berildi",
          any(t and "PRO" in t for t, _ in q.answers), str(q.answers))
    check("FREE: enh['is_pro']=False keshlandi", enh.get("is_pro") is False)

    # 2) Matnli bo'lmagan post → auditor chaqirilmaydi
    out, bot, enh, ctx, chain, q = asyncio.run(
        run(True, _text_enh(is_pro=True, post_type="photo")))
    check("rasm post: auditor chaqirilmadi", len(chain.calls) == 0, str(len(chain.calls)))
    check("rasm post: post mazmuni o'zgarmadi", enh["post"]["content"] == STAGE1_POST)
    check("rasm post: oqim davom etadi (ENH_POST)", out == pe.ENH_POST, str(out))
    check("rasm post: AI kutish xabari yuborilmadi", bot.sent == [], str(bot.sent))
    check("rasm post: user_data['content'] tegilmadi",
          ctx.user_data["content"] == STAGE1_POST)
    check("rasm post: 'faqat matnli' eslatmasi",
          any(t and "matnli" in t for t, _ in q.answers), str(q.answers))

    # 3) Bo'sh matn → auditor chaqirilmaydi
    _out, _bot, _enh, _ctx, chain, _q = asyncio.run(
        run(True, _text_enh(is_pro=True, content="  ")))
    check("bo'sh matn: auditor chaqirilmadi", len(chain.calls) == 0, str(len(chain.calls)))

    # 4) _resolve_is_pro: admin → PRO (DB so'rovisiz)
    IS_PRO["value"] = False
    admin_id = min(pe.ADMIN_IDS_SET) if pe.ADMIN_IDS_SET else 123
    enh_admin = _text_enh(is_pro=None)
    is_pro = asyncio.run(pe._resolve_is_pro(admin_id, enh_admin))
    check("admin: PRO sifatida audit huquqiga ega", is_pro is True, str(is_pro))

    # 5) _resolve_is_pro: DB xatosida False (oqim to'xtamaydi)
    async def broken_run_db(fn, *a, **k):
        raise RuntimeError("DB uzildi")

    original_run_db = db.run_db
    db.run_db = broken_run_db
    try:
        enh_broken = _text_enh(is_pro=None)
        is_pro = asyncio.run(pe._resolve_is_pro(424400, enh_broken))
    finally:
        db.run_db = original_run_db
    check("DB xatosi: is_pro=False (xavfsiz), oqim to'xtamadi", is_pro is False)


def test_source_wiring():
    section("F5) Manba kodi: oqim to'g'ri ulangan (statik tekshiruv)")
    ai_src = (ROOT / "utils" / "ai_agent.py").read_text(encoding="utf-8")
    pe_src = (ROOT / "handlers" / "post_enhancer.py").read_text(encoding="utf-8")

    body = ai_src.split("async def analyze_user_prompt", 1)[1].split("\nasync def ", 1)[0]
    check("analyze_user_prompt: PRO uchun 2-bosqich chaqiriladi",
          "if is_pro:" in body and "apply_pro_audit_stage" in body,
          body[-200:])
    check("analyze_user_prompt: FREE uchun audit chaqirilmaydi (shart ichida)",
          "apply_pro_audit_stage" in body and body.count("apply_pro_audit_stage") == 1)
    check("refine_post_pro: _AUDIT_PRO_SYSTEM ishlatiladi",
          "_AUDIT_PRO_SYSTEM" in ai_src.split("async def refine_post_pro", 1)[1]
          .split("\nasync def ", 1)[0])
    check("apply_pro_audit_stage: fallback 1-bosqich matnini saqlaydi",
          "post_text_stage1" in ai_src and "audit_applied" in ai_src)
    check("post_enhancer: ai_agent.refine_post_pro chaqiriladi",
          "ai_agent.refine_post_pro" in pe_src)
    check("post_enhancer: enh:audit router'ga ulangan",
          'action == "audit"' in pe_src and "_audit_post_step" in pe_src)
    check("post_enhancer: audit tugmasi faqat PRO'da (is_pro sharti)",
          'enh.get("is_pro")' in pe_src and "enh:audit" in pe_src)
    check("post_enhancer: ASL MATNGA TEKILMAYDI kafolati saqlangan",
          "TEKILMAYDI" in pe_src)
    check("post_enhancer: audit FAQAT foydalanuvchi so'rovi bilan (istisno izohi)",
          "O'Z so'rovi" in pe_src or "O'Z so'rovi bilan" in pe_src)


def main():
    print("PostAssist V2 — ✨ PRO 2-BOSQICHLI AUDIT + FREE PROMPT STRUKTURASI TESTI")
    test_pro_two_stage_audit()
    test_pro_audit_skipped_for_faq()
    test_free_single_stage()
    test_stage2_failure_fallback()
    test_two_stage_disabled_by_env_flag()
    test_free_prompt_structure()
    test_audit_request_contract_i18n()
    test_extract_improved_post()
    test_enhancer_audit_button_visibility()
    test_enhancer_audit_flow()
    test_enhancer_audit_fallback_keeps_original()
    test_enhancer_audit_guards()
    test_source_wiring()

    print("\n" + "-" * 64)
    print(f"JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        sys.exit(1)
    print("Barcha PRO 2-bosqichli audit testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
