<?php
// 8-bosqich: AI kontent-reja va autopilot (MarketTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Config;
use PostAssist\Repo\ContentPlans;
use PostAssist\Services\Ai;
use PostAssist\Services\Plans;
use PostAssist\Services\Scheduler;

T::section('T. Kontent-reja va Autopilot');
T::eq('g\'oyalar: raqam/belgi olinadi, takror va qisqa tashlanadi', ContentPlans::parseIdeas("1. Birinchi g'oya matni\n2) Ikkinchi g'oya\n- Birinchi g'oya matni\n• ok\n* «Uchinchi foydali g'oya»"),
    ["Birinchi g'oya matni", "Ikkinchi g'oya", "Uchinchi foydali g'oya"]);
T::eq('g\'oyalar: eng ko\'pi 7 ta', count(ContentPlans::parseIdeas(implode("\n", array_map(function ($i) { return "G'oya raqami {$i}"; }, range(1, 12))))), 7);

$clock = new DateTimeImmutable('2026-12-20 02:00:00', new DateTimeZone('UTC')); // Toshkent 07:00
$AP = 9600;
$AX = 9601;
$text($AP, '/start');
$text($AX, '/start');
$APC = -1009600;
$fake->chats[$APC] = ['id' => $APC, 'type' => 'channel', 'title' => 'Ingliz tili'];
$fake->members["{$APC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($AP, $APC, 'Ingliz tili', null, 0);
$REF = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$APC]);

$apCalls = [];
$apQueue = [];
$app->ai = new Ai(new Config(['gemini_api_key' => 'GK']), static function (string $url, array $h, string $body) use (&$apCalls, &$apQueue): array {
    $apCalls[] = json_decode($body, true);
    return $apQueue ? array_shift($apQueue) : [500, ''];
});
$gemA = static function (string $t): array {
    return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => $t]]]]]])];
};
$promptA = static function () use (&$apCalls): string {
    $b = end($apCalls);
    return (string) ($b['contents'][0]['parts'][0]['text'] ?? '');
};
$kbA = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$sched = new Scheduler($app, static function (int $us): void {
});

