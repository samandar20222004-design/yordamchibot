"""Oylik/haftalik takrorlash (bot + Mini App serveri), oyning kunini raqam bilan yozish va oddiy postdan Mini App'da davom etish (DB'siz)."""
import asyncio
import os
import sys
from datetime import datetime, time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "telegram_bot"))
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")
os.environ.pop("MINIAPP_ENABLED", None)
os.environ.pop("MINIAPP_URL", None)

import handlers.manual_post as mp  # noqa: E402
import scheduler  # noqa: E402
from locales.translations import get_text  # noqa: E402
from miniapp_api.errors import ApiError  # noqa: E402
from miniapp_api.writes import parse_recurrence_input  # noqa: E402
from services import recurrence as rc  # noqa: E402
from services.schedule_nlp import parse_day_number_once, parse_schedule_text  # noqa: E402
from services.user_timezone import utz  # noqa: E402
from translations import manual_post_t  # noqa: E402
from utils.helpers import format_schedule_line, parse_schedule_input  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [XATO] {name} {extra}")


def at(*a):
    return utz().localize(datetime(*a))


NOW = at(2026, 10, 20, 12, 0)

print("== services.recurrence: monthly ==")
check("normalize monthly", rc.normalize_recurrence("monthly", 15, "10:00") == ("monthly", 15, time(10, 0)))
for bad in (0, 32, True, None, "15"):
    try:
        rc.normalize_recurrence("monthly", bad, "10:00")
        check(f"monthly kun {bad!r} rad etiladi", False)
    except ValueError:
        check(f"monthly kun {bad!r} rad etiladi", True)
check("keyingi: bu oyning kuni hali o'tmagan", rc.next_monthly_occurrence(25, "10:00", NOW) == at(2026, 10, 25, 10, 0))
check("keyingi: kun o'tgan -> keyingi oy", rc.next_monthly_occurrence(15, "10:00", NOW) == at(2026, 11, 15, 10, 0))
check("keyingi: dekabrdan yanvarga", rc.next_monthly_occurrence(15, "10:00", at(2026, 12, 16, 9, 0)) == at(2027, 1, 15, 10, 0))
check("31-kun: fevralda oxirgi kun (28)", rc.next_monthly_occurrence(31, "10:00", at(2026, 1, 31, 10, 0)) == at(2026, 2, 28, 10, 0))
check("31-kun: fevraldan keyin 31-mart", rc.next_monthly_occurrence(31, "10:00", at(2026, 2, 28, 10, 0)) == at(2026, 3, 31, 10, 0))
check("kabisa yili: 29-fevral", rc.next_monthly_occurrence(31, "10:00", at(2028, 1, 31, 10, 0)) == at(2028, 2, 29, 10, 0))
check("first_occurrence monthly", rc.first_occurrence("monthly", 15, "10:00", NOW) == at(2026, 11, 15, 10, 0))
check("scheduler.calculate_next_time monthly", scheduler.calculate_next_time("monthly", 15, time(10, 0), at(2026, 10, 15, 10, 0)) == at(2026, 11, 15, 10, 0))

print("== tabiiy til: oylik / haftalik / oyning kuni raqam bilan ==")
monthly_cases = [
    ("har oyning 15-kuni 10:00", 15, time(10, 0)), ("har oy 15 10:00", 15, time(10, 0)), ("har oy 5-sanasi soat 9:00", 5, time(9, 0)),
    ("har oyda 1-kuni 8:30", 1, time(8, 30)), ("15-kuni har oy 10:00", 15, time(10, 0)), ("oyiga bir marta 18:00", 20, time(18, 0)),
    ("каждый месяц 15 числа в 10:00", 15, time(10, 0)), ("каждое 5 число в 9:30", 5, time(9, 30)), ("ежемесячно в 10:00", 20, time(10, 0)),
    ("every month on the 15th at 10:00", 15, time(10, 0)), ("monthly 5th 9am", 5, time(9, 0)), ("once a month at 8:15", 20, time(8, 15)),
]
for text, day, tm in monthly_cases:
    r = parse_schedule_text(text, NOW)
    rec = r.get("recurrence") or {}
    check(f"«{text}» -> oyda bir, {day}-kun {tm:%H:%M}", r.get("ok") and rec.get("type") == "monthly" and rec.get("day") == day and rec.get("time") == tm, str(r))
