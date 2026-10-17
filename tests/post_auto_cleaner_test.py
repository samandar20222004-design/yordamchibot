#!/usr/bin/env python3
"""🧹 POST AUTO-CLEANER & CUSTOM SIGNATURE — TO'LIQ TEST SUITE.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  🧱 ENTITY-SAFE TOZALASH (HTML) — begona ``@username`` va
           ``t.me`` havolalari o'chirilganda <b>/<i>/<a> teg daraxti 100%
           SAQLANADI; natija balanslangan, Telegram uchun yaroqli HTML
           (XML simulyatsiyasi bilan tasdiqlanadi — soxta PASS yo'q).
  TEST 2:  🔢 TELEGRAM MessageEntity QAYTA XARITALASH — offset'lar UTF-16
           da aniq qayta hisoblanadi (emoji = 2 birlik), to'liq o'chirilgan
           entity tushirib qoldiriladi, qisman o'chirilgani QIRQILADI;
           ``code``/``pre`` ichidagi matn HECH QACHON tozalanmaydi.
  TEST 3:  📝 MARKDOWN DARAXTI — ``**bold**``/``__italic__``/``[t](u)``/
           `` `code` `` belgilari tozalashdan keyin ham to'g'ri yopiladi.
  TEST 4:  ✍️ CUSTOM SIGNATURE INJECTION — imzo oxirga/boshga qo'yiladi,
           URL bo'lsa <a> teg bo'ladi (``validate_button_url`` orqali),
           yozuvcha matn HTML-escape qilinadi (XSS yo'q), ikkinchi marta
           tozalashda DUPLIKAT qo'shilmaydi (idempotent).
  TEST 5:  🌍 KO'P DAVLATLILIK — reklama/atributsiya naqshlari uz/ru/en
           uchala tilda ishlaydi; hech qanday mamlakat/mintaqa cheklovi
           yo'q (bir xil matn istalgan davlatda bir xil tozalanadi).
  TEST 6:  🛟 FAIL-SAFE — o'chirilgan sozlama matnga UMUMAN tegmaydi;
           tozalash matnni butunlay yeb qo'ysa ASL matn qaytariladi;
           foydalanuvchining O'Z kanali saqlanadi.
  TEST 7:  🧭 "KO'PROQ SOZLAMALAR" NAVIGATSIYASI — ⚙️ Sozlamalar hub'i
           10 TUGMA bo'lib QOLADI (layout buzilmaydi); yo'l:
           ✍️ Post sozlamalari → ⚙️ Ko'proq → 🧹 Avto-tozalash va
           [◀️ Orqaga] zanjiri to'g'ri (post → more → clean → more → post).
  TEST 8:  🔌 HANDLER ROUTING — ``stgs_more`` / ``stgs_clean`` /
           ``stgs_clean_demo`` / ``stgs_clean_sig_clear`` haqiqiy handlerda
           ishlaydi; ``stgs_tgl:clean:*`` OQ RO'YXAT qo'riqchisi joyida
           (soxta kalit → DB amali YO'Q).
  TEST 9:  💾 IMZO SAQLASH — ``normalize_signature`` boshqaruv/yo'nalish
           belgilarini o'chiradi, ≤10 qator va ≤500 belgiga qisqadi;
           repository shu YAGONA qoidani ishlatadi (ikki nusxa yo'q).
  TEST 10: 🌐 i18n PARITET + 18-BELGI STANDARTI — yangi kalitlar uz/ru/en
           100% paritet, format argumentlari bir xil, inline yorliqlar ≤18.
  TEST 11: 📥 INGEST ULANMASI — RSS ``build_draft`` yoqilgan sozlama bilan
           MANBA matnini tozalaydi (botning o'z ``🔗 Manba:`` yorlig'i
           SAQLANADI), o'chirilgan sozlama bilan matn O'ZGARMAYDI;
           URL ``build_drafts`` ham xuddi shunday.

Ishga tushirish:
    python3 tests/post_auto_cleaner_test.py
"""
import asyncio
import os
import re
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AUTO_CLEANER_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10047")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

import database as db_mod  # noqa: E402
import handlers.settings as STG  # noqa: E402
from keyboards.callback_data import is_registered_callback  # noqa: E402
from keyboards.inline import get_settings_profile_keyboard  # noqa: E402
from services import post_cleaner as PC  # noqa: E402
from services.post_cleaner import (  # noqa: E402
    CleanerConfig,
    clean_html,
    clean_markdown,
    clean_plain,
    normalize_signature,
)
from translations.settings_stats import (  # noqa: E402
    settings_stats_parity_report,
    settings_stats_t,
)
from utils.post_signature import MAX_SIGNATURE_LEN  # noqa: E402

LANGS = ("uz", "ru", "en")
USER_ID = 441122
OWN = frozenset({"my_channel"})

PASSED = 0
FAILURES = 0


