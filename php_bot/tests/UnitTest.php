<?php
// DB'siz testlar.
declare(strict_types=1);

use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Services\Links;
use PostAssist\Services\PostRender;
use PostAssist\Services\TimeParser;

T::section('A. Formatlash (Telegram entities -> HTML)');
T::eq('oddiy matn escape qilinadi', Html::fromEntities('a < b & "c"', []), 'a &lt; b &amp; &quot;c&quot;');
T::eq('qalin', Html::fromEntities('Salom dunyo', [['type' => 'bold', 'offset' => 0, 'length' => 5]]), '<b>Salom</b> dunyo');
T::eq('emoji (UTF-16 = 2 birlik) dan keyingi offset', Html::fromEntities('😀 bold', [['type' => 'bold', 'offset' => 3, 'length' => 4]]), '😀 <b>bold</b>');
T::eq('ichma-ich: qalin ichida kursiv', Html::fromEntities('abcdef', [['type' => 'bold', 'offset' => 0, 'length' => 6], ['type' => 'italic', 'offset' => 2, 'length' => 2]]), '<b>ab<i>cd</i>ef</b>');
T::eq('ustma-ust teglar to\'g\'ri yopiladi', Html::fromEntities('abcdef', [['type' => 'bold', 'offset' => 0, 'length' => 4], ['type' => 'italic', 'offset' => 2, 'length' => 4]]), '<b>ab<i>cd</i></b><i>ef</i>');
T::eq('havola: URL escape qilinadi', Html::fromEntities('bu yerda', [['type' => 'text_link', 'offset' => 0, 'length' => 8, 'url' => 'https://x.uz/?a=1&b="2"']]), '<a href="https://x.uz/?a=1&amp;b=&quot;2&quot;">bu yerda</a>');
T::eq('url/mention/hashtag oddiy matn bo\'lib qoladi', Html::fromEntities('@kanal #teg', [['type' => 'mention', 'offset' => 0, 'length' => 6], ['type' => 'hashtag', 'offset' => 7, 'length' => 4]]), '@kanal #teg');
T::eq('pre + til', Html::fromEntities('x=1', [['type' => 'pre', 'offset' => 0, 'length' => 3, 'language' => 'php']]), '<pre><code class="language-php">x=1</code></pre>');
T::eq('custom emoji', Html::fromEntities('🔥', [['type' => 'custom_emoji', 'offset' => 0, 'length' => 2, 'custom_emoji_id' => '5368324170671202286']]), '<tg-emoji emoji-id="5368324170671202286">🔥</tg-emoji>');
T::eq('chegaradan chiqqan entity e\'tiborsiz', Html::fromEntities('abc', [['type' => 'bold', 'offset' => 2, 'length' => 9]]), 'abc');
T::eq('kirill + qalin', Html::fromEntities('Привет мир', [['type' => 'bold', 'offset' => 7, 'length' => 3]]), 'Привет <b>мир</b>');
T::eq('UTF-16 uzunlik: emoji 2', Html::utf16Len('a😀'), 3);
T::eq('plain: teglar va entity olib tashlanadi', Html::plain('<b>a &amp; b</b>'), 'a & b');

