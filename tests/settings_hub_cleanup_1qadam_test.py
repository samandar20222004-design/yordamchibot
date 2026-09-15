#!/usr/bin/env python3
"""1-QADAM: Sozlamalar menyusida eski kabinet tugmalari yo'qligini qat'iy tekshirish"""
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
        # QAT'IY: 9 tugma
        assert len(cbs)==9, f"[{lang}] 9 tugma kerak, {len(cbs)} topildi"
        # QAT'IY: eski cab_* yo'q
        for cb in cbs:
            assert not cb.startswith("cab_"), f"[{lang}] Eski cab_ callback topildi: {cb}"
        # QAT'IY: eski matnlar yo'q
        forbidden = ["Mening kanallarim","Kanallar analitikasi","Kutilayotgan postlar","Rejalashtirilgan","Ballar & Reklama rejimi"]
        for f in forbidden:
            assert f not in texts, f"[{lang}] Eski matn topildi: {f}"
        # Yangi 8+1 borligi
        assert "stgs_hub" not in cbs  # hub o'zi callback emas, orqaga stgs_back
        assert "stgs_back" in cbs
        assert "stgs_profile" in cbs
        assert "stgs_lang" in cbs
    print("✅ 1-QADAM: Sozlamalar hub toza, eski kabinet tugmalari yo'q, 8+1 menyu to'g'ri")

if __name__=="__main__":
    test()