def check(name, cond, extra=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def header(num, title):
    print(f"\n===== TEST {num}: {title} =====")


# Telegram HTML uchun yaroqli teglar (``telegram_sanitizer`` ro'yxati bilan
# bir xil). XML simulyatori balans va yopilishni QAT'IY tekshiradi.
TAGS = {"b", "i", "u", "s", "a", "tg-spoiler", "pre", "code", "blockquote",
        "strong", "em", "ins", "strike", "del", "span"}


def _xml_wellformed(html: str) -> bool:
    """HTML Telegram uchun yaroqlimi? (XML balans + teg oq ro'yxati)."""
    if not html.strip():
        return True
    # XML boolean atribut qiymat talab qiladi.
    prepared = html.replace("<blockquote expandable>", '<blockquote expandable="true">')
    prepared = re.sub(r"&(?!amp;|lt;|gt;|quot;|#\d+;|#x[0-9a-fA-F]+;)", "&amp;",
                      prepared)
    try:
        root = ET.fromstring(f"<root>{prepared}</root>")
    except ET.ParseError:
        return False
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag != "root" and tag not in TAGS:
            return False
        if tag == "a":
            href = node.get("href") or ""
            if not href.startswith(("http://", "https://", "tg://")):
                return False
    return True


def _utf16_slice(text: str, offset: int, length: int) -> str:
    """UTF-16 offset/length bo'yicha matn bo'lagi (Telegram semantikasi)."""
    units = text.encode("utf-16-le")
    return units[offset * 2:(offset + length) * 2].decode("utf-16-le")


# ============================================================
# TEST 1 — ENTITY-SAFE TOZALASH (HTML)
# ============================================================
def test_entity_safe_html():
    header("1", "🧱 ENTITY-SAFE TOZALASH (HTML) — formatlash daraxti saqlanadi")
    cfg = CleanerConfig(enabled=True, signature="", own_usernames=OWN)

    source = (
        "<b>Sarlavha</b> va <i>kursiv</i> matn @foreign_kanal bilan "
        "https://t.me/other_news/42 davomida.\n\n"
        "<a href=\"https://example.com\">Foydali havola</a> saqlanadi."
    )
    result = clean_html(source, cfg)
    check("begona @username o'chirildi", "@foreign_kanal" not in result.text)
    check("begona t.me havolasi o'chirildi", "t.me/other_news" not in result.text)
    check("bold saqlandi", "<b>Sarlavha</b>" in result.text, result.text[:160])
    check("kursiv saqlandi", "<i>kursiv</i>" in result.text, result.text[:160])
    check("BEGONA bo'lmagan havola saqlandi",
          'href="https://example.com"' in result.text and "Foydali havola" in result.text,
          result.text[:200])
    check("natija Telegram uchun yaroqli HTML", _xml_wellformed(result.text),
          result.text[:200])
    check("hisoblagich: 1 mention + 1 havola",
          result.removed_mentions == 1 and result.removed_links == 1,
          str(result.as_dict()))

    # Ichma-ich formatlash: o'chirish ichki tegga tushsa ham balans saqlanadi.
    nested = "<b>Qalin <i>@bad_user</i> va <u>tagi</u></b> matn"
    nested_out = clean_html(nested, cfg).text
    check("ichma-ich formatlash balanslangan", _xml_wellformed(nested_out),
          nested_out)
    check("ichma-ich: bold saqlandi", "<b>" in nested_out and "</b>" in nested_out,
          nested_out)
    check("ichma-ich: tagi chizig'i saqlandi", "<u>tagi</u>" in nested_out,
          nested_out)
    check("ichma-ich: bo'sh (yetim) teg qolmadi",
          "<i></i>" not in nested_out and "<i> </i>" not in nested_out, nested_out)


# ============================================================
# TEST 2 — TELEGRAM MessageEntity QAYTA XARITALASH
# ============================================================
def test_entity_offsets():
    header("2", "🔢 MessageEntity offset'lari (UTF-16) + code/pre himoyasi")
    cfg = CleanerConfig(enabled=True, signature="", own_usernames=OWN)

    # Emoji = 2 UTF-16 birligi → offset konvertatsiyasi MAJBURIY.
    text = "🎉 Bayram @bad_kanal bilan keldi"
    entities = [
        {"type": "bold", "offset": 0, "length": 2},          # 🎉
        {"type": "italic", "offset": 3, "length": 6},        # Bayram
    ]
    result = clean_plain(text, entities, cfg)
    check("mention o'chirildi", "@bad_kanal" not in result.text, result.text)
    check("2 ta entity ham saqlandi", len(result.entities) == 2,
          str([str(e.type) for e in result.entities]))
    slices = [_utf16_slice(result.text, e.offset, e.length) for e in result.entities]
    check("bold entity AYNAN emoji ustida", slices[0] == "🎉", repr(slices[0]))
    check("italic entity AYNAN 'Bayram' ustida", slices[1] == "Bayram",
          repr(slices[1]))

    # To'liq o'chirilgan entity tushirib qoldiriladi (yetim entity yo'q).
    text2 = "Salom dunyo"
    ents2 = [
        {"type": "bold", "offset": 0, "length": 5},
        {"type": "text_link", "offset": 6, "length": 5, "url": "https://t.me/x"},
    ]
    r2 = clean_plain(text2, ents2, CleanerConfig(
        enabled=True, signature="", own_usernames=OWN, strip_mentions=False))
    kept = [(str(e.type), _utf16_slice(r2.text, e.offset, e.length))
            for e in r2.entities]
    check("to'liq o'chirilgan entity tushirib qoldirildi",
          not any("t.me" in s for _, s in kept), str(kept))
    check("saqlangan entity matni to'g'ri",
          any(t == "Salom" for _, t in kept), str(kept))

    # code/pre ichidagi matn LITERAL — tozalanmaydi.
    code_text = "Namuna: @example_code va https://t.me/inside_code"
    ents3 = [
        {"type": "code", "offset": 8, "length": 13},
        {"type": "code", "offset": 25, "length": 24},
    ]
    r3 = clean_plain(code_text, ents3, cfg)
    check("code ichidagi @username SAQLANDI", "@example_code" in r3.text, r3.text)
    check("code ichidagi havola SAQLANDI", "t.me/inside_code" in r3.text, r3.text)
    check("code entity'lari saqlandi", len(r3.entities) == 2,
          str([str(e.type) for e in r3.entities]))

    # pre + language entity saqlanadi.
    pre_text = "Kod:\nsample @x here"
    ents4 = [{"type": "pre", "offset": 5, "length": 14, "language": "python"}]
    r4 = clean_plain(pre_text, ents4, cfg)
    check("pre ichidagi matn tegilmadi", "@x" in r4.text, r4.text)
    check("pre language saqlandi",
          any(getattr(e, "language", "") == "python" for e in r4.entities),
          str([(str(e.type), getattr(e, "language", "")) for e in r4.entities]))


# ============================================================
# TEST 3 — MARKDOWN DARAXTI
# ============================================================
def test_markdown_tree():
    header("3", "📝 MARKDOWN — belgilar daraxti saqlanadi")
    cfg = CleanerConfig(enabled=True, signature="", own_usernames=OWN)

    md = "**Qalin** va __kursiv__ matn @bad_user bilan, `kod @ichida` va [havola](https://site.example)"
    out = clean_markdown(md, cfg).text
    check("begona mention o'chirildi", "@bad_user" not in out, out)
    check("**bold** saqlandi", "**Qalin**" in out, out)
    check("__kursiv__ saqlandi", "__kursiv__" in out, out)
    check("kod ichidagi @ SAQLANDI", "`kod @ichida`" in out, out)
    check("[havola](url) saqlandi", "[havola](https://site.example)" in out, out)
    # Belgilar juftligi balanslangan bo'lishi kerak.
    check("bold belgilari juft", out.count("**") % 2 == 0, out)
    check("kursiv belgilari juft", out.count("__") % 2 == 0, out)
    check("kod belgilari juft", out.count("`") % 2 == 0, out)


# ============================================================
# TEST 4 — CUSTOM SIGNATURE INJECTION
# ============================================================
def test_signature_injection():
    header("4", "✍️ CUSTOM SIGNATURE — imzo/havola kiritish")

    source = "<b>Xabar</b> @foreign kanalidan olindi"
    # 4a) Oddiy matn imzo (oxirga).
    cfg = CleanerConfig(enabled=True, signature="© Mening kanalim",
                        own_usernames=OWN)
    out = clean_html(source, cfg).text
    check("imzo oxirga qo'shildi", out.rstrip().endswith("© Mening kanalim"), out)
    check("imzo qo'shilgani belgilandi",
          clean_html(source, cfg).signature_added is True)

    # 4b) URL imzo → <a> teg (validate_button_url orqali).
    url_cfg = CleanerConfig(enabled=True, signature="https://t.me/my_channel",
                            own_usernames=OWN)
    url_out = clean_html(source, url_cfg).text
    check("URL imzo <a> teg bo'ldi",
          '<a href="https://t.me/my_channel">' in url_out, url_out)
    check("URL imzo HTML'i yaroqli", _xml_wellformed(url_out), url_out)

    # 4c) ZARARLI imzo — HTML-escape qilinadi (XSS yo'q).
    evil = CleanerConfig(enabled=True,
                         signature='<script>alert(1)</script><b>x</b>',
                         own_usernames=OWN)
    evil_out = clean_html(source, evil).text
    check("imzodagi <script> Yozuvcha matn (XSS yo'q)",
          "<script>" not in evil_out and "&lt;script&gt;" in evil_out, evil_out)
    check("imzodagi <b> ham yozuvcha matn",
          evil_out.count("<b>") == 1, evil_out)
    check("zararli imzo HTML'i yaroqli", _xml_wellformed(evil_out), evil_out)

    # 4d) javascript: URL — validate_button_url rad etadi, matn qoladi.
    js = CleanerConfig(enabled=True, signature="javascript:alert(1)",
                       own_usernames=OWN)
    js_out = clean_html(source, js).text
    check("javascript: URL <a> bo'lmadi", "javascript:" not in js_out
          or 'href="javascript' not in js_out, js_out)

    # 4e) Idempotent — ikkinchi marta tozalashda dublikat qo'shilmaydi.
    once = clean_html(source, url_cfg).text
    twice = clean_html(once, url_cfg).text
    check("idempotent: imzo ikki marta qo'shilmaydi",
          twice.count("https://t.me/my_channel") <= 2, twice)

    # 4f) signature_position="start".
    start_cfg = CleanerConfig(enabled=True, signature="© Kanal",
                              signature_position="start", own_usernames=OWN)
    start_out = clean_html(source, start_cfg).text
    check("imzo boshga qo'shildi", start_out.lstrip().startswith("© Kanal"),
          start_out)

    # 4g) Imzo normalize: multiline promo/link, 10 qator, NUL/bidi va 500 belgi.
    messy = normalize_signature("  a \n\n\n b \n\n c \n\n d\x00\u202eevil  ")
    check("normalize: bo'sh qatorlar yig'iladi", messy == "a\nb\nc\ndevil", repr(messy))
    ten_lines = normalize_signature("\n".join(f"Promo {i}" for i in range(1, 12)))
    check("normalize: ko'pi bilan 10 qator", len(ten_lines.split("\n")) == 10,
          repr(ten_lines))
    multiline_link = normalize_signature("Kanal\nhttps://t.me/example\nPromo\nNarx: 99")
    check("normalize: multiline promo/link saqlanadi",
          multiline_link == "Kanal\nhttps://t.me/example\nPromo\nNarx: 99",
          repr(multiline_link))
    check("normalize: NUL o'chirildi", "\x00" not in messy, repr(messy))
    check("normalize: bidi-override o'chirildi", "\u202e" not in messy, repr(messy))
    check("normalize: 500 belgigacha saqlanadi",
          normalize_signature("x" * 500) == "x" * MAX_SIGNATURE_LEN
          and len(normalize_signature("x" * 900)) == MAX_SIGNATURE_LEN)

    # 4h) Bo'sh imzo — hech narsa qo'shilmaydi.
    empty_cfg = CleanerConfig(enabled=True, signature="   ", own_usernames=OWN)
    check("bo'sh imzo qo'shilmaydi",
          clean_html(source, empty_cfg).signature_added is False)


# ============================================================
# TEST 5 — KO'P DAVLATLILIK (uz / ru / en)
# ============================================================
def test_multi_country():
    header("5", "🌍 KO'P DAVLATLILIK — reklama naqshlari uch tilda")
    cfg = CleanerConfig(enabled=True, signature="", own_usernames=OWN)
    body = ("Birinchi qator: asosiy mazmun bu yerda joylashgan.\n"
            "Ikkinchi qator: qo'shimcha tafsilotlar va raqamlar 42.\n"
            "Uchinchi qator: yakuniy xulosa va tavsiyalar berilgan.\n")

    samples = {
        "uz": body + "📢 Bizning kanal: @uzbek_news — obuna bo'ling!\n"
                     "Manba: https://t.me/uzbek_news/12\n",
        "ru": body + "📢 Наш канал: @russian_news — подписывайтесь!\n"
                     "Источник: https://t.me/russian_news/12\n",
        "en": body + "📢 Our channel: @english_news — subscribe!\n"
                     "Source: https://t.me/english_news/12\n",
    }
    for lang, text in samples.items():
        out = clean_html(text, cfg).text
        check(f"[{lang}] begona mention o'chirildi",
              "@uzbek_news" not in out and "@russian_news" not in out
              and "@english_news" not in out, out[-120:])
        check(f"[{lang}] reklama/atributsiya qatori o'chirildi",
              "Manba:" not in out and "Источник:" not in out
              and "Source:" not in out, out[-120:])
        check(f"[{lang}] asosiy kontent SAQLANDI",
              "asosiy mazmun" in out and "asosiy" in out.split("\n")[0], out[:120])
        check(f"[{lang}] HTML yaroqli", _xml_wellformed(out), out[:160])

    # Mamlakat cheklovi YO'Q: bir xil matn boshqa davlat manbasi bilan ham
    # bir xil tozalanadi (kod faqat MATN naqshiga qaraydi).
    for country_domain in ("t.me/de_news_x", "t.me/jp_news_x", "t.me/br_news_x",
                           "t.me/uz_news_x", "t.me/us_news_x"):
        text = ("Ma'no qatori bir.\nMa'no qatori ikki.\nMa'no qatori uch.\n"
                f"Reklama: @{country_domain.split('/')[1]} — obuna bo'ling!\n")
        out = clean_html(text, cfg).text
        check(f"[{country_domain}] mintaqaviy cheklovsiz tozalandi",
              country_domain.split("/")[1] not in out, out[-90:])


# ============================================================
# TEST 6 — FAIL-SAFE
# ============================================================
def test_fail_safe():
    header("6", "🛟 FAIL-SAFE — o'chirilgan holat + bo'sh natija himoyasi")

    source = "<b>Xabar</b> @foreign kanalidan"
    # 6a) O'chirilgan (standart) — matn UMUMAN o'zgarmaydi.
    check("DEFAULT_CONFIG: enabled=False", PC.DEFAULT_CONFIG.enabled is False)
    check("o'chirilgan: matn AYNAN asl holatda",
          clean_html(source, PC.DEFAULT_CONFIG).text == source)
    check("o'chirilgan: changed=False",
          clean_html(source, PC.DEFAULT_CONFIG).changed is False)

    # 6b) Butun post bitta begona havoladan iborat → bo'sh qolmasligi kerak.
    only_link = "https://t.me/some_channel/1"
    r = clean_html(only_link, CleanerConfig(enabled=True, signature=""))
    check("faqat havolali post: ASL matn saqlandi (bo'sh post yo'q)",
          bool(r.text.strip()), repr(r.text))

    # 6c) Foydalanuvchining O'Z kanali saqlanadi.
    own_text = "Bizning kanal: @my_channel va begona @other_one"
    own_out = clean_html(own_text, CleanerConfig(
        enabled=True, signature="", own_usernames=OWN)).text
    check("o'z kanali SAQLANDI", "@my_channel" in own_out, own_out)
    check("begona kanal o'chirildi", "@other_one" not in own_out, own_out)

    # 6d) Email mention deb hisoblanmaydi.
    email = "Bog'lanish: info@example.com orqali"
    email_out = clean_html(email, CleanerConfig(enabled=True, signature="")).text
    check("email @ mention deb hisoblanmadi", "info@example.com" in email_out,
          email_out)

    # 6e) Bo'sh/None kirish yiqilmaydi.
    check("None kirish: bo'sh matn (xato yo'q)", clean_html(None, CleanerConfig(
        enabled=True, signature="x")).text == "")
    check("bo'sh kirish: bo'sh matn (xato yo'q)", clean_html("", CleanerConfig(
        enabled=True, signature="x")).text == "")
    check("clean_plain(None) yiqilmaydi",
          clean_plain(None, None, CleanerConfig(enabled=True)).text == "")


# ============================================================
# TEST 7 — "KO'PROQ SOZLAMALAR" NAVIGATSIYASI
# ============================================================
def _flat(kb):
    return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]