// --- kontent-reja (bepul tarifda ham)
$text($AP, '✨ AI post');
T::check('AI post ekranida Kontent-reja va Autopilot tugmalari', strpos($kbA(), 'cp:show') !== false && strpos($kbA(), 'ap:show') !== false);
$press($AP, 'cp:show');
T::eq('reja yo\'q: mavzu so\'raladi', $app->states->get($AP)['state'] ?? null, 'cp_topic');
$apQueue[] = $gemA("1. Har kuni bitta ibora\n2. Eng ko'p xato qilinadigan so'zlar\n3. Film orqali ingliz tili\n4. Savol-javob: Present Perfect\n5. Kichik test\n6. O'quvchi hikoyasi\n7. Haftalik so'rovnoma");
$used0 = $app->aiUsage->usedOn($AP, $app->today());
$text($AP, 'Ingliz tili o\'rganish kanali, boshlovchilar uchun');
$planId = (int) $db->value('SELECT id FROM content_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$AP]);
T::check('reja tuzildi: 7 g\'oya va «✍️» tugmalari', $planId > 0 && strpos($fake->lastText(), 'Film orqali') !== false && strpos($kbA(), 'cp:w:' . $planId . ':6') !== false);
T::eq('reja: 1 ta AI so\'rovi sarflandi', $app->aiUsage->usedOn($AP, $app->today()), $used0 + 1);
T::check('reja so\'rovida mavzu bor', strpos($promptA(), 'boshlovchilar') !== false);
$press($AP, 'cp:w:' . $planId . ':2');
$st = $app->states->get($AP);
T::check('g\'oya tanlandi: uslub so\'raladi, mavzuda g\'oya', ($st['state'] ?? '') === 'ai_style' && strpos((string) ($st['data']['topic'] ?? ''), 'Film orqali') !== false);
T::check('g\'oya belgilandi (✅)', $app->plans->get($AP, $planId)['items'][2]['done'] === true);
$apQueue[] = $gemA('<b>Film orqali ingliz tili</b> — eng qiziqarli usul.');
$press($AP, 'ai:s:useful');
T::eq('AI post preview\'ga tushdi', $app->states->get($AP)['state'] ?? null, 'post_preview');
$press($AX, 'cp:w:' . $planId . ':0');
T::check('begona reja ochilmaydi (IDOR)', strpos($fake->lastText(), 'topilmadi') !== false && ($app->states->get($AX)['state'] ?? '') !== 'ai_style');
$apQueue[] = $gemA('ok');
$app->states->set($AP, 'cp_topic');
$text($AP, 'Juda qisqa javob beradigan mavzu');
T::check('AI ro\'yxat bermasa: tushunarli xabar', strpos($fake->lastText(), 'tushunarli') !== false);
$press($AP, 'm:home');

// --- autopilot: bepul tarifda yo'q
$text($AP, '/autopilot');
T::check('bepul: autopilot PRO/ULTRA da, tariflar tugmasi', strpos($fake->lastText(), 'PRO') !== false && strpos($kbA(), 'pl:show') !== false && strpos($kbA(), 'ap:new') === false);
$press($AP, 'ap:new');
T::check('bepul: yaratib bo\'lmaydi', strpos($fake->lastText(), 'PRO') !== false && ($app->states->get($AP)['state'] ?? '') !== 'ap_topic');

Plans::grant($db, $AP, 'pro', 30, $clock);
$press($AP, 'ap:show');
T::check('PRO: «➕ Qo\'shish»', strpos($kbA(), 'ap:new') !== false);
$press($AP, 'ap:new');
T::eq('bitta kanal: darhol mavzu so\'raladi', $app->states->get($AP)['state'] ?? null, 'ap_topic');
$text($AP, 'ab');
T::check('qisqa mavzu rad', strpos($fake->lastText(), '3–500') !== false);
$text($AP, 'Ingliz tili: har kuni bitta ibora, misol va mashq');
T::eq('mavzu → uslub', $app->states->get($AP)['state'] ?? null, 'ap_style');
$press($AP, 'ap:st:useful');
T::check('uslub → vaqt (tugmalar va mintaqa)', ($app->states->get($AP)['state'] ?? '') === 'ap_time' && strpos($kbA(), 'ap:t:0800') !== false && strpos($fake->lastText(), 'Asia/Tashkent') !== false);
$text($AP, '25:00');
T::check('noto\'g\'ri vaqt rad', strpos($fake->lastText(), 'SS:DD') !== false && ($app->states->get($AP)['state'] ?? '') === 'ap_time');
$text($AP, '8:00');
T::eq('vaqt → rejim', $app->states->get($AP)['state'] ?? null, 'ap_mode');
$press($AP, 'ap:m:review');
$apId = (int) $db->value('SELECT id FROM autopilots WHERE user_id = ?', [$AP]);
$row = $app->autopilots->get($apId);
T::check('autopilot saqlandi: 08:00, tekshirib, bugundan (07:00 hali vaqt emas)', $apId > 0 && (int) $row['post_time'] === 480 && $row['mode'] === 'review' && $row['last_run'] === null
    && strpos($fake->texts(), 'har kuni 08:00') !== false);
$press($AP, 'ap:new');
T::check('PRO: ikkinchi autopilot yo\'q (limit 1)', strpos($fake->lastText(), '1 ta') !== false);
T::eq('limitlar: free 0, pro 1, ultra 3, admin 10', [$app->autopilotLimit($AX), $app->autopilotLimit($AP), $app->autopilotLimit($ADMIN)], [0, 1, 10]);

// IDOR
$press($AX, 'ap:v:' . $apId);
T::check('begona autopilot ko\'rinmaydi', strpos($fake->lastText(), 'Ingliz tili: har kuni') === false);
$press($AX, 'ap:dok:' . $apId);
T::eq('begona odam o\'chira olmaydi', $app->autopilots->get($apId) !== null, true);
$press($AX, 'ap:tg:' . $apId);
T::eq('begona odam to\'xtata olmaydi', (int) $app->autopilots->get($apId)['active'], 1);

// --- cron: vaqti emas
$fake->reset();
$sched->run(5);
T::eq('07:00 — hali post yozilmaydi', count($apCalls), 3);
$clock = new DateTimeImmutable('2026-12-20 03:05:00', new DateTimeZone('UTC')); // 08:05
$apQueue[] = $gemA("<b>Bugungi ibora:</b> break the ice\nMisol: ...");
$fake->reset();
$sched->run(5);
T::check('08:05 — qoralama egasiga keldi (kanalga emas)', strpos($fake->texts(), 'break the ice') !== false && strpos(json_encode($fake->of('sendMessage')), 'apd:ok:') !== false
    && !array_filter($fake->of('sendMessage'), function ($p) use ($APC) { return (int) $p['chat_id'] === $APC; }));
T::check('so\'rovda mavzu va sana', strpos($promptA(), 'har kuni bitta ibora') !== false && strpos($promptA(), '2026-12-20') !== false);
T::eq('bugungi kun band qilindi', $app->autopilots->get($apId)['last_run'], '2026-12-20');
$n = count($apCalls);
$sched->run(5);
T::eq('o\'sha kuni qayta yozilmaydi', count($apCalls), $n);
$dId = (int) $db->value('SELECT id FROM autopilot_drafts WHERE autopilot_id = ? ORDER BY id DESC LIMIT 1', [$apId]);
$press($AX, 'apd:ok:' . $dId);
T::check('begona qoralama ishlamaydi', strpos($fake->lastText(), 'eskirgan') !== false);
$press($AP, 'apd:ok:' . $dId);
$chanSends = array_filter($fake->of('sendMessage'), function ($p) use ($APC) { return (int) $p['chat_id'] === $APC; });
T::check('✅ Kanalga: post kanalga chiqdi', count($chanSends) === 1 && strpos($fake->texts(), 'Yuborildi') !== false);
$press($AP, 'apd:ok:' . $dId);
T::eq('ikkinchi bosish — ikkinchi post yo\'q', count(array_filter($fake->of('sendMessage'), function ($p) use ($APC) { return (int) $p['chat_id'] === $APC; })), 0);

// ertasi kun: avtomatik rejim
$press($AP, 'ap:mo:' . $apId);
T::eq('rejim almashdi: avtomatik', $app->autopilots->get($apId)['mode'], 'auto');
$clock = new DateTimeImmutable('2026-12-21 03:10:00', new DateTimeZone('UTC'));
$apQueue[] = $gemA('<b>Ibora:</b> piece of cake');
$fake->reset();
$sched->run(5);
T::check('avtomatik: post to\'g\'ridan-to\'g\'ri kanalga', count(array_filter($fake->of('sendMessage'), function ($p) use ($APC) { return (int) $p['chat_id'] === $APC; })) === 1);
T::check('oldingi post takrorlanmasin deb so\'rovga qo\'shildi', strpos($promptA(), 'takrorlama') !== false && strpos($promptA(), 'break the ice') !== false);
T::check('bepul nishon yo\'q (PRO)', strpos(json_encode(array_values(array_filter($fake->of('sendMessage'), function ($p) use ($APC) { return (int) $p['chat_id'] === $APC; }))), 'PostAssistrobot') === false);

// AI xato: limit qaytadi
$clock = new DateTimeImmutable('2026-12-22 03:10:00', new DateTimeZone('UTC'));
$used = $app->aiUsage->usedOn($AP, $app->today());
$fake->reset();
$sched->run(5); // navbat bo'sh — 500
T::check('AI xato: egasiga xabar, limit qaytdi', strpos($fake->texts(), 'AI javob bermadi') !== false && $app->aiUsage->usedOn($AP, $app->today()) === $used);

// cron uzoq to'xtagan (6 soatdan kech) — o'tkazib yuboriladi
$clock = new DateTimeImmutable('2026-12-23 12:00:00', new DateTimeZone('UTC')); // 17:00
$n = count($apCalls);
$sched->run(5);
T::check('6 soatdan kech: post yozilmaydi, kun belgilanadi', count($apCalls) === $n && $app->autopilots->get($apId)['last_run'] === '2026-12-23');

// ⚡ Hozir sinash va ✏️ Tahrirlash
$press($AP, 'ap:mo:' . $apId);
$apQueue[] = $gemA('Sinov posti matni');
$press($AP, 'ap:run:' . $apId);
$dId2 = (int) $db->value('SELECT id FROM autopilot_drafts WHERE autopilot_id = ? ORDER BY id DESC LIMIT 1', [$apId]);
T::check('⚡ Hozir sinash: qoralama keldi', $dId2 > $dId && strpos($fake->texts(), 'Sinov posti') !== false);
$apQueue[] = $gemA('Yangi variant matni');
$press($AP, 'apd:re:' . $dId2);
T::check('🔄 Boshqa variant: qoralama yangilandi', strpos($fake->texts(), 'Yangi variant') !== false
    && $db->value('SELECT text FROM autopilot_drafts WHERE id = ?', [$dId2]) === 'Yangi variant matni');
$press($AP, 'apd:ed:' . $dId2);
$st = $app->states->get($AP);
T::check('✏️ Tahrirlash: odatdagi preview (kanal tanlangan)', ($st['state'] ?? '') === 'post_preview' && (int) ($st['data']['channel'] ?? 0) === $REF
    && strpos((string) $st['data']['draft']['text'], 'Yangi variant') !== false);
$press($AP, 'apd:no:' . $dId2);
T::check('ishlatilgan qoralama qayta ishlamaydi', strpos($fake->lastText(), 'eskirgan') !== false);
$press($AP, 'm:home');

// pauza / yoqish
$press($AP, 'ap:tg:' . $apId);
T::eq('⏸ to\'xtatildi', (int) $app->autopilots->get($apId)['active'], 0);
$press($AP, 'ap:tg:' . $apId);
T::check('▶️ yoqildi (bugungi vaqt o\'tgan — ertadan)', (int) $app->autopilots->get($apId)['active'] === 1 && $app->autopilots->get($apId)['last_run'] === '2026-12-23');

// tarif tugadi — to'xtaydi
$db->exec("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL WHERE user_id = ?", [$AP]);
$clock = new DateTimeImmutable('2026-12-24 03:10:00', new DateTimeZone('UTC'));
$fake->reset();
$n = count($apCalls);
$sched->run(5);
T::check('tarif tugadi: autopilot to\'xtadi, AI chaqirilmadi', (int) $app->autopilots->get($apId)['active'] === 0 && count($apCalls) === $n && strpos($fake->texts(), 'to\'xtatildi') !== false);
$press($AP, 'ap:tg:' . $apId);
T::eq('bepul tarifda qayta yoqib bo\'lmaydi', (int) $app->autopilots->get($apId)['active'], 0);

// o'chirish (tasdiq bilan)
$press($AP, 'ap:del:' . $apId);
T::check('o\'chirish: tasdiq so\'raladi', strpos($kbA(), 'ap:dok:' . $apId) !== false && $app->autopilots->get($apId) !== null);
$press($AP, 'ap:dok:' . $apId);
T::eq('o\'chirildi', $app->autopilots->get($apId), null);
$app->ai = new Ai(new Config([]));
