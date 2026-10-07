#!/usr/bin/env python3
"""⚙️ SOZLAMALAR menyusida dublikat guruhlar yo'qligini qat'iy tekshirish.

1-QADAM kabinet dublikatlarini tozalagan edi; 3-QADAM hub'ni yanada
ixchamlashtirdi, KLASSIK qaytarish esa «👥 Do'stlarni taklif» tugmasini
asosiy menyudan Sozlamalar hub'iga ko'chirdi. 3-BOSQICH: «💎 PRO» va «❓ Yordam» ham
asosiy reply-menudan shu hub'ga ko'chirildi. Jami 8 tugma:
Til | Post sozlamalari | Bildirishnomalar | Do'stlarni taklif |
To'lovlar | PRO | Yordam va Qo'llanma | Yopish."""
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
        # QAT'IY: 10 tugma (⚙️ Sozlamalar; SPRINT 1: 🔐 Maxfiylik +
        # 🗑 Ma'lumotlarimni o'chirish qatori qo'shildi):
        # Til | Post sozlamalari | Bildirishnomalar | Do'stlarni taklif |
        # To'lovlar | PRO | Maxfiylik | O'chirish | Yordam va Qo'llanma | Yopish
        assert len(cbs)==10, f"[{lang}] 10 tugma kerak, {len(cbs)} topildi"
        assert "sub_open" in cbs, f"[{lang}] PRO tugmasi hub'da yo'q: {cbs}"
        assert "stgs_help_hub" in cbs, f"[{lang}] Yordam tugmasi hub'da yo'q: {cbs}"
        # QAT'IY: eski cab_* yo'q
        for cb in cbs:
            assert not cb.startswith("cab_"), f"[{lang}] Eski cab_ callback topildi: {cb}"
        # QAT'IY: «👤 Profil» ham yo'q — kabinet matnining o'zi profil
        assert "stgs_profile" not in cbs, f"[{lang}] Profil tugmasi hub'da qolib ketdi: {cbs}"
        # QAT'IY: eski matnlar yo'q
        forbidden = ["Mening kanallarim","Kanallar analitikasi","Kutilayotgan postlar","Rejalashtirilgan","Ballar & Reklama rejimi","👤 Profil"]
        for f in forbidden:
            assert f not in texts, f"[{lang}] Eski matn topildi: {f}"
        # QAT'IY: «🎁 Bonuslar & Taklif» guruhi hub'dan olib tashlandi —
        # referral endi alohida «👥 Do'stlarni taklif» tugmasida
        # (stgs_referral), guruh tugmasi emas.
        assert not any("Bonuslar & Taklif" in t or "Бонусы и приглашения" in t
                       or "Bonus" in t for t in texts), f"[{lang}] Bonuslar & Taklif qoldi: {texts}"
        assert "stgs_referral" in cbs, f"[{lang}] stgs_referral topilmadi: {cbs}"
        assert not any("Bonuslar & Ballar" in t or "Бонусы и баллы" in t
                       or "Vositalar" in t or "Инструменты" in t or "Tools" in t
                       for t in texts), texts
        # Yangi 10 tugma to'liqligi
        assert "stgs_hub" not in cbs  # hub o'zi callback emas, yopish stgs_back
        for cb in ("stgs_lang", "stgs_post", "stgs_notif", "stgs_referral",
                   "stgs_pay", "sub_open", "stgs_privacy", "stgs_delete_data",
                   "stgs_help_hub", "stgs_back"):
            assert cb in cbs, f"[{lang}] {cb} topilmadi: {cbs}"
        # Eski guruh parent'lari ko'rinishdan chiqdi (routing'da qoladi)
        for cb in ("stgs_rewards", "stgs_tools"):
            assert cb not in cbs, f"[{lang}] {cb} hub'da qolib ketdi: {cbs}"
    print("✅ ⚙️ Sozlamalar — 10 tugma (PRO + Yordam + Maxfiylik/O'chirish shu yerda), dublikat guruhlar yo'q, Qo'llab-quvvatlash bir tugmada")

if __name__=="__main__":
    test()