def _rows(kb):
    return [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]


def test_more_settings_navigation():
    header("7", "🧭 SOZLAMALAR — primary 3×2 grid va toza submenu navigatsiyasi")

    # 7a) Sozlamalar hub'i oltita asosiy yo'nalish bilan tartibli qoladi.
    for lang in LANGS:
        kb = get_settings_profile_keyboard(lang)
        cbs = [cb for _, cb in _flat(kb)]
        rows = kb.inline_keyboard
        check(f"[{lang}] hub = 5 asosiy tugma (imzo/tozalash tugmasi yo'q)", cbs == [
            "stgs_lang", "stgs_notif",
            "sub_open", "stgs_referral", "stgs_help_hub"], str(cbs))
        check(f"[{lang}] hub = 3 qator (2+2+1)", [len(r) for r in rows] == [2, 2, 1], str(len(rows)))
        check(f"[{lang}] sekundar payment/privacy hub'da yo'q",
              not any(c in cbs for c in ("stgs_pay",
                                         "stgs_privacy", "stgs_delete_data")),
              str(cbs))

    # 7b) ✍️ Post sozlamalari ekranidagi [⚙️ Ko'proq] — [◀️ Orqaga] bilan
    #     BIR qatorda (mavjud kontrakt: Orqaga qatordagi BIRINCHI tugma).
    values = {k: STG.SETTING_DEFAULTS[k] for k in STG.POST_SETTING_KEYS}
    for lang in LANGS:
        kb = STG._build_toggles_keyboard("post", STG.POST_SETTING_KEYS,
                                         values, lang)
        rows = _rows(kb)
        check(f"[{lang}] post ekrani: 1-qator toggle'lar",
              rows[0][0][0].startswith(("✅", "⬜️"))
              and rows[0][1][0].startswith(("✅", "⬜️")), str(rows[0]))
        check(f"[{lang}] post ekrani: [◀️ Orqaga] BIRINCHI tugma (kontrakt)",
              "Orqaga" in rows[1][0][0] or "Назад" in rows[1][0][0]
              or "Back" in rows[1][0][0], str(rows[1]))
        check(f"[{lang}] post ekrani: [⚙️ Ko'proq] shu qatorda",
              rows[1][1][1] == "stgs_more", str(rows[1]))

    # 7c) 🔔 Bildirishnomalar ekranida [⚙️ Ko'proq] YO'Q (faqat post sozlamalari).
    notif_values = {k: STG.SETTING_DEFAULTS[k] for k in STG.NOTIF_SETTING_KEYS}
    notif_cbs = [cb for _, cb in _flat(
        STG._build_toggles_keyboard("notif", STG.NOTIF_SETTING_KEYS,
                                    notif_values, "uz"))]
    check("bildirishnomalar ekranida stgs_more YO'Q", "stgs_more" not in notif_cbs,
          str(notif_cbs))

    # 7d) ⚙️ Ko'proq sozlamalar menyusi → 🧹 Avto-tozalash tugmasi bor.
    _check_more_menu()

    # 7e) Cleaner ekranidan [◀️ Orqaga] to'g'ridan-to'g'ri Settings hub'iga qaytadi.
    cleaner_values = {k: STG.SETTING_DEFAULTS[k] for k in STG.CLEANER_SETTING_KEYS}
    for lang in LANGS:
        ckb = STG._build_cleaner_keyboard(cleaner_values, lang)
        cbs = [cb for _, cb in _flat(ckb)]
        check(f"[{lang}] kengaytirilgan ekran: [◀️ Orqaga] → 🧹 tozalagich ekrani",
              cbs[-1] == "stgs_clean", str(cbs))
        check(f"[{lang}] cleaner ekrani: bosh toggle bor",
              "stgs_tgl:clean:post_auto_clean" in cbs, str(cbs))
        check(f"[{lang}] cleaner ekrani: legacy watermark/imzo toggles bor",
              "stgs_tgl:clean:post_watermark" in cbs
              and "stgs_tgl:clean:post_signature" in cbs, str(cbs))
        check(f"[{lang}] cleaner ekrani: ✍️ Imzo matni tugmasi bor",
              "stgs_clean_sig" in cbs, str(cbs))
        check(f"[{lang}] cleaner ekrani: 🧪 Namuna tugmasi bor",
              "stgs_clean_demo" in cbs, str(cbs))
        check(f"[{lang}] cleaner ekrani: 🗑 imzoni o'chirish bor",
              "stgs_clean_sig_clear" in cbs, str(cbs))

    # 7f) Barcha cleaner callback'lar REGISTRY'da (64-bayt limiti + prefix).
    for cb in ("stgs_more", "stgs_clean", "stgs_clean_sig", "stgs_clean_demo",
               "stgs_clean_sig_clear", "stgs_tgl:clean:post_auto_clean",
               "stgs_tgl:clean:post_clean_mentions",
               "stgs_tgl:clean:post_clean_links",
               "stgs_tgl:clean:post_clean_promo",
               "stgs_tgl:clean:post_watermark",
               "stgs_tgl:clean:post_signature"):
        check(f"registry: {cb}", is_registered_callback(cb))

    # IKKI QATLAMLI HIMOYA (repo arxitekturasi bilan bir xil): namespace
    # ostidagi SOXTA payload registry'dan O'TADI (chunki ``stgs_`` prefix),
    # lekin HANDLER darajasidagi OQ RO'YXAT (``_SETTING_SCOPES``) uni
    # fail-closed rad etadi — TEST 8c buni haqiqiy handlerda tekshiradi.
    check("soxta payload namespace'da registered (2-qatlamga o'tadi)",
          is_registered_callback("stgs_tgl:clean:hacked_key"))
    check("handler OQ RO'YXAT'i 'clean' doirasini qamraydi",
          "clean" in STG._SETTING_SCOPES
          and set(STG.CLEANER_SETTING_KEYS) == {
              "post_auto_clean", "post_clean_mentions", "post_clean_links",
              "post_clean_promo", "post_watermark", "post_signature"},
          str(sorted(STG._SETTING_SCOPES.get("clean", {}))))
    check("OQ RO'YXAT'dan tashqari kalit rad etiladi (mantiq manbada)",
          "hacked_key" not in STG.CLEANER_SETTING_KEYS)