once_cases = [("25-kuni soat 18:00", at(2026, 10, 25, 18, 0)), ("25 18:00", at(2026, 10, 25, 18, 0)), ("oyning 5-sanasi 10:00", at(2026, 11, 5, 10, 0)),
              ("15th 10:00", at(2026, 11, 15, 10, 0)), ("25 числа в 18:00", at(2026, 10, 25, 18, 0)), ("31-kuni 10:00", at(2026, 10, 31, 10, 0))]
for text, want in once_cases:
    r = parse_schedule_text(text, NOW)
    check(f"«{text}» -> bir martalik {want:%d.%m %H:%M}", r.get("ok") and r.get("recurrence") is None and r.get("start") == want, str(r))
check("30 kunlik oyda 31-kun keyingi mos oyga o'tadi", parse_day_number_once("31-kuni 10:00", at(2026, 11, 2, 9, 0))["start"] == at(2026, 12, 31, 10, 0))
check("«2 kun keyin» oyning kuni deb o'qilmaydi", parse_day_number_once("2 kun keyin 10:00", NOW) is None)
check("«har oy» vaqtsiz — so'raladi", parse_schedule_text("har oy", NOW) == {"ok": False, "reason": "no_time"})
for text, want_day in (("har haftada 18:00", NOW.weekday()), ("haftasiga bir juma 10:00", 4), ("har hafta juma 10:00", 4)):
    r = parse_schedule_text(text, NOW)
    rec = r.get("recurrence") or {}
    check(f"«{text}» -> haftada bir, kun={want_day}", rec.get("type") == "weekly" and rec.get("day") == want_day, str(r))
check("eski: «har kuni 9:00» o'zgarmadi", parse_schedule_text("har kuni 9:00", NOW)["recurrence"]["type"] == "daily")
check("eski: «har dushanba 9:00» o'zgarmadi", parse_schedule_text("har dushanba 9:00", NOW)["recurrence"] == {"type": "weekly", "day": 0, "time": time(9, 0)})
check("eski: «ertaga 10:00» bir martalik", parse_schedule_text("ertaga 10:00", NOW)["recurrence"] is None)

print("== sana oy nomi bilan (oldin «25 oktabr» bugunga tushardi) ==")
for text, want in (("25 oktabr 18:00", at(2026, 10, 25, 18, 0)), ("25-oktabr 18:00", at(2026, 10, 25, 18, 0)), ("3 noyabr 9:00", at(2026, 11, 3, 9, 0)),
                   ("october 25 18:00", at(2026, 10, 25, 18, 0)), ("25 october 18:00", at(2026, 10, 25, 18, 0)), ("5 ноября 10:00", at(2026, 11, 5, 10, 0))):
    got, _reason = parse_schedule_input(text, NOW)
    check(f"parse_schedule_input «{text}»", got == want, str(got))

print("== ko'rsatish (uz/ru/en) ==")
for lang in ("uz", "ru", "en"):
    line = format_schedule_line(None, "monthly", 15, time(10, 0), lang)
    check(f"[{lang}] format_schedule_line monthly", "15" in line and "10:00" in line, line)
    for key in ("np_confirm_time_monthly", "np_scheduled_when_monthly", "pend_schedule_monthly"):
        check(f"[{lang}] {key}", "{day}" not in get_text(key, lang, day=15, time="10:00") and "15" in get_text(key, lang, day=15, time="10:00"))
    for key in ("mp_repeat_prompt", "mp_repeat_hint_daily", "mp_repeat_hint_weekly", "mp_repeat_hint_monthly", "mp_repeat_set", "mp_repeat_ok2",
                "mp_btn_rk_daily", "mp_btn_rk_weekly", "mp_btn_rk_monthly", "mp_miniapp_hint"):
        check(f"[{lang}] manual_post_t {key}", bool(manual_post_t(key, lang, when="X", channel="K", first="F")))
    for key in ("mp_btn_rk_daily", "mp_btn_rk_weekly", "mp_btn_rk_monthly"):
        check(f"[{lang}] {key} <= 18 belgi", len(manual_post_t(key, lang)) <= 18)

