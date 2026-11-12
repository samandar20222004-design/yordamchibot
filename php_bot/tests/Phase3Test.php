<?php
// 3-bosqich integratsiya testi (IntegrationTest.php -> Phase2Test.php dan keyin; o'sha o'zgaruvchilar).
declare(strict_types=1);

use PostAssist\Services\Scheduler;

T::section('J. Vaqt mintaqasi, takroriy post, reaksiya, avto-o\'chirish, albom');
$clock = new DateTimeImmutable('2026-11-20 10:00:00', new DateTimeZone('UTC'));
$sched = new Scheduler($app, static function (int $us): void {
});
$W = $U2; // PRO, CH kanali unga ulangan
$press($W, 'lang:uz');
$chW = $app->channels->listFor($W)[0];
$last = static function () use ($db): array {
    return $db->one('SELECT * FROM scheduled_posts ORDER BY id DESC LIMIT 1') ?? [];
};
$draftText = static function (string $t) use ($text, $send, $W) {
    $text($W, '/newpost');
    $send($W, ['text' => $t]);
};

// --- vaqt mintaqasi
$text($W, '/timezone');
T::check('/timezone: joriy zona va tugmalar', strpos($fake->lastText(), 'Asia/Tashkent') !== false && strpos($mk($fake->of('sendMessage')[0] ?? []), 'tz:Europe\/Moscow') !== false);
$text($W, 'Marsda');
T::check('noma\'lum zona rad', stripos($fake->lastText(), 'topilmadi') !== false);
$text($W, 'Samarqand');
T::eq('shahar nomi bilan: Asia/Samarkand', $app->users->get($W)['timezone'] ?? null, 'Asia/Samarkand');
$press($W, 'tz:Europe/Moscow');
T::check('tugma bilan: Europe/Moscow, hozirgi soat ko\'rsatiladi', ($app->users->get($W)['timezone'] ?? null) === 'Europe/Moscow'
    && strpos($fake->lastText(), '13:00') !== false);
$press($W, 'tz:Mars/Base');
T::eq('soxta zona tugmasi rad', $app->users->get($W)['timezone'] ?? null, 'Europe/Moscow');
$text($W, '⚙️ Sozlamalar');
T::check('sozlamalarda zona', strpos($fake->lastText(), 'Europe/Moscow') !== false && strpos($mk($fake->of('sendMessage')[0] ?? []), 'set:tz') !== false);
$draftText('Moskva vaqti');
$press($W, 'p:time');
T::check('vaqt so\'rovida foydalanuvchi zonasi', strpos($fake->lastText(), 'Europe/Moscow') !== false);
$text($W, 'ertaga 09:00');
T::eq('ertaga 09:00 Moskva = 06:00 UTC', $last()['scheduled_time'] ?? null, '2026-11-21 06:00:00');
T::check('javobda Moskva vaqti', strpos($fake->lastText(), '21.11.2026 09:00') !== false);
$tzPost = (int) $last()['id'];

