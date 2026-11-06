<?php
// Tugmalar tartibi, Sozlamalar markazi va to'lov oqimining oxirigacha borishi (LookTest.php dan keyin).
declare(strict_types=1);

use PostAssist\App;
use PostAssist\Config;
use PostAssist\Keyboards;
use PostAssist\Repo\Payments;
use PostAssist\Router;
use PostAssist\Telegram;

T::section('AO. Tartibli tugmalar, Sozlamalar va to\'lov oqimi');

// --- grid: 2 tadan, toq qolganiga bitta tugmali dum qo'shiladi
$g = Keyboards::grid([['a'], ['b'], ['c']], [['x']]);
T::eq('grid: [a b] [c x]', array_map('count', $g), [2, 2]);
$g = Keyboards::grid([['a'], ['b']], [['x']]);
T::eq('grid: juft bo\'lsa dum alohida qatorda', array_map('count', $g), [2, 1]);
$g = Keyboards::grid([['a']], [['x'], ['y']]);
T::eq('grid: ikki tugmali dum qo\'shilmaydi', array_map('count', $g), [1, 2]);

// --- bosh menyu: hech qaysi qator 2 dan ko'p emas, yolg'iz qator faqat oxirida
$rowsOk = static function (array $rows): bool {
    $n = count($rows);
    foreach ($rows as $i => $r) {
        if (count($r) > 2 || (count($r) === 1 && $i < $n - 1)) {
            return false;
        }
    }
    return true;
};
foreach ([[false, false, null], [true, true, 'https://x.uz/app.php'], [true, false, 'https://x.uz/app.php'], [false, true, null]] as [$adm, $ai, $url]) {
    T::check('bosh menyu tartibli (admin=' . (int) $adm . ', ai=' . (int) $ai . ', app=' . (int) ($url !== null) . ')', $rowsOk(Keyboards::main('uz', $adm, $ai, $url)['keyboard']));
}
$more = Keyboards::more('uz', ['type' => 'text', 'text' => 'Salom'], false, true, [2, 1]);
$lastRow = end($more['inline_keyboard']);
T::check('«Qo\'shimcha»: har qatorda 2 tadan, oxirida «Orqaga»', $rowsOk($more['inline_keyboard']) && end($lastRow)['callback_data'] === 'p:back');
$cbs = [];
foreach ($more['inline_keyboard'] as $r) {
    foreach ($r as $b) {
        $cbs[] = $b['callback_data'];
    }
}
T::check('«Qo\'shimcha»: hamma amal joyida', !array_diff(['p:btn', 'p:rx', 'p:hidden', 'p:o_comments', 'p:rep', 'p:ad', 'p:o_silent', 'p:o_nopreview', 'p:o_pin', 'p:o_protect', 'p:mc', 'p:ai', 'p:tsave'], $cbs));
$moreAlbum = Keyboards::more('uz', ['type' => 'album'], true);
T::check('«Qo\'shimcha» albomda: tugma/reaksiya yo\'q, tartibli', $rowsOk($moreAlbum['inline_keyboard']) && strpos(json_encode($moreAlbum), 'p:btn') === false);
$pv = Keyboards::previewRows('uz', true, 'https://x.uz/app.php');
T::check('preview: [AI qayta][Mini App] va [Bekor] tartibli', count($pv) === 4 && count($pv[2]) === 2 && $pv[3][0]['callback_data'] === 'p:cancel');

// --- alohida ilova: karta + Payme + AI
$cfgU = new Config(['bot_token' => $config->str('bot_token'), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN], 'timezone' => 'Asia/Tashkent',
    'card_number' => '8600 1111 2222 3333', 'card_holder' => 'ALI', 'gemini_api_key' => 'test', 'webhook_url' => 'https://ex.uz/webhook.php']);
