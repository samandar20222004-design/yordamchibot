<?php
// 19–21-bosqich: yangi takrorlash turlari, ko'p post rejasi, haftalik hisobot (CommentsTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;
use PostAssist\Services\Recurrence;
use PostAssist\Services\Scheduler;

T::section('AF. Takrorlash: ish kunlari va har N kunda');
$tzT = new DateTimeZone('Asia/Tashkent');
$fri = new DateTimeImmutable('2027-06-04 05:00:00', new DateTimeZone('UTC')); // juma 10:00 Toshkent
$loc = static function (?DateTimeImmutable $d) use ($tzT): string {
    return $d ? $d->setTimezone($tzT)->format('D Y-m-d H:i') : 'null';
};
T::eq('ish kunlari: juma 10:00 dan, vaqt 09:00 → dushanba', $loc(Recurrence::next('workdays', 540, null, $fri, $tzT)), 'Mon 2027-06-07 09:00');
T::eq('ish kunlari: vaqt 11:00 → bugun (juma)', $loc(Recurrence::next('workdays', 660, null, $fri, $tzT)), 'Fri 2027-06-04 11:00');
T::eq('ish kunlari: shanbadan → dushanba', $loc(Recurrence::next('workdays', 660, null, $fri->modify('+1 day'), $tzT)), 'Mon 2027-06-07 11:00');
T::eq('har 2 kunda: 09:00 o\'tgan → 2 kundan keyin', $loc(Recurrence::next('interval', 540, 2, $fri, $tzT)), 'Sun 2027-06-06 09:00');
T::eq('har 3 kunda: 11:00 hali kelmagan → bugun', $loc(Recurrence::next('interval', 660, 3, $fri, $tzT)), 'Fri 2027-06-04 11:00');
T::eq('interval: kun soni noto\'g\'ri', [Recurrence::fromFirst('interval', $fri, $tzT), Recurrence::fromFirst('interval', $fri, $tzT, null, 31), Recurrence::next('interval', 540, 1, $fri, $tzT)], [null, null, null]);
T::eq('interval: birinchi vaqtdan', Recurrence::fromFirst('interval', $fri, $tzT, null, 2), ['type' => 'interval', 'time' => 600, 'day' => 2]);
$clock = $fri;
$XU = 9990;
$XC = -1009990;
$text($XU, '/start');
$fake->chats[$XC] = ['id' => $XC, 'type' => 'channel', 'title' => 'Reja kanali'];
$fake->members["{$XC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($XU, $XC, 'Reja kanali', null, 0);
$kbX = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$text($XU, '/newpost');
$text($XU, 'Har ikki kunda maslahat');
$press($XU, 'p:rep');
T::check('takror tanlovida yangi turlar', strpos($kbX(), 'pr:workdays') !== false && strpos($kbX(), 'pr:int2') !== false && strpos($kbX(), 'pr:int3') !== false);
$press($XU, 'pr:int2');
T::check('preview: «Har 2 kunda»', strpos($fake->texts(), 'Har 2 kunda') !== false);
$press($XU, 'p:now');
$xp = $db->one('SELECT * FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$XU]);
T::check('chiqdi va 2 kundan keyin qayta rejalandi', $xp['recurrence_type'] === 'interval' && (int) $xp['recurrence_day'] === 2 && $xp['status'] === 'pending'
    && $loc(new DateTimeImmutable((string) $xp['scheduled_time'], new DateTimeZone('UTC'))) === 'Sun 2027-06-06 10:00');
$text($XU, '/newpost');
$text($XU, 'Ish kunlari post');
$press($XU, 'p:rep');
$press($XU, 'pr:workdays');
$press($XU, 'p:time');
$press($XU, 't:tom09');
$xp2 = $db->one('SELECT * FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$XU]);
T::check('ish kunlari rejalandi, matnda ko\'rinadi', $xp2['recurrence_type'] === 'workdays' && strpos($fake->lastText(), 'Ish kunlari') !== false);
$mcallX = static function (int $uid, string $action, array $in = []) use ($app, $fake, $mkInit, &$clock, $token): array {
    $fake->reset();
    return MiniAppApi::handle($app, $action, $in, $mkInit(['id' => $uid, 'first_name' => 'U', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token));
};
$XREF = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$XC]);
$whenX = $clock->setTimezone($tzT)->modify('+1 day')->format('Y-m-d\TH:i');
[$sx, $rx] = $mcallX($XU, 'post_create', ['channel_id' => $XREF, 'type' => 'text', 'text' => 'Mini', 'repeat' => 'interval3', 'when' => $whenX]);
T::check('Mini App: har 3 kunda', $sx === 200 && (int) $db->value('SELECT recurrence_day FROM scheduled_posts WHERE id = ?', [$rx['id']]) === 3);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$XU]);
T::eq('Mini App: noto\'g\'ri interval rad', $mcallX($XU, 'post_create', ['channel_id' => $XREF, 'type' => 'text', 'text' => 'Mini', 'repeat' => 'interval9', 'when' => $whenX])[1]['error'] ?? null, 'repeat');
T::eq('Mini App: «interval» raqamsiz rad', $mcallX($XU, 'post_create', ['channel_id' => $XREF, 'type' => 'text', 'text' => 'Mini', 'repeat' => 'interval', 'when' => $whenX])[1]['error'] ?? null, 'repeat');

