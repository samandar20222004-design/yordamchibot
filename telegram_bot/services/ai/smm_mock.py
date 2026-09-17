"""Deterministik SMM javoblar banki (MockProvider + offline fallback).

PHASE 11 & 12 uchun yagona «so'zsiz javob» manbasi. Ikki iste'molchi bor:

1. :class:`services.ai.providers.MockProvider` — API kalitsiz muhit (CI,
   sandbox, lokal test) uchun realga o'xshash, lekin **to'liq deterministik**
   javob. Har bir xizmat o'z rejimini ``context["smm_mode"]`` orqali
   bildiradi, MockProvider shu rejimga mos matn/JSON qaytaradi.
2. Advanced SMM xizmatlarining o'zi — provayder butunlay javob
   bermaganda (barcha zaxira tugadi, javob buzuq) shu bankdagi
   **angle bo'yicha farq qiluvchi** shablonlar ishlatiladi. Shu tufayli
   5 variant hech qachon bir-birining sinonimi bo'lib qolmaydi.

Matnlar Telegram HTML (<b>, <i>) formatida, UZ/RU/EN uchun alohida —
``AIOutputValidator`` til tekshiruvini (kirill ulushi) muvaffaqiyatli o'tishi
uchun tillar haqiqiy tilida yozilgan.
"""

from __future__ import annotations

import json
from typing import Any

#: MockProvider tanib oladigan rejimler.
SMM_MODE_VARIANTS = "VARIANTS"
SMM_MODE_REPURPOSE = "REPURPOSE"
SMM_MODE_AUDIT = "AUDIT"
SMM_MODE_PLANNER = "PLANNER"
# 📥 PHASE D — kontent manbalari (11, 12, 13-bandlar).
SMM_MODE_URL_POST = "URL_POST"
SMM_MODE_RSS = "RSS_DIGEST"
SMM_MODE_RECYCLE = "RECYCLE"
SMM_MODES = (SMM_MODE_VARIANTS, SMM_MODE_REPURPOSE, SMM_MODE_AUDIT,
             SMM_MODE_PLANNER, SMM_MODE_URL_POST, SMM_MODE_RSS,
             SMM_MODE_RECYCLE)

_LANGS = ("uz", "ru", "en")


