"""✨ 2-BOSQICH — AI PROMPT VA MAGIC POST SIFATI VALIDATSIYASI.

Skrinshotlardagi muammo: «sport haqida bo'lsin futbol bo'yicha» kabi mavzu
kiritilganda AI 1 qatorli, ma'nosiz va robotik matn qaytarardi
(«Sportlar boshqalariga qoling: futbol bo'yicha»). Ushbu test quyidagilarni
QAT'IY kafolatlaydi:

  TEST 1 — Tizim promptlari (5 uslub × 3 til) professional SMM muhandisligi:
           majburiy 4 qism (Hook / Asosiy mazmun / CTA / 3-5 hashtag),
           «1-2 qatorli quruq jumla» taqiqi, so'zma-so'z tarjima taqiqi,
           uslublar real farqlanadi (AIDA/PAS, ekspert xulosasi, premium,
           blogerona hayotiy misollar).
  TEST 2 — Sifat validatori (magic_post_quality_report): yaxshi post o'tadi,
           1 qatorli robotik matn rad etiladi; hook/CTA/hashtag/uzunlik
           alohida aniqlanadi.
  TEST 3 — generate_magic_post: AI yupqa javob bersa kuchaytirilgan
           ko'rsatma bilan BIR MARTA qayta so'raydi va yaxshirog'ini
           qaytaradi; natijada ``quality`` hisoboti bor; yaxshi javobda
           qayta so'rov YO'Q (kredit/taymer tejaladi).
  TEST 4 — UI ixchamligi: mp_intro qisqa SaaS taklifi (3 tilda), natija
           klaviaturasi faqat eng kerakli amallar [2, 2, 1] layout, i18n
           paritet saqlangan.
  TEST 5 — Regressiya: mavjud FSM holatlari, callback'lar (mp_restyle,
           mp_back ≤ 64 bayt) va Magic Post ichida ovoz/rasm o'z oqimiga
           yo'naltirilishi.

Ishga tushirish:  PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
"""

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:AI_PROMPT_QUALITY_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def run(coro):
    return asyncio.run(coro)


from utils.ai_agent import (  # noqa: E402
    MAGIC_POST_STYLES,
    MAGIC_POST_SYSTEMS,
    MAGIC_POST_MIN_BODY_CHARS,
    MAGIC_POST_MIN_CONTENT_LINES,
    build_magic_post_system,
    generate_magic_post,
    is_magic_post_too_thin,
    magic_post_quality_report,
)
from translations import MAGIC_POST_I18N, magic_t, magic_post_parity_report  # noqa: E402
from handlers import magic_post as mp  # noqa: E402
from keyboards.callback_data import is_callback_safe  # noqa: E402

LANGS = ("uz", "ru", "en")

# ---------------------------------------------------------------------------
# Namuna postlar
# ---------------------------------------------------------------------------
ROBOTIC_ONE_LINER = "Sportlar boshqalariga qoling: futbol bo'yicha"

GOOD_POST_UZ = (
    "⚽️ <b>Futbol — dunyoni birlashtirgan o'yin!</b>\n\n"
    "🏟 Har hafta oxiri milliardlab odam stadion va ekranlar oldida bitta "
    "to'p ortidan nafas rostlaydi. Bu shunchaki sport emas — bu his-tuyg'u.\n\n"
    "💪 Muntazam futbol o'ynash yurak-qon tomir tizimini mustahkamlaydi, "
    "chidamlilikni oshiradi va stressni kamaytiradi.\n\n"
    "🤝 Jamoaviy o'yin sizga muloqot, sabr va yetakchilik ko'nikmalarini "
    "beradi — bu maydon tashqarisida ham asqotadi.\n\n"
    "Siz qaysi jamoani qo'llab-quvvatlaysiz? Izohlarda yozing 👇\n\n"
    "#futbol #sport #salomatlik #jamoa"
)

