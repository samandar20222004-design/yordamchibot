<?php
// 10-bosqich: Mini App'da birja (PaymeTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;

T::section('V. Mini App: birja (katalog, e\'lon, suhbat)');
$clock = new DateTimeImmutable('2027-02-01 10:00:00', new DateTimeZone('UTC'));
$MAO = 9800; // kanal egasi
$MAB = 9801; // reklama beruvchi
$MAX = 9802; // begona
foreach ([$MAO, $MAB, $MAX] as $u) {
    $text($u, '/start');
}
$db->exec('UPDATE users SET created_at = ? WHERE user_id IN (?, ?, ?)', ['2026-01-01 00:00:00', $MAO, $MAB, $MAX]); // eski hisob (havola qoidasi uchun)
$mlid = $app->market->upsert($MAO, ['channel_id' => -1009800, 'title' => 'Sport yangiliklari', 'username' => 'sport_uz_test'], 300000, 'UZS', 'Kuniga 3 post, sport', 'sport', 45000, $clock);
$app->market->upsert($MAO, ['channel_id' => -1009801, 'title' => 'Avto bozor', 'username' => 'avto_test'], 50, 'USD', '', 'auto', 2000, $clock);
$initOf = static function (int $uid) use ($mkInit, $clock, $token): string {
    return $mkInit(['id' => $uid, 'first_name' => 'U' . $uid, 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token);
};
$mcall = static function (int $uid, string $action, array $in = []) use ($app, $fake, $initOf): array {
    $fake->reset();
    return MiniAppApi::handle($app, $action, $in, $initOf($uid));
};
T::eq('imzosiz birja so\'rovi rad', MiniAppApi::handle($app, 'market', [], '')[0], 401);
[$st, $r] = $mcall($MAB, 'market', ['cat' => 'sport']);
T::check('katalog: toifa bo\'yicha, toifalar nomi bilan', $st === 200 && count($r['items']) >= 1 && $r['items'][0]['username'] === 'sport_uz_test'
    && $r['items'][0]['price'] === '300 000 UZS' && count($r['categories']) === 10 && $r['categories'][0]['name'] !== '');
[, $r] = $mcall($MAB, 'market', ['cat' => 'hack\'']);
T::eq('noma\'lum toifa — hammasi', $r['cat'], null);
[, $r] = $mcall($MAO, 'market', []);
T::check('egasi: «Mening e\'lonlarim»', count($r['mine']) === 2 && $r['mine'][0]['status'] === 'active');
[$st, $v] = $mcall($MAB, 'market_view', ['id' => $mlid]);
T::check('e\'lon kartasi', $st === 200 && $v['listing']['title'] === 'Sport yangiliklari' && $v['listing']['mine'] === false && $v['thread'] === null);
$app->market->setStatus($mlid, 'hidden');
T::eq('yashirin e\'lon begonaga ko\'rinmaydi', $mcall($MAB, 'market_view', ['id' => $mlid])[0], 404);
T::eq('yashirin e\'lon egasiga ko\'rinadi', $mcall($MAO, 'market_view', ['id' => $mlid])[0], 200);
$app->market->setStatus($mlid, 'active');

// so'rov yuborish — bot bilan bir xil himoya
[$st, $s] = $mcall($MAB, 'market_send', ['listing' => $mlid, 'text' => 'qisqa']);
T::check('qisqa xabar rad (matn bilan)', $st === 400 && $s['error'] === 'len' && strpos($s['message'], '10') !== false);
[$st, $s] = $mcall($MAB, 'market_send', ['listing' => $mlid, 'text' => 'Karta raqamim 8600 1234 5678 9012 ga tashlang']);
T::check('karta raqami to\'siladi', $st === 400 && $s['error'] === 'unsafe');
[$st, $s] = $mcall($MAO, 'market_send', ['listing' => $mlid, 'text' => 'O\'z kanalimga so\'rov yozaman']);
T::eq('o\'z e\'loniga so\'rov yozib bo\'lmaydi', $st, 404);
[$st, $s] = $mcall($MAB, 'market_send', ['listing' => $mlid, 'text' => 'Salom, 10-fevralga bitta reklama posti kerak, narx qancha?']);
$mtid = (int) ($s['thread'] ?? 0);
T::check('so\'rov yuborildi: suhbat ochildi', $st === 200 && $mtid > 0);
$toOwner = array_values(array_filter($fake->of('sendMessage'), function ($p) use ($MAO) { return (int) $p['chat_id'] === $MAO; }));
T::check('egasiga bot orqali keldi (javob tugmalari bilan)', count($toOwner) === 1 && strpos((string) $toOwner[0]['text'], '10-fevralga') !== false
    && strpos($mk($toOwner[0]), 'mk:re:' . $mtid) !== false);
[, $v] = $mcall($MAB, 'market_view', ['id' => $mlid]);
T::eq('e\'lon kartasida suhbat bor', $v['thread'], $mtid);
[$st, $th] = $mcall($MAX, 'market_thread', ['id' => $mtid]);
T::eq('begona suhbatni o\'qiy olmaydi (IDOR)', $st, 404);
T::eq('begona suhbatga yoza olmaydi', $mcall($MAX, 'market_send', ['thread' => $mtid, 'text' => 'Men ham shu suhbatga yozaman'])[0], 404);
[$st, $s] = $mcall($MAO, 'market_send', ['thread' => $mtid, 'text' => 'Assalomu alaykum, 10-fevral bo\'sh, narxi e\'londa.']);
T::check('egasi javob berdi, reklama beruvchiga keldi', $st === 200 && count(array_filter($fake->of('sendMessage'), function ($p) use ($MAB) { return (int) $p['chat_id'] === $MAB; })) === 1);
[$st, $th] = $mcall($MAB, 'market_thread', ['id' => $mtid]);
T::check('suhbat: 2 xabar, kim yozgani belgilangan', $st === 200 && count($th['messages']) === 2 && $th['messages'][0]['me'] === true && $th['messages'][1]['me'] === false);
$s = $mcall($MAO, 'market_send', ['thread' => $mtid, 'text' => 'Assalomu alaykum, 10-fevral bo\'sh, narxi e\'londa.'])[1];
T::eq('takror xabar rad', $s['error'] ?? null, 'dup');
[, $tl] = $mcall($MAO, 'market_threads');
T::check('suhbatlar ro\'yxati (egasi uchun «reklama beruvchi»)', count($tl['threads']) >= 1 && $tl['threads'][0]['id'] === $mtid && $tl['threads'][0]['role'] === 'owner');
$app->market->blockThread($mtid);
T::eq('bloklangan suhbatga yozib bo\'lmaydi', $mcall($MAB, 'market_send', ['thread' => $mtid, 'text' => 'Yana bir marta yozib ko\'raman'])[1]['error'] ?? null, 'blocked');
$app->market->banUser($MAX, true);
[, $r] = $mcall($MAX, 'market', []);
T::eq('ban qilingan: katalogda belgi', $r['banned'], true);
T::eq('ban qilingan: so\'rov yozolmaydi', $mcall($MAX, 'market_send', ['listing' => $mlid, 'text' => 'Reklama kerak edi, narxi qancha bo\'ladi?'])[1]['error'] ?? null, 'banned');
$app->market->banUser($MAX, false);
// kunlik limit
for ($i = 0; $i < 5; $i++) {
    $app->market->upsert($MAO, ['channel_id' => -1009810 - $i, 'title' => 'K' . $i, 'username' => 'k_test' . $i], 1000, 'UZS', '', 'news', 100, $clock);
}
$sent = 0;
foreach ($db->all("SELECT id FROM market_listings WHERE owner_id = ? AND username LIKE 'k\\_test%' ORDER BY id", [$MAO]) as $row) {
    $sent += $mcall($MAX, 'market_send', ['listing' => (int) $row['id'], 'text' => 'Reklama kerak edi, narxi qancha bo\'ladi?'])[0] === 200 ? 1 : 0;
}
$lim = $mcall($MAX, 'market_send', ['listing' => $mlid, 'text' => 'Reklama kerak edi, narxi qancha bo\'ladi?'])[1];
T::check('kuniga 5 ta yangi so\'rov, 6-si rad', $sent === 5 && ($lim['error'] ?? '') === 'limit');
$appSrc2 = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: Birja tabi va ?tab=market', strpos($appSrc2, 'data-go="market"') !== false && strpos($appSrc2, "'market', 'me'") !== false);