# ---------------------------------------------------------------------------
# 1) MULTI-VARIANT (48-band) — har bir uslub ALOHIDA BURG'UCH (angle)
# ---------------------------------------------------------------------------
#: style → lang → shablon. ``{topic}`` — foydalanuvchi mavzusi (escape qilingan).
VARIANT_BANK: dict[str, dict[str, str]] = {
    "viral": {
        "uz": (
            "🔥 <b>{topic}: buni hech kim ochiq aytmaydi</b>\n\n"
            "Savol bitta: nega odamlar bunga hali ham ishonmaydi? Javob — "
            "natijani emas, jarayonni ko'rishgani uchun.\n\n"
            "⚡️ Kuniga atigi 10 daqiqa — oy oxirida farqni o'lchaysiz.\n"
            "💣 Eng qizig'i: buni bugun BEPUL sinab ko'rish mumkin.\n\n"
            "💬 Sizning fikringiz? Izohda bahslashamiz — eng kuchli javobni "
            "keyingi postga olamiz.\n"
            "🚀 Do'stingizga ulashing, u ham buni bilishi kerak.\n\n"
            "#viral #tezkor #munozara"
        ),
        "ru": (
            "🔥 <b>{topic}: об этом молчат</b>\n\n"
            "Вопрос один: почему в это до сих пор не верят? Ответ простой — "
            "смотрят на процесс, а не на результат.\n\n"
            "⚡️ Всего 10 минут в день — разница измерима через месяц.\n"
            "💣 Самое интересное: сегодня можно попробовать бесплатно.\n\n"
            "💬 А что думаете вы? Спорим в комментариях — лучший ответ попадёт "
            "в следующий пост.\n"
            "🚀 Перешлите другу, ему это тоже нужно.\n\n"
            "#вирусно #быстро #спор"
        ),
        "en": (
            "🔥 <b>{topic}: nobody says this out loud</b>\n\n"
            "One question: why do people still doubt it? Because they watch the "
            "process instead of the result.\n\n"
            "⚡️ Ten minutes a day — measurable difference in a month.\n"
            "💣 Best part: you can try it for free today.\n\n"
            "💬 What is your take? Argue in the comments — the sharpest answer "
            "gets featured next post.\n"
            "🚀 Share it with a friend who needs this.\n\n"
            "#viral #quickwin #debate"
        ),
    },
    "premium": {
        "uz": (
            "💎 <b>{topic} — tanlov saviyasi</b>\n\n"
            "Barqarorlik shov-shinsiz quriladi. Biz uchun muhim bo'lgan — "
            "vaqt, aniqlik va detallarga bo'lgan hurmat.\n\n"
            "Har bir bosqich oldindan o'ylangan: bir marta kelishiladi, so'ngra "
            "o'zgarishlar ro'yxati kengaytirilmaydi.\n\n"
            "🤍 Sizga mos taklifni tayyorlab berishimizni istasangiz — yozing.\n\n"
            "#premium #sifat #tanlov"
        ),
        "ru": (
            "💎 <b>{topic} — уровень выбора</b>\n\n"
            "Стабильность строится без шума. Для нас важны время, точность и "
            "уважение к деталям.\n\n"
            "Каждый этап продуман заранее: условия фиксируются один раз и не "
            "расширяются на ходу.\n\n"
            "🤍 Напишите нам, чтобы получить предложение под ваш запрос.\n\n"
            "#премиум #качество #выбор"
        ),
        "en": (
            "💎 <b>{topic} — a matter of standards</b>\n\n"
            "Consistency is built quietly. What matters to us is time, accuracy "
            "and respect for detail.\n\n"
            "Every stage is agreed in advance: terms are fixed once and never "
            "expanded mid-process.\n\n"
            "🤍 Message us to receive a proposal shaped around your request.\n\n"
            "#premium #quality #standard"
        ),
    },
    "sales": {
        "uz": (
            "💰 <b>{topic}: muammo — vaqt, yechim — bizning taklif</b>\n\n"
            "Har oy [summa] va bir hafta sarflangan vaqt yo'qoladi, natija esa "
            "o'rnida turadi. Bu — eng qimmat xato.\n\n"
            "✅ Taklif: bir oyda birinchi real natija;\n"
            "✅ Kafolat: natija bo'lmasa — qaytamiz;\n"
            "🎁 Maxsus narx: <b>[narx]</b> — faqat [sana] gacha.\n\n"
            "🛒 <b>Hoziroq buyurtma bering</b> — joylar soni cheklangan.\n\n"
            "#aksiya #chegirma #buyurtma"
        ),
        "ru": (
            "💰 <b>{topic}: проблема — время, решение — наше предложение</b>\n\n"
            "Каждый месяц уходит [сумма] и неделя потерянного времени, а результат "
            "остаётся на нуле. Это самая дорогая ошибка.\n\n"
            "✅ Предложение: первый реальный результат за месяц;\n"
            "✅ Гарантия: если результата нет — возвращаем;\n"
            "🎁 Специальная цена: <b>[цена]</b> — только до [дата].\n\n"
            "🛒 <b>Закажите сейчас</b> — количество мест ограничено.\n\n"
            "#акция #скидка #заказ"
        ),
        "en": (
            "💰 <b>{topic}: the problem is time, the offer is ours</b>\n\n"
            "Every month costs you [amount] and a week of lost time while the "
            "result stays flat. That is the most expensive mistake there is.\n\n"
            "✅ Offer: first measurable result within a month;\n"
            "✅ Guarantee: no result, no fee;\n"
            "🎁 Special price: <b>[price]</b> — until [date] only.\n\n"
            "🛒 <b>Order now</b> — places are limited.\n\n"
            "#offer #discount #order"
        ),
    },
    "informative": {
        "uz": (
            "📚 <b>{topic}: 3 ta fakt va bitta xulosa</b>\n\n"
            "1. <b>Tajriba</b> — natija tizimli qaytarilganda o'sadi, "
            "bir martalik urinishda emas.\n"
            "2. <b>O'lchov</b> — raqamsiz yaxshilanish yo'q; haftada bitta "
            "ko'rsatkichni kuzatish kifoya.\n"
            "3. <b>Xato</b> — eng katta yo'qotish noto'g'ri prioritet, "
            "resurs tanqisligi emas.\n\n"
            "🧠 Ekspert xulosasi: rejangizni bitta metrikaga bog'lang — qolgan "
            "qatorlar o'zi tartibga tushadi.\n\n"
            "👉 Foydali bo'ldimi? Saqlab oling va do'stingizga ham yuboring.\n\n"
            "#fakt #tahlil #maslahat"
        ),
        "ru": (
            "📚 <b>{topic}: три факта и один вывод</b>\n\n"
            "1. <b>Системность</b> — результат растёт от повторяемых действий, "
            "а не от одного рывка.\n"
            "2. <b>Измерение</b> — без цифр улучшения нет; достаточно следить "
            "за одной метрикой в неделю.\n"
            "3. <b>Ошибка</b> — самый большой убыток это неверный приоритет, а "
            "не отсутствие ресурсов.\n\n"
            "🧠 Вывод эксперта: привяжите план к одной метрике — остальное "
            "выстроится само.\n\n"
            "👉 Полезно? Сохраните и отправьте другу.\n\n"
            "#факты #анализ #совет"
        ),
        "en": (
            "📚 <b>{topic}: three facts and one conclusion</b>\n\n"
            "1. <b>System</b> — results compound from repeated actions, not "
            "from a single sprint.\n"
            "2. <b>Measurement</b> — without numbers there is no improvement; "
            "one metric a week is enough.\n"
            "3. <b>Risk</b> — the biggest loss is a wrong priority, not a "
            "missing resource.\n\n"
            "🧠 Expert take: tie the plan to one metric — the rest falls into "
            "place.\n\n"
            "👉 Useful? Save it and send it to a colleague.\n\n"
            "#facts #analysis #advice"
        ),
    },
    "blogger": {
        "uz": (
            "🤳 <b>{topic} — chinakam tajribam</b>\n\n"
            "Boshida men ham «menga kerakmas» deb o'ylagandim. Bir oy o'tib "
            "eng ko'p ishlatadigan narsamga aylandi.\n\n"
            "Eng foydali lahza — ertalabki 15 daqiqa; eng qiyini — "
            "birinchi kuni o'zingni majburlash.\n\n"
            "Siz ham shu bosqichdamisiz? Yozing, birga tahlil qilamiz 🤍\n\n"
            "#kundalik #tajriba #samimiy"
        ),
        "ru": (
            "🤳 <b>{topic} — мой честный опыт</b>\n\n"
            "Сначала я думал: «мне это не нужно». Через месяц это стало тем, "
            "чем я пользуюсь чаще всего.\n\n"
            "Самое полезное — первые 15 минут утром; самое сложное — заставить "
            "себя в первый день.\n\n"
            "Вы на этом же этапе? Напишите, разберём вместе 🤍\n\n"
            "#дневник #опыт #честно"
        ),
        "en": (
            "🤳 <b>{topic} — my honest experience</b>\n\n"
            "At first I thought: “not for me.” A month later it became the "
            "thing I use most.\n\n"
            "Most useful: the first 15 minutes in the morning. Hardest: showing "
            "up on day one.\n\n"
            "Are you at that stage right now? Write to me — we'll figure it "
            "out 🤍\n\n"
            "#diary #experience #honest"
        ),
    },
}


