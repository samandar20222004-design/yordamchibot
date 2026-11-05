<?php
// 💰 Reklama birjasi (TeamTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Services\MarketSafety;

T::section('S. Reklama birjasi');
$clock = new DateTimeImmutable('2026-12-15 10:00:00', new DateTimeZone('UTC'));
$MO = 9500;
$B = 9501;
foreach ([$MO, $B, 9502, 9503, 9504, 9505] as $u) {
    $text($u, '/start');
}
$db->exec('UPDATE users SET created_at = ? WHERE user_id IN (9500, 9501, 9502, 9503, 9504)', ['2026-11-01 00:00:00']);
$kbM = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$MC = -1009500;
$fake->chats[$MC] = ['id' => $MC, 'type' => 'channel', 'title' => 'Texno <kanal>', 'username' => 'texno_kanal'];
$fake->members["{$MC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["{$MC}|{$MO}"] = ['status' => 'creator'];
$app->channels->connect($MO, $MC, 'Texno <kanal>', 'texno_kanal', 0);
$app->channels->connect($MO, -1009599, 'Yopiq', null, 0);

// --- unit: xavfsizlik
T::eq('xavfsizlik: karta, hamyon, havola (birinchi xabar)', [MarketSafety::assess('8600 1234 5678 9012')['reason'], MarketSafety::assess('0x' . str_repeat('a1', 20))['reason'],
    MarketSafety::assess('sayt: example.com', true)['reason'], MarketSafety::assess('sayt: example.com', false, 30.0)['reason']], ['card', 'wallet', 'link', null]);
T::eq('yangi hisobdan havola to\'siladi, egasiga ruxsat', [MarketSafety::assess('t.me/x', false, 1.0)['reason'], MarketSafety::assess('t.me/x', true, 1.0, true)['reason']], ['link', null]);
T::eq('belgilar: oldindan to\'lov, shoshiltirish, kafolatlangan daromad', MarketSafety::assess("Oldindan to‘lov kerak, hoziroq! Kafolatlangan daromad")['flags'], ['prepay', 'pressure', 'scam']);
T::check('takror matn xeshi (bo\'shliq va katta harf farqsiz)', MarketSafety::dupHash('Salom  Dunyo') === MarketSafety::dupHash('salom dunyo'));

// --- kirish
$text($MO, '/market');
T::check('/market: katalog, kanal qo\'yish, suhbatlar, e\'lonlarim', strpos($kbM(), 'mk:cat') !== false && strpos($kbM(), 'mk:pub') !== false && strpos($kbM(), 'mk:th') !== false && strpos($kbM(), 'mk:my') !== false);
$text($MO, '📢 Kanallarim');
T::check('kanallar ekranida «💰 Reklama birjasi»', strpos($kbM(), 'mk:home') !== false);

// --- e'lon qo'yish
$press($MO, 'mk:pub');
T::check('telefon so\'raladi (request_contact)', strpos($mk($fake->of('sendMessage')[0] ?? []), 'request_contact') !== false);
$send($MO, ['contact' => ['phone_number' => '+998901234567', 'user_id' => $MO, 'first_name' => 'M']]);
$kb = $kbM();
T::check('tasdiqlandi: faqat ochiq kanallar ro\'yxati', $app->users->isPhoneVerified($MO) && strpos($kb, 'mk:pc:') !== false && strpos($kb, 'Yopiq') === false);
$mcId = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$MC]);
$fake->members["{$MC}|{$MO}"] = ['status' => 'member'];
$press($MO, 'mk:pc:' . $mcId);
T::check('egasi kanalda admin bo\'lmasa rad', strpos($fake->lastText(), 'admin') !== false);
$fake->members["{$MC}|{$MO}"] = ['status' => 'creator'];
$fake->forced['getChatMemberCount'] = [['ok' => true, 'result' => 12345]];
$press($MO, 'mk:pc:' . $mcId);
T::check('narx so\'m-da so\'raladi (UZ tasdiqlangan)', ($app->states->get($MO)['state'] ?? '') === 'mk_price' && strpos($fake->lastText(), "so'mda") !== false);
$text($MO, 'arzon');
T::check('noto\'g\'ri narx', strpos($fake->lastText(), 'raqam') !== false);
$text($MO, '150 000');
T::eq('narx qabul qilindi', $app->states->get($MO)['state'] ?? '', 'mk_desc');
$text($MO, 'To\'lov 8600 1234 5678 9012 kartaga');
T::check('tavsifda karta raqami — rad', strpos($fake->lastText(), 'Karta raqami') !== false && ($app->states->get($MO)['state'] ?? '') === 'mk_desc');
$text($MO, 'IT yangiliklari, 70% Toshkent');
$press($MO, 'mk:cs:tech');
$L = $db->one('SELECT * FROM market_listings WHERE channel_id = ?', [$MC]);
T::eq('e\'lon saqlandi: obunachi, narx, valyuta, bo\'lim', [(int) $L['subscribers'], (int) $L['price'], $L['currency'], $L['category'], $L['status']], [12345, 150000, 'UZS', 'tech', 'active']);
$LID = (int) $L['id'];

