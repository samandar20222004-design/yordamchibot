#!/usr/bin/env python3
"""Mini App — API endpointlari, ruxsat (beta), ownership, xatolar, DB ijrochisi.

Muhit: aiohttp TestClient + SOXTA kursor (in-memory model). Haqiqiy PostgreSQL
YO'Q: SQL matni/parametrlari kontrakti tekshiriladi (egalik sharti SQL'da, xato
bo'sh ro'yxatga aylanmasi). Real DB ownership/statement_timeout testi alohida
fayl (`miniapp_db_real_test.py`) — PostgreSQL bo'lmasa SKIP/BLOCKED.
"""
from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import logging
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

import psycopg2  # noqa: E402
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from miniapp_api import app as appmod  # noqa: E402
from miniapp_api.access import evaluate_access  # noqa: E402
from miniapp_api.db import ReadOnlyRunner  # noqa: E402
from miniapp_api.errors import ApiError, catalog_codes, message_for  # noqa: E402
from miniapp_api.ratelimit import StrictLimiter  # noqa: E402
from miniapp_api.service import MiniAppService, _config_invite_only, _is_admin  # noqa: E402
from miniapp_api.settings import load_settings  # noqa: E402

T = Counter("MINI APP — API (soxta kursor, TestClient)")
UTC = timezone.utc
DB_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
SECRET_SQL = "password=hunter2 SELECT secret FROM users"


# ------------------------------------------------------------------ model
class Model:
    def __init__(self):
        self.users = {}
        self.channels = []   # (owner, channel_id, title, active, deleted)
        self.posts = []      # dict
        self.beta_raw = None
        self.log = []
        self.fail_on = None
        self.tx_calls = 0

    def add_user(self, uid, *, plan="free", expires=None, role="user", deleted=False,
                 lang="uz", name="User", ai_today=0, credits=5):
        self.users[uid] = (uid, f"u{uid}", name, lang, plan, expires, role, credits,
                           ai_today, deleted, DB_NOW)


class Cursor:
    def __init__(self, m):
        self.m, self._rows = m, []

    def execute(self, sql, params=()):
        m = self.m
        m.log.append((" ".join(sql.split()), tuple(params)))
        if m.fail_on and m.fail_on in sql:
            raise psycopg2.OperationalError(SECRET_SQL)
        s = " ".join(sql.split())
        if s.startswith("SET LOCAL"):
            self._rows = []
        elif "FROM users WHERE user_id = %s" in s:
            row = m.users.get(params[0])
            self._rows = [row] if row else []
        elif "FROM system_settings" in s:
            self._rows = [(m.beta_raw,)] if m.beta_raw is not None else []
        elif s.startswith("SELECT COUNT(*) FROM channels"):
            self._rows = [(len([c for c in m.channels if c[0] == params[0] and c[3] and not c[4]]),)]
        elif "FROM channels c" in s and "LATERAL" in s:
            # (channel_id, title, pending_posts, member_count, snapshot_date) — haqiqiy SELECT shakli; params = (kunlar, user_id, limit)
            rows = [(c[1], c[2], 0, None, None) for c in m.channels if c[0] == params[1] and c[3] and not c[4]]
            self._rows = rows[: params[2]]
        elif s.startswith("SELECT COUNT(*), MIN(scheduled_time) FROM scheduled_posts"):
            mine = [p for p in m.posts if p["owner"] == params[0] and p["status"] == "pending"]
            self._rows = [(len(mine), min((p["time"] for p in mine), default=None))]
        elif s.startswith("SELECT status, COUNT(*) FROM scheduled_posts"):
            counts = {}
            for p in m.posts:
                if p["owner"] == params[0]:
                    counts[p["status"]] = counts.get(p["status"], 0) + 1
            self._rows = list(counts.items())
        elif s.startswith("SELECT COUNT(*) FROM scheduled_posts"):
            mine = [p for p in m.posts if p["owner"] == params[0] and p["status"] == "pending"]
            self._rows = [(len(mine),)]
        elif "FROM scheduled_posts sp" in s:
            _prev, uid, off, lim = params
            mine = sorted([p for p in m.posts if p["owner"] == uid and p["status"] == "pending"],
                          key=lambda p: (p["time"], p["id"]))[off: off + lim]
            self._rows = [(p["id"], p["channel_id"], p.get("title"), "text", p["content"][:200],
                           False, p["time"], p["id"], "none", "pending") for p in mine]
        else:
            raise AssertionError("kutilmagan SQL: " + s)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


def tx_factory_for(model):
    @contextmanager
    def factory():
        model.tx_calls += 1
        yield Cursor(model)
    return factory


# --------------------------------------------------------------- yordamchi
def settings_for(**over):
    base = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                          "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    return dataclasses.replace(base, **over) if over else base


class NullLimiter:
    def __init__(self):
        self.calls = []

    async def hit(self, bucket, subject, *, limit, window):
        self.calls.append((bucket, subject))


