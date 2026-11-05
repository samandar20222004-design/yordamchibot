<?php
// 5-bosqich integratsiya testi: karta to'lovi (chek), hammaga xabar, majburiy obuna (MiniAppTest.php dan keyin).
declare(strict_types=1);

use PostAssist\App;
use PostAssist\Config;
use PostAssist\Router;
use PostAssist\Services\Scheduler;
use PostAssist\Telegram;

T::section('P. Karta to\'lovi, hammaga xabar, majburiy obuna');
$clock = new DateTimeImmutable('2026-12-01 10:00:00', new DateTimeZone('UTC'));
$app->sleeper = static function (int $ms): void {
};
$cfg5 = new Config(['bot_token' => $config->str('bot_token'), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN], 'timezone' => 'Asia/Tashkent',
    'free_max_channels' => 2, 'free_max_queued' => 3, 'card_number' => '8600 1111 2222 3333', 'card_holder' => 'ALI <V>']);
$app5 = new App($cfg5, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$app5->sleeper = static function (int $ms): void {
};
$router5 = new Router($app5);
$text5 = static function (int $uid, string $t) use (&$upd, $router5, $from, $fake) {
    $fake->reset();
    $router5->handle(['update_id' => $upd++, 'message' => ['message_id' => $upd, 'from' => $from($uid), 'chat' => ['id' => $uid, 'type' => 'private'], 'date' => 0, 'text' => $t]]);
};
$send5 = static function (int $uid, array $extra) use (&$upd, $router5, $from, $fake) {
    $fake->reset();
    $router5->handle(['update_id' => $upd++, 'message' => array_merge(['message_id' => $upd, 'from' => $from($uid), 'chat' => ['id' => $uid, 'type' => 'private'], 'date' => 0], $extra)]);
};
$press5 = static function (int $uid, string $data, int $mid = 77) use (&$upd, $router5, $from, $fake) {
    $fake->reset();
    $router5->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'c' . $upd, 'from' => $from($uid), 'data' => $data,
        'message' => ['message_id' => $mid, 'chat' => ['id' => $uid, 'type' => 'private'], 'text' => 'eski']]]);
};
$kb5 = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$planOf = static function (int $uid) use ($db): array {
    return $db->one('SELECT plan_type, subscription_expires_at FROM users WHERE user_id = ?', [$uid]) ?? [];
};

// --- karta o'chiq (card_number yo'q)
$text($U2, '/start');
$press($U2, 'pl:show');
T::check('card_number yo\'q: tariflar ekranida «Karta» tugmasi yo\'q', strpos($mk($fake->of('editMessageText', 'sendMessage')[0] ?? []), 'pl:card') === false);
$press($U2, 'pl:card');
T::check('karta o\'chiq: aniq xabar', strpos($fake->lastText(), 'yoqilmagan') !== false);

// --- UZ tasdig'i
$C = 9100;
$text5($C, '/start');
$press5($C, 'pl:show');
T::check('card_number bor: «Karta» tugmasi', strpos($kb5(), 'pl:card') !== false);
$press5($C, 'pl:card');
$ask = $fake->of('sendMessage')[0] ?? [];
T::check('birinchi marta: kontakt so\'raladi (request_contact)', strpos($mk($ask), 'request_contact') !== false && ($app5->states->get($C)['state'] ?? '') === 'uz_verify');
$send5($C, ['contact' => ['phone_number' => '+998901112233', 'first_name' => 'Boshqa', 'user_id' => 424242]]);
T::check('boshqa odam kontakti rad', strpos($fake->lastText(), 'o\'zingizning') !== false && !$app5->users->isUzVerified($C));
$send5($C, ['contact' => ['phone_number' => '+14155550100', 'first_name' => 'A', 'user_id' => $C]]);
T::check('chet el raqami: so\'m yo\'q, Stars taklif; tasdiqlanmadi, raqam saqlanmadi', strpos($fake->lastText(), 'Stars') !== false && !$app5->users->isUzVerified($C)
    && $app5->states->get($C) === null);