// --- takroriy: har kuni
$draftText('Har kungi post');
$press($W, 'p:more');
$press($W, 'p:rep');
T::check('takror menyusi', strpos($mk($fake->of('sendMessage')[0] ?? []), 'pr:twice') !== false);
$press($W, 'pr:daily');
T::check('preview ostida «Har kuni»', strpos($fake->texts(), '🔄 Har kuni') !== false);
$press($W, 'p:time');
$text($W, '12:00');
$rp = $last();
T::eq('takroriy saqlandi: daily, 12:00 (720), birinchisi ertaga 09:00 UTC', [$rp['recurrence_type'], (int) $rp['recurrence_time'], $rp['scheduled_time']], ['daily', 720, '2026-11-21 09:00:00']);
T::check('javobda jadval', strpos($fake->lastText(), 'Har kuni 12:00 da') !== false);
$rid = (int) $rp['id'];
$clock = new DateTimeImmutable('2026-11-21 09:00:30', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
$rp = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [$rid]);
T::eq('cron: chiqdi va ertangi kunga qaytdi', [$rp['status'], $rp['scheduled_time'], (int) $rp['sent_count']], ['pending', '2026-11-22 09:00:00', 1]);
T::check('egasiga birinchi marta xabar (keyingisi bilan)', strpos($fake->texts(), 'Takroriy post chiqdi') !== false && strpos($fake->texts(), '22.11.2026 12:00') !== false);
T::eq('zonali oddiy post ham chiqdi', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$tzPost]), 'sent');
$clock = new DateTimeImmutable('2026-11-22 09:00:10', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
$toOwner = array_filter($fake->of('sendMessage'), static function ($m) use ($W) {
    return (int) $m['chat_id'] === $W;
});
T::check('ikkinchi chiqish: kanalga ketdi, egasiga xabar yo\'q', count($fake->of('sendMessage')) === 1 && !$toOwner
    && (int) $db->value('SELECT sent_count FROM scheduled_posts WHERE id = ?', [$rid]) === 2);
$clock = new DateTimeImmutable('2026-11-26 09:30:00', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
$toCh = static function () use ($fake, $CH): int {
    return count(array_filter($fake->of('sendMessage'), static function ($m) use ($CH) {
        return (int) $m['chat_id'] === $CH;
    }));
};
T::eq('cron 4 kun ishlamasa: faqat bitta nusxa, keyingisi ertaga', [$toCh(), $db->value('SELECT scheduled_time FROM scheduled_posts WHERE id = ?', [$rid])],
    [1, '2026-11-27 09:00:00']);
$press($W, 'q:v:' . $rid);
T::check('navbatda: jadval va necha marta chiqqani', strpos($fake->lastText(), 'Har kuni 12:00 da') !== false && strpos($fake->lastText(), 'chiqdi: 3 marta') !== false);
$text($W, '📅 Rejalashtirilgan');
T::check('ro\'yxatda 🔄 belgisi', strpos($mk($fake->of('sendMessage')[0] ?? []), '🔄') !== false);
$press($W, 'q:dok:' . $rid);
$clock = new DateTimeImmutable('2026-11-27 09:01:00', new DateTimeZone('UTC'));
$fake->reset();
$sched->run(5);
T::eq('to\'xtatilgan takroriy post chiqmaydi', [$db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$rid]), $toCh()], ['cancelled', 0]);

// --- kuniga 2 marta
$draftText('Ikki marta');
$press($W, 'pr:twice');
T::eq('ikkinchi vaqt kutilmoqda', $app->states->get($W)['state'] ?? null, 'post_time2');
$text($W, '25:00');
T::check('noto\'g\'ri soat rad', strpos($fake->lastText(), 'HH:MM') !== false);
$text($W, '18:30');
T::check('preview: Kuniga 2 marta (+18:30)', strpos($fake->texts(), 'Kuniga 2 marta (+18:30)') !== false);
$press($W, 'p:time');
$text($W, '09:00');
$rp = $last();
T::eq('twice: 09:00 (540) va 18:30 (1110)', [$rp['recurrence_type'], (int) $rp['recurrence_time'], (int) $rp['recurrence_day']], ['twice', 540, 1110]);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ?", [(int) $rp['id']]);
$n = (int) $db->value('SELECT COUNT(*) FROM scheduled_posts');
$draftText('Bir xil vaqt');
$press($W, 'pr:twice');
$text($W, '09:00');
$press($W, 'p:time');
$text($W, '09:00');
T::check('ikki vaqt bir xil: rad, post yaratilmadi', strpos($fake->lastText(), 'farq qilishi') !== false && (int) $db->value('SELECT COUNT(*) FROM scheduled_posts') === $n);
$app->states->clear($W);

// --- har hafta, «hozir yuborish» bilan
$draftText('Haftalik');
$press($W, 'pr:weekly');
$press($W, 'p:now');
$rp = $last();
T::eq('hozir + har hafta: chiqdi, 7 kundan keyin qaytadi (shu hafta kuni, Moskva)', [$rp['status'], $rp['scheduled_time'], (int) $rp['recurrence_day'], (int) $rp['sent_count']],
    ['pending', '2026-12-04 09:01:00', 5, 1]);
T::check('javobda «Keyingisi»', strpos($fake->lastText(), 'Keyingisi: 04.12.2026 12:01') !== false);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ?", [(int) $rp['id']]);

// --- har oy
$draftText('Oylik');
$press($W, 'pr:monthly');
$press($W, 'p:time');
$text($W, '30.11 10:00');
T::eq('har oy: 30-kuni', [$last()['recurrence_type'], (int) $last()['recurrence_day']], ['monthly', 30]);
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ?", [(int) $last()['id']]);