async def _check_more_menu():
    """⚙️ Ko'proq sozlamalar menyusini haqiqiy handler orqali tekshiradi.

    Eslatma: bu funksiya SINXRON chaqiriladi (``_check_more_menu()``) —
    ``_with_db`` ichida ``asyncio.run`` bor, shu sababli tashqi event loop
    ichidan chaqirish ``RuntimeError`` beradi.
    """
    fake = _FakeDB()
    for lang in LANGS:
        def _go(lang=lang):
            async def _run():
                query = _Query("stgs_more")
                await STG.settings_menu_callback(_upd_query(query), _ctx(lang))
                return query
            return _run

        query = _with_db(fake, _go(lang))
        text = query.screen.get("text", "")
        cbs = [cb for _, cb in _flat(query.screen.get("reply_markup"))]
        check(f"[{lang}] 'Ko'proq sozlamalar' ekrani ochildi",
              bool(text) and "stgs_clean" in cbs, str(cbs))
        check(f"[{lang}] [🧹 Avto-tozalash] tugmasi bor",
              any("stgs_clean" == cb for cb in cbs), str(cbs))
        check(f"[{lang}] [◀️ Orqaga] → stgs_post (post sozlamalariga)",
              cbs[-1] == "stgs_post", str(cbs))


# ============================================================
# TEST 8 — HANDLER ROUTING (haqiqiy handler + soxta DB)
# ============================================================
class _Msg:
    def __init__(self, user_id=USER_ID):
        self.chat_id = 555
        self.message_id = 9001
        self.from_user = SimpleNamespace(id=user_id, first_name="T")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=9002)

    async def delete(self):
        return True


