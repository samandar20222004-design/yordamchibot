<?php
// 25-bosqich: hamma davlatlar bo'yicha vaqt mintaqasi (MiniAdminTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;
use PostAssist\Services\Countries;
use PostAssist\Services\CountryData;

T::section('AL. Davlatlar va vaqt mintaqasi');
T::check('200+ davlat/hudud, har birida mintaqa', count(CountryData::ALL) >= 240 && count(array_filter(CountryData::ALL, function ($r) { return !$r[3]; })) === 0);
$bad = [];
foreach (CountryData::ALL as $code => $r) {
    foreach (Countries::zones($code) as $z) {
        try {
            new DateTimeZone($z);
        } catch (Throwable $e) {
            $bad[] = $z;
        }
    }
}
T::eq('hamma mintaqalar shu PHP\'da mavjud (yangi nom bo\'lmasa eskisi)', $bad, []);
T::check('Ukraina: eski tzdata\'da ham topiladi', in_array(Countries::zones('UA')[0] ?? '', ['Europe/Kyiv', 'Europe/Kiev'], true));
T::check('davlatlarda mintaqa bo\'sh qolmadi', count(array_filter(array_keys(CountryData::ALL), function ($c) { return !Countries::zones($c); })) === 0);
foreach (['Germaniya' => 'DE', 'Rossiya' => 'RU', 'Qozog\'iston' => 'KZ', 'qozogiston' => 'KZ', 'Qozogʻiston' => 'KZ', 'AQSH' => 'US', 'США' => 'US',
    'Turkiya' => 'TR', 'Германия' => 'DE', 'Japan' => 'JP', 'Misr' => 'EG', 'Braziliya' => 'BR', 'BAA' => 'AE', 'Angliya' => 'GB', 'Polsha' => 'PL',
    'Indoneziya' => 'ID', 'Avstraliya' => 'AU', 'Koreya' => 'KR', 'fr' => 'FR', 'Oʻzbekiston' => 'UZ'] as $q => $want) {
    T::eq("qidiruv: {$q}", Countries::search($q)[0] ?? null, $want);
}
T::eq('bayroq', Countries::flag('UZ'), '🇺🇿');
T::eq('bir xil vaqtli mintaqalar birlashtiriladi (Germaniya)', Countries::distinctZones('DE', new DateTimeImmutable('2027-01-01', new DateTimeZone('UTC'))), ['Europe/Berlin']);
T::check('mintaqa yorlig\'i UTC farqi bilan', Countries::zoneLabel('Asia/Kolkata', new DateTimeImmutable('2027-01-01 00:00:00', new DateTimeZone('UTC'))) === 'Kolkata (UTC+5:30)');
// bot
$GU = 9995;
$text($GU, '/start');
$text($GU, '/timezone');
$text($GU, 'Germaniya');
T::eq('bitta mintaqali davlat: darhol o\'rnatiladi', $app->users->get($GU)['timezone'] ?? null, 'Europe/Berlin');
$text($GU, '/timezone');
$text($GU, 'Qozog‘iston');
if (count(Countries::distinctZones('KZ', $clock)) === 1) {
    T::eq('Qozog\'iston (yangi tzdata: hammasi UTC+5): darhol Almaty', $app->users->get($GU)['timezone'] ?? null, 'Asia/Almaty');
} else {
    T::check('Qozog\'iston (eski tzdata: 2 xil vaqt): shahar so\'raladi', strpos($mk(($fake->of('sendMessage') ?: [[]])[0]), 'tz:Asia\\/Almaty') !== false);
}
$text($GU, '/timezone');
$text($GU, 'Rossiya');
$kbG = $mk(($fake->of('sendMessage') ?: [[]])[0]);
T::check('ko\'p vaqtli davlat: faqat vaqti farqli shaharlar (Moskva birinchi)', strpos($fake->lastText(), 'Rossiya') !== false && strpos($kbG, '"tz:Europe\\/Moscow"') !== false
    && strpos($kbG, 'tz:Asia\\/Vladivostok') !== false && strpos($kbG, 'UTC') !== false && substr_count($kbG, 'tz:') === count(Countries::distinctZones('RU', $clock))
    && strpos($kbG, 'Ust-Nera') === false);
$press($GU, 'tz:Asia/Vladivostok');
T::eq('shahar tugmasi bilan', $app->users->get($GU)['timezone'] ?? null, 'Asia/Vladivostok');
$text($GU, '/timezone');
$text($GU, 'Gvineya');
T::check('o\'xshash nomlar: davlat tanlash', strpos($fake->lastText(), 'Qaysi davlat') !== false && substr_count($mk(($fake->of('sendMessage') ?: [[]])[0]), 'tzc:') >= 2);
$press($GU, 'tzc:US');
T::check('davlat tugmasi: AQSH shaharlari', strpos($mk(($fake->of('sendMessage') ?: [[]])[0]), 'tz:America\/New_York') !== false);
$press($GU, 'tz:America/Port-au-Prince');
T::eq('defisli mintaqa nomi ham ishlaydi', $app->users->get($GU)['timezone'] ?? null, 'America/Port-au-Prince');
$text($GU, '/timezone');
$text($GU, 'Nyu-York');
T::eq('shahar (o\'zbekcha yozilishi)', $app->users->get($GU)['timezone'] ?? null, 'America/New_York');
$fake->reset();
$r = MiniAppApi::handle($app, 'tz_search', ['q' => 'Braziliya'], $mkInit(['id' => $GU, 'first_name' => 'G', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token));
T::check('Mini App: davlat qidiruvi', $r[0] === 200 && $r[1]['results'][0]['zone'] === 'America/Sao_Paulo' && $r[1]['results'][0]['flag'] === '🇧🇷');
$r2 = MiniAppApi::handle($app, 'tz_search', ['q' => 'Germaniya'], $mkInit(['id' => $GU, 'first_name' => 'G', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token));
T::eq('Mini App: bir xil vaqtli mintaqalar takrorlanmaydi', array_column($r2[1]['results'], 'zone'), ['Europe/Berlin']);

T::section('AM. Mini App: ko\'rinish sozlamalari');
$appSrc6 = (string) file_get_contents(__DIR__ . '/../app.php');
foreach (['data-theme=dark', 'data-accent=violet', 'data-size=l', 'data-density=compact', 'data-motion=off', 'data-labels=off', 'pa_ui_v1', 'CloudStorage', 'tz_search', 'id="ui-card"'] as $needle) {
    T::check("app.php: {$needle}", strpos($appSrc6, $needle) !== false);
}
foreach (['uz', 'ru', 'en'] as $l) {
    $tbl = \PostAssist\I18n::table($l);
    T::check("[{$l}] ko'rinish matnlari", isset($tbl['ma_ui_title'], $tbl['ma_ui_part_bot'], $tbl['ma_tz_search'], $tbl['tz_pick_zone']));
}
