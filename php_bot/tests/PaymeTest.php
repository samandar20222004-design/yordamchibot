<?php
// 9-bosqich: Payme Merchant API (AutopilotTest.php dan keyin).
declare(strict_types=1);

use PostAssist\App;
use PostAssist\Config;
use PostAssist\Router;
use PostAssist\Services\Payme;
use PostAssist\Telegram;

T::section('U. Payme (Merchant API)');
$clock = new DateTimeImmutable('2027-01-10 10:00:00', new DateTimeZone('UTC'));
T::eq('sukut: Payme o\'chiq', Payme::enabled($app), false);
$cfgP = new Config(['bot_token' => $config->str('bot_token'), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN], 'timezone' => 'Asia/Tashkent',
    'payme_merchant_id' => 'MERCH123', 'payme_key' => 'SeCrEt-KeY', 'payme_test' => true]);
$appP = new App($cfgP, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$routerP = new Router($appP);
$pressP = static function (int $uid, string $data) use (&$upd, $routerP, $from, $fake) {
    $fake->reset();
    $routerP->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'c' . $upd, 'from' => $from($uid), 'data' => $data,
        'message' => ['message_id' => 77, 'chat' => ['id' => $uid, 'type' => 'private'], 'text' => 'eski']]]);
};
$kbP = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$pm = new Payme($appP);
$AUTH = 'Basic ' . base64_encode('Paycom:SeCrEt-KeY');
$rpc = static function (string $method, array $params, ?string $auth = null) use ($pm, $AUTH): array {
    return $pm->handle(['jsonrpc' => '2.0', 'id' => 7, 'method' => $method, 'params' => $params], $auth ?? $AUTH);
};
$errCode = static function (array $r): ?int {
    return isset($r['error']['code']) ? (int) $r['error']['code'] : null;
};

// --- autentifikatsiya
T::eq('noto\'g\'ri kalit: -32504', $errCode($rpc('CheckTransaction', ['id' => 'x'], 'Basic ' . base64_encode('Paycom:wrong'))), -32504);
T::eq('sarlavhasiz: -32504', $errCode($pm->handle(['id' => 1, 'method' => 'CheckTransaction', 'params' => []], null)), -32504);
T::eq('kalit sozlanmagan bo\'lsa hamma narsa rad', $errCode((new Payme($app))->handle(['id' => 1, 'method' => 'CheckTransaction', 'params' => []], $AUTH)), -32504);
T::eq('noma\'lum metod: -32601', $errCode($rpc('Hack', [])), -32601);
T::eq('params yo\'q: -32600', $errCode($pm->handle(['id' => 1, 'method' => 'CheckTransaction'], $AUTH)), -32600);
$r = $rpc('Hack', []);
T::check('xato xabari uch tilda, id qaytariladi', isset($r['error']['message']['uz'], $r['error']['message']['ru'], $r['error']['message']['en']) && $r['id'] === 7);

// --- botda: faqat Payme sozlangan (karta yo'q)
$PU = 9700;
$text($PU, '/start');
$appP->users->markUzVerified($PU);
$pressP($PU, 'pl:show');
T::check('Payme bor: tariflarda «So\'m» tugmasi', strpos($kbP(), 'pl:card') !== false);
$pressP($PU, 'pl:cb:1m');
T::check('faqat Payme: Payme ma\'lumoti va tugma (chek kutilmaydi)', strpos($fake->lastText(), 'Payme') !== false && strpos($kbP(), 'pl:pm:1m') !== false
    && ($appP->states->get($PU)['state'] ?? '') !== 'receipt_wait');
$pressP($PU, 'pl:pm:1m');
$kb = json_decode($kbP(), true);
$url = (string) ($kb['inline_keyboard'][0][0]['url'] ?? '');
T::check('to\'lov havolasi: sinov muhiti', strpos($url, 'https://checkout.test.paycom.uz/') === 0);
$dec = (string) base64_decode(substr($url, strlen('https://checkout.test.paycom.uz/')));
$order = $db->one('SELECT * FROM payme_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 1', [$PU]);
T::check('havolada merchant, buyurtma va summa (tiyin)', $order !== null && strpos($dec, 'm=MERCH123') !== false && strpos($dec, 'ac.order_id=' . $order['order_id']) !== false
    && strpos($dec, 'a=' . $order['amount_tiyin']) !== false && strpos($dec, 'l=uz') !== false);