// --- reaksiyalar
$draftText('Reaksiyali post');
$press($W, 'p:rx');
$press($W, 'px:c');
$text($W, 'zo\'r');
T::check('o\'z reaksiyasi: matn rad', strpos($fake->lastText(), 'Faqat emoji') !== false);
$text($W, '👍 🎉');
T::check('o\'z reaksiyasi preview\'da', strpos($mk($fake->of('sendMessage')[0] ?? []), '🎉') !== false);
$press($W, 'px:1');
$prev = $fake->of('sendMessage')[0] ?? [];
T::check('tayyor to\'plam: ❤️ 🔥 😂 (rx tugmalari)', strpos($mk($prev), 'rx:2') !== false && strpos($mk($prev), '😂') !== false);
$press($W, 'p:now');
$msgRow = $db->one('SELECT * FROM sent_messages ORDER BY id DESC LIMIT 1');
T::check('kanal postida reaksiya tugmalari, sent_messages yozildi', ($msgRow['reactions'] ?? '') === '❤️,🔥,😂'
    && strpos($mk($fake->of('sendMessage')[0] ?? []), 'rx:0') !== false && (int) $msgRow['chat_id'] === $CH);
$react = static function (int $uid, int $mid, string $data, int $chat) use (&$upd, $router, $from, $fake) {
    $fake->reset();
    $router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'rq' . $upd, 'from' => $from($uid), 'data' => $data,
        'message' => ['message_id' => $mid, 'chat' => ['id' => $chat, 'type' => 'channel']]]]);
};
$mid = (int) $msgRow['message_id'];
$react(9001, $mid, 'rx:1', $CH);
$ed = $fake->of('editMessageReplyMarkup')[0] ?? [];
T::check('reaksiya bosildi: 🔥 1, javob emoji', strpos($mk($ed), '🔥 1') !== false && ($fake->of('answerCallbackQuery')[0]['text'] ?? '') === '🔥');
$react(9002, $mid, 'rx:1', $CH);
T::check('ikkinchi odam: 🔥 2', strpos($mk($fake->of('editMessageReplyMarkup')[0] ?? []), '🔥 2') !== false);
$react(9001, $mid, 'rx:1', $CH);
T::check('qayta bosish: olib tashlanadi (🔥 1)', strpos($mk($fake->of('editMessageReplyMarkup')[0] ?? []), '🔥 1') !== false);
$react(9002, $mid, 'rx:0', $CH);
$ed = $mk($fake->of('editMessageReplyMarkup')[0] ?? []);
T::check('boshqasiga almashtirish: ❤️ 1, 🔥 sonsiz', strpos($ed, '❤️ 1') !== false && strpos($ed, '"🔥"') !== false);
$react(9001, 999999, 'rx:0', $CH);
T::check('noma\'lum xabar: faqat javob, tahrir yo\'q', count($fake->of('editMessageReplyMarkup')) === 0 && count($fake->of('answerCallbackQuery')) === 1);
$react(9001, $mid, 'rx:5', $CH);
T::eq('mavjud bo\'lmagan reaksiya raqami: tahrir yo\'q', count($fake->of('editMessageReplyMarkup')), 0);
T::eq('ovozlar bazada: 1 ta', (int) $db->value('SELECT COUNT(*) FROM reaction_votes WHERE chat_id = ? AND message_id = ?', [$CH, $mid]), 1);

// --- avto-o'chirish
$draftText('24 soatlik e\'lon');
$press($W, 'p:ad');
$press($W, 'pa:999');
T::check('noto\'g\'ri muddat qabul qilinmaydi', strpos($fake->texts(), 'soatdan keyin') === false);
$press($W, 'p:ad');
$press($W, 'pa:1440');
T::check('preview: 24 soatdan keyin o\'chadi', strpos($fake->texts(), '24 soatdan keyin') !== false);
$press($W, 'p:now');
$msgRow = $db->one('SELECT * FROM sent_messages ORDER BY id DESC LIMIT 1');
T::eq('o\'chirish vaqti: +24 soat', $msgRow['delete_at'] ?? null, $clock->modify('+1440 minutes')->format('Y-m-d H:i:s'));
$clock = $clock->modify('+23 hours');
$fake->reset();
$sched->run(5);
T::eq('vaqti kelmaguncha o\'chirilmaydi', count($fake->of('deleteMessage')), 0);
$clock = $clock->modify('+61 minutes');
$fake->reset();
$sched->run(5);
$dm = $fake->of('deleteMessage')[0] ?? [];
T::check('24 soatdan keyin kanaldan o\'chdi', (int) ($dm['chat_id'] ?? 0) === $CH && (int) ($dm['message_id'] ?? 0) === (int) $msgRow['message_id']
    && (int) $db->value('SELECT deleted FROM sent_messages WHERE id = ?', [(int) $msgRow['id']]) === 1);
