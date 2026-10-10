#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔐 MAXFIYLIK SIYOSATI + «🗑 MA'LUMOTLARIMNI O'CHIRISH» — deterministik testlar.

SPRINT 1 (Privacy & GDPR) qabul mezonlari birma-bir:

  TEST 1: 🌐 I18N PARITET — ``translations/privacy.py`` uz/ru/en 100%
          to'liq (kalitlar bir xil, bo'sh qiymat YO'Q, placeholder'lar
          uchala tilda bir xil);
  TEST 2: 📄 SIYOSAT MATNI — bot nima saqlashini OCHIQ aytadi (kanal ID,
          post matnlari, AI telemetriyasi, to'lov yozuvlari) va qanday
          huquqlar borligini tushuntiradi; matn HTML uchun xavfsiz;
  TEST 3: ⌨️ KLAVIATURALAR — siyosat ekrani [🗑 O'chirish | ◀️ Orqaga],
          tasdiq ekrani [✅ Ha | ❌ Bekor], Sozlamalar hub'ida
          ``stgs_privacy`` + ``stgs_delete_data`` mavjud;
  TEST 4: 📣 ``/privacy`` HANDLERI — uchala tilda ishlaydi (buyruq hamda
          callback orqali), xabar ``reply_text`` bilan yuboriladi;
  TEST 5: 🛡 TASDIQ HIMOYASI — «🗑 O'chirish» bosilganda FAQAT tasdiq
          ekrani chiqadi (ma'lumot tegilmaydi); «❌ Bekor qilish» hech
          narsani o'chirmaydi;
  TEST 6: 🗑 O'CHIRISH BAJARILADI — tasdiqlangach ``delete_user_data``
          chaqiriladi va foydalanuvchiga hisob-tozalash hisoboti +
          asosiy menyu qaytariladi; DB xatosida — xavfsiz xato xabari
          (jim yutilmaydi);
  TEST 7: 🧬 SQL KONTRAKTI (fake cursor) — ``delete_user_data`` aynan:
            * ``users`` va ``channels`` ni SOFT-delete qiladi
              (``deleted_at``, anonimlashtirish);
            * post matnini NULL qiladi va qoralamalarni bekor qiladi;
            * ``ai_usage_events`` (uchinchi tomon AI tarixi) ni o'chiradi;
            * audit yozuvi qoldiradi (``user_data_deleted``,
              ``self_service=true``);
            * TO'LOV jadvallariga (``payments``, ``payment_receipts``,
              ``payment_orders``, ``credits_ledger``) HECH QACHON
              tegmaydi — qonuniy audit uchun SAQLANADI;
  TEST 8: ♻️ IDEMPOTENTLIK — allaqachon o'chirilgan hisob uchun qayta
          bosish yozuvlarni o'zgartirmaydi (``already_deleted=True``);
          noto'g'ri ``user_id`` → ``ok=False`` (FAIL-CLOSED).

Ishga tushirish:
    python3 tests/privacy_and_data_deletion_test.py
"""
import asyncio
import datetime as dt
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

LANGS = ("uz", "ru", "en")
USER_ID = 777000111

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


def header(letter, title):
    print(f"\n== TEST {letter}: {title} ==")


def _run(coro):
    return asyncio.run(coro)


# ============================================================================
# TEST 1 — I18N PARITET
# ============================================================================
def test_1_i18n_parity():
    header("1", "🌐 privacy i18n — uz/ru/en to'liq paritet")
    from translations import PRIVACY_I18N, PRIVACY_KEYS, privacy_parity_report, privacy_t

    report = privacy_parity_report()
    check("paritet hisoboti: in_sync", report["in_sync"] is True, str(report))
    check("paritet: uz/ru/en farqi yo'q",
          not report.get("uz_only") and not report.get("ru_only"),
          str(report))
    check("kalitlar soni ≥ 25 (siyosat + o'chirish oqimi)",
          len(PRIVACY_KEYS) >= 25, str(len(PRIVACY_KEYS)))

    # Kalitlarning umumiy soni — paritet hisobotidagi bilan bir xil.
    check("PRIVACY_KEYS == PRIVACY_I18N['uz'] kalitlari",
          set(PRIVACY_KEYS) == set(PRIVACY_I18N["uz"]),
          str(set(PRIVACY_KEYS) ^ set(PRIVACY_I18N["uz"])))

    for key in PRIVACY_KEYS:
        values = {}
        for lang in LANGS:
            value = privacy_t(key, lang)
            values[lang] = value
            check(f"{lang}: {key} bo'sh emas", bool(str(value).strip()), repr(value))
        check(f"{key}: uz/ru/en qiymatlari bir xil emas (tarjima qilingan)",
              len(set(values.values())) >= 2 or key.startswith("pv_retention"),
              str(values))

    # Noma'lum til — xavfsiz fallback (uz), lekin bo'sh emas.
    check("noma'lum til → fallback (bo'sh emas)", bool(privacy_t("pv_title", "de").strip()))
    # Noma'lum kalit — jim yiqilmaydi, kalitning o'zi qaytadi (debug uchun).
    check("noma'lum kalit jim yiqilmaydi",
          isinstance(privacy_t("pv_yoq_kalit", "uz"), str))


# ============================================================================
# TEST 2 — SIYOSAT MATNI
# ============================================================================
def test_2_policy_text():
    header("2", "📄 Siyosat matni — nima saqlanishi OCHIQ")
    from handlers.privacy import build_policy_text
    from translations import privacy_t

    for lang in LANGS:
        text = build_policy_text(lang)
        low = text.lower()
        check(f"[{lang}] matn yetarlicha to'liq (≥400 belgi)", len(text) >= 400, str(len(text)))
        # Kanal ID — uchala tilda ham aniq aytilishi shart (uz: kanal,
        # ru: канал, en: channel).
        check(f"[{lang}] kanal ID saqlanishi aytilgan",
              ("kanal" in low or "канал" in low or "channel" in low) and "id" in low,
              text[:120])
        check(f"[{lang}] post matni saqlanishi aytilgan",
              ("post" in low and ("matn" in low or "text" in low or "текст" in low)),
              text[:120])
        check(f"[{lang}] siyosat matni haqiqiy tugma yorlig'ini tilga oladi",
              privacy_t("pv_btn_delete", lang) in text, text[:200])
        check(f"[{lang}] AI telemetriyasi aytilgan",
              ("ai" in low or "ии" in low), text[:120])
        check(f"[{lang}] to'lov yozuvlari + saqlash muddati aytilgan",
              ("to'lov" in low or "платеж" in low or "payment" in low), text[:120])
        check(f"[{lang}] huquqlar bo'limi bor (o'chirish)",
              "o'chirish" in low or "удал" in low or "delet" in low, text[:120])
        # HTML xavfsizligi: foydalanuvchi kiritmasi yo'q — faqat bizning teglar.
        check(f"[{lang}] matndagi HTML teglar XAVFSIZ (allowlist)",
              _html_tags_are_safe(text), text[:200])

    # Matn uchala tilda farq qiladi (haqiqiy tarjima).
    texts = {lang: build_policy_text(lang) for lang in LANGS}
    check("siyosat matni uchala tilda har xil", len(set(texts.values())) == 3)


def _html_tags_are_safe(text: str) -> bool:
    """Matnda faqat <b>/<i>/<code>/<a href> teglari ishlatilishini tekshiradi."""
    import re

    allowed = {"b", "i", "u", "s", "code", "pre", "a", "em", "strong", "tg-spoiler"}
    for match in re.finditer(r"</?([a-zA-Z0-9-]+)", text):
        if match.group(1).lower() not in allowed:
            return False
    return True


# ============================================================================
# TEST 3 — KLAVIATURALAR
# ============================================================================
def _kb_rows(kb):
    return [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]


def test_3_keyboards():
    header("3", "⌨️ Klaviaturalar — siyosat, tasdiq, hub")
    from handlers.privacy import get_delete_confirm_keyboard, get_privacy_keyboard
    from keyboards.inline import get_settings_profile_keyboard

    for lang in LANGS:
        pol = _kb_rows(get_privacy_keyboard(lang))
        check(f"[{lang}] siyosat ekrani: 2 qator (o'chirish + orqaga)",
              len(pol) == 2, str(pol))
        check(f"[{lang}] siyosat ekrani: stgs_privacy_del",
              pol[0][0][1] == "stgs_privacy_del", str(pol[0]))
        check(f"[{lang}] siyosat ekrani: orqaga → stgs_hub",
              pol[1][0][1] == "stgs_hub", str(pol[1]))

        conf = _kb_rows(get_delete_confirm_keyboard(lang))
        check(f"[{lang}] tasdiq ekrani: 2 qator", len(conf) == 2, str(conf))
        check(f"[{lang}] tasdiq: stgs_privacy_del_ok",
              conf[0][0][1] == "stgs_privacy_del_ok", str(conf[0]))
        check(f"[{lang}] tasdiq: stgs_privacy_cancel",
              conf[1][0][1] == "stgs_privacy_cancel", str(conf[1]))
        # Xavfli amal — tasdiq tugmasi BOSHQA qatorda (tasodifiy bosish yo'q).
        check(f"[{lang}] tasdiq va bekor ALOHIDA qatorlarda",
              conf[0][0][1] != conf[1][0][1], str(conf))

        hub_cbs = [c for row in get_settings_profile_keyboard(lang).inline_keyboard
                   for _t, c in [(b.text, b.callback_data) for b in row]]
        check(f"[{lang}] hub: stgs_privacy BOR", "stgs_privacy" in hub_cbs, str(hub_cbs))
        check(f"[{lang}] hub: stgs_delete_data BOR",
              "stgs_delete_data" in hub_cbs, str(hub_cbs))
        check(f"[{lang}] hub: callback'lar dublikat emas",
              len(hub_cbs) == len(set(hub_cbs)), str(hub_cbs))


# ============================================================================
# TEST 4 — /privacy HANDLERI
# ============================================================================
class _FakeMessage:
    def __init__(self, user_id=USER_ID):
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=len(self.sent), chat=self.chat)


class _FakeContext:
    def __init__(self, lang="uz"):
        self.user_data = {"lang": lang} if lang else {}
        self.bot_data = {}


def _command_update(lang="uz"):
    msg = _FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=USER_ID, first_name="Tester"),
        effective_message=msg,
        message=msg,
        callback_query=None,
    )
    return update, msg, _FakeContext(lang)


def test_4_privacy_command():
    header("4", "📣 /privacy handleri — uchala tilda ishlaydi")
    from handlers.privacy import privacy_command

    for lang in LANGS:
        update, msg, ctx = _command_update(lang)
        _run(privacy_command(update, ctx))
        check(f"[{lang}] /privacy: xabar yuborildi", len(msg.sent) == 1, str(msg.sent))
        text = msg.sent[0]["text"] if msg.sent else ""
        check(f"[{lang}] /privacy: HTML parse_mode",
              msg.sent and msg.sent[0].get("parse_mode") == "HTML", str(msg.sent[:1]))
        check(f"[{lang}] /privacy: klaviatura (o'chirish tugmasi)",
              msg.sent and _kb_rows(msg.sent[0]["reply_markup"])[0][0][1] == "stgs_privacy_del",
              str(msg.sent[:1]))
        check(f"[{lang}] /privacy: matn siyosat bilan bir xil",
              text == __import__("handlers.privacy", fromlist=["x"]).build_policy_text(lang))

    # User yo'q (kanal posti) → jim qaytadi, xato bermaydi.
    lonely = SimpleNamespace(effective_user=None, effective_message=None, message=None,
                             callback_query=None)
    _run(privacy_command(lonely, _FakeContext()))
    check("/privacy: user yo'q → xatosiz qaytadi", True)


# ============================================================================
# TEST 5 — TASDIQ HIMOYASI
# ============================================================================
def test_5_two_step_confirmation():
    header("5", "🛡 Ikki bosqichli tasdiq — bir bosishda o'chmaydi")
    from handlers.privacy import _render_delete_confirm, privacy_cancel

    calls = []

    class _Query:
        def __init__(self):
            self.from_user = SimpleNamespace(id=USER_ID)
            self.message = _FakeMessage()
            self.edits = []
            self.answered = False

        async def answer(self, *a, **kw):
            self.answered = True

        async def edit_message_text(self, text, **kw):
            self.edits.append(dict(text=text, **kw))
            return SimpleNamespace(message_id=1)

    def _fake_delete(*a, **kw):
        calls.append(("delete", a, kw))
        return {"ok": True, "channels": 0, "posts": 0, "ai_events": 0}

    query = _Query()
    with patch("database.run_db", new=_fake_run_db(_fake_delete)):
        _run(_render_delete_confirm(query, _FakeContext(), USER_ID, "uz"))
        check("tasdiq ekrani: matn tahrirlandi", bool(query.edits), str(query.edits))
        check("tasdiq ekrani: HECH NARSA o'chirilmadi", not calls, str(calls))
        confirm_kb = _kb_rows(query.edits[0]["reply_markup"]) if query.edits else []
        check("tasdiq ekrani: [✅ Ha] + [❌ Bekor]",
              [c for row in confirm_kb for _t, c in row]
              == ["stgs_privacy_del_ok", "stgs_privacy_cancel"], str(confirm_kb))

        # «❌ Bekor qilish» — hech narsa o'chirmaydi, siyosat ekraniga qaytadi.
        query2 = _Query()
        update2 = SimpleNamespace(effective_user=SimpleNamespace(id=USER_ID),
                                  callback_query=query2,
                                  effective_message=query2.message, message=None)
        _run(privacy_cancel(update2, _FakeContext("uz")))
        check("bekor qilish: DB chaqirilmadi", not calls, str(calls))
        check("bekor qilish: foydalanuvchiga xabar berildi",
              bool(query2.edits), str(query2.edits))


def _fake_run_db(fn):
    """``database.run_db`` o'rnini bosadi: birinchi arg — DB funksiyasi."""
    async def _inner(func, *args, **kwargs):
        return fn(*args, **kwargs)

    return _inner


# ============================================================================
# TEST 6 — O'CHIRISH BAJARILADI (handler darajasi)
# ============================================================================
def test_6_delete_confirm_handler():
    header("6", "🗑 Tasdiqlangach o'chirish bajariladi + hisobot qaytadi")
    from handlers.privacy import privacy_delete_confirm

    class _Query:
        def __init__(self):
            self.from_user = SimpleNamespace(id=USER_ID)
            self.message = _FakeMessage()
            self.answered = False

        async def answer(self, *a, **kw):
            self.answered = True

        async def edit_message_text(self, text, **kw):  # bu yo'l ishlatilmaydi
            return SimpleNamespace(message_id=1)

    result_holder = {}

    def _fake_delete(user_id):
        result_holder["user_id"] = user_id
        return {"ok": True, "user_id": user_id, "channels": 2, "posts": 5,
                "ai_events": 9, "already_deleted": False, "cleaned": {}}

    query = _Query()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=USER_ID),
                             callback_query=query,
                             effective_message=query.message, message=None)
    ctx = _FakeContext("ru")
    with patch("database.run_db", new=_fake_run_db(_fake_delete)):
        result = _run(privacy_delete_confirm(update, ctx))

    check("o'chirish: run_db foydalanuvchi ID'si bilan chaqirildi",
          result_holder.get("user_id") == USER_ID, str(result_holder))
    check("o'chirish: natija qaytarildi (ok=True)",
          isinstance(result, dict) and result.get("ok") is True, str(result))
    check("o'chirish: callback toast yuborildi (answer)", query.answered)
    check("o'chirish: hisobot xabari yuborildi", bool(query.message.sent),
          str(query.message.sent))
    report = query.message.sent[0]["text"] if query.message.sent else ""
    check("hisobot: kanal/post/AI raqamlari ko'rsatilgan",
          all(str(n) in report for n in (2, 5, 9)), report[:200])
    check("o'chirish: asosiy menyu klaviaturasi qaytarildi",
          query.message.sent and query.message.sent[0].get("reply_markup") is not None,
          str(query.message.sent[:1]))
    check("o'chirish: FSM tozalandi (til saqlanadi)",
          ctx.user_data.get("lang") == "ru", str(ctx.user_data))

    # --- DB xatosi: jim yutilmaydi, foydalanuvchiga xavfsiz xabar ---
    query2 = _Query()
    update2 = SimpleNamespace(effective_user=SimpleNamespace(id=USER_ID),
                              callback_query=query2,
                              effective_message=query2.message, message=None)
    with patch("database.run_db", new=_fake_run_db_raise()):
        res2 = _run(privacy_delete_confirm(update2, _FakeContext("uz")))
    check("DB xatosi: handler None qaytaradi (yiqilmaydi)", res2 is None, str(res2))
    check("DB xatosi: foydalanuvchiga xato xabari yuborildi",
          bool(query2.message.sent), str(query2.message.sent))