T::section('B. Vaqtni tushunish (Toshkent, hozir 15:00 = 10:00 UTC)');
$tz = new DateTimeZone('Asia/Tashkent');
$now = new DateTimeImmutable('2026-11-03 10:00:00', new DateTimeZone('UTC'));
$p = static function (string $s) use ($tz, $now): string {
    $r = TimeParser::parse($s, $tz, $now);
    return $r['ok'] ? $r['utc']->format('Y-m-d H:i') : 'ERR:' . $r['error'];
};
T::eq('16:30 -> bugun', $p('16:30'), '2026-11-03 11:30');
T::eq('14:00 (o\'tgan) -> ertaga', $p('14:00'), '2026-11-04 09:00');
T::eq('14.30 nuqta bilan', $p('16.45'), '2026-11-03 11:45');
T::eq('ertaga 09:00', $p('ertaga 09:00'), '2026-11-04 04:00');
T::eq('Ertaga soat 9:05 (katta harf, soat so\'zi)', $p('Ertaga soat 9:05'), '2026-11-04 04:05');
T::eq('завтра 23:59', $p('завтра 23:59'), '2026-11-04 18:59');
T::eq('tomorrow 08:00', $p('tomorrow 08:00'), '2026-11-04 03:00');
T::eq('indinga 10:00', $p('indinga 10:00'), '2026-11-05 05:00');
T::eq('bugun 14:00 (o\'tgan) -> xato', $p('bugun 14:00'), 'ERR:past');
T::eq('25.12 18:00', $p('25.12 18:00'), '2026-12-25 13:00');
T::eq('01.01 10:00 -> keyingi yil', $p('01.01 10:00'), '2027-01-01 05:00');
T::eq('25.12.2026 18:00', $p('25.12.2026 18:00'), '2026-12-25 13:00');
T::eq('31.02 -> xato', $p('31.02 10:00'), 'ERR:bad');
T::eq('25:00 -> xato', $p('25:00'), 'ERR:bad');
T::eq('+30 daqiqa', $p('+30'), '2026-11-03 10:30');
T::eq('+0 -> o\'tgan', $p('+0'), 'ERR:past');
T::eq('2 soatdan keyin', $p('2 soatdan keyin'), '2026-11-03 12:00');
T::eq('30 daqiqadan keyin', $p('30 daqiqadan keyin'), '2026-11-03 10:30');
T::eq('через 2 часа', $p('через 2 часа'), '2026-11-03 12:00');
T::eq('in 15 minutes', $p('in 15 minutes'), '2026-11-03 10:15');
T::eq('3 kundan keyin', $p('3 kundan keyin'), '2026-11-06 10:00');
T::eq('2030 -> juda uzoq', $p('01.01.2030 10:00'), 'ERR:too_far');
T::eq('ma\'nosiz matn', $p('salom'), 'ERR:bad');
T::eq('tezkor: 1 soat', TimeParser::quick('1h', $tz, $now)->format('Y-m-d H:i'), '2026-11-03 11:00');
T::eq('tezkor: bugun 18:00', TimeParser::quick('today18', $tz, $now)->format('Y-m-d H:i'), '2026-11-03 13:00');
T::eq('tezkor: bugun 18:00 o\'tgan -> ertaga', TimeParser::quick('today18', $tz, new DateTimeImmutable('2026-11-03 13:30:00', new DateTimeZone('UTC')))->format('Y-m-d H:i'), '2026-11-04 13:00');
T::eq('tezkor: ertaga 09:00', TimeParser::quick('tom09', $tz, $now)->format('Y-m-d H:i'), '2026-11-04 04:00');
T::eq('tezkor: noma\'lum -> null', TimeParser::quick('x', $tz, $now), null);
T::eq('ko\'rsatish: UTC -> Toshkent', TimeParser::show('2026-12-25 13:00:00', $tz), '25.12.2026 18:00');

T::section('C. Havolali tugma');
T::eq('@kanal', Links::normalize('@kanalim'), 'https://t.me/kanalim');
T::eq('t.me/...', Links::normalize('t.me/kanal/12'), 'https://t.me/kanal/12');
T::eq('sayt.uz', Links::normalize('sayt.uz'), 'https://sayt.uz');
T::eq('https saqlanadi', Links::normalize('https://example.com/a?b=1'), 'https://example.com/a?b=1');
T::eq('javascript: rad', Links::normalize('javascript:alert(1)'), null);
T::eq('nuqtasiz host rad', Links::normalize('http://localhost'), null);
T::eq('ftp rad', Links::normalize('ftp://x.uz'), null);
T::eq('probelli rad', Links::normalize('sayt .uz'), null);
T::eq('tugma: "Matn - havola"', Links::parseButton('Batafsil - https://sayt.uz'), ['Batafsil', 'https://sayt.uz']);
T::eq('tugma: "Matn | @kanal"', Links::parseButton('Kanal | @kanalim'), ['Kanal', 'https://t.me/kanalim']);
T::eq('tugma: chiziqchali matn', Links::parseButton("Yangi-yil aksiyasi - sayt.uz"), ['Yangi-yil aksiyasi', 'https://sayt.uz']);
T::eq('tugma: havolasiz rad', Links::parseButton('faqat matn'), null);
T::eq('tugma: matnsiz rad', Links::parseButton(' - https://x.uz'), null);

