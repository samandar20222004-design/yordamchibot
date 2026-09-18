#!/usr/bin/env python3
"""🧭 UI/UX STANDARTLARI — FAZA 17, 18, 19, 26, 30 QABUL TESTI.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1 — ASOSIY REPLY MENYU QAT'IY 3 QATOR / 6 TUGMA (uz/ru/en):
           [✨ Kontent yaratish] [📢 Kanallarim] / [📅 Rejalashtirilgan]
           [📊 Statistika] / [💎 PRO] [⚙️ Sozlamalar]. 4-qator YO'Q;
           admin variantida faqat oxirga [⚙️ Admin Panel] qo'shiladi va
           birinchi 3 qator AYNAN saqlanadi.

  TEST 2 — KANONIK NAVIGATSIYA STANDARTI (FAZA 17):
           ◀️/⬅️ Orqaga = parent oyna; ❌ Bekor qilish = FSM to'xtatish;
           🏠/🔙 Asosiy menyu = bosh menyu; ❌ Yopish = vaqtinchalik
           xabarni yopish. Barcha inline/reply klaviaturalarda (3 tilda)
           bir xil vazifali IKKITA tugma yo'q (find_nav_conflicts == 0)
           va yorliq↔callback semantikasi mos.

  TEST 3 — INLINE DUBLIKATLAR TOZALANGAN (FAZA 18):
           get_cabinet_inline_keyboard va get_settings_hub_keyboard endi
           KANONIK get_settings_profile_keyboard bilan AYNAN bir xil
           panelni qaytaradi (7 tugma, oxirgi qator [❌ Yopish]).

  TEST 4 — CALLBACK REGISTRY VA XAVFSIZLIK (FAZA 19):
           barcha klaviatura callback'lari registry'da; noma'lum/soxta
           (tampered) callback FAIL-CLOSED rad etiladi (show_alert=True,
           xabar o'chirilmaydi/tahrirlanmaydi); 64-bayt limiti buzilgan
           qiymat ham rad etiladi; registry'da bor, lekin eskirgan tugma
           muloyim toast oladi.

  TEST 5 — I18N 100% PARITET VA HARDCODED TOZALIGI (FAZA 26):
           handlers/admin.py va handlers/channels.py da foydalanuvchi
           ko'radigan QOTIRILGAN o'zbekcha satrlar YO'Q (AST-skaner:
           docstring/logger/texnik tokenlar bundan mustasno);
           translations/admin_panel.py UZ↔RU↔EN in_sync=True;
           channels_queue/settings_stats/asosiy lug'at pariteti buzilmagan;
           admin matnlari 3 tilda haqiqatan farqli va formatlanadi.

  TEST 6 — REGRESSIYA: uz chiqishlari migratsiyagacha bo'lgan matnlar
           bilan bir xil (dashboard/stats/dbcache/posts oltin substringlari),
           CHANNEL_LIMIT_MSG/PRO_UPGRADE_KEYBOARD orqaga mosligi,
           parse_channel_target xatolari 3 tilda.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/ui_ux_and_navigation_standards_test.py
"""
import ast
import asyncio
import os
import re
import sys
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:UIUX_NAV_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10002")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0

LANGS = ("uz", "ru", "en")


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def header(letter, title):
    print(f"\n== TEST {letter}: {title} ==")


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import keyboards.callback_data as CB                        # noqa: E402
import keyboards.default as KD                              # noqa: E402
import keyboards.inline as KI                               # noqa: E402
import keyboards.nav as NAV                                 # noqa: E402
import handlers as H                                        # noqa: E402
import handlers.admin as HA                                 # noqa: E402
import handlers.channels as HC                              # noqa: E402
import services.rbac_service as RB                          # noqa: E402
from locales.translations import (                          # noqa: E402
    get_text, safe_t, translation_parity_report,
)
from translations import (                                  # noqa: E402
    admin_panel_parity_report, admin_t,
    channels_queue_parity_report, channels_queue_t,
    settings_stats_parity_report, settings_stats_t,
)

# Asosiy menyu — QAT'IY 6 TUGMA / 3 QATOR (ux_v2 testi bilan bir xil speks).
EXPECTED_MAIN = {
    "uz": ("✨ Kontent yaratish", "📢 Kanallarim",
           "📅 Rejalashtirilgan", "📊 Statistika",
           "💎 PRO", "⚙️ Sozlamalar"),
    "ru": ("✨ Создать контент", "📢 Мои каналы",
           "📅 Запланированные", "📊 Статистика",
           "💎 PRO", "⚙️ Настройки"),
    "en": ("✨ Create content", "📢 My channels",
           "📅 Scheduled", "📊 Statistics",
           "💎 PRO", "⚙️ Settings"),
}