$press5($C, 'pl:card');
$send5($C, ['contact' => ['phone_number' => '+998 90 111-22-33', 'first_name' => 'A', 'user_id' => $C]]);
T::check('O\'zbekiston raqami: tasdiqlandi, tarif tanlash ochildi', $app5->users->isUzVerified($C) && strpos($fake->texts(), 'Karta orqali to\'lov (so\'m)') !== false);
T::eq('raqam bazada saqlanmaydi', (int) $db->value("SELECT COUNT(*) FROM users WHERE user_id = ? AND (username LIKE '%998%' OR full_name LIKE '%998%')", [$C]), 0);
$press5($C, 'pl:card');
T::check('tasdiqlangan: qayta so\'ralmaydi', ($app5->states->get($C)['state'] ?? '') !== 'uz_verify' && strpos($kb5(), 'pl:ct:pro') !== false);

// --- tarif va muddat
$press5($C, 'pl:ct:pro');
T::check('PRO muddatlari so\'mda, tejam bilan', strpos($fake->lastText(), '29 000') !== false && strpos($fake->lastText(), '245 000') !== false && strpos($fake->lastText(), '30%') !== false
    && strpos($mk($fake->of('editMessageText')[0] ?? []), 'pl:cb:3m') !== false);
$press5($C, 'pl:ct:ultra');
T::check('ULTRA: 69 000 dan', strpos($fake->lastText(), '69 000') !== false && strpos($mk($fake->of('editMessageText')[0] ?? []), 'pl:cb:u1y') !== false);
$press5($C, 'pl:cb:3m');
T::check('rekvizitlar: summa 75 000, karta, egasi escape qilingan', strpos($fake->lastText(), '75 000') !== false && strpos($fake->lastText(), '<code>8600 1111 2222 3333</code>') !== false
    && strpos($fake->lastText(), 'ALI &lt;V&gt;') !== false && ($app5->states->get($C)['state'] ?? '') === 'receipt_wait');
T::eq('noto\'g\'ri kalit rad', (function () use ($press5, $C, $fake) {
    $press5($C, 'pl:cb:2m');
    return count($fake->of('editMessageText'));
})(), 0);
$press5($C, 'pl:cb:3m');

// --- chek yuborish
$text5($C, 'to\'ladim');
T::check('chek o\'rniga matn: rasm so\'raladi', strpos($fake->lastText(), 'rasm yoki PDF') !== false && ($app5->states->get($C)['state'] ?? '') === 'receipt_wait');
$send5($C, ['document' => ['file_id' => 'DOC1', 'file_unique_id' => 'U1', 'mime_type' => 'application/zip', 'file_size' => 100]]);
T::check('zip fayl chek bo\'la olmaydi', strpos($fake->lastText(), 'rasm yoki PDF') !== false);
$send5($C, ['document' => ['file_id' => 'DOC2', 'file_unique_id' => 'U2', 'mime_type' => 'application/pdf', 'file_size' => 99999999]]);
T::check('juda katta PDF rad', strpos($fake->lastText(), 'rasm yoki PDF') !== false);
$send5($C, ['photo' => [['file_id' => 'ph_s', 'file_unique_id' => 'US'], ['file_id' => 'ph_big', 'file_unique_id' => 'UBIG']]]);
$adm = $fake->of('sendPhoto')[0] ?? [];
T::check('chek adminga: rasm, izoh (ism escape), ✅/❌ tugmalari', (int) ($adm['chat_id'] ?? 0) === $ADMIN && ($adm['photo'] ?? '') === 'ph_big'
    && strpos((string) $adm['caption'], '75 000') !== false && strpos((string) $adm['caption'], 'Ali&lt;script&gt;') !== false
    && strpos($mk($adm), 'rc:ok:') !== false && strpos($mk($adm), 'rc:no:') !== false);
T::check('foydalanuvchiga «qabul qilindi», holat tozalandi', strpos($fake->texts(), 'qabul qilindi') !== false && $app5->states->get($C) === null);
$rid = (int) $db->value('SELECT id FROM payment_receipts ORDER BY id DESC LIMIT 1');
T::eq('chek bazada: pending, 90 kun, 75 000', $db->one('SELECT status, days, amount_uzs, tier FROM payment_receipts WHERE id = ?', [$rid]), ['status' => 'pending', 'days' => 90, 'amount_uzs' => 75000, 'tier' => 'pro']);
$text($ADMIN, '/receipts');
T::check('/receipts: kutayotgan chek admin xabarsiz ham topiladi', count($fake->of('sendPhoto')) === 1);
// takror fayl
$press5($C, 'pl:cb:1m');
$send5($C, ['photo' => [['file_id' => 'ph_big2', 'file_unique_id' => 'UBIG']]]);
T::check('bir xil fayl: adminga ogohlantirish', strpos((string) ($fake->of('sendPhoto')[0]['caption'] ?? ''), 'avval ham yuborilgan') !== false);
$press5($C, 'pl:cb:1m');
$send5($C, ['photo' => [['file_id' => 'ph3', 'file_unique_id' => 'U3']]]);
$press5($C, 'pl:cb:1m');
$fake->reset();
$send5($C, ['photo' => [['file_id' => 'ph4', 'file_unique_id' => 'U4']]]);
T::check('3 tadan ortiq kutayotgan chek: rad', strpos($fake->lastText(), '3 ta') !== false && count($fake->of('sendPhoto')) === 0);
$app5->states->clear($C);