T::section('D. Nishon (bepul tarif) va post qoralamasi');
T::eq('bepul: boshiga nishon', PostRender::watermark('Salom', 'text', 'PostAssistrobot', true), "🤖 @PostAssistrobot\n\nSalom");
T::eq('pullik: nishonsiz', PostRender::watermark('Salom', 'text', 'PostAssistrobot', false), 'Salom');
$full = str_repeat('a', 4096);
T::eq('matn limitga to\'lgan: nishon qo\'yilmaydi', PostRender::watermark($full, 'text', 'PostAssistrobot', true), $full);
$cap = str_repeat('b', 1010);
T::eq('izoh (1024) limitiga sig\'masa: nishonsiz', PostRender::watermark($cap, 'photo', 'PostAssistrobot', true), $cap);
T::eq('matn: qoralama', PostRender::draftFromMessage(['text' => 'Hi', 'entities' => [['type' => 'bold', 'offset' => 0, 'length' => 2]]]), ['type' => 'text', 'file_id' => null, 'text' => '<b>Hi</b>']);
T::eq('rasm: eng katta o\'lcham, izoh', PostRender::draftFromMessage(['photo' => [['file_id' => 's'], ['file_id' => 'L']], 'caption' => 'c']), ['type' => 'photo', 'file_id' => 'L', 'text' => 'c']);
T::eq('GIF: animation (document emas)', PostRender::draftFromMessage(['animation' => ['file_id' => 'g'], 'document' => ['file_id' => 'd']])['type'] ?? null, 'animation');
T::eq('hujjat', PostRender::draftFromMessage(['document' => ['file_id' => 'd']])['type'] ?? null, 'document');
T::eq('stiker: qo\'llanmaydi', PostRender::draftFromMessage(['sticker' => ['file_id' => 'x']]), null);
T::eq('sabab: admin emas', PostRender::reasonKey(['error_code' => 400, 'description' => 'Bad Request: not enough rights to send text messages to the chat']), 'reason_not_admin');
T::eq('sabab: 403 chiqarilgan', PostRender::reasonKey(['error_code' => 403, 'description' => 'Forbidden: bot was kicked']), 'reason_not_admin');
T::eq('sabab: kanal topilmadi', PostRender::reasonKey(['error_code' => 400, 'description' => 'Bad Request: chat not found']), 'reason_chat_not_found');
T::eq('sabab: format', PostRender::reasonKey(['error_code' => 400, 'description' => "Bad Request: can't parse entities"]), 'reason_format');
T::eq('sabab: tarmoq', PostRender::reasonKey(['error_code' => 0, 'description' => 'network: timeout']), 'reason_network');