# ---------------------------------------------------------------------------
# 2) REPURPOSE (49-band) — platforma matnining «xom» qismi
# ---------------------------------------------------------------------------
PLATFORM_BANK: dict[str, dict[str, str]] = {
    "telegram": {
        "uz": ("Bu yo'nalishda har kuni ishlaymiz: tajribali jamoa, shaffof "
               "narx va o'z vaqtida topshirish. Biz natijani so'z bilan emas, "
               "raqam bilan ko'rsatamiz. Har bir bosqich boshidan kelishiladi "
               "va keyin o'zgartirilmaydi."),
        "ru": ("Мы работаем в этом направлении каждый день: опытная команда, "
               "прозрачные цены и сдача точно в срок. Результат показываем "
               "цифрами, а не обещаниями. Каждый этап согласуется заранее и не "
               "меняется на ходу."),
        "en": ("We work on this every day: an experienced team, transparent "
               "pricing and on-time delivery. We show results with numbers, not "
               "promises. Every stage is agreed upfront and never shifts "
               "mid-process."),
    },
    "instagram": {
        "uz": ("Eng zo'ri — soddaligi: bir qarashda tushunasiz, bir sinovda "
               "sezasiz. Ertaga ertalab boshlang, kechaga o'zingiz ham "
               "hayron qolasiz. Bu postni saqlab qo'ying, keyin kerak bo'ladi."),
        "ru": ("Самое приятное — простота: понятно с первого взгляда и ощутимо "
               "с первой пробы. Начните завтра утром — к вечеру удивитесь себе. "
               "Сохраните этот пост, он пригодится."),
        "en": ("The best part is how simple it feels: clear at first glance, "
               "real from the first try. Start tomorrow morning and be surprised "
               "by yourself by evening. Save this post — you will need it."),
    },
    "stories": {
        "uz": ("Eski usul ishlamayapti. Bir haftalik sinov — natija ko'rindi. "
               "Xohlagan kishi takrorlay oladi. Havola bo'yida yuring."),
        "ru": ("Старый способ не работал. Неделя теста — и результат виден. "
               "Повторит любой. Переходите по ссылке."),
        "en": ("The old way kept failing. One week of testing showed a result. "
               "Anyone can repeat it. Follow the link."),
    },
    "reels": {
        "uz": ("To'xtang va bir soniya o'ylang. Ana shu yerda xato boshlanadi. "
               "Biz buni 3 qadamda tuzatamiz. Natijani o'zingiz hisoblang."),
        "ru": ("Остановитесь и подумайте секунду. Именно тут начинается ошибка. "
               "Мы исправляем это в три шага. Посчитайте результат сами."),
        "en": ("Stop and think for one second. This is where it goes wrong. We "
               "fix it in three steps. Count the result yourself."),
    },
    "ads": {
        "uz": ("Muammo aniq: har oy vaqt va pul birga ketadi. Yechim tayyor — "
               "bir hafta ichida birinchi natija. Joylar soni cheklangan, "
               "hoziroq yozing."),
        "ru": ("Боль понятна: каждый месяц уходят и время, и деньги. Решение "
               "готово — первый результат за неделю. Мест мало, напишите сейчас."),
        "en": ("The pain is clear: every month you lose time and money. The fix "
               "is ready — first result within a week. Spots are limited, "
               "message us now."),
    },
}


