# -*- coding: utf-8 -*-
"""
=====================================================================
 🔌 RUNTIME — repository qatlamining kech bog'langan yadro ko'prigi
=====================================================================

Repository modullari yadroga (``database``) to'g'ridan-to'g'ri bog'lanmaydi.
Bu moduli shu maqsadda:

* **Mock qobiliyati saqlanadi.** Ishlab chiqarish va test kodida
  ``database.db_cursor`` ``unittest.mock.patch`` bilan almashtiriladi
  (``telegram_bot/tests/scheduler_service_test.py`` shuni qiladi). Agar
  repository ``from database import db_cursor`` desa, u ORIGINAL
  funksiyaga bog'lanib qolardi va patch kuchsizlanardi. Bu modul esa har
  chaqiruvda ``database`` modulining **joriy** atributiga qarab yuradi —
  patch ham, monkeypatch ham, istalgan import tartibi ham saqlanadi.

* **Import sikli yo'q.** ``database`` repository paketini faqat faylning
  **oxirida** import qiladi. ``repositories/__init__.py`` esa avval
  ``database`` ni import qilib yadroni to'liq yuklaydi — shuning uchun
  ``import database`` va ``import repositories.x_repository``
  tartiblarining IKKALASI ham xavfsiz.

Barcha proksilar ``*args, **kwargs`` ni o'zgartirmaydi — imzo va
default'lar yagona manba (``database``) da qoladi.
"""
#: Kech bog'lanadigan yadro / boshqa repository nomlari.
LATE_BOUND = (
    "_cache_clear",
    "_cache_get",
    "_cache_set",
    "_invalidate_rbac_resource_cache",
    "_invalidate_user",
    "_normalize_language_code",
    "_profile_clear_all",
    "_profile_invalidate",
    "db_cursor",
    "db_transaction",
    "get_channel_owner_id",
    "get_setting",
    "get_user_profile",
    "peek_user_profile",
    "set_setting",
)


def _late(name):
    """``database.<name>`` ni chaqiruv paytida qaytaruvchi proksi."""

    def _proxy(*args, **kwargs):
        import database
        return getattr(database, name)(*args, **kwargs)

    _proxy.__name__ = name
    _proxy.__qualname__ = name
    _proxy.__doc__ = "``database." + name + "`` ga kech (late) bog'langan proksi."
    _proxy.__module__ = __name__
    return _proxy


globals().update({n: _late(n) for n in LATE_BOUND})