$fake->reset();
$sched->run(5);
T::eq('ikkinchi marta o\'chirishga urinmaydi', count($fake->of('deleteMessage')), 0);
$draftText('1 soatlik');
$press($W, 'pa:60');
$press($W, 'p:now');
$msgRow = $db->one('SELECT * FROM sent_messages ORDER BY id DESC LIMIT 1');
$clock = $clock->modify('+61 minutes');
$fake->reset();
$fake->forced['deleteMessage'] = [['ok' => false, 'error_code' => 502, 'description' => 'Bad Gateway']];
$sched->run(5);
$mr = $db->one('SELECT * FROM sent_messages WHERE id = ?', [(int) $msgRow['id']]);
T::eq('vaqtinchalik xato: 5 daqiqadan keyin qayta', [(int) $mr['deleted'], (int) $mr['delete_attempts'], $mr['delete_at']], [0, 1, $clock->modify('+5 minutes')->format('Y-m-d H:i:s')]);
$clock = $clock->modify('+6 minutes');
$fake->reset();
$fake->forced['deleteMessage'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: message to delete not found']];
$sched->run(5);
T::eq('xabar allaqachon yo\'q: o\'chirilgan deb belgilanadi', (int) $db->value('SELECT deleted FROM sent_messages WHERE id = ?', [(int) $msgRow['id']]), 1);

// --- albom
$album = static function (int $uid, int $mid, string $group, array $media) use (&$upd, $from): array {
    return ['update_id' => $upd++, 'message' => array_merge(['message_id' => $mid, 'from' => $from($uid), 'chat' => ['id' => $uid, 'type' => 'private'],
        'date' => 0, 'media_group_id' => $group], $media)];
};
$text($W, '/newpost');
$queue = [$album($W, 502, 'G1', ['video' => ['file_id' => 'V2']]), $album($W, 503, 'G1', ['photo' => [['file_id' => 's'], ['file_id' => 'P3']]])];
$sleeps = 0;
$app->sleeper = static function (int $ms) use (&$queue, &$sleeps, $router): void {
    $sleeps++;
    if ($queue) {
        $router->handle(array_shift($queue)); // kutish paytida keyingi qism keldi (parallel so'rov)
    }
};
$fake->reset();
$router->handle($album($W, 501, 'G1', ['photo' => [['file_id' => 'P1']], 'caption' => 'Albom izohi', 'caption_entities' => [['type' => 'bold', 'offset' => 0, 'length' => 5]]]));
$mg = $fake->of('sendMediaGroup');
$media = json_decode((string) ($mg[0]['media'] ?? '[]'), true);
T::check('albom: 3 qism bitta preview bo\'lib yig\'ildi (bir marta)', count($mg) === 1 && count($media) === 3 && $sleeps === 3
    && $media[0]['media'] === 'P1' && $media[1]['type'] === 'video' && $media[2]['media'] === 'P3');
T::eq('albom izohi formatlangan (PRO — nishonsiz)', $media[0]['caption'] ?? null, '<b>Albom</b> izohi');
$st = $app->states->get($W);
T::eq('holat: albom preview', [$st['state'] ?? null, $st['data']['draft']['type'] ?? null, count($st['data']['draft']['media'] ?? [])], ['post_preview', 'album', 3]);
$app->sleeper = static function (int $ms): void {
};
$fake->reset();
$router->handle($album($W, 504, 'G1', ['photo' => [['file_id' => 'LATE']]]));
$mg = $fake->of('sendMediaGroup');
T::check('kechikkan qism (server band edi) yo\'qolmaydi: albomga qo\'shilib, preview yangilanadi', count($mg) === 1
    && count(json_decode((string) $mg[0]['media'], true)) === 4 && count($app->states->get($W)['data']['draft']['media'] ?? []) === 4);
$fake->reset();
$router->handle($album($W, 505, 'G1', ['photo' => [['file_id' => 'LATE']]]));
T::eq('o\'sha fayl qayta kelsa — takrorlanmaydi', count($fake->calls), 0);
$fake->reset();
foreach ([901, 902, 903] as $m) {
    $router->handle($album($W, $m, 'G9', ['photo' => [['file_id' => 'Q' . $m]]]));
}
T::eq('kutilmagan albom (preview paytida): faqat bitta «tushunmadim»', count($fake->of('sendMessage')), 1);
$press($W, 'p:more');
T::check('albomda tugma/reaksiya yo\'q (izoh bilan)', strpos($mk($fake->of('sendMessage')[0] ?? []), 'p:btn') === false && strpos($fake->lastText(), 'Albomga tugma') !== false);
$press($W, 'p:btn');
T::check('albomga tugma so\'ralmaydi', strpos($fake->lastText(), 'Albomga tugma') !== false);
$press($W, 'p:time');
$press($W, 't:tom09');
$ap = $last();
T::eq('albom navbatga: tur va media', [$ap['post_type'], count(json_decode((string) $ap['media'], true))], ['album', 4]);
$text($W, '📅 Rejalashtirilgan');
T::check('ro\'yxatda 🖼 belgisi', strpos($mk($fake->of('sendMessage')[0] ?? []), '🖼') !== false);
$press($W, 'q:v:' . (int) $ap['id']);
T::check('ko\'rishda «album ×4»', strpos($fake->lastText(), 'album ×4') !== false);
$clock = (new DateTimeImmutable($ap['scheduled_time'], new DateTimeZone('UTC')))->modify('+10 seconds');
$fake->reset();
$sched->run(5);
$mg = $fake->of('sendMediaGroup');
$sm = $db->one('SELECT * FROM sent_messages WHERE post_id = ?', [(int) $ap['id']]);
T::check('cron: albom kanalga, 4 xabar ID yozildi', count($mg) === 1 && (int) $mg[0]['chat_id'] === $CH && $sm && count(explode(',', (string) $sm['extra_ids'])) === 3);

// albom: aralash turlar
$text($W, '/newpost');
$queue = [$album($W, 602, 'G2', ['document' => ['file_id' => 'D2']])];
$app->sleeper = static function (int $ms) use (&$queue, $router): void {
    if ($queue) {
        $router->handle(array_shift($queue));
    }
};
$fake->reset();
$router->handle($album($W, 601, 'G2', ['photo' => [['file_id' => 'P1']]]));
T::check('rasm + hujjat: albom bo\'lmaydi, sababi aytiladi', strpos($fake->texts(), 'bitta albomga') !== false && count($fake->of('sendMediaGroup')) === 0
    && ($app->states->get($W)['state'] ?? null) === 'post_content');

// albom: jarayon uzildi -> cron yig'adi
$app->sleeper = static function (int $ms): void {
    throw new RuntimeException('jarayon to\'xtadi');
};
foreach ([701, 702] as $i => $m) {
    try {
        $router->handle($album($W, $m, 'G3', ['photo' => [['file_id' => 'C' . $i]]]));
    } catch (RuntimeException $e) {
    }
}
$app->sleeper = static function (int $ms): void {
};
$fake->reset();
T::eq('10 soniyadan oldin cron albomga tegmaydi', $sched->finishStaleAlbums(), 0);
$clock = $clock->modify('+11 seconds');
T::eq('uzilgan albomni cron yig\'di', $sched->finishStaleAlbums(), 1);
T::check('foydalanuvchiga albom preview\'i', count($fake->of('sendMediaGroup')) === 1 && (int) $fake->of('sendMediaGroup')[0]['chat_id'] === $W);
T::eq('qayta yig\'ilmaydi', $sched->finishStaleAlbums(), 0);
// albom: 10 dan ko'p
$app->states->set($W, 'post_content');
for ($m = 801; $m <= 812; $m++) {
    $app->albums->add($W, 'G4', $m, 'photo', 'F' . $m, '', $app->nowMs());
}
$fake->reset();
PostAssist\Handlers\PostHandler::finishAlbum($app, $W, 'G4');
T::check('12 ta fayl: 10 tasi olinadi va aytiladi', strpos($fake->texts(), 'ko\'pi bilan 10') !== false
    && count(json_decode((string) ($fake->of('sendMediaGroup')[0]['media'] ?? '[]'), true)) === 10);
$app->states->clear($W);