print("== Mini App serveri: monthly validatsiya ==")
when_utc = datetime(2026, 11, 15, 5, 0, tzinfo=utz().utcoffset(datetime(2026, 11, 15)) and __import__("datetime").timezone.utc)  # 10:00 Toshkent
ok = parse_recurrence_input({"type": "monthly", "day": 15, "time": "10:00"}, when_utc)
check("monthly 15-kun, birinchi chiqish 15-nov 10:00 -> qabul", ok == ("monthly", 15, time(10, 0)), str(ok))
for bad in ({"type": "monthly", "day": 16, "time": "10:00"}, {"type": "monthly", "day": 0, "time": "10:00"}, {"type": "monthly", "day": 15, "time": "11:00"}):
    try:
        parse_recurrence_input(bad, when_utc)
        check(f"rad etiladi {bad}", False)
    except ApiError:
        check(f"rad etiladi {bad}", True)
feb = datetime(2026, 2, 28, 5, 0, tzinfo=__import__("datetime").timezone.utc)
check("31-kun, birinchi chiqish 28-fevral (oyning oxirgi kuni) -> qabul", parse_recurrence_input({"type": "monthly", "day": 31, "time": "10:00"}, feb) == ("monthly", 31, time(10, 0)))

print("== oddiy post: takrorlash bot oqimida ==")


class Msg:
    def __init__(self, text=None):
        self.text = text
        self.chat_id = 777
        self.from_user = SimpleNamespace(id=777)
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(dict(text=text, **kw))
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=777))

    chat = SimpleNamespace(id=777, type="private")


def ctx(**ud):
    base = {"lang": "uz", mp.UD_CONTENT: "Salom dunyo", mp.UD_POST_TYPE: "text", mp.UD_SELECTED_CHANNEL_ID: -1001, mp.UD_SELECTED_CHANNEL_TITLE: "Kanal"}
    base.update(ud)
    return SimpleNamespace(user_data=base, chat_data={}, bot=SimpleNamespace(username="b"), application=None)


def run_time(text, **ud):
    m = Msg(text)
    c = ctx(**ud)
    state = asyncio.run(mp.manual_time_received(SimpleNamespace(message=m, effective_message=m, effective_user=m.from_user, callback_query=None), c))
    return state, c, m


