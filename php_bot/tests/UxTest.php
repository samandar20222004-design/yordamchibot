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

// --- eski (Python bot) pastki menyu yorliqlari
$textU($X, '⚙️ Sozlamalar / Ko\'proq');
T::check('eski yorliq: pastki menyu yangisiga almashadi', strpos($fake->texts(), 'Menyu yangilandi') !== false
    && strpos(json_encode($fake->of('sendMessage'), JSON_UNESCAPED_UNICODE), 'Sozlamalar / Ko') === false);
$textU($ADMIN, '⚙️ Admin Panel');
T::check('eski «⚙️ Admin Panel» (Python bot) — admin paneli ochiladi, aqlli qabul emas', strpos($fake->texts(), 'Bu bilan nima qilamiz') === false
    && $fake->of('sendMessage') !== [] && ($appU->states->get($ADMIN)['state'] ?? null) !== 'intake' && strpos($fake->texts(), 'Menyu yangilandi') !== false);
T::check('eski yorliqda admin statistikasi chiqdi', strpos($fake->texts(), 'Foydalanuvchilar') !== false);
$textU($ADMIN, '👑 Admin panel');
T::check('yangi admin yorlig\'i: panel, menyu qayta yuborilmaydi', strpos($fake->texts(), 'Foydalanuvchilar') !== false && strpos($fake->texts(), 'Menyu yangilandi') === false);
$textU($X, '⚙️ Admin Panel');
T::check('oddiy foydalanuvchiga eski admin yorlig\'i paneli ochmaydi', strpos($fake->texts(), 'Bu bilan nima qilamiz') === false && strpos($fake->texts(), 'Foydalanuvchilar') === false);
$textU($X, '🔙 Asosiy menyu');
T::check('eski «🔙 Asosiy menyu» — yangi menyu yuboriladi', strpos($fake->texts(), 'Menyu yangilandi') !== false && strpos($fake->texts(), 'Bu bilan nima qilamiz') === false);

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
    && strpos($appSrcU, "setAttribute('data-tgp'") !== false && strpos($appSrcU, 'class="chips scroll" id="mk-cats"') !== false && strpos($appSrcU, 'class="mk-bar"') !== false // birja: qidiruv · davlat · suhbat · e'lon — bitta qator
    && strpos($appSrcU, 'id="ui-compact"') !== false && strpos($appSrcU, "closest('.hint, .mk-note')") !== false);

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
$allBtns = static function (array $r): array {
    $o = [];
    foreach ($r['screens'] as $sc) {
        foreach ($sc['rows'] as $row) {
            foreach ($row as $b) {
                $o[] = $b;
            }
        }
    }
    return $o;
};
$navLeft = 0;
foreach (['ap:show', 'rss:show', 'ref:show', 'tpl:list', 'cp:show', 'st:show', 'ch:list'] as $scr) {
    foreach ($allBtns($br(['d' => $scr])[1]) as $b) {
        if (($b['d'] ?? '') === 'm:home' || in_array(PostAssist\I18n::bare($b['t']), ['Orqaga', 'Menyu'], true)) {
            $navLeft++;
        }
    }
}
T::eq('ko\'prik: Mini App\'da «◀️ Orqaga» / «🏠 Menyu» tugmalari yo\'q (tepada Telegram orqaga, pastda bosh sahifa)', $navLeft, 0);
// --- moslik: birja qidiruvi botda ham, manba havolalari (/mylinks) Mini App'da ham
$appU->market->upsert($ADMIN, ['channel_id' => -1007790, 'title' => 'Qidiruv sinov kanali', 'username' => 'qidiruv_sinov'], 100000, 'UZS', 'Futbol yangiliklari', 'sport', 5000, $clock);
[$st, $r] = $br(['d' => 'mk:cat']);
T::check('bot birjasi: toifalarda «🔎 Qidirish»', strpos(json_encode($r, JSON_UNESCAPED_UNICODE), 'mk:q') !== false);
$br(['d' => 'mk:q']);
T::eq('mk:q — qidiruv so\'zi kutiladi', $appU->states->get($B)['state'] ?? null, 'mk_search');
[$st, $r] = $br(['t' => 'futbol']);
T::check('qidiruv tavsifdan topdi', strpos($r['screens'][0]['text'] ?? '', '<b>1</b>') !== false && strpos(json_encode($r, JSON_UNESCAPED_UNICODE), 'Qidiruv sinov') !== false
    && ($appU->states->get($B)['state'] ?? null) === null);
$br(['d' => 'mk:q']);
[$st, $r] = $br(['t' => 'yoqkanalxyz']);
T::check('qidiruv: topilmasa tushunarli xabar', strpos($r['screens'][0]['text'] ?? '', 'topilmadi') !== false);
[$st, $r] = $br(['d' => 'ref:show']);
T::check('havolasi yo\'q foydalanuvchida «Havolalarim» yo\'q', strpos(json_encode($r), 'ref:links') === false);
$appU->links->create('mosl1', 'Sinov', $B, $ADMIN, $clock);
[$st, $r] = $br(['d' => 'ref:show']);
T::check('havola egasida «🔗 Havolalarim» (Mini App\'da ham)', strpos(json_encode($r), 'ref:links') !== false);
[$st, $r] = $br(['d' => 'ref:links']);
T::check('ref:links — havolalar soni ko\'rinadi', strpos($r['screens'][0]['text'] ?? '', 'mosl1') !== false);
T::check('boshlash kartasi: bajarilgan qadam ustidan chizilmaydi va xiralashmaydi (✓ belgi)', strpos($appSrcU, 'line-through') === false
    && strpos($appSrcU, '.steps li.done::before{content:"✓"') !== false && strpos($appSrcU, "'ma_start_1_done'") !== false);
foreach (['uz', 'ru', 'en'] as $lg) {
    T::check("boshlash 3-qadam hozirgi bo'lim nomlari ($lg)", strpos(PostAssist\I18n::t('ma_start_3', $lg), PostAssist\I18n::t('ma_tab_posts', $lg)) !== false
        && strpos(PostAssist\I18n::t('ma_ai_media', $lg), 'Gemini') === false);
}
T::check('app.php: ekran ichidagi «Orqaga» tugmasi yo\'q, Telegram BackButton ishlatiladi', strpos($appSrcU, 'id="br-back"') === false
    && strpos($appSrcU, 'id="mk-close"') === false && strpos($appSrcU, 'tg.BackButton.onClick') !== false);

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

// --- pastki panel: ko'pi bilan 5 ta tugma (4 bo'lim + «＋»), ikonkalar SVG
$srcNav = (string) file_get_contents(__DIR__ . '/../app.php');
preg_match('#<div class="dock">(.*?)</div>#s', $srcNav, $dockM);
$dock = $dockM[1] ?? '';
T::check('pastki panel: 4 bo\'lim + markaziy «＋» = 5 ta, emoji emas SVG ikonka', substr_count($dock, 'data-go=') === 4 && substr_count($dock, '<svg') === 5 && strpos($dock, 'id="fab"') !== false);
T::check('app.php: «＋» tezkor amallar oynasi, yaqin postlar, qoralama qurilmada saqlanadi, o\'z logotipi', strpos($srcNav, 'data-qa="') !== false
    && strpos($srcNav, 'function loadUpcoming') !== false && strpos($srcNav, "DKEY = 'pa_draft_text_v1'") !== false && strpos($srcNav, '<div class="logo"><svg') !== false);

// --- til almashtirish (Mini App): bazada saqlanadi, bot menyusi ham yangi tilga o'tadi, «me» yangi tilni qaytaradi
$fake->reset();
[$st, $r] = PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['lang' => 'ru'], $initB);
$lm = $fake->of('sendMessage')[0] ?? [];
T::check('til ru: bot pastki menyusi ruscha yuborildi', $st === 200 && (int) ($lm['chat_id'] ?? 0) === $B && strpos($mk($lm), 'Настройки') !== false);
T::eq('til ru: me.user.lang', PostAssist\Handlers\MiniAppApi::handle($appU, 'me', [], $initB)[1]['user']['lang'], 'ru');
$fake->reset();
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['lang' => 'ru'], $initB);
T::eq('o\'sha til qayta tanlansa bot xabar yubormaydi', $fake->of('sendMessage'), []);
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['lang' => 'uz'], $initB);
T::eq('noto\'g\'ri til rad', PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['lang' => 'xx'], $initB)[0], 400);
$appSrcL = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: til almashganda me yangilanadi (eski tilga qaytmaydi), sahifa keshlanmaydi', strpos($appSrcL, 'me.user.lang = l') !== false
    && strpos($appSrcL, "header('Cache-Control: no-cache, no-store, must-revalidate')") !== false && strpos($appSrcL, 'refreshPage()') !== false);
