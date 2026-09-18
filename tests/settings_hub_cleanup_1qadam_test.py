#!/usr/bin/env python3
"""3-QADAM (ixchamlashtirish): 👤 Profil menyusida dublikat guruhlar yo'qligini qat'iy tekshirish.

1-QADAM kabinet dublikatlarini tozalagan edi; 3-QADAM hub'ni yanada
ixchamlashtirdi: «🎁 Bonuslar & Taklif» → asosiy menyu («👥 Do'stlarni
taklif»), «🧰 Vositalar» va «❓ Yordam» hub'i ko'rinishdan chiqdi —
faqat [💬 Qo'llab-quvvatlash] qoldi. Jami 6 tugma."""
import os, sys
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

from keyboards.inline import get_settings_hub_keyboard

def test():
    for lang in ("uz","ru","en"):
        kb = get_settings_hub_keyboard(lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        texts = [b.text for row in kb.inline_keyboard for b in row]
        # QAT'IY: 6 tugma (ixcham 👤 Profil — 3-QISM):
        # Til | Post sozlamalari | Bildirishnomalar | To'lovlar |
        # Qo'llab-quvvatlash | Yopish
        assert len(cbs)==6, f"[{lang}] 6 tugma kerak, {len(cbs)} topildi"
        # QAT'IY: eski cab_* yo'q
        for cb in cbs:
            assert not cb.startswith("cab_"), f"[{lang}] Eski cab_ callback topildi: {cb}"
        # QAT'IY: «👤 Profil» ham yo'q — kabinet matnining o'zi profil
        assert "stgs_profile" not in cbs, f"[{lang}] Profil tugmasi hub'da qolib ketdi: {cbs}"
        # QAT'IY: eski matnlar yo'q
        forbidden = ["Mening kanallarim","Kanallar analitikasi","Kutilayotgan postlar","Rejalashtirilgan","Ballar & Reklama rejimi","👤 Profil"]
        for f in forbidden:
            assert f not in texts, f"[{lang}] Eski matn topildi: {f}"
        # QAT'IY (3-QISM): «🎁 Bonuslar & Taklif» hub'dan olib tashlandi —
        # referral endi ASOSIY menyu «👥 Do'stlarni taklif» tugmasida.
        assert not any("Taklif" in t or "приглашения" in t or "Invites" in t
                       for t in texts), f"[{lang}] Bonuslar & Taklif qoldi: {texts}"
        assert not any("Bonuslar & Ballar" in t or "Бонусы и баллы" in t
                       or "Vositalar" in t or "Инструменты" in t or "Tools" in t
                       for t in texts), texts
        # Yangi ixcham 6 tugma to'liqligi
        assert "stgs_hub" not in cbs  # hub o'zi callback emas, yopish stgs_back
        for cb in ("stgs_lang", "stgs_post", "stgs_notif", "stgs_pay",
                   "help_support", "stgs_back"):
            assert cb in cbs, f"[{lang}] {cb} topilmadi: {cbs}"
        # Eski guruh parent'lari ko'rinishdan chiqdi (routing'da qoladi)
        for cb in ("stgs_rewards", "stgs_tools", "stgs_help_hub"):
            assert cb not in cbs, f"[{lang}] {cb} hub'da qolib ketdi: {cbs}"
    print("✅ 3-QADAM: 👤 Profil ixcham — 6 tugma, dublikat guruhlar yo'q, Qo'llab-quvvatlash bir tugmada")

if __name__=="__main__":
    test()
