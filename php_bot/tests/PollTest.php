<?php
// 22-bosqich: so'rovnoma va viktorina (ExtrasTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\PollHandler;
use PostAssist\Services\PostRender;

T::section('AI. So\'rovnoma va viktorina');
T::eq('variantlar: raqam/belgi olinadi', PollHandler::parseOptions("1. Ha\n2) Yo'q\n- Bilmayman"), ['options' => ['Ha', "Yo'q", 'Bilmayman'], 'quiz' => null]);
T::eq('viktorina: * to\'g\'ri javob', PollHandler::parseOptions("Toshkent\n*Samarqand\nBuxoro"), ['options' => ['Toshkent', 'Samarqand', 'Buxoro'], 'quiz' => 1]);
T::eq('ikkita * rad', PollHandler::parseOptions("*A\n*B"), 'poll_two_correct');
T::eq('bitta variant rad', PollHandler::parseOptions('Faqat bitta'), 'poll_opts_count');
T::eq('11 ta variant rad', PollHandler::parseOptions(implode("\n", range(1, 11)) . "\nx"), 'poll_opts_count');
T::eq('takror variant rad', PollHandler::parseOptions("Ha\nha"), 'poll_opt_dup');
T::eq('uzun variant rad', PollHandler::parseOptions("Ha\n" . str_repeat('x', 101)), 'poll_opt_long');
$pp = PostRender::pollParams(-100, ['text' => 'Savol?', 'media' => '{"options":["A","B"],"quiz":null}'], 'Bot', true, true);
T::check('sendPoll: anonim, ko\'p javob, bepul nishon savolda', $pp['is_anonymous'] === true && !empty($pp['allows_multiple_answers']) && $pp['question'] === 'Savol? · 🤖 @Bot'
    && $pp['options'] === [['text' => 'A'], ['text' => 'B']]);
$pq = PostRender::pollParams(-100, ['text' => 'Q', 'media' => ['options' => ['A', 'B'], 'quiz' => 0]], 'Bot', false, true);
T::check('viktorina: quiz + to\'g\'ri javob, ko\'p javob yo\'q, PRO nishonsiz', $pq['type'] === 'quiz' && $pq['correct_option_id'] === 0 && !isset($pq['allows_multiple_answers']) && $pq['question'] === 'Q');

$text($XU, '/newpost');
T::check('post boshida «📊 So\'rovnoma»', strpos($kbX(), 'poll:start') !== false);
$press($XU, 'poll:start');
T::eq('savol so\'raladi', $app->states->get($XU)['state'] ?? null, 'poll_q');
$text($XU, str_repeat('s', 301));
T::check('uzun savol rad', strpos($fake->lastText(), '300') !== false);
$text($XU, 'Qaysi shahar poytaxt bo\'lgan?');
T::eq('variantlar so\'raladi', $app->states->get($XU)['state'] ?? null, 'poll_opts');
$text($XU, "*A\n*B");
T::check('xato variantlar: aniq sabab, holat saqlanadi', strpos($fake->lastText(), 'bitta to\'g\'ri') !== false && ($app->states->get($XU)['state'] ?? '') === 'poll_opts');
$text($XU, "Toshkent\n*Samarqand\nBuxoro");
$pv = $fake->of('sendPoll');
T::check('preview: viktorina so\'rovnomasi va boshqaruv', count($pv) === 1 && ($pv[0]['type'] ?? '') === 'quiz' && (int) $pv[0]['correct_option_id'] === 1
    && ($app->states->get($XU)['state'] ?? '') === 'post_preview' && strpos($kbX(), 'p:now') !== false);
$press($XU, 'p:more');
T::check('«Qo\'shimcha»: tugma/reaksiya/izoh yo\'q, viktorinada «Ko\'p javob» yo\'q', strpos($kbX(), 'p:btn') === false && strpos($kbX(), 'p:rx') === false
    && strpos($kbX(), 'p:o_comments') === false && strpos($kbX(), 'p:o_multi') === false && strpos($kbX(), 'p:o_silent') !== false);
$press($XU, 'p:btn');
T::check('tugma qo\'shishga urinish — tushuntirish', strpos($fake->lastText(), 'So\'rovnomaga') !== false);
$press($XU, 'p:now');
$cp = array_values(array_filter($fake->of('sendPoll'), function ($p) use ($XC) { return (int) $p['chat_id'] === $XC; }));
T::check('kanalga chiqdi: variantlar va to\'g\'ri javob bilan (bepul: nishon savolda)', count($cp) === 1 && strpos((string) json_encode($cp[0]['options'] ?? ''), 'Samarqand') !== false
    && (int) ($cp[0]['correct_option_id'] ?? -1) === 1 && strpos((string) $cp[0]['question'], '@PostAssistrobot') !== false && strpos($fake->lastText(), 'Yuborildi') !== false);
$sp = $db->one('SELECT * FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$XU]);
T::check('saqlangan: poll, savol, variantlar', $sp['post_type'] === 'poll' && PostRender::pollData($sp)['options'] === ['Toshkent', 'Samarqand', 'Buxoro']);
// oddiy so'rovnoma + ko'p javob, rejalashtirish
$press($XU, 'poll:start');
$text($XU, 'Qaysi kunlar qulay?');
$text($XU, "Dushanba\nChorshanba\nJuma");
$press($XU, 'p:more');
T::check('oddiy so\'rovnomada «Ko\'p javob» bor', strpos($kbX(), 'p:o_multi') !== false);
$press($XU, 'p:o_multi');
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$XU]);
$press($XU, 'p:time');
$press($XU, 't:tom09');
$sp2 = $db->one('SELECT * FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$XU]);
T::check('rejalashtirildi, ko\'p javob saqlandi', $sp2['post_type'] === 'poll' && $sp2['status'] === 'pending' && $sp2['options'] === 'multi');
$db->exec('UPDATE scheduled_posts SET scheduled_time = ? WHERE id = ?', [$clock->modify('-1 minute')->format('Y-m-d H:i:s'), (int) $sp2['id']]);
$fake->reset();
(new \PostAssist\Services\Scheduler($app, static function (int $us): void {
}))->run(5);
$cp2 = array_values(array_filter($fake->of('sendPoll'), function ($p) use ($XC) { return (int) $p['chat_id'] === $XC; }));
T::check('cron: ko\'p javobli so\'rovnoma chiqdi', count($cp2) === 1 && !empty($cp2[0]['allows_multiple_answers']));
$smp = $db->one('SELECT id FROM sent_messages WHERE post_id = ?', [(int) $sp2['id']]);
$press($XU, 's:e:' . (int) $smp['id']);
T::check('chiqqan so\'rovnomani tahrirlab bo\'lmaydi — tushuntirish', strpos($fake->lastText(), 'tahrirlashga ruxsat bermaydi') !== false);