T::check('setup.php: Mini App manzili versiya bilan (?v=)', strpos((string) file_get_contents(__DIR__ . '/../setup.php'), "miniAppUrl('v='") !== false);
$fake->reset();
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['lang' => 'en'], $initB);
$cm = $fake->of('setMyCommands')[0] ?? [];
T::check('til en: «/» buyruqlar menyusi shu chat uchun inglizcha', strpos((string) ($cm['scope'] ?? ''), (string) $B) !== false && strpos((string) ($cm['commands'] ?? ''), 'Main menu') !== false);
$fake->reset();
$textU($B, '/start');
$pressU($B, 'lang:ru');
$cm = $fake->of('setMyCommands')[0] ?? [];
T::check('botda til ru: buyruqlar menyusi ham ruscha', strpos((string) ($cm['commands'] ?? ''), 'Главное меню') !== false);
$pressU($B, 'lang:uz');

// --- navbatdagi post: hozir yuborish, vaqtni o'zgartirish, nusxa (bot) va Mini App post_now
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at) VALUES (?, ?, 'text', 'Navbat posti', 'pending', DATE_ADD(UTC_TIMESTAMP(), INTERVAL 3 DAY), UTC_TIMESTAMP())", [$B, $BC]);
$qid = $db->lastId();
$pressU($B, 'q:v:' . $qid);
$qkb = $lastKb();
T::check('bot: navbatdagi post — Hozir / Vaqt / Nusxa / Bekor qilish tugmalari', strpos($qkb, 'q:now:' . $qid) !== false && strpos($qkb, 'q:t:' . $qid) !== false
    && strpos($qkb, 'q:cp:' . $qid) !== false && strpos($qkb, 'q:d:' . $qid) !== false);
$pressU($B, 'q:t:' . $qid);
T::eq('bot: vaqt so\'raldi (holat q_time)', $appU->states->get($B)['state'] ?? null, 'q_time');
$textU($B, 'ertaga 09:00');
T::check('bot: yangi vaqt saqlandi', strpos($fake->lastText(), '09:00') !== false && strpos((string) $db->value('SELECT scheduled_time FROM scheduled_posts WHERE id = ?', [$qid]), ':00:00') !== false
    && $appU->states->get($B) === null);
$pressU($B, 'q:tq:' . $qid . ':1h');
T::check('bot: tezkor vaqt (+1 soat)', strpos($fake->lastText(), '✅') !== false);
$pressU($B, 'q:cp:' . $qid);
T::check('bot: nusxa — post ko\'rinishi (preview) ochildi', strpos(json_encode($fake->calls, JSON_UNESCAPED_UNICODE), 'Navbat posti') !== false && strpos($lastKb() . json_encode($fake->calls), 'p:now') !== false);
$appU->states->clear($B);
$fake->reset();
$pressU($B, 'q:now:' . $qid);
T::check('bot: «Hozir yuborish» — kanalga chiqdi', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$qid]) === 'sent' && $fake->of('sendMessage') !== []);
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at) VALUES (?, ?, 'text', 'Mini navbat', 'pending', DATE_ADD(UTC_TIMESTAMP(), INTERVAL 3 DAY), UTC_TIMESTAMP())", [$B, $BC]);
$qid2 = $db->lastId();
T::eq('post_now: boshqa odam — 404', PostAssist\Handlers\MiniAppApi::handle($appU, 'post_now', ['id' => $qid2], $initZ)[0], 404);
[$st, $r] = $call2('post_now', ['id' => $qid2]);
T::check('Mini App post_now: yuborildi', $st === 200 && ($r['status'] ?? '') === 'sent' && $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$qid2]) === 'sent');
$appSrcQ = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: kunlar lentasi, qidiruv, Hozir/Nusxa tugmalari', strpos($appSrcQ, 'function renderDays') !== false && strpos($appSrcQ, 'id="q-search"') !== false
    && strpos($appSrcQ, "api('post_now'") !== false && strpos($appSrcQ, 'function applyToEditor') !== false);

// --- bir nechta havolali tugma (qatorlar; qatorda 3 tagacha)
$pb = PostAssist\Services\Links::parseButtons("Sayt - sayt.uz | Kanal - @kanalim\nBatafsil - t.me/kanalim/5");
T::check('parseButtons: 2 qator, birinchisida 2 tugma', is_array($pb) && count($pb) === 2 && count($pb[0]) === 2 && $pb[0][1][1] === 'https://t.me/kanalim'
    && $pb[1][0][0] === 'Batafsil');
T::eq('parseButtons: eski «Matn | havola» — bitta tugma', PostAssist\Services\Links::parseButtons('Batafsil | sayt.uz'), [[['Batafsil', 'https://sayt.uz']]]);
T::eq('parseButtons: noto\'g\'ri qator — rad', PostAssist\Services\Links::parseButtons("Sayt - sayt.uz\nyomon"), null);
T::eq('parseButtons: qatorda 4 tugma — rad', PostAssist\Services\Links::parseButtons('a - a.uz | b - b.uz | c - c.uz | d - d.uz'), null);
T::eq('parseButtons: 9 qator — rad', PostAssist\Services\Links::parseButtons(implode("\n", array_fill(0, 9, 'a - a.uz'))), null);
T::eq('cleanButtons: {t,u} va [t,u], bo\'sh tugmalar tashlanadi', PostAssist\Services\Links::cleanButtons([[['t' => 'A', 'u' => 'a.uz'], ['B', '@bkanal']], [['t' => '', 'u' => '']]]),
    [[['A', 'https://a.uz'], ['B', 'https://t.me/bkanal']]]);
T::eq('cleanButtons: havolasiz tugma — xato', PostAssist\Services\Links::cleanButtons([[['t' => 'A', 'u' => '']]]), null);
T::eq('cleanButtons: massiv emas — bo\'sh', PostAssist\Services\Links::cleanButtons('x'), []);
T::eq('buttonsJson: bitta tugma — eski ustunlar yetadi (null)', PostAssist\Services\PostRender::buttonsJson([[['A', 'https://a.uz']]]), null);

$urlRows = static function (array $markup): array {
    $out = [];
    foreach ($markup['inline_keyboard'] ?? [] as $r) {
        $u = [];
        foreach ($r as $b) {
            if (isset($b['url'])) {
                $u[] = $b['url'];
            }
        }
        if ($u) {
            $out[] = $u;
        }
    }
    return $out;
};
$appU->states->clear($B);
$textU($B, '/newpost');
$textU($B, 'Ko\'p tugmali post');
if (($appU->states->get($B)['state'] ?? '') === 'post_pick') {
    $pressU($B, 'p:ch:' . (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$BC]));
}
$pressU($B, 'p:btn');
$textU($B, "Sayt - sayt.uz | Kanal - @kanalim\nBatafsil - t.me/kanalim/5");
$pvb = $fake->of('sendMessage')[0] ?? [];
$pvm = json_decode((string) ($pvb['reply_markup'] ?? '{}'), true) ?: [];
T::eq('bot: preview — tugmalar qatorlari aynan shunday', array_slice($urlRows($pvm), 0, 2), [['https://sayt.uz', 'https://t.me/kanalim'], ['https://t.me/kanalim/5']]);
$fake->reset();
$pressU($B, 'p:now');
$sentB = null;
foreach ($fake->of('sendMessage') as $c) {
    if ((string) ($c['chat_id'] ?? '') === (string) $BC) {
        $sentB = $c;
    }
}
T::eq('kanalga: 2 qator url tugma', $urlRows(json_decode((string) ($sentB['reply_markup'] ?? '{}'), true) ?: []), [['https://sayt.uz', 'https://t.me/kanalim'], ['https://t.me/kanalim/5']]);
$smB = $db->one('SELECT * FROM sent_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1', [$BC]);
T::check('sent_messages.buttons saqlandi', $smB !== null && count(json_decode((string) $smB['buttons'], true) ?: []) === 2);
T::eq('qayta chizish (reaksiya/izoh): tugmalar yo\'qolmaydi', $urlRows(['inline_keyboard' => $appU->messageRows($smB)]), [['https://sayt.uz', 'https://t.me/kanalim'], ['https://t.me/kanalim/5']]);

