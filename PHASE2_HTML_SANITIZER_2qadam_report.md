# PHASE 2 · 2-QADAM — Telegram HTML Sanitizer va post xavfsizligi

**Sana:** 2026-09-15  
**Repo:** `samandar20222004-design/yordamchibot`  
**Branch:** `main`  
**Baseline:** `52e9204`  
**Kod va testlar:** bajarildi — **EXIT=0, 0 `[FAIL]`**.  
**Remote push:** autentifikatsiya yo‘qligi sababli bloklangan. O‘zgarishlar lokal commit’da saqlangan; GitHub `main` yangilangani haqida da’vo qilinmaydi.

## 1. Yagona SSOT

Yangi modul: `telegram_bot/utils/telegram_sanitizer.py`.

- Oq ro‘yxat: `b`, `strong`, `i`, `em`, `u`, `ins`, `s`, `strike`, `del`, faqat `class="tg-spoiler"` bilan `span`, `tg-spoiler`, `a`, `code`, `pre`, `blockquote`.
- Noma’lum va buzilgan teglar literal matn sifatida escape qilinadi. Masalan, `<script>x</script>` → `&lt;script&gt;x&lt;/script&gt;`.
- Yopilmagan teglar avtomatik yopiladi; kesishgan teglar stack yordamida muvozanatlashtiriladi.
- Atributlar oq ro‘yxat bilan cheklanadi: xavfsiz `href`, spoiler klassi, `pre > code` uchun `language-*`, `blockquote expandable`. Event/style atributlari chiqarib tashlanadi.
- Havolalar mavjud `security.validate_button_url` siyosatidan o‘tadi; `javascript:`, `data:`, `file:` va yaroqsiz URL’lar teg bo‘lib chiqmaydi.
- Xom `&`, `<`, `>` escape qilinadi. Mavjud entity’lar qayta-qayta escape bo‘lib buzilmaydi: sanitizer idempotent.
- Noto‘g‘ri `code/pre`, ichma-ich havola yoki quote formatlari matnni saqlagan holda soddalashtiriladi.
- Limitlar HTML sintaksisi uzunligiga emas, **entity’lar ochilgandan keyingi UTF-16 birliklariga** qo‘llanadi: xabar **4096**, caption **1024**. Astral emoji ikki birlik hisoblanadi — konservativ xavfsiz chegara.
- Qisqartirish teg, Unicode code point yoki entity o‘rtasidan kesmaydi; ochiq teglar oxirida yopiladi.
- NUL/control belgilar va yolg‘iz surrogatlar almashtiriladi; chuqur markup uchun stack chegarasi bor.

Misollar:

```python
sanitize_html("<b>Salom")
# <b>Salom</b>

sanitize_html("5 < 10 & price > 100")
# 5 &lt; 10 &amp; price &gt; 100

sanitize_html("<b>" + "&amp;" * 2000, 1024)
# <b> + 1024 ta butun &amp; entity + </b>
```

## 2. Backward compatibility

Tarixiy funksiyalarning ikki xil kontrakti ataylab saqlandi:

| Eski kirish nuqtasi | Yangi markazdagi vazifa |
|---|---|
| `utils.helpers.safe_html` | Formatni saqlovchi `sanitize_html`; fragment uchun default limitsiz |
| `utils.helpers.html_escape` | Literal qiymatni `escape_html` orqali escape qilish; eski falsey xatti-harakati saqlangan |
| `utils.security.safe_html`, `escape_html`, `html_escape` | **Barcha** teglarni escape qilish — user/kanal ismi HTML’ga aylanmaydi |
| `utils.security.safe_text`, `safe_limit_html` | Eski serialized-length budjeti saqlanadi, lekin entity bo‘linmaydi; sig‘magan entity o‘rniga qolgan joy nuqtalar bilan to‘ldiriladi |
| `utils.helpers.telegram_html_payload` | SSOT proxy; oddiy matn uchun `parse_mode=None` saqlanadi, ixtiyoriy limit qo‘shildi |
| `utils.ai_agent.sanitize_magic_post_html` | To‘g‘ridan-to‘g‘ri SSOT proxy; eski alohida fallback sanitizer olib tashlandi |

Reklama validatori ham teglar oq ro‘yxatini SSOT’dan oladi. `scheduler.sanitize_channel_content` esa HTML sanitizer emas: ichki preview/xizmat qatorlarini tozalash vazifasi saqlanadi, undan keyingi HTML tayyorlash SSOT orqali bajariladi.

## 3. Barcha HTML chiqishlari uchun yakuniy himoya

Yangi modul: `telegram_bot/utils/telegram_delivery.py`.

`SafeHTMLBot(ExtBot)` PTB `Defaults` va `api_kwargs` qiymatlari aniqlangandan **keyin**, rate limiter va HTTP yuborishdan **oldin** payload’ni SSOT’dan o‘tkazadi.

`main.py` ilovani `.bot(create_safe_bot(BOT_TOKEN))` orqali quradi. Handlerlar va Scheduler aynan shu botdan foydalanadi. Shu sababli himoya faqat bir nechta qo‘lda o‘zgartirilgan joy bilan cheklanmaydi. Statik audit ilova kodida **29 faylda 499 ta literal `parse_mode="HTML"` keyword** topdi; dinamik HTML parse_mode’lar ham yakuniy boundary’da tekshiriladi.

Qamrov:

- HTML `sendMessage`, matn va caption tahrirlash;
- foto, video, animation, document, audio, voice caption’lari;
- albomdagi `InputMedia` caption’lari va media tahrirlash;
- yangi caption berilgan `copyMessage`;
- inline natijalardagi `input_message_content`;
- fayl yuklash obyektlari va qayta ishlatiladigan media nusxalari buzilmaydi;
- `parse_mode=None`, Markdown va faqat explicit entity’li so‘rovlar qayta yozilmaydi;
- HTML tanlanganda eskirgan explicit entity offset’lari tashlanadi, Telegram yangi HTML’dan hisoblaydi.

Mavjud timeout/pool sozlamalari saqlangan. Yangi global monkey-patch va transport darajasida avtomatik qayta yuborish qo‘shilmadi.

## 4. Oqimlar bo‘yicha tuzatishlar

- **Magic Post:** `payload[:4000]` olib tashlandi; natija preview’i HTML-aware qisqartiriladi. Plain fallback haqiqiy ko‘rinadigan matn yuboradi, escape kodlarini emas. Fallback faqat aniq entity-parsing `BadRequest` uchun; timeout’dan keyin ko‘r-ko‘rona ikkinchi yuborish yo‘q.
- **Fotopost:** preview va kanalga yuborishda caption uchun SSOT 1024 limiti; escaped HTML’ni xom slice qilish olib tashlandi.
- **Scheduler:** `compose_post_text` reklama/nishon uchun format-aware joy ajratadi; brand alohida muvozanatlashtiriladi. Albom va final payload caption/xabar limitini aniq oladi. Haddan tashqari uzun brand holati ham tekshirildi.
- **AI Studio:** media preview va matn preview’i, post/audit fragmentlari avval to‘liq parse qilinib, keyin xavfsiz qisqartiriladi.

## 5. Muhit va test dalillari

Repo ildizida `requirements.txt` yo‘q; haqiqiy fayl `telegram_bot/requirements.txt`.

Boshlang‘ich Python 3.13’da pin qilingan `psycopg2-binary==2.9.9` build’i muvaffaqiyatsiz bo‘ldi. Dependency pin’lari o‘zgartirilmadi; Dockerfile’dagi Python 3.11 bilan mos **Python 3.11.16** muhit yaratilib, paketlar o‘rnatildi.

Asosiy tekshiruv:

```bash
PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
```

| Tekshiruv | Natija |
|---|---|
| Baseline — o‘zgartirishlardan oldin | EXIT=0, 0 `[FAIL]` |
| Yangi `tests/html_sanitizer_test.py`, PTB 22.8 | 34 test, 0 error/failure, 0 skipped |
| Yangi suite, minimal qo‘llab-quvvatlangan PTB 21.11.1 | 34 test, 0 error/failure, 0 skipped |
| Yakuniy root runner, yangi suite bilan | **EXIT=0, 0 `[FAIL]`** |
| `git diff --check` | Xatosiz |

Yangi suite root `tests/run_tests.sh` ichiga ulandi. Mavjud test fayllari/assertion’lari yumshatilmadi yoki o‘chirilmadi.

Yangi testlar:

- yopilmagan, kesishgan, noma’lum teglar va buzilgan tokenlar;
- whitelist, atribut/havola xavfsizligi, entity normalizatsiyasi;
- 0/1/2/5/1024/4096 chegaralari, UTF-16 emoji, control belgilar;
- SSOT’dan mustaqil qat’iy entity parsing simulyatori: balans, atributlar, nesting, limitlar;
- idempotentlik va **600 ta deterministik tasodifiy token kombinatsiyasi**;
- 10 000 ta ichma-ich boshlang‘ich tegli kirish;
- haqiqiy PTB metodlari → fake HTTP transport: defaults, api_kwargs, media upload, albums, edits, inline;
- Magic/Fotopost/AI Studio helper’lari, Scheduler kompozitsiyasi va brand chegaralari;
- timeout’dan keyin dublikat yuborilmasligi.

Yakuniy log oxiri:

```text
BARCHA TESTLAR MUVOFFAQIYATLI ✔
==============================================================
BARCHA TESTLAR 100% YASHIL ✔
EXIT=0
```

Workspace dalil fayllari: `baseline_tests.log`, `final_tests.log`, `html_sanitizer_tests.log`, `ptb21_tests.log`. Muhit/kesh/log fayllari source commit’ga qo‘shilmaydi.

**Chegara:** bu offline va mock asosidagi tekshiruv. Live Telegram yuborishi va live PostgreSQL tekshiruvi uchun credential taqdim etilmagan. Matn formati/uzunligi himoyasi tarmoq, kanal ruxsati, bo‘sh xabar yoki Telegram xizmatining mavjudligi bo‘yicha kafolat emas.

## 6. GitHub push holati

GitHub yozish autentifikatsiyasi muhitda mavjud emas. Push ruxsatini tekshirish:

```bash
GIT_TERMINAL_PROMPT=0 git push --dry-run origin main
GIT_TERMINAL_PROMPT=0 git push origin main
```

```text
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```

GitHub’ga yozish huquqi xavfsiz tarzda muhitga ulangach, tayyor lokal commit uchun:

```bash
git push origin main
```

Token/parolni chatga yoki repozitoriy fayliga yozish kerak emas. Remote o‘zgarmagan bo‘lsa oddiy push yetarli; branch oldinga siljigan bo‘lsa avval yangilanishlar olinib, testlar takrorlanishi kerak. Force push ishlatilmaydi.