$appU = new App($cfgU, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$appU->sleeper = static function (int $ms): void {
};
$routerU = new Router($appU);
$textU = static function (int $uid, string $t) use (&$upd, $routerU, $from, $fake) {
    $fake->reset();
    $routerU->handle(['update_id' => $upd++, 'message' => ['message_id' => $upd, 'from' => $from($uid), 'chat' => ['id' => $uid, 'type' => 'private'], 'date' => 0, 'text' => $t]]);
};
$sendU = static function (int $uid, array $extra) use (&$upd, $routerU, $from, $fake) {
    $fake->reset();
    $routerU->handle(['update_id' => $upd++, 'message' => array_merge(['message_id' => $upd, 'from' => $from($uid), 'chat' => ['id' => $uid, 'type' => 'private'], 'date' => 0], $extra)]);
};
$pressU = static function (int $uid, string $data) use (&$upd, $routerU, $from, $fake) {
    $fake->reset();
    $routerU->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'u' . $upd, 'from' => $from($uid), 'data' => $data,
        'message' => ['message_id' => 77, 'chat' => ['id' => $uid, 'type' => 'private'], 'text' => 'eski']]]);
};
$lastKb = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$X = 7701;
$textU($X, '/start');
$textU($X, '⚙️ Sozlamalar');
T::check('yangi qisqa yorliq «⚙️ Sozlamalar» ishlaydi', strpos($fake->lastText(), 'ID <code>') !== false);
$textU($X, '⚙️ Sozlamalar / Ko\'proq');
T::check('eski yorliq ham taniladi', strpos($fake->lastText(), 'ID <code>') !== false);
$st = $fake->lastText();
T::check('Sozlamalar: profil kartasi (ism, ID, tarif, kanallar, AI qoldig\'i, ball, til, mintaqa)', strpos($st, 'ID <code>' . $X . '</code>') !== false
    && strpos($st, 'Tarif: <b>FREE</b>') !== false && strpos($st, 'Kanallar: <b>0/') !== false && strpos($st, 'AI (bugun qoldi): <b>5/5</b>') !== false
    && strpos($st, 'Ball:') !== false && strpos($st, 'Asia/Tashkent') !== false);
$kb = $lastKb();
T::check('Sozlamalar: FREE da «💎 PRO olish», guruhlangan tugmalar, Mini App', strpos($kb, 'PRO olish') !== false && strpos($kb, 'set:tz') !== false
    && strpos($kb, 'set:team') !== false && strpos($kb, 'ref:show') !== false && strpos($kb, 'web_app') !== false && strpos($kb, 'm:home') !== false);
$s = json_decode($kb, true)['inline_keyboard'] ?? [];
T::check('Sozlamalar: 2 ustunli, navigatsiya oxirida', $rowsOk($s) && end($s)[0]['callback_data'] === 'm:home');

// --- so'mda to'lov: tasdiqsiz muddat/karta tugmasini chetlab o'tib bo'lmaydi
$pressU($X, 'pl:ct:pro');
T::check('tasdiqsiz pl:ct -> raqam so\'raladi', ($appU->states->get($X)['state'] ?? '') === 'uz_verify' && strpos($mk($fake->of('sendMessage')[0] ?? []), 'request_contact') !== false);
$pressU($X, 'pl:cb:1m');
T::check('tasdiqsiz pl:cb -> chek kutilmaydi, karta raqami ko\'rsatilmaydi', ($appU->states->get($X)['state'] ?? '') !== 'receipt_wait'
    && strpos($fake->texts(), '8600 1111') === false);
$sendU($X, ['contact' => ['phone_number' => '+998901112233', 'user_id' => $X, 'first_name' => 'A']]);
$pressU($X, 'pl:ct:pro');
$per = json_decode($lastKb(), true)['inline_keyboard'] ?? [];
T::check('tasdiqlangach: muddatlar 2×2 + navigatsiya', count($per) === 3 && count($per[0]) === 2 && count($per[1]) === 2 && $per[0][0]['callback_data'] === 'pl:cb:1m');
$pressU($X, 'pl:t:ultra');
$per = json_decode($lastKb(), true)['inline_keyboard'] ?? [];
T::check('Stars muddatlari ham 2×2, orqaga va menyu', count($per) === 3 && count($per[1]) === 2 && $per[2][0]['callback_data'] === 'pl:show' && $per[2][1]['callback_data'] === 'm:home');

