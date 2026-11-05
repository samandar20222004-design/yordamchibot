<?php
// Jamoa va rollar (Phase6Test.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;
use PostAssist\Services\Plans;

T::section('R. Jamoa va rollar (bot + Mini App)');
$clock = new DateTimeImmutable('2026-12-10 10:00:00', new DateTimeZone('UTC'));
$O = 9400;
$H = 9401;
$H2 = 9402;
$H3 = 9403;
$P = 9404;
foreach ([$O, $H, $H2, $H3, $P] as $u) {
    $text($u, '/start');
}
Plans::grant($db, $O, 'ultra', 30, $clock);
$OC = -1009400;
$fake->chats[$OC] = ['id' => $OC, 'type' => 'channel', 'title' => 'Egasi kanali'];
$fake->members["{$OC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($O, $OC, 'Egasi kanali', null, 0);
$tokenOf = static function (string $t): string {
    return preg_match('/team_([a-f0-9]{24})/', $t, $m) ? $m[1] : '';
};
$kbT = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};

$press($P, 'set:team');
T::check('FREE egasi: jamoa uchun ULTRA kerak', strpos($fake->lastText(), 'ULTRA') !== false && strpos($kbT(), 'pl:show') !== false && strpos($kbT(), 'tm:inv') === false);
$text($O, '⚙️ Sozlamalar / Ko\'proq');
T::check('sozlamalarda «👥 Jamoa» tugmasi', strpos($kbT(), 'set:team') !== false);
$press($O, 'set:team');
T::check('ULTRA egasi: 0/2 va taklif tugmasi', strpos($fake->lastText(), '(0/2)') !== false && strpos($kbT(), 'tm:inv') !== false);
$press($O, 'tm:inv');
T::check('ruxsat to\'plamlari', strpos($kbT(), 'tm:ip:all') !== false && strpos($kbT(), 'tm:ip:editor') !== false && strpos($kbT(), 'tm:ip:viewer') !== false);
$press($O, 'tm:ip:editor');
$tok1 = $tokenOf($fake->lastText());
T::check('taklif havolasi (token bazada faqat xesh ko\'rinishida)', strlen($tok1) === 24 && (int) $db->value('SELECT COUNT(*) FROM team_invites WHERE token_hash = ?', [hash('sha256', $tok1)]) === 1
    && (int) $db->value('SELECT COUNT(*) FROM team_invites WHERE token_hash = ?', [$tok1]) === 0);
$text($O, '/start team_' . $tok1);
T::check('o\'z havolasi bilan qo\'shilib bo\'lmaydi', strpos($fake->lastText(), 'o\'zingizning') !== false);
$text($H, '/start team_' . $tok1);
T::check('yordamchi qo\'shildi, ish joyi egasiniki, egasiga xabar', strpos($fake->texts(), 'jamoasiga qo\'shildingiz') !== false && $app->team->workspace($H) === $O
    && $app->team->perms($O, $H) === ['create', 'ai'] && strpos($fake->texts(), 'jamoangizga qo\'shildi') !== false);
$text($H2, '/start team_' . $tok1);
T::check('havola bir martalik', strpos($fake->lastText(), 'eskirgan yoki ishlatilgan') !== false && $app->team->perms($O, $H2) === null);
$text($H2, '/start team_' . str_repeat('a', 24));
T::check('soxta token', strpos($fake->lastText(), 'eskirgan yoki ishlatilgan') !== false);
$exp = $app->team->createInvite($O, 'all', 2, $clock)['token'];
$db->exec('UPDATE team_invites SET expires_at = ? WHERE token_hash = ?', ['2026-12-01 00:00:00', hash('sha256', $exp)]);
$text($H2, '/start team_' . $exp);
T::check('muddati o\'tgan havola', strpos($fake->lastText(), 'eskirgan') !== false);

