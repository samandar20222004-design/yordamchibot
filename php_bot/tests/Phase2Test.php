<?php
// 2-bosqich integratsiya testi (IntegrationTest.php ichidan chaqiriladi: $app, $db, $fake, $router, $text, $press, $send, $clock ... tayyor).
declare(strict_types=1);

use PostAssist\Services\Plans;
use PostAssist\Services\Scheduler;

T::section('H. Tariflar, Stars to\'lovi, promo, referal, manba havolalari');
$clock = new DateTimeImmutable('2026-11-10 10:00:00', new DateTimeZone('UTC'));
$pay = static function (int $uid, string $payload, int $amount, string $charge, string $currency = 'XTR') use ($send) {
    $send($uid, ['successful_payment' => ['currency' => $currency, 'total_amount' => $amount, 'invoice_payload' => $payload,
        'telegram_payment_charge_id' => $charge, 'provider_payment_charge_id' => '']]);
};
$pcq = static function (int $uid, string $payload, int $amount, string $currency = 'XTR') use (&$upd, $router, $from, $fake): array {
    $fake->reset();
    $router->handle(['update_id' => $upd++, 'pre_checkout_query' => ['id' => 'pcq' . $upd, 'from' => $from($uid), 'currency' => $currency,
        'total_amount' => $amount, 'invoice_payload' => $payload]]);
    return $fake->of('answerPreCheckoutQuery')[0] ?? [];
};
$plan = static function (int $uid) use ($db): array {
    return $db->one('SELECT plan_type, subscription_expires_at, ai_credits FROM users WHERE user_id = ?', [$uid]) ?? [];
};

// --- tariflar ekrani
$text($U, '⚙️ Sozlamalar / Ko\'proq');
$kb = $mk($fake->of('sendMessage')[0] ?? []);
T::check('sozlamalar: tarif, taklif, promo tugmalari', strpos($kb, 'pl:show') !== false && strpos($kb, 'ref:show') !== false && strpos($kb, 'promo:ask') !== false);
T::check('sozlamalarda joriy tarif: FREE', strpos($fake->lastText(), 'Tarif: <b>FREE</b>') !== false);
$text($U, '/plans');
T::check('/plans: FREE/PRO/ULTRA limitlari', strpos($fake->lastText(), 'Sizning tarifingiz: <b>FREE</b>') !== false
    && strpos($fake->lastText(), '📢 10 kanal') !== false && strpos($fake->lastText(), '📢 30 kanal') !== false);
$press($U, 'pl:t:ultra');
T::check('ULTRA muddatlari: narx va tejam', strpos($fake->lastText(), '1180⭐') !== false && strpos($fake->lastText(), 'tejam 16%') !== false
    && strpos($mk($fake->of('editMessageText')[0] ?? []), 'pl:b:u1y') !== false);
$press($U, 'pl:b:3m');
$inv = $fake->of('sendInvoice')[0] ?? [];
T::check('hisob (invoice): XTR, 510 Stars, payload', ($inv['currency'] ?? '') === 'XTR' && ($inv['payload'] ?? '') === 'sub_stars_3m_' . $U
    && strpos((string) ($inv['prices'] ?? ''), '"amount":510') !== false && ($inv['provider_token'] ?? null) === '');
T::check('hisob nomi ≤32 belgi', mb_strlen((string) ($inv['title'] ?? '')) <= 32 && mb_strlen((string) ($inv['title'] ?? '')) > 0);
$press($ADMIN, 'pl:b:3m');
T::eq('admin uchun hisob yuborilmaydi (cheksiz)', count($fake->of('sendInvoice')), 0);

// --- pre_checkout
$a = $pcq($U, 'sub_stars_3m_' . $U, 510);
T::eq('pre_checkout: to\'g\'ri — ok', $a['ok'] ?? null, 'true');
$a = $pcq($U, 'sub_stars_3m_' . $U, 1);
T::check('pre_checkout: summa noto\'g\'ri — rad, sabab bilan', ($a['ok'] ?? null) === 'false' && strpos((string) ($a['error_message'] ?? ''), 'eskirgan') !== false);
$a = $pcq($U, 'sub_stars_3m_' . $U2, 510);
T::eq('pre_checkout: boshqa foydalanuvchi payloadi — rad', $a['ok'] ?? null, 'false');