RETRY_POST_UZ = (
    "🔥 <b>Futbol haqida 3 ta qiziqarli fakt</b>\n\n"
    "1️⃣ Eng birinchi rasmiy futbol qoidalari 1863-yilda Angliyada qabul qilingan.\n\n"
    "2️⃣ Bitta o'yinda futbolchi o'rtacha 10-12 kilometr masofani bosib o'tadi.\n\n"
    "3️⃣ Jahon chempionati finalini sayyoramizning yarmidan ko'pi tomosha qiladi.\n\n"
    "Qaysi fakt siz uchun yangilik bo'ldi? Fikringizni izohda qoldiring 👇\n\n"
    "#futbol #sport #faktlar"
)


# ============================================================================
# TEST 1 — TIZIM PROMPTLARI: PROFESSIONAL SMM MUHANDISLIGI
# ============================================================================
def test_system_prompts_engineering():
    print("\n== TEST 1: System promptlar — majburiy tuzilma va uslub farqlari ==")

    structure_markers = {
        "uz": ("HOOK", "ASOSIY MAZMUN", "CALL-TO-ACTION", "HASHTAG", "3-5",
               "1-2 qatorli", "so'zma-so'z", "5 qatordan qisqa"),
        "ru": ("ХУК", "ОСНОВНОЕ СОДЕРЖАНИЕ", "ПРИЗЫВ К ДЕЙСТВИЮ", "ХЭШТЕГ", "3-5",
               "1-2 строк", "дословный", "короче 5 строк"),
        "en": ("HOOK", "MAIN BODY", "CALL-TO-ACTION", "HASHTAG", "3-5",
               "1-2 line", "word-for-word", "shorter than 5 lines"),
    }
    for style in MAGIC_POST_STYLES:
        for lang in LANGS:
            prompt = MAGIC_POST_SYSTEMS[style][lang]
            low = prompt.lower()
            missing = [m for m in structure_markers[lang] if m.lower() not in low]
            check(f"[{style}/{lang}] majburiy 4 qism + taqiqlar promptda", not missing,
                  str(missing))
            check(f"[{style}/{lang}] prompt yetarlicha batafsil (>1500 belgi)",
                  len(prompt) > 1500, str(len(prompt)))
            check(f"[{style}/{lang}] rol: qisqa mavzu ham to'liq postga aylanadi",
                  any(k in low for k in ("futbol", "футбол", "football")))
            check(f"[{style}/{lang}] JSON kontrakti saqlangan", '"post_text"' in prompt)
            check(f"[{style}/{lang}] build_magic_post_system bir xil promptni qaytaradi",
                  build_magic_post_system(style, lang) == prompt)

    # Uslublar REAL farqlanadi (bir xil skelet, turli formulalar).
    uz = {s: MAGIC_POST_SYSTEMS[s]["uz"] for s in MAGIC_POST_STYLES}
    check("Sotuv: AIDA/PAS + aniq taklif", "AIDA" in uz["sales"] and "PAS" in uz["sales"]
          and "ANIQ TAKLIF" in uz["sales"])
    check("Informativ: foydali faktlar + ekspert xulosasi",
          "EKSPERT XULOSASI" in uz["informative"] and "foydali faktlar" in uz["informative"].lower())
    check("Premium: nafis, lakonik, ishonchli — aksiya toni taqiqlangan",
          "lakonik" in uz["premium"] and "TAQIQLANGAN" in uz["premium"])
    check("Oddiy/Blogerona: samimiy + hayotiy misollar",
          "HAYOTIY MISOLLAR" in uz["casual"] and "samimiy" in uz["casual"].lower())
    check("Reklama: sarlavha + havola joyi + CTA",
          "SARLAVHA" in uz["ads"] and "HAVOLA JOYI" in uz["ads"])
    check("5 uslub prompti o'zaro farqli", len(set(uz.values())) == 5)
    # O'zbek tili sifati talabi (xom tarjima taqiqi) format qoidalarida.
    check("UZ: tabiiy o'zbek tili va g'aliz jumla taqiqi",
          "tabiiy o'zbek tili" in uz["sales"] and "boshqalariga qoling" in uz["sales"])