state, c, m = run_time("15 10:00", **{mp.UD_MODE: mp.MODE_REPEAT, mp.UD_REPEAT_HINT: "monthly"})
check("Oyda bir tugmasi + «15 10:00» -> monthly 15", state == mp.MANUAL_PREVIEW and c.user_data.get(mp.UD_REPEAT_REC) == {"type": "monthly", "day": 15, "time": "10:00"}, str(c.user_data.get(mp.UD_REPEAT_REC)))
check("takrorlash xabari yuborildi", any("Takrorlash belgilandi" in x["text"] for x in m.sent))
state, c, m = run_time("dushanba 9:00", **{mp.UD_MODE: mp.MODE_REPEAT, mp.UD_REPEAT_HINT: "weekly"})
check("Haftada bir + «dushanba 9:00» -> weekly 0", c.user_data.get(mp.UD_REPEAT_REC) == {"type": "weekly", "day": 0, "time": "09:00"}, str(c.user_data.get(mp.UD_REPEAT_REC)))
state, c, m = run_time("19:30", **{mp.UD_MODE: mp.MODE_REPEAT})
check("eski xulq: faqat «19:30» -> har kuni", c.user_data.get(mp.UD_REPEAT_REC) == {"type": "daily", "day": None, "time": "19:30"}, str(c.user_data.get(mp.UD_REPEAT_REC)))
state, c, m = run_time("har oyning 5-kuni 12:00", **{mp.UD_MODE: mp.MODE_TIME})
check("Vaqt belgilash ichida «har oyning 5-kuni 12:00» ham takrorlash", c.user_data.get(mp.UD_REPEAT_REC) == {"type": "monthly", "day": 5, "time": "12:00"} and c.user_data.get(mp.UD_MODE) == mp.MODE_REPEAT, str(c.user_data))
state, c, m = run_time("25-kuni 18:00", **{mp.UD_MODE: mp.MODE_TIME})
check("Vaqt belgilash: «25-kuni 18:00» bir martalik", state == mp.MANUAL_PREVIEW and c.user_data.get(mp.UD_WHEN, "").endswith("-25 18:00") and not c.user_data.get(mp.UD_REPEAT_REC), str(c.user_data.get(mp.UD_WHEN)))
state, c, m = run_time("salom", **{mp.UD_MODE: mp.MODE_TIME})
check("tushunarsiz matn: holat saqlanadi, xato xabari", state == mp.MANUAL_TIME_INPUT and m.sent, str(state))

# Saqlash: add_post'ga to'g'ri recurrence ketadi
saved = {}


async def fake_run_db(fn, *a, **k):
    name = getattr(fn, "__name__", "")
    if name == "add_post":
        saved.update(k)
        return 42
    return None


async def allow(*a, **k):
    return True


mp.db.run_db = fake_run_db
mp.manual_channel_guard = allow
c = ctx(**{mp.UD_MODE: mp.MODE_REPEAT, mp.UD_REPEAT_REC: {"type": "monthly", "day": 15, "time": "10:00"}, mp.UD_REPEAT_TIME: "10:00", mp.UD_DUP_FORCE: True})
m = Msg()
asyncio.run(mp._publish(m, c, 777, "-1001", "Kanal", "uz"))
check("add_post: recurrence_type=monthly", saved.get("recurrence_type") == "monthly", str(saved))
check("add_post: recurrence_day=15, vaqt 10:00:00", saved.get("recurrence_day") == 15 and saved.get("recurrence_time") == "10:00:00")
st = saved.get("scheduled_time")
check("add_post: birinchi chiqish kelajakda va 15-kun 10:00", st is not None and st > datetime.now(utz()) and st.day == 15 and (st.hour, st.minute) == (10, 0), str(st))
check("yakuniy xabarda «Har oyning 15-kuni» va birinchi chiqish", m.sent and "15" in m.sent[-1]["text"] and "10:00" in m.sent[-1]["text"], str(m.sent[-1]["text"] if m.sent else ""))

print("== oddiy post -> Mini App'da davom etish ==")
saved_drafts = []
dropped = []


async def fake_db_ma(fn, *a, **k):
    name = getattr(fn, "__name__", "")
    if name == "save_draft":
        saved_drafts.append((a[0], a[1]))
    elif name == "delete_draft":
        dropped.append(a[0])
    return None


mp.db.run_db = fake_db_ma
c = ctx(**{mp.UD_REACTIONS: ["👍", "🔥"], mp.UD_URL_BTN_TEXT: "Ochish", mp.UD_URL_BTN_URL: "https://example.org/x", mp.UD_DEL24: True})
asyncio.run(mp._sync_miniapp_draft(c, 777))
check("Mini App o'chiq: qoralama yozilmaydi, tugma yo'q", not saved_drafts and not c.user_data.get(mp.UD_MA_URL))
check("Mini App o'chiq: preview'da web_app tugmasi yo'q", not [b for r in mp._manual_preview_markup(c, "uz").inline_keyboard for b in r if getattr(b, "web_app", None)])