// --- muvaffaqiyatli to'lov
$pay($U, 'sub_stars_3m_' . $U, 510, 'ch_1');
T::eq('to\'lov: PRO 90 kun', [$plan($U)['plan_type'] ?? '', $plan($U)['subscription_expires_at'] ?? ''], ['pro', '2027-02-08 10:00:00']);
T::check('foydalanuvchiga «To\'lov qabul qilindi»', strpos($fake->texts(), 'To\'lov qabul qilindi') !== false && strpos($fake->texts(), '08.02.2027') !== false);
$adminMsg = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($ADMIN) {
    return (int) $m['chat_id'] === $ADMIN;
}));
T::check('adminga to\'lov xabari (davr admin tilida)', $adminMsg && strpos((string) $adminMsg[0]['text'], '510⭐') !== false && strpos((string) $adminMsg[0]['text'], '3 oy') !== false);
$pay($U, 'sub_stars_3m_' . $U, 510, 'ch_1');
T::check('o\'sha to\'lov qayta kelsa — ikkinchi marta tarif berilmaydi', ($plan($U)['subscription_expires_at'] ?? '') === '2027-02-08 10:00:00'
    && strpos($fake->lastText(), 'allaqachon') !== false);
T::eq('payments jadvalida bitta yozuv', (int) $db->value('SELECT COUNT(*) FROM payments WHERE user_id = ?', [$U]), 1);
$pay($U, 'sub_stars_1y_' . $U, 5, 'ch_bad');
T::check('summa mos kelmagan to\'lov: tarif o\'zgarmaydi, adminga muammo', ($plan($U)['subscription_expires_at'] ?? '') === '2027-02-08 10:00:00'
    && strpos($fake->texts(), 'To\'lov muammosi') !== false && strpos($fake->texts(), 'mos kelmadi') !== false);
T::eq('PRO limitlari: 10 kanal, 300 navbat', [$app->channelLimit($U), $app->queueLimit($U)], [10, 300]);
T::eq('PRO: nishonsiz', $app->isFree($U), false);
$pay($U, 'sub_stars_u1m_' . $U, 470, 'ch_2');
T::eq('PRO ustiga ULTRA: tarif ULTRA, qolgan kunlar saqlanadi (+30)', [$plan($U)['plan_type'] ?? '', $plan($U)['subscription_expires_at'] ?? ''], ['ultra', '2027-03-10 10:00:00']);
$pay($U, 'sub_stars_1m_' . $U, 195, 'ch_3');
T::check('ULTRA bor-u PRO olsa: ULTRA saqlanadi, muddat uzayadi', ($plan($U)['plan_type'] ?? '') === 'ultra'
    && ($plan($U)['subscription_expires_at'] ?? '') === '2027-04-09 10:00:00' && strpos($fake->texts(), 'saqlandi') !== false);

// --- admin: tarif berish
$text($U2, '/grant_pro ' . $U2 . ' 30');
T::check('oddiy foydalanuvchi /grant_pro qila olmaydi', ($plan($U2)['plan_type'] ?? '') === 'free');
$text($ADMIN, '/grant_pro 424242 30');
T::check('noma\'lum foydalanuvchi', strpos($fake->lastText(), 'topilmadi') !== false);
$text($ADMIN, '/grant_pro ' . $U2 . ' 99999');
T::check('kunlar chegarasi (3650)', strpos($fake->texts(), '1–3650') !== false || strpos($fake->texts(), 'Foydalanish') !== false);
$text($ADMIN, '/grant_pro ' . $U2 . ' 3650 vip');
T::check('noma\'lum tarif rad', ($plan($U2)['plan_type'] ?? '') === 'free');
$text($ADMIN, '/grant_pro ' . $U2 . ' 7 ultra');
T::eq('admin berdi: ULTRA 7 kun', [$plan($U2)['plan_type'] ?? '', $plan($U2)['subscription_expires_at'] ?? ''], ['ultra', '2026-11-17 10:00:00']);
T::check('foydalanuvchiga xabar (o\'z tilida — ru)', strpos($fake->texts(), 'Вам выдан тариф') !== false);
$db->exec("UPDATE users SET plan_type = 'enterprise', subscription_expires_at = NULL WHERE user_id = 5004");
$text($ADMIN, '/grant_pro 5004 30');
T::eq('enterprise o\'zgarmaydi', $plan(5004)['plan_type'] ?? '', 'enterprise');
T::eq('enterprise limitlari cheksiz', [$app->channelLimit(5004), $app->queueLimit(5004), $app->isFree(5004)], [0, 0, false]);