# ============================================================================
# TEST 2 — SIFAT VALIDATORI
# ============================================================================
def test_quality_validator():
    print("\n== TEST 2: magic_post_quality_report — yaxshi post o'tadi, robotik rad ==")

    good = magic_post_quality_report(GOOD_POST_UZ)
    check("yaxshi post: ok=True", good["ok"] is True, str(good))
    check("yaxshi post: hook (qalin + emoji) topildi", good["hook"])
    check("yaxshi post: CTA (savol/izoh) topildi", good["cta"])
    check("yaxshi post: 3-5 hashtag", good["hashtags"] and good["hashtag_count"] == 4)
    check(f"yaxshi post: mazmun ≥ {MAGIC_POST_MIN_BODY_CHARS} belgi",
          good["body"] and good["body_chars"] >= MAGIC_POST_MIN_BODY_CHARS)
    check(f"yaxshi post: qatorlar ≥ {MAGIC_POST_MIN_CONTENT_LINES}",
          good["lines"] and good["content_lines"] >= MAGIC_POST_MIN_CONTENT_LINES)
    check("yaxshi post yupqa emas", is_magic_post_too_thin(GOOD_POST_UZ) is False)

    bad = magic_post_quality_report(ROBOTIC_ONE_LINER)
    check("robotik 1 qator: ok=False", bad["ok"] is False)
    check("robotik 1 qator: body/lines/hook/cta/hashtags xatolari",
          {"body", "lines", "hook", "cta", "hashtags"} <= set(bad["issues"]), str(bad))
    check("robotik 1 qator YUPQA deb topiladi", is_magic_post_too_thin(ROBOTIC_ONE_LINER))

    # Hashtag yetishmasligi yupqa emas (ensure_magic_hashtags to'ldiradi).
    no_tags = GOOD_POST_UZ.rsplit("\n\n", 1)[0]
    rep = magic_post_quality_report(no_tags)
    check("hashtagsiz, lekin mazmunli post — faqat 'hashtags' issue",
          rep["issues"] == ["hashtags"], str(rep["issues"]))
    check("hashtagsiz mazmunli post yupqa EMAS", is_magic_post_too_thin(no_tags) is False)

    # Hajmi yetarli, lekin hook ham CTA ham yo'q — robotik.
    flat = ("Futbol juda yaxshi sport turi hisoblanadi va uni ko'pchilik yaxshi ko'radi. "
            "U odamlarga foyda beradi.\n") * 4
    check("hook va CTA'siz yassi matn yupqa deb topiladi", is_magic_post_too_thin(flat))

    # Bo'sh / None — yiqilmaydi.
    check("None uchun ok=False, istisno yo'q", magic_post_quality_report(None)["ok"] is False)
    check("'' uchun ok=False", magic_post_quality_report("")["ok"] is False)

    # RU/EN CTA va emoji-hook ham taniladi.
    ru = ("⚽️ <b>Футбол объединяет мир</b>\n\nКаждые выходные миллиарды людей "
          "следят за одним мячом. Это больше чем спорт — это эмоции.\n\n"
          "Регулярная игра укрепляет сердце и снижает стресс, а командная работа "
          "учит терпению и лидерству.\n\nА за какую команду болеете вы? 👇\n\n"
          "#футбол #спорт #здоровье")
    en = ("⚽️ <b>Football unites the world</b>\n\nEvery weekend billions follow "
          "one ball. It is more than sport — it is emotion.\n\nRegular play "
          "strengthens the heart and cuts stress, while teamwork teaches patience "
          "and leadership.\n\nWhich team do you support? Tell us below 👇\n\n"
          "#football #sport #health")
    check("RU post validatordan o'tadi", magic_post_quality_report(ru)["ok"])
    check("EN post validatordan o'tadi", magic_post_quality_report(en)["ok"])