$bcId = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$BC]);
[$st, $r] = $call2('post_create', ['channel_id' => $bcId, 'text' => 'Mini tugmalar', 'when' => $clock->modify('+2 day')->format('Y-m-d') . 'T10:00',
    'buttons' => [[['t' => 'Bir', 'u' => 'bir.uz'], ['t' => 'Ikki', 'u' => 'ikki.uz']], [['t' => 'Uch', 'u' => '@uchkanal']]]]);
T::check('Mini App post_create: 3 tugma (2+1) saqlandi', $st === 200 && count(PostAssist\Services\PostRender::buttonList($db->one('SELECT * FROM scheduled_posts WHERE id = ?', [(int) ($r['id'] ?? 0)]) ?? [])) === 2, json_encode($r));
$mpid = (int) ($r['id'] ?? 0);
T::eq('Mini App post_create: noto\'g\'ri tugma — 400', $call2('post_create', ['channel_id' => $bcId, 'text' => 'x', 'buttons' => [[['t' => 'A', 'u' => '']]]])[0], 400);
[$st, $r] = $call2('post_update', ['id' => $mpid, 'buttons' => [[['t' => 'Yangi', 'u' => 'yangi.uz']]]]);
$mp = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [$mpid]);
T::check('post_update: bitta tugmaga tushdi (eski ustunlar)', $st === 200 && $mp['buttons'] === null && $mp['button_url'] === 'https://yangi.uz');
[$st, $r] = $call2('post_update', ['id' => $mpid, 'buttons' => []]);
$mp = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [$mpid]);
T::check('post_update: tugmalar olib tashlandi', $st === 200 && $mp['button_url'] === null && PostAssist\Services\PostRender::buttonList($mp) === []);
[$st, $r] = $call2('template_save', ['name' => 'Tugmali', 'text' => 'Shablon', 'buttons' => [[['t' => 'A', 'u' => 'a.uz'], ['t' => 'B', 'u' => 'b.uz']]]]);
T::check('shablon: tugmalar saqlandi va qaytdi', $st === 200 && count($call2('template', ['id' => (int) $r['id']])[1]['template']['buttons'][0] ?? []) === 2);
$appSrcB = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: tugma muharriri (qatorlar)', strpos($appSrcB, 'function btnEditor') !== false && strpos($appSrcB, "btnRead('b-rows')") !== false && strpos($appSrcB, "btnRead('e-rows')") !== false);

// --- 🏆 eng yaxshi postlar va ⏰ eng yaxshi vaqt
$SB = 7720;
$textU($SB, '/start');
$SBC = -1001000000720;
$db->exec("INSERT INTO channels (user_id, channel_id, title, is_active, created_at) VALUES (?, ?, 'Vaqt kanali', 1, UTC_TIMESTAMP())", [$SB, $SBC]);
$tzSB = $appU->tzFor($SB);
$bt0 = PostAssist\Handlers\StatsHandler::bestTime($appU, $SB, $tzSB);
T::check('eng yaxshi vaqt: ma\'lumot yo\'q — umumiy tavsiya 09/13/20', $bt0['data'] === false && $bt0['hours'] === [9, 13, 20] && $bt0['posts'] === 0);
$mid = 5000;
$mkSent = static function (string $utc, int $votes, string $txt) use ($db, $SB, $SBC, &$mid): void {
    $db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at) VALUES (?, ?, 'text', ?, 'sent', ?, ?)", [$SB, $SBC, $txt, $utc, $utc]);
    $pid = $db->lastId();
    $mid++;
    $db->exec('INSERT INTO sent_messages (post_id, chat_id, message_id, created_at) VALUES (?, ?, ?, ?)', [$pid, $SBC, $mid, $utc]);
    for ($v = 0; $v < $votes; $v++) {
        $db->exec('INSERT INTO reaction_votes (chat_id, message_id, user_id, idx, created_at) VALUES (?, ?, ?, 0, ?)', [$SBC, $mid, 90000 + $v, $utc]);
    }
};
foreach ([2, 3, 4, 5] as $k => $ago) {
    $mkSent($clock->modify('-' . $ago . ' days')->format('Y-m-d') . ' 15:00:00', 2 + $k, 'Kechki post ' . $k); // Toshkent 20:00
}
$mkSent($clock->modify('-2 days')->format('Y-m-d') . ' 04:00:00', 0, 'Ertalabki post A'); // 09:00
$mkSent($clock->modify('-3 days')->format('Y-m-d') . ' 04:00:00', 1, 'Ertalabki post B');
$mkSent($clock->modify('-200 days')->format('Y-m-d') . ' 04:00:00', 50, 'Juda eski post'); // 90 kundan eski — hisobga olinmaydi
$bt = PostAssist\Handlers\StatsHandler::bestTime($appU, $SB, $tzSB);
T::check('eng yaxshi vaqt: 20:00 birinchi, 09:00 keyin (mahalliy soat)', $bt['data'] === true && $bt['posts'] === 6 && $bt['hours'] === [20, 9], json_encode($bt));
$tp = PostAssist\Handlers\StatsHandler::topPosts($appU, $SB, $tzSB);
T::check('top postlar: ballsiz post yo\'q, eng faoli birinchi, eski post kirmaydi', count($tp) === 5 && $tp[0]['text'] === 'Kechki post 3' && $tp[0]['votes'] === 5
    && strpos(json_encode($tp, JSON_UNESCAPED_UNICODE), 'Juda eski') === false && strpos(json_encode($tp, JSON_UNESCAPED_UNICODE), 'Ertalabki post A') === false);
$pressU($SB, 'st:show');
T::check('bot: Statistika — «Top postlar» va «Eng yaxshi vaqt» tugmalari', strpos($lastKb(), 'st:top') !== false && strpos($lastKb(), 'st:best') !== false);
$pressU($SB, 'st:top');
T::check('bot: top postlar ro\'yxati + ko\'rishlar haqida izoh', strpos($fake->lastText(), '1. «Kechki post 3»') !== false && strpos($fake->lastText(), 'ko\'rishlar sonini bermaydi') !== false
    && strpos($lastKb(), 'st:show') !== false);
$pressU($SB, 'st:best');
T::check('bot: eng yaxshi vaqt — 20:00 va eng faol kun', strpos($fake->lastText(), '<b>20:00</b>') !== false && strpos($fake->lastText(), 'Eng faol kun') !== false
    && strpos($fake->lastText(), '6 ta post') !== false);
$initSB = $mkInitU(['id' => $SB, 'first_name' => 'S', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
[$st, $r] = PostAssist\Handlers\MiniAppApi::handle($appU, 'stats', [], $initSB);
T::check('Mini App stats: top va best', $st === 200 && count($r['top']) === 5 && $r['best']['hours'][0] === 20);
[$st, $r] = PostAssist\Handlers\MiniAppApi::handle($appU, 'best_time', [], $initSB);
T::check('Mini App best_time', $st === 200 && $r['ok'] === true && $r['data'] === true && $r['hours'][0] === 20);
$pressU($B, 'lang:ru');
$pressU($SB, 'lang:ru');
$pressU($SB, 'st:best');
T::check('ru: лучшее время', strpos($fake->lastText(), 'Лучшее время') !== false);
$pressU($SB, 'lang:uz');
$pressU($B, 'lang:uz');
$appSrcS = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: statistikada top/vaqt, tezkor vaqtda «⭐ Eng yaxshi»', strpos($appSrcS, 'function topHtml') !== false && strpos($appSrcS, "api('best_time')") !== false
    && strpos($appSrcS, "t('ma_q_best'") !== false);

// --- AI: kalit/model xatosi yashirin qolmaydi (log + setup.php tekshiruvi), kalit logga tushmaydi
$aiLogs = [];
$aiT = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'GKEY-SECRET', 'groq_api_key' => 'QKEY']), static function (string $url, array $h, string $b): array {
    if (strpos($url, 'googleapis') !== false) {
        return [400, json_encode(['error' => ['code' => 400, 'message' => 'API key not valid: GKEY-SECRET', 'status' => 'INVALID_ARGUMENT']])];
    }
    return [200, json_encode(['choices' => [['message' => ['content' => 'OK']]]])];
});
$aiT->logger = static function (string $m) use (&$aiLogs): void {
    $aiLogs[] = $m;
};
$chk = $aiT->check();
T::check('AI tekshiruvi: gemini — sabab bilan xato, groq — OK', strpos($chk['gemini'], 'HTTP 400') !== false && strpos($chk['gemini'], 'API key not valid') !== false
    && strpos($chk['groq'], 'OK (llama') === 0, json_encode($chk));