// --- muddat: eslatma va tugash (cron)
$sched = new Scheduler($app, static function (int $us): void {
});
$clock = new DateTimeImmutable('2026-11-16 11:00:00', new DateTimeZone('UTC'));
$fake->reset();
$r = $sched->planMaintenance();
T::check('24 soat qolganda eslatma', $r['reminded'] === 1 && strpos($fake->texts(), 'заканчивается') !== false);
$fake->reset();
T::eq('eslatma faqat bir marta', $sched->planMaintenance()['reminded'], 0);
$clock = new DateTimeImmutable('2026-11-17 10:00:01', new DateTimeZone('UTC'));
T::eq('muddat tugadi: darhol FREE hisoblanadi', [$app->tier($U2), $app->isFree($U2)], ['free', true]);
$fake->reset();
$r = $sched->run(5);
T::check('cron: tarif FREE ga tushirildi va xabar berildi', ($plan($U2)['plan_type'] ?? '') === 'free' && strpos($fake->texts(), 'закончился') !== false);
$fake->reset();
T::eq('qayta cron: ikkinchi xabar yo\'q', $sched->planMaintenance()['expired'], 0);
$pay($U2, 'sub_stars_1m_' . $U2, 195, 'ch_4');
T::eq('tugagandan keyin sotib olish: hozirdan +30 kun', $plan($U2)['subscription_expires_at'] ?? '', '2026-12-17 10:00:01');

// --- promo-kodlar
$text($U2, '/create_promo X 30');
T::check('oddiy foydalanuvchi promo yarata olmaydi', (int) $db->value('SELECT COUNT(*) FROM promo_codes') === 0);
$text($ADMIN, '/create_promo test30 30 2');
T::check('promo yaratildi (katta harf)', strpos($fake->lastText(), 'TEST30') !== false && (int) $db->value("SELECT max_uses FROM promo_codes WHERE code = 'TEST30'") === 2);
$text($ADMIN, '/create_promo TEST30 10');
T::check('takror kod rad', strpos($fake->lastText(), 'allaqachon bor') !== false);
$text($ADMIN, '/create_promo ULT7 7 ultra');
$text($ADMIN, '/create_promo BAD 0');
T::check('0 kun rad', (int) $db->value("SELECT COUNT(*) FROM promo_codes WHERE code = 'BAD'") === 0);
$text($ADMIN, '/create_promo E! 5');
T::check('yaroqsiz kod rad', strpos($fake->lastText(), '3–32') !== false);
$U7 = 7001;
$text($U7, '/start');
$text($U7, '⚙️ Sozlamalar / Ko\'proq');
$press($U7, 'promo:ask');
T::eq('promo kutilmoqda', $app->states->get($U7)['state'] ?? null, 'promo_wait');
$text($U7, '«test30»');
T::eq('promo: PRO 30 kun', [$plan($U7)['plan_type'] ?? '', $plan($U7)['subscription_expires_at'] ?? ''], ['pro', '2026-12-17 10:00:01']);
T::check('promo xabari va holat tozalandi', strpos($fake->lastText(), 'Promo-kod qabul qilindi') !== false && $app->states->get($U7) === null);
$text($U7, '/promo TEST30');
T::check('bir kod bir marta', strpos($fake->lastText(), 'allaqachon foydalangansiz') !== false);
$text(5003, '/promo test30');
$text(5002, '/promo test30');
T::check('limit tugadi (2 ta)', strpos($fake->lastText(), 'limiti tugagan') !== false || strpos($fake->lastText(), 'исчерпан') !== false);
T::eq('foydalanishlar soni 2', (int) $db->value("SELECT current_uses FROM promo_codes WHERE code = 'TEST30'"), 2);
$text($ADMIN, '/promo_off ULT7');
$text(5003, '/promo ULT7');
T::check('o\'chirilgan kod', strpos($fake->lastText(), 'o\'chirilgan') !== false);
$text($ADMIN, '/promo_on ULT7');
$text(5003, '/promo ULT7');
T::eq('PRO ustiga ULTRA promo: ULTRA, qolgan kunlar saqlanadi', [$plan(5003)['plan_type'] ?? '', $plan(5003)['subscription_expires_at'] ?? ''], ['ultra', '2026-12-24 10:00:01']);
$text(5004, '/promo ULT7');
T::check('enterprise: kod sarflanmaydi', strpos($fake->lastText(), 'muddatsiz') !== false
    && (int) $db->value("SELECT current_uses FROM promo_codes WHERE code = 'ULT7'") === 1);