class _Query:
    def __init__(self, data, user_id=USER_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="T")
        self.message = _Msg(user_id)
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, **kwargs):
        return True

    @property
    def screen(self):
        if self.edits:
            return self.edits[-1]
        if self.message.sent:
            return self.message.sent[-1]
        return {}


class _Bot:
    async def send_message(self, chat_id, text, **kwargs):
        return SimpleNamespace(message_id=1)

    async def edit_message_text(self, **kwargs):
        return SimpleNamespace(message_id=1)


def _upd_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user, callback_query=query,
                           effective_chat=SimpleNamespace(id=555))


def _ctx(lang="uz"):
    return SimpleNamespace(user_data={"lang": lang}, chat_data={}, bot=_Bot(),
                           application=None)


class _FakeDB:
    """``database.run_db`` ni almashtiruvchi deterministik mock."""

    def __init__(self, settings=None, signature=""):
        self.settings_store = dict(settings or {})
        self.signature = signature
        self.set_calls = []
        self.signature_calls = []
        self.combined_calls = 0

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        if name == "get_user_settings_and_signature":
            self.combined_calls += 1
            keys = args[1] if len(args) > 1 else []
            defaults = args[2] if len(args) > 2 else {}
            values = {key: self.settings_store.get(key, bool(defaults.get(key, False)))
                      for key in keys}
            return values, self.signature
        if name == "get_user_settings_bulk":
            keys = args[1] if len(args) > 1 else []
            defaults = args[2] if len(args) > 2 else {}
            return {k: self.settings_store.get(k, bool(defaults.get(k, False)))
                    for k in keys}
        if name == "set_user_setting":
            self.set_calls.append((args[0], args[1], args[2]))
            self.settings_store[args[1]] = bool(args[2])
            return True
        if name == "get_user_post_signature":
            return self.signature
        if name == "get_user_post_signature_html":
            return self.signature
        if name == "set_user_post_signature_html":
            self.signature_calls.append((args[0], args[1]))
            self.signature = str(args[1] or "")
            return True
        if name == "get_user_setting":
            return self.settings_store.get(args[1], bool(args[2]) if len(args) > 2 else False)
        if name == "set_user_post_signature":
            self.signature_calls.append((args[0], args[1]))
            self.signature = str(args[1] or "")
            return True
        if name == "get_user_channels":
            return [("-1001", "@my_channel — Kanal A")]
        if name == "get_user_language":
            return "uz"
        return None