// yordamchi (Muharrir) ishlashi
$text($H, '/newpost');
T::check('post yaratishda ish joyi ko\'rsatiladi', strpos($fake->lastText(), 'Ish joyi') !== false);
$send($H, ['text' => 'Yordamchi posti']);
T::check('egasining kanali bilan preview (egasi ULTRA — nishonsiz)', strpos((string) ($fake->of('sendMessage')[0]['text'] ?? ''), 'Yordamchi posti') === 0);
$press($H, 'p:now');
T::check('Muharrirga «Hozir yuborish» yo\'q', strpos($fake->lastText(), 'ruxsat yo\'q') !== false && (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE text = 'Yordamchi posti'") === 0
    && ($app->states->get($H)['state'] ?? '') === 'post_preview');
$press($H, 'p:time');
$press($H, 't:tom09');
$hp = $db->one("SELECT * FROM scheduled_posts WHERE text = 'Yordamchi posti'");
T::check('rejalangan post EGASI nomidan, kanal egasiniki, created_by — yordamchi', (int) ($hp['user_id'] ?? 0) === $O && (int) $hp['channel_id'] === $OC && (int) $hp['created_by'] === $H);
$text($H, '📅 Rejalashtirilgan');
T::check('navbat: egasining postlari, ish joyi qatori', strpos($fake->lastText(), 'Ish joyi') !== false && strpos($kbT(), 'q:v:' . (int) $hp['id']) !== false);
$press($H, 'q:d:' . (int) $hp['id']);
T::check('Muharrir postni bekor qila olmaydi', strpos($fake->lastText(), 'ruxsat yo\'q') !== false);
$press($H, 'q:dok:' . (int) $hp['id']);
T::eq('to\'g\'ridan-to\'g\'ri bekor qilish ham rad', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [(int) $hp['id']]), 'pending');
$text($O, '📅 Rejalashtirilgan');
T::check('egasi ham shu postni ko\'radi', strpos($kbT(), 'q:v:' . (int) $hp['id']) !== false);

// ikkinchi yordamchi (Faqat ko'rish) va o'rinlar
$tok2 = $app->team->createInvite($O, 'viewer', $app->teamSeats($O), $clock)['token'];
$tok3 = $app->team->createInvite($O, 'all', $app->teamSeats($O), $clock)['token'];
$text($H2, '/start team_' . $tok2);
$text($H3, '/start team_' . $tok3);
T::check('2 o\'rin to\'lgan: uchinchisi qo\'shilmaydi', strpos($fake->lastText(), 'to\'lgan') !== false && $app->team->perms($O, $H3) === null && $app->team->count($O) === 2);
T::eq('to\'lgan jamoaga yangi taklif yaratilmaydi', $app->team->createInvite($O, 'all', $app->teamSeats($O), $clock)['error'] ?? '', 'full');
$press($O, 'set:team');
T::check('egasi: 2/2, taklif tugmasi yo\'q, a\'zolar ro\'yxati', strpos($fake->lastText(), '(2/2)') !== false && strpos($kbT(), 'tm:inv') === false && strpos($kbT(), 'tm:rm:' . $H2) !== false);
$text($H2, '/newpost');
T::check('Faqat ko\'rish: post yarata olmaydi', strpos($fake->lastText(), 'ruxsat yo\'q') !== false && $app->states->get($H2) === null);
$text($H2, '/ai');
T::check('Faqat ko\'rish: AI yo\'q', strpos($fake->lastText(), 'ruxsat yo\'q') !== false || strpos($fake->lastText(), 'yoqilmagan') !== false);

// ish joyini almashtirish
$press($H, 'set:team');
T::check('yordamchi: ish joyi tanlovi va chiqish tugmasi', strpos($kbT(), 'tm:ws:0') !== false && strpos($kbT(), 'tm:ws:' . $O) !== false && strpos($kbT(), 'tm:lv:' . $O) !== false);
$press($H, 'tm:ws:0');
$text($H, '/newpost');
T::check('o\'z ish joyida: o\'z kanallari (yo\'q) — kanal ulash so\'raladi', strpos($fake->texts(), 'Avval kanal ulang') !== false);
$app->states->clear($H);
$press($H, 'tm:ws:' . $P);
T::eq('a\'zo bo\'lmagan egaga o\'tib bo\'lmaydi', $app->team->workspace($H), null);
$press($H, 'tm:ws:' . $O);
T::eq('egasining ish joyiga qaytish', $app->team->workspace($H), $O);