def _fake_run_db_raise():
    async def _inner(*args, **kwargs):
        raise RuntimeError("db down")

    return _inner


# ============================================================================
# TEST 7 — SQL KONTRAKTI (fake cursor)
# ============================================================================
class _FakeCursor:
    """``db_transaction()`` kursorini taqlid qiladi va SQL'larni yozib boradi."""

    def __init__(self, *, already_deleted=False, channels=("chan_1", "chan_2"),
                 rowcounts=None):
        self.sql = []
        self.params = []
        self._already_deleted = already_deleted
        self._channels = list(channels)
        self._rowcounts = dict(rowcounts or {})
        self.rowcount = 0
        self._one = None
        self._all = []

    # -- SQL normalizatsiyasi (bir necha qatorli so'rovlar) --
    @staticmethod
    def _norm(sql):
        return " ".join(str(sql).split())

    def execute(self, sql, params=None):
        norm = self._norm(sql)
        self.sql.append(norm)
        self.params.append(params)
        if "SELECT deleted_at FROM users" in norm:
            self._one = ((dt.datetime(2026, 1, 1),) if self._already_deleted else (None,))
            self.rowcount = 1
            return
        if "SELECT channel_id FROM channels" in norm:
            self._all = [(c,) for c in self._channels]
            self.rowcount = len(self._all)
            return
        self._one = None
        self._all = []
        self.rowcount = self._rowcount_for(norm)

    def _rowcount_for(self, norm):
        for marker, count in self._rowcounts.items():
            if marker in norm:
                return count
        return 1

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _FakeTx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self.cur

    def __exit__(self, *exc):
        return False