// --- admin qarori
$press5($C, 'rc:ok:' . $rid);
T::eq('oddiy foydalanuvchi chekni tasdiqlay olmaydi', $db->value('SELECT status FROM payment_receipts WHERE id = ?', [$rid]), 'pending');
$press5($ADMIN, 'rc:ok:' . $rid, 88);
T::eq('tasdiq: PRO 90 kun (hozirdan)', [$planOf($C)['plan_type'] ?? '', $planOf($C)['subscription_expires_at'] ?? ''], ['pro', '2027-03-01 10:00:00']);
$toUser = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($C) {
    return (int) $m['chat_id'] === $C;
}));
T::check('foydalanuvchiga «To\'lov qabul qilindi» (o\'z mintaqasida sana)', $toUser && strpos((string) $toUser[0]['text'], 'To\'lov qabul qilindi') !== false && strpos((string) $toUser[0]['text'], '01.03.2027') !== false);
T::check('admin tugmalari olib tashlandi, natija xabari', count($fake->of('editMessageReplyMarkup')) === 1 && strpos($fake->texts(), 'tasdiqlandi') !== false);
T::eq('to\'lov yozuvi: karta, UZS, bir marta', $db->one("SELECT provider, currency, amount, charge_id FROM payments WHERE charge_id = ?", ['card_' . $rid]),
    ['provider' => 'card', 'currency' => 'UZS', 'amount' => 75000, 'charge_id' => 'card_' . $rid]);
$press5($ADMIN, 'rc:ok:' . $rid, 88);
T::check('ikkinchi bosish: allaqachon, tarif qayta berilmaydi', strpos($fake->lastText(), 'allaqachon') !== false && ($planOf($C)['subscription_expires_at'] ?? '') === '2027-03-01 10:00:00'
    && (int) $db->value("SELECT COUNT(*) FROM payments WHERE charge_id = ?", ['card_' . $rid]) === 1);
$press5($ADMIN, 'rc:no:' . $rid, 88);
T::eq('tasdiqlangan chekni keyin rad etib bo\'lmaydi', $db->value('SELECT status FROM payment_receipts WHERE id = ?', [$rid]), 'approved');
T::check('tasdiqlangan mijoz: karta bilan to\'laganlar qayta tasdiqlanmaydi', $app5->receipts->hasPaid($C));
$rid2 = (int) $db->value("SELECT id FROM payment_receipts WHERE status = 'pending' ORDER BY id LIMIT 1");
$press5($ADMIN, 'rc:no:' . $rid2, 89);
$toUser = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($C) {
    return (int) $m['chat_id'] === $C;
}));
T::check('rad etish: foydalanuvchiga sabab, tarif o\'zgarmadi', $db->value('SELECT status FROM payment_receipts WHERE id = ?', [$rid2]) === 'rejected'
    && $toUser && strpos((string) $toUser[0]['text'], 'rad etildi') !== false && ($planOf($C)['subscription_expires_at'] ?? '') === '2027-03-01 10:00:00');
$press5($ADMIN, 'rc:ok:999999', 90);
T::check('mavjud bo\'lmagan chek', strpos($fake->lastText(), 'topilmadi') !== false);
$db->exec("DELETE FROM users WHERE user_id = 9101");
$db->exec("INSERT INTO payment_receipts (user_id, plan_key, tier, days, amount_uzs, media_type, file_id, created_at) VALUES (9101, '1m', 'pro', 30, 29000, 'photo', 'x', UTC_TIMESTAMP())");
$ghost = (int) $db->lastId();
$press5($ADMIN, 'rc:ok:' . $ghost, 91);
T::check('foydalanuvchi yo\'q: tarif berilmaydi, chek kutishda qoladi', $db->value('SELECT status FROM payment_receipts WHERE id = ?', [$ghost]) === 'pending' && strpos($fake->lastText(), 'topilmadi') !== false
    && (int) $db->value("SELECT COUNT(*) FROM payments WHERE charge_id = ?", ['card_' . $ghost]) === 0);