// egasining tarifi tugasa
$db->exec("UPDATE users SET subscription_expires_at = '2026-12-01 00:00:00' WHERE user_id = ?", [$O]);
$text($H, '/newpost');
T::check('egasining ULTRA si tugasa: yordamchi o\'z ish joyiga qaytadi', strpos($fake->texts(), 'Ish joyi') === false && $app->team->workspace($H) === null);
$app->states->clear($H);
$db->exec("UPDATE users SET plan_type = 'ultra', subscription_expires_at = '2027-01-10 00:00:00' WHERE user_id = ?", [$O]);
$app->team->setWorkspace($H, $O);

// Mini App ham shu ish joyida
$init = $mkInit(['id' => $H, 'first_name' => 'Hamza'], $clock->getTimestamp() - 30, $token);
[$st, $me] = MiniAppApi::handle($app, 'me', [], $init);
T::check('Mini App: egasining kanallari, ish joyi va ruxsatlar', $st === 200 && count($me['channels']) === 1 && $me['channels'][0]['title'] === 'Egasi kanali'
    && $me['workspace']['owner_id'] === $O && $me['workspace']['perms'] === ['create', 'ai'] && $me['plan']['tier'] === 'ultra');
$chO = (int) $me['channels'][0]['id'];
T::eq('Mini App: hozir yuborish — ruxsat yo\'q (403)', MiniAppApi::handle($app, 'post_create', ['channel_id' => $chO, 'text' => 'MA', 'when' => 'now'], $init)[0], 403);
[$st, $r] = MiniAppApi::handle($app, 'post_create', ['channel_id' => $chO, 'text' => 'MA yordamchi', 'when' => $clock->modify('+1 day')->format('Y-m-d') . 'T12:00'], $init);
T::check('Mini App: rejalash — egasi nomidan', $st === 200 && (int) $db->value('SELECT user_id FROM scheduled_posts WHERE id = ?', [(int) $r['id']]) === $O
    && (int) $db->value('SELECT created_by FROM scheduled_posts WHERE id = ?', [(int) $r['id']]) === $H);
T::eq('Mini App: bekor qilish — ruxsat yo\'q', MiniAppApi::handle($app, 'post_cancel', ['id' => (int) $r['id']], $init)[0], 404);
T::check('Mini App: navbatda egasining postlari', count(MiniAppApi::handle($app, 'posts', [], $init)[1]['posts']) >= 2);
$initP = $mkInit(['id' => $P, 'first_name' => 'P'], $clock->getTimestamp() - 30, $token);
T::eq('begona odam egasining kanaliga post yoza olmaydi', MiniAppApi::handle($app, 'post_create', ['channel_id' => $chO, 'text' => 'x', 'when' => 'now'], $initP)[1]['error'] ?? '', 'channel');

// olib tashlash va chiqish
$press($O, 'tm:rm:' . $H);
T::check('olib tashlash tasdiq so\'raydi', strpos($kbT(), 'tm:rmok:' . $H) !== false);
$press($O, 'tm:rmok:' . $H);
T::check('yordamchi olib tashlandi va xabar oldi, ish joyi tozalandi', $app->team->perms($O, $H) === null && $app->team->workspace($H) === null
    && strpos($fake->texts(), 'olib tashladi') !== false);
$press($P, 'tm:rmok:' . $H2);
T::eq('begona odam boshqaning yordamchisini o\'chira olmaydi', $app->team->perms($O, $H2) !== null, true);
$press($H2, 'tm:lv:' . $O);
T::check('yordamchi o\'zi chiqdi, egasiga xabar', $app->team->perms($O, $H2) === null && strpos($fake->texts(), 'jamoangizdan chiqdi') !== false);
$text($H, '/team');
T::check('/team buyrug\'i', strpos($fake->lastText(), 'Jamoa') !== false);