# ============================================================================
# TEST 3 — generate_magic_post: YUPQA JAVOBDA QAYTA URINISH
# ============================================================================
def test_generate_retry_on_thin_answer():
    print("\n== TEST 3: generate_magic_post — yupqa javob → kuchaytirilgan qayta so'rov ==")

    calls = []

    async def thin_then_good(prompt, system_instruction=None, timeout=None,
                             tone=None, is_pro=False, lang="uz"):
        calls.append({"prompt": prompt, "system": system_instruction, "lang": lang})
        if len(calls) == 1:
            return {"post_text": ROBOTIC_ONE_LINER}
        return {"post_text": RETRY_POST_UZ}

    with patch("utils.ai_agent.generate_ai_response", new=thin_then_good):
        result = run(generate_magic_post("sport haqida bo'lsin futbol bo'yicha",
                                         "informative", lang="uz"))

    check("AI 2 marta chaqirildi (1 yupqa + 1 qayta urinish)", len(calls) == 2, str(len(calls)))
    check("qayta so'rov tizim promptida KUCHAYTIRILGAN ko'rsatma bor",
          len(calls) == 2 and "OLDINGI URINISH RAD ETILDI" in calls[1]["system"]
          and "kamida 600 belgi" in calls[1]["system"])
    check("qayta so'rov asl tizim promptini saqlagan (AIDA emas — informativ)",
          len(calls) == 2 and "INFORMATIV" in calls[1]["system"])
    check("qayta so'rov ham foydalanuvchi matni bilan",
          len(calls) == 2 and calls[1]["prompt"] == "sport haqida bo'lsin futbol bo'yicha")
    check("natija — yaxshi (qayta yozilgan) post", "3 ta qiziqarli fakt" in result.get("post_text", ""))
    check("robotik jumla natijada YO'Q", "boshqalariga qoling" not in result.get("post_text", ""))
    check("natijada quality hisoboti bor va ok=True",
          isinstance(result.get("quality"), dict) and result["quality"]["ok"] is True,
          str(result.get("quality")))
    check("retried=True belgilangan", result.get("retried") is True)
    check("post oxirida 3-5 hashtag",
          3 <= result["quality"]["hashtag_count"] <= 5)

    # Yaxshi javobda qayta so'rov YO'Q.
    calls.clear()

    async def good_first(prompt, system_instruction=None, timeout=None,
                         tone=None, is_pro=False, lang="uz"):
        calls.append(1)
        return {"post_text": GOOD_POST_UZ}

    with patch("utils.ai_agent.generate_ai_response", new=good_first):
        result = run(generate_magic_post("futbol", "casual", lang="uz"))
    check("yaxshi javobda AI faqat 1 marta chaqiriladi", len(calls) == 1)
    check("retried=False", result.get("retried") is False)
    check("natija quality.ok=True", result["quality"]["ok"] is True)

    # Ikkala urinish ham yupqa — oqim baribir post qaytaradi (bo'sh emas).
    calls.clear()

    async def always_thin(prompt, system_instruction=None, **kwargs):
        calls.append(1)
        return {"post_text": ROBOTIC_ONE_LINER}

    with patch("utils.ai_agent.generate_ai_response", new=always_thin):
        result = run(generate_magic_post("futbol", "sales", lang="uz"))
    check("ikkala urinish yupqa: AI 2 marta chaqirildi, oqim uzilmaydi",
          len(calls) == 2 and bool(result.get("post_text")) and not result.get("error"))
    check("ikkala urinish yupqa: quality.ok=False (handler/testlar ko'ra oladi)",
          result["quality"]["ok"] is False)

    # Retry provayder xatosi bersa — birinchi javob saqlanadi, istisno yo'q.
    calls.clear()

    async def thin_then_error(prompt, system_instruction=None, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"post_text": ROBOTIC_ONE_LINER}
        raise RuntimeError("provider down")

    with patch("utils.ai_agent.generate_ai_response", new=thin_then_error):
        result = run(generate_magic_post("futbol", "ads", lang="uz"))
    check("retry istisnosi yutiladi — birinchi javob qaytadi",
          not result.get("error") and "boshqalariga" in result.get("post_text", ""))

    # RU tilida ham kuchaytirilgan ko'rsatma ruscha.
    calls_ru = []

    async def thin_ru(prompt, system_instruction=None, **kwargs):
        calls_ru.append(system_instruction)
        return {"post_text": "Футбол это хорошо"}

    with patch("utils.ai_agent.generate_ai_response", new=thin_ru):
        run(generate_magic_post("футбол", "casual", lang="ru"))
    check("RU: qayta so'rov ko'rsatmasi ruscha",
          len(calls_ru) == 2 and "ПРЕДЫДУЩАЯ ПОПЫТКА ОТКЛОНЕНА" in calls_ru[1])