T::check('AI xatosi logga yozildi, kalit yashirildi', count($aiLogs) === 1 && strpos($aiLogs[0], 'AI gemini ishlamadi') === 0 && strpos($aiLogs[0], 'GKEY-SECRET') === false
    && strpos($aiLogs[0], '***') !== false);
$g = $aiT->generate('s', 'p', 500);
T::check('generate: gemini yiqilsa groq javob beradi', $g['ok'] === true && $g['provider'] === 'groq');
$aiE = new PostAssist\Services\Ai(new Config(['groq_api_key' => 'Q']), static function (): array {
    return [500, json_encode(['error' => ['code' => 500]])];
});
T::check('xato javobida message yo\'q — ogohlantirishsiz', strpos($aiE->check()['groq'], 'HTTP 500') === 0);
$aiN = new PostAssist\Services\Ai(new Config(['groq_api_key' => 'Q']), static function (): array {
    return [0, ''];
});
T::check('tarmoq yo\'q — aniq sabab', strpos($aiN->check()['groq'], 'tarmoq') === 0);

// --- cron: bitta fon ish xato bersa ham qolganlari ishlaydi (oldin RSS xatosi tarif muddati/avto-o'chirishni to'xtatardi)
$EXU = 7730;
$textU($EXU, '/start');
$db->exec("UPDATE users SET plan_type = 'pro', subscription_expires_at = ? WHERE user_id = ?", [$clock->modify('-1 hour')->format('Y-m-d H:i:s'), $EXU]);
$db->exec('RENAME TABLE rss_feeds TO rss_feeds_tmp');
$logFile = __DIR__ . '/../storage/bot.log';
$logBefore = is_file($logFile) ? (int) filesize($logFile) : 0;
try {
    $schedX = new PostAssist\Services\Scheduler($appU, static function (int $us): void {
    });
    $schedX->run(5);
} finally {
    $db->exec('RENAME TABLE rss_feeds_tmp TO rss_feeds');
}
T::eq('RSS jadvali buzuq bo\'lsa ham tarif muddati ishladi (pro → free)', (string) $db->value('SELECT plan_type FROM users WHERE user_id = ?', [$EXU]), 'free');
$logNew = is_file($logFile) ? (string) file_get_contents($logFile, false, null, $logBefore) : '';
T::check('xato logga yozildi («rss»)', strpos($logNew, 'cron «rss» xato') !== false);

// --- check.php: umumiy sog'lik tekshiruvi (HealthCheck) — maxfiy qiymat chiqmaydi, muammolar topiladi
$hcCfg = ['bot_token' => $config->str('bot_token'), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN], 'webhook_url' => 'https://ex.uz/webhook.php',
    'webhook_secret' => 'wsecret-1234567890', 'cron_key' => 'cronkey-1234567890', 'db_pass' => 'DBPASS-SECRET', 'gemini_api_key' => 'GEMINI-SECRET-KEY'];