def _run_delete(cur, *, expect_ok=True, patch_core=True):
    """``delete_user_data`` ni fake kursor bilan bajaradi (yadro patch'lari bilan)."""

    import database  # noqa: F401

    invalidated = []
    cache_cleared = []
    with patch("database.db_transaction", new=lambda: _FakeTx(cur)), \
            patch("database._invalidate_user", new=lambda uid: invalidated.append(uid)), \
            patch("database._cache_clear", new=lambda key: cache_cleared.append(key)):
        from repositories.users_repository import delete_user_data

        result = delete_user_data(USER_ID)
    return result, invalidated, cache_cleared


def test_7_sql_contract():
    header("7", "🧬 delete_user_data SQL kontrakti (to'lovlar SAQLANADI)")
    from repositories.users_repository import ACCOUNT_DELETE_RETAINED_TABLES

    check("saqlanadigan jadvallar ro'yxati (legal audit)",
          set(ACCOUNT_DELETE_RETAINED_TABLES)
          == {"payments", "payment_receipts", "payment_orders", "credits_ledger"},
          str(ACCOUNT_DELETE_RETAINED_TABLES))

    cur = _FakeCursor(rowcounts={
        "UPDATE scheduled_posts SET content = NULL": 4,
        "UPDATE scheduled_posts SET status = 'cancelled'": 4,
        "DELETE FROM ai_usage_events": 9,
    })
    result, invalidated, cache_cleared = _run_delete(cur)

    check("natija: ok=True", result.get("ok") is True, str(result))
    check("natija: channels=2", result.get("channels") == 2, str(result))
    check("natija: posts=4", result.get("posts") == 4, str(result))
    check("natija: ai_events=9", result.get("ai_events") == 9, str(result))
    check("natija: already_deleted=False", result.get("already_deleted") is False,
          str(result))

    joined = "\n".join(cur.sql)

    # 1) Hisob: soft-delete + anonimlashtirish
    check("SQL: users soft-delete (deleted_at = NOW())",
          "UPDATE users" in joined and "deleted_at = NOW()" in joined, joined[:200])
    check("SQL: users anonimlashtirildi (username/full_name NULL)",
          "username = NULL" in joined and "full_name = NULL" in joined)
    check("SQL: users roli tushirildi (role = 'user')", "role = 'user'" in joined)

    # 2) Kanallar: soft-delete
    check("SQL: channels soft-delete (is_active = FALSE)",
          "UPDATE channels" in joined and "is_active = FALSE" in joined, joined[:200])
    check("SQL: channels.deleted_at = NOW()", "deleted_at = NOW()" in joined)

    # 3) Post matnlari va navbat
    check("SQL: post matni NULL qilindi",
          "content = NULL" in joined, joined[:200])
    check("SQL: qoralamalar bekor qilindi (status = 'cancelled')",
          "status = 'cancelled'" in joined)
    check("SQL: yuborilmagan navbat (pending) o'chirildi",
          "DELETE FROM post_deliveries" in joined)

    # 4) AI tarixi
    check("SQL: ai_usage_events o'chirildi",
          "DELETE FROM ai_usage_events" in joined)

    # 5) Audit izi
    check("SQL: audit yozuvi (admin_audit_logs)",
          "INSERT INTO admin_audit_logs" in joined)
    audit_sql = [sql for sql in cur.sql if sql.startswith("INSERT INTO admin_audit_logs")]
    audit_params = [p for sql, p in zip(cur.sql, cur.params)
                    if sql.startswith("INSERT INTO admin_audit_logs")]
    check("audit: action = user_data_deleted (SQL literali)",
          audit_sql and "'user_data_deleted'" in audit_sql[0], str(audit_sql))
    check("audit: target_type='user' + target_id",
          audit_sql and "'user'" in audit_sql[0] and "target_id" in audit_sql[0],
          str(audit_sql))
    check("audit: self_service=true belgisi",
          audit_params and '"self_service": true' in str(audit_params[0]).replace("'", '"'),
          str(audit_params))

    # 6) TO'LOVLAR — hech qachon o'chirilmaydi
    for table in ACCOUNT_DELETE_RETAINED_TABLES:
        check(f"SAQLANADI: {table} ga DELETE/UPDATE yo'q",
              f"FROM {table}" not in joined and f"UPDATE {table}" not in joined,
              joined[-400:])

    # 7) Kesh: tranzaksiyadan keyin tozalanadi
    check("kesh: _invalidate_user(user_id) chaqirildi",
          invalidated == [USER_ID], str(invalidated))
    check("kesh: user_lang kesh tozalandi", "user_lang" in cache_cleared,
          str(cache_cleared))