T::section('AG. Ko\'p post rejasi');
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$XU]);
$text($XU, '/newpost');
T::check('post boshida «📦 Ko\'p post rejasi»', strpos($kbX(), 'bk:start') !== false);
$press($XU, 'bk:start');
T::eq('yig\'ish rejimi', $app->states->get($XU)['state'] ?? null, 'bulk');
$text($XU, 'Birinchi post');
T::check('qo\'shildi, «Tayyor (1)»', strpos($fake->lastText(), '1-post') !== false && strpos($kbX(), 'bk:done') !== false && strpos($kbX(), '(1)') !== false);
$send($XU, ['photo' => [['file_id' => 'PH_BULK', 'width' => 1, 'height' => 1]], 'caption' => 'Ikkinchi (rasm)']);
// albom: kutish paytida qolgan qismlar keladi (parallel so'rovlar) — bitta post bo'lib qo'shiladi
$bkAlbum = static function (string $file, int $mid, string $cap = '') use (&$upd, $XU): array {
    return ['update_id' => $upd++, 'message' => ['message_id' => $mid, 'from' => ['id' => $XU, 'is_bot' => false, 'first_name' => 'X'], 'chat' => ['id' => $XU, 'type' => 'private'],
        'date' => 0, 'media_group_id' => 'BKG1', 'photo' => [['file_id' => $file, 'width' => 1, 'height' => 1]], 'caption' => $cap]];
};
$bkQueue = [$bkAlbum('A2', 9102), $bkAlbum('A3', 9103)];
$app->sleeper = static function (int $ms) use (&$bkQueue, $router): void {
    if ($bkQueue) {
        $router->handle(array_shift($bkQueue));
    }
};
$fake->reset();
$router->handle($bkAlbum('A1', 9101, 'Albom izohi'));
$app->sleeper = static function (int $ms): void {
};
$bkItems = $app->states->get($XU)['data']['items'] ?? [];
T::check('albom qabul qilindi: bitta post, 3 fayl, izoh bilan', count($bkItems) === 3 && ($bkItems[2]['type'] ?? '') === 'album' && count($bkItems[2]['media'] ?? []) === 3
    && $bkItems[2]['text'] === 'Albom izohi' && count($fake->of('sendMessage')) === 1 && strpos($fake->lastText(), 'albom (3 ta fayl)') !== false);
