#!/usr/bin/env python3
"""Mini App -> bot navigatsiyasi KONTRAKTI (faqat o'qish, mavjud bot kodiga tegmaydi).

Savollar va haqiqiy koddan javoblar:
  * Mini App Post/PRO tugmasi /newpost yoki PRO oqimini OCHA OLADIMI?  -> YO'Q: `https://t.me/<bot>`
    faqat chatni ochadi; buyruqni foydalanuvchi o'zi yuboradi (matn shunga mos).
  * `/start <payload>` deep-link: `ref_<id>` VA qat'iy ruxsat ro'yxati
    `go_plans|go_settings|go_help|go_channels|go_invite` (Mini App «Sotib olish», «Botga o'tish»,
    «Kanal qo'shish», «Do'stlarni taklif», «Post tozalagich»); boshqa payload e'tiborsiz. Mini App faqat `go_<bo'lim>` quradi.
  * Matnda aytilgan yo'l haqiqatmi? /settings -> «💎 PRO va Tariflar» -> `sub_open`.
Ruxsat ro'yxati kengaysa bu test ataylab yiqiladi: Mini App (telegram.ts) va bot (MINIAPP_GO_TARGETS) birga yangilansin.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import REPO, Counter  # noqa: E402

T = Counter("MINI APP — NAVIGATSIYA KONTRAKTI (Post / PRO / deep-link)")
BOT = REPO / "telegram_bot"
SRC = REPO / "miniapp" / "src"


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", code)


def frontend_sources():
    return [p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx") and ".test." not in p.name]


def test_frontend_links():
    print("\n== 1. Frontend havolalari ==")
    text = {p: strip_comments(p.read_text(encoding="utf8")) for p in frontend_sources()}
    T.check("frontend manbalari topildi", len(text) > 10)
    bad = [p.name for p, t in text.items() if p.name != "telegram.ts" and re.search(r"[?&]start(app)?=|tg://|t\.me/[^`'\"$]*\?", t)]
    T.check("telegram.ts'dan boshqa hech bir fayl `?start=`/`startapp`/`tg://` havola yasamaydi", not bad, str(bad))
    tg = text[SRC / "telegram.ts"]
    T.check("openBot `https://t.me/${username}` quradi", "`https://t.me/${username}`" in tg)
    T.check("openBot faqat ruxsat ro'yxatidagi bo'lim uchun `?start=go_<bo'lim>` qo'shadi",
            "BOT_SECTIONS.includes(section)" in tg and "?start=go_${section}" in tg and "tg://" not in tg)
    ui = text[SRC / "components" / "ui.tsx"]
    T.check("openBot tugmasi username'ni tekshiradi (isValidBotUsername)", "isValidBotUsername" in ui)
    pages = "\n".join(t for p, t in text.items() if "pages" in p.parts)
    T.check("sahifalarda to'lov/sotib olish tugmasi yo'q", not re.search(r"sendData|invoice|openInvoice|payment", pages, re.I))
    # Yozuv amallari FAQAT yagona API klienti orqali (qayta urinishsiz `send`); sahifa/komponentlar to'g'ridan-to'g'ri fetch qilmaydi.
    ui_files = "\n".join(t for p, t in text.items() if "pages" in p.parts or "components" in p.parts or "hooks" in p.parts)
    T.check("sahifa/komponent/hook'larda to'g'ridan-to'g'ri fetch yoki method: yo'q", not re.search(r"\bfetch\(|method:\s*'", ui_files))
    client = text[SRC / "api" / "client.ts"]
    client_path = SRC / "api" / "client.ts"
    others = [t for p, t in text.items() if p != client_path and p.suffix in (".ts", ".tsx") and "test" not in p.name]
    T.check("yozuv usullari (POST/PATCH/DELETE) faqat api/client.ts da",
            others and all(not re.search(r"'(POST|PATCH|DELETE)'", t) for t in others) and re.search(r"'POST'", text[client_path]))
    T.check("yozuvchi so'rovlar qayta urinilmaydi (send() retry tsiklisiz)", "async function send" in client and "tries" not in client.split("async function send")[1].split("return {")[0])


def test_start_payload_behaviour():
    print("\n== 2. /start payload: haqiqiy bot xulqi ==")
    import importlib

    start_mod = importlib.import_module("handlers.start")  # `handlers.start` nomi paketda funksiya bilan soyalanadi

    src = inspect.getsource(start_mod.start)
    T.check("start() handleri `ref_` ni tanlaydi", 'startswith("ref_")' in src)
    routed = [w for w in ("newpost", "start_new_post", "sub_open", "pro_plans", "subscription_callback") if w in src]
    T.check("start() ichida payload orqali /newpost yoki PRO ga yo'naltirish YO'Q", not routed, str(routed))
    T.check("start() `ref_` prefiksini va `go_` ruxsat ro'yxatini (MINIAPP_GO_TARGETS) tanlaydi",
            src.count("arg.startswith(") == 1 and "arg in MINIAPP_GO_TARGETS" in src and not re.search(r"\barg\s*(==|!=)", src))
    T.check("go_ ruxsat ro'yxati faqat plans/settings/help/channels/invite/team",
            sorted(start_mod.MINIAPP_GO_TARGETS) == ["go_channels", "go_help", "go_invite", "go_plans", "go_settings", "go_team"])
    go_src = inspect.getsource(start_mod._open_go_target)
    for target, handler in (("plans", "send_subscription_card"), ("settings", "user_cabinet_menu"), ("help", "help_command"),
                            ("channels", "channels_menu"), ("invite", "user_invite_menu"), ("team", "team_command")):
        T.check(f"go_{target} -> botdagi haqiqiy ekran ({handler})",
                f'target == "{target}"' in go_src and f"await {handler}(" in go_src)
    tg = (SRC / "telegram.ts").read_text(encoding="utf8")
    sections = sorted(re.findall(r"'([a-z]+)'", re.search(r"const BOT_SECTIONS[^=]*=\s*\[([^\]]*)\]", tg).group(1)))
    T.check("Mini App bo'limlari bot ruxsat ro'yxati bilan AYNAN bir xil (uzilish yo'q)",
            sections == sorted(v for v in start_mod.MINIAPP_GO_TARGETS.values()), str(sections))


def test_go_targets_runtime():
    print("\n== 2b. go_<bo'lim>: har biri haqiqatan botdagi ekranni chaqiradi ==")
    import asyncio
    import importlib

    start_mod = importlib.import_module("handlers.start")
    channels_mod = importlib.import_module("handlers.channels")
    sub_mod = importlib.import_module("handlers.subscription")
    team_mod = importlib.import_module("handlers.team_ui")
    called = []

    def fake(name):
        async def _f(*_a, **_k):
            called.append(name)
        return _f

    patches = [(start_mod, "user_cabinet_menu"), (start_mod, "help_command"), (start_mod, "user_invite_menu"),
               (channels_mod, "channels_menu"), (sub_mod, "send_subscription_card"), (team_mod, "team_command")]
    saved = [(m, n, getattr(m, n)) for m, n in patches]
    try:
        for m, n in patches:
            setattr(m, n, fake(n))
        upd = SimpleNamespace(message=object(), effective_user=SimpleNamespace(id=1))
        expected = {"plans": "send_subscription_card", "settings": "user_cabinet_menu", "help": "help_command",
                    "channels": "channels_menu", "invite": "user_invite_menu", "team": "team_command"}
        for target, handler in expected.items():
            called.clear()
            asyncio.run(start_mod._open_go_target(upd, SimpleNamespace(), target, "uz"))
            T.check(f"go_{target} -> {handler}() chaqirildi", called == [handler], str(called))
        called.clear()
        asyncio.run(start_mod._open_go_target(upd, SimpleNamespace(), "unknown", "uz"))
        T.check("noma'lum bo'lim hech narsa ochmaydi", called == [])
    finally:
        for m, n, f in saved:
            setattr(m, n, f)


def test_real_flows():
    print("\n== 3. Matnda aytilgan yo'llar haqiqatan mavjud ==")
    import menu_commands
    from keyboards.inline import get_settings_hub_keyboard
    from translations import settings_stats_t

    handlers_src = (BOT / "handlers" / "__init__.py").read_text(encoding="utf8")
    T.check("CommandHandler('newpost') ro'yxatga olingan", 'CommandHandler("newpost"' in handlers_src)
    T.check("CommandHandler('settings') ro'yxatga olingan", 'CommandHandler("settings", user_cabinet_menu)' in handlers_src)
    T.check("`sub_` callbacklari subscription_callback'ga ulangan",
            'CallbackQueryHandler(subscription_callback, pattern=r"^sub_")' in handlers_src)
    names = menu_commands.MENU_COMMAND_NAMES
    T.check("☰ menyuda newpost, settings bor; /cleaner (imzo) yo'q", all(n in names for n in ("newpost", "settings")) and "cleaner" not in names)
    start_src = (BOT / "handlers" / "start.py").read_text(encoding="utf8")
    T.check("/settings (user_cabinet_menu) hub klaviaturasini yuboradi", "get_settings_hub_keyboard(lang)" in start_src.split("async def user_cabinet_menu")[1].split("async def ")[0])
    msgs = (REPO / "miniapp" / "src" / "i18n" / "messages.ts").read_text(encoding="utf8")
    for lang in ("uz", "ru", "en"):
        kb = get_settings_hub_keyboard(lang)
        buttons = [b for row in kb.inline_keyboard for b in row]
        pro = [b for b in buttons if b.callback_data == "sub_open"]
        T.check(f"[{lang}] hub'da PRO tugmasi `sub_open` ga ulangan", len(pro) == 1)
        label = settings_stats_t("ss_btn_pro_plans", lang)
        T.check(f"[{lang}] Mini App matni botdagi yorliqni aynan keltiradi ({label})", f"«{label}»" in msgs.replace("“", "«").replace("”", "»"))
    T.check("Mini App matnlari /newpost buyrug'ini aytadi (havola emas)", msgs.count("/newpost") >= 3)


def main() -> int:
    test_frontend_links()
    test_start_payload_behaviour()
    test_go_targets_runtime()
    test_real_flows()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