$U8 = 7002;
$text($U8, '/start');
for ($i = 1; $i <= 5; $i++) {
    $text($U8, '/promo WRONG' . $i);
}
$text($U8, '/promo ULT7');
T::check('5 ta noto\'g\'ri urinishdan keyin to\'siladi (to\'g\'ri kod bilan ham)', strpos($fake->lastText(), '10 daqiqadan') !== false && ($plan($U8)['plan_type'] ?? '') === 'free');
$clock = $clock->modify('+11 minutes');
$text($U8, '/promo ULT7');
T::eq('10 daqiqadan keyin yana mumkin', $plan($U8)['plan_type'] ?? '', 'ultra');
$text($ADMIN, '/promos');
T::check('/promos ro\'yxati', strpos($fake->lastText(), 'TEST30') !== false && strpos($fake->lastText(), '2/2') !== false && strpos($fake->lastText(), 'ULT7') !== false);
$text($ADMIN, '/promo test30');
T::check('/promo KOD: kim ishlatgani (escape bilan)', strpos($fake->lastText(), '@ali7001') !== false && strpos($fake->lastText(), '&lt;script&gt;') !== false);
$text($ADMIN, '/promo_del TEST30');
T::check('o\'chirish tasdiq so\'raydi', strpos($fake->lastText(), '/promo_del TEST30 ok') !== false && (int) $db->value("SELECT COUNT(*) FROM promo_codes WHERE code = 'TEST30'") === 1);
$text($ADMIN, '/promo_del TEST30 ok');
T::check('butunlay o\'chirildi, foydalanuvchi tarifi saqlandi', (int) $db->value("SELECT COUNT(*) FROM promo_codes WHERE code = 'TEST30'") === 0
    && (int) $db->value('SELECT COUNT(*) FROM promo_redemptions WHERE promo_id NOT IN (SELECT id FROM promo_codes)') === 0 && ($plan($U7)['plan_type'] ?? '') === 'pro');

// --- referal: do'st birinchi postini qilganda ball
$balance0 = (int) ($plan($U)['ai_credits'] ?? 0);
$text($U2, '/newpost');
$send($U2, ['text' => 'Do\'stning birinchi posti']);
$press($U2, 'p:now');
T::eq('do\'st birinchi post qildi: taklif qiluvchiga +3', (int) ($plan($U)['ai_credits'] ?? 0), $balance0 + 3);
T::check('taklif qiluvchiga xabar (o\'z tilida, ism escape)', strpos($fake->texts(), '+3') !== false && strpos($fake->texts(), 'Ali&lt;script&gt;') !== false);
$text($U2, '/newpost');
$send($U2, ['text' => 'Ikkinchi post']);
$press($U2, 'p:now');
T::eq('ikkinchi post: qayta ball yo\'q', (int) ($plan($U)['ai_credits'] ?? 0), $balance0 + 3);
foreach ([8001, 8002, 8003] as $fr) {
    $text($fr, '/start ref_' . $U);
}
$res = array_map(static function ($fr) use ($app) {
    return $app->afterPostSaved($fr)['reward'] ?? null;
}, [8001, 8002, 8003]);
T::eq('2-, 3-do\'st +3, 4-do\'st +1', $res, [3, 3, 1]);
T::eq('balans: +3+3+3+1', (int) ($plan($U)['ai_credits'] ?? 0), $balance0 + 10);
T::eq('ballar tarixi (ledger) yozildi', (int) $db->value("SELECT COALESCE(SUM(amount), 0) FROM credits_ledger WHERE user_id = ? AND operation_type = 'referral'", [$U]), 10);
T::eq('taklifsiz foydalanuvchiga mukofot yo\'q', $app->afterPostSaved(5004), null);
$press($U, 'ref:show');
T::check('taklif ekrani: havola, sonlar, ulashish', strpos($fake->lastText(), 'start=ref_' . $U) !== false && strpos($fake->lastText(), 'Taklif qilinganlar: <b>4</b>') !== false
    && strpos($mk($fake->of('sendMessage')[0] ?? []), 't.me\/share\/url') !== false);