$db->exec('DELETE FROM payment_receipts WHERE id = ?', [$ghost]);
$text($ADMIN, '/admin');
T::check('admin panel: karta bo\'yicha bugungi tushum', strpos($fake->lastText(), '75 000') !== false);

// --- hammaga xabar
$text($U, '/broadcast');
T::check('oddiy foydalanuvchiga /broadcast yo\'q', strpos($fake->lastText(), 'Tushunmadim') !== false);
$db->exec('UPDATE users SET is_blocked = 0');
$audience = (int) $db->value('SELECT COUNT(*) FROM users WHERE is_blocked = 0');
$text5($ADMIN, '/broadcast');
T::check('/broadcast: auditoriya soni va so\'rov', ($app5->states->get($ADMIN)['state'] ?? '') === 'bc_wait' && strpos($fake->lastText(), '<b>' . $audience . '</b>') !== false);
$text5($ADMIN, 'Yangi imkoniyat: AI!');
T::check('xabar adminga ko\'rsatiladi (copyMessage) va tasdiq so\'raladi', count($fake->of('copyMessage')) === 1 && (int) $fake->of('copyMessage')[0]['chat_id'] === $ADMIN
    && strpos($kb5(), 'bc:go') !== false && ($app5->states->get($ADMIN)['state'] ?? '') === 'bc_confirm');
$press5($U, 'bc:go');
T::eq('oddiy foydalanuvchi yubora olmaydi', (int) $db->value('SELECT COUNT(*) FROM broadcasts'), 0);
$press5($ADMIN, 'bc:go');
$bid = (int) $db->value('SELECT id FROM broadcasts ORDER BY id DESC LIMIT 1');
T::check('yuborish boshlandi', $bid > 0 && (int) $db->value('SELECT total FROM broadcasts WHERE id = ?', [$bid]) === $audience && strpos($fake->lastText(), 'boshlandi') !== false);
$press5($ADMIN, 'bc:go');
T::eq('ikkinchi bosish: ikki marta boshlanmaydi', (int) $db->value('SELECT COUNT(*) FROM broadcasts'), 1);
$text5($ADMIN, '/broadcast');
$text5($ADMIN, 'Boshqa xabar');
$press5($ADMIN, 'bc:go');
T::check('boshqasi ishlayotganda: band', strpos($fake->lastText(), 'tugamagan') !== false && (int) $db->value('SELECT COUNT(*) FROM broadcasts') === 1);
$app5->states->clear($ADMIN);
$sched5 = new Scheduler($app5, static function (int $us): void {
});
// 403 va 429
$victim = (int) $db->value('SELECT user_id FROM users WHERE user_id <> ? ORDER BY user_id LIMIT 1', [$ADMIN]);
$fake->reset();
$fake->forced['copyMessage'] = [['ok' => false, 'error_code' => 403, 'description' => 'Forbidden: bot was blocked by the user'], ['ok' => true, 'result' => ['message_id' => 1]], ['ok' => false, 'error_code' => 429, 'description' => 'Too Many Requests', 'parameters' => ['retry_after' => 5]]];
$sched5->run(5);
$b = $db->one('SELECT * FROM broadcasts WHERE id = ?', [$bid]);
T::check('403: foydalanuvchi bloklangan deb belgilandi, 429: to\'xtadi (kursor oldinga siljimadi)', (int) $b['blocked'] === 1 && (int) $b['sent'] === 1 && $b['status'] === 'running'
    && (int) $db->value('SELECT is_blocked FROM users WHERE user_id = ?', [(int) ($db->value('SELECT user_id FROM users WHERE is_blocked = 1 ORDER BY user_id LIMIT 1'))]) === 1);
$cursor1 = (int) $b['last_user_id'];
$fake->reset();
$sched5->run(5);
$b = $db->one('SELECT * FROM broadcasts WHERE id = ?', [$bid]);
$copied = array_column($fake->of('copyMessage'), 'chat_id');
T::check('keyingi cron davom ettirdi: hamma foydalanuvchiga BIR martadan, tugadi', $b['status'] === 'done' && (int) $b['sent'] + (int) $b['blocked'] + (int) $b['failed'] === $audience
    && count($copied) === count(array_unique($copied)));
