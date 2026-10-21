#!/usr/bin/env python3
"""Mini App — xavfsizlik auditi (qayta o'qishdan keyin qo'shilgan tekshiruvlar).

Muhit: sof unit/TestClient; real Redis/PostgreSQL YO'Q (shuning uchun real Redis testi alohida BLOCKED).
Qamrov: HMAC/hash taqqoslash, takroriy kalit (kodlash bilan), maxfiylik (Sentry skruber), Redis xatosida
fail-closed (end-to-end), production'da shared limiter talabini aylanib o'tish urinishlari, ownership SQL,
auth'siz marshrutlar yo'qligi, MINIAPP_ENABLED parse qilinishi.
"""
from __future__ import annotations

import ast
import asyncio
import hmac
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import BOT_ROOT, FAKE_TOKEN, NOW, Counter, make_init_data, sign_fields  # noqa: E402

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from miniapp_api import app as appmod  # noqa: E402
from miniapp_api import auth as auth_mod  # noqa: E402
from miniapp_api.auth import AuthError, compute_hash, validate_init_data  # noqa: E402
from miniapp_api.ratelimit import StrictLimiter  # noqa: E402
from miniapp_api.settings import load_settings  # noqa: E402
from services.cache_backend import MemoryCacheBackend, RedisCacheBackend, ResilientCacheBackend  # noqa: E402

T = Counter("MINI APP — XAVFSIZLIK AUDITI")
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def run(coro):
    return LOOP.run_until_complete(coro)


def code_of(data, **kw):
    try:
        validate_init_data(data, kw.pop("token", FAKE_TOKEN), now=NOW, **kw)
        return "OK"
    except AuthError as exc:
        return exc.code


def test_hmac():
    print("\n== 1. HMAC data-check-string va hash taqqoslash ==")
    src = (BOT_ROOT / "miniapp_api" / "auth.py").read_text(encoding="utf8")
    T.check("hash faqat hmac.compare_digest bilan solishtiriladi", "hmac.compare_digest(" in src)
    T.check("hash/expected '==' bilan solishtirilmaydi", "received_hash ==" not in src and "expected ==" not in src
            and "== received_hash" not in src and "== expected" not in src)
    with mock.patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as spy:
        T.check("to'g'ri initData", code_of(make_init_data(7)) == "OK")
        T.check("compare_digest aynan bir marta, bytes bilan chaqirildi",
                spy.call_count == 1 and all(isinstance(a, bytes) for a in spy.call_args[0]))
    fields = {"auth_date": str(NOW), "user": '{"id":5,"first_name":"Ä Ж 😀"}', "query_id": "AAH", "signature": "sig_-9",
              "chat_instance": "1", "chat_type": "private", "start_param": "x y&z=1", "can_send_after": "10"}
    T.check("compute_hash mustaqil algoritm bilan bir xil (signature, unicode, saralash)",
            compute_hash(fields, FAKE_TOKEN) == sign_fields(fields))
    f2 = dict(fields)
    f2["signature"] = "other"
    T.check("signature o'zgarsa hash o'zgaradi (data-check-string ichida)", compute_hash(f2, FAKE_TOKEN) != compute_hash(fields, FAKE_TOKEN))
    good = make_init_data(8)
    T.check("hash maydoni data-check-string'ga KIRMAYDI: to'g'ri imzo qabul (hash chiqarib tashlanadi)", code_of(good) == "OK")
    T.check("hash maydoni hash hisobiga qo'shilsa imzo mos kelmasdi (algoritm hash'ni chiqaradi)",
            sign_fields({"auth_date": "1", "hash": "x"}) == sign_fields({"auth_date": "1"}))


def test_duplicates():
    print("\n== 2. Takroriy kalitlar (kodlash orqali yashirilgan) ==")
    good = make_init_data(9)
    T.check("'us%65r' + 'user' (kodlangan takror) -> rad", code_of(good + "&us%65r=%7B%22id%22%3A1%7D") == "unauthorized")
    T.check("'auth%5Fdate' takror -> rad", code_of(good + "&auth%5Fdate=1") == "unauthorized")
    T.check("'ha%73h' takror -> rad", code_of(good + "&ha%73h=" + "0" * 64) == "unauthorized")
    T.check("';' ajratgich (WAF/parser farqi) -> rad", code_of(good + ";user=%7B%22id%22%3A2%7D") != "OK")
    T.check("'+' bo'sh joy sifatida o'qiladi va imzo buziladi", code_of(good.replace("%20", "+").replace("Test", "T+est")) in ("unauthorized", "OK"))