T::section('E. Uch til (uz/ru/en) va tugmalar');
$base = I18n::table('uz');
$ph = static function (string $s): array {
    preg_match_all('/\{(\w+)\}/', $s, $m);
    $x = array_unique($m[1]);
    sort($x);
    return $x;
};
foreach (['ru', 'en'] as $l) {
    $tbl = I18n::table($l);
    T::eq("[{$l}] kalitlar uz bilan bir xil", array_values(array_diff(array_keys($base), array_keys($tbl))), []);
    T::eq("[{$l}] ortiqcha kalit yo'q", array_values(array_diff(array_keys($tbl), array_keys($base))), []);
    $bad = [];
    foreach ($base as $k => $v) {
        if (isset($tbl[$k]) && $ph($v) !== $ph($tbl[$k])) {
            $bad[] = $k;
        }
    }
    T::eq("[{$l}] {o'rinbosarlar} mos", $bad, []);
}
$menuKeys = ['btn_create_content', 'btn_my_channels', 'btn_scheduled', 'btn_statistics', 'btn_settings', 'btn_admin'];
foreach (I18n::LANGS as $l) {
    $long = [];
    foreach (I18n::table($l) as $k => $v) {
        if (strpos($k, 'btn_') === 0 && !in_array($k, $menuKeys, true) && mb_strlen($v) > 18) {
            $long[] = "{$k}={$v}";
        }
    }
    T::eq("[{$l}] tugma yorlig'i ≤18 belgi", $long, []);
    $empty = array_keys(array_filter(I18n::table($l), static function ($v) {
        return trim((string) $v) === '';
    }));
    T::eq("[{$l}] bo'sh matn yo'q", $empty, []);
}
T::eq('menyu tugmasi har tilda taniladi', I18n::keyOf('📢 Мои каналы', $menuKeys), 'btn_my_channels');
T::eq('noma\'lum matn menyu emas', I18n::keyOf('salom', $menuKeys), null);
T::eq('til aniqlash: ru', I18n::detect('ru-RU'), 'ru');
T::eq('til aniqlash: noma\'lum -> en', I18n::detect('de'), 'en');
T::eq('til aniqlash: bo\'sh -> uz', I18n::detect(null), 'uz');
$cb = [];
foreach ([Keyboards::previewRows('uz', true), Keyboards::confirm('uz', 'ch:delok:9999999999', 'ch:list')['inline_keyboard']] as $rows) {
    foreach ($rows as $row) {
        foreach ($row as $b) {
            $cb[] = strlen((string) ($b['callback_data'] ?? ''));
        }
    }
}
T::check('callback_data ≤64 bayt', max($cb) <= 64);

T::section('G. Tariflar, to\'lov, promo, havola qoidalari (2-bosqich)');
use PostAssist\Repo\Credits;
use PostAssist\Repo\Payments;
use PostAssist\Repo\Promos;
use PostAssist\Repo\TrackedLinks;
use PostAssist\Services\Plans;
use PostAssist\Handlers\PlansHandler;

$cat = Plans::catalog();
T::eq('katalog: 8 ta kalit (PRO + ULTRA, 4 muddat)', array_keys($cat), ['1m', '3m', '6m', '1y', 'u1m', 'u3m', 'u6m', 'u1y']);
T::eq('Stars narxlari (Python bilan bir xil)', array_map(static function ($p) {
    return $p['stars'];
}, array_values($cat)), [195, 510, 910, 1650, 470, 1180, 2260, 4180]);
T::eq('kunlar 30/90/180/365', array_values(array_unique(array_column($cat, 'days'))), [30, 90, 180, 365]);
T::eq('PRO tejam: 0/13/22/29', [Plans::discount(195, 195, 1), Plans::discount(510, 195, 3), Plans::discount(910, 195, 6), Plans::discount(1650, 195, 12)], [0, 13, 22, 29]);
T::eq('ULTRA tejam: 0/16/20/26', [Plans::discount(470, 470, 1), Plans::discount(1180, 470, 3), Plans::discount(2260, 470, 6), Plans::discount(4180, 470, 12)], [0, 16, 20, 26]);
T::eq('limitlar: FREE 3/40, PRO 10/300, ULTRA 30/900, enterprise cheksiz', [Plans::limits('free'), Plans::limits('pro'), Plans::limits('ultra'), Plans::limits('enterprise')],
    [['channels' => 3, 'queue' => 40], ['channels' => 10, 'queue' => 300], ['channels' => 30, 'queue' => 900], ['channels' => 0, 'queue' => 0]]);