@contextmanager
def running(model, *, settings=None, limiter=None, invite_only=False, admin=lambda u, r: False,
            runner=None):
    async def _noop():
        pass
    settings = settings or settings_for()
    runner = runner or ReadOnlyRunner(statement_timeout_ms=settings.db_statement_timeout_ms,
                                      max_inflight=settings.max_inflight_db,
                                      tx_factory=tx_factory_for(model))
    service = MiniAppService(settings, runner, invite_only_getter=lambda: invite_only,
                             admin_check=admin)
    api = appmod.build_api_app(settings, runner=runner, limiter=limiter or NullLimiter(),
                               clock=lambda: NOW, service=service)
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)
    app.router.add_route("*", "/api/{tail:.*}", appmod._api_not_found)
    yield app, runner


def hdr(uid=4242, **kw):
    return {"Authorization": "tma " + make_init_data(uid, **kw)}


LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)


async def call(app, method, path, **kw):
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.request(method, path, **kw)
        try:
            body = await resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return resp.status, body, resp.headers
    finally:
        await client.close()


def world():
    m = Model()
    m.add_user(1, lang="uz", name="Alice")
    m.add_user(2, lang="ru", name="Bob")
    m.channels += [(1, "-1001", "Alice kanal", True, False), (1, "-1002", "Alice 2", True, False),
                   (1, "-1003", "Alice o'chgan", False, True), (2, "-2001", "Bob kanal", True, False)]
    base = DB_NOW + timedelta(days=1)
    for i in range(7):
        m.posts.append({"owner": 1, "id": 100 + i, "channel_id": "-1001", "title": "Alice kanal",
                        "status": "pending", "content": f"alice post {i}", "time": base + timedelta(hours=i)})
    m.posts.append({"owner": 1, "id": 200, "channel_id": "-1001", "status": "sent",
                    "content": "alice sent", "time": base})
    m.posts.append({"owner": 2, "id": 300, "channel_id": "-2001", "title": "Bob kanal",
                    "status": "pending", "content": "BOB SECRET", "time": base})
    return m


# ----------------------------------------------------------------- testlar
def test_health_and_errors():
    print("\n== 1. Health, xato formati, 404/405 ==")
    m = world()
    with running(m) as (app, _):
        st, body, h = run(call(app, "GET", "/api/v1/health"))
        T.check("health auth'siz 200", st == 200 and body["status"] == "ok")
        T.check("health no-store", h.get("Cache-Control") == "no-store")
        T.check("health DB'ga tegmaydi", m.tx_calls == 0)
        st, body, h = run(call(app, "GET", "/api/v1/me"))
        T.check("Authorization yo'q -> 401 unauthorized", st == 401 and body["error"]["code"] == "unauthorized")
        e = body["error"]
        T.check("xato formati: code/message/request_id/retry_after",
                set(e) == {"code", "message", "request_id", "retry_after", "field"} and e["request_id"])
        T.check("X-Request-Id sarlavhasi javob tanasi bilan bir xil", h.get("X-Request-Id") == e["request_id"])
        T.check("DB'ga auth'siz tegilmadi", m.tx_calls == 0)
        st, body, _ = run(call(app, "GET", "/api/v1/me", headers={"Accept-Language": "ru-RU,ru;q=0.9"}))
        T.check("xato matni Accept-Language bo'yicha (ru)", body["error"]["message"] == message_for("unauthorized", "ru"))
        st, body, _ = run(call(app, "GET", "/api/v1/me", headers={"Accept-Language": "en-US"}))
        T.check("xato matni (en)", body["error"]["message"] == message_for("unauthorized", "en"))
        st, body, _ = run(call(app, "GET", "/api/v1/me", headers={"Accept-Language": "de"}))
        T.check("noma'lum til -> uz", body["error"]["message"] == message_for("unauthorized", "uz"))
        st, body, _ = run(call(app, "POST", "/api/v1/me", headers=hdr()))
        T.check("POST /me -> 405 JSON", st == 405 and body["error"]["code"] == "method_not_allowed")
        st, body, _ = run(call(app, "GET", "/api/v1/nope", headers=hdr()))
        T.check("/api/v1/nope -> JSON 404", st == 404 and body["error"]["code"] == "not_found")
        st, body, _ = run(call(app, "GET", "/api/other"))
        T.check("/api/other -> JSON 404", st == 404 and body["error"]["code"] == "not_found")
        st, body, _ = run(call(app, "POST", "/api/v1/scheduled-posts", headers=hdr(), json={"a": 1}))
        T.check("yozuvchi endpoint yo'q (POST -> 405)", st == 405)
        for lang in ("uz", "ru", "en"):
            T.check(f"barcha kodlar {lang} da mavjud va bo'sh emas",
                    all(message_for(c, lang) for c in catalog_codes()))
        T.check("tillar bo'yicha matnlar farqli", all(
            len({message_for(c, lg) for lg in ("uz", "ru", "en")}) == 3 for c in catalog_codes()))