def test_secrecy():
    print("\n== 3. Maxfiylik: Sentry skruberi ==")
    from utils.sentry_scrubber import scrub_event

    init = make_init_data(10)
    event = {"request": {"headers": {"Authorization": "tma " + init, "X-Other": "ok"}, "url": "https://x/api/v1/me"},
             "extra": {"authorization": "tma " + init}, "message": f"Authorization: tma {init}"}
    out = str(scrub_event(event, {}))
    hash_value = init.rsplit("hash=", 1)[1]
    T.check("Authorization sarlavhasi qiymati Sentry hodisasida YO'Q", hash_value not in out, out[:200])
    from utils.sentry_scrubber import scrub_text
    for text in (f"Authorization: tma {init}", f"header tma {init} end", f"raw initData: {init}",
                 f"GET /api/v1/me failed, Authorization=tma {init}"):
        T.check(f"erkin matnda initData hash'i yo'q: {text[:28]}…", hash_value not in scrub_text(text), scrub_text(text)[:120])
    T.check("oddiy 'tma' so'zi va qisqa matn buzilmaydi", scrub_text("tma ok") == "tma ok")
    event2 = {"message": f"boshqa matn {FAKE_TOKEN}"}
    from utils.sentry_scrubber import register_secret
    register_secret(FAKE_TOKEN, "BOT_TOKEN")
    T.check("ro'yxatga olingan BOT_TOKEN hodisadan o'chiriladi", FAKE_TOKEN not in str(scrub_event(event2, {})))


class CountingRunner:
    calls = 0

    async def run(self, fn):
        type(self).calls += 1
        raise AssertionError("DB'ga tegilmasligi kerak")


def api_app(limiter, settings=None):
    s = settings or load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "production",
                                   "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    runner = CountingRunner()
    api = appmod.build_api_app(s, runner=runner, limiter=limiter, clock=lambda: NOW)
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)
    return app, api


async def fetch(app, path, method="GET", **kw):
    c = TestClient(TestServer(app))
    await c.start_server()
    try:
        r = await c.request(method, path, **kw)
        return r.status, await r.json()
    finally:
        await c.close()


def test_fail_closed_end_to_end():
    print("\n== 4. Redis xatosida auth limiter fail-closed (end-to-end) ==")

    class DeadRedis:
        async def eval(self, *a, **k):
            raise ConnectionError("down")

    resilient = ResilientCacheBackend(RedisCacheBackend(DeadRedis()), MemoryCacheBackend(), failure_threshold=2, cooldown=30)
    lim = StrictLimiter(require_shared=True, backend_getter=lambda: resilient)
    app, _ = api_app(lim)
    hdr = {"Authorization": "tma " + make_init_data(11)}
    CountingRunner.calls = 0
    for path in ("/api/v1/me", "/api/v1/channels", "/api/v1/scheduled-posts"):
        st, body = run(fetch(app, path, headers=hdr))
        T.check(f"{path}: Redis o'lik -> 503 (sog'lom initData bilan ham)", st == 503 and body["error"]["code"] == "service_unavailable")
    st, body = run(fetch(app, "/api/v1/me"))
    T.check("Authorization'siz so'rov ham 503 (limiter HMAC'dan oldin)", st == 503)
    for _ in range(3):
        run(resilient.incr("x", ttl=5))  # boshqa iste'molchilar breaker'ni ochadi
    T.check("breaker ochiq", resilient.circuit_open)
    st, _ = run(fetch(app, "/api/v1/me", headers=hdr))
    T.check("breaker ochiq (xotira fallback): 503, xotira hisoblagichi umumiy deb qabul qilinmadi", st == 503)
    T.check("DB'ga hech qachon tegilmadi", CountingRunner.calls == 0)
    st, _ = run(fetch(app, "/api/v1/health"))
    T.check("health ishlayveradi (limiterga bog'liq emas)", st == 200)