$cfg2 = new PostAssist\Config(['stars_prices' => ['1m' => 250, 'xx' => 5, '3m' => -1], 'tier_limits' => ['pro' => ['channels' => 12]]]);
T::eq('config: narxni almashtirish (noto\'g\'ri qiymatlar e\'tiborsiz)', [Plans::catalog($cfg2)['1m']['stars'], Plans::catalog($cfg2)['3m']['stars'], isset(Plans::catalog($cfg2)['xx'])], [250, 510, false]);
T::eq('config: tarif limitini almashtirish', Plans::limits('pro', $cfg2), ['channels' => 12, 'queue' => 300]);
$nowU = new DateTimeImmutable('2026-11-10 10:00:00', new DateTimeZone('UTC'));
T::eq('amaldagi tarif: muddati bor PRO', Plans::effective('pro', '2026-12-01 00:00:00', $nowU), 'pro');
T::eq('amaldagi tarif: muddati o\'tgan ULTRA = free', Plans::effective('ultra', '2026-11-10 09:59:59', $nowU), 'free');
T::eq('amaldagi tarif: muddatsiz PRO = free', Plans::effective('pro', null, $nowU), 'free');
T::eq('amaldagi tarif: enterprise', Plans::effective('enterprise', null, $nowU), 'enterprise');
T::eq('amaldagi tarif: noma\'lum = free', Plans::effective('vip', '2030-01-01 00:00:00', $nowU), 'free');
$long = [];
foreach (I18n::LANGS as $l) {
    foreach ($cat as $p) {
        $b = PlansHandler::periodButton(I18n::t('period_' . $p['period'], $l), $p['stars']);
        if (mb_strlen($b) > 18) {
            $long[] = "{$l}:{$b}";
        }
        $title = I18n::t('invoice_title', $l, ['plan' => Plans::NAMES[$p['tier']], 'period' => I18n::t('period_' . $p['period'], $l)]);
        if (mb_strlen($title) > 32) {
            $long[] = "{$l}:{$title}";
        }
    }
}
T::eq('muddat tugmalari ≤18 belgi, hisob nomi ≤32 (3 tilda)', $long, []);
T::eq('payload', Payments::payload('u3m', 5001), 'sub_stars_u3m_5001');
T::eq('to\'lov tekshiruvi: to\'g\'ri', Payments::validate(null, 'sub_stars_3m_5001', 'XTR', 510, 5001)['ok'], true);
T::eq('to\'lov: summa mos emas', Payments::validate(null, 'sub_stars_3m_5001', 'XTR', 1, 5001)['error'] ?? '', 'bad_amount');
T::eq('to\'lov: valyuta XTR emas', Payments::validate(null, 'sub_stars_3m_5001', 'USD', 510, 5001)['error'] ?? '', 'bad_amount');
T::eq('to\'lov: boshqa foydalanuvchi payloadi', Payments::validate(null, 'sub_stars_3m_5002', 'XTR', 510, 5001)['error'] ?? '', 'wrong_user');
T::eq('to\'lov: noma\'lum kalit', Payments::validate(null, 'sub_stars_2m_5001', 'XTR', 510, 5001)['error'] ?? '', 'bad_payload');
T::eq('to\'lov: ortiqcha belgi', Payments::validate(null, 'sub_stars_3m_5001x', 'XTR', 510, 5001)['error'] ?? '', 'bad_payload');
T::eq('promo normallashtirish: probel, qo\'shtirnoq, ko\'rinmas belgi', Promos::normalize(" «test\u{200B}30» "), 'TEST30');
T::eq('promo: juda qisqa', Promos::normalize('ab'), null);
T::eq('promo: noto\'g\'ri belgi', Promos::normalize('KOD!'), null);
T::eq('havola kodi: " Kanal-1 " -> kanal_1', TrackedLinks::normalizeCode(' Kanal-1 '), 'kanal_1');
T::eq('havola kodi: 1 belgi rad', TrackedLinks::normalizeCode('a'), null);
T::eq('havola kodi: kirill rad', TrackedLinks::normalizeCode('канал'), null);
T::eq('start parametri s_<kod>', [TrackedLinks::codeFromPayload('s_kanal_1'), TrackedLinks::codeFromPayload('ref_5'), TrackedLinks::codeFromPayload('s_A')], ['kanal_1', null, null]);
T::eq('referal mukofoti: 1-3 => 3, 4+ => 1', [Credits::rewardFor(1), Credits::rewardFor(3), Credits::rewardFor(4), Credits::rewardFor(50)], [3, 3, 1, 1]);
$cbs = [];
foreach ($cat as $p) {
    $cbs[] = strlen('pl:b:' . $p['key']);
}
T::check('tarif callback_data ≤64 bayt', max($cbs) <= 64);