# 3) AUDIT (33/50-band) — model JSON kontraktsiyasi
# ---------------------------------------------------------------------------
AUDIT_BANK: dict[str, dict[str, Any]] = {
    "uz": {
        "verdict": "Post kuchli, lekin CTA va raqamli dalil bilan yana ko'tariladi.",
        "strengths": [
            "Birinchi qator o'quvchini to'xtatadi — hook aniq ishlayapti",
            "Abzaslar qisqa, matn ko'zga chalg'inoq emas",
            "Hashtaglar mavzuga mos va 3-5 ta chegarasida",
        ],
        "improvements": [
            {"criterion": "hook", "fix": "Hook'ni raqam bilan kuchaytiring: masalan «3 xato» yoki «70%»"},
            {"criterion": "value", "fix": "Har bir punktga o'lchanadigan natija qo'shing (vaqt, foiz, summa)"},
            {"criterion": "cta", "fix": "Yakunda bitta aniq CTA qoldiring — ikkinchi chaqiriqni olib tashlang"},
        ],
        "improved_post": (
            "🔥 <b>{topic}</b>\n\n"
            "Haftada 1 marta qaytariladigan xato oyiga [so'm] vaqt olib ketadi. "
            "Quyidagi 3 qadam buni yo'qqa chiqaradi:\n\n"
            "1. <b>Bitta maqsad</b> — postda faqat bitta asosiy fikr;\n"
            "2. <b>Bitta raqam</b> — kamida bitta o'lchanadigan dalil;\n"
            "3. <b>Bitta chaqiriq</b> — oxirda aniq harakat.\n\n"
            "👉 <b>Hoziroq sinab ko'ring</b> va natijani izohda yozing.\n\n"
            "#tahlil #yaxshilangan #smm"
        ),
    },
    "ru": {
        "verdict": "Пост сильный, но CTA и цифровое доказательство поднимут его ещё выше.",
        "strengths": [
            "Первая строка останавливает читателя — hook работает",
            "Короткие абзацы, текст не рябит",
            "Хэштеги по теме и в пределах 3-5",
        ],
        "improvements": [
            {"criterion": "hook", "fix": "Усильте хук цифрой: например «3 ошибки» или «70%»"},
            {"criterion": "value", "fix": "Добавьте измеримый результат в каждый пункт (время, процент, сумма)"},
            {"criterion": "cta", "fix": "Оставьте в конце один чёткий призыв — второй уберите"},
        ],
        "improved_post": (
            "🔥 <b>{topic}</b>\n\n"
            "Ошибка, повторяемая раз в неделю, стоит [сумма] времени в месяц. "
            "Три шага убирают это:\n\n"
            "1. <b>Одна цель</b> — в посте только одна главная мысль;\n"
            "2. <b>Одна цифра</b> — минимум одно измеримое доказательство;\n"
            "3. <b>Один призыв</b> — конкретное действие в конце.\n\n"
            "👉 <b>Попробуйте сегодня</b> и напишите результат в комментариях.\n\n"
            "#разбор #улучшено #smm"
        ),
    },
    "en": {
        "verdict": "The post is strong; a clearer CTA and one number lift it further.",
        "strengths": [
            "The first line stops the scroll — the hook works",
            "Short paragraphs, the text stays easy to scan",
            "Hashtags are on topic and within the 3-5 range",
        ],
        "improvements": [
            {"criterion": "hook", "fix": "Sharpen the hook with a number: “3 mistakes” or “70%”"},
            {"criterion": "value", "fix": "Add a measurable outcome to every bullet (time, percent, amount)"},
            {"criterion": "cta", "fix": "Keep one clear CTA at the end and drop the second ask"},
        ],
        "improved_post": (
            "🔥 <b>{topic}</b>\n\n"
            "A mistake repeated once a week costs [amount] of time each month. "
            "Three steps remove it:\n\n"
            "1. <b>One goal</b> — the post carries a single main idea;\n"
            "2. <b>One number</b> — at least one measurable proof;\n"
            "3. <b>One ask</b> — a concrete action at the end.\n\n"
            "👉 <b>Try it today</b> and write the result in the comments.\n\n"
            "#audit #improved #smm"
        ),
    },
}