// --- manba havolalari
$text($U, '/links');
T::check('oddiy foydalanuvchiga /links yo\'q', strpos($fake->lastText(), 'Tushunmadim') !== false);
$text($ADMIN, '/link_new A Nom');
T::check('yaroqsiz kod', strpos($fake->lastText(), '2–24') !== false);
$text($ADMIN, '/link_new kanal1 @nobody123 Nom');
T::check('noma\'lum egasi', strpos($fake->lastText(), 'Egasi botda topilmadi') !== false);
$text($ADMIN, '/link_new Kanal-1 @ali' . $U . ' Kanal <b>reklamasi</b>');
T::check('havola yaratildi (egasi bilan, nom escape)', strpos($fake->lastText(), 'start=s_kanal_1') !== false && strpos($fake->lastText(), '&lt;b&gt;') !== false
    && (int) $db->value("SELECT owner_id FROM tracked_links WHERE code = 'kanal_1'") === $U);
$text($ADMIN, '/link_new kanal_1 Takror');
T::check('takror kod', strpos($fake->lastText(), 'allaqachon bor') !== false);
$text($ADMIN, '/link_new insta Instagram story');
$text(9001, '/start s_kanal_1');
T::eq('yangi foydalanuvchi: havola egasining taklifi', (int) ($app->users->get(9001)['referrer_id'] ?? 0), $U);
$text(9001, '/start s_kanal_1');
$text(9001, '/start s_insta');
$text($U2, '/start s_kanal_1');
$l = $app->links->get('kanal_1');
T::eq('havola: 3 bosish, 2 tashrif, 1 yangi', [(int) $l['clicks'], (int) $l['visitors'], (int) $l['new_users']], [3, 2, 1]);
T::eq('birinchi tegish: ikkinchi havolada yangi emas', (int) $app->links->get('insta')['new_users'], 0);
T::eq('eski foydalanuvchining taklif qiluvchisi o\'zgarmaydi', (int) ($app->users->get($U2)['referrer_id'] ?? 0), $U);
$app->afterPostSaved(9001);
$l = $app->links->get('kanal_1');
T::eq('birinchi post belgisi (va havola egasiga ball)', [(int) $l['posted'], (int) ($plan($U)['ai_credits'] ?? 0)], [1, $balance0 + 11]);
$db->exec("INSERT INTO payments (user_id, amount, currency, payload, charge_id, plan_key, tier, days, created_at) VALUES (9001, 195, 'XTR', 'p', 'ch_9001', '1m', 'pro', 30, UTC_TIMESTAMP())");
T::eq('to\'lagan soni', (int) $app->links->get('kanal_1')['paid'], 1);
$text($ADMIN, '/links');
T::check('/links: sonlar', strpos($fake->lastText(), 'kanal_1') !== false && strpos($fake->lastText(), '👆3') !== false && strpos($fake->lastText(), '💎1') !== false);
$text($ADMIN, '/link kanal_1');
T::check('/link KOD: kimlar kelgani', strpos($fake->lastText(), '<code>9001</code>') !== false && strpos($fake->lastText(), 'Bosishlar: <b>3</b>') !== false);
$text($ADMIN, '/link_user 9001');
T::check('/link_user: qayerdan kelgan', strpos($fake->lastText(), 'kanal_1') !== false && strpos($fake->lastText(), 'insta') !== false);
$text($U, '/mylinks');
T::check('/mylinks: egasi sonlarni ko\'radi, ismlarsiz', strpos($fake->lastText(), 'kanal_1') !== false && strpos($fake->lastText(), '9001') === false);
$text($ADMIN, '/link_off kanal_1');
$text(9002, '/start s_kanal_1');
T::check('o\'chiq havola: taklif va tashrif yozilmaydi', ($app->users->get(9002)['referrer_id'] ?? null) === null && (int) $app->links->get('kanal_1')['clicks'] === 3);

// --- admin panel va yordam
$text($ADMIN, '/admin');
T::check('admin panel: PRO/ULTRA va Stars', strpos($fake->lastText(), 'ULTRA: <b>') !== false && strpos($fake->lastText(), '⭐') !== false);
$text($ADMIN, '/admin_help');
T::check('/admin_help', strpos($fake->lastText(), '/link_new') !== false && strpos($fake->lastText(), '/create_promo') !== false);
$text($U, '/admin_help');
T::check('oddiy foydalanuvchiga /admin_help yo\'q', strpos($fake->lastText(), 'Tushunmadim') !== false);