def kb_rows_reply(markup):
    return [[b.text if hasattr(b, "text") else str(b) for b in row]
            for row in markup.keyboard]


def kb_flat_inline(markup):
    return [(b.text, b.callback_data)
            for row in markup.inline_keyboard for b in row]


def render_all_keyboards(lang):
    """(inline + default) modullaridagi barcha chaqiriladigan klaviaturalar."""
    import inspect

    out = []
    for mod in (KI, KD):
        for name, fn in sorted(vars(mod).items()):
            if not callable(fn) or name.startswith("_"):
                continue
            try:
                sig = inspect.signature(fn)
            except (ValueError, TypeError):
                continue
            kwargs, ok = {}, True
            for pname, p in sig.parameters.items():
                if p.default is inspect.Parameter.empty:
                    ok = False
                    break
                kwargs[pname] = lang if pname == "lang" else p.default
            if not ok:
                continue
            try:
                res = fn(**kwargs)
            except Exception:
                continue
            if hasattr(res, "inline_keyboard") or hasattr(res, "keyboard"):
                out.append((f"{mod.__name__}.{name}", res))
    return out


# ============================================================================
# TEST 1 — ASOSIY REPLY MENYU: QAT'IY 3 QATOR / 6 TUGMA
# ============================================================================
def test_1_main_reply_menu_strict_6_buttons():
    header("1", "🏠 Asosiy Reply menyu — QAT'IY 3 qator / 6 tugma (4-qator TAQIQLANADI)")
    for lang in LANGS:
        expected = EXPECTED_MAIN[lang]
        kb = KD.get_main_keyboard(False, lang=lang)
        rows = kb_rows_reply(kb)
        flat = [t for row in rows for t in row]
        check(f"[{lang}] aynan 6 tugma", len(flat) == 6, str(flat))
        check(f"[{lang}] aynan 3 qator × 2 tugma",
              rows == [list(expected[0:2]), list(expected[2:4]), list(expected[4:6])],
              str(rows))
        # Admin varianti: birinchi 3 qator AYNAN saqlanadi + faqat Admin Panel.
        kb_adm = KD.get_main_keyboard(True, lang=lang)
        rows_adm = kb_rows_reply(kb_adm)
        check(f"[{lang}] admin: 6+1 (faqat Admin Panel qatori qo'shiladi)",
              rows_adm[:3] == rows and len(rows_adm) == 4
              and rows_adm[3] == [KD.BTN_ADMIN_PANEL], str(rows_adm))
    # Deprecated parametrlar ham 6-tugma standartini buzmaydi.
    kb_dep = KD.get_main_keyboard(False, lang="uz", include_image_post=True,
                                  include_post_score=True)
    check("deprecated flaglar 6 tugmani o'zgartirmaydi",
          len([t for r in kb_rows_reply(kb_dep) for t in r]) == 6)
    # get_refreshed_main_keyboard ham bir xil standartda.
    kb_ref = KD.get_refreshed_main_keyboard("ru", is_admin=False)
    check("refreshed menyu (ru) — bir xil 6 tugma",
          [t for r in kb_rows_reply(kb_ref) for t in r] == list(EXPECTED_MAIN["ru"]))