# ---------------------------------------------------------------------------
# 4) PLANNER (51-band) — kunlar bo'yicha JSON batch
# ---------------------------------------------------------------------------
PLAN_BANK: dict[str, dict[str, list[str]]] = {
    "uz": {
        "topics": [
            "{topic}: eng ko'p beriladigan 3 savolga javob",
            "{topic} bo'yicha 5 tezkor maslahat",
            "Haftalik natija: {topic} — raqamlar ortidagi haqiqat",
            "{topic} da yo'l qo'yiladigan 3 xato",
            "Mijoz tarixi: {topic} orqali qanday natija olingani",
            "{topic} ning yashirilgan imkoniyatlari",
            "Xulosa haftasi: {topic} bo'yicha o'z fikringizni yozing",
        ],
        "ctas": [
            "👉 Savolingizni izohda qoldiring",
            "📌 Postni saqlab oling va amaliyotda sinang",
            "🔗 Batafsil ma'lumot — profil havolasida",
            "💬 Do'stingizga yuboring, birga muhokama qiling",
            "🛒 Cheklangan joy — hoziroq yozing",
        ],
    },
    "ru": {
        "topics": [
            "{topic}: ответы на 3 частых вопроса",
            "{topic}: 5 быстрых советов",
            "Итоги недели: {topic} — что стоит за цифрами",
            "3 ошибки в теме «{topic}»",
            "Кейс клиента: как был получен результат через {topic}",
            "{topic}: скрытые возможности",
            "Неделя выводов: {topic} — поделитесь мнением",
        ],
        "ctas": [
            "👉 Задайте вопрос в комментариях",
            "📌 Сохраните пост и попробуйте на практике",
            "🔗 Подробности — по ссылке в профиле",
            "💬 Отправьте другу и обсудите вместе",
            "🛒 Мест мало — напишите нам сегодня",
        ],
    },
    "en": {
        "topics": [
            "{topic}: answers to three frequent questions",
            "{topic}: five quick wins",
            "Weekly recap: {topic} behind the numbers",
            "Three mistakes people make with {topic}",
            "Client story: how {topic} produced a real result",
            "{topic}: the hidden upside",
            "Reflection week: what do you think about {topic}",
        ],
        "ctas": [
            "👉 Drop your question in the comments",
            "📌 Save this post and test it this week",
            "🔗 Full details in the profile link",
            "💬 Send it to a friend and compare notes",
            "🛒 Limited spots — message us today",
        ],
    },
}