def test_production_bypass_attempts():
    print("\n== 5. Production'da shared limiter talabini aylanib o'tish urinishlari ==")
    base = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"}
    bypass_envs = ["production", "PRODUCTION", " Production ", "prod", "staging", "live", "", "dev", "testing", "stage"]
    bypass_vals = ["0", "false", "FALSE", "no", "off", " 0 ", "False"]
    leaked = []
    for envname in bypass_envs:
        for val in bypass_vals:
            env = {**base, "ENVIRONMENT": envname, "MINIAPP_RATE_REQUIRE_SHARED": val}
            s = load_settings(env)
            app = web.Application()
            mounted = appmod.register_miniapp_routes(app, env=env)
            if mounted or not s.rate_require_shared and not s.config_errors:
                leaked.append((envname, val))
    T.check(f"{len(bypass_envs) * len(bypass_vals)} ta kombinatsiyada REQUIRE_SHARED=0 production'da marshrut ULANMAYDI", not leaked, str(leaked))
    for garbage in ("maybe", "disable", "2", "nope", "Нет"):
        s = load_settings({**base, "ENVIRONMENT": "production", "MINIAPP_RATE_REQUIRE_SHARED": garbage})
        T.check(f"noma'lum qiymat {garbage!r} -> xavfsiz sukut (talab YOQIQ)", s.rate_require_shared is True and not s.config_errors)
    for env_name in ("development", "test"):
        s = load_settings({**base, "ENVIRONMENT": env_name, "MINIAPP_RATE_REQUIRE_SHARED": "0"})
        T.check(f"{env_name}: ataylab 0 mumkin", s.rate_require_shared is False and not s.config_errors)
    s = load_settings({**base, "ENVIRONMENT": "staging"})
    T.check("sukut (qiymat yo'q): production-o'xshash muhitda talab YOQIQ", s.rate_require_shared is True)
    for val, expect in (("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("false", False),
                        ("", False), ("garbage", False), ("2", False), (" 1 ", True)):
        T.check(f"MINIAPP_ENABLED={val!r} -> {expect}", load_settings({"MINIAPP_ENABLED": val}).enabled is expect)
    app = web.Application()
    T.check("MINIAPP_ENABLED=garbage -> ulanmaydi", appmod.register_miniapp_routes(app, env={"MINIAPP_ENABLED": "garbage"}) is False)


def _execute_sql_texts(path):
    """Fayldagi har bir `cur.execute(<birinchi argument>)` uchun BIRLASHTIRILGAN SQL matni
    (satr konstantalari + modul darajasidagi `_POST_SELECT` kabi nomlar o'rniga qo'yiladi)."""
    tree = ast.parse(path.read_text(encoding="utf8"))
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            consts[node.targets[0].id] = node.value.value
    texts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute" and node.args:
            parts = []
            for sub in ast.walk(node.args[0]):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    parts.append(sub.value)
                elif isinstance(sub, ast.Name) and sub.id in consts:
                    parts.append(consts[sub.id])
            texts.append((" ".join(" ".join(parts).split()), any(isinstance(n, ast.JoinedStr) for n in ast.walk(node.args[0]))))
    return texts


def test_ownership_sql_static():
    print("\n== 6. Ownership SQL (statik skan; birlashtirilgan so'rovlar) ==")
    texts = _execute_sql_texts(BOT_ROOT / "miniapp_api" / "repository.py")
    sqls = [t for t, _ in texts if "FROM channels" in t or "FROM scheduled_posts" in t or "FROM users" in t]
    T.check("repository'da kamida 8 ta kanal/post/user SQL topildi", len(sqls) >= 8, str(len(sqls)))
    own = [s for s in sqls if "FROM channels" in s or "FROM scheduled_posts" in s]
    T.check("har bir kanal/post so'rovida 'user_id = %s' sharti (BIRLASHTIRILGAN matnda)", all(("user_id = %s" in s) for s in own),
            str([s[:60] for s in own if "user_id = %s" not in s]))
    T.check("so'rovlarda ID f-string/format bilan yopishtirilmagan", not any(f for _, f in texts))
    T.check("repository'da yozuvchi SQL yo'q (u faqat read-only tranzaksiyada ishlaydi)",
            not any(w in s.upper() for s in sqls for w in ("INSERT ", "UPDATE ", "DELETE ")))
    T.check("users so'rovi egasi bo'yicha", all("user_id = %s" in s for s in sqls if "FROM users" in s))
    writes = _execute_sql_texts(BOT_ROOT / "miniapp_api" / "writes.py")
    T.check("writes.py: kamida 2 ta SQL (dublikat tekshiruvi, vaqt o'zgartirish) topildi", len(writes) >= 2, str(len(writes)))
    T.check("writes.py: har bir SQL egasi sharti 'user_id = %s' ga ega", all("user_id = %s" in t for t, _ in writes), str([t[:50] for t, _ in writes]))
    T.check("writes.py: SQL parametrli (f-string yo'q)", not any(f for _, f in writes))
    T.check("writes.py: UPDATE faqat 'pending' postga", all("status = 'pending'" in t for t, _ in writes if t.upper().startswith("UPDATE")))


def test_all_routes_require_auth():
    print("\n== 7. Barcha marshrutlar auth talab qiladi (health'dan tashqari) ==")
    lim = StrictLimiter(require_shared=False, backend_getter=lambda: MemoryCacheBackend())
    app, api = api_app(lim, load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                           "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"}))
    routes = sorted({(r.method, r.resource.canonical) for r in api.router.routes() if r.method != "HEAD"})
    expected = [("DELETE", "/api/v1/draft"), ("DELETE", "/api/v1/draft/media"), ("DELETE", "/api/v1/posts/{post_id}"), ("DELETE", "/api/v1/posts/{post_id}/media"), ("DELETE", "/api/v1/templates/{template_id}"), ("GET", "/api/v1/channels"), ("GET", "/api/v1/channels/{channel_id}/analytics"),
                ("GET", "/api/v1/draft"), ("GET", "/api/v1/draft/media"), ("GET", "/api/v1/health"),
                ("GET", "/api/v1/me"), ("GET", "/api/v1/posts/{post_id}"), ("GET", "/api/v1/posts/{post_id}/media"), ("GET", "/api/v1/scheduled-posts"),
                ("GET", "/api/v1/scheduled-posts/calendar"), ("GET", "/api/v1/templates"),
                ("PATCH", "/api/v1/me/settings"), ("PATCH", "/api/v1/posts/{post_id}"),
                ("POST", "/api/v1/ai/generate"), ("POST", "/api/v1/draft/media"), ("POST", "/api/v1/posts"), ("POST", "/api/v1/posts/{post_id}/media"), ("POST", "/api/v1/schedule/parse"),
                ("POST", "/api/v1/templates")]
    # 💰 Reklama birjasi (miniapp_api/market.py): har biri auth talab qiladi, yozuvchilari yozuv-limiti bilan.
    expected += [("DELETE", "/api/v1/market/mine/{item_id}"), ("GET", "/api/v1/market/listings"), ("GET", "/api/v1/market/listings/{item_id}"),
                 ("GET", "/api/v1/market/mine"), ("GET", "/api/v1/market/summary"), ("GET", "/api/v1/market/threads"),
                 ("GET", "/api/v1/market/threads/{item_id}"), ("PATCH", "/api/v1/market/mine/{item_id}"),
                 ("POST", "/api/v1/market/listings/{item_id}/inquiries"), ("POST", "/api/v1/market/listings/{item_id}/report"),
                 ("POST", "/api/v1/market/mine"), ("POST", "/api/v1/market/mine/{item_id}/refresh"),
                 ("POST", "/api/v1/market/threads/{item_id}/block"), ("POST", "/api/v1/market/threads/{item_id}/close"),
                 ("POST", "/api/v1/market/threads/{item_id}/messages"), ("POST", "/api/v1/market/threads/{item_id}/report"),
                 ("GET", "/api/v1/market/unread")]
    # 🛡 Super admin (miniapp_api/admin.py): har biri auth + admin tekshiruvi.
    expected += [("DELETE", "/api/v1/admin/ads/{item_id}"), ("DELETE", "/api/v1/admin/sponsors/{item_id}"),
                 ("GET", "/api/v1/admin/ads"), ("GET", "/api/v1/admin/market"), ("GET", "/api/v1/admin/overview"),
                 ("GET", "/api/v1/admin/sponsors"), ("PATCH", "/api/v1/admin/ads/settings"),
                 ("PATCH", "/api/v1/admin/ads/{item_id}"), ("POST", "/api/v1/admin/ads"),
                 ("POST", "/api/v1/admin/market/listings/{item_id}/status"),
                 ("POST", "/api/v1/admin/market/users/{item_id}/ban"), ("POST", "/api/v1/admin/sponsors")]
    # 🎁 Promo-kodlar, tarif berish, tizim, rollar (har biri auth + RBAC).
    expected += [("GET", "/api/v1/admin/promos"), ("POST", "/api/v1/admin/promos"), ("GET", "/api/v1/admin/promos/{code}"),
                 ("PATCH", "/api/v1/admin/promos/{code}"), ("POST", "/api/v1/admin/grant"), ("GET", "/api/v1/admin/audit"),
                 ("GET", "/api/v1/admin/features"), ("GET", "/api/v1/admin/system"), ("GET", "/api/v1/admin/roles"),
                 ("POST", "/api/v1/admin/roles")]
    # 👥 Jamoa (miniapp_api/team.py): har biri auth talab qiladi; egalik serverda (services/team_invites).
    expected += [("GET", "/api/v1/team"), ("PATCH", "/api/v1/team/mode"), ("POST", "/api/v1/team/invites"),
                 ("DELETE", "/api/v1/team/invites/{item_id}"), ("PATCH", "/api/v1/team/members"),
                 ("POST", "/api/v1/team/members/remove"), ("POST", "/api/v1/team/leave")]
    expected.sort()
    T.check("marshrutlar ro'yxati kutilgandek", routes == expected, str(routes))
    CountingRunner.calls = 0
    for method, canonical in routes:
        path = canonical.replace("{post_id}", "1").replace("{channel_id}", "-1001234567890").replace("{template_id}", "1").replace("{item_id}", "1").replace("{code}", "ZT_X")
        st, body = run(fetch(app, path, method=method) if method != "GET" else fetch(app, path))
        if path.endswith("/health"):
            T.check("/health auth'siz 200", st == 200)
        else:
            T.check(f"{method} {canonical} auth'siz -> 401", st == 401 and body["error"]["code"] == "unauthorized", f"{st} {body}")
    writers = {(r.method, r.resource.canonical): getattr(r.handler, "miniapp_write", False) for r in api.router.routes() if r.method not in ("GET", "HEAD")}
    T.check("har bir yozuvchi marshrut yozuv-limiti bilan belgilangan (miniapp_write)", all(writers.values()) and len(writers) == 41, str(writers))
    ai_flags = {r.resource.canonical: getattr(r.handler, "miniapp_ai", False) for r in api.router.routes() if r.method == "POST"}
    T.check("faqat AI ishlatadigan marshrutlar (/ai/generate, /schedule/parse) AI limitiga ega",
            ai_flags == {"/api/v1/ai/generate": True, "/api/v1/posts": False, "/api/v1/schedule/parse": True,
                         "/api/v1/templates": False, "/api/v1/draft/media": False,
                         "/api/v1/posts/{post_id}/media": False,
                         # 💰 birja: AI ishlatmaydi
                         "/api/v1/market/listings/{item_id}/inquiries": False, "/api/v1/market/listings/{item_id}/report": False,
                         "/api/v1/market/mine": False, "/api/v1/market/mine/{item_id}/refresh": False,
                         "/api/v1/market/threads/{item_id}/block": False, "/api/v1/market/threads/{item_id}/close": False,
                         "/api/v1/market/threads/{item_id}/messages": False, "/api/v1/market/threads/{item_id}/report": False,
                         # 🛡 admin: AI ishlatmaydi
                         "/api/v1/admin/ads": False, "/api/v1/admin/sponsors": False,
                         "/api/v1/admin/market/listings/{item_id}/status": False,
                         "/api/v1/admin/market/users/{item_id}/ban": False,
                         "/api/v1/admin/promos": False, "/api/v1/admin/grant": False, "/api/v1/admin/roles": False,
                         "/api/v1/team/invites": False, "/api/v1/team/members/remove": False, "/api/v1/team/leave": False},
                        str(ai_flags))
    methods = {r.method for r in api.router.routes()}
    T.check("faqat ruxsat etilgan usullar ulangan (PUT yo'q)", methods <= {"GET", "HEAD", "POST", "PATCH", "DELETE"}, str(methods))
    T.check("DB'ga auth'siz tegilmadi", CountingRunner.calls == 0)
    _ = auth_mod


def main() -> int:
    test_hmac()
    test_duplicates()
    test_secrecy()
    test_fail_closed_end_to_end()
    test_production_bypass_attempts()
    test_ownership_sql_static()
    test_all_routes_require_auth()
    T.skip("haqiqiy Redis bilan umumiy limiter / uzilish", "BLOCKED: Redis serveri va `redis` paketi mavjud emas")
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