# ============================================================================
# TEST 2 — KANONIK NAVIGATSIYA STANDARTI (FAZA 17)
# ============================================================================
def test_2_canonical_navigation():
    header("2", "🧭 Kanonik navigatsiya: Orqaga/Bekor/Asosiy menyu/Yopish — yagona ma'no")
    # 2a) Semantik yorliqlar i18n'dan va 3 tilda mavjud.
    sem_keys = {
        NAV.NAV_SEMANTIC_BACK: "btn_back",
        NAV.NAV_SEMANTIC_CANCEL: "btn_cancel",
        NAV.NAV_SEMANTIC_HOME: "btn_main_menu",
        NAV.NAV_SEMANTIC_CLOSE: "cab_close",
    }
    for sem, key in sem_keys.items():
        labels = [NAV.nav_label(sem, lang) for lang in LANGS]
        check(f"{sem}: yorliq 3 tilda bo'sh emas", all(labels), str(labels))
        check(f"{sem}: yorliq i18n kaliti ({key}) bilan bir xil",
              labels == [get_text(key, lang) for lang in LANGS])
    check("back yorlig'i 'Orqaga' ma'nosida (uz)",
          "Orqaga" in NAV.nav_label(NAV.NAV_SEMANTIC_BACK, "uz"))
    check("cancel yorlig'i 'Bekor qilish' (uz)",
          NAV.nav_label(NAV.NAV_SEMANTIC_CANCEL, "uz") == "❌ Bekor qilish")
    check("close yorlig'i 'Yopish' (uz)",
          NAV.nav_label(NAV.NAV_SEMANTIC_CLOSE, "uz") == "❌ Yopish")
    check("home yorlig'i 'Asosiy menyu' (uz)",
          "Asosiy menyu" in NAV.nav_label(NAV.NAV_SEMANTIC_HOME, "uz"))

    # 2b) nav_button quruvchisi: callback'siz back/cancel → ValueError (fail-fast).
    b = NAV.nav_button("close")
    check("nav_button('close') standart callback bilan (close_msg)",
          b.callback_data == "close_msg" and b.text == "❌ Yopish", str(b))
    try:
        NAV.nav_button("back")
        check("nav_button('back') callbacksiz → ValueError", False)
    except ValueError:
        check("nav_button('back') callbacksiz → ValueError", True)

    # 2c) nav_row dublikat semantikani RAD ETADI (qoidabuzar klaviatura qurilmaydi).
    try:
        NAV.nav_row(("back", "stgs_hub"), ("back", "adm_back"))
        check("nav_row: dublikat semantika → ValueError", False)
    except ValueError:
        check("nav_row: dublikat semantika → ValueError", True)

    # 2d) Yorliq klassifikatori 3 tilda ishlaydi.
    cls_cases = [
        ("⬅️ Orqaga", NAV.NAV_SEMANTIC_BACK),
        ("◀️ Orqaga", NAV.NAV_SEMANTIC_BACK),
        ("⬅️ Назад", NAV.NAV_SEMANTIC_BACK),
        ("⬅️ Back", NAV.NAV_SEMANTIC_BACK),
        ("❌ Bekor qilish", NAV.NAV_SEMANTIC_CANCEL),
        ("❌ Отмена", NAV.NAV_SEMANTIC_CANCEL),
        ("❌ Cancel", NAV.NAV_SEMANTIC_CANCEL),
        ("🔙 Asosiy menyu", NAV.NAV_SEMANTIC_HOME),
        ("🔙 Главное меню", NAV.NAV_SEMANTIC_HOME),
        ("🔙 Main menu", NAV.NAV_SEMANTIC_HOME),
        ("❌ Yopish", NAV.NAV_SEMANTIC_CLOSE),
        ("❌ Закрыть", NAV.NAV_SEMANTIC_CLOSE),
        ("❌ Close", NAV.NAV_SEMANTIC_CLOSE),
        ("📊 Statistika", None),   # kontent tugmasi — navigatsiya EMAS
    ]
    for label, expected in cls_cases:
        got = NAV.classify_nav_label(label)
        check(f"classify({label!r}) = {expected!r}", got == expected, str(got))

    # 2e) BUTUNLOY KLAVIATURA PARKI: bir xil vazifali ikkita tugma YO'Q va
    #     yorliq↔callback semantikasi mos (3 tilda).
    conflicts_total = 0
    kb_total = 0
    for lang in LANGS:
        for where, markup in render_all_keyboards(lang):
            kb_total += 1
            probs = NAV.find_nav_conflicts(markup, f"{where}[{lang}]")
            if probs:
                conflicts_total += len(probs)
                for p in probs[:3]:
                    print("      CONFLICT:", p)
    check(f"barcha klaviaturalar ({kb_total} render) — 0 navigatsiya konflikti",
          conflicts_total == 0, f"{conflicts_total} ta konflikt")

    # 2f) Kanonik callback semantikasi registry'da (FAZA 19 bilan bitta joyda).
    sem_map_cases = [
        ("adm_back", NAV.NAV_SEMANTIC_BACK),
        ("stgs_hub", NAV.NAV_SEMANTIC_BACK),
        ("ch_back", NAV.NAV_SEMANTIC_BACK),
        ("ai_back_to_menu", NAV.NAV_SEMANTIC_BACK),
        ("ai_back_to_content", NAV.NAV_SEMANTIC_BACK),
        ("help:guide", NAV.NAV_SEMANTIC_BACK),
        ("adm_cancel", NAV.NAV_SEMANTIC_CANCEL),
        ("mnp_cancel", NAV.NAV_SEMANTIC_CANCEL),
        ("ai_close", NAV.NAV_SEMANTIC_CANCEL),
        ("src_cancel", NAV.NAV_SEMANTIC_CANCEL),
        ("studio_close", NAV.NAV_SEMANTIC_HOME),
        ("cc_menu", NAV.NAV_SEMANTIC_HOME),
        ("close_msg", NAV.NAV_SEMANTIC_CLOSE),
        ("stgs_back", NAV.NAV_SEMANTIC_CLOSE),
        ("close_cabinet", NAV.NAV_SEMANTIC_CLOSE),
        ("adp:channel:back", NAV.NAV_SEMANTIC_BACK),   # dinamik prefiks qoidasi
        ("adp:reply:cancel", NAV.NAV_SEMANTIC_CANCEL),
        ("stgs_lang", None),                            # kontent — nav emas
    ]
    for data, expected in sem_map_cases:
        got = CB.callback_semantic(data)
        check(f"semantic({data!r}) = {expected!r}", got == expected, str(got))

    # 2g) AI Studio home tugmasi endi KANONIK yorliqda (plan keyboard bilan bir xil).
    for lang in LANGS:
        # {callback → yorliq} xaritasi (kb_flat_inline (text, cb) juftligini beradi).
        studio_cbs = {c: t for t, c in kb_flat_inline(KI.get_ai_studio_keyboard(lang))}
        plan_cbs = {c: t for t, c in kb_flat_inline(KI.get_ai_studio_plan_keyboard(lang))}
        check(f"[{lang}] studio_close yorlig'i = kanonik btn_main_menu",
              studio_cbs.get("studio_close") == get_text("btn_main_menu", lang),
              str(studio_cbs.get("studio_close")))
        check(f"[{lang}] studio va plan klaviaturalarida home yorlig'i BIR XIL",
              studio_cbs.get("studio_close") == plan_cbs.get("studio_close"))