# ---------------------------------------------------------------------------
# 📥 PHASE D — URL→POST / RSS / RECYCLE banks (11, 12, 13-bandlar)
# ---------------------------------------------------------------------------
#: URL→post: 4 format (news/short/expert/ads) — deterministik, faqat sarlavha.
URL_POST_BANK: dict[str, dict[str, str]] = {
    "news": {
        "uz": ("📰 <b>{topic}</b>\n\nManbaning asosiy g'oyasi: sodda va aniq "
               "tilda aytilgan yangilik. Tafsilotlar manbada — takrorlab "
               "chiqmasdan eng muhimini ajratdik.\n\n🔗 Manba: maqola havolasi"),
        "ru": ("📰 <b>{topic}</b>\n\nГлавная мысль источника: новость, "
               "изложенная простым и точным языком. Детали — в источнике.\n\n"
               "🔗 Источник: ссылка на статью"),
        "en": ("📰 <b>{topic}</b>\n\nThe key idea of the source: the news told "
               "in simple and precise language. Details are in the source.\n\n"
               "🔗 Source: article link"),
    },
    "short": {
        "uz": "⚡ {topic} — buni bilish 30 soniya oladi. Batafsili havolada.",
        "ru": "⚡ {topic} — на это нужно 30 секунд. Подробности по ссылке.",
        "en": "⚡ {topic} — it takes 30 seconds to know this. Details in link.",
    },
    "expert": {
        "uz": ("🧠 <b>{topic}</b>\n\nAmaliy xulosa:\n• Manbadagi asosiy tezisni "
               "o'z sohangizga moslashtiring\n• Raqam va faktlarga tayaning — "
               "tasdiqlanmagan da'vo yozmang\n• Keyingi postda misol bilan "
               "davom ettiring"),
        "ru": ("🧠 <b>{topic}</b>\n\nПрактический вывод:\n• адаптируйте тезис "
               "источника к своей сфере\n• опирайтесь на цифры и факты\n"
               "• продолжите примером в следующем посте"),
        "en": ("🧠 <b>{topic}</b>\n\nPractical takeaway:\n• adapt the source "
               "thesis to your field\n• rely on numbers and facts\n• follow up "
               "with an example in the next post"),
    },
    "ads": {
        "uz": ("📢 <b>{topic}</b>\n\n🎯 Taklif: mavzu bo'yicha amaliy yechim.\n"
               "👉 Batafsil ma'lumot: havolada"),
        "ru": ("📢 <b>{topic}</b>\n\n🎯 Предложение: практическое решение по "
               "теме.\n👉 Подробнее: по ссылке"),
        "en": ("📢 <b>{topic}</b>\n\n🎯 Offer: a practical solution on the "
               "topic.\n👉 More details: in the link"),
    },
}