os.environ["MINIAPP_ENABLED"] = "1"
os.environ["MINIAPP_URL"] = "https://bot.example.com/app/"
os.environ["MINIAPP_PROXY_ASSERT_EDGE_ONLY"] = "1"
asyncio.run(mp._sync_miniapp_draft(c, 777))
check("Mini App yoqilgan: qoralama yozildi", len(saved_drafts) == 1 and saved_drafts[0][0] == 777)
payload = saved_drafts[0][1] if saved_drafts else {}
check("qoralama: matn, tur, tugma, reaksiya, 24 soat, kanal AYNAN bot ko'rsatgandek",
      payload.get("content") == "Salom dunyo" and payload.get("post_type") == "text" and payload.get("btn_text") == "Ochish"
      and payload.get("btn_url") == "https://example.org/x" and payload.get("enable_reactions") is True and payload.get("delete_after_hours") == 24
      and payload.get("channel_id") == "-1001", str(payload))
urls = [b.web_app.url for r in mp._manual_preview_markup(c, "uz").inline_keyboard for b in r if getattr(b, "web_app", None)]
check("preview'ning BIRINCHI qatorida «📱 Mini App'da» tugmasi", urls == ["https://bot.example.com/app/?tab=post"] and getattr(mp._manual_preview_markup(c, "uz").inline_keyboard[0][0], "web_app", None) is not None, str(urls))
for lang in ("uz", "ru", "en"):
    lab = mp._manual_preview_markup(c, lang).inline_keyboard[0][0].text
    check(f"[{lang}] Mini App tugma yorlig'i <= 18 belgi: {lab}", len(lab) <= 18)

# media (rasm) va albom qoralamada saqlanadi
saved_drafts.clear()
c2 = ctx(**{mp.UD_POST_TYPE: "photo", mp.UD_FILE_ID: "PHOTO_ID", mp.UD_CONTENT: "Sarlavha"})
asyncio.run(mp._sync_miniapp_draft(c2, 777))
check("rasmli post qoralamada: tur=photo, file_id saqlangan", saved_drafts and saved_drafts[0][1].get("post_type") == "photo" and saved_drafts[0][1].get("file_id") == "PHOTO_ID")
saved_drafts.clear()
import json  # noqa: E402

album = json.dumps([{"type": "photo", "file_id": "A", "caption": ""}, {"type": "video", "file_id": "B", "caption": ""}])
c3 = ctx(**{mp.UD_POST_TYPE: "album", mp.UD_FILE_ID: album, mp.UD_CONTENT: ""})
asyncio.run(mp._sync_miniapp_draft(c3, 777))
check("albom qoralamada: tur=album, ikkala fayl saqlangan", saved_drafts and saved_drafts[0][1].get("post_type") == "album" and "B" in (saved_drafts[0][1].get("file_id") or ""))
saved_drafts.clear()
c4 = ctx(**{mp.UD_CONTENT: "   "})
asyncio.run(mp._sync_miniapp_draft(c4, 777))
check("bo'sh post: qoralama yozilmaydi, tugma yo'q", not saved_drafts and not c4.user_data.get(mp.UD_MA_URL))

# yuborilgach / bekor qilingach qoralama o'chadi (Mini App'da eski post qolmaydi)
m = Msg()
asyncio.run(mp._finalize(m, ctx(), 777, "uz", "Tayyor"))
check("yakunlanganda qoralama o'chiriladi", dropped == [777], str(dropped))
for k in ("MINIAPP_ENABLED", "MINIAPP_URL", "MINIAPP_PROXY_ASSERT_EDGE_ONLY"):
    os.environ.pop(k, None)
dropped.clear()
asyncio.run(mp._finalize(Msg(), ctx(), 777, "uz", "Tayyor"))
check("Mini App o'chiq: bazaga hech narsa tegmaydi", dropped == [])

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(1 if failed else 0)