$fake->reset();
$router->handle($bkAlbum('A4', 9104));
T::check('kechikkan qism oxirgi albomga qo\'shiladi (jim)', count($app->states->get($XU)['data']['items'][2]['media'] ?? []) === 4 && $fake->of('sendMessage') === []);
$router->handle($bkAlbum('A4', 9104));
T::eq('takror qism qo\'shilmaydi', count($app->states->get($XU)['data']['items'][2]['media'] ?? []), 4);
$text($XU, 'Uchinchi post');
T::eq('4 ta yig\'ildi (albom — bitta)', count($app->states->get($XU)['data']['items'] ?? []), 4);
$bkSaved = $app->states->get($XU);
// dialogdan tashqari albom (aqlli qabul): yo'qolmaydi — oddiy post preview'i
$app->states->clear($XU);
$dqQueue = [$bkAlbum('D2', 9202)];
$app->sleeper = static function (int $ms) use (&$dqQueue, $router): void {
    if ($dqQueue) {
        $router->handle(array_shift($dqQueue));
    }
};
$fake->reset();
$dq = $bkAlbum('D1', 9201, 'Tashqi albom');
$dq['message']['media_group_id'] = 'DQG1';
$dqQueue[0]['message']['media_group_id'] = 'DQG1';
$router->handle($dq);
$app->sleeper = static function (int $ms): void {
};
$dqSt = $app->states->get($XU);
T::check('dialogdan tashqari albom: post qoralamasi (2 fayl), «tushunmadim» emas', in_array($dqSt['state'] ?? '', ['post_preview', 'post_pick'], true)
    && ($dqSt['data']['draft']['type'] ?? '') === 'album' && count($dqSt['data']['draft']['media'] ?? []) === 2 && strpos(json_encode($fake->calls, JSON_UNESCAPED_UNICODE), 'tushunmadim') === false);
$app->states->set($XU, (string) $bkSaved['state'], $bkSaved['data']);
$press($XU, 'bk:done');
T::eq('bitta kanal: darhol vaqt so\'raladi', $app->states->get($XU)['state'] ?? null, 'bulk_time');
$text($XU, 'qachondir');
T::check('noto\'g\'ri vaqt rad', strpos($fake->lastText(), 'tushunmadim') !== false && ($app->states->get($XU)['state'] ?? '') === 'bulk_time');
$text($XU, 'ertaga 09:00');
T::check('oraliq so\'raladi', ($app->states->get($XU)['state'] ?? '') === 'bulk_gap' && strpos($kbX(), 'bk:g:180') !== false && strpos($kbX(), 'bk:g:1440') !== false);
$press($XU, 'bk:g:999');
T::eq('noma\'lum oraliq — hech narsa yaratilmaydi', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$XU]), 0);
$app->states->set($XU, 'bulk_gap', ['items' => [['type' => 'album', 'file_id' => null, 'text' => 'Rejadagi albom', 'media' => [['photo', 'R1'], ['photo', 'R2'], ['video', 'R3']]]],
    'channel' => $XREF, 'start' => '2027-06-07 04:00:00']);
$press($XU, 'bk:g:60');
$bpa = $db->one("SELECT * FROM scheduled_posts WHERE user_id = ? AND text = 'Rejadagi albom'", [$XU]);
T::check('ko\'p post: albom albom bo\'lib rejalashtirildi (3 fayl)', $bpa !== null && $bpa['post_type'] === 'album' && count(json_decode((string) $bpa['media'], true) ?: []) === 3
    && strpos($fake->lastText(), '🖼×3') !== false, $fake->lastText());
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ?", [(int) ($bpa['id'] ?? 0)]);
$app->states->set($XU, 'bulk_gap', ['items' => [['type' => 'text', 'file_id' => null, 'text' => 'a'], ['type' => 'text', 'file_id' => null, 'text' => 'b'],
    ['type' => 'text', 'file_id' => null, 'text' => 'c']], 'channel' => $XREF, 'start' => '2027-06-05 04:00:00']);
$press($XU, 'bk:g:180');
$bp = $db->all("SELECT scheduled_time, text FROM scheduled_posts WHERE user_id = ? AND status = 'pending' ORDER BY scheduled_time", [$XU]);
T::check('3 ta post: 09:00, 12:00, 15:00 (Toshkent)', count($bp) === 3 && $bp[0]['scheduled_time'] === '2027-06-05 04:00:00' && $bp[1]['scheduled_time'] === '2027-06-05 07:00:00'
    && $bp[2]['scheduled_time'] === '2027-06-05 10:00:00' && strpos($fake->lastText(), '3 ta post rejalashtirildi') !== false);