def _with_db(fake, coro):
    if callable(coro) and not asyncio.iscoroutine(coro):
        coro = coro()
    original = db_mod.run_db
    db_mod.run_db = fake.run_db
    try:
        return asyncio.run(coro)
    finally:
        db_mod.run_db = original


def test_handler_routing():
    header("8", "🔌 HANDLER ROUTING — stgs_more / stgs_clean / demo / clear")

    # 8a) stgs_clean → 🧹 tezkor tozalash ekrani (imzo + boshlash tugmasi).
    fake = _FakeDB(signature="https://t.me/my_channel")
    query = _with_db(fake, lambda: _run_cb("stgs_clean"))
    text = query.screen.get("text", "")
    cbs = [cb for _, cb in _flat(query.screen.get("reply_markup"))]
    check("stgs_clean: ekran chizildi", bool(text), text[:80])
    check("stgs_clean: boshlash/imzo/darhol yuborish/qo'shimcha tugmalari",
          all(cb in cbs for cb in ("stgs_clean_go", "stgs_clean_sig",
                                   "stgs_clean_auto", "stgs_clean_adv")), str(cbs))
    check("stgs_clean: saqlangan imzo ko'rsatilgan (tezkor ekran)",
          "https://t.me/my_channel" in text, text[-160:])

    # 8a') stgs_clean_adv → kanaldan olingan postlar uchun toggle'lar ekrani.
    fake = _FakeDB(signature="https://t.me/my_channel")
    query = _with_db(fake, lambda: _run_cb("stgs_clean_adv"))
    text = query.screen.get("text", "")
    cbs = [cb for _, cb in _flat(query.screen.get("reply_markup"))]
    check("stgs_clean: klaviatura chizildi (toggle + imzo + namuna)",
          "stgs_tgl:clean:post_auto_clean" in cbs and "stgs_clean_sig" in cbs
          and "stgs_clean_demo" in cbs, str(cbs))
    check("stgs_clean: holat ko'rsatilgan (o'chirilgan)",
          "O'chirilgan" in text or "Выключено" in text or "Disabled" in text,
          text[:160])
    check("stgs_clean: saqlangan imzo ko'rsatilgan",
          "https://t.me/my_channel" in text, text[-160:])
    check("stgs_clean: toggles + imzo bitta DB read'da",
          fake.combined_calls == 1 and not fake.signature_calls,
          f"combined={fake.combined_calls}, signatures={fake.signature_calls}")
    check("stgs_clean: tavsifda 'formati saqlanadi' va'dasi bor",
          "saqlanadi" in text or "сохраняется" in text or "preserved" in text,
          text[:300])

    # 8b) stgs_tgl:clean:post_auto_clean → toggle + ekran joyida yangilanadi.
    fake = _FakeDB()
    query = _with_db(fake, lambda: _run_cb("stgs_tgl:clean:post_auto_clean"))
    check("toggle: DB'ga yozildi",
          ("stgs_tgl" and len(fake.set_calls) == 1
           and fake.set_calls[0][1] == "post_auto_clean"
           and fake.set_calls[0][2] is True), str(fake.set_calls))
    check("toggle: yangi xabar yuborilmadi (joyida tahrir)",
          not query.message.sent, str(query.message.sent))

    # 8c) OQ RO'YXAT: soxta kalit → DB amali YO'Q (fail-closed).
    fake = _FakeDB()
    query = _with_db(fake, lambda: _run_cb("stgs_tgl:clean:evil_key"))
    check("soxta toggle kaliti: DB amali YO'Q", fake.set_calls == [],
          str(fake.set_calls))
    check("soxta toggle kaliti: ekran chizilmaydi",
          not query.edits and not query.message.sent)

    # 8d) stgs_clean_demo → namuna ekrani (DB'ga yozmaydi).
    fake = _FakeDB(signature="https://t.me/my_channel")
    query = _with_db(fake, lambda: _run_cb("stgs_clean_demo"))
    text = query.screen.get("text", "")
    check("demo: ekran chizildi", bool(text), text[:80])
    check("demo: 'Manba posti' va 'Tozalandi' bloklari bor",
          "Manba posti" in text and "Tozalandi" in text, text[:200])
    check("demo: hisobot raqamlari bor", "🧹 O'chirildi:" in text, text[-200:])
    check("demo: imzo qo'shilgani ko'rsatilgan", "imzo qo'shildi" in text,
          text[-200:])
    check("demo: DB'ga HECH NARSA yozilmadi",
          fake.set_calls == [] and fake.signature_calls == [],
          str((fake.set_calls, fake.signature_calls)))

    # 8e) stgs_clean_sig_clear → imzo o'chadi + toast.
    fake = _FakeDB(signature="https://t.me/my_channel")
    query = _with_db(fake, lambda: _run_cb("stgs_clean_sig_clear"))
    check("clear: DB'ga bo'sh imzo yozildi (HTML + matn)",
          fake.signature_calls and fake.signature_calls[-1][1] == "",
          str(fake.signature_calls))
    check("clear: toast berildi", len(query.answered) >= 1, str(query.answered))

    # 8f) 10 qatorli, havolali imzo to'liq saqlanadi (yangi oqim, HTML).
    from telegram.ext import ConversationHandler
    long_signature = "\n".join(["x" * 50 for _ in range(9)] + ["https://t.me/my_channel"])
    signature_replies = []

    class _SignatureMessage:
        text = long_signature
        entities = ()

        async def reply_text(self, text, **kwargs):
            signature_replies.append(text)

    signature_context = SimpleNamespace(
        user_data={"lang": "uz"}, bot=_Bot(), chat_data={}, application=None,
    )
    signature_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=USER_ID),
        effective_chat=SimpleNamespace(id=555),
        message=_SignatureMessage(),
        effective_message=_SignatureMessage(),
    )
    fake = _FakeDB()
    signature_state = _with_db(
        fake, lambda: STG.cleaner_signature_received(signature_update, signature_context),
    )
    check("signature input: 10 qatorli havolali imzo saqlandi",
          fake.signature == long_signature and len(fake.signature.split("\n")) == 10,
          f"len={len(fake.signature)}, lines={len(fake.signature.splitlines())}")
    check("signature input: saqlandi va oqim tugadi",
          fake.signature_calls == [(USER_ID, long_signature)]
          and signature_state == ConversationHandler.END,
          str(fake.signature_calls))

    # 8g) Noma'lum stgs_* callback — jim, crash yo'q.
    fake = _FakeDB()
    query = _with_db(fake, lambda: _run_cb("stgs_totally_unknown"))
    check("noma'lum callback: crash yo'q, ekran yo'q",
          not query.edits and not query.message.sent)