#: RECYCLE: eski postni yangilovchi (hook/title/body/cta) JSON banki.
RECYCLE_BANK: dict[str, dict[str, str]] = {
    "uz": {
        "hook": "♻️ Bu mavzuni ko'pchilik o'tkazib yuborgan — endi boshqacha ko'rinishda.",
        "title": "Yangilangan qarash: {topic}",
        "body": ("Mavzu o'sha, lekin urg'u boshqa: avval natijaga e'tibor "
                 "berardik, endi esa jarayonning eng muhim qadamiga."),
        "cta": "👉 Siz qaysi qadamni birinchi qo'llaysiz? Izohda yozing.",
    },
    "ru": {
        "hook": "♻️ Эту тему многие пропустили — теперь в другом виде.",
        "title": "Обновлённый взгляд: {topic}",
        "body": ("Тема та же, но акцент другой: раньше смотрели на результат, "
                 "теперь — на ключевой шаг процесса."),
        "cta": "👉 Какой шаг примените первым? Напишите в комментариях.",
    },
    "en": {
        "hook": "♻️ Many missed this topic — here it is again, restructured.",
        "title": "Refreshed take: {topic}",
        "body": ("Same topic, new emphasis: we used to focus on the outcome, "
                 "now on the single most important step of the process."),
        "cta": "👉 Which step will you try first? Tell us in the comments.",
    },
}

#: RSS digest: oqim elementidan AI bilan yozilgan qisqa post.
RSS_BANK: dict[str, str] = {
    "uz": ("📡 <b>{topic}</b>\n\nManba mazmunidagi asosiy o'zgarish va uning "
           "kanalingiz uchun ahamiyati qisqa qilib tushuntirildi.\n\n"
           "🔗 Batafsil: manba havolasi"),
    "ru": ("📡 <b>{topic}</b>\n\nКратко о главном изменении в источнике и о "
           "том, почему это важно для вашего канала.\n\n"
           "🔗 Подробнее: ссылка источника"),
    "en": ("📡 <b>{topic}</b>\n\nA short note on the key change in the source "
           "and why it matters for your channel.\n\n"
           "🔗 Read more: source link"),
}


def url_post_json(lang: Any, topic: str) -> str:
    """URL→post uchun 4 formatdagi deterministik JSON (mock)."""
    code = _lang(lang)
    variants = {key: bank[code].format(topic=topic or "Manba")
                for key, bank in URL_POST_BANK.items()}
    return json.dumps({"variants": variants}, ensure_ascii=False)


def recycle_json(lang: Any, topic: str) -> str:
    """Recycle uchun yangilangan post JSON'i (mock)."""
    code = _lang(lang)
    table = RECYCLE_BANK[code]
    return json.dumps({"refreshed": {
        "hook": table["hook"],
        "title": str(table["title"]).format(topic=clip_topic(topic)),
        "body": table["body"],
        "cta": table["cta"],
    }}, ensure_ascii=False)


def rss_digest_text(lang: Any, topic: str) -> str:
    """RSS qoralamasi uchun qisqa post matni (mock)."""
    return RSS_BANK[_lang(lang)].format(topic=topic or "Yangi material")


def clip_topic(topic: Any, limit: int = 90) -> str:
    """Mavzuni sarlavha uchun qisqartiradi."""
    value = " ".join(str(topic or "").split())
    return value[:limit] if value else "Mavzu"


