"""📊 EVENT TRACKER — SPRINT 2 (VAZIFA 3): engil, asinxron foydalanuvchi
hodisalari analitikasi.

Maqsad — qaysi tugma/buyruqlar eng ko'p (va qaysilari eng kam, <5%)
ishlatilayotganini aniqlash, hech qanday og'ir infratuzilmasiz:

  * **Yengil** — jarayon xotirasida (process-local), bounded hajmda saqlanadi;
    yangi DB jadvali yoki migratsiya TALAB QILINMAYDI.
  * **Asinxron / bloklamaydigan** — ``track()`` chaqiruvi hech qachon
    ``await`` qilinishi shart emas (ichkarida ``asyncio.create_task`` bilan
    fire-and-forget qilinadi) va HECH QACHON istisno otmaydi — botning
    asosiy oqimiga ta'sir qilmaydi.
  * **(user_id, event_name, timestamp)** — har bir hodisa shu uchlik bilan
    yoziladi (``services.observability`` dagi mavjud bounded-counter
    uslubiga mos).

Integratsiya: ``handlers.guard_entry`` / ``handlers.guard_menu`` — botdagi
asosiy tugma/buyruq oqimlarining markaziy "darvozasi" — shu modulni
chaqiradi, shuning uchun YANGI import yoki ro'yxatga olish kodini HAR BIR
handler uchun qo'lda yozish shart emas (regressiya xavfi minimal).

Oddiy ichki agregatsiya — :func:`usage_report` — har bir hodisa nechta NOYOB
foydalanuvchi tomonidan bosilgani va shu son umumiy faol foydalanuvchilar
sonidan necha foizini tashkil etishini qaytaradi; ``underused=True`` —
``LOW_USAGE_THRESHOLD`` (standart 5%) dan past.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ============================================================
# SOZLAMALAR
# ============================================================
_MAX_EVENTS = 20_000          # process-local bounded buffer (eng so'nggi N hodisa)
_MAX_EVENT_NAMES = 500        # bitta hodisa nomi uchun noyob foydalanuvchilar keshi chegarasi
LOW_USAGE_THRESHOLD = 0.05    # 5% — shundan past bo'lsa "kam ishlatilyapti" deb belgilanadi

_LOCK = threading.RLock()


@dataclass
class _EventStat:
    """Bitta ``event_name`` uchun yengil, bounded agregatsiya."""

    count: int = 0
    users: "OrderedDict[int, None]" = field(default_factory=OrderedDict)
    last_seen: float = 0.0

    def add(self, user_id, now: float) -> None:
        self.count += 1
        self.last_seen = now
        if user_id is None:
            return
        # OrderedDict — LRU: eng so'nggi faol foydalanuvchi oxiriga suriladi,
        # xotira cheksiz o'smasligi uchun eskilari chiqarib tashlanadi.
        self.users.pop(user_id, None)
        self.users[user_id] = None
        while len(self.users) > _MAX_EVENT_NAMES:
            self.users.popitem(last=False)


# event_name -> _EventStat
_STATS: "OrderedDict[str, _EventStat]" = OrderedDict()
# Eng so'nggi xom hodisalar jurnali (user_id, event_name, timestamp) — debug/export uchun.
_RAW_LOG: "list[tuple[int, str, float]]" = []
_ALL_USERS_SEEN: "OrderedDict[int, None]" = OrderedDict()


def _now() -> float:
    return time.time()


def _record(user_id, event_name: str) -> None:
    """Sinxron yozuv — ichki, hech qachon tashqariga istisno otmaydi."""
    try:
        name = str(event_name or "unknown").strip() or "unknown"
        now = _now()
        with _LOCK:
            stat = _STATS.get(name)
            if stat is None:
                stat = _EventStat()
                _STATS[name] = stat
                while len(_STATS) > _MAX_EVENT_NAMES:
                    _STATS.popitem(last=False)
            stat.add(user_id, now)

            _RAW_LOG.append((user_id, name, now))
            while len(_RAW_LOG) > _MAX_EVENTS:
                _RAW_LOG.pop(0)

            if user_id is not None:
                _ALL_USERS_SEEN.pop(user_id, None)
                _ALL_USERS_SEEN[user_id] = None
                while len(_ALL_USERS_SEEN) > _MAX_EVENTS:
                    _ALL_USERS_SEEN.popitem(last=False)
    except Exception:
        # Analitika HECH QACHON asosiy botni buzmaydi.
        logger.debug("event_tracker: yozishda kutilmagan xato", exc_info=True)


def track(user_id, event_name: str) -> None:
    """Hodisani qayd etadi — bloklamaydi, hech qachon istisno otmaydi.

    Asinxron kontekstda bo'lsa fon vazifasi sifatida rejalashtiriladi
    (``asyncio.create_task``); event loop yo'q bo'lsa (masalan sinxron
    skript/test) to'g'ridan-to'g'ri sinxron yoziladi — ikkala holatda ham
    chaqiruvchini KUTIB TURMAYDI va xato bermaydi.
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    except Exception:
        loop = None

    if loop is not None:
        try:
            loop.create_task(_track_async(user_id, event_name))
            return
        except Exception:
            pass
    _record(user_id, event_name)


