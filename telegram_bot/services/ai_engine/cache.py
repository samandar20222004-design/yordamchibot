"""Deterministik AI javob keshi (AI ENGINE V2, Faza 1).

Audit topilmasi: "tezkor kesh yo'q" — bir xil so'rov har safar provayderga
yuborilardi (bepul RPM limitlarini keraksiz yeydi, foydalanuvchi kutardi).

Bu modul kichik, xavfsiz in-memory kesh:

* **Deterministik kalit** — ``sha256(lane|task|lang|tone|is_pro|system|prompt)``.
  Bir xil so'rov → aynan bir xil kalit (provayder tartibidan MUSTAQIL —
  fallback boshqa provayderga o'tsa ham kalit o'zgarmaydi).
* **TTL** (default 15 daqiqa) — eskirgan javob qaytmaydi.
* **LRU chegara** (default 512 yozuv) — xotira cheklangan.
* Faqat FAST lane default keshlanadi (Quality/Reasoning javoblari
  kontekstga bog'liq — kesh faqat aniq so'ralganda ishlaydi).

Not: bu kesh FAQAT yangi shlyuz (``services.ai_engine.gateway``) uchun.
Legacy ``generate_ai_response`` chaqiruvlari keshga tegmaydi (eski
testlar/HTTP zanjir determinizmi saqlanadi).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

#: Kesh yozuvi prefiksi (diagnostika/loglar uchun qulay).
KEY_PREFIX = "aicache:"


def cache_ttl() -> float:
    """Kesh TTL (soniya). ``AI_CACHE_TTL`` env (default 900s = 15 daqiqa)."""
    try:
        return max(0.0, float(os.getenv("AI_CACHE_TTL", "900")))
    except (TypeError, ValueError):
        return 900.0


def cache_max_entries() -> int:
    """Maksimal yozuvlar soni (LRU); 2-BOSQICH: 512MB limit uchun qat'iy chegara."""
    try:
        # 2-BOSQICH: LRU maxsize — Render 512MB limitini himoya qilish.
        # Xavfsiz default 512, hard cap 1024 (8MB bytes limiti bilan birga).
        return min(1024, max(1, int(os.getenv("AI_CACHE_MAX_ENTRIES", "512"))))
    except (TypeError, ValueError):
        return 512


def cache_max_bytes() -> int:
    """Keshning taxminiy xotira limiti (default 8 MiB, env bilan sozlanadi)."""
    try:
        value = int(os.getenv("AI_CACHE_MAX_BYTES", str(8 * 1024 * 1024)))
        return min(64 * 1024 * 1024, max(1024, value))
    except (TypeError, ValueError):
        return 8 * 1024 * 1024


def _value_size(value: Any) -> int:
    """Qiymatning taxminiy heap hajmi; nested javoblarni ham hisobga oladi."""
    seen: set[int] = set()

    def visit(item: Any) -> int:
        identity = id(item)
        if identity in seen:
            return 0
        seen.add(identity)
        size = sys.getsizeof(item)
        if isinstance(item, dict):
            size += sum(visit(k) + visit(v) for k, v in item.items())
        elif isinstance(item, (list, tuple, set, frozenset)):
            size += sum(visit(child) for child in item)
        return size

    return visit(value)


def canonical_prompt(text: str | None) -> str:
    """Kesh kaliti uchun matnni deterministik shaklga keltiradi.

    * Unicode NFC normalizatsiya (o'zbek harflari har xil kodlanishi);
    * barcha bo'shliq turlari → bitta prob (ko'rinadigan mazmun bir xil);
    * boshi/oxiridagi bo'shliqlar olib tashlanadi.
    """
    normalized = unicodedata.normalize("NFC", str(text or ""))
    return " ".join(normalized.split())


def cache_key(
    *,
    prompt: str,
    lane: str = "QUALITY",
    task: str = "",
    lang: str = "uz",
    tone: str = "",
    is_pro: bool = False,
    system_instruction: str = "",
    extra: str = "",
) -> str:
    """Deterministik kesh kaliti (sha256).

    Bir xil (lane, task, lang, tone, is_pro, system, prompt) → BITTA kalit.
    Provayder nomi ATAYLAB kiritilmagan: fallback boshqa provayderga
    o'tsa ham javob bir xil kalitga yoziladi.
    """
    payload = "|".join([
        str(lane or "").strip().upper(),
        canonical_prompt(task),
        canonical_prompt(lang).lower(),
        canonical_prompt(tone).lower(),
        "1" if is_pro else "0",
        canonical_prompt(system_instruction),
        canonical_prompt(prompt),
        canonical_prompt(extra),
    ])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}{digest}"