# ============================================================================
# TEST 3 — INLINE DUBLIKATLAR TOZALANGAN (FAZA 18)
# ============================================================================
def test_3_inline_duplicates_removed():
    header("3", "🧹 FAZA 18: cabinet/hub klaviaturalari KANONIK profile'ga yo'naltirilgan")
    for lang in LANGS:
        canon = kb_flat_inline(KI.get_settings_profile_keyboard(lang))
        cab = kb_flat_inline(KI.get_cabinet_inline_keyboard(lang))
        hub = kb_flat_inline(KI.get_settings_hub_keyboard(lang))
        hub_legacy = kb_flat_inline(KI.get_settings_hub_keyboard(lang, include_legacy=True))
        check(f"[{lang}] get_cabinet_inline_keyboard == kanonik panel", cab == canon)
        check(f"[{lang}] get_settings_hub_keyboard == kanonik panel", hub == canon)
        check(f"[{lang}] include_legacy=True ham dublikat tugma qo'shmaydi",
              hub_legacy == canon)
        # Kanonik panel tuzilishi: 7 tugma, 4 qator, oxirgisi [❌ Yopish](stgs_back).
        rows = KI.get_settings_profile_keyboard(lang).inline_keyboard
        flat = [t for t, _ in canon]
        check(f"[{lang}] panel: 7 tugma / 4 qator", len(flat) == 7 and len(rows) == 4,
              str(rows))
        check(f"[{lang}] panel: oxirgi qator [❌ Yopish] (stgs_back)",
              canon[-1] == (settings_stats_t("ss_btn_close", lang), "stgs_back"),
              str(canon[-1]))
        cbs = [c for _, c in canon]
        check(f"[{lang}] panel: callback'lar tilga bog'liq emas",
              cbs == ["stgs_lang", "stgs_post", "stgs_notif", "stgs_referral",
                      "stgs_pay", "help_support", "stgs_back"], str(cbs))
    # Eski alias-funksiyalar ham kanonik manbaga tushadi.
    for fn in (KI.get_stgs_rewards_keyboard, KI.get_rewards_keyboard):
        check(f"{fn.__name__} == get_settings_rewards_keyboard",
              kb_flat_inline(fn("uz")) == kb_flat_inline(KI.get_settings_rewards_keyboard("uz")))


# ============================================================================
# TEST 4 — CALLBACK REGISTRY VA TAMPERING (FAZA 19)
# ============================================================================
class _FakeFromUser:
    id = 4242


class _FakeMessage:
    """Tampering holatida xabar O'CHIRILMASLIGI/TAXRIRLANMASLIGI uchun kuzatuvchi."""

    def __init__(self):
        self.deleted = False
        self.edited = []

    async def delete(self):
        self.deleted = True

    async def edit_message_text(self, *a, **k):
        self.edited.append((a, k))

    async def reply_text(self, *a, **k):
        self.edited.append(("reply", a, k))