def test_auth_paths():
    print("\n== 2. Auth: noto'g'ri imzo, muddat ==")
    m = world()
    with running(m) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers={"Authorization": "tma " + make_init_data(1, token="987654321:OTHERtokenZZZZZZZZZZZZZZZZZZZZZZ")}))
        T.check("boshqa token imzosi -> 401", st == 401 and b["error"]["code"] == "unauthorized")
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1, auth_date=NOW - 4000)))
        T.check("eskirgan -> 401 auth_expired", st == 401 and b["error"]["code"] == "auth_expired")
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1, auth_date=NOW + 3600)))
        T.check("kelajak -> 401", st == 401)
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers={"Authorization": "Bearer x"}))
        T.check("noto'g'ri sxema -> 401", st == 401)
        T.check("DB'ga tegilmadi", m.tx_calls == 0)
    bad = settings_for(bot_token="")
    with running(m, settings=bad) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("BOT_TOKEN yo'q -> 503 auth_unavailable (fail-closed)",
                st == 503 and b["error"]["code"] == "auth_unavailable")
    with running(m, settings=settings_for(bot_token="nonsense")) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("BOT_TOKEN yaroqsiz -> 503", st == 503)
        T.check("health baribir ishlaydi", run(call(app, "GET", "/api/v1/health"))[0] == 200)


def test_endpoints_and_ownership():
    print("\n== 3. /me, /channels, /scheduled-posts + ownership ==")
    m = world()
    with running(m) as (app, _):
        st, me, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("/me 200", st == 200)
        T.check("/me: user id imzodan", me["user"]["id"] == 1 and me["user"]["name"] == "Alice")
        T.check("/me: kanallar soni (o'chirilgani hisoblanmaydi)", me["usage"]["channels"] == 2)
        T.check("/me: kutilayotgan postlar (faqat pending, faqat o'ziniki)", me["usage"]["pending_posts"] == 7)
        T.check("/me: free tarif", me["plan"]["type"] == "free" and me["plan"]["is_pro"] is False)
        T.check("/me: limitlar bor", {"max_channels", "daily_ai_requests", "queued_posts"} <= set(me["plan"]["limits"]))
        T.check("/me: bot username sozlanmagan -> null (taxmin yo'q)", me["bot"]["username"] is None)
        T.check("/me: next_post_at ISO Z", me["next_post_at"].endswith("Z"))
        st, ch, _ = run(call(app, "GET", "/api/v1/channels", headers=hdr(1)))
        T.check("/channels faqat Alice kanallari", [c["id"] for c in ch["items"]] == ["-1001", "-1002"])
        T.check("/channels: Bob kanali ko'rinmaydi", "-2001" not in json.dumps(ch))
        st, ch2, _ = run(call(app, "GET", "/api/v1/channels", headers=hdr(2)))
        T.check("Bob faqat o'z kanalini ko'radi", [c["id"] for c in ch2["items"]] == ["-2001"])
        st, sp, _ = run(call(app, "GET", "/api/v1/scheduled-posts?limit=3&offset=0", headers=hdr(1)))
        T.check("/scheduled-posts: faqat pending (7), sent yo'q", sp["total"] == 7 and len(sp["items"]) == 3)
        T.check("pagination: has_more", sp["has_more"] is True)
        st, sp2, _ = run(call(app, "GET", "/api/v1/scheduled-posts?limit=3&offset=6", headers=hdr(1)))
        T.check("oxirgi sahifa has_more=false", len(sp2["items"]) == 1 and sp2["has_more"] is False)
        T.check("Bob postlari Alice javobida yo'q", "BOB SECRET" not in json.dumps(sp) + json.dumps(sp2))
        T.check("holat 'sent' post ko'rinmaydi", "alice sent" not in json.dumps(sp) + json.dumps(sp2))
        st, bsp, _ = run(call(app, "GET", "/api/v1/scheduled-posts", headers=hdr(2)))
        T.check("Bob faqat o'z postini ko'radi", [i["preview"] for i in bsp["items"]] == ["BOB SECRET"])
        # user_id soxtalashtirish
        st, me2, _ = run(call(app, "GET", "/api/v1/me?user_id=2&uid=2", headers=hdr(1)))
        T.check("query'dagi user_id e'tiborsiz (Alice qoladi)", me2["user"]["id"] == 1)
        st, ch3, _ = run(call(app, "GET", "/api/v1/channels?user_id=2", headers={**hdr(1), "X-User-Id": "2"}))
        T.check("X-User-Id/user_id e'tiborsiz", [c["id"] for c in ch3["items"]] == ["-1001", "-1002"])
        # SQL kontrakti
        sqls = [(s, p) for s, p in m.log if "scheduled_posts" in s or "FROM channels" in s]
        T.check("har bir egalik so'rovi 'user_id = %s' shartiga ega",
                all("user_id = %s" in s for s, _ in sqls))
        T.check("scheduled-posts so'rovi status='pending' SQL ichida",
                all("status = 'pending'" in s for s, _ in sqls
                    if "scheduled_posts" in s and "GROUP BY status" not in s))  # /me hisob so'rovi: egasi bo'yicha, status bo'yicha guruhlaydi
        T.check("so'rov parametrlari (bind) ishlatilgan, ID matnga yopishtirilmagan",
                all("1001" not in s and " 1 " not in s for s, _ in sqls))
        T.check("channels so'rovi soft-delete va is_active filtrlari bilan",
                all("deleted_at IS NULL" in s and "is_active = TRUE" in s for s, _ in m.log if "FROM channels" in s))
        T.check("scheduled JOIN channels egasi bo'yicha (kanal nomi sizmaydi)",
                any("c.user_id = sp.user_id" in s for s, _ in m.log))
        T.check("hamma so'rovlar SET LOCAL statement_timeout'dan keyin",
                m.log[0][0].startswith("SET LOCAL statement_timeout") and m.log[1][0].startswith("SET LOCAL lock_timeout"))
        bad_sql = [s for s, _ in m.log if any(w in s.upper() for w in ("INSERT ", "UPDATE ", "DELETE "))]
        T.check("hech qanday yozuvchi SQL yo'q", not bad_sql)