T::eq('hisob: yuborilgan + bloklagan = auditoriya', (int) $b['sent'] + (int) $b['blocked'] + (int) $b['failed'], $audience);
T::check('admin tugash haqida xabar oldi', strpos($fake->texts(), 'tugadi') !== false);
$fake->reset();
$sched5->run(5);
T::eq('tugagan yuborish qayta ishlamaydi', count($fake->of('copyMessage')), 0);
$text5($ADMIN, '/broadcast_status');
T::check('/broadcast_status', strpos($fake->lastText(), '#' . $bid) !== false && strpos($fake->lastText(), 'tugadi') !== false);
$text5($ADMIN, '/broadcast');
$text5($ADMIN, 'To\'xtatiladigan');
$press5($ADMIN, 'bc:go');
$text5($ADMIN, '/broadcast_stop');
T::check('/broadcast_stop', strpos($fake->lastText(), 'to\'xtatildi') !== false && $db->value("SELECT status FROM broadcasts ORDER BY id DESC LIMIT 1") === 'stopped');
$text5($ADMIN, '/broadcast');
$text5($ADMIN, 'Manba o\'chadi');
$press5($ADMIN, 'bc:go');
$fake->reset();
$fake->forced['copyMessage'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: message to copy not found']];
$sched5->run(5);
T::check('admin xabarni o\'chirsa: yuborish to\'xtaydi va adminga aytiladi', $db->value("SELECT status FROM broadcasts ORDER BY id DESC LIMIT 1") === 'stopped' && strpos($fake->texts(), 'o\'chirilgan') !== false);
$db->exec('UPDATE users SET is_blocked = 0');

// --- majburiy obuna
$FC1 = -1007770000001;
$fake->chats['@majburiy'] = ['id' => $FC1, 'type' => 'channel', 'title' => 'Majburiy <kanal>', 'username' => 'majburiy'];
$text5($ADMIN, '/force_add @majburiy');
T::check('bot kanalda admin emas: rad', strpos($fake->lastText(), 'admin emas') !== false && count($app5->forced->active()) === 0);
$fake->members["{$FC1}|{$BOT}"] = ['status' => 'administrator'];
$fake->chats['@guruhcha'] = ['id' => -100555, 'type' => 'supergroup', 'title' => 'G'];
$text5($ADMIN, '/force_add @guruhcha');
T::check('guruh kanal emas: rad', strpos($fake->lastText(), 'topilmadi') !== false);
$text($U, '/force_add @majburiy');
T::eq('oddiy foydalanuvchi qo\'sha olmaydi', count($app5->forced->active()), 0);
$text5($ADMIN, '/force_add @majburiy');
T::check('qo\'shildi (nom escape)', count($app5->forced->active()) === 1 && strpos($fake->lastText(), 'Majburiy &lt;kanal&gt;') !== false);
$text5($ADMIN, '/force_add @majburiy');
T::check('takror qo\'shib bo\'lmaydi', strpos($fake->lastText(), 'allaqachon') !== false);
$text5($ADMIN, '/force_list');
T::check('/force_list', strpos($fake->lastText(), 'Majburiy &lt;kanal&gt;') !== false && strpos($fake->lastText(), '@majburiy') !== false);

$G = 9200;
$fake->members["{$FC1}|{$G}"] = ['status' => 'left'];
$text5($G, '/start');
$kb = $kb5();
T::check('a\'zo bo\'lmagan: obuna ekrani (kanal havolasi + Tekshirish), menyu yo\'q', strpos($fake->lastText(), 'obuna bo\'ling') !== false && strpos($kb, 't.me\/majburiy') !== false
    && strpos($kb, 'fs:check') !== false && strpos($kb, '"keyboard"') === false && $app5->users->get($G) !== null);
$text5($G, '✍️ Post yaratish');
T::check('boshqa xabarlar ham to\'siladi', strpos($fake->lastText(), 'obuna bo\'ling') !== false && $app5->states->get($G) === null);
$press5($G, 'pl:show');
T::check('tugmalar ham to\'siladi', strpos($fake->texts(), 'obuna bo\'ling') !== false && strpos($fake->texts(), 'Tarifingiz') === false);
$press5($G, 'fs:check');
T::check('hali a\'zo emas: «Hali hamma kanalga…»', strpos($fake->lastText(), 'Hali hamma') !== false);
$fake->members["{$FC1}|{$G}"] = ['status' => 'member'];
$press5($G, 'fs:check');
T::check('a\'zo bo\'ldi: rahmat va bosh menyu', strpos($fake->lastText(), 'Rahmat') !== false && isset($fake->of('sendMessage')[0]['reply_markup']));
$fake->members["{$FC1}|{$G}"] = ['status' => 'left'];
$text5($G, '/start');
T::check('10 daqiqa ichida qayta tekshirilmaydi (kesh)', strpos($fake->lastText(), 'Kerakli bo\'limni') !== false);
$clock = $clock->modify('+11 minutes');
$text5($G, '/start');
T::check('kesh tugagach yana tekshiriladi', strpos($fake->lastText(), 'obuna bo\'ling') !== false);
$text5($ADMIN, '/start');
T::check('admin majburiy obunadan mustasno', strpos($fake->lastText(), 'Kerakli bo\'limni') !== false);
$text5(9201, '/start');
T::check('Telegram javob bermasa (a\'zolik noma\'lum): foydalanuvchi o\'tkaziladi (botni yopib qo\'ymaydi)', strpos($fake->lastText(), 'obuna bo\'ling') === false);
$fake->members["{$FC1}|9202"] = ['status' => 'restricted', 'is_member' => true];
$text5(9202, '/start');
T::check('cheklangan, lekin a\'zo: o\'tadi', strpos($fake->lastText(), 'obuna bo\'ling') === false);
// referal darvozadan oldin yoziladi
$text5(9203, '/start ref_' . $C);
$fake->members["{$FC1}|9203"] = ['status' => 'kicked'];
$app5->forced->resetCache();
$text5(9203, '/start');
T::check('chiqarib yuborilgan: to\'siladi', strpos($fake->lastText(), 'obuna bo\'ling') !== false);
T::eq('referal darvozadan oldin saqlangan', (int) ($app5->users->get(9203)['referrer_id'] ?? 0), $C);
// private kanal: havola
$FC2 = -1007770000002;
$fake->chats[$FC2] = ['id' => $FC2, 'type' => 'channel', 'title' => 'Yopiq kanal'];
$fake->members["{$FC2}|{$BOT}"] = ['status' => 'administrator'];
$fake->forced['exportChatInviteLink'] = [['ok' => true, 'result' => 'https://t.me/+AbCdEf']];
$text5($ADMIN, '/force_add ' . $FC2);
$fake->members["{$FC2}|9203"] = ['status' => 'left'];
$text5(9203, '/start');
T::check('yopiq kanal: taklif havolasi tugmada', strpos($kb5(), 'AbCdEf') !== false);
$fid = (int) $db->value('SELECT id FROM forced_channels WHERE chat_id = ?', [$FC2]);
$text5($ADMIN, '/force_del ' . $fid);
T::check('/force_del', strpos($fake->lastText(), 'olib tashlandi') !== false && count($app5->forced->active()) === 1);
$fid1 = (int) $db->value('SELECT id FROM forced_channels WHERE chat_id = ?', [$FC1]);
$text5($ADMIN, '/force_del ' . $fid1);
$text5(9203, '/start');
T::check('hammasi olib tashlansa: to\'siq yo\'q', strpos($fake->lastText(), 'obuna bo\'ling') === false && count($app5->forced->active()) === 0);
$text5($ADMIN, '/admin_help');
T::check('/admin_help: yangi buyruqlar', strpos($fake->lastText(), '/broadcast') !== false && strpos($fake->lastText(), '/force_add') !== false && strpos($fake->lastText(), '/receipts') !== false);
$text5($ADMIN, '/admin');
T::check('admin panelda «Xabar yuborish» va «Majburiy obuna» tugmalari', strpos($kb5(), 'a:bc') !== false && strpos($kb5(), 'a:fs') !== false);
$press5($ADMIN, 'a:fs');
T::check('a:fs tugmasi', strpos($fake->lastText(), 'Majburiy obuna yo\'q') !== false);
$press5($ADMIN, 'a:bc');
T::eq('a:bc tugmasi: holat', $app5->states->get($ADMIN)['state'] ?? null, 'bc_wait');
$app5->states->clear($ADMIN);