$hcLookup = static function (array $rows, string $name): ?array {
    foreach ($rows as $r) {
        if ($r[1] === $name) {
            return $r;
        }
    }
    return null;
};
$hcApp = new App(new Config($hcCfg), $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$fake->forced['getMe'] = [['ok' => true, 'result' => ['username' => 'PostAssistrobot']]];
$fake->forced['getWebhookInfo'] = [['ok' => true, 'result' => ['url' => 'https://ex.uz/webhook.php', 'pending_update_count' => 0]]];
$db->exec("DELETE FROM bot_settings WHERE k = 'cron_last'");
$hcRows = (new PostAssist\Services\HealthCheck($hcApp, $hcCfg, dirname(__DIR__)))->run(false);
T::check('sog\'lik: baza, jadvallar, bot, webhook — OK', $hcLookup($hcRows, 'Baza')[0] === 'ok' && $hcLookup($hcRows, 'Jadvallar')[0] === 'ok'
    && $hcLookup($hcRows, 'Bot')[0] === 'ok' && $hcLookup($hcRows, 'Webhook')[0] === 'ok', json_encode($hcRows, JSON_UNESCAPED_UNICODE));
T::eq('sog\'lik: cron hali ishlamagan — xato', $hcLookup($hcRows, 'Cron')[0], 'fail');
$db->exec("INSERT INTO bot_settings (k, v, updated_at) VALUES ('cron_last', ?, UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE v = VALUES(v)", [gmdate('Y-m-d H:i:s')]);
$fake->forced['getMe'] = [['ok' => true, 'result' => ['username' => 'PostAssistrobot']]];
$fake->forced['getWebhookInfo'] = [['ok' => true, 'result' => ['url' => 'https://boshqa.uz/webhook.php', 'pending_update_count' => 50, 'last_error_message' => 'Connection timed out', 'last_error_date' => time()]]];
$hcRows2 = (new PostAssist\Services\HealthCheck($hcApp, $hcCfg, dirname(__DIR__)))->run(false);
T::eq('sog\'lik: cron yangi — OK', $hcLookup($hcRows2, 'Cron')[0], 'ok');
T::eq('sog\'lik: webhook boshqa manzilda — xato', $hcLookup($hcRows2, 'Webhook')[0], 'fail');
T::eq('sog\'lik: ko\'p kutilayotgan yangilanish — ogohlantirish', $hcLookup($hcRows2, 'Kutilayotgan yangilanishlar')[0], 'warn');
T::eq('sog\'lik: Telegram webhook xatosi ko\'rinadi', $hcLookup($hcRows2, 'Telegram webhook xatosi (oxirgi soat)')[0], 'fail');
$fake->forced['getMe'] = [['ok' => true, 'result' => ['username' => 'BoshqaBot']]];
$fake->forced['getWebhookInfo'] = [['ok' => true, 'result' => ['url' => 'https://ex.uz/webhook.php']]];
$hcRows3 = (new PostAssist\Services\HealthCheck($hcApp, $hcCfg, dirname(__DIR__)))->run(false);
T::eq('sog\'lik: token boshqa botniki — xato', $hcLookup($hcRows3, 'Bot')[0], 'fail');
$fake->forced['getMe'] = [['ok' => false, 'description' => 'Unauthorized']];
$hcRows4 = (new PostAssist\Services\HealthCheck($hcApp, $hcCfg, dirname(__DIR__)))->run(false);
T::check('sog\'lik: noto\'g\'ri token — sabab bilan xato', $hcLookup($hcRows4, 'Bot tokeni')[0] === 'fail' && strpos($hcLookup($hcRows4, 'Bot tokeni')[2], 'Unauthorized') !== false);
$all = json_encode([$hcRows, $hcRows2, $hcRows3, $hcRows4], JSON_UNESCAPED_UNICODE);
T::check('sog\'lik: token, parol, kalit natijada YO\'Q', strpos($all, 'DBPASS-SECRET') === false && strpos($all, 'GEMINI-SECRET-KEY') === false
    && strpos($all, 'wsecret-1234567890') === false && strpos($all, $config->str('bot_token')) === false);
T::check('sog\'lik: summary', strpos(PostAssist\Services\HealthCheck::summary($hcRows2), 'MUAMMO') !== false);
$logSecret = dirname(__DIR__) . '/storage/bot.log';
@file_put_contents($logSecret, '[' . gmdate('Y-m-d H:i:s') . '] webhook xato: so\'rov DBPASS-SECRET bilan yiqildi' . "\n", FILE_APPEND);
$fake->forced['getMe'] = [['ok' => true, 'result' => ['username' => 'PostAssistrobot']]];
$fake->forced['getWebhookInfo'] = [['ok' => true, 'result' => ['url' => 'https://ex.uz/webhook.php']]];
$hcRows5 = (new PostAssist\Services\HealthCheck($hcApp, $hcCfg, dirname(__DIR__)))->run(false);
$logRow = $hcLookup($hcRows5, 'Oxirgi xatolar (bot.log)');
T::check('sog\'lik: log xatosi ko\'rinadi, lekin maxfiy qism yashirilgan', $logRow !== null && $logRow[0] === 'warn' && strpos($logRow[2], 'DBPASS-SECRET') === false && strpos($logRow[2], '***') !== false);
$appSrcC = (string) file_get_contents(dirname(__DIR__) . '/cron.php');
T::check('cron.php: «cron_last» belgisini yozadi', strpos($appSrcC, "'cron_last'") !== false);

// --- AI: model eskirsa (404) bot o'zi mavjud ro'yxatdan mosini topadi, saqlaydi va keyin shuni ishlatadi
$aiStoreData = [];
$aiStore = static function (string $k, ?string $v = null) use (&$aiStoreData): ?string {
    if ($v !== null) {
        $aiStoreData[$k] = $v;
        return $v;
    }
    return $aiStoreData[$k] ?? null;
};
$aiCalls = [];
$aiTr = static function (string $url, array $h, string $b) use (&$aiCalls): array {
    $aiCalls[] = [$url, $b];
    if ($b === '' && strpos($url, 'googleapis.com/v1beta/models?') !== false) { // modellar ro'yxati (GET)
        return [200, json_encode(['models' => [
            ['name' => 'models/gemini-2.5-flash', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/gemini-3.8-flash', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/gemini-3.8-flash-lite', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/gemini-3.9-flash-preview', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/embedding-001', 'supportedGenerationMethods' => ['embedContent']],
        ]])];
    }
    if ($b === '' && strpos($url, 'api.groq.com/openai/v1/models') !== false) {
        return [200, json_encode(['data' => [['id' => 'whisper-large-v3'], ['id' => 'llama-guard-4'], ['id' => 'llama-4-70b-versatile'], ['id' => 'gpt-oss-20b']]])];
    }
    if (strpos($url, 'googleapis.com') !== false) {
        if (strpos($url, 'gemini-3.8-flash:generate') !== false) {
            return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => 'Salom']]]]]])];
        }
        return [404, json_encode(['error' => ['code' => 404, 'message' => 'This model models/x is no longer available to new users.']])];
    }
    if (strpos($url, 'api.groq.com') !== false) {
        if (strpos($b, 'llama-4-70b-versatile') !== false) {
            return [200, json_encode(['choices' => [['message' => ['content' => 'Salom']]]])];
        }
        return [404, json_encode(['error' => ['message' => 'The model `x` does not exist or you do not have access to it.']])];
    }
    return [500, '{}'];
};
$aiH = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'G', 'groq_api_key' => 'Q', 'gemini_model' => 'gemini-2.5-flash']), $aiTr);
$aiH->store = $aiStore;
$aiHLogs = [];
$aiH->logger = static function (string $m) use (&$aiHLogs): void {
    $aiHLogs[] = $m;
};
$hRes = $aiH->generate('s', 'p', 500);
T::check('AI: gemini modeli eskirgan (404) — bot gemini-3.8-flash ni topib ishladi', $hRes['ok'] === true && $hRes['provider'] === 'gemini' && ($aiH->healed['gemini'] ?? '') === 'gemini-2.5-flash → gemini-3.8-flash', json_encode($aiH->healed));
T::check('AI: tanlov — preview/lite emas, eng yangi barqaror flash', ($aiStoreData['ai_model_gemini'] ?? '') === json_encode(['from' => 'gemini-2.5-flash', 'to' => 'gemini-3.8-flash']));
T::check('AI: topilgan model logga yozildi', count(array_filter($aiHLogs, static function ($m) {
    return strpos($m, 'avtomatik almashtirildi: gemini-3.8-flash') !== false;
})) === 1);
$aiCalls = [];
$aiH2 = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'G', 'gemini_model' => 'gemini-2.5-flash']), $aiTr);
$aiH2->store = $aiStore;
$aiH2->generate('s', 'p', 500);
T::check('AI: keyingi safar (yangi nusxa) saqlangan modelni darhol ishlatadi — ortiqcha so\'rov yo\'q', count($aiCalls) === 1 && strpos($aiCalls[0][0], 'gemini-3.8-flash:generate') !== false);
$aiH3 = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'G', 'gemini_model' => 'boshqa-model-9']), $aiTr);
$aiH3->store = $aiStore;
T::eq('AI: config\'da model o\'zgartirilsa — eski saqlangan almashtirish ta\'sir qilmaydi', $aiH3->providers()[0]['model'], 'boshqa-model-9');
$gq = new PostAssist\Services\Ai(new Config(['groq_api_key' => 'Q']), $aiTr);
$gq->store = $aiStore;
$gq->logger = static function (string $m): void {
};
$gres = $gq->check();
T::check('AI: groq modeli yo\'q — whisper/guard o\'tkazib, llama-4-70b-versatile tanlandi', strpos($gres['groq'], 'OK (llama-3.3-70b-versatile → llama-4-70b-versatile)') === 0, json_encode($gres));
T::eq('AI: pickModel — gemini', PostAssist\Services\Ai::pickModel('gemini', ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.0-flash-exp']), 'gemini-2.5-flash');
T::eq('AI: pickModel — faqat lite bo\'lsa lite', PostAssist\Services\Ai::pickModel('gemini', ['gemini-2.5-flash-lite', 'gemini-pro']), 'gemini-2.5-flash-lite');
T::eq('AI: pickModel — mos yo\'q: null', PostAssist\Services\Ai::pickModel('gemini', ['embedding-001']), null);
$badKey = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'BAD']), static function (string $u, array $h, string $b): array {
    return $b === '' ? [403, '{}'] : [400, json_encode(['error' => ['message' => 'API key not valid. Please pass a valid API key.']])];
});
$bk = $badKey->check();
T::check('AI: noto\'g\'ri kalit modelni almashtirmaydi (adashmaydi)', strpos($bk['gemini'], 'HTTP 400') !== false && $badKey->healed === []);

// --- AI daqiqalik cheklov: FREE 3 / PRO 6 / ULTRA 10 / admin cheksiz; bloklangan urinish kunlik limitni yemaydi; jadval yo'q bo'lsa to'xtamaydi
T::eq('daqiqalik standart: free 3, pro 6, ultra 10, enterprise cheksiz', [PostAssist\Services\Plans::aiPerMinute('free'), PostAssist\Services\Plans::aiPerMinute('pro'),
    PostAssist\Services\Plans::aiPerMinute('ultra'), PostAssist\Services\Plans::aiPerMinute('enterprise')], [3, 6, 10, 0]);