def test_pagination_validation():
    print("\n== 4. Pagination validatsiyasi ==")
    m = world()
    with running(m) as (app, _):
        for q in ("limit=0", "limit=51", "limit=abc", "limit=-1", "offset=-1", "offset=abc",
                  "offset=100001", "limit=1.5", "limit=", "limit=99999999", "offset=%20"):
            st, b, _ = run(call(app, "GET", f"/api/v1/scheduled-posts?{q}", headers=hdr(1)))
            T.check(f"{q} -> 400 bad_request", st == 400 and b["error"]["code"] == "bad_request")
        st, b, _ = run(call(app, "GET", "/api/v1/scheduled-posts?limit=50&offset=100000", headers=hdr(1)))
        T.check("chegaraviy limit=50, offset=100000 -> 200", st == 200 and b["items"] == [])
        st, b, _ = run(call(app, "GET", "/api/v1/scheduled-posts", headers=hdr(1)))
        T.check("sukut limit=20", st == 200 and b["limit"] == 20 and b["offset"] == 0)
        st, b, _ = run(call(app, "GET", "/api/v1/scheduled-posts?limit=1&limit=2", headers=hdr(1)))
        T.check("takroriy limit parametri xavfsiz (400 yoki aniq qiymat)", st in (200, 400))
        T.check("javobda kiritilgan qiymat qaytarilmaydi (xato matni)",
                "abc" not in json.dumps(run(call(app, "GET", "/api/v1/scheduled-posts?limit=abc", headers=hdr(1)))[1]))


def test_plan():
    print("\n== 5. PRO holati faqat bazadan ==")
    m = world()
    m.add_user(3, plan="pro", expires=DB_NOW + timedelta(days=10))
    m.add_user(4, plan="pro", expires=DB_NOW - timedelta(days=1))
    m.add_user(5, plan="enterprise", expires=None)
    m.add_user(6, plan="weird")
    with running(m) as (app, _):
        def me(uid):
            return run(call(app, "GET", "/api/v1/me", headers=hdr(uid)))[1]
        p = me(3)["plan"]
        T.check("faol PRO", p["type"] == "pro" and p["is_pro"] and p["expires_at"].endswith("Z"))
        T.check("PRO limitlari katta", p["limits"]["max_channels"] > 3)
        p = me(4)["plan"]
        T.check("muddati o'tgan PRO -> free (yozmasdan)", p["type"] == "free" and not p["is_pro"] and p["expires_at"] is None)
        p = me(5)["plan"]
        T.check("muddatsiz enterprise -> PRO", p["is_pro"] and p["expires_at"] is None)
        T.check("noma'lum tarif -> free", me(6)["plan"]["type"] == "free")
        T.check("o'qish tranzaksiyasida UPDATE yo'q", not any("UPDATE" in s for s, _ in m.log))