class _FakeQuery:
    def __init__(self, data):
        self.data = data
        self.from_user = _FakeFromUser()
        self.message = _FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class _FakeUpdate:
    def __init__(self, data):
        self.callback_query = _FakeQuery(data)
        self.effective_user = _FakeFromUser()
        self.message = None


class _FakeContext:
    def __init__(self, lang="uz"):
        self.user_data = {"lang": lang}
        self.bot = None


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_4_callback_registry_and_tampering():
    header("4", "🗝 FAZA 19: callback registry — fail-closed rad etish (tampering)")
    # 4a) Barcha klaviatura callback'lari registry'da (3 tilda render qilingan).
    unregistered = set()
    seen = set()
    for lang in LANGS:
        for _where, markup in render_all_keyboards(lang):
            rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", [])
            for row in rows:
                for b in row:
                    cd = getattr(b, "callback_data", None)
                    if cd:
                        seen.add(cd)
                        if not CB.is_registered_callback(cd):
                            unregistered.add(cd)
    check(f"barcha klaviatura callback'lari ({len(seen)} ta) registry'da",
          not unregistered, str(sorted(unregistered)))

    # 4b) CANONICAL_PREFIXES registry bilan qoplangan.
    uncovered = [p for p in CB.CANONICAL_PREFIXES
                 if not CB.is_registered_callback(p + "1")
                 and not CB.is_registered_callback(p)]
    check("CANONICAL_PREFIXES registry'da qoplangan", not uncovered, str(uncovered))

    # 4c) Noma'lum/soxta callback'lar — registered EMAS (fail-closed, 1-qatlam).
    tampered = ["", " ", "totally_fake_cb", "XXXXXXXX", "not_real", "🚀",
                "close_msg\x00", "__proto__", "DROP TABLE users",
                "stgsX_lang", "admx_stats", "../../etc/passwd"]
    for t in tampered:
        check(f"tampered {t[:24]!r} → registered=False",
              not CB.is_registered_callback(t))
    check("64 baytdan uzun cab_* → validate_callback=False",
          not CB.validate_callback("cab_" + "x" * 200))
    check("registry'da bor + <=64 bayt → validate_callback=True",
          CB.validate_callback("stgs_lang"))

    # 4c') IKKI QATLAM: namespace ostida SOXTA payload (masalan
    # "stgs_tgl:notif:evil_key") registry'dan o'tadi, lekin handler darajasida
    # OQ RO'YXAT/RBAC bilan zararsizlantiriladi (fail-closed). Qo'riqchi
    # mantiq manbada mavjudligi qat'iy tekshiriladi.
    check("soxta payload namespace'da registered (2-qatlamga o'tadi)",
          CB.is_registered_callback("stgs_tgl:notif:evil_key"))
    settings_src = (ROOT / "handlers" / "settings.py").read_text(encoding="utf-8")
    check("settings: stgs_tgl OQ RO'YXAT qo'riqchisi joyida (fail-closed)",
          "key not in keys" in settings_src
          and "noma'lum toggle kaliti rad etildi" in settings_src)
    check("settings: noma'lum stgs_* → xavfsiz jim chiqish (crash yo'q)",
          "Noma'lum settings callback — xavfsiz jim chiqish" in settings_src)
    admin_src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("admin: har bir adm_* oqimi server-side RBAC bilan (verify_admin_callback)",
          "verify_admin_callback(update)" in admin_src
          and "from_user.id" in admin_src)

    # 4d) Dispatcher catch-all: TAMPERED callback → show_alert=True rad javobi,
    #     xabar o'chirilmaydi/tahrirlanmaydi, tilga mos i18n matn.
    for lang in LANGS:
        upd = _FakeUpdate("evil_fake_payload")
        _run(H.expired_session_callback(upd, _FakeContext(lang)))
        ans = upd.callback_query.answers
        check(f"[{lang}] tampered: bitta javob, show_alert=True",
              len(ans) == 1 and ans[0][1] is True, str(ans))
        check(f"[{lang}] tampered: javob matni = callback_rejected({lang})",
              ans and ans[0][0] == get_text("callback_rejected", lang), str(ans))
        check(f"[{lang}] tampered: xabar o'chirilmadi/tahrirlanmadi",
              not upd.callback_query.message.deleted
              and not upd.callback_query.message.edited)

    # 4e) Registry'da BOR, lekin eskirgan (stale) tugma → muloyim toast (alert yo'q).
    upd = _FakeUpdate("stgs_lang")
    _run(H.expired_session_callback(upd, _FakeContext("uz")))
    ans = upd.callback_query.answers
    check("stale (registered): toast show_alert=False",
          len(ans) == 1 and ans[0][1] is False, str(ans))
    check("stale (registered): matn = sys_stale_button",
          ans and ans[0][0] == get_text("sys_stale_button", "uz"))

    # 4f) callback_rejected kaliti 3 tilda mavjud va farqli.
    rejected = [get_text("callback_rejected", lang) for lang in LANGS]
    check("callback_rejected 3 tilda bo'sh emas va kalit emas",
          all(r and r != "callback_rejected" for r in rejected), str(rejected))
    check("callback_rejected 3 tilda farqli", len(set(rejected)) == 3, str(rejected))

    # 4g) Registry hisoboti — kanonik struktura.
    rep = CB.callback_registry_report()
    check("registry report: namespaces/static/prefixes > 0",
          rep["namespaces"] > 40 and rep["static_callbacks"] > 100
          and rep["canonical_prefixes"] >= 40, str(rep))


