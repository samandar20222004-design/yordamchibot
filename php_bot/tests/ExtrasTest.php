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