def test_access():
    print("\n== 6. Ruxsat: ro'yxatdan o'tmagan / pending / approved / admin ==")
    m = world()
    m.add_user(7, deleted=True)
    m.add_user(8)
    m.add_user(9)
    m.add_user(10)
    state = {"enabled": None, "approved": {"8": {"source": "code"}}, "pending": {"9": {}}}

    def call_me(uid, *, invite_only=True, admin=lambda u, r: False, raw=state):
        m.beta_raw = json.dumps(raw) if raw is not None and not isinstance(raw, str) else raw
        with running(m, invite_only=invite_only, admin=admin) as (app, _):
            return run(call(app, "GET", "/api/v1/me", headers=hdr(uid)))

    st, b, _ = call_me(999)
    T.check("users'da yo'q -> 403 not_registered", st == 403 and b["error"]["code"] == "not_registered")
    users_before = dict(m.users)
    T.check("API foydalanuvchi YARATMADI", m.users == users_before and 999 not in m.users)
    st, b, _ = call_me(7)
    T.check("soft-delete qilingan -> 403 not_registered", st == 403 and b["error"]["code"] == "not_registered")
    st, b, _ = call_me(8)
    T.check("approved -> 200", st == 200)
    st, b, _ = call_me(9)
    T.check("pending -> 403 beta_access_required", st == 403 and b["error"]["code"] == "beta_access_required")
    st, b, _ = call_me(10)
    T.check("approved/pending'da yo'q (eski foydalanuvchi) -> 200 (bot qoidasi REASON_EXISTING bilan bir xil)",
            st == 200)
    st, b, _ = call_me(9)
    T.check("pending baribir RAD (eski foydalanuvchi qoidasi pending'ga tegmaydi)",
            st == 403 and b["error"]["code"] == "beta_access_required")
    st, b, _ = call_me(10, admin=lambda u, r: u == 10)
    T.check("admin -> 200", st == 200)
    st, b, _ = call_me(10, invite_only=False)
    T.check("darvoza o'chiq (config) -> 200", st == 200)
    st, b, _ = call_me(10, raw={"enabled": False, "approved": {}, "pending": {}})
    T.check("holat 'enabled=false' override -> 200", st == 200)
    st, b, _ = call_me(9, invite_only=False, raw={"enabled": True, "approved": {}, "pending": {"9": {}}})
    T.check("holat 'enabled=true' override config'dan ustun (pending) -> 403", st == 403)
    st, b, _ = call_me(10, raw=None)
    T.check("beta holati yo'q (qator yo'q) = bo'sh holat -> eski foydalanuvchi 200", st == 200)
    for label, raw in {"buzuq JSON": "{bad json", "ro'yxat": "[1,2]", "approved ro'yxat": '{"approved":[1]}',
                       "pending satr": '{"pending":"x"}', "enabled satr": '{"enabled":"yes"}'}.items():
        st, b, _ = call_me(8, raw=raw)
        T.check(f"beta holati yaroqsiz ({label}) -> 503, ruxsat YO'Q",
                st == 503 and b["error"]["code"] == "service_unavailable")
    # beta holati o'zgarmaydi
    m.beta_raw = json.dumps(state)
    snap = m.beta_raw
    call_me(9)
    call_me(10)
    T.check("API beta holatini O'ZGARTIRMADI (pending kengaymadi)", m.beta_raw == snap)
    T.check("beta uchun yozuvchi SQL yo'q", not any(("INSERT" in s or "UPDATE" in s) for s, _ in m.log))
    # to'g'ridan-to'g'ri evaluate_access
    d = evaluate_access(5, user_exists=True, deleted=False, is_admin=False, beta_raw=None, config_invite_only=True)
    T.check("evaluate_access: invite_only + ro'yxatda yo'q -> eski foydalanuvchi, ruxsat", d.allowed and d.reason == "existing_user")
    d = evaluate_access(5, user_exists=True, deleted=False, is_admin=False,
                        beta_raw='{"pending": {"5": {}}}', config_invite_only=True)
    T.check("evaluate_access: invite_only + pending -> rad", not d.allowed)
    d = evaluate_access(5, user_exists=True, deleted=False, is_admin=False, beta_raw=None, config_invite_only=False)
    T.check("evaluate_access: darvoza o'chiq -> ruxsat", d.allowed)
    T.check("default admin tekshiruvi: ADMIN_ID (legacy) admin", _is_admin(123456789, None) is True)
    T.check("default admin tekshiruvi: oddiy foydalanuvchi emas", _is_admin(555, "user") is False)
    T.check("default admin: DB roli admin", _is_admin(555, "admin") is True)
    T.check("config invite_only bool qaytaradi", isinstance(_config_invite_only(), bool))


def test_db_failures():
    print("\n== 7. DB xatosi bo'sh ma'lumotga aylanmaydi ==")
    m = world()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        for path, needle in (("/api/v1/channels", "FROM channels c"),
                             ("/api/v1/scheduled-posts", "FROM scheduled_posts sp"),
                             ("/api/v1/me", "FROM users WHERE user_id"),
                             ("/api/v1/me", "FROM system_settings")):
            m.fail_on = needle
            with running(m) as (app, _):
                st, b, h = run(call(app, "GET", path, headers=hdr(1)))
            T.check(f"{path} ({needle[:22]}…) DB xatosi -> 503 (bo'sh ro'yxat emas)",
                    st == 503 and b["error"]["code"] == "service_unavailable" and "items" not in b)
            T.check("503 da Retry-After bor", h.get("Retry-After") is not None)
            T.check("javobda SQL/parol tafsiloti yo'q", "hunter2" not in json.dumps(b) and "SELECT" not in json.dumps(b))
        m.fail_on = None
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
    out = stream.getvalue()
    T.check("serverga xato qayd etildi (sinf nomi)", "OperationalError" in out)
    T.check("logda parol/SQL matni yo'q", "hunter2" not in out)
    # kutilmagan xato -> 500, ichki matn yo'q
    class Boom(MiniAppService):
        async def me(self, uid):
            raise RuntimeError("internal-secret-xyz")
    settings = settings_for()
    runner = ReadOnlyRunner(statement_timeout_ms=1000, max_inflight=2, tx_factory=tx_factory_for(m))
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW,
                               service=Boom(settings, runner))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)
    st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
    T.check("kutilmagan xato -> 500 internal_error, matn sizmaydi",
            st == 500 and b["error"]["code"] == "internal_error" and "internal-secret" not in json.dumps(b))


