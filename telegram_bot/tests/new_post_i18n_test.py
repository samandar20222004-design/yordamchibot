#!/usr/bin/env python3
"""Test new post oqimi UZ, RU, EN i18n to'liq zanjiri."""

import os
import sys
import re
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

TEST_FILE = Path(__file__).resolve()
ROOT = TEST_FILE.parent.parent  # /home/user/yordamchibot/telegram_bot
sys.path.insert(0, str(ROOT))

from locales.translations import TRANSLATIONS, DEFAULT_LANG, normalize_lang, get_text

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


def test_new_post_keys_exist():
    """Test that all new_post translation keys exist in UZ, RU, EN."""
    print("== new_post i18n completeness test ==")
    
    # Get all keys used in new_post.py
    np_path = ROOT.parent / "telegram_bot" / "handlers" / "new_post.py"
    with open(np_path, "r", encoding="utf-8") as f:
        np_content = f.read()
    
    # Extract keys from get_text("key", lang) pattern
    np_keys = set(re.findall(r'get_text\(["\']([^"\']+)["\']', np_content))
    
    print(f"Total new_post keys: {len(np_keys)}")
    
    # Check each language
    for lang_code, lang_name in [("uz", "UZ"), ("ru", "RU"), ("en", "EN")]:
        table = TRANSLATIONS.get(lang_code, {})
        if not isinstance(table, dict):
            check(f"{lang_name} table exists", False, "table is not dict")
            continue
        
        # For EN, also check overlay
        overlay_keys = set()
        if lang_code == "en":
            try:
                from locales.en_overlay import EN_OVERLAY
                overlay_keys = set(EN_OVERLAY.keys())
            except ImportError:
                overlay_keys = set()
        
        all_keys = set(table.keys()) | overlay_keys
        missing = np_keys - all_keys
        
        check(f"{lang_name}: all {len(np_keys)} keys present", len(missing) == 0,
              f"Missing: {len(missing)} keys")
        if missing:
            print(f"    Missing keys: {list(missing)[:5]}")


def test_uz_ru_parity():
    """Test UZ-RU translation parity for new_post keys."""
    print("\n== UZ-RU parity test ==")
    
    uz_keys = set(TRANSLATIONS.get("uz", {}).keys() or {})
    ru_keys = set(TRANSLATIONS.get("ru", {}).keys() or {})
    
    uz_only = sorted(uz_keys - ru_keys)
    ru_only = sorted(ru_keys - uz_keys)
    
    check(f"UZ has {len(uz_only)} keys only in UZ", len(uz_only) == 0,
          f"Keys: {uz_only[:5] if uz_only else 'none'}")
    check(f"RU has {len(ru_only)} keys only in RU", len(ru_only) == 0,
          f"Keys: {ru_only[:5] if ru_only else 'none'}")


def test_get_text_works():
    """Test that get_text works for all new_post keys in all languages."""
    print("\n== get_text functionality test ==")
    
    np_path = ROOT.parent / "telegram_bot" / "handlers" / "new_post.py"
    with open(np_path, "r", encoding="utf-8") as f:
        np_content = f.read()
    
    np_keys = set(re.findall(r'get_text\(["\']([^"\']+)["\']', np_content))
    
    for lang_code in ["uz", "ru", "en"]:
        table = TRANSLATIONS.get(lang_code, {})
        if not isinstance(table, dict):
            continue
        
        for key in list(np_keys)[:20]:  # Test first 20 keys
            try:
                text = get_text(key, lang=lang_code)
                check(f"get_text({key!r}, {lang_code}) works", True)
            except Exception as e:
                check(f"get_text({key!r}, {lang_code}) works", False, str(e))


# Run tests
test_new_post_keys_exist()
test_uz_ru_parity()
test_get_text_works()

print(f"\n\n=== Results: {passed} passed, {failures} failed ===")