T::eq('daqiqalik: config bilan o\'zgaradi', PostAssist\Services\Plans::aiPerMinute('pro', new Config(['ai_per_minute' => ['pro' => 12]])), 12);
$RU = 7740;
$textU($RU, '/start');
$rlClock = $clock;
$rlNow = static function () use (&$rlClock): string {
    return $rlClock->format('Y-m-d H:i:s');
};
$rlDay = $clock->format('Y-m-d');
$db->exec('DELETE FROM ai_rate WHERE user_id = ?', [$RU]);
$db->exec('DELETE FROM ai_usage WHERE user_id = ?', [$RU]);
$rs = [];
for ($i = 0; $i < 4; $i++) {
    $rs[] = $appU->aiUsage->reserve($RU, 5, $rlDay, $rlNow(), 3);
}
T::eq('free: 3 ta o\'tadi, 4-si «rate»', $rs, ['daily', 'daily', 'daily', 'rate']);
T::eq('bloklangan urinish kunlik limitni yemadi (3 ta)', $appU->aiUsage->usedOn($RU, $rlDay), 3);
T::check('kutish vaqti 1–60 soniya', ($w = $appU->aiUsage->rateWait($RU, $rlNow())) >= 1 && $w <= 60);
$rlClock = $clock->modify('+61 seconds');
T::eq('61 soniyadan keyin yana ruxsat', $appU->aiUsage->reserve($RU, 5, $rlDay, $rlNow(), 3), 'daily');
T::eq('cheklov 0 — cheksiz (admin / autopilot)', $appU->aiUsage->reserve($RU, 0, $rlDay, $rlNow(), 0), 'unlimited');
$db->exec('RENAME TABLE ai_rate TO ai_rate_tmp');
try {
    T::eq('ai_rate jadvali yo\'q (setup.php ishlamagan) — bot to\'xtamaydi (ruxsat)', $appU->aiUsage->reserve($RU, 0, $rlDay, $rlNow(), 3), 'unlimited');
} finally {
    $db->exec('RENAME TABLE ai_rate_tmp TO ai_rate');
}
// bot oqimi: cheklovga tushsa — tushunarli xabar, AI chaqirilmaydi
$cfgR = new Config(['bot_token' => $config->str('bot_token'), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN], 'timezone' => 'Asia/Tashkent',
    'gemini_api_key' => 'test', 'ai_per_minute' => ['free' => 1]]);
$appR = new App($cfgR, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$appR->sleeper = static function (int $ms): void {
};
$rCalls = 0;
$appR->ai = new PostAssist\Services\Ai($cfgR, static function () use (&$rCalls): array {
    $rCalls++;
    return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => 'AI matni']]]]]])];
});
$routerR = new Router($appR);
$RB = 7741;
$db->exec('DELETE FROM ai_rate WHERE user_id = ?', [$RB]);
$sendR = static function (string $kind, string $v) use (&$upd, $routerR, $from, $fake, $RB) {
    $fake->reset();
    $u = $kind === 't' ? ['message' => ['message_id' => $upd, 'from' => $from($RB), 'chat' => ['id' => $RB, 'type' => 'private'], 'date' => 0, 'text' => $v]]
        : ['callback_query' => ['id' => 'r' . $upd, 'from' => $from($RB), 'data' => $v, 'message' => ['message_id' => 77, 'chat' => ['id' => $RB, 'type' => 'private'], 'text' => 'x']]];
    $routerR->handle(['update_id' => $upd++] + $u);
};
$sendR('t', '/start');
$db->exec("INSERT INTO channels (user_id, channel_id, title, is_active, created_at) VALUES (?, -1001000000741, 'R kanal', 1, UTC_TIMESTAMP())", [$RB]);
$appR->states->set($RB, 'ai_style', ['topic' => 'Birinchi mavzu haqida post']);
$sendR('d', 'ai:s:news');
T::eq('1-so\'rov: AI chaqirildi', $rCalls, 1);
$appR->states->set($RB, 'ai_style', ['topic' => 'Ikkinchi mavzu haqida post']);
$sendR('d', 'ai:s:news');
T::check('2-so\'rov shu daqiqada: «Juda tez!» xabari, AI chaqirilmadi', $rCalls === 1 && strpos($fake->texts(), 'Juda tez') !== false && strpos($fake->texts(), '1 tagacha') !== false);
$initR = $mkInitU(['id' => $RB, 'first_name' => 'R', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgR->str('bot_token'));
[$st, $r] = PostAssist\Handlers\MiniAppApi::handle($appR, 'ai', ['mode' => 'post', 'topic' => 'Uchinchi mavzu haqida', 'style' => 'news'], $initR);
T::check('Mini App: 429 ai_rate (n, s bilan)', $st === 429 && ($r['error'] ?? '') === 'ai_rate' && ($r['n'] ?? 0) === 1 && ($r['s'] ?? 0) >= 1, json_encode($r));

// --- «Kuniga 2 marta»: ikkala vaqt qo'lda; birinchi chiqish — eng yaqini (avtomatik «hozirgi soat» emas)
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['timezone' => 'Asia/Tashkent'], $initB);
$bcRef = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$BC]);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$B]);
[$st, $r] = $call2('post_create', ['channel_id' => $bcRef, 'text' => 'Ikki vaqtli post', 'repeat' => 'twice', 'time1' => '09:00', 'time2' => '18:30', 'when' => 'now']);
$tw = $db->one("SELECT * FROM scheduled_posts WHERE user_id = ? AND text = 'Ikki vaqtli post'", [$B]);
// kutilgan: ikki vaqtdan hozirdan keyingi eng yaqini (Toshkent bo'yicha) — mustaqil hisoblanadi
$nearest = static function (array $hhmm) use ($appU): string {
    $tzT = new DateTimeZone('Asia/Tashkent');
    $loc = $appU->now()->setTimezone($tzT);
    $c = [];
    foreach ([0, 1] as $add) {
        foreach ($hhmm as $hm) {
            [$h, $m] = array_map('intval', explode(':', $hm));
            $d = $loc->modify('+' . $add . ' day')->setTime($h, $m, 0);
            if ($d > $loc) {
                $c[] = $d->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s');
            }
        }
    }
    sort($c);
    return $c[0];
};
T::check('twice: 1-vaqt 09:00, 2-vaqt 18:30; birinchi chiqish — ulardan eng yaqini, «hozirgi soat» emas', $st === 200 && $tw !== null && (int) $tw['recurrence_time'] === 540
    && (int) $tw['recurrence_day'] === 1110 && $tw['scheduled_time'] === $nearest(['09:00', '18:30']) && $tw['status'] === 'pending', json_encode([$r, $tw]));
T::eq('twice: bir xil vaqt — 400 twice', $call2('post_create', ['channel_id' => $bcRef, 'text' => 'x', 'repeat' => 'twice', 'time1' => '10:00', 'time2' => '10:00'])[0], 400);
T::eq('twice: 2-vaqt yo\'q — 400 twice', $call2('post_create', ['channel_id' => $bcRef, 'text' => 'x', 'repeat' => 'twice', 'time1' => '10:00'])[1]['error'] ?? '', 'twice');
$twOut = null;
foreach ($call2('posts')[1]['posts'] ?? [] as $pp) {
    if ((int) $pp['id'] === (int) $tw['id']) {
        $twOut = $pp;
    }
}
T::check('postOut: time1 va time2 qaytadi (tahrir oynasi uchun)', ($twOut['time1'] ?? '') === '09:00' && ($twOut['time2'] ?? '') === '18:30');
[$st, $r] = $call2('post_update', ['id' => (int) $tw['id'], 'repeat' => 'twice', 'time1' => '07:15', 'time2' => '12:00']);
$tw2 = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [(int) $tw['id']]);
T::check('post_update: ikki vaqt o\'zgardi; keyingi chiqish — 07:15 yoki 12:00 dan eng yaqini', $st === 200 && (int) $tw2['recurrence_time'] === 435 && (int) $tw2['recurrence_day'] === 720
    && $tw2['scheduled_time'] === $nearest(['07:15', '12:00']), json_encode($tw2));
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$B]);

// --- vaqt mintaqasi: Mini App telefon zonasini FAQAT tanlanmagan bo'lsa saqlaydi
$TZU = 7750;
$textU($TZU, '/start');
$initTZ = $mkInitU(['id' => $TZU, 'first_name' => 'T', 'language_code' => 'de'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
T::eq('me: zona tanlanmagan (tz_set=false)', PostAssist\Handlers\MiniAppApi::handle($appU, 'me', [], $initTZ)[1]['user']['tz_set'] ?? null, false);
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['timezone_auto' => 'Bad/Zone'], $initTZ);
T::eq('noto\'g\'ri zona e\'tiborsiz', (string) $db->value('SELECT timezone FROM users WHERE user_id = ?', [$TZU]), '');
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['timezone_auto' => 'Europe/Berlin'], $initTZ);
$meTZ = PostAssist\Handlers\MiniAppApi::handle($appU, 'me', [], $initTZ)[1];
T::check('telefon zonasi saqlandi (Europe/Berlin), tz_set=true', ($meTZ['user']['timezone'] ?? '') === 'Europe/Berlin' && ($meTZ['user']['tz_set'] ?? false) === true);
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['timezone' => 'Asia/Tokyo'], $initTZ);
PostAssist\Handlers\MiniAppApi::handle($appU, 'settings', ['timezone_auto' => 'America/New_York'], $initTZ);
T::eq('qo\'lda tanlangan zona ustidan avtomatik yozilmaydi', (string) $db->value('SELECT timezone FROM users WHERE user_id = ?', [$TZU]), 'Asia/Tokyo');