def test_rate_limits_and_https():
    print("\n== 8. Limitlar va HTTPS ==")
    m = world()

    class Recorder(NullLimiter):
        def __init__(self, fail_bucket=None):
            super().__init__()
            self.fail_bucket = fail_bucket

        async def hit(self, bucket, subject, *, limit, window):
            self.calls.append((bucket, subject))
            if bucket == self.fail_bucket:
                raise ApiError("service_unavailable", retry_after=30)

    lim = Recorder(fail_bucket="auth_ip")
    with running(m, limiter=lim) as (app, _):
        st, b, h = run(call(app, "GET", "/api/v1/me"))   # auth'siz ham
        T.check("auth limiteri xatosi -> 503 (HMAC'dan OLDIN)", st == 503 and b["error"]["code"] == "service_unavailable")
        T.check("503 Retry-After", h.get("Retry-After") == "30")
        T.check("limiter DB va auth'dan oldin chaqirildi", lim.calls[0][0] == "auth_ip" and m.tx_calls == 0)
        st, _, _ = run(call(app, "GET", "/api/v1/health"))
        T.check("health limiterga bog'liq emas", st == 200)
    lim = Recorder()
    with running(m, limiter=lim) as (app, _):
        run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("IP va foydalanuvchi bucketlari", [c[0] for c in lim.calls] == ["auth_ip", "user"] and lim.calls[1][1] == "1")
    lim = Recorder(fail_bucket="user")
    with running(m, limiter=lim) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("user limiteri xatosi -> 503", st == 503)
    # haqiqiy StrictLimiter bilan 429
    from services.cache_backend import MemoryCacheBackend
    mem = MemoryCacheBackend()
    real = StrictLimiter(require_shared=False, backend_getter=lambda: mem)
    s = settings_for(rate_user_limit=2, rate_auth_limit=100)
    with running(m, limiter=real, settings=s) as (app, _):
        async def many():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                codes = []
                for _ in range(4):
                    r = await client.get("/api/v1/me", headers=hdr(1))
                    codes.append((r.status, r.headers.get("Retry-After")))
                r2 = await client.get("/api/v1/me", headers=hdr(2))
                return codes, r2.status
            finally:
                await client.close()
        codes, other = run(many())
        T.check("user limiti oshgach 429 + Retry-After", [c[0] for c in codes] == [200, 200, 429, 429] and codes[2][1] == "60")
        T.check("boshqa foydalanuvchiga ta'sir qilmaydi", other == 200)
    # HTTPS
    s = settings_for(require_https=True)
    with running(m, settings=s) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("HTTPS majburiy: http -> 400 https_required", st == 400 and b["error"]["code"] == "https_required")
        st, _, _ = run(call(app, "GET", "/api/v1/me", headers={**hdr(1), "X-Forwarded-Proto": "https"}))
        T.check("edge-only + X-Forwarded-Proto: https -> 200", st == 200)
        st, _, _ = run(call(app, "GET", "/api/v1/health"))
        T.check("health HTTPS talab qilmaydi", st == 200)
    s = settings_for(require_https=True, proxy_assert_edge_only=False,
                     trusted_proxy_cidrs=load_settings({"MINIAPP_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}).trusted_proxy_cidrs)
    with running(m, settings=s) as (app, _):
        st, b, _ = run(call(app, "GET", "/api/v1/me", headers={**hdr(1), "X-Forwarded-Proto": "https"}))
        T.check("ishonchsiz peer (127.0.0.1) + soxta X-Forwarded-Proto -> 400", st == 400)


def test_runner():
    print("\n== 9. DB ijrochisi: timeout semantikasi, semafor, tranzaksiya ==")
    m = world()
    gate = threading.Event()
    started = threading.Event()

    @contextmanager
    def slow_factory():
        started.set()
        gate.wait(5)
        yield Cursor(m)

    s = settings_for(request_timeout_seconds=0.3, max_inflight_db=1)
    runner = ReadOnlyRunner(statement_timeout_ms=1000, max_inflight=1, tx_factory=slow_factory,
                            queue_wait_seconds=0)  # navbatsiz: tez-503 yo'lini tekshiramiz
    with running(m, settings=s, runner=runner) as (app, _):
        async def scenario():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                t0 = time.monotonic()
                r1 = await client.get("/api/v1/me", headers=hdr(1))
                dt = time.monotonic() - t0
                inflight_after = runner.inflight
                r2 = await client.get("/api/v1/channels", headers=hdr(1))  # semafor band
                b2 = await r2.json()
                gate.set()
                for _ in range(50):
                    if runner.inflight == 0:
                        break
                    await asyncio.sleep(0.05)
                return r1.status, dt, inflight_after, r2.status, b2, runner.inflight
            finally:
                gate.set()
                await client.close()
        s1, dt, infl, s2, b2, final = run(scenario())
    T.check("HTTP timeout -> 503 (mijoz tez javob oladi)", s1 == 503 and dt < 2.0)
    T.check("HTTP timeout DB threadini TO'XTATMAYDI (inflight=1 qoladi)", infl == 1 and started.is_set())
    T.check("semafor thread tugaguncha band: 2-so'rov darhol 503", s2 == 503 and b2["error"]["code"] == "service_unavailable")
    T.check("thread tugagach resurs bo'shatildi (inflight=0)", final == 0)
    test_runner_queue(m)
    # semafor qayta ishlaydi
    runner2 = ReadOnlyRunner(statement_timeout_ms=1000, max_inflight=1, tx_factory=tx_factory_for(m))
    with running(m, runner=runner2) as (app, _):
        st, _, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        st2, _, _ = run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        T.check("semafor muvaffaqiyatdan keyin bo'shaydi", st == 200 and st2 == 200 and runner2.inflight == 0)
    # xatoda ham bo'shaydi
    m.fail_on = "FROM users"
    with running(m, runner=runner2) as (app, _):
        run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
        run(call(app, "GET", "/api/v1/me", headers=hdr(1)))
    m.fail_on = None
    T.check("DB xatosidan keyin ham semafor bo'shaydi", runner2.inflight == 0)

    # Haqiqiy db_transaction chaqiruvi: read-only, commit=False (autocommit emas)
    import database as dbmod
    seen = {}

    @contextmanager
    def spy(commit=True, isolation_level=None, readonly=False):
        seen.update(commit=commit, readonly=readonly, iso=isolation_level)
        yield Cursor(m)

    original = dbmod.db_transaction
    dbmod.db_transaction = spy
    try:
        runner3 = ReadOnlyRunner(statement_timeout_ms=1500, max_inflight=1)  # default factory
        m.log.clear()
        res = run(runner3.run(lambda cur: cur.execute(
            "SELECT COUNT(*) FROM channels WHERE user_id = %s", (1,)) or "ok"))
    finally:
        dbmod.db_transaction = original
    T.check("default factory: db_transaction(commit=False, readonly=True)", seen == {"commit": False, "readonly": True, "iso": None})
    T.check("statement_timeout SET LOCAL (global SET emas)",
            m.log[0][0] == "SET LOCAL statement_timeout = 1500" and not any(s.startswith("SET ") and not s.startswith("SET LOCAL") for s, _ in m.log))
    T.check("natija qaytdi", res == "ok")
    # fast_read (autocommit) rejimi o'chirilganini kod darajasida tasdiqlash
    tx = dbmod._Transaction(commit=False, readonly=True)
    T.check("readonly=True tranzaksiya autocommit (fast_read) EMAS", tx.fast_read is False)
    T.check("oddiy o'qish fast_read (autocommit) — shuning uchun alohida tx kerak",
            dbmod._Transaction(commit=False).fast_read is True)


def test_runner_queue(m):
    print("\n== 9b. DB ijrochisi: burst navbati (darhol 503 o'rniga cheklangan kutish) ==")

    def slow_runner(hold, **kw):
        @contextmanager
        def factory():
            time.sleep(hold)
            yield Cursor(m)
        return ReadOnlyRunner(statement_timeout_ms=1000, tx_factory=factory, **kw)

    async def burst(runner, n):
        async def one():
            try:
                return await runner.run(lambda cur: "ok")
            except ApiError as err:
                return err.code
        res = await asyncio.gather(*[one() for _ in range(n)])
        return {k: res.count(k) for k in set(res)}

    r = slow_runner(0.05, max_inflight=2, queue_wait_seconds=3.0, max_queue=64)
    out = run(burst(r, 20))
    T.check("navbat bilan: 20 parallel so'rov, 2 slot -> hammasi bajariladi (503 yo'q)", out == {"ok": 20}, str(out))
    T.check("navbatdan keyin slotlar bo'sh (inflight=0, waiting=0)", r.inflight == 0 and r.waiting == 0)

    r = slow_runner(0.3, max_inflight=1, queue_wait_seconds=3.0, max_queue=2)
    out = run(burst(r, 6))
    T.check("max_queue=2: 1 bajariladi + 2 kutadi = 3 ok, ortiqchasi (3) darhol 503", out == {"ok": 3, "service_unavailable": 3}, str(out))

    r = slow_runner(0.6, max_inflight=1, queue_wait_seconds=0.1, max_queue=10)
    t0 = time.monotonic()
    out = run(burst(r, 3))
    T.check("kutish tugadi (0.1 s) -> 503; birinchisi bajarildi", out == {"ok": 1, "service_unavailable": 2}, str(out))
    T.check("kutish chegarasi tez (503 ~0.1 s da, bajarilish tugashini kutmaydi)", time.monotonic() - t0 < 1.5)

    async def cancel_while_waiting():
        r2 = slow_runner(0.3, max_inflight=1, queue_wait_seconds=5.0, max_queue=10)
        first = asyncio.ensure_future(r2.run(lambda cur: "first"))
        await asyncio.sleep(0.05)
        waiter = asyncio.ensure_future(r2.run(lambda cur: "waiter"))
        await asyncio.sleep(0.05)
        waiter.cancel()
        try:
            await waiter
        except asyncio.CancelledError:
            pass
        await first
        await asyncio.sleep(0.05)
        again = await asyncio.wait_for(r2.run(lambda cur: "again"), 2.0)
        return r2.waiting, r2.inflight, again
    waiting, inflight, again = run(cancel_while_waiting())
    T.check("navbatda kutayotgan so'rov bekor qilinsa slot YO'QOLMAYDI (keyingi so'rov bajariladi)",
            again == "again" and waiting == 0 and inflight == 0, f"{waiting},{inflight},{again}")


def test_logging_secrecy():
    print("\n== 10. Loglarda Authorization/initData/token yo'q ==")
    m = world()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    init = make_init_data(1, extra={"start_param": "SECRETSTART"})
    try:
        with running(m) as (app, _):
            run(call(app, "GET", "/api/v1/me", headers={"Authorization": "tma " + init}))
            run(call(app, "GET", "/api/v1/me", headers={"Authorization": "tma " + init + "x"}))
            run(call(app, "GET", "/api/v1/me?x=" + "SECRETQUERY", headers={"Authorization": "tma bad"}))
        m.fail_on = "FROM users"
        with running(m) as (app, _):
            run(call(app, "GET", "/api/v1/me", headers={"Authorization": "tma " + init}))
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
    out = stream.getvalue()
    hash_value = init.rsplit("hash=", 1)[1]
    T.check("BOT_TOKEN logda yo'q", FAKE_TOKEN not in out)
    T.check("initData (hash) logda yo'q", hash_value not in out)
    T.check("initData maydonlari logda yo'q", "SECRETSTART" not in out and "query_id" not in out)
    T.check("Authorization sarlavhasi logda yo'q", "tma " not in out and "Authorization" not in out)
    T.check("so'rov yo'li va request_id logda bor (kuzatuvchanlik)", "/api/v1/me" in out and "request_id=" in out)


def test_register():
    print("\n== 11. register_miniapp_routes ==")
    good = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "production",
            "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"}
    def mounted(env):
        app = web.Application()
        res = appmod.register_miniapp_routes(app, env=env, limiter=NullLimiter())
        return res, sorted(r.canonical for r in app.router.resources())
    res, routes = mounted({})
    T.check("MINIAPP_ENABLED yo'q -> ulanmaydi", res is False and routes == [])
    res, routes = mounted({"MINIAPP_ENABLED": "0", "BOT_TOKEN": FAKE_TOKEN})
    T.check("MINIAPP_ENABLED=0 -> ulanmaydi", res is False and routes == [])
    res, routes = mounted(good)
    T.check("to'g'ri sozlama: /api/v1, /app ulanadi", res is True and "/api/v1" in routes and "/app/{tail}" in routes)
    for label, over in {"proksi yo'q": {"MINIAPP_PROXY_ASSERT_EDGE_ONLY": ""},
                        "BOT_TOKEN yaroqsiz": {"BOT_TOKEN": "xx"},
                        "production + REQUIRE_SHARED=0": {"MINIAPP_RATE_REQUIRE_SHARED": "0"},
                        "noto'g'ri CIDR": {"MINIAPP_TRUSTED_PROXY_CIDRS": "bad"}}.items():
        res, routes = mounted({**good, **over})
        T.check(f"{label} -> ULANMAYDI (fail-closed)", res is False and routes == [])
    res, routes = mounted({**good, "ENVIRONMENT": "development", "MINIAPP_RATE_REQUIRE_SHARED": "0"})
    T.check("development'da REQUIRE_SHARED=0 -> ulanadi", res is True)


def main() -> int:
    test_health_and_errors()
    test_auth_paths()
    test_endpoints_and_ownership()
    test_pagination_validation()
    test_plan()
    test_access()
    test_db_failures()
    test_rate_limits_and_https()
    test_runner()
    test_logging_secrecy()
    test_register()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