// --- Stars to'lovi muvaffaqiyatli: imkoniyatlar va keyingi qadam
$sendU($X, ['successful_payment' => ['currency' => 'XTR', 'total_amount' => 195, 'invoice_payload' => Payments::payload('1m', $X), 'telegram_payment_charge_id' => 'ux-ch-1']]);
$ok = $fake->of('sendMessage')[0] ?? [];
T::check('to\'lovdan keyin: «Endi sizda» va [Yangi post][Tarifim][Menyu]', strpos((string) ($ok['text'] ?? ''), 'Endi sizda') !== false
    && strpos($mk($ok), 'p:new') !== false && strpos($mk($ok), 'pl:show') !== false && strpos($mk($ok), 'm:home') !== false);
$textU($X, '/plans');
$kb = $lastKb();
T::check('PRO egasida: «PRO uzaytirish» va «ULTRA ga o\'tish»', strpos($kb, 'PRO uzaytirish') !== false && strpos($kb, "ULTRA ga o'tish") !== false);
$pressU($X, 'set:show');
T::check('Sozlamalarda PRO: «💎 Tarifim» va tugash sanasi', strpos($lastKb(), 'Tarifim') !== false && strpos($fake->lastText(), 'gacha') !== false
    && strpos($fake->lastText(), 'AI (bugun qoldi): <b>40/40</b>') !== false);

// --- karta cheki tasdiqlanganda ham keyingi qadam tugmalari
$Y = 7702;
$textU($Y, '/start');
$pressU($Y, 'pl:card');
$sendU($Y, ['contact' => ['phone_number' => '+998901112244', 'user_id' => $Y, 'first_name' => 'B']]);
$pressU($Y, 'pl:cb:1m');
$sendU($Y, ['photo' => [['file_id' => 'RC1', 'file_unique_id' => 'rc1', 'width' => 10, 'height' => 10]]]);
$rid = (int) $db->value('SELECT MAX(id) FROM payment_receipts WHERE user_id = ?', [$Y]);
$pressU($ADMIN, 'rc:ok:' . $rid);
$msg = null;
foreach ($fake->of('sendMessage') as $p) {
    if ((int) $p['chat_id'] === $Y) {
        $msg = $p;
    }
}
T::check('chek tasdiqlandi: foydalanuvchiga imkoniyatlar va [Yangi post][Tarifim]', $msg !== null && strpos((string) $msg['text'], 'Endi sizda') !== false
    && strpos($mk($msg), 'p:new') !== false);
$textU($ADMIN, '/admin');
$adm = json_decode($lastKb(), true)['inline_keyboard'] ?? [];
T::check('admin panel: 🧾 Cheklar, 2 ustunli', strpos(json_encode($adm), 'a:rc') !== false && $rowsOk($adm));
$pressU($ADMIN, 'a:rc');
T::check('admin «🧾 Cheklar» ishlaydi', $fake->of('sendMessage', 'editMessageText', 'sendPhoto', 'sendDocument') !== []);
foreach ([$X, $Y] as $id) {
    $appU->states->clear($id);
}

// --- pastki menyu: Mini App takrorlanmaydi, qisqa «⚙️ Sozlamalar» (2 qatorga sinmaydi)
$mainKb = json_encode(Keyboards::main('uz', true, false, 'https://x.uz/app.php'), JSON_UNESCAPED_UNICODE);
T::check('pastki menyu: Mini App yo\'q, «⚙️ Sozlamalar» qisqa', strpos($mainKb, 'web_app') === false && strpos($mainKb, '"⚙️ Sozlamalar"') !== false);
// --- Mini App premium qatlami va ixcham birja
$appSrcU = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: premium uslub qatlami, Telegram Premium belgisi, ixcham birja', strpos($appSrcU, 'id="ui-premium"') !== false
    && strpos($appSrcU, "setAttribute('data-tgp'") !== false && strpos($appSrcU, 'class="chips scroll" id="mk-cats"') !== false && strpos($appSrcU, 'class="mk-head"') !== false);