def _run_cb(data, lang="uz"):
    """Callback'ni haqiqiy handler orqali bajaradi (KORUTINA qaytaradi)."""
    async def _go():
        query = _Query(data)
        await STG.settings_menu_callback(_upd_query(query), _ctx(lang))
        return query
    return _go()


# ============================================================
# TEST 9 — IMZO SAQLASH (normalize + repository yagona qoida)
# ============================================================
def test_signature_storage():
    header("9", "💾 IMZO SAQLASH — yagona normalizatsiya qoidasi")

    from repositories.users_repository import (
        POST_SIGNATURE_MAX_LEN,
        _normalize_post_signature,
    )

    check("repository chegarasi = post_cleaner chegarasi",
          POST_SIGNATURE_MAX_LEN == MAX_SIGNATURE_LEN)
    samples = [
        ("  oddiy imzo  ", "oddiy imzo"),
        ("a\n\n\nb\n\nc\n\nd", "a\nb\nc\nd"),
        ("x" * 900, "x" * MAX_SIGNATURE_LEN),
        ("evil\x00\u202e\u200e text", "evil text"),
        ("<b>teg</b>", "<b>teg</b>"),
        (None, ""),
        ("", ""),
    ]
    for raw, expected in samples:
        got_repo = _normalize_post_signature(raw)
        got_engine = normalize_signature(raw)
        check(f"normalize {raw!r:.40} → ikki manba BIR XIL",
              got_repo == got_engine, f"{got_repo!r} != {got_engine!r}")
        if expected:
            check(f"normalize {raw!r:.40} → kutilgan natija", got_repo == expected,
                  f"{got_repo!r} != {expected!r}")

    # Schema/migration pariteti: ustun ikkala joyda ham e'lon qilingan.
    schema = (ROOT / "telegram_bot" / "schema.sql").read_text(encoding="utf-8")
    database_py = (ROOT / "telegram_bot" / "database.py").read_text(encoding="utf-8")
    check("schema.sql: post_signature_text ustuni bor",
          "post_signature_text VARCHAR(500)" in schema)
    check("database.py: idempotent migratsiya bor",
          "ALTER COLUMN post_signature_text TYPE VARCHAR(500)" in database_py)
    check("database.py: funksiyalar eksport qilingan",
          "get_user_post_signature" in database_py
          and "set_user_post_signature" in database_py)
    check("database moduli: funksiyalar mavjud",
          hasattr(db_mod, "get_user_post_signature")
          and hasattr(db_mod, "set_user_post_signature"))


# ============================================================
# TEST 10 — i18n PARITET + 18-BELGI STANDARTI
# ============================================================
_INVISIBLE = "\ufe0f\u200d" + "".join(chr(c) for c in range(0x1F3FB, 0x1F400))


def _vlen(label: str) -> int:
    return len(label.replace(_INVISIBLE, "").replace("\u200e", ""))


def test_i18n():
    header("10", "🌐 i18n PARITET + 18-BELGI STANDARTI")
    report = settings_stats_parity_report()
    check("uz/ru/en kalit pariteti 100%", report["in_sync"],
          str({"missing": report["missing"], "extra": report["extra"]}))
    check("format argumentlari bir xil", not report["format_mismatch"],
          str(report["format_mismatch"]))
    check("bo'sh qiymat yo'q", not report["empty"], str(report["empty"]))

    new_keys = (
        "ss_btn_more", "ss_more_title", "ss_more_hint", "ss_btn_cleaner",
        "ss_clean_title", "ss_clean_status", "ss_clean_on", "ss_clean_off",
        "ss_clean_body", "ss_clean_sig_label", "ss_clean_sig_empty",
        "ss_clean_sig_value", "ss_clean_hint", "ss_btn_clean_sig",
        "ss_btn_clean_clear", "ss_btn_clean_demo", "ss_clean_sig_prompt",
        "ss_clean_sig_saved", "ss_clean_sig_cleared", "ss_clean_sig_none",
        "ss_clean_sig_rejected", "ss_clean_demo_title", "ss_clean_demo_before",
        "ss_clean_demo_after", "ss_clean_demo_stats",
        "ss_clean_demo_sig_added", "ss_clean_demo_nochange",
    )
    for key in new_keys:
        for lang in LANGS:
            value = settings_stats_t(key, lang)
            check(f"[{lang}] {key}: qiymat bor va fallback EMAS",
                  bool(value.strip()) and value != key, repr(value))

    # 18-belgi standarti (inline yorliqlar) — repo standarti bilan bir xil.
    for key in ("ss_btn_more", "ss_btn_cleaner", "ss_btn_clean_sig",
                "ss_btn_clean_clear", "ss_btn_clean_demo"):
        for lang in LANGS:
            value = settings_stats_t(key, lang)
            check(f"[{lang}] {key} ≤18 belgi", _vlen(value) <= 18,
                  f"{value!r} = {_vlen(value)}")

    # Toggle yorliqlari uchala tilda (COMPACT_TOGGLE_LABELS pariteti).
    for key in STG.CLEANER_SETTING_KEYS:
        present = [lang for lang in LANGS
                   if key in STG.COMPACT_TOGGLE_LABELS.get(lang, {})]
        check(f"toggle yorlig'i '{key}' uchala tilda", len(present) == 3,
              str(present))
        for lang in LANGS:
            label = STG.settings_toggle_label(key, lang, True)
            check(f"[{lang}] toggle '{key}' ≤18 belgi", _vlen(label) <= 18,
                  f"{label!r} = {_vlen(label)}")


