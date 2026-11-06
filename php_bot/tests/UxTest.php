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
T::check('Sozlamalar: FREE da «💎 PRO olish», guruhlangan tugmalar, Mini App tugmasi yo\'q', strpos($kb, 'PRO olish') !== false && strpos($kb, 'set:tz') !== false
    && strpos($kb, 'set:team') !== false && strpos($kb, 'ref:show') !== false && strpos($kb, 'web_app') === false && strpos($kb, 'm:home') !== false);
$s = json_decode($kb, true)['inline_keyboard'] ?? [];
T::check('Sozlamalar: 2 ustunli, oxirida [Yordam][Menyu]', $rowsOk($s) && end($s)[0]['callback_data'] === 'set:help' && end($s)[1]['callback_data'] === 'm:home');

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

// --- Mini App: tariflar va Stars to'lovi (createInvoiceLink)
$mkInitU = static function (array $user, int $authDate, string $tok) {
    $pairs = ['auth_date' => (string) $authDate, 'query_id' => 'AAH', 'user' => json_encode($user, JSON_UNESCAPED_UNICODE)];
    ksort($pairs);
    $lines = [];
    foreach ($pairs as $k => $v) {
        $lines[] = $k . '=' . $v;
    }
    $pairs['hash'] = hash_hmac('sha256', implode("\n", $lines), hash_hmac('sha256', $tok, 'WebAppData', true));
    return http_build_query($pairs);
};
$Z = 7703;
$initZ = $mkInitU(['id' => $Z, 'first_name' => 'Z', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
[$st, $pr] = PostAssist\Handlers\MiniAppApi::handle($appU, 'plans', [], $initZ);
$pro = $pr['tiers'][1] ?? [];
T::check('Mini App plans: 3 tarif, PRO 4 muddat (oylik … yillik), tejam va oylik narx', $st === 200 && count($pr['tiers']) === 3 && count($pro['periods'] ?? []) === 4
    && $pro['periods'][3]['key'] === '1y' && $pro['periods'][3]['save'] > 0 && $pro['periods'][3]['per_month'] < $pro['periods'][0]['stars'] && $pr['blocked'] === null && $pr['uzs'] === true);
$fake->reset();
$fake->forced['createInvoiceLink'] = [['ok' => true, 'result' => 'https://t.me/$abc123']];
[$st, $ir] = PostAssist\Handlers\MiniAppApi::handle($appU, 'invoice', ['key' => '1y'], $initZ);
$ci = $fake->of('createInvoiceLink')[0] ?? [];
T::check('Mini App invoice: Stars havolasi, to\'g\'ri summa va payload (bot bilan bir xil)', $st === 200 && ($ir['url'] ?? '') === 'https://t.me/$abc123'
    && ($ci['currency'] ?? '') === 'XTR' && ($ci['payload'] ?? '') === Payments::payload('1y', $Z) && strpos((string) ($ci['prices'] ?? ''), '1650') !== false);
T::eq('noto\'g\'ri kalit rad', PostAssist\Handlers\MiniAppApi::handle($appU, 'invoice', ['key' => '2y'], $initZ)[0], 400);
$initA = $mkInitU(['id' => $ADMIN, 'first_name' => 'A', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
T::check('admin (muddatsiz): sahifa ochiladi, sotib olish bloklangan', PostAssist\Handlers\MiniAppApi::handle($appU, 'plans', [], $initA)[1]['blocked'] === 'enterprise'
    && PostAssist\Handlers\MiniAppApi::handle($appU, 'invoice', ['key' => '1m'], $initA)[1]['error'] === 'enterprise');
[$st, $meZ] = PostAssist\Handlers\MiniAppApi::handle($appU, 'me', [], $initZ);
T::check('me: AI modellar ro\'yxati', ($meZ['ai']['models'][0]['name'] ?? '') === 'gemini' && $meZ['ai']['media'] === true);
T::check('app.php: tarif sahifasi va openInvoice', strpos($appSrcU, 'id="p-plans"') !== false && strpos($appSrcU, 'tg.openInvoice(r.url') !== false
    && strpos($appSrcU, "api('invoice'") !== false && strpos($appSrcU, 'requestFullscreen') !== false);

// --- Mini App ko'prigi: botdagi ekranlar Mini App ichida (xabar chatga ketmaydi, ekran sifatida qaytadi)
$B = 7710;
$initB = $mkInitU(['id' => $B, 'first_name' => 'B', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
$br = static function (array $in) use ($appU, $initB, $fake): array {
    $fake->reset();
    return PostAssist\Handlers\MiniAppApi::handle($appU, 'bridge', $in, $initB);
};
[$st, $r] = $br(['d' => 'ap:show']);
T::check('ko\'prik: autopilot ekrani Mini App\'ga qaytdi (matn + tugmalar), chatga xabar ketmadi', $st === 200 && !empty($r['screens']) && strpos($r['screens'][0]['text'], 'AI') !== false
    && !empty($r['screens'][0]['rows']) && $fake->of('sendMessage') === [] && $fake->of('editMessageText') === []);
T::check('ko\'prik: haqiqiy Telegram mijozi tiklandi', $appU->tg !== null);
[$st, $r] = $br(['d' => 'rss:show']);
T::check('ko\'prik: RSS ekrani', $st === 200 && !empty($r['screens']));
[$st, $r] = $br(['d' => 'ref:show']);
T::check('ko\'prik: taklif ekrani havola bilan', strpos($r['screens'][0]['text'], 'ref_' . $B) !== false);
[$st, $r] = $br(['d' => 'promo:ask']);
T::eq('ko\'prik: promo so\'raldi — matn kutilmoqda', $r['state'] ?? null, 'promo_wait');
[$st, $r] = $br(['t' => 'NOMA\'LUMKOD']);
T::check('ko\'prik: matn yuborish (promo) javob qaytardi', $st === 200 && !empty($r['screens']));
PostAssist\Handlers\MiniAppApi::handle($appU, 'bridge_reset', [], $initB);
T::eq('bridge_reset: holat tozalandi', $appU->states->get($B), null);
T::eq('ko\'prik: bo\'sh so\'rov rad', $br([])[0], 400);
[$st, $r] = $br(['d' => 'm:home']);
T::check('ko\'prik: m:home — bosh menyu belgisi', $st === 200 && $r['menu'] === true);

// --- kuzatish: yuborilgan va chiqmagan postlar
$call2 = static function (string $a, array $in = []) use ($appU, $initB): array {
    return PostAssist\Handlers\MiniAppApi::handle($appU, $a, $in, $initB);
};
T::check('sent_list / failed_list ishlaydi (bo\'sh)', $call2('sent_list')[1]['items'] === [] && $call2('failed_list')[1]['items'] === []);
T::eq('sent_edit: topilmasa 404', $call2('sent_edit', ['id' => 99999, 'text' => 'x'])[0], 404);
T::eq('sent_delete: topilmasa 404', $call2('sent_delete', ['id' => 99999])[0], 404);
T::eq('post_retry: topilmasa 404', $call2('post_retry', ['id' => 99999])[0], 404);

// --- Mini App: hamma matn kalitlari 3 tilda bor (data-t, data-bt, data-ph va JS dagi t('...'))
$srcAll = (string) file_get_contents(__DIR__ . '/../app.php');
preg_match_all('/(?:data-t|data-bt|data-ph)="(ma_[a-z0-9_]+)"|\bt\(\'(ma_[a-z0-9_]+)\'|\'(ma_(?:opt|rep|ad|err)_[a-z0-9_]+)\'/', $srcAll, $mmk);
$keysUsed = array_unique(array_filter(array_merge($mmk[1], $mmk[2], $mmk[3]), static function ($k) {
    return (string) $k !== '' && substr((string) $k, -1) !== '_'; // dinamik old qo'shimchalar (ma_opt_ + nom)
}));
$missing = [];
foreach (['uz', 'ru', 'en'] as $lg) {
    $tbl = PostAssist\I18n::table($lg);
    foreach ($keysUsed as $k) {
        if (!isset($tbl[$k]) || trim((string) $tbl[$k]) === '') {
            $missing[] = $lg . ':' . $k;
        }
    }
}
if ($missing) {
    echo '    yo\'q: ' . implode(' ', array_slice($missing, 0, 30)) . "\n";
}
T::check('Mini App: ' . count($keysUsed) . ' ta matn kaliti uz/ru/en da bor (' . implode(',', array_slice($missing, 0, 5)) . ')', $missing === []);
$ma = [];
foreach (['uz', 'ru', 'en'] as $lg) {
    $ma[$lg] = array_keys(array_filter(PostAssist\I18n::table($lg), static function ($k) {
        return strpos($k, 'ma_') === 0;
    }, ARRAY_FILTER_USE_KEY));
}
T::check('ma_* kalitlari uch tilda bir xil to\'plam', !array_diff($ma['uz'], $ma['ru']) && !array_diff($ma['uz'], $ma['en']) && !array_diff($ma['ru'], $ma['uz']) && !array_diff($ma['en'], $ma['uz']));
$allKeys = [];
foreach (['uz', 'ru', 'en'] as $lg) {
    $allKeys[$lg] = array_keys(PostAssist\I18n::table($lg));
}
T::check('butun bot matnlari uch tilda bir xil to\'plam (' . count($allKeys['uz']) . ' kalit)', !array_diff($allKeys['uz'], $allKeys['ru']) && !array_diff($allKeys['uz'], $allKeys['en']) && !array_diff($allKeys['ru'], $allKeys['en']));
T::check('app.php: karusel nav, ko\'prik, yuborilgan postlar, to\'liq tahrirlash', strpos($srcAll, 'id="nav"') !== false && strpos($srcAll, "api('bridge'") !== false
    && strpos($srcAll, "api('sent_edit'") !== false && strpos($srcAll, "api('failed_list')") !== false && strpos($srcAll, 'id="e-rep"') !== false && strpos($srcAll, 'centerNav') !== false);

// --- ko'prik orqali oqimlar: kanal ulash, so'rovnoma, kontent-reja; chiqqan postni tahrirlash/o'chirish
$BC = -1001000000777;
$fake->chats['@brkanal'] = ['id' => $BC, 'type' => 'channel', 'title' => 'Ko\'prik kanali', 'username' => 'brkanal'];
$fake->members["{$BC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["{$BC}|{$B}"] = ['status' => 'creator'];
$before = $appU->channels->countFor($B);
[$st, $r] = $br(['d' => 'ch:add']);
T::eq('ko\'prik: kanal ulash — matn kutilmoqda', $r['state'] ?? null, 'ch_wait');
[$st, $r] = $br(['t' => '@brkanal']);
T::check('ko\'prik: @username bilan kanal ulandi (bot admin tekshiruvi haqiqiy)', $appU->channels->countFor($B) === $before + 1 && strpos((string) ($r['screens'][0]['text'] ?? ''), 'prik kanali') !== false);
[$st, $r] = $br(['d' => 'ch:list']);
T::check('ko\'prik: kanallar ro\'yxatida yangi kanal tugmasi', strpos(json_encode($r['screens'], JSON_UNESCAPED_UNICODE), 'Ko\'prik kanali') !== false);
[$st, $r] = $br(['d' => 'poll:start']);
T::eq('ko\'prik: so\'rovnoma — savol kutilmoqda', $r['state'] ?? null, 'poll_q');
$br(['t' => 'Qaysi biri yaxshi?']);
[$st, $r] = $br(['t' => "Birinchi\nIkkinchi\nUchinchi"]);
T::check('ko\'prik: so\'rovnoma tayyor — preview ekrani va tugmalar (p:now)', strpos(json_encode($r['screens']), 'p:now') !== false || strpos(json_encode($r['screens']), 'p:') !== false);
PostAssist\Handlers\MiniAppApi::handle($appU, 'bridge_reset', [], $initB);
[$st, $r] = $br(['d' => 'cp:show']);
T::check('ko\'prik: kontent-reja ekrani', $st === 200 && !empty($r['screens']));
[$st, $r] = $br(['d' => 'tpl:list']);
T::check('ko\'prik: shablonlar ekrani', $st === 200);
[$st, $r] = $br(['d' => 'st:show']);
T::check('ko\'prik: tahlil ekrani', $st === 200 && !empty($r['screens']));
[$st, $r] = $br(['d' => 'set:team']);
T::check('ko\'prik: jamoa ekrani', $st === 200 && !empty($r['screens']));
[$st, $r] = $br(['d' => 'set:help']);
T::check('ko\'prik: yordam matni', $st === 200 && strpos($r['screens'][0]['text'], '/start') !== false);

// chiqqan post: tahrirlash va o'chirish (kanalda haqiqiy editMessage/deleteMessage chaqiriladi)
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at) VALUES (?, ?, 'text', 'Eski matn', 'sent', UTC_TIMESTAMP(), UTC_TIMESTAMP())", [$B, $BC]);
$pidB = $db->lastId();
$db->exec("INSERT INTO sent_messages (post_id, chat_id, message_id, created_at) VALUES (?, ?, 555, UTC_TIMESTAMP())", [$pidB, $BC]);
$smid = $db->lastId();
[$st, $r] = $call2('sent_list');
T::check('sent_list: chiqqan post ko\'rinadi', $st === 200 && count($r['items']) === 1 && $r['items'][0]['editable'] === true && $r['items'][0]['channel'] !== '');
$fake->reset();
[$st, $r] = $call2('sent_edit', ['id' => $smid, 'text' => '<b>Yangi</b> matn']);
$em = $fake->of('editMessageText')[0] ?? [];
T::check('sent_edit: kanaldagi xabar tahrirlandi (editMessageText, to\'g\'ri chat va id)', $st === 200 && (int) ($em['chat_id'] ?? 0) === $BC && (int) ($em['message_id'] ?? 0) === 555
    && strpos((string) ($em['text'] ?? ''), 'Yangi') !== false);
T::eq('sent_edit: bo\'sh matn rad', $call2('sent_edit', ['id' => $smid, 'text' => '   '])[0], 400);
T::eq('sent_edit: boshqa odamning posti — 404', PostAssist\Handlers\MiniAppApi::handle($appU, 'sent_edit', ['id' => $smid, 'text' => 'x'], $initZ)[0], 404);
$fake->reset();
T::eq('sent_delete: boshqa odam — 404', PostAssist\Handlers\MiniAppApi::handle($appU, 'sent_delete', ['id' => $smid], $initZ)[0], 404);
[$st, $r] = $call2('sent_delete', ['id' => $smid]);
T::check('sent_delete: kanaldan o\'chirildi', $st === 200 && ($fake->of('deleteMessage')[0]['message_id'] ?? 0) == 555 && $call2('sent_list')[1]['items'] === []);

// chiqmagan post: ro'yxat va qayta navbatga
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at, last_error) VALUES (?, ?, 'text', 'Chiqmadi', 'failed', UTC_TIMESTAMP(), UTC_TIMESTAMP(), 'Bot admin emas')", [$B, $BC]);
$fid = $db->lastId();
[$st, $r] = $call2('failed_list');
T::check('failed_list: sabab bilan', count($r['items']) === 1 && $r['items'][0]['error'] === 'Bot admin emas');
T::eq('post_retry: boshqa odam — 404', PostAssist\Handlers\MiniAppApi::handle($appU, 'post_retry', ['id' => $fid], $initZ)[0], 404);
T::eq('post_retry: qayta navbatga', $call2('post_retry', ['id' => $fid])[0], 200);
T::eq('post_retry: holat pending', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$fid]), 'pending');

// navbatdagi postni TO'LIQ tahrirlash
[$st, $r] = $call2('post_update', ['id' => $fid, 'text' => 'Yangilangan', 'button_text' => 'Batafsil', 'button_url' => 'sayt.uz', 'reactions' => '', 'delete_after' => 60,
    'options' => 'silent,pin', 'hidden' => 'Sir', 'repeat' => 'daily', 'channel_id' => $appU->channels->countFor($B) ? (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$BC]) : 0]);
$row = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [$fid]);
T::check('post_update: matn, tugma, avto-o\'chirish, sozlamalar, yashirin matn, takror saqlandi', $st === 200 && $row['text'] === 'Yangilangan' && $row['button_text'] === 'Batafsil'
    && $row['button_url'] === 'https://sayt.uz' && (int) $row['delete_after'] === 60 && $row['options'] === 'silent,pin' && strpos((string) $row['hidden_text'], 'Sir') !== false && $row['recurrence_type'] === 'daily');
T::check('post_update: javobda xom qiymatlar (repeat_key, options, hidden, channel_ref)', $r['post']['repeat_key'] === 'daily' && $r['post']['options'] === ['silent', 'pin'] && $r['post']['hidden'] === 'Sir' && $r['post']['channel_ref'] > 0);
T::eq('post_update: tugmasiz URL rad', $call2('post_update', ['id' => $fid, 'button_text' => 'x', 'button_url' => 'bu url emas'])[0], 400);
$call2('post_update', ['id' => $fid, 'button_text' => '', 'button_url' => '', 'repeat' => '', 'hidden' => '', 'delete_after' => 0, 'options' => '']);
$row = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [$fid]);
T::check('post_update: bo\'sh qiymatlar tugma/takror/yashirin matnni o\'chiradi', $row['button_text'] === null && $row['recurrence_type'] === null && $row['hidden_text'] === null && $row['delete_after'] === null);
T::eq('post_update: boshqa odam — 404', PostAssist\Handlers\MiniAppApi::handle($appU, 'post_update', ['id' => $fid, 'text' => 'hack'], $initZ)[0], 404);