// --- katalog
$press($B, 'mk:cat');
T::check('bo\'limlar', strpos($kbM(), 'mk:l:tech:0') !== false && strpos($kbM(), 'mk:l:all:0') !== false);
$press($B, 'mk:l:tech:0');
T::check('ro\'yxatda kanal (12.3K, narx)', strpos($kbM(), 'mk:v:' . $LID) !== false && strpos($kbM(), '12.3K') !== false && strpos($kbM(), '150 000 UZS') !== false);
$press($B, 'mk:v:' . $LID);
T::check('kanal kartasi: nom escape, obunachi, narx, so\'rov va shikoyat', strpos($fake->lastText(), 'Texno &lt;kanal&gt;') !== false && strpos($fake->lastText(), '12 345') !== false
    && strpos($kbM(), 'mk:ask:' . $LID) !== false && strpos($kbM(), 'mk:rep:' . $LID) !== false && strpos($kbM(), 't.me\/texno_kanal') !== false);
$press($MO, 'mk:v:' . $LID);
T::check('o\'z e\'lonida so\'rov tugmasi yo\'q', strpos($kbM(), 'mk:ask:') === false);

// --- so'rov va yozishma
$press($B, 'mk:ask:' . $LID);
T::eq('so\'rov kutilmoqda', $app->states->get($B)['state'] ?? '', 'mk_msg');
$text($B, 'qisqa');
T::check('juda qisqa xabar rad', strpos($fake->lastText(), 'belgi') !== false);
$text($B, 'Mana kartam 8600 1234 5678 9012 pul tashlayman');
T::check('karta raqami to\'siladi', strpos($fake->lastText(), 'Karta raqami') !== false && (int) $db->value('SELECT COUNT(*) FROM market_messages') === 0);
$text($B, 'Batafsil saytda: example.com qarang');
T::check('birinchi xabarda havola to\'siladi', strpos($fake->lastText(), 'havola') !== false);
$text($B, 'Assalomu alaykum, 20-dekabrga reklama posti mumkinmi? Oldindan to\'lov kerakmi?');
$toOwner = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($MO) {
    return (int) $m['chat_id'] === $MO;
}));
T::check('egasiga yetdi: kanal nomi, matn escape, ⚠️ oldindan to\'lov belgisi, tugmalar', $toOwner && strpos((string) $toOwner[0]['text'], 'Yangi so\'rov') !== false
    && strpos((string) $toOwner[0]['text'], 'Oldindan to') !== false && strpos((string) $toOwner[0]['text'], 'ehtiyot') !== false
    && strpos($mk($toOwner[0]), 'mk:re:') !== false && strpos($mk($toOwner[0]), 'mk:fr:') !== false);
T::check('yuboruvchining raqami/username\'i egasiga ko\'rinmaydi', strpos((string) $toOwner[0]['text'], 'ali' . $B) === false && strpos((string) $toOwner[0]['text'], (string) $B) === false);
$TID = (int) $db->value('SELECT id FROM market_threads WHERE buyer_id = ? AND listing_id = ?', [$B, $LID]);
$press($MO, 'mk:re:' . $TID);
$text($MO, 'Ha mumkin, narx 150 000. Kanal: t.me/texno_kanal');
$toBuyer = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($B) {
    return (int) $m['chat_id'] === $B;
}));
T::check('egasi javobi xaridorga (egasining havolasi ruxsat, ⚠️ havola belgisi)', $toBuyer && strpos((string) $toBuyer[0]['text'], 'Kanal egasidan javob') !== false
    && strpos((string) $toBuyer[0]['text'], 'havola bor') !== false);