# ============================================================================
# TEST 4 — UI IXCHAMLIGI + i18n
# ============================================================================
def test_ui_compactness_and_i18n():
    print("\n== TEST 4: Ixcham intro + minimal natija klaviaturasi (3 til) ==")

    expected_intro_head = {
        "uz": "✨ <b>Magic Post</b> — g'oyadan tayyor postgacha!",
        "ru": "✨ <b>Magic Post</b> — от идеи до готового поста!",
        "en": "✨ <b>Magic Post</b> — from an idea to a ready post!",
    }
    for lang in LANGS:
        intro = magic_t("mp_intro", lang)
        check(f"[{lang}] mp_intro kutilgan SaaS sarlavhasi bilan boshlanadi",
              intro.startswith(expected_intro_head[lang]), repr(intro))
        check(f"[{lang}] mp_intro ≤ 4 qator va ≤ 220 belgi",
              intro.count("\n") <= 4 and len(intro) <= 220, str(len(intro)))
        check(f"[{lang}] mp_intro'da uslublar ro'yxati YO'Q",
              "AIDA" not in intro and "🔥" not in intro and "💎" not in intro)
        check(f"[{lang}] mp_intro ovoz/rasm taklifini o'z ichiga oladi",
              any(k in intro.lower() for k in ("ovoz", "голос", "voice")))

    # Natija klaviaturasi: [📢][📅] / [✏️][📊] / [◀️]
    for lang in LANGS:
        kb = mp._magic_action_keyboard(lang)
        rows = kb.inline_keyboard
        check(f"[{lang}] natija klaviaturasi layouti 2+2+1",
              [len(r) for r in rows] == [2, 2, 1])
        cbs = [b.callback_data for r in rows for b in r]
        check(f"[{lang}] callback tartibi: send, sched, restyle, ps_eval, back",
              cbs == ["mp_send", "mp_sched", "mp_restyle", "ps_eval:magic", "mp_back"], str(cbs))
        texts = [b.text for r in rows for b in r]
        check(f"[{lang}] tugma emojilari 📢 📅 ✏️ 📊 ◀️",
              [t[0] for t in texts] == ["📢", "📅", "✏", "📊", "◀"], str(texts))
        check(f"[{lang}] barcha callback'lar ≤ 64 bayt", all(is_callback_safe(c) for c in cbs))

    uz_texts = [b.text for r in mp._magic_action_keyboard("uz").inline_keyboard for b in r]
    check("UZ yorliqlar topshiriqdagidek",
          uz_texts == ["📢 Kanalga yuborish", "📅 Rejalashtirish",
                       "✏️ Qayta yozish", "📊 Baholash", "◀️ Orqaga"], str(uz_texts))

    rep = magic_post_parity_report()
    check("magic_post i18n pariteti in_sync (yangi kalitlar 3 tilda)", rep["in_sync"] is True, str(rep))
    for key in ("mp_btn_rewrite", "mp_btn_back"):
        check(f"{key} 3 tilda mavjud",
              all(key in MAGIC_POST_I18N[l] for l in LANGS))


# ============================================================================
# TEST 5 — REGRESSIYA: FSM, callback'lar, media routing
# ============================================================================
class _Msg:
    def __init__(self, text=None, voice=None, photo=None):
        self.text = text
        self.caption = None
        self.voice = voice
        self.audio = None
        self.document = None
        self.photo = photo
        self.chat = SimpleNamespace(id=1)
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append({"text": text, "reply_markup": reply_markup})
        return self


class _Query:
    def __init__(self, data):
        self.data = data
        self.from_user = SimpleNamespace(id=42)
        self.message = _Msg()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append({"text": text, "reply_markup": reply_markup})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append({"reply_markup": reply_markup})