# ============================================================================
# TEST 5 — HARDCODED TOZALIGI + I18N 100% PARITET (FAZA 26)
# ============================================================================
UZ_WORD_RE = re.compile(
    r"(?i)(\bta\b|qil|beril|tizim|foydalanuvchi|kanal|uchun|yoki|bilan|mumkin|kerak|"
    r"ruxsat|topilmadi|yubor|olmadi|xato|reklama|yopil|orqaga|bekor|yakun|kiriting|"
    r"tanlang|sozla|rad\b|javob|yaratil|ochil|yangilan|kutib|cheklov|shaxsiy|jami|"
    r"faol|nofaol|takror|vaqtincha|muvaffaqiyat|amalga|holat|matn|tugma|ro'yxat|"
    r"o'chir|tozal|saqla|boshqar|statistik|homiy|oraliq|postlar|obuna|promo|nishon|"
    r"parametr|harakat|jurnal|sarlavha|kesh|so'rov|kirit|yozing|bosing|kunting)"
)
# i18n kalitlari / FSM nomlari / texnik tokenlar (foydalanuvchiga KO'RINMAYDI).
IDENT_RE = re.compile(r"^[a-z][a-z0-9_:.|=-]*$")
INPUT_TOKEN_ALLOWLIST = {"clear", "-", "yo'q", "yoq", "нет", "no", "none", "reset"}