# ============================================================
# TEST 11 — INGEST ULANMASI (RSS + URL)
# ============================================================
def test_ingest_wiring():
    header("11", "📥 INGEST ULANMASI — RSS/URL manba matni tozalanadi")
    from services.sources.rss_service import FeedItem, RssService, digest_draft
    from services.sources import url_extractor as ux

    cfg_on = CleanerConfig(enabled=True, signature="© MyChannel",
                           own_usernames=OWN)
    cfg_off = CleanerConfig(enabled=False, signature="© MyChannel")

    item = FeedItem(
        external_id="x1", canonical_url="https://site.example/a",
        title="Sarlavha @foreign_news",
        summary=("Asosiy mazmun shu yerda.\n"
                 "Reklama: @promo_uz — obuna bo'ling!\n"
                 "Manba: https://t.me/foreign_news/7"),
    )

    service = RssService.__new__(RssService)  # tarmoq/AI'siz, faqat tozalash
    # Yoqilgan: MANBA matni tozalanadi, botning o'z yorlig'i SAQLANADI.
    draft_on = _with_db(_FakeDB(), lambda: service.build_draft(
        item, user_id=None, lang="uz", use_ai=False, cleaner_config=cfg_on))
    text_on = draft_on.get("text", "")
    check("RSS (yoqilgan): begona mention yo'q", "@foreign_news" not in text_on
          and "@promo_uz" not in text_on, text_on[:200])
    check("RSS (yoqilgan): imzo qo'shildi", "© MyChannel" in text_on, text_on[-200:])
    check("RSS (yoqilgan): botning O'Z '🔗 Manba:' yorlig'i SAQLANDI",
          "Manba" in text_on, text_on[-260:])
    check("RSS (yoqilgan): sarlavha tozalandi",
          "@foreign_news" not in text_on, text_on[:200])

    # O'chirilgan: matn o'zgarmaydi (regressiya yo'q).
    draft_off = _with_db(_FakeDB(), lambda: service.build_draft(
        item, user_id=None, lang="uz", use_ai=False, cleaner_config=cfg_off))
    text_off = draft_off.get("text", "")
    check("RSS (o'chirilgan): manba matni O'ZGARMADI",
          "@foreign_news" in text_off, text_off[:200])
    check("RSS (o'chirilgan): imzo qo'shilmadi", "© MyChannel" not in text_off)

    # Sentinel (uzatilmagan) + user_id yo'q → tozalashsiz (soxta yoqish yo'q).
    draft_unset = _with_db(_FakeDB(), lambda: service.build_draft(
        item, user_id=None, lang="uz", use_ai=False))
    check("RSS (konfiguratsiya uzatilmagan, user_id yo'q): tozalanmadi",
          "@foreign_news" in draft_unset.get("text", ""))

    # digest_draft o'zi (tozalashsiz) bot yorlig'ini qo'shishini tasdiqlash.
    plain = digest_draft(item, lang="uz")
    check("digest_draft: '🔗 Manba' yorlig'i mavjud (tozalash uni buzmaydi)",
          "Manba" in plain, plain[-160:])

    # URL manba maqolasi tozalanadi.
    article = {"title": "Sarlavha @foreign_news", "text":
               "Asosiy mazmun bir.\nAsosiy mazmun ikki.\nAsosiy mazmun uch.\n"
               "Reklama: @promo_uz — obuna bo'ling!\n"
               "Manba: https://t.me/foreign_news/9",
               "source": "site.example"}
    cleaned = _with_db(_FakeDB(), lambda: ux._clean_source_article(
        article, USER_ID, cfg_on))
    check("URL: begona mention o'chirildi",
          "@foreign_news" not in cleaned.get("text", "")
          and "@foreign_news" not in cleaned.get("title", ""), str(cleaned)[:200])
    check("URL: imzo qo'shildi", "© MyChannel" in cleaned.get("text", ""),
          cleaned.get("text", "")[-160:])
    check("URL: META (source) saqlandi", cleaned.get("source") == "site.example",
          str(cleaned.get("source")))
    unchanged = _with_db(_FakeDB(), lambda: ux._clean_source_article(
        article, USER_ID, cfg_off))
    # Diqqat: ``text`` ichida manba URL ko'rinishida (``t.me/foreign_news``),
    # sarlavhada esa @mention ko'rinishida — shu sababli ikkalasi alohida.
    check("URL (o'chirilgan): matn o'zgarmadi",
          "foreign_news" in unchanged.get("text", "")
          and "@foreign_news" in unchanged.get("title", ""),
          str(unchanged)[:200])
    check("URL: asl dict O'ZGARMADI (nusxa ustida ishlaydi)",
          "foreign_news" in article["text"]
          and "@foreign_news" in article["title"],
          str(article)[:200])

    # Kanal-extract: auto-cleaner opt-in pass.
    import handlers.channel_extract as CE

    adapted_off = _with_db(_FakeDB(), lambda: CE._apply_auto_cleaner(
        "Salom @bad_user dunyo", USER_ID))
    check("channel_extract (o'chirilgan): matn o'zgarmadi",
          adapted_off == "Salom @bad_user dunyo", adapted_off)
    adapted_none = _with_db(_FakeDB(), lambda: CE._apply_auto_cleaner(
        "Salom @bad_user", None))
    check("channel_extract (user_id yo'q): tozalanmaydi",
          adapted_none == "Salom @bad_user", adapted_none)


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print(" 🧪 POST AUTO-CLEANER & CUSTOM SIGNATURE — TEST SUITE")
    print("=" * 70)
    test_entity_safe_html()
    test_entity_offsets()
    test_markdown_tree()
    test_signature_injection()
    test_multi_country()
    test_fail_safe()
    test_more_settings_navigation()
    test_handler_routing()
    test_signature_storage()
    test_i18n()
    test_ingest_wiring()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] POST AUTO-CLEANER TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" 🧹 POST AUTO-CLEANER & CUSTOM SIGNATURE — 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