# ---------------------------------------------------------------------------
# YARDAMCHILAR
# ---------------------------------------------------------------------------
def _lang(lang: Any) -> str:
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in _LANGS else "uz"


def variant_post(style: str, lang: Any, topic: str) -> str:
    """Uslubga xos deterministik post (mock va fallback uchun bitta manba)."""
    template = (VARIANT_BANK.get(str(style or "")) or {}).get(_lang(lang))
    if not template:
        return ""
    return template.format(topic=topic or "Mavzu")


def platform_body(platform: str, lang: Any) -> str:
    """Platforma uchun matn «yadrosi» (repurpose formatlagichi uni o'raydi)."""
    return ((PLATFORM_BANK.get(str(platform or "")) or {}).get(_lang(lang)) or "")


def audit_json(lang: Any, topic: str = "") -> str:
    """Audit xizmati o'qiydigan JSON (model kontrakti bilan bir xil shaklda)."""
    table = AUDIT_BANK.get(_lang(lang)) or AUDIT_BANK["uz"]
    payload = {
        "verdict": table["verdict"],
        "strengths": list(table["strengths"]),
        "improvements": [dict(item) for item in table["improvements"]],
        "improved_post": str(table["improved_post"]).format(topic=topic or "Mavzu"),
    }
    return json.dumps(payload, ensure_ascii=False)


def plan_json(lang: Any, count: int, start_day: int, topic: str) -> str:
    """Reja xizmati o'qiydigan JSON batch (kunlar soni bilan cheklangan)."""
    code = _lang(lang)
    table = PLAN_BANK.get(code) or PLAN_BANK["uz"]
    topics = table["topics"]
    ctas = table["ctas"]
    days = []
    total = max(1, min(int(count or 1), 7))
    for offset in range(total):
        index = start_day + offset
        slot = (index - 1) % len(topics)
        days.append({
            "day": index,
            "topic": str(topics[slot]).format(topic=topic or "Mavzu"),
            "cta": ctas[(index - 1) % len(ctas)],
        })
    return json.dumps({"plan": days}, ensure_ascii=False)


def smm_mock_reply(context: dict | None, topic: str = "") -> str | None:
    """``context["smm_mode"]`` bo'yicha deterministik javob (yo'q bo'lsa None).

    MockProvider shu funksiya orqali advanced SMM rejimlarini real prompt
    formatiga tegizmasdan, lekin to'liq qaytariladigan tarzda javob beradi.
    Mavzu ``context["smm_topic"]`` dan olinadi (xizmat uni escape qilib
    yuboradi) — chunki prompt o'z ichiga butun ko'rsatmani oladi.
    """
    if not isinstance(context, dict):
        return None
    mode = str(context.get("smm_mode") or "").upper()
    if mode not in SMM_MODES:
        return None
    lang = context.get("lang") or "uz"
    topic = str(context.get("smm_topic") or topic or "").strip()

    if mode == SMM_MODE_VARIANTS:
        style = str(context.get("smm_variant_style") or "")
        text = variant_post(style, lang, topic)
        return text or None

    if mode == SMM_MODE_REPURPOSE:
        platform = str(context.get("smm_platform") or "")
        body = platform_body(platform, lang)
        if not body:
            return None
        headline = topic or "Mavzu"
        return (
            f"<b>{headline}</b>\n\n{body}\n\n"
            f"#smm #{platform or 'kontent'}"
        )

    if mode == SMM_MODE_AUDIT:
        return audit_json(lang, topic)

    if mode == SMM_MODE_PLANNER:
        return plan_json(lang, int(context.get("smm_plan_batch") or 7),
                         int(context.get("smm_plan_start") or 1), topic)

    # 📥 PHASE D — URL→post / RSS qoralamasi / recycle (11, 12, 13-bandlar).
    if mode == SMM_MODE_URL_POST:
        return url_post_json(lang, topic)
    if mode == SMM_MODE_RSS:
        return rss_digest_text(lang, topic)
    if mode == SMM_MODE_RECYCLE:
        return recycle_json(lang, topic)
    return None