def _scan_hardcoded(path: Path):
    """Foydalanuvchiga ko'rinadigan qotirilgan o'zbekcha satrlarni topadi.

    Mustasnolar: docstring'lar, logger/l logging chaqiruvi argumentlari,
    i18n kalit identifikatorlari va foydalanuvchi KIRITISH tokenlari.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                docstrings.add(id(node.body[0].value))
    logger_strs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = (f.attr if isinstance(f, ast.Attribute)
                     else (f.id if isinstance(f, ast.Name) else ""))
            base = (f.value.id if isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name) else "")
            if base in ("logger", "logging") or fname in (
                    "debug", "info", "warning", "error", "exception", "critical"):
                for a in list(node.args) + [kw.value for kw in node.keywords]:
                    for sub in ast.walk(a):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            logger_strs.add(id(sub))
    flagged = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings or id(node) in logger_strs:
                continue
            s = node.value.strip()
            if len(s) < 3:
                continue
            if s.lower() in INPUT_TOKEN_ALLOWLIST:
                continue
            if IDENT_RE.match(s):
                continue
            if UZ_WORD_RE.search(s):
                flagged.append((node.lineno, s[:90]))
    return flagged


def test_5_i18n_parity_and_hardcode_cleanup():
    header("5", "🌐 FAZA 26: hardcoded tozaligi + UZ/RU/EN 100% paritet")
    # 5a) handlers/admin.py va handlers/channels.py — qotirilgan satrlar YO'Q.
    for rel in ("handlers/admin.py", "handlers/channels.py"):
        flagged = _scan_hardcoded(ROOT / rel)
        check(f"{rel}: foydalanuvchiga ko'rinadigan hardcoded satr YO'Q",
              not flagged, str(flagged[:6]))

    # 5b) Admin panel i18n lug'ati — 3 tilda 100% paritet.
    rep = admin_panel_parity_report()
    check("admin_panel: in_sync=True (uz↔ru↔en)", rep["in_sync"] is True,
          f"missing={rep['missing']} extra={rep['extra']} fmt={rep['format_mismatch']}")
    check("admin_panel: >=200 kalit", rep["keys"] >= 200, str(rep["keys"]))

    # 5c) Mavjud lug'atlar pariteti buzilmagan.
    check("channels_queue: in_sync=True", channels_queue_parity_report()["in_sync"] is True)
    check("settings_stats: in_sync=True", settings_stats_parity_report()["in_sync"] is True)
    main_rep = translation_parity_report()
    check("asosiy lug'at: all_in_sync=True (callback_rejected bilan)",
          main_rep.get("all_in_sync") is True, str({k: v for k, v in main_rep.items()
                                                   if k.endswith("only") or k.endswith("missing")}))

    # 5d) admin_t haqiqatan 3 xil tilni qaytaradi va formatlaydi.
    for key in ("dash_title", "cancelled_toast", "perm_broadcast", "ad_hub_title"):
        vals = [admin_t(key, lang) for lang in LANGS]
        check(f"admin_t({key}) 3 tilda farqli", len(set(vals)) == 3, str(vals))
    gp = [admin_t("gp_granted", lang, user=7, days=30) for lang in LANGS]
    check("admin_t format argumentlari 3 tilda ishlaydi ({user}/{days})",
          all("7" in g and "30" in g for g in gp), str(gp))
    check("admin_t noma'lum kalit → kalitning o'zi (crash yo'q)",
          admin_t("no_such_key_xyz", "ru") == "no_such_key_xyz")

    # 5e) channels_queue yangi kalitlari (advisor/generic) 3 tilda.
    for key in ("cq_advice_pick_title", "cq_advice_unavailable",
                "cq_advice_build_error", "cq_channel_generic_title",
                "cq_channel_generic_name"):
        vals = [channels_queue_t(key, lang) for lang in LANGS]
        check(f"channels_queue_t({key}) 3 tilda farqli",
              len(set(vals)) == 3 and all(vals), str(vals))

    # 5f) RBAC rad javoblari i18n markeri orqali yechiladi.
    resolved = RB._resolve_denied_message("adm:audit_denied", None)
    check("rbac: 'adm:audit_denied' → admin_t matni (uz)",
          resolved == admin_t("audit_denied", "uz"), str(resolved))
    check("rbac: oddiy satr o'zgarmaydi (orqaga moslik)",
          RB._resolve_denied_message("Oddiy xabar", None) == "Oddiy xabar")

    # 5g) ai_btn_close RU endi kanonik «❌ Отмена» (cancel ma'nosi, FAZA 17).
    check("ai_btn_close ru = ❌ Отмена (semantik moslik)",
          get_text("ai_btn_close", "ru") == "❌ Отмена",
          get_text("ai_btn_close", "ru"))


# ============================================================================
# TEST 6 — REGRESSIYA: UZ CHIQISHLARI MIGRATSIYAGACHA BO'LGAN MATNLAR BILAN BIR XIL
# ============================================================================
def test_6_uz_output_regression():
    header("6", "♻️ Regressiya: uz matnlari migratsiyadan oldingi bilan bir xil")
    stats = {"users": 10, "pro_subscribers": 2, "channels": 3, "posts_today": 4,
             "pending_posts": 5, "stars_revenue": 6}
    dash = HA._build_dashboard_text(stats, "uz")
    for frag in ("👑 <b>Admin Boshqaruv Paneli</b>",
                 "👥 Jami foydalanuvchilar: <b>10 ta</b>",
                 "⭐️ PRO obunachilar: <b>2 ta</b>",
                 "📢 Ulangan faol kanallar: <b>3 ta</b>",
                 "📝 Bugun chiqarilgan postlar: <b>4 ta</b>",
                 "⏳ Navbatdagi postlar: <b>5 ta</b>",
                 "⭐️ Telegram Stars tushumi: <b>6 XTR</b>",
                 "Kerakli bo'limni tanlang 👇"):
        check(f"dashboard(uz) fragmenti: {frag[:40]!r}", frag in dash)

    fs = {"users": 1, "channels": 2, "sponsors": 3, "pending": 4,
          "sent": 5, "cancelled": 6, "failed": 7}
    fst = HA._build_full_stats_text(fs, "uz")
    for frag in ("📊 <b>To'liq Statistika:</b>",
                 "📢 Homiy kanallar: <b>3 ta</b>",
                 "🚫 Bekor qilingan: <b>6 ta</b>",
                 "⚠️ Xatolik: <b>7 ta</b>"):
        check(f"full_stats(uz) fragmenti: {frag[:40]!r}", frag in fst)

    st = {"collapsed": True, "cache_enabled": False, "ready": True, "message": "ok",
          "min": 1, "max": 5, "used": 2, "available": 3, "cache_entries": 9}
    dbc = HA._build_dbcache_text(st, "uz")
    for frag in ("🗄️ <b>DB Pool va Kesh holati:</b>",
                 "Pool: <b>✅ ishlayapti</b> (ok)",
                 "Min/Maks: <b>1 / 5</b>",
                 "Yopiq: <b>yo'q</b>",
                 "Kesh: <b>o'chirilgan</b> — <b>9 ta</b> yozuv",
                 "Kesh TTL o'zgarishlarsiz avtomatik eskiradi."):
        check(f"dbcache(uz) fragmenti: {frag[:40]!r}", frag in dbc)
    dbc2 = HA._build_dbcache_text(st, "uz", pool_message=False, cleared=True)
    check("dbcache(cleared) footer: ✅ <b>Kesh tozalandi.</b>",
          "✅ <b>Kesh tozalandi.</b>" in dbc2 and "(ok)" not in dbc2)

    posts_empty = HA._build_admin_posts_text([], "uz")
    check("posts(uz, bo'sh): 'Hozircha hech qanday post mavjud emas.'",
          "📋 <b>Barcha postlar</b>" in posts_empty
          and "Hozircha hech qanday post mavjud emas." in posts_empty)

    # Sponsor boshqaruvi matni — yagona builder (adm_sponsors va del_sponsor).
    sp = HA._build_sponsor_manage_text([], "uz")
    for frag in ("📢 <b>Majburiy obuna (Sponsor kanallar) boshqaruvi:</b>",
                 "Ulangan kanallar soni: <b>0 ta</b>",
                 "<i>Hozircha hech qanday sponsor kanal ulanmagan.</i>",
                 "Kanalni o'chirish uchun tegishli tugmani bosing"):
        check(f"sponsors(uz) fragmenti: {frag[:40]!r}", frag in sp)

    # channels.py orqaga moslik konstantalari.
    check("CHANNEL_LIMIT_MSG uz lug'atdan (PRO mavjud)",
          "PRO" in HC.CHANNEL_LIMIT_MSG
          and HC.CHANNEL_LIMIT_MSG == safe_t("ch_limit_msg", "uz"))
    check("PRO_UPGRADE_KEYBOARD: sub_open callback saqlangan",
          any(b.callback_data == "sub_open"
              for row in HC.PRO_UPGRADE_KEYBOARD.inline_keyboard for b in row))
    check("PRO_UPGRADE_KEYBOARD yorlig'i i18n'dan (ch_pro_btn)",
          HC.PRO_UPGRADE_KEYBOARD.inline_keyboard[0][0].text == safe_t("ch_pro_btn", "uz"))

    # parse_channel_target — xato matnlari 3 tilda (uz default saqlanadi).
    t, err = HC.parse_channel_target("   ")
    check("parse_channel_target(bo'sh): uz xato (default)",
          t is None and err == safe_t("ch_empty_target", "uz"), str(err)[:60])
    _, err_ru = HC.parse_channel_target("https://t.me/joinchat/AAAAAE", "ru")
    check("parse_channel_target(invite, ru): xato RUSCHA",
          err_ru == safe_t("ch_invite_blocked", "ru"), str(err_ru)[:60])
    _, err_en = HC.parse_channel_target("https://t.me/joinchat/AAAAAE", "en")
    check("parse_channel_target(invite, en): xato INGLIZCHA",
          err_en == safe_t("ch_invite_blocked", "en"), str(err_en)[:60])
    t2, e2 = HC.parse_channel_target("@mychannel")
    check("parse_channel_target(@username) — o'zgarmagan", t2 == "@mychannel" and e2 is None)

    # _channel_title fallback endi i18n'da.
    check("_channel_title(bo'sh, uz) = 'Kanal'",
          HC._channel_title((None, "")) == "Kanal")
    check("_channel_title(bo'sh, ru) = 'Канал'",
          HC._channel_title((None, ""), "ru") == "Канал")
    check("_channel_title(bo'sh, en) = 'Channel'",
          HC._channel_title((None, ""), "en") == "Channel")

    # Admin AI sozlamalari matni uz'da avvalgi tuzilishda.
    ai_txt = HA._ai_settings_text("uz")
    check("_ai_settings_text(uz): 7 parametr qatori",
          ai_txt.count("• <b>") == 7 and "0.0–2.0 (0.2 = aniq)" in ai_txt)


# ============================================================================
def main():
    print("=" * 62)
    print(" 🧭 UI/UX STANDARTLARI — FAZA 17/18/19/26 QABUL TESTLARI")
    print("=" * 62)
    test_1_main_reply_menu_strict_6_buttons()
    test_2_canonical_navigation()
    test_3_inline_duplicates_removed()
    test_4_callback_registry_and_tampering()
    test_5_i18n_parity_and_hardcode_cleanup()
    test_6_uz_output_regression()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] UI/UX STANDARTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA UI/UX STANDART TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