T::check('buyurtma: PRO 1 oy, 30 kun, pending', $order['tier'] === 'pro' && (int) $order['days'] === 30 && $order['status'] === 'pending' && (int) $order['amount_tiyin'] > 0);
$OID = (string) $order['order_id'];
$AMT = (int) $order['amount_tiyin'];
$NV = 9701;
$text($NV, '/start');
$pressP($NV, 'pl:pm:1m');
T::check('UZ tasdiqlanmagan: avval telefon so\'raladi', ($appP->states->get($NV)['state'] ?? '') === 'uz_verify');
$pressP($ADMIN, 'pl:pm:1m');
T::check('admin/muddatsiz: to\'lov kerak emas', strpos($fake->lastText(), 'cheksiz') !== false || strpos($fake->lastText(), '♾') !== false || strpos($fake->lastText(), 'kerak emas') !== false);

// --- CheckPerformTransaction
T::eq('noto\'g\'ri summa: -31001', $errCode($rpc('CheckPerformTransaction', ['amount' => $AMT - 100, 'account' => ['order_id' => $OID]])), -31001);
T::eq('noma\'lum buyurtma: -31050', $errCode($rpc('CheckPerformTransaction', ['amount' => $AMT, 'account' => ['order_id' => 'pmnope']])), -31050);
T::eq('account yo\'q: -32600', $errCode($rpc('CheckPerformTransaction', ['amount' => $AMT])), -32600);
T::eq('to\'g\'ri: allow', $rpc('CheckPerformTransaction', ['amount' => $AMT, 'account' => ['order_id' => $OID]])['result'] ?? null, ['allow' => true]);

// --- CreateTransaction
$t0 = (int) $clock->format('U') * 1000;
$c1 = $rpc('CreateTransaction', ['id' => 'pay_A', 'time' => $t0, 'amount' => $AMT, 'account' => ['order_id' => $OID]]);
T::check('yaratildi: state 1', ($c1['result']['state'] ?? null) === 1 && ($c1['result']['create_time'] ?? 0) === $t0);
$c1b = $rpc('CreateTransaction', ['id' => 'pay_A', 'time' => $t0, 'amount' => $AMT, 'account' => ['order_id' => $OID]]);
T::eq('takror Create: o\'sha natija', $c1b['result'] ?? null, $c1['result']);
T::eq('boshqa Payme id, o\'sha buyurtma: -31052 band', $errCode($rpc('CreateTransaction', ['id' => 'pay_B', 'time' => $t0, 'amount' => $AMT, 'account' => ['order_id' => $OID]])), -31052);
T::eq('Perform\'dan oldin tarif yo\'q', $appP->tier($PU), 'free');

// --- PerformTransaction
$fake->reset();
$clock = $clock->modify('+2 minutes');
$p1 = $rpc('PerformTransaction', ['id' => 'pay_A']);
T::check('bajarildi: state 2', ($p1['result']['state'] ?? null) === 2 && ($p1['result']['perform_time'] ?? 0) > 0);
T::eq('tarif yoqildi: PRO', $appP->tier($PU), 'pro');
$exp1 = $db->value('SELECT subscription_expires_at FROM users WHERE user_id = ?', [$PU]);
T::check('foydalanuvchiga va adminga xabar', strpos($fake->texts(), 'To\'lov qabul qilindi') !== false && strpos($fake->texts(), 'Payme to\'lovi') !== false);
T::eq('payments: bitta qator (payme)', (int) $db->value("SELECT COUNT(*) FROM payments WHERE charge_id = 'payme_pay_A' AND provider = 'payme'"), 1);
$fake->reset();
$clock = $clock->modify('+1 minute');
$p2 = $rpc('PerformTransaction', ['id' => 'pay_A']);
T::eq('takror Perform: o\'sha natija', $p2['result'] ?? null, $p1['result']);
T::check('takror Perform: tarif ikki marta berilmadi, xabar yo\'q', $db->value('SELECT subscription_expires_at FROM users WHERE user_id = ?', [$PU]) === $exp1 && $fake->texts() === '');
T::eq('to\'langan buyurtma: -31051', $errCode($rpc('CheckPerformTransaction', ['amount' => $AMT, 'account' => ['order_id' => $OID]])), -31051);
T::eq('to\'langan buyurtmaga yangi Create: -31051', $errCode($rpc('CreateTransaction', ['id' => 'pay_C', 'time' => $t0, 'amount' => $AMT, 'account' => ['order_id' => $OID]])), -31051);
$ck = $rpc('CheckTransaction', ['id' => 'pay_A']);
T::check('CheckTransaction: holat 2, vaqtlar', ($ck['result']['state'] ?? null) === 2 && $ck['result']['create_time'] === $t0 && $ck['result']['perform_time'] > 0 && $ck['result']['reason'] === null);
T::eq('CheckTransaction: topilmadi -31003', $errCode($rpc('CheckTransaction', ['id' => 'nope'])), -31003);
$gs = $rpc('GetStatement', ['from' => $t0 - 1000, 'to' => $t0 + 1000]);
T::check('GetStatement: tranzaksiya bor', count($gs['result']['transactions'] ?? []) === 1 && $gs['result']['transactions'][0]['account']['order_id'] === $OID);
T::eq('GetStatement: to < from rad', $errCode($rpc('GetStatement', ['from' => 10, 'to' => 5])), -32600);
T::eq('bajarilganni bekor qilib bo\'lmaydi (qaytarish o\'chiq): -31007', $errCode($rpc('CancelTransaction', ['id' => 'pay_A', 'reason' => 5])), -31007);
T::eq('tarif saqlandi', $appP->tier($PU), 'pro');