# ============================================================================
# TEST 8 — IDEMPOTENTLIK VA FAIL-CLOSED
# ============================================================================
def test_8_idempotency_and_validation():
    header("8", "♻️ Idempotentlik + noto'g'ri user_id (FAIL-CLOSED)")
    from repositories.users_repository import delete_user_data

    # (a) allaqachon o'chirilgan → hech qanday YOZUV bo'lmasligi shart
    cur = _FakeCursor(already_deleted=True)
    result, invalidated, _cleared = _run_delete(cur)
    check("qayta o'chirish: already_deleted=True", result.get("already_deleted") is True,
          str(result))
    check("qayta o'chirish: faqat SELECT bo'ldi (yozuv yo'q)",
          all(sql.startswith("SELECT") for sql in cur.sql), str(cur.sql))
    check("qayta o'chirish: yozuvlarni o'zgartirmadi",
          not any("UPDATE" in sql or "DELETE" in sql or "INSERT" in sql for sql in cur.sql),
          str(cur.sql))

    # (b) noto'g'ri user_id — FAIL-CLOSED, DB'ga umuman bormaydi
    for bad in ("abc", None, 0, -5):
        bad_cur = _FakeCursor()
        with patch("database.db_transaction", new=lambda: _FakeTx(bad_cur)):
            result = delete_user_data(bad)
        check(f"user_id={bad!r}: ok=False (invalid_user_id)",
              result.get("ok") is False and result.get("reason") == "invalid_user_id",
              str(result))
        check(f"user_id={bad!r}: DB so'rovi YO'Q", not bad_cur.sql, str(bad_cur.sql))

    # (c) DB xatosi → ok=False, reason=db_error (jim yutilmaydi)
    class _BoomCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "UPDATE users" in self._norm(sql):
                raise RuntimeError("connection lost")
            return super().execute(sql, params)

    with patch("database.db_transaction", new=lambda: _FakeTx(_BoomCursor())):
        result = delete_user_data(USER_ID)
    check("DB xatosi: ok=False (db_error)",
          result.get("ok") is False and result.get("reason") == "db_error",
          str(result))


# ============================================================================
# RUNNER
# ============================================================================
def main():
    print("=" * 68)
    print(" 🔐 MAXFIYLIK + MA'LUMOTLARNI O'CHIRISH TESTLARI (SPRINT 1, GDPR)")
    print("=" * 68)
    test_1_i18n_parity()
    test_2_policy_text()
    test_3_keyboards()
    test_4_privacy_command()
    test_5_two_step_confirmation()
    test_6_delete_confirm_handler()
    test_7_sql_contract()
    test_8_idempotency_and_validation()
    print("\n" + "=" * 68)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" 🔐 MAXFIYLIK TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA MAXFIYLIK VA O'CHIRISH TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