def test_regression_fsm_and_routing():
    print("\n== TEST 5: Regressiya — FSM holatlari, mp_back, ovoz/rasm routing ==")

    check("FSM holatlari o'zgarmagan (430-433)",
          (mp.MAGIC_INPUT, mp.MAGIC_STYLE_SELECT, mp.MAGIC_RESULT, mp.MAGIC_SEND_CHOOSE)
          == (430, 431, 432, 433))
    check("MP_BACK callback = 'mp_back' (^mp_ stale qo'riqchisi ostida)",
          mp.MP_BACK == "mp_back" and mp.MP_BACK.startswith("mp_"))

    # ◀️ Orqaga — sessiya tozalanadi, Kontent yaratish submenyusi chiqadi, END.
    ctx = SimpleNamespace(user_data={"lang": "uz", "magic_raw_text": "x",
                                     "magic_post_text": "y"}, bot=None)
    q = _Query("mp_back")
    state = run(mp.magic_back_callback(SimpleNamespace(callback_query=q, message=None), ctx))
    from telegram.ext import ConversationHandler
    check("mp_back → ConversationHandler.END", state == ConversationHandler.END)
    check("mp_back: query.answer() chaqirildi", len(q.answers) >= 1)
    check("mp_back: magic_* kalitlari tozalandi",
          not any(k.startswith("magic_") for k in ctx.user_data))
    check("mp_back: til saqlangan", ctx.user_data.get("lang") == "uz")
    check("mp_back: Kontent yaratish submenyusi yuborildi",
          q.message.replies and q.message.replies[0]["reply_markup"] is not None
          and "Kontent" in q.message.replies[0]["text"], str(q.message.replies[:1]))

    # Ovoz Magic Post ichida → voice oqimi (voice_message_received) chaqiriladi.
    routed = []

    async def fake_voice(update, context):
        routed.append("voice")
        return 901

    async def fake_image(update, context):
        routed.append("image")
        return 902

    import handlers.voice_post as vp
    import handlers.image_post as ip
    ctx2 = SimpleNamespace(user_data={"lang": "uz", "magic_raw_text": "old"}, bot=None)
    with patch.object(vp, "voice_message_received", new=fake_voice), \
            patch.object(ip, "image_photo_received", new=fake_image):
        m_voice = _Msg(voice=SimpleNamespace(file_id="v1"))
        st_v = run(mp.magic_text_received(SimpleNamespace(message=m_voice), ctx2))
        m_img = _Msg(photo=[SimpleNamespace(file_id="p1")])
        st_i = run(mp.magic_text_received(SimpleNamespace(message=m_img), ctx2))
    check("ovoz → Voice → Post oqimiga uzatildi", routed[:1] == ["voice"] and st_v == 901)
    check("rasm → Rasm → Post oqimiga uzatildi", routed[1:2] == ["image"] and st_i == 902)
    check("routingda eski magic_raw_text tozalandi", "magic_raw_text" not in ctx2.user_data)

    # Sticker/boshqa media — avvalgidek MAGIC_INPUT + hint.
    m_other = _Msg()
    st_o = run(mp.magic_text_received(SimpleNamespace(message=m_other),
                                      SimpleNamespace(user_data={"lang": "uz"}, bot=None)))
    check("boshqa media: MAGIC_INPUT'da qoladi va hint chiqadi",
          st_o == mp.MAGIC_INPUT and len(m_other.replies) == 1)

    # Handler ro'yxatida mp_back MAGIC_RESULT holatida ro'yxatdan o'tgan.
    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("handlers/__init__.py: mp_back callback MAGIC_RESULT'da ro'yxatda",
          'pattern=r"^mp_back$"' in src and "magic_back_callback" in src)


# ============================================================================
def main():
    print("=" * 62)
    print(" ✨ 2-BOSQICH — AI PROMPT VA MAGIC POST SIFATI VALIDATSIYASI")
    print("=" * 62)
    test_system_prompts_engineering()
    test_quality_validator()
    test_generate_retry_on_thin_answer()
    test_ui_compactness_and_i18n()
    test_regression_fsm_and_routing()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] AI PROMPT SIFATI TESTIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" AI PROMPT SIFATI TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