$press($XU, 'bk:g:180');
T::eq('ikki marta bosish — ikki marta yaratilmaydi', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$XU]), 3);
$app->states->set($XU, 'bulk_gap', ['items' => [['type' => 'text', 'file_id' => null, 'text' => 'd']], 'channel' => $XREF, 'start' => '2027-06-06 04:00:00']);
$press($XU, 'bk:g:60');
T::check('bepul navbat limiti (3): rad, sabab aytiladi', strpos($fake->lastText(), 'limiti 3') !== false
    && (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$XU]) === 3);
$app->states->set($XU, 'bulk_gap', ['items' => [['type' => 'text', 'file_id' => null, 'text' => 'e']], 'channel' => (int) $db->value('SELECT id FROM channels WHERE user_id <> ? LIMIT 1', [$XU]), 'start' => '2027-06-06 04:00:00']);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$XU]);
$press($XU, 'bk:g:60');
T::eq('begona kanalga rejalab bo\'lmaydi', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$XU]), 0);

T::section('AH. Haftalik hisobot');
$sched = new Scheduler($app, static function (int $us): void {
});
$toX = static function () use ($fake, $XU): array {
    return array_values(array_filter($fake->of('sendMessage'), function ($p) use ($XU) { return (int) $p['chat_id'] === $XU; }));
};
$db->exec('UPDATE users SET report_week = NULL, weekly_report = 1 WHERE user_id = ?', [$XU]);
$clock = new DateTimeImmutable('2027-06-07 03:00:00', new DateTimeZone('UTC')); // dushanba 08:00 Toshkent
$fake->reset();
$sched->run(5);
T::eq('dushanba 08:00 — hali yuborilmaydi', count($toX()), 0);
$clock = new DateTimeImmutable('2027-06-07 04:10:00', new DateTimeZone('UTC')); // 09:10
$fake->reset();
$sched->run(5);
$rep = $toX();
T::check('dushanba 09:10 — hisobot keldi (kanal, obunachi, postlar, o\'chirish yo\'li)', count($rep) === 1 && strpos((string) $rep[0]['text'], 'Haftalik hisobot') !== false
    && strpos((string) $rep[0]['text'], 'Reja kanali') !== false && strpos((string) $rep[0]['text'], 'Statistika') !== false);
$fake->reset();
$sched->run(5);
T::eq('o\'sha hafta qayta yuborilmaydi', count($toX()), 0);
$clock = new DateTimeImmutable('2027-06-08 04:10:00', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
T::eq('seshanba — yuborilmaydi', count($toX()), 0);
$text($XU, '📊 Statistika');
T::check('statistikada hisobot tugmalari', strpos($kbX(), 'st:wk') !== false && strpos($kbX(), 'st:now') !== false && strpos($kbX(), 'yoqiq') !== false);
$press($XU, 'st:wk');
T::check('o\'chirildi', (int) $db->value('SELECT weekly_report FROM users WHERE user_id = ?', [$XU]) === 0 && strpos($kbX(), "o'chiq") !== false);
$clock = new DateTimeImmutable('2027-06-14 04:10:00', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
T::eq('o\'chirilgan — keyingi dushanba ham kelmaydi', count($toX()), 0);
$press($XU, 'st:wk');
$fake->forced['sendMessage'] = [];
$fake->reset();
$sched->run(5);
T::eq('qayta yoqilgach — keladi', count($toX()), 1);
$press($XU, 'st:now');
T::check('«📈 Haftalik hisobot» — hozir ko\'rish', strpos($fake->lastText(), 'Haftalik hisobot') !== false);
$text($XU, '/report');
T::check('/report buyrug\'i', strpos($fake->lastText(), 'Haftalik hisobot') !== false);
