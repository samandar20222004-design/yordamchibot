#!/usr/bin/env python3
"""Mini App — Telegram initData tekshiruvi, sozlamalar va maxfiylik testlari.

Muhit: sof unit (tarmoq/DB/Redis yo'q). Tokenlar — faqat soxta test qiymatlari.
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data, sign_fields  # noqa: E402

from miniapp_api.auth import (  # noqa: E402
    AuthError,
    parse_authorization,
    validate_init_data,
)
from miniapp_api.settings import is_valid_bot_token, load_settings  # noqa: E402

T = Counter("MINI APP — AUTH (initData HMAC) + SOZLAMALAR")


def code_of(init_data, **kw):
    kw.setdefault("now", NOW)
    token = kw.pop("token", FAKE_TOKEN)
    try:
        validate_init_data(init_data, token, **kw)
    except AuthError as exc:
        return exc.code
    return "OK"


def test_valid():
    print("\n== 1. To'g'ri imzo ==")
    user = validate_init_data(make_init_data(777), FAKE_TOKEN, now=NOW)
    T.check("tasdiqlangan user_id qaytadi", user.user_id == 777)
    T.check("auth_date saqlanadi", user.auth_date == NOW)
    T.check("language_code faqat imzodan keyin o'qiladi", user.language_code == "uz")
    # signature maydoni HMAC data-check-string ICHIDA (hujjat bo'yicha)
    data = make_init_data(5, extra={"signature": "abcDEF_-123"})
    T.check("signature bor initData qabul qilinadi", code_of(data) == "OK")
    # signature qiymati o'zgarsa, hash buziladi (u data-check-string ichida)
    tampered = data.replace("abcDEF_-123", "abcDEF_-124")
    T.check("signature o'zgarsa rad (HMAC ichida ekani)", code_of(tampered) == "unauthorized")
    # mustaqil hisob: signature'siz hash signature'li bilan MOS KELMAYDI
    f1 = {"auth_date": str(NOW), "user": '{"id":1}'}
    f2 = dict(f1, signature="x")
    T.check("signature hash'ga ta'sir qiladi", sign_fields(f1) != sign_fields(f2))
    # maxsus belgilar (unicode, bo'sh joy, %)
    uni = make_init_data(9, user_obj={"id": 9, "first_name": "Ўзбек 😀 A&B=C"})
    T.check("unicode / & / = qiymatlar to'g'ri ishlaydi", code_of(uni) == "OK")


def test_tamper():
    print("\n== 2. Noto'g'ri imzo / buzilgan maydonlar ==")
    good = make_init_data(10)
    T.check("boshqa bot tokeni -> rad", code_of(good, token="987654321:OTHERtokenZZZZZZZZZZZZZZZZZZZZZZ") == "unauthorized")
    T.check("hash buzilgan -> rad", code_of(good[:-1] + ("0" if good[-1] != "0" else "1")) == "unauthorized")
    T.check("user id almashtirilgan -> rad", code_of(good.replace("%22id%22%3A10", "%22id%22%3A11")) == "unauthorized")
    T.check("hash yo'q -> rad", code_of(make_init_data(10).rsplit("&hash=", 1)[0]) == "unauthorized")
    T.check("hash katta harf -> rad (qat'iy format)", code_of(good.replace(good.rsplit("hash=", 1)[1], good.rsplit("hash=", 1)[1].upper())) == "unauthorized")
    T.check("hash qisqa -> rad", code_of(good.rsplit("hash=", 1)[0] + "hash=abcd") == "unauthorized")
    T.check("bo'sh initData -> rad", code_of("") == "unauthorized")
    T.check("None -> rad", code_of(None) == "unauthorized")
    T.check("auth_date yo'q -> rad", code_of(make_init_data(10, drop=("auth_date",))) == "unauthorized")
    T.check("user yo'q -> rad", code_of(make_init_data(10, drop=("user",))) == "unauthorized")


def test_duplicates_and_malformed():
    print("\n== 3. Takroriy kalitlar / noto'g'ri tuzilma ==")
    good = make_init_data(11)
    for key in ("auth_date", "user", "hash", "query_id"):
        val = [p for p in good.split("&") if p.startswith(key + "=")][0]
        T.check(f"takroriy '{key}' -> rad", code_of(good + "&" + val) == "unauthorized")
    sig = make_init_data(11, extra={"signature": "aaa"})
    T.check("takroriy signature -> rad", code_of(sig + "&signature=aaa") == "unauthorized")
    T.check("bo'sh kalit -> rad", code_of(good + "&=x") == "unauthorized")
    T.check("bo'sh qiymat -> rad", code_of(good + "&foo=") == "unauthorized")
    T.check("'=' siz maydon -> rad (strict)", code_of(good + "&junk") == "unauthorized")
    T.check("NUL belgi -> rad", code_of(good + "%00") in ("unauthorized",))
    many = good + "".join(f"&k{i}=v" for i in range(40))
    T.check("maydonlar soni chegarasi", code_of(many, max_bytes=10_000) == "unauthorized")
    T.check("uzunlik chegarasi", code_of(make_init_data(11, extra={"x": "a" * 5000})) == "unauthorized")


def test_auth_date():
    print("\n== 4. auth_date chegaralari (maks yosh 3600 s, kelajak 60 s) ==")
    ok = lambda d, **kw: code_of(make_init_data(12, auth_date=d), **kw)  # noqa: E731
    T.check("hozir -> OK", ok(NOW) == "OK")
    T.check("yosh = 3600 (chegara) -> OK", ok(NOW - 3600) == "OK")
    T.check("yosh = 3601 -> auth_expired", ok(NOW - 3601) == "auth_expired")
    T.check("kelajak +60 (chegara) -> OK", ok(NOW + 60) == "OK")
    T.check("kelajak +61 -> rad", ok(NOW + 61) == "unauthorized")
    T.check("juda uzoq kelajak -> rad", ok(NOW + 10 ** 9) == "unauthorized")
    T.check("auth_date=0 -> auth_expired", ok(0) == "auth_expired")
    for bad in ("-5", "1.5", "1e9", " 123", "0x10", "12345678901234", "abc", "+5"):
        data = make_init_data(12, extra={"auth_date": bad})
        T.check(f"auth_date={bad!r} -> rad", code_of(data) == "unauthorized")
    T.check("max_age sozlanadi", ok(NOW - 120, max_age=60) == "auth_expired")


def test_user_field():
    print("\n== 5. user maydoni ==")
    cases = {
        "id manfiy": {"id": -5}, "id nol": {"id": 0}, "id matn": {"id": "5"},
        "id float": {"id": 5.0}, "id bool(True)": {"id": True}, "id null": {"id": None},
        "id yo'q": {"first_name": "x"}, "id juda katta": {"id": 2 ** 60},
    }
    for label, obj in cases.items():
        T.check(f"{label} -> rad", code_of(make_init_data(0, user_obj=obj)) == "unauthorized")
    for label, raw in {"ro'yxat": "[1]", "raqam": "5", "null": "null", "buzuq JSON": "{bad",
                       "NaN": '{"id":NaN}', "satr": '"x"'}.items():
        T.check(f"user={label} -> rad", code_of(make_init_data(0, user_obj=raw)) == "unauthorized")


def test_token_config():
    print("\n== 6. BOT_TOKEN konfiguratsiyasi (fail-closed) ==")
    good = make_init_data(13)
    for label, tok in {"bo'sh": "", "probel": "   ", "None": None, "':' yo'q": "123456789",
                       "id harf": "abc:XYZ", "sir bo'sh": "123:", "unicode": "123:тест",
                       "boshqaruv": "123:ab\ncd", "bo'shliq ichida": "123:ab cd"}.items():
        T.check(f"token {label} -> auth_unavailable", code_of(good, token=tok) == "auth_unavailable")
    T.check("qisqa token '1:x' yaroqli (uzunlik cheklovi yo'q)", is_valid_bot_token("1:x"))
    T.check("uzun token yaroqli", is_valid_bot_token("1234567890:" + "A" * 200))
    T.check("tokenning '-' va '_' belgilari yaroqli", is_valid_bot_token("12:AA-bb_CC"))
    short_ok = code_of(make_init_data(13, token="1:x"), token="1:x")
    T.check("qisqa token bilan imzolangan initData ishlaydi", short_ok == "OK")


def test_authorization_header():
    print("\n== 7. Authorization sarlavhasi ==")
    T.check("'tma <data>' qabul", parse_authorization("tma abc=1") == "abc=1")
    T.check("sxema katta-kichik harf farqsiz", parse_authorization("TMA abc=1") == "abc=1")
    for bad in (None, "", "tma", "tma ", "Bearer abc", "tma  x", "tma x ", "tmaabc", 5):
        try:
            parse_authorization(bad)
            T.check(f"{bad!r} -> rad", False)
        except AuthError:
            T.check(f"{bad!r} -> rad", True)


def test_secrecy():
    print("\n== 8. Maxfiy qiymatlar log/xatoga tushmaydi ==")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    leaked = False
    try:
        good = make_init_data(14, extra={"start_param": "SECRETSTART"})
        for token in (FAKE_TOKEN, ""):
            for data in (good, good + "&hash=zz", "junk"):
                try:
                    validate_init_data(data, token, now=NOW)
                except AuthError as exc:
                    if FAKE_TOKEN in str(exc) or "SECRETSTART" in str(exc):
                        leaked = True
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    out = stream.getvalue()
    T.check("istisno matnida token/initData yo'q", not leaked)
    T.check("auth modulining logida token/initData yo'q",
            FAKE_TOKEN not in out and "SECRETSTART" not in out)
    s = load_settings({"BOT_TOKEN": FAKE_TOKEN, "MINIAPP_ENABLED": "1"})
    T.check("Settings repr tokenni ko'rsatmaydi", FAKE_TOKEN not in repr(s) and FAKE_TOKEN not in str(s))
    T.check("config_errors tokenni o'z ichiga olmaydi",
            all(FAKE_TOKEN not in e for e in s.config_errors))
    _ = quote  # noqa


def test_settings():
    print("\n== 9. Sozlamalar ==")
    s = load_settings({})
    T.check("MINIAPP_ENABLED sukut = 0", s.enabled is False)
    s = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN})
    T.check("HTTPS majburiy, proksi yo'q -> config xatosi",
            any("proksi" in e for e in s.config_errors))
    s = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": "bad", "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"})
    T.check("yaroqsiz BOT_TOKEN -> config xatosi", any("BOT_TOKEN" in e for e in s.config_errors))
    base = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"}
    s = load_settings(base)
    T.check("production'da umumiy limiter sukut = 1", s.rate_require_shared is True and not s.config_errors)
    s = load_settings({**base, "MINIAPP_RATE_REQUIRE_SHARED": "0"})
    T.check("production'da REQUIRE_SHARED=0 -> config xatosi (ulanmaydi)",
            any("MINIAPP_RATE_REQUIRE_SHARED" in e for e in s.config_errors))
    s = load_settings({**base, "ENVIRONMENT": "development", "MINIAPP_RATE_REQUIRE_SHARED": "0"})
    T.check("development'da REQUIRE_SHARED=0 mumkin", not s.config_errors and s.rate_require_shared is False)
    s = load_settings({**base, "ENVIRONMENT": "test"})
    T.check("test muhitida sukut 0", s.rate_require_shared is False)
    s = load_settings({**base, "ENVIRONMENT": ""})
    T.check("ENVIRONMENT bo'sh = production (fail-closed)", s.is_production)
    s = load_settings({**base, "MINIAPP_TRUSTED_PROXY_CIDRS": "10.0.0.0/8, nonsense"})
    T.check("noto'g'ri CIDR -> config xatosi", any("CIDR" in e for e in s.config_errors))
    s = load_settings({**base, "MINIAPP_AUTH_MAX_AGE_SECONDS": "999999999"})
    T.check("max yosh yuqori chegaraga qisqartiriladi (<= 86400)", s.auth_max_age_seconds == 86400)
    d = load_settings(base)
    T.check("DB navbat sukutlari: kutish 2 s, navbat 64", d.db_queue_wait_seconds == 2.0 and d.db_max_queue == 64)
    d2 = load_settings({**base, "MINIAPP_DB_QUEUE_WAIT_SECONDS": "0", "MINIAPP_DB_MAX_QUEUE": "5"})
    T.check("DB navbat sozlamalari o'qiladi (0 = navbatsiz)", d2.db_queue_wait_seconds == 0.0 and d2.db_max_queue == 5)
    d3 = load_settings({**base, "MINIAPP_DB_QUEUE_WAIT_SECONDS": "999", "MINIAPP_DB_MAX_QUEUE": "99999"})
    T.check("DB navbat chegaralanadi (<= 10 s, <= 1000)", d3.db_queue_wait_seconds == 10.0 and d3.db_max_queue == 1000)
    T.check("Redis concurrency sukut = 4", load_settings(base).rate_redis_concurrency == 4)
    T.check("MINIAPP_RATE_REDIS_CONCURRENCY o'qiladi", load_settings({**base, "MINIAPP_RATE_REDIS_CONCURRENCY": "8"}).rate_redis_concurrency == 8)
    T.check("concurrency chegaralanadi (1..64)", load_settings({**base, "MINIAPP_RATE_REDIS_CONCURRENCY": "0"}).rate_redis_concurrency == 1
            and load_settings({**base, "MINIAPP_RATE_REDIS_CONCURRENCY": "9999"}).rate_redis_concurrency == 64)
    s = load_settings({**base, "MINIAPP_AUTH_MAX_AGE_SECONDS": "xx"})
    T.check("noto'g'ri son -> sukut 3600", s.auth_max_age_seconds == 3600)


def test_third_party_vectors():
    print("\n== 10. Uchinchi tomon implementatsiyasi vektorlari (RASMIY EMAS, o'zaro mos kelish) ==")
    # Manba: aiogram 3.31.0 `tests/test_utils/test_web_app.py` (MIT) — aiogram muallifi yaratgan vektorlar
    # (token `42:TEST`, soxta). Ular Telegram tomonidan emas; ular faqat BOSHQA mustaqil implementatsiya
    # (aiogram `check_webapp_signature`, u rasmiy hujjat bo'limiga havola qiladi) bilan HMAC natijasi mosligini
    # ko'rsatadi. `signature` maydoni bu vektorlarda YO'Q, shuning uchun u haqda dalil bermaydi.
    from miniapp_api.auth import compute_hash

    token = "42:TEST"
    v1 = ("auth_date=1650385342&user=%7B%22id%22%3A42%2C%22first_name%22%3A%22Test%22%7D&query_id=test"
          "&hash=46d2ea5e32911ec8d30999b56247654460c0d20949b6277af519e76271182803")
    T.check("aiogram vektori #1: to'liq tekshiruv OK", _third_party_ok(v1, token) is True)
    T.check("compute_hash aiogram'dagi literal hash bilan bir xil (#1 maydonlar)",
            compute_hash({"auth_date": "1650385342", "user": '{"id":42,"first_name":"Test"}', "query_id": "test"}, token)
            == "46d2ea5e32911ec8d30999b56247654460c0d20949b6277af519e76271182803")
    T.check("boshqa token bilan o'sha vektor rad etiladi", _third_party_ok(v1, "42:INVALID") is False)
    T.check("hash buzilgan vektor rad etiladi", _third_party_ok(v1[:-1] + "0", token) is False)


def test_realistic_and_matrix():
    print("\n== 11. Haqiqiy formatdagi initData va maydon-maydon buzish matritsasi ==")
    import json as _json
    from urllib.parse import urlencode as _enc

    user = {"id": 5001, "first_name": "Ali", "last_name": "Valiyev", "username": "ali_v",
            "language_code": "uz", "is_premium": True, "allows_write_to_pm": True,
            "photo_url": "https://t.me/i/userpic/320/x.svg"}
    base = {"query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": _json.dumps(user, separators=(",", ":"), ensure_ascii=False),
            "auth_date": str(NOW), "start_param": "ref_77", "chat_type": "sender",
            "chat_instance": "-1234567890123456789", "signature": "Zm9vYmFyX3NpZ19fXy0"}
    base["hash"] = sign_fields(base)
    good = _enc(base, quote_via=quote)
    T.check("to'liq maydonli (signature+start_param+chat_*) initData OK", code_of(good) == "OK")
    u = validate_init_data(good, FAKE_TOKEN, now=NOW)
    T.check("user_id imzolangan user'dan olinadi", u.user_id == 5001 and u.language_code == "uz")

    for field in ("user", "auth_date", "query_id", "start_param", "chat_type",
                  "chat_instance", "signature"):
        bad = dict(base)
        bad[field] = base[field] + ("1" if field == "auth_date" else "x")
        T.check(f"'{field}' o'zgartirilsa -> rad (hash eskicha)",
                code_of(_enc(bad, quote_via=quote)) == "unauthorized")
        gone = {k: v for k, v in base.items() if k != field}
        expected = "unauthorized"
        T.check(f"'{field}' olib tashlansa -> rad", code_of(_enc(gone, quote_via=quote)) == expected)
    extra = dict(base, injected="1")
    T.check("qo'shimcha maydon qo'shilsa -> rad", code_of(_enc(extra, quote_via=quote)) == "unauthorized")
    swapped = dict(base, user=_json.dumps(dict(user, id=1), separators=(",", ":"), ensure_ascii=False))
    T.check("user.id boshqasiga almashtirilsa -> rad", code_of(_enc(swapped, quote_via=quote)) == "unauthorized")

    # auth_date: imzo to'g'ri, lekin eskirgan / kelajak
    old = make_init_data(5, auth_date=NOW - 3601)
    T.check("auth_date 3601s eski -> auth_expired", code_of(old) == "auth_expired")
    fut = make_init_data(5, auth_date=NOW + 61)
    T.check("auth_date kelajakda (>60s) -> rad", code_of(fut) == "unauthorized")
    # bo'sh / yaroqsiz qiymatlar
    for label, data in (("bo'sh hash", good.rsplit("hash=", 1)[0] + "hash="),
                        ("bo'sh user", make_init_data(5, extra={"user": ""})),
                        ("user JSON emas", make_init_data(5, user_obj="not-json")),
                        ("user massiv", make_init_data(5, user_obj="[1]")),
                        ("user.id=0", make_init_data(5, user_obj={"id": 0})),
                        ("user.id satr", make_init_data(5, user_obj={"id": "7"})),
                        ("user.id bool", make_init_data(5, user_obj={"id": True})),
                        ("auth_date harf", make_init_data(5, extra={"auth_date": "abc"})),
                        ("faqat hash", "hash=" + "0" * 64)):
        T.check(f"{label} -> rad", code_of(data) in ("unauthorized",))


def test_never_crashes():
    print("\n== 12. Dushmanona kiritma: validator FAQAT AuthError ko'taradi (500 bermaydi) ==")
    import random

    rnd = random.Random(7)
    alphabet = ["%", "%00", "%ff", "%ed%a0%80", "&", "=", "+", "\x00", "hash", "user",
                "auth_date", "\U0001F600", "a", "0", "{", "}", '"', "\n", " ", "9" * 40]
    bad = []

    def probe(data):
        try:
            validate_init_data(data, FAKE_TOKEN, now=NOW)
        except AuthError:
            pass
        except Exception as exc:  # noqa: BLE001 — aynan shuni qidiramiz
            bad.append(type(exc).__name__)

    for _ in range(3000):
        probe("".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 40))))
    T.check("3000 tasodifiy kiritma: AuthError'dan boshqa istisno yo'q", not bad, str(bad[:3]))

    # IMZO TO'G'RI, lekin maydon qiymatlari dushmanona
    hostile_users = ['{"id":1e400}', '{"id":NaN}', '{"id":' + "9" * 5000 + "}", "[" * 5000,
                     '{"id":-1}', '{"id":1.5}', "null", '"s"', "{}",
                     '{"id":123456789012345678901234567890}', '{"id":true}']
    for user in hostile_users:
        for auth_date in ("1", str(NOW), "9" * 12, "0" * 12, "99999999999999"):
            fields = {"auth_date": auth_date, "user": user}
            fields["hash"] = sign_fields(fields)
            probe("&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items()))
    T.check("imzolangan dushmanona user/auth_date: istisno yo'q", not bad, str(bad[:3]))
    T.check("user.id=1e400 / NaN / ulkan son / bool -> rad",
            all(code_of(_signed_user(u)) == "unauthorized"
                for u in ('{"id":1e400}', '{"id":NaN}', '{"id":123456789012345678901234567890}',
                          '{"id":true}', '{"id":1.5}', '{"id":-1}')))
    for header in (None, "", "tma", "tma ", "Bearer x", "tma  x", "tma x\n", "tma " + "a" * 100000):
        try:
            parse_authorization(header)
        except AuthError:
            pass
        except Exception as exc:  # noqa: BLE001
            bad.append(type(exc).__name__)
    T.check("Authorization sarlavhasi: faqat AuthError", not bad, str(bad[:3]))


def _signed_user(user_json):
    fields = {"auth_date": str(NOW), "user": user_json}
    fields["hash"] = sign_fields(fields)
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items())


def test_independent_openssl_vectors():
    print("\n== 13. MUSTAQIL vektorlar (openssl CLI bilan hisoblangan, literal; production helper'lariga tayanmaydi) ==")
    # Hash'lar `openssl dgst -sha256 -hmac "WebAppData"` (secret) va `-mac HMAC -macopt hexkey:` (imzo) bilan
    # hisoblangan: Python `hmac`/`hashlib`, `compute_hash` va `sign_fields` ishtirok etmagan.
    # DIQQAT (faraz): data-check-string tuzilishi (hash'dan boshqa BARCHA maydon, saralangan, `\n`) va
    # `signature`ning ichkarida qolishi rasmiy hujjat matni bilan bu sessiyada TASDIQLANMAGAN (hujjatga kirib
    # bo'lmadi). Bu test kodning shu farazga muvofiqligini mustaqil hisob bilan qotiradi, rasmiy tasdiq emas.
    user = "%7B%22id%22%3A4242%2C%22first_name%22%3A%22Test%22%2C%22language_code%22%3A%22uz%22%7D"
    base = f"auth_date=1760000000&query_id=AAHdF6IQAAAAAN0XohDhrOrc&user={user}"
    plain_hash = "8ca5376ac28de748b2c6b80ae209d880a3a9d1413eac49b896198d78c46b35fb"
    sig_hash = "caeb7c118831ed40177afc762a7e5bbf5daf07b91ba8f123b6758a88d8f42eab"
    T.check("openssl hash (signature'siz) qabul qilinadi", code_of(f"{base}&hash={plain_hash}") == "OK")
    with_sig = f"{base}&signature=abcDEF_-123"
    T.check("openssl hash (signature BILAN hisoblangan) qabul qilinadi",
            code_of(f"{with_sig}&hash={sig_hash}") == "OK")
    T.check("signature bor, lekin hash signature'siz hisoblangan -> rad (farazni qotiradi)",
            code_of(f"{with_sig}&hash={plain_hash}") == "unauthorized")
    T.check("maydonlar tartibi URL'da boshqacha bo'lsa ham bir xil natija",
            code_of(f"hash={plain_hash}&user={user}&query_id=AAHdF6IQAAAAAN0XohDhrOrc&auth_date=1760000000") == "OK")


def _third_party_ok(data, token):
    try:
        validate_init_data(data, token, now=1650385342 + 5, max_age=3600)
        return True
    except AuthError:
        return False


def main() -> int:
    test_valid()
    test_tamper()
    test_duplicates_and_malformed()
    test_auth_date()
    test_user_field()
    test_token_config()
    test_authorization_header()
    test_secrecy()
    test_settings()
    test_third_party_vectors()
    test_realistic_and_matrix()
    test_never_crashes()
    test_independent_openssl_vectors()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