class AIResponseCache:
    """Kichik, thread-safe, TTL + LRU javob keshi."""

    def __init__(self, max_entries: int | None = None, ttl: float | None = None,
                 max_bytes: int | None = None):
        # 2-BOSQICH: qat'iy LRU chegara — cheksiz o'sish YO'Q (512MB himoyasi).
        self.max_entries = min(1024, max(1, int(max_entries or cache_max_entries())))
        self.ttl = min(86400.0, max(0.0, float(ttl if ttl is not None else cache_ttl())))
        self.max_bytes = min(64 * 1024 * 1024, max(1024, int(max_bytes or cache_max_bytes())))
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._entry_sizes: dict[str, int] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        # Telemetriya (kesh samaradorligini kuzatish uchun).
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    # --------------------------------------------------------------- API
    def get(self, key: str) -> Any | None:
        """Keshdan oladi (muddati o'tgan/yo'q → ``None``)."""
        with self._lock:
            now = time.time()
            for old_key, (expires, _) in list(self._entries.items()):
                if expires <= now:
                    self._entries.pop(old_key, None)
                    self._bytes -= self._entry_sizes.pop(old_key, 0)
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires, value = entry
            if expires <= time.time():
                self._entries.pop(key, None)
                self._bytes -= self._entry_sizes.pop(key, 0)
                self.misses += 1
                return None
            # LRU: yaqinda ishlatilganni oxiriga suramiz.
            self._entries.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Keshga yozadi; entry soni va umumiy xotira LRU bilan cheklanadi."""
        size = _value_size(value)
        with self._lock:
            now = time.time()
            # Muddati o'tgan entry'larni tozalash, keshni faol yozuvlar bilan to'ldirish.
            for old_key, (expires, _) in list(self._entries.items()):
                if expires <= now:
                    self._entries.pop(old_key, None)
                    self._bytes -= self._entry_sizes.pop(old_key, 0)
            if key in self._entries:
                self._entries.pop(key, None)
                self._bytes -= self._entry_sizes.pop(key, 0)
            if size > self.max_bytes:
                return  # juda katta javob keshga olinmaydi
            ttl_value = self.ttl if ttl is None else min(86400.0, max(0.0, float(ttl)))
            self._entries[key] = (now + ttl_value, value)
            self._entry_sizes[key] = size
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                oldest, _ = self._entries.popitem(last=False)
                self._bytes -= self._entry_sizes.pop(oldest, 0)
                self.evictions += 1

    def invalidate(self, key: str) -> None:
        """Bitta kalitni o'chiradi."""
        with self._lock:
            self._entries.pop(key, None)
            self._bytes -= self._entry_sizes.pop(key, 0)

    def clear(self) -> None:
        """Butun keshni tozalaydi (testlar/admin)."""
        with self._lock:
            self._entries.clear()
            self._entry_sizes.clear()
            self._bytes = 0
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    def stats(self) -> dict:
        """Kesh holati (diagnostika)."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "max_entries": self.max_entries,
                "max_bytes": self.max_bytes,
                "bytes": self._bytes,
                "ttl": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
                "evictions": self.evictions,
            }

    def __len__(self) -> int:  # pragma: no cover — qulaylik
        with self._lock:
            return len(self._entries)


# ---------------------------------------------------------------------------
# Yagona singleton (gateway ishlatadi; testlar reset qilishi mumkin).
# ---------------------------------------------------------------------------
_default_cache: AIResponseCache | None = None


def default_cache() -> AIResponseCache:
    """Global javob keshi (birinchi chaqiruvda quriladi)."""
    global _default_cache
    if _default_cache is None:
        _default_cache = AIResponseCache()
    return _default_cache


def reset_cache(max_entries: int | None = None, ttl: float | None = None) -> AIResponseCache:
    """Testlar uchun: keshni qayta quradi va yangisini qaytaradi."""
    global _default_cache
    _default_cache = AIResponseCache(max_entries=max_entries, ttl=ttl)
    return _default_cache


__all__ = [
    "AIResponseCache",
    "KEY_PREFIX",
    "cache_key",
    "cache_ttl",
    "cache_max_entries",
    "cache_max_bytes",
    "canonical_prompt",
    "default_cache",
    "reset_cache",
]