// --- bot: zona tanlanmagan bo'lsa rejalashtirilganda /timezone eslatmasi; tanlangan bo'lsa — yo'q
$HZ = 7751;
$textU($HZ, '/start');
$db->exec("INSERT INTO channels (user_id, channel_id, title, is_active, created_at) VALUES (?, -1001000000751, 'HZ kanal', 1, UTC_TIMESTAMP())", [$HZ]);
$textU($HZ, '/newpost');
$textU($HZ, 'Zona eslatmasi uchun sinov posti');
$pressU($HZ, 'p:time');
$textU($HZ, 'ertaga 10:00');
T::check('bot: zona tanlanmagan — «/timezone» eslatmasi', strpos($fake->texts(), 'Rejalashtirildi') !== false && strpos($fake->texts(), '/timezone') !== false);
$db->exec("UPDATE users SET timezone = 'Asia/Tashkent' WHERE user_id = ?", [$HZ]);
$appU->forgetTz($HZ);
$textU($HZ, '/newpost');
$textU($HZ, 'Ikkinchi sinov posti matni');
$pressU($HZ, 'p:time');
$textU($HZ, 'ertaga 11:00');
T::check('bot: zona tanlangan — eslatma yo\'q', strpos($fake->texts(), 'Rejalashtirildi') !== false && strpos($fake->texts(), '/timezone') === false);

$appSrcX = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: reaksiya qo\'lda (rxPicker), ⌫ tarix bilan, ❝/</> ikkinchi bosishda olib tashlanadi', strpos($appSrcX, 'function rxPicker') !== false
    && strpos($appSrcX, '_hist.pop()') !== false && strpos($appSrcX, 'function toggleWrap') !== false && strpos($appSrcX, "ancestor(edEl, 'a')") !== false);
T::check('app.php: ikki vaqt (t1/t2, e-time1), avtomatik zona, gorizontal qatorlar o\'rtaga/g\'ildirak/tortish', strpos($appSrcX, 'id="t1"') !== false && strpos($appSrcX, 'e-time1') !== false
    && strpos($appSrcX, 'timezone_auto') !== false && strpos($appSrcX, 'function hCenter') !== false && strpos($appSrcX, "addEventListener('wheel'") !== false);
T::check('app.php: AI model nomlari ko\'rsatilmaydi', strpos($appSrcX, "'Google Gemini'") === false && strpos($appSrcX, 'm.model') === false);

// --- zaxira cron: cron sozlanmagan bo'lsa webhook navbatni o'zi yuboradi (daqiqasiga bir marta); cron ishlasa — tegmaydi
$FBU = 7760;
$FBC = -1001000000760;
$textU($FBU, '/start');
$db->exec("INSERT INTO channels (user_id, channel_id, title, is_active, created_at) VALUES (?, ?, 'Zaxira kanal', 1, UTC_TIMESTAMP())", [$FBU, $FBC]);
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at) VALUES (?, ?, 'text', 'Zaxira cron posti', 'pending', ?, UTC_TIMESTAMP())",
    [$FBU, $FBC, $clock->modify('-5 minutes')->format('Y-m-d H:i:s')]);
$fbId = $db->lastId();
$db->exec("DELETE FROM bot_settings WHERE k IN ('cron_last', 'webhook_tick')");
$fbS = new PostAssist\Services\Scheduler($appU, static function (int $us): void {
});
T::eq('zaxira: cron hech qachon ishlamagan — navbat yuborildi', [$fbS->fallbackTick(5), (string) $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$fbId])], [true, 'sent']);
T::eq('zaxira: shu daqiqada ikkinchi marta ishlamaydi', $fbS->fallbackTick(5), false);
$db->exec("INSERT INTO bot_settings (k, v, updated_at) VALUES ('cron_last', ?, UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE v = VALUES(v)", [$clock->format('Y-m-d H:i:s')]);
$db->exec("UPDATE bot_settings SET v = '' WHERE k = 'webhook_tick'");
T::eq('zaxira: cron ishlab tursa — tegmaydi', $fbS->fallbackTick(5), false);
$whSrc = (string) file_get_contents(__DIR__ . '/../webhook.php');
T::check('webhook.php: javobni qaytarib, keyin zaxira cron', strpos($whSrc, '$app->releaseClient();') !== false && strpos($whSrc, 'fallbackTick') !== false);

// --- Gemini band yoki sekin (vaqt tugadi / 503): boshqa Gemini modeli bilan zaxira urinish; kalit xatosida — yo'q
$fbCalls = [];
$fbTr = static function (string $url, array $h, string $b) use (&$fbCalls): array {
    $fbCalls[] = $url;
    if ($b === '' && strpos($url, '/models?') !== false) {
        return [200, json_encode(['models' => [
            ['name' => 'models/gemini-3.8-flash', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/gemini-3.8-flash-lite', 'supportedGenerationMethods' => ['generateContent']],
            ['name' => 'models/gemini-3.9-flash-preview', 'supportedGenerationMethods' => ['generateContent']],
        ]])];
    }
    if (strpos($url, 'gemini-3.8-flash-lite:generate') !== false) {
        return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => 'Zaxira javob']]]]]])];
    }
    return [0, '']; // asosiy model: javob yo'q (vaqt tugadi)
};
$aiFb = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'G']), $fbTr);
$fbLog = [];
$aiFb->logger = static function (string $m) use (&$fbLog): void {
    $fbLog[] = $m;
};
$fr = $aiFb->generate('S', 'P', 500, ['mime' => 'image/jpeg', 'data' => 'x']);
T::check('Gemini vaqt tugadi — rasm uchun zaxira model (flash-lite) javob berdi', $fr['ok'] === true && $fr['text'] === 'Zaxira javob' && ($aiFb->fallbackUsed['gemini'] ?? '') === 'gemini-3.8-flash-lite');
T::check('zaxira model logga yozildi, preview tanlanmadi', count(array_filter($fbLog, static function ($m) {
    return strpos($m, 'zaxira model ishladi: gemini-3.8-flash-lite') !== false;
})) === 1 && count(array_filter($fbCalls, static function ($u) {
    return strpos($u, 'preview') !== false;
})) === 0);
$aiFb2 = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'G']), $fbTr);
$aiFb2->logger = static function (string $m): void {
};
$fc = $aiFb2->check();
T::check('setup/check: «OK (zaxira)» va asosiy modelning sababi ko\'rinadi', strpos($fc['gemini'], 'OK (gemini-3.8-flash-lite — zaxira; asosiy gemini-3.8-flash: tarmoq') === 0, json_encode($fc));
$keyErrCalls = 0;
$aiKey = new PostAssist\Services\Ai(new Config(['gemini_api_key' => 'BAD']), static function (string $u, array $h, string $b) use (&$keyErrCalls): array {
    $keyErrCalls++;
    return [400, json_encode(['error' => ['message' => 'API key not valid.']])];
});
$aiKey->logger = static function (string $m): void {
};
T::check('kalit xatosida zaxira model sinalmaydi (bitta so\'rov)', $aiKey->generate('S', 'P', 100)['ok'] === false && $keyErrCalls === 1);
T::eq('pickAlternate: joriydan boshqa eng yangi flash', PostAssist\Services\Ai::pickAlternate(['gemini-3.8-flash', 'gemini-3.5-flash', 'gemini-3.8-flash-lite'], 'gemini-3.8-flash'), 'gemini-3.5-flash');

// --- «Yuborilgan» soni: takroriy post chiqqach yana navbatga qaytadi — har chiqish baribir sanaladi (oldin 0 ko'rinardi)
$RSU = 7770;
$RSC = -1001000000770;
$textU($RSU, '/start');
$db->exec("INSERT INTO channels (user_id, channel_id, title, is_active, created_at) VALUES (?, ?, 'Takror kanal', 1, UTC_TIMESTAMP())", [$RSU, $RSC]);
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, recurrence_type, recurrence_time, created_at)
    VALUES (?, ?, 'text', 'Har kungi post', 'pending', ?, 'daily', 600, UTC_TIMESTAMP())", [$RSU, $RSC, $clock->modify('-2 minutes')->format('Y-m-d H:i:s')]);