$press($B, 'mk:re:' . $TID);
$text($B, 'Yaxshi, ertaga yozaman batafsil');
$press($B, 'mk:re:' . $TID);
$text($B, 'Yaxshi,  ertaga yozaman BATAFSIL');
T::check('bir xil matn takrori rad', strpos($fake->lastText(), 'allaqachon yuborilgan') !== false);
$press(9505, 'mk:t:' . $TID);
T::eq('begona odam suhbatni ko\'ra olmaydi', count($fake->of('editMessageText', 'sendMessage')), 0);
$press(9505, 'mk:re:' . $TID);
T::eq('begona odam javob yoza olmaydi', $app->states->get(9505), null);
$press($B, 'mk:th');
T::check('suhbatlar ro\'yxati', strpos($kbM(), 'mk:t:' . $TID) !== false);
$press($B, 'mk:t:' . $TID);
T::check('suhbat tarixi', strpos($fake->lastText(), 'Assalomu alaykum') !== false && strpos($fake->lastText(), 'Ha mumkin') !== false);
$press($B, 'mk:ct:' . $TID);
$toOwner = array_values(array_filter($fake->of('sendMessage'), static function ($m) use ($MO) {
    return (int) $m['chat_id'] === $MO;
}));
T::check('kontakt faqat o\'zi xohlasa ulashiladi', $toOwner && strpos((string) $toOwner[0]['text'], '@ali' . $B) !== false);

// --- kunlik limit
for ($i = 1; $i <= 5; $i++) {
    $cid = -1009500 - $i;
    $app->market->upsert(9504, ['channel_id' => $cid, 'title' => 'K' . $i, 'username' => 'k' . $i . 'kanal'], 10000, 'UZS', '', 'news', 100 * $i, $clock);
}
$ids = array_map('intval', array_column($db->all("SELECT id FROM market_listings WHERE owner_id = 9504 ORDER BY id"), 'id'));
foreach (array_slice($ids, 0, 4) as $lid) {
    $press($B, 'mk:ask:' . $lid);
    $text($B, 'Salom, reklama narxi qancha bo\'ladi? ' . $lid);
}
$press($B, 'mk:ask:' . $ids[4]);
T::check('kuniga 5 ta yangi so\'rov: 6-si rad', strpos($fake->lastText(), '5 ta') !== false && ($app->states->get($B)['state'] ?? '') !== 'mk_msg');
$press($B, 'mk:ask:' . $LID);
T::eq('mavjud suhbatga yozish limitga kirmaydi', $app->states->get($B)['state'] ?? '', 'mk_msg');
$app->states->clear($B);

// --- bloklash
$press($MO, 'mk:bl:' . $TID);
$press($B, 'mk:re:' . $TID);
T::check('bloklangan suhbatga yozib bo\'lmaydi', strpos($fake->lastText(), 'bloklangan') !== false && ($app->states->get($B)['state'] ?? '') !== 'mk_msg');

