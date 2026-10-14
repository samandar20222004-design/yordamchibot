"""PostAssist Mini App — HTTP API qatlami (faqat o'qish, 1-versiya).

Bu paket bot handlerlariga (``Update``/``context``) BOG'LIQ EMAS: faqat
``database`` tranzaksiya yordamchilari, ``services.beta_gate`` holat
formati, ``services.cache_backend`` va ``config`` ishlatiladi. Shuning uchun
kelajakda alohida servisga ajratish mumkin.

Ulash nuqtasi: :func:`miniapp_api.app.register_miniapp_routes`. Sukut bo'yicha
``MINIAPP_ENABLED=0`` — hech qanday marshrut ulanmaydi.
"""