async def _track_async(user_id, event_name: str) -> None:
    _record(user_id, event_name)


def track_sync(user_id, event_name: str) -> None:
    """Majburiy sinxron yozuv (testlar / sinxron chaqiruvchilar uchun)."""
    _record(user_id, event_name)


def event_name_for(fn) -> str:
    """Handler funksiyasidan o'qiladigan hodisa nomi hosil qiladi."""
    name = getattr(fn, "__name__", None) or getattr(fn, "__qualname__", None) or repr(fn)
    return str(name)


def reset() -> None:
    """Faqat testlar uchun — jarayon xotirasidagi barcha statistikani tozalaydi."""
    with _LOCK:
        _STATS.clear()
        _RAW_LOG.clear()
        _ALL_USERS_SEEN.clear()


def raw_events(limit: int = 100) -> list:
    with _LOCK:
        return list(_RAW_LOG[-limit:])


def event_counts() -> dict:
    """``{event_name: {"count": int, "unique_users": int, "last_seen": float}}``."""
    with _LOCK:
        return {
            name: {
                "count": stat.count,
                "unique_users": len(stat.users),
                "last_seen": stat.last_seen,
            }
            for name, stat in _STATS.items()
        }


def total_tracked_users() -> int:
    with _LOCK:
        return len(_ALL_USERS_SEEN)


def usage_report(total_users: int = None, threshold: float = LOW_USAGE_THRESHOLD) -> dict:
    """Oddiy ichki agregatsiya hisobot.

    Args:
        total_users: foizni hisoblash uchun mahraj (odatda botdagi umumiy
            faol foydalanuvchilar soni, ``db.count_users()`` dan). Berilmasa
            — shu jarayon davomida ko'rilgan NOYOB foydalanuvchilar soni
            ishlatiladi (fallback, kam aniq lekin hech qachon ZeroDivision
            bermaydi).
        threshold: "kam ishlatilmoqda" chegarasi (standart 5%).

    Returns:
        ``{"generated_at": iso-str, "total_users": int,
           "events": [{"event_name", "count", "unique_users",
                        "adoption_rate", "underused"}, ...]  # count bo'yicha kamayish tartibida
           "most_used": [...top 5...], "least_used": [...underused bo'lganlar...]}``
    """
    with _LOCK:
        base_total = total_users if total_users and total_users > 0 else max(1, len(_ALL_USERS_SEEN))
        rows = []
        for name, stat in _STATS.items():
            adoption = len(stat.users) / base_total if base_total else 0.0
            rows.append({
                "event_name": name,
                "count": stat.count,
                "unique_users": len(stat.users),
                "adoption_rate": round(adoption, 4),
                "underused": adoption < threshold,
            })
    rows.sort(key=lambda r: r["count"], reverse=True)
    underused = [r for r in rows if r["underused"]]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_users": base_total,
        "events": rows,
        "most_used": rows[:5],
        "least_used": underused,
    }


__all__ = [
    "LOW_USAGE_THRESHOLD",
    "track",
    "track_sync",
    "event_name_for",
    "reset",
    "raw_events",
    "event_counts",
    "total_tracked_users",
    "usage_report",
]