// --- shikoyatlar
$press($B, 'mk:rep:' . $ids[0]);
$press($B, 'mk:rep:' . $ids[0]);
T::check('bir kishi bir marta shikoyat qiladi', strpos($fake->lastText(), 'allaqachon') !== false);
$press(9502, 'mk:rep:' . $ids[0]);
$press(9503, 'mk:rep:' . $ids[0]);
T::check('3 ta shikoyat: e\'lon yopildi, adminga xabar', $db->value('SELECT status FROM market_listings WHERE id = ?', [$ids[0]]) === 'banned' && strpos($fake->texts(), 'yopildi') !== false);
$press($B, 'mk:l:news:0');
T::check('yopilgan e\'lon katalogda yo\'q', strpos($kbM(), 'mk:v:' . $ids[0]) === false && strpos($kbM(), 'mk:v:' . $ids[1]) !== false);
$text($ADMIN, '/market_unban ' . $ids[0]);
T::eq('admin qayta ochdi', $db->value('SELECT status FROM market_listings WHERE id = ?', [$ids[0]]), 'active');
// firibgar
$threads = array_map('intval', array_column($db->all('SELECT id FROM market_threads WHERE buyer_id = ? AND owner_id = 9504', [$B]), 'id'));
$press(9504, 'mk:fr:' . $threads[0]);
foreach ([9502, 9503] as $rep) {
    $app->market->report('user', $B, $rep, $clock);
}
$press(9504, 'mk:fr:' . $threads[1]);
T::check('3 ta «firibgar»: birjadan ban, adminga xabar', $app->market->isBanned($B) && (strpos($fake->texts(), 'bloklandi') !== false || $app->market->isBanned($B)));
$press($B, 'mk:ask:' . $ids[2]);
T::check('ban qilingan: so\'rov yoza olmaydi', strpos($fake->lastText(), 'cheklangan') !== false);
$press($B, 'mk:pub');
T::check('ban qilingan: e\'lon qo\'ya olmaydi', strpos($fake->lastText(), 'cheklangan') !== false);
$text($U, '/market_userunban ' . $B);
T::eq('oddiy foydalanuvchi ban olib tashlay olmaydi', $app->market->isBanned($B), true);
$text($ADMIN, '/market_userunban ' . $B);
T::eq('admin ban olib tashladi', $app->market->isBanned($B), false);
$text($ADMIN, '/market_userban ' . $B);
T::eq('/market_userban', $app->market->isBanned($B), true);
$text($ADMIN, '/market_userunban ' . $B);

// --- e'lonlarim
$press($MO, 'mk:my');
T::check('e\'lonlarim: holat va boshqaruv', strpos($fake->lastText(), 'faol') !== false && strpos($kbM(), 'mk:hide:' . $LID) !== false && strpos($kbM(), 'mk:del:' . $LID) !== false);
$press($MO, 'mk:hide:' . $LID);
T::eq('yashirildi', $db->value('SELECT status FROM market_listings WHERE id = ?', [$LID]), 'hidden');
$press($B, 'mk:v:' . $LID);
T::check('yashirin e\'lon ochilmaydi', strpos($fake->lastText(), 'topilmadi') !== false);
$press($B, 'mk:hide:' . $LID);
T::eq('begona odam yashira/ochira olmaydi', $db->value('SELECT status FROM market_listings WHERE id = ?', [$LID]), 'hidden');
$fake->forced['getChatMemberCount'] = [['ok' => true, 'result' => 13000]];
$press($MO, 'mk:upd:' . $LID);
T::eq('obunachilar yangilandi', (int) $db->value('SELECT subscribers FROM market_listings WHERE id = ?', [$LID]), 13000);
$press($B, 'mk:del:' . $LID);
T::eq('begona odam o\'chira olmaydi', (int) $db->value('SELECT COUNT(*) FROM market_listings WHERE id = ?', [$LID]), 1);
$press($MO, 'mk:del:' . $LID);
T::eq('egasi o\'chirdi', (int) $db->value('SELECT COUNT(*) FROM market_listings WHERE id = ?', [$LID]), 0);
$text($ADMIN, '/admin_help');
T::check('/admin_help: birja buyruqlari', strpos($fake->lastText(), '/market_ban') !== false);

// Mini App -> bot bo'limlari (deep link ruxsat ro'yxati)
$lastKb = function () use ($fake) {
    $all = $fake->of('sendMessage', 'editMessageText');
    $last = $all ? end($all) : [];
    return json_encode($last['reply_markup'] ?? '');
};
$text($B, '/start go_market');
T::check('/start go_market: birja ochiladi', strpos($fake->lastText(), 'irja') !== false);
$text($B, '/start go_plans');
T::check('/start go_plans: tariflar', strpos($lastKb(), 'pl:') !== false);
$text($B, '/start go_evil');
T::check('noma\'lum go_*: oddiy start', strpos($lastKb(), 'pl:') === false);
$appSrc = (string) file_get_contents(__DIR__ . '/../app.php');
preg_match("/var BOT_SECTIONS = \\[([^\\]]*)\\]/", $appSrc, $mm);
$js = array_map(function ($x) { return trim($x, " '"); }, explode(',', $mm[1] ?? ''));
T::eq('app.php BOT_SECTIONS == Router::GO_TARGETS', $js, \PostAssist\Router::GO_TARGETS);