// --- yaratilganni bekor qilish va timeout
$o2 = $pm->createOrder($PU, 'u1m');
$c2 = $rpc('CreateTransaction', ['id' => 'pay_D', 'time' => $t0, 'amount' => $o2['amount_tiyin'], 'account' => ['order_id' => $o2['order_id']]]);
$x = $rpc('CancelTransaction', ['id' => 'pay_D', 'reason' => 3]);
T::check('yaratilgan bekor: state -1, buyurtma ochiq', ($x['result']['state'] ?? null) === -1
    && $db->value('SELECT status FROM payme_orders WHERE order_id = ?', [$o2['order_id']]) === 'pending');
T::eq('takror Cancel: o\'sha natija', $rpc('CancelTransaction', ['id' => 'pay_D', 'reason' => 3])['result'] ?? null, $x['result']);
T::eq('bekor qilinganni bajarib bo\'lmaydi: -31008', $errCode($rpc('PerformTransaction', ['id' => 'pay_D'])), -31008);
$c3 = $rpc('CreateTransaction', ['id' => 'pay_E', 'time' => $t0, 'amount' => $o2['amount_tiyin'], 'account' => ['order_id' => $o2['order_id']]]);
T::eq('bekordan keyin yangi urinish mumkin', $c3['result']['state'] ?? null, 1);
$clock = $clock->modify('+13 hours');
T::eq('12 soatdan keyin Perform: -31008', $errCode($rpc('PerformTransaction', ['id' => 'pay_E'])), -31008);
T::check('timeout bekor saqlandi (state -1, sabab 4), ULTRA berilmadi', (int) $db->value("SELECT state FROM payme_transactions WHERE payme_id = 'pay_E'") === -1
    && (int) $db->value("SELECT reason FROM payme_transactions WHERE payme_id = 'pay_E'") === 4 && $appP->tier($PU) === 'pro');
T::eq('noto\'g\'ri summa turi (matn): -31001', $errCode($rpc('CheckPerformTransaction', ['amount' => '1000', 'account' => ['order_id' => $o2['order_id']]])), -31001);
T::check('ichki xato ham JSON-RPC javob (istisno chiqmaydi)', isset($pm->handle('buzuq', $AUTH)['error']));

// --- qaytarish yoqilgan bo'lsa
$cfgR = new Config(['bot_token' => $config->str('bot_token'), 'admin_ids' => [$ADMIN], 'timezone' => 'Asia/Tashkent', 'payme_merchant_id' => 'M', 'payme_key' => 'K', 'payme_allow_refunds' => true]);
$appR = new App($cfgR, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$pmR = new Payme($appR);
$authR = 'Basic ' . base64_encode('Paycom:K');
$PR = 9702;
$text($PR, '/start');
$o3 = $pmR->createOrder($PR, '1m');
$tR = (int) $clock->format('U') * 1000;
$pmR->handle(['id' => 1, 'method' => 'CreateTransaction', 'params' => ['id' => 'pay_R', 'time' => $tR, 'amount' => $o3['amount_tiyin'], 'account' => ['order_id' => $o3['order_id']]]], $authR);
$pmR->handle(['id' => 2, 'method' => 'PerformTransaction', 'params' => ['id' => 'pay_R']], $authR);
$expR = (string) $db->value('SELECT subscription_expires_at FROM users WHERE user_id = ?', [$PR]);
$rr = $pmR->handle(['id' => 3, 'method' => 'CancelTransaction', 'params' => ['id' => 'pay_R', 'reason' => 5]], $authR);
T::check('qaytarish: state -2, muddat qisqardi', ($rr['result']['state'] ?? null) === -2 && (string) $db->value('SELECT subscription_expires_at FROM users WHERE user_id = ?', [$PR]) < $expR);