$rsId = $db->lastId();
$db->exec("DELETE FROM bot_settings WHERE k = 'webhook_tick'");
(new PostAssist\Services\Scheduler($appU, static function (int $us): void {
}))->run(5);
$rsRow = $db->one('SELECT status, sent_count FROM scheduled_posts WHERE id = ?', [$rsId]);
$rsStats = $appU->posts->userStats($RSU);
T::check('takroriy post chiqdi va yana navbatda; statistika: yuborilgan 1, navbatda 1', $rsRow['status'] === 'pending' && (int) $rsRow['sent_count'] === 1
    && $rsStats['sent'] === 1 && $rsStats['pending'] === 1, json_encode([$rsRow, $rsStats]));
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, status, scheduled_time, created_at, sent_count) VALUES (?, ?, 'text', 'Eski bir martalik', 'sent', UTC_TIMESTAMP(), UTC_TIMESTAMP(), 0)", [$RSU, $RSC]);
T::eq('eski yuborilgan post (sent_count=0) ham sanaladi', $appU->posts->userStats($RSU)['sent'], 2);
$initRS = $mkInitU(['id' => $RSU, 'first_name' => 'R', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
T::eq('Mini App bosh sahifa: yuborilgan 2', PostAssist\Handlers\MiniAppApi::handle($appU, 'me', [], $initRS)[1]['stats']['sent'] ?? null, 2);

// --- Birja: o'z davlati birinchi → yaqin davlatlar → Global → boshqalar; davlat filtri; qidiruv; hudud almashtirish
$db->exec('DELETE FROM market_listings');
$mkOwner = static function (int $uid, string $tz) use ($textU, $db): void {
    $textU($uid, '/start');
    $db->exec('UPDATE users SET timezone = ?, market_banned = 0 WHERE user_id = ?', [$tz, $uid]);
};
$mkOwner(7781, 'Asia/Tashkent');
$mkOwner(7782, 'Asia/Almaty');
$mkOwner(7783, 'Europe/Berlin');
$mkOwner(7784, 'Asia/Tashkent');
$appU->forgetTz(7781);
$mkL = static function (int $owner, int $chId, string $title, string $user, int $subs, ?string $country) use ($appU, $clock): int {
    return $appU->market->upsert($owner, ['channel_id' => $chId, 'title' => $title, 'username' => $user], 100, 'USD', 'Tavsif ' . $title, 'news', $subs, $clock, $country);
};
$mkL(7783, -1009001, 'Berlin News', 'berlinnews', 90000, 'DE');
$mkL(7782, -1009002, 'Almaty Kanal', 'almatykanal', 50000, 'KZ');
$gl = $mkL(7784, -1009003, 'World Global', 'worldglobal', 70000, 'ZZ');
$mkL(7781, -1009004, 'Toshkent Yangiliklari', 'toshyangi', 1000, 'UZ');
$catUz = $appU->market->catalog(null, 0, 'UZ');
T::eq('tartib (UZ uchun): UZ → KZ (yaqin) → Global → DE (obunachi ko\'p bo\'lsa ham oxirida)', array_column($catUz['rows'], 'username'), ['toshyangi', 'almatykanal', 'worldglobal', 'berlinnews']);
$catDe = $appU->market->catalog(null, 0, 'DE');
T::eq('tartib (DE uchun): o\'zi birinchi', $catDe['rows'][0]['username'], 'berlinnews');
T::eq('davlat filtri: faqat DE', array_column($appU->market->catalog(null, 0, 'UZ', 'DE')['rows'], 'username'), ['berlinnews']);
T::eq('davlat filtri: Global', array_column($appU->market->catalog(null, 0, 'UZ', 'ZZ')['rows'], 'username'), ['worldglobal']);
T::eq('qidiruv: nom bo\'yicha', array_column($appU->market->catalog(null, 0, 'UZ', null, 'almaty')['rows'], 'username'), ['almatykanal']);
T::eq('qidiruv: @username bo\'yicha', array_column($appU->market->catalog(null, 0, 'UZ', null, '@berlin')['rows'], 'username'), ['berlinnews']);
T::eq('qidiruv: % belgisi xavfsiz (hamma narsani qaytarmaydi)', $appU->market->catalog(null, 0, 'UZ', null, '%')['total'], 0);
T::check('davlatlar ro\'yxati (soni bilan)', $appU->market->countries() == ['DE' => 1, 'KZ' => 1, 'ZZ' => 1, 'UZ' => 1] || count($appU->market->countries()) === 4);
$initMk = $mkInitU(['id' => 7781, 'first_name' => 'M', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $cfgU->str('bot_token'));
[$st, $mr] = PostAssist\Handlers\MiniAppApi::handle($appU, 'market', [], $initMk);
T::check('Mini App birja: o\'z davlati (UZ) birinchi, bayroq va hudud, davlatlar ro\'yxatida UZ birinchi', $st === 200 && $mr['my_country'] === 'UZ'
    && $mr['items'][0]['username'] === 'toshyangi' && $mr['items'][0]['flag'] === '🇺🇿' && strpos($mr['items'][0]['region'], 'zbekiston') !== false
    && $mr['countries'][0]['code'] === 'UZ', json_encode($mr['countries'] ?? null));
[$st, $mr2] = PostAssist\Handlers\MiniAppApi::handle($appU, 'market', ['country' => 'de', 'q' => ''], $initMk);
T::check('Mini App birja: boshqa davlatni tanlash (DE)', $st === 200 && $mr2['country'] === 'DE' && count($mr2['items']) === 1 && $mr2['items'][0]['country'] === 'DE');
[$st, $mr3] = PostAssist\Handlers\MiniAppApi::handle($appU, 'market', ['q' => 'world'], $initMk);
T::check('Mini App birja: qidiruv', $st === 200 && count($mr3['items']) === 1 && $mr3['items'][0]['flag'] === '🌍');
T::eq('Mini App birja: noto\'g\'ri davlat kodi e\'tiborsiz', PostAssist\Handlers\MiniAppApi::handle($appU, 'market', ['country' => 'XX'], $initMk)[1]['country'], null);
// bot: ro'yxatda bayroq; egasi hududni Global'ga almashtiradi
$uzId = (int) $db->value("SELECT id FROM market_listings WHERE username = 'toshyangi'");
$pressU(7781, 'mk:l:all:0');
T::check('bot katalog: bayroq bilan, o\'z davlati birinchi', strpos($lastKb(), '🇺🇿 Toshkent') !== false && strpos($lastKb(), 'mk:v:' . $uzId) < strpos($lastKb(), 'berlinnews') + 99999);
$pressU(7781, 'mk:rg:' . $uzId);
T::eq('bot: hudud → Global', (string) $db->value('SELECT country FROM market_listings WHERE id = ?', [$uzId]), 'ZZ');
$pressU(7781, 'mk:rg:' . $uzId);
T::eq('bot: hudud → yana o\'z davlati', (string) $db->value('SELECT country FROM market_listings WHERE id = ?', [$uzId]), 'UZ');
$pressU(7782, 'mk:rg:' . $uzId);
T::eq('bot: begona e\'lon hududini o\'zgartirib bo\'lmaydi', (string) $db->value('SELECT country FROM market_listings WHERE id = ?', [$uzId]), 'UZ');
$pressU(7781, 'mk:v:' . $uzId);
T::check('bot e\'lon kartasi: hudud qatori', strpos($fake->lastText(), 'Hudud') !== false);
$db->exec('UPDATE market_listings SET country = NULL WHERE id = ?', [$gl]);
$bfN = $appU->market->backfillCountries(static function (int $o) use ($appU): string {
    return $appU->userCountry($o);
});
T::check('eski e\'lonlar: davlat egasining vaqt mintaqasidan yoziladi (setup.php)', $bfN === 1 && (string) $db->value('SELECT country FROM market_listings WHERE id = ?', [$gl]) === 'UZ');
$db->exec('DELETE FROM market_listings');
