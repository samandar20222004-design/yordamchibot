#!/usr/bin/env python3
"""🎯 PHASE 9 — UX, ONBOARDING VA CONTEXTUAL MENUS TEST SUITE.

Tekshiriladigan talablar:
  1. ASOSIY MENYU KONSOLIDATSIYASI:
     - 5 ta asosiy tugma: [✍️ Post yaratish], [📢 Kanallarim],
       [📅 Rejalashtirilgan], [📊 Statistika], [⚙️ Sozlamalar]
     - Admin tugmalari faqat adminga ko'rinadi
     - Murakkab funksiyalar Inline/Contextual menyular ichiga yashirilgan
  2. CONTEXTUAL MENULAR:
     - [✍️ Post yaratish] bosilganda 4x2 inline menyu:
       [⚡ AI Post] | [📝 Oddiy Post]
       [🖼 Rasmdan Post] | [🎙 Ovozdan Post]
       [🔗 Havoladan Post] | [♻️ Qayta ishlash]
       [🤖 AI Yordamchi] | [📊 Post Score]
     - [📢 Kanallarim] ichida har bir kanal uchun:
       [➕ Kanal qo‘shish]
       [🚀 Autopilot] | [📋 Kontent reja]
       [🧬 Channel DNA] | [📊 Analytics]
       [👥 Team] | [⚙️ Sozlamalar]
  3. 2 DAQIQALIK INSTANT-VALUE ONBOARDING:
     - 1) Qisqa salomlashuv
     - 2) "Telegram kanalingizni ulang"
     - 3) Kanal ulangach -> Avtomatik tezkor Channel DNA tahlili
     - 4) Qisqa xulosa -> "7 kunlik kontent reja tuzamizmi?" taklifi
     - 5) Bitta tugma bilan birinchi foydali natijani olish
  4. ERROR UX VA USER COMMUNICATION:
     - Hech qachon "Exception occurred" ko'rsatilmaydi
     - AI band: "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring."
     - Telegram flood: "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi."
     - URL xato: "Bu havolani xavfsiz yuklab bo‘lmadi."
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456789:TEST_PHASE9_UX_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("ADMIN_IDS", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        extra = f" -> {detail}" if detail else ""
        print(f"  [FAIL] {name}{extra}")


# ======================================================================
# 1. ASOSIY MENYU KONSOLIDATSIYASI (5 TA ASOSIY TUGMA + ADMIN FILTER)
# ======================================================================
def test_main_menu_consolidation() -> None:
    print("\n1. Asosiy menyu konsolidatsiyasi (5 ta asosiy tugma + Admin izolyatsiyasi)")
    from keyboards.default import (
        BTN_ADMIN_PANEL,
        BTN_MY_CHANNELS,
        BTN_POST_CREATE,
        BTN_SCHEDULED,
        BTN_SETTINGS_CORE,
        BTN_STATISTICS,
        CORE_MAIN_MENU_KEYS,
        get_main_keyboard,
        get_phase9_main_keyboard,
        is_menu_text,
    )

    check("CORE_MAIN_MENU_KEYS 5 ta kalitdan iborat", len(CORE_MAIN_MENU_KEYS) == 5)

    kb_user = get_phase9_main_keyboard(is_admin=False, lang="uz")
    flat_user = [btn.text for row in kb_user.keyboard for btn in row]
    expected_uz = [
        "✍️ Post yaratish",
        "📢 Kanallarim",
        "📅 Rejalashtirilgan",
        "📊 Statistika",
        "⚙️ Sozlamalar",
    ]
    check(
        "Oddiy foydalanuvchi uchun 5 ta asosiy tugma (UZ)",
        flat_user == expected_uz,
        f"got={flat_user}",
    )
    check(
        "Oddiy foydalanuvchiga Admin Panel ko'rinmaydi",
        BTN_ADMIN_PANEL not in flat_user,
    )

    kb_admin = get_phase9_main_keyboard(is_admin=True, lang="uz")
    flat_admin = [btn.text for row in kb_admin.keyboard for btn in row]
    check(
        "Admin uchun 5 ta asosiy tugma + [⚙️ Admin Panel] ko'rinadi",
        flat_admin == expected_uz + [BTN_ADMIN_PANEL],
        f"got={flat_admin}",
    )

    # 3 tilda (UZ, RU, EN) 5 ta tugma va <= 18 belgi tekshiruvi
    for lang in ("uz", "ru", "en"):
        kb_l = get_phase9_main_keyboard(is_admin=False, lang=lang)
        btns_l = [btn.text for row in kb_l.keyboard for btn in row]
        check(f"[{lang}] 5 ta asosiy tugma", len(btns_l) == 5, f"got={btns_l}")

    # get_main_keyboard(..., phase9_core=True) yoki context phase9_core_menu
    ctx_p9 = SimpleNamespace(user_data={"phase9_core_menu": True})
    kb_via_main = get_main_keyboard(False, lang="uz", context=ctx_p9)
    flat_via_main = [btn.text for row in kb_via_main.keyboard for btn in row]
    check(
        "get_main_keyboard(context=phase9_core_menu) 5 ta asosiy tugmani qaytaradi",
        flat_via_main == expected_uz,
    )

    # Menu text registry: [✍️ Post yaratish] -> create_content, [⚙️ Sozlamalar] -> settings
    check(
        "BTN_POST_CREATE create_content oilasida taniladi",
        is_menu_text(BTN_POST_CREATE, "create_content"),
    )
    check(
        "BTN_SETTINGS_CORE settings oilasida taniladi",
        is_menu_text(BTN_SETTINGS_CORE, "settings"),
    )
    check("BTN_MY_CHANNELS == '📢 Kanallarim'", BTN_MY_CHANNELS == "📢 Kanallarim")
    check("BTN_SCHEDULED == '📅 Rejalashtirilgan'", BTN_SCHEDULED == "📅 Rejalashtirilgan")
    check("BTN_STATISTICS == '📊 Statistika'", BTN_STATISTICS == "📊 Statistika")


# ======================================================================
# 2. CONTEXTUAL MENULAR ([✍️ Post yaratish] va [📢 Kanallarim])
# ======================================================================
def test_post_creation_contextual_menu() -> None:
    print("\n2A. [✍️ Post yaratish] kontekstual inline menyusi (4x2, 8 tugma, i18n, <=18 belgi)")
    from keyboards.callback_data import (
        CB_CTX_AI_ASSISTANT,
        CB_CTX_AI_POST,
        CB_CTX_IMAGE_POST,
        CB_CTX_LINK_POST,
        CB_CTX_MANUAL_POST,
        CB_CTX_POST_SCORE,
        CB_CTX_RECYCLE_POST,
        CB_CTX_VOICE_POST,
        is_registered_callback,
    )
    from keyboards.inline import get_post_creation_contextual_keyboard

    kb_uz = get_post_creation_contextual_keyboard("uz")
    rows_uz = [[btn.text for btn in row] for row in kb_uz.inline_keyboard]
    expected_rows_uz = [
        ["⚡ AI Post", "📝 Oddiy Post"],
        ["🖼 Rasmdan Post", "🎙 Ovozdan Post"],
        ["🔗 Havoladan Post", "♻️ Qayta ishlash"],
        ["🤖 AI Yordamchi", "📊 Post Score"],
    ]
    check(
        "[✍️ Post yaratish] UZ menyusi aynan 4x2 talab qilingan tartibda",
        rows_uz == expected_rows_uz,
        f"got={rows_uz}",
    )

    cbs_uz = [[btn.callback_data for btn in row] for row in kb_uz.inline_keyboard]
    expected_cbs = [
        [CB_CTX_AI_POST, CB_CTX_MANUAL_POST],
        [CB_CTX_IMAGE_POST, CB_CTX_VOICE_POST],
        [CB_CTX_LINK_POST, CB_CTX_RECYCLE_POST],
        [CB_CTX_AI_ASSISTANT, CB_CTX_POST_SCORE],
    ]
    check("Barcha 8 ta callback_data to'g'ri bog'langan", cbs_uz == expected_cbs)
    for row in expected_cbs:
        for cb_val in row:
            check(
                f"Callback '{cb_val}' fail-closed reyestrda ro'yxatdan o'tgan",
                is_registered_callback(cb_val),
            )

    for lang in ("uz", "ru", "en"):
        kb = get_post_creation_contextual_keyboard(lang)
        all_btns = [btn for row in kb.inline_keyboard for btn in row]
        check(
            f"[{lang}] 8 ta tugma va har biri <= 18 belgi",
            len(all_btns) == 8 and all(1 <= len(b.text) <= 18 for b in all_btns),
            f"lengths={[(b.text, len(b.text)) for b in all_btns]}",
        )


def test_post_creation_contextual_dispatch() -> None:
    print("\n2B. [✍️ Post yaratish] tugmalari dispatcher oqimlari (8 yo'nalish)")
    import database as db
    from handlers.ai_assistant import AI_MENU_STATE, ai_studio_menu_entry
    from handlers.content_menu import contextual_post_menu_callback
    from handlers.image_post import IMAGE_POST_INPUT
    from handlers.magic_post import MAGIC_INPUT
    from handlers.manual_post import MANUAL_AWAIT_CONTENT
    from handlers.post_score import POST_SCORE_INPUT
    from handlers.sources import SRC_RECYCLE_LIST, SRC_URL_INPUT
    from handlers.voice_post import VOICE_AWAIT
    from keyboards.callback_data import (
        CB_CTX_AI_ASSISTANT,
        CB_CTX_AI_POST,
        CB_CTX_IMAGE_POST,
        CB_CTX_LINK_POST,
        CB_CTX_MANUAL_POST,
        CB_CTX_POST_SCORE,
        CB_CTX_RECYCLE_POST,
        CB_CTX_VOICE_POST,
    )

    async def _run():
        replies = []

        async def fake_reply_text(text, **kwargs):
            replies.append((text, kwargs))

        msg = SimpleNamespace(reply_text=fake_reply_text)
        user = SimpleNamespace(id=777001, first_name="Tester")
        ctx = SimpleNamespace(user_data={"lang": "uz"})
        upd_entry = SimpleNamespace(message=msg, effective_message=msg, effective_user=user)

        await ai_studio_menu_entry(upd_entry, ctx)
        check("ai_studio_menu_entry xabar yuboradi", len(replies) == 1)
        _, kw = replies[0]
        markup = kw.get("reply_markup")
        check(
            "ai_studio_menu_entry 4x2 kontekstual menyuni qaytaradi",
            markup is not None and len(markup.inline_keyboard) == 4,
        )

        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name in ("get_user_channels", "get_user_channels_with_tone"):
                return [("-100555", "Texno Kanal", "friendly")]
            if name == "get_user_ai_credits":
                return 10
            return []

        def make_cb_update(cb_data: str):
            async def _ans(*a, **k):
                return True

            async def _edit(text, **k):
                replies.append((text, k))
                return True

            q = SimpleNamespace(
                data=cb_data,
                from_user=user,
                message=msg,
                answer=_ans,
                edit_message_text=_edit,
            )
            return SimpleNamespace(
                callback_query=q,
                effective_user=user,
                effective_message=msg,
                message=None,
            )

        with patch.object(db, "run_db", side_effect=fake_run_db):
            st_ai = await contextual_post_menu_callback(make_cb_update(CB_CTX_AI_POST), ctx)
            check("[⚡ AI Post] -> MAGIC_INPUT", st_ai == MAGIC_INPUT, f"got={st_ai}")

            st_man = await contextual_post_menu_callback(make_cb_update(CB_CTX_MANUAL_POST), ctx)
            check(
                "[📝 Oddiy Post] -> MANUAL_AWAIT_CONTENT",
                st_man == MANUAL_AWAIT_CONTENT,
                f"got={st_man}",
            )

            st_img = await contextual_post_menu_callback(make_cb_update(CB_CTX_IMAGE_POST), ctx)
            check(
                "[🖼 Rasmdan Post] -> IMAGE_POST_INPUT",
                st_img == IMAGE_POST_INPUT,
                f"got={st_img}",
            )

            st_vc = await contextual_post_menu_callback(make_cb_update(CB_CTX_VOICE_POST), ctx)
            check("[🎙 Ovozdan Post] -> VOICE_AWAIT", st_vc == VOICE_AWAIT, f"got={st_vc}")

            st_url = await contextual_post_menu_callback(make_cb_update(CB_CTX_LINK_POST), ctx)
            check(
                "[🔗 Havoladan Post] -> SRC_URL_INPUT",
                st_url == SRC_URL_INPUT,
                f"got={st_url}",
            )

            st_rec = await contextual_post_menu_callback(make_cb_update(CB_CTX_RECYCLE_POST), ctx)
            check(
                "[♻️ Qayta ishlash] -> SRC_RECYCLE_LIST",
                st_rec == SRC_RECYCLE_LIST,
                f"got={st_rec}",
            )

            st_ast = await contextual_post_menu_callback(make_cb_update(CB_CTX_AI_ASSISTANT), ctx)
            check(
                "[🤖 AI Yordamchi] -> AI_MENU_STATE",
                st_ast == AI_MENU_STATE,
                f"got={st_ast}",
            )

            st_ps = await contextual_post_menu_callback(make_cb_update(CB_CTX_POST_SCORE), ctx)
            check(
                "[📊 Post Score] -> POST_SCORE_INPUT",
                st_ps == POST_SCORE_INPUT,
                f"got={st_ps}",
            )

    asyncio.run(_run())


def test_channels_contextual_menu() -> None:
    print("\n2C. [📢 Kanallarim] kontekstual menyusi (Autopilot, Kontent reja, DNA, Analytics, Team, Sozlamalar)")
    import database as db
    from handlers.channels import channel_plan_callback, channel_team_callback
    from handlers.content_plan import PLAN_GET_TOPIC
    from keyboards.callback_data import is_registered_callback
    from keyboards.inline import get_channel_contextual_keyboard, render_channel_panel

    ch_id = "-100987654321"
    kb_uz = render_channel_panel(ch_id, "uz")
    rows_uz = [[btn.text for btn in row] for row in kb_uz.inline_keyboard]
    expected_rows_uz = [
        ["➕ Kanal qo‘shish"],
        ["🚀 Autopilot", "📋 Kontent reja"],
        ["🧬 Channel DNA", "📊 Analytics"],
        ["👥 Team", "⚙️ Sozlamalar"],
        ["◀️ Orqaga"],
    ]
    check(
        "[📢 Kanallarim] kanal menyusi (UZ) talab qilingan kontekstual tartibda",
        rows_uz == expected_rows_uz,
        f"got={rows_uz}",
    )

    cbs = [[btn.callback_data for btn in row] for row in kb_uz.inline_keyboard]
    expected_cbs = [
        ["add_channel_start"],
        [f"ch_ap:{ch_id}", f"ch_plan:{ch_id}"],
        [f"ch_dna:{ch_id}", f"ch_st:{ch_id}"],
        [f"ch_team:{ch_id}", f"ch_set:{ch_id}"],
        ["ch_back"],
    ]
    check("Kanal kontekstual tugmalari callback_data to'g'ri", cbs == expected_cbs, f"got={cbs}")
    for row in expected_cbs:
        for cb_val in row:
            check(
                f"Kanal callback '{cb_val}' fail-closed reyestrda ro'yxatdan o'tgan",
                is_registered_callback(cb_val),
            )

    for lang in ("uz", "ru", "en"):
        kb = get_channel_contextual_keyboard(ch_id, lang)
        all_btns = [btn for row in kb.inline_keyboard for btn in row]
        check(
            f"[{lang}] Kanal menyusidagi barcha tugmalar <= 18 belgi",
            all(1 <= len(b.text) <= 18 for b in all_btns),
            f"lengths={[(b.text, len(b.text)) for b in all_btns]}",
        )

    # channel_plan_callback va channel_team_callback oqimlari
    async def _run_channel_cbs():
        sent = []
        edited = []

        async def _reply(text, **kw):
            sent.append((text, kw))

        async def _edit(text, **kw):
            edited.append((text, kw))

        async def _ans(*a, **k):
            return True

        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "get_user_channels_with_tone":
                return [(ch_id, "Biznes Kanal", "formal")]
            return []

        user = SimpleNamespace(id=123456789, first_name="Owner")
        msg = SimpleNamespace(reply_text=_reply)
        ctx = SimpleNamespace(user_data={"lang": "uz"})

        with patch.object(db, "run_db", side_effect=fake_run_db), patch(
            "handlers.channels._rbac_channel_allowed", return_value=True
        ):
            q_plan = SimpleNamespace(
                data=f"ch_plan:{ch_id}",
                from_user=user,
                message=msg,
                answer=_ans,
                edit_message_text=_edit,
            )
            upd_plan = SimpleNamespace(
                callback_query=q_plan, effective_user=user, effective_message=msg
            )
            st_plan = await channel_plan_callback(upd_plan, ctx)
            check(
                "[📋 Kontent reja] -> PLAN_GET_TOPIC va plan_channel_id saqlanadi",
                st_plan == PLAN_GET_TOPIC and ctx.user_data.get("plan_channel_id") == ch_id,
                f"state={st_plan}",
            )

            q_team = SimpleNamespace(
                data=f"ch_team:{ch_id}",
                from_user=user,
                message=msg,
                answer=_ans,
                edit_message_text=_edit,
            )
            upd_team = SimpleNamespace(
                callback_query=q_team, effective_user=user, effective_message=msg
            )
            await channel_team_callback(upd_team, ctx)
            check(
                "[👥 Team] -> Jamoa kartochkasi va kanal paneli ko'rsatiladi",
                len(edited) == 1 and "Biznes Kanal" in edited[0][0],
            )

    asyncio.run(_run_channel_cbs())


# ======================================================================
# 3. 2 DAQIQALIK INSTANT-VALUE ONBOARDING (5 QADAM)
# ======================================================================
def test_instant_value_onboarding() -> None:
    print("\n3. 2 daqiqalik Instant-Value Onboarding (5 qadam: salomlashuv -> ulash -> DNA -> xulosa -> 1-click 7 kunlik reja)")
    import database as db
    from handlers.autopilot import AUTOPILOT_VIEW, UD_DAYS
    from handlers.onboarding import (
        analyze_quick_channel_dna,
        build_instant_onboarding_greeting,
        onboarding_quick_plan_callback,
        run_instant_dna_onboarding,
    )
    from keyboards.callback_data import is_registered_callback

    # 1- va 2-qadamlar: Qisqa salomlashuv + "Telegram kanalingizni ulang"
    greeting_uz = build_instant_onboarding_greeting("uz")
    check(
        "1-qadam: Qisqa salomlashuv mavjud",
        "Xush kelibsiz" in greeting_uz or "PostAssist" in greeting_uz,
    )
    check(
        "2-qadam: 'Telegram kanalingizni ulang' aniq ko'rsatilgan",
        "Telegram kanalingizni ulang" in greeting_uz,
        f"got={greeting_uz}",
    )
    check(
        "Onboarding matnida '7 kunlik kontent reja tuzamizmi?' eslatilgan",
        "7 kunlik kontent reja tuzamizmi?" in greeting_uz,
    )

    for lang in ("uz", "ru", "en"):
        g = build_instant_onboarding_greeting(lang)
        check(f"[{lang}] Instant onboarding greeting bo'sh emas", len(g) > 40)

    # 3-, 4- va 5-qadamlar: Kanal ulangach -> Avtomatik tezkor DNA tahlili ->
    # Qisqa xulosa + "7 kunlik kontent reja tuzamizmi?" -> 1-click reja
    async def _run_onboarding_flow():
        ch_id = "-100777888999"
        sent_cards = []

        async def fake_send(text, **kwargs):
            sent_cards.append((text, kwargs))

        dna_info = await analyze_quick_channel_dna(
            user_id=5001, channel_id=ch_id, channel_title="Startap Uz", lang="uz"
        )
        check(
            "3-qadam: Avtomatik tezkor Channel DNA tahlili natija qaytaradi",
            bool(dna_info.get("style")) and bool(dna_info.get("summary")),
            f"dna={dna_info}",
        )

        ok = await run_instant_dna_onboarding(
            fake_send,
            user_id=5001,
            channel_id=ch_id,
            channel_title="Startap Uz",
            lang="uz",
        )
        check("4-qadam: run_instant_dna_onboarding xulosa kartasini yuboradi", ok and len(sent_cards) == 1)
        card_text, card_kw = sent_cards[0]
        check(
            "4-qadam: Qisqa xulosada '7 kunlik kontent reja tuzamizmi?' taklifi bor",
            "7 kunlik kontent reja tuzamizmi?" in card_text and "Startap Uz" in card_text,
            f"card={card_text}",
        )
        offer_kb = card_kw.get("reply_markup")
        btn = offer_kb.inline_keyboard[0][0]
        check(
            "4-qadam: 1-click tugma <= 18 belgi va onb_plan:<id> callback'ga ega",
            len(btn.text) <= 18
            and btn.callback_data == f"onb_plan:{ch_id}"
            and is_registered_callback(btn.callback_data),
            f"btn={btn.text!r} ({btn.callback_data!r})",
        )

        # 5-qadam: Bitta tugma bosilganda 7 kunlik kontent reja tayyor bo'ladi
        plan_replies = []

        async def fake_plan_reply(text, **kwargs):
            plan_replies.append((text, kwargs))

        async def fake_ans(*a, **k):
            return True

        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "get_user_channels_with_tone":
                return [(ch_id, "Startap Uz", "friendly")]
            return []

        user = SimpleNamespace(id=5001, first_name="Founder")
        msg = SimpleNamespace(reply_text=fake_plan_reply)
        q = SimpleNamespace(
            data=f"onb_plan:{ch_id}",
            from_user=user,
            message=msg,
            answer=fake_ans,
        )
        upd = SimpleNamespace(callback_query=q, effective_user=user, effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz"})

        with patch.object(db, "run_db", side_effect=fake_run_db):
            state = await onboarding_quick_plan_callback(upd, ctx)

        check(
            "5-qadam: Bitta tugma bilan 7 kunlik reja generatsiya qilinadi (AUTOPILOT_VIEW)",
            state == AUTOPILOT_VIEW
            and len(plan_replies) == 1
            and len(ctx.user_data.get(UD_DAYS) or []) == 7,
            f"state={state}, days={len(ctx.user_data.get(UD_DAYS) or [])}",
        )

    asyncio.run(_run_onboarding_flow())


# ======================================================================
# 4. ERROR UX VA USER COMMUNICATION
# ======================================================================
def test_error_ux_and_user_communication() -> None:
    print("\n4. Error UX va User Communication (aniq, muloyim xabarlar; hech qachon 'Exception occurred' yo'q)")
    from telegram.error import RetryAfter
    from handlers.error_handler import (
        classify_user_error_kind,
        format_user_error_message,
        global_error_handler,
        sanitize_user_error_text,
    )
    from handlers.sources import SRC_URL_INPUT, UD_CHANNEL, url_text_received

    # 1) AI band bo'lsa: "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring."
    ai_exc = RuntimeError("OpenAI rate_limit_exceeded: AI busy")
    check("AI xatosi 'ai_busy' deb tasniflanadi", classify_user_error_kind(ai_exc) == "ai_busy")
    ai_msg_uz = format_user_error_message(ai_exc, "uz")
    check(
        "AI band xabari (UZ) talabga aynan mos",
        ai_msg_uz == "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring.",
        f"got={ai_msg_uz!r}",
    )

    # 2) Telegram flood bo'lsa: "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi."
    flood_exc = RetryAfter(25)
    check(
        "Telegram RetryAfter 'telegram_flood' deb tasniflanadi",
        classify_user_error_kind(flood_exc) == "telegram_flood",
    )
    flood_msg_uz = format_user_error_message(flood_exc, "uz")
    check(
        "Telegram flood xabari (UZ) talabga aynan mos",
        flood_msg_uz == "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi.",
        f"got={flood_msg_uz!r}",
    )

    # 3) URL xato bo'lsa: "Bu havolani xavfsiz yuklab bo‘lmadi."
    url_exc = ValueError("url_security_gateway: private_address SSRF blocked")
    check("URL xatosi 'url_error' deb tasniflanadi", classify_user_error_kind(url_exc) == "url_error")
    url_msg_uz = format_user_error_message(url_exc, "uz")
    check(
        "URL xato xabari (UZ) talabga aynan mos",
        url_msg_uz == "Bu havolani xavfsiz yuklab bo‘lmadi.",
        f"got={url_msg_uz!r}",
    )

    # 4) 3 tilda (UZ, RU, EN) barcha 3 xato xabari mavjud va "Exception occurred" yo'q
    for lang in ("uz", "ru", "en"):
        for exc in (ai_exc, flood_exc, url_exc, RuntimeError("Exception occurred in module")):
            msg = format_user_error_message(exc, lang)
            check(
                f"[{lang}] '{type(exc).__name__}' xabarida 'Exception occurred' yo'q",
                "exception occurred" not in msg.lower() and "traceback" not in msg.lower(),
                f"got={msg!r}",
            )

    # 5) sanitize_user_error_text texnik "Exception occurred" matnini tozalaydi
    sanitized = sanitize_user_error_text("Exception occurred: KeyError('x')", "uz")
    check(
        "sanitize_user_error_text 'Exception occurred' ni muloyim xabarga almashtiradi",
        "exception occurred" not in sanitized.lower() and "keyerror" not in sanitized.lower(),
        f"got={sanitized!r}",
    )

    # 6) global_error_handler va url_text_received integratsiyasi
    async def _run_error_handlers():
        replies = []

        async def _reply(text, **kw):
            replies.append(text)

        msg = SimpleNamespace(reply_text=_reply, text="http://127.0.0.1/admin")
        user = SimpleNamespace(id=9001, first_name="User")
        upd = SimpleNamespace(
            effective_message=msg,
            message=msg,
            effective_user=user,
            effective_chat=SimpleNamespace(id=9001),
            callback_query=None,
        )

        for err_obj, expected_text in (
            (ai_exc, "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring."),
            (flood_exc, "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi."),
            (url_exc, "Bu havolani xavfsiz yuklab bo‘lmadi."),
        ):
            replies.clear()
            ctx = SimpleNamespace(error=err_obj, user_data={"lang": "uz"})
            await global_error_handler(upd, ctx)
            check(
                f"global_error_handler -> {expected_text!r}",
                len(replies) == 1 and replies[0] == expected_text,
                f"got={replies}",
            )

        # url_text_received SSRF / xavfsiz bo'lmagan havolada aniq xabar qaytaradi
        replies.clear()
        ctx_url = SimpleNamespace(user_data={"lang": "uz", UD_CHANNEL: "-100111"})
        st = await url_text_received(upd, ctx_url)
        check(
            "url_text_received xavfli havolada 'Bu havolani xavfsiz yuklab bo‘lmadi.' qaytaradi",
            st == SRC_URL_INPUT
            and len(replies) == 1
            and replies[0] == "Bu havolani xavfsiz yuklab bo‘lmadi.",
            f"got={replies}",
        )

    asyncio.run(_run_error_handlers())


def main() -> int:
    print("=" * 72)
    print("PHASE 9 — UX, ONBOARDING VA CONTEXTUAL MENUS TEST SUITE")
    print("=" * 72)
    test_main_menu_consolidation()
    test_post_creation_contextual_menu()
    test_post_creation_contextual_dispatch()
    test_channels_contextual_menu()
    test_instant_value_onboarding()
    test_error_ux_and_user_communication()
    print("=" * 72)
    print(f"JAMI: {passed} passed, {failed} failed")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
