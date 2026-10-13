#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💲 AI MODEL NARXINI ANIQLASH — provayder va model birgalikda tekshiriladi.

Muammo: ``price_for`` / ``price_spec`` ``"{provider} {model}"`` satridan eng
UZUN kalitni qidirardi. Groq narxi bilan yozilgan ``llama-3.3-70b`` kaliti
Cerebras/SambaNova/Cloudflare/OpenRouter'dagi shu nomli modelga ham
qo'llanardi (boshqa provayderning narxi).

Tuzatish: Groq narxi bilan yozilgan kalitlar ``providers=("groq",)`` bilan
chegaralangan; boshqa provayderdagi mos model narxi NOMA'LUM
(``priced=False``) bo'ladi — soxta narx ham, "bepul" ham emas.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/ai_price_lookup_test.py
"""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:PRICE_LOOKUP_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


from services.ai import cost_tracker as ct  # noqa: E402
from services.ai.engine import gateway as gw  # noqa: E402
from services.ai.engine import telemetry as tel  # noqa: E402

GROQ_L33 = (0.00059, 0.00079)


def ct_price(provider, model):
    p = ct.price_for(provider, model)
    return None if p is None else (p.input_per_1k, p.output_per_1k)


def tel_price(provider, model):
    if not tel.is_priced(provider, model):
        return None
    s = tel.price_spec(provider, model)
    return (s.input_per_1k, s.output_per_1k)


def both(provider, model):
    a, b = ct_price(provider, model), tel_price(provider, model)
    return a if a == b else ("MISMATCH", a, b)


print("\n== 1) Bir xil nomli model, ikki xil provayder ==")
check("Groq llama-3.3-70b-versatile → Groq narxi", both("Groq", "llama-3.3-70b-versatile") == GROQ_L33,
      str(both("Groq", "llama-3.3-70b-versatile")))
for prov, model in (("Cerebras", "llama-3.3-70b"),
                    ("SambaNova", "Meta-Llama-3.3-70B-Instruct"),
                    ("Cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
                    ("OpenRouter", "meta-llama/llama-3.3-70b-instruct")):
    got = both(prov, model)
    check(f"{prov} {model}: Groq narxi QO'LLANMAYDI", got != GROQ_L33, str(got))
    check(f"{prov} {model}: narxi noma'lum (priced=False), 'bepul' emas", got is None, str(got))
check("Mixtral faqat Groq narxida; boshqa provayderda noma'lum",
      both("Groq", "mixtral-8x7b-32768") == (0.00024, 0.00024)
      and both("Cerebras", "mixtral-8x7b") is None)

print("\n== 2) Provayder nomi katta-kichik harfda ==")
for spelling in ("Groq", "GROQ", "groq", "  Groq  "):
    check(f"provayder {spelling!r} → Groq narxi",
          both(spelling, "llama-3.3-70b-versatile") == GROQ_L33, str(both(spelling, "llama-3.3-70b-versatile")))
for spelling in ("Cerebras", "CEREBRAS", "cerebras"):
    check(f"provayder {spelling!r} → Groq narxi qo'llanmaydi",
          both(spelling, "llama-3.3-70b") is None, str(both(spelling, "llama-3.3-70b")))

print("\n== 3) Aniq model ID va aliaslar ==")
check("Groq llama-3.1-8b-instant → llama-3.1-8b narxi",
      both("Groq", "llama-3.1-8b-instant") == (0.00005, 0.00008))
check("Gemini gemini-flash-latest (alias) → Gemini oilasi narxi",
      both("Gemini", "gemini-flash-latest") == (0.0003, 0.0025))
check("Gemini gemini-2.5-pro → o'z narxi", both("Gemini", "gemini-2.5-pro") == (0.00125, 0.01))
check("Groq llama3-70b-8192 → Llama oilasi (o'zgarmagan)",
      both("Groq", "llama3-70b-8192") == (0.0002, 0.0003))

print("\n== 4) Narxi mavjud model (regressiya: avvalgi natijalar) ==")
for prov, model, expect in (
        ("Gemini", "gemini-2.5-flash", (0.0003, 0.0025)),
        ("Mistral", "mistral-small-latest", (0.0002, 0.0006)),
        ("OpenRouter", "openrouter/free", (0.0005, 0.0015)),
        ("Cerebras", "llama3.1-8b", (0.0, 0.0)),        # provayder darajasidagi e'lon
        ("Cloudflare", "workers-ai-8b", (0.0, 0.0)),
        ("SambaNova", "Qwen3-32B", (0.0, 0.0)),
        ("Pollinations", "", (0.0, 0.0)),
        ("Groq", "gemma2-9b-it", (0.0002, 0.0003)),
):
    check(f"{prov} {model or '—'} → {expect}", both(prov, model) == expect, str(both(prov, model)))
check("provayder ko'rsatilmasa (None) model kaliti avvalgidek ishlaydi",
      both(None, "llama-3.3-70b") == GROQ_L33 and both("", "gemini-2.5-flash") == (0.0003, 0.0025))

print("\n== 5) Narxi noma'lum model ==")
check("Mystery zeta-9000 noma'lum", both("Mystery", "zeta-9000") is None)
check("noma'lum model: cost_usd = 0.0 va is_priced = False",
      ct.cost_usd("Mystery", "zeta-9000", 1000, 1000) == 0.0 and not ct.is_priced("Mystery", "zeta-9000"))
check("Cerebras llama-3.3-70b: estimate_cost = 0.0 (to'qilgan narx yo'q)",
      tel.estimate_cost("Cerebras", "llama-3.3-70b", 1000, 1000) == 0.0)
event = tel.build_usage_event(
    result=gw.GatewayResult(ok=True, text="javob " * 50, provider="Cerebras",
                            model="llama-3.3-70b", task="social_post"),
    prompt="p" * 400, user_id=1, channel_id=-100)
check("telemetriya hodisasi: Cerebras llama-3.3-70b → unpriced (priced=False, $0 emas-belgi bilan)",
      event.cost_status == tel.COST_UNPRICED and event.priced is False and event.as_dict()["unpriced"] is True,
      f"{event.cost_status} {event.priced}")
book = ct.CostLedger()
entry = book.record(user_id=5, provider="Cerebras", model="llama-3.3-70b",
                    input_tokens=500, output_tokens=500)
check("ledger: Cerebras llama-3.3-70b → unpriced", entry.get("cost_status") == "unpriced",
      str(entry.get("cost_status")))
entry = book.record(user_id=5, provider="Groq", model="llama-3.3-70b-versatile",
                    input_tokens=1000, output_tokens=1000)
check("ledger: Groq llama-3.3-70b-versatile → priced, xarajat > 0",
      entry.get("cost_status") == "priced" and entry.get("cost_usd", 0) > 0, str(entry))

print("\n== 6) _PRICE_OVERRIDES asosiy jadvaldan ustun ==")
tel.clear_price_overrides()
try:
    tel.set_price_override("llama-3.3-70b", tel.PriceSpec(1.0, 2.0, "test override"))
    check("override Groq narxini almashtiradi", tel_price("Groq", "llama-3.3-70b-versatile") == (1.0, 2.0),
          str(tel_price("Groq", "llama-3.3-70b-versatile")))
    check("override aniq belgilangan model uchun boshqa provayderda ham ishlaydi (ataylab, ochiq qaror)",
          tel_price("Cerebras", "llama-3.3-70b") == (1.0, 2.0), str(tel_price("Cerebras", "llama-3.3-70b")))
    check("override cost_tracker jadvaliga ta'sir qilmaydi", ct_price("Groq", "llama-3.3-70b-versatile") == GROQ_L33)
finally:
    tel.clear_price_overrides()
check("override olib tashlangach asosiy jadval qaytadi",
      tel_price("Groq", "llama-3.3-70b-versatile") == GROQ_L33 and tel_price("Cerebras", "llama-3.3-70b") is None)

print("\n== 7) Jadval tuzilishi ==")
check("PRICE_TABLE kalitlari = MODEL_PRICES kalitlari",
      list(tel.PRICE_TABLE.keys()) == list(ct.MODEL_PRICES.keys()))
check("PRICE_TABLE narxlari va provayder chegaralari MODEL_PRICES bilan bir xil",
      all((tel.PRICE_TABLE[k].input_per_1k, tel.PRICE_TABLE[k].output_per_1k,
           getattr(tel.PRICE_TABLE[k], "providers", None))
          == (v.input_per_1k, v.output_per_1k, getattr(v, "providers", None))
          for k, v in ct.MODEL_PRICES.items()))
check("Groq narxi bilan yozilgan kalitlar Groq'ga chegaralangan",
      all(getattr(ct.MODEL_PRICES[k], "providers", None) == ("groq",)
          for k in ("llama-3.3-70b", "llama-3.1-8b", "mixtral", "groq")))

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
