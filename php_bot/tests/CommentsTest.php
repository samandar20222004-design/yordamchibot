<?php
// 18-bosqich: izohlar (StatsTest.php dan keyin).
declare(strict_types=1);

T::section('AE. Izohlar');
$clock = new DateTimeImmutable('2027-06-01 10:00:00', new DateTimeZone('UTC'));
$CU = 9980;
$CC = -1009980;
$R1 = 8101;
$R2 = 8102;
foreach ([$CU, $R1, $R2] as $u) {
    $text($u, '/start');
}
$fake->chats[$CC] = ['id' => $CC, 'type' => 'channel', 'title' => 'Muhokama kanali'];
$fake->members["{$CC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($CU, $CC, 'Muhokama kanali', null, 0);
$kbC = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$text($CU, '/newpost');
$text($CU, 'Fikringiz qanday?');
$press($CU, 'p:rx');
$press($CU, 'px:0');
$press($CU, 'p:more');
T::check('«Qo\'shimcha»da «💬 Izohlar»', strpos($kbC(), 'p:o_comments') !== false);
$press($CU, 'p:o_comments');
$press($CU, 'p:back');
T::check('preview: izohlar tugmasi', strpos($mk($fake->of('sendMessage')[0] ?? []), 'start=c_0') !== false);
$press($CU, 'p:now');
$cpid = (int) $db->value('SELECT id FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$CU]);
$chanPost = array_values(array_filter($fake->of('sendMessage'), function ($p) use ($CC) { return (int) $p['chat_id'] === $CC; }));
T::check('kanal postida «💬 Izohlar» (bot havolasi)', count($chanPost) === 1 && strpos($mk($chanPost[0]), 'PostAssistrobot?start=c_' . $cpid) !== false
    && strpos($mk($chanPost[0]), 'Izohlar') !== false && strpos($mk($chanPost[0]), 'rx:0') !== false);
$text($R1, '/start c_' . $cpid);
T::check('o\'quvchi: izohlar sahifasi (bo\'sh)', strpos($fake->lastText(), 'Fikringiz qanday') !== false && strpos($fake->lastText(), 'birinchi') !== false
    && strpos($kbC(), 'cm:w:' . $cpid) !== false);
$press($R1, 'cm:w:' . $cpid);
T::eq('izoh kutiladi', $app->states->get($R1)['state'] ?? null, 'cm_write');
$text($R1, 'a');
T::check('qisqa rad', strpos($fake->lastText(), '2–500') !== false);
$text($R1, 'Batafsil: https://spam.uz');
T::check('havola rad', strpos($fake->lastText(), 'havola') !== false);
$text($R1, 'Zo\'r post, <rahmat>!');
$cid1 = (int) $db->value('SELECT id FROM post_comments WHERE post_id = ? ORDER BY id DESC LIMIT 1', [$cpid]);
$toOwner = array_values(array_filter($fake->of('sendMessage'), function ($p) use ($CU) { return (int) $p['chat_id'] === $CU; }));
T::check('izoh qo\'shildi, egasiga xabar (o\'chirish/bloklash)', $cid1 > 0 && count($toOwner) === 1 && strpos((string) $toOwner[0]['text'], '&lt;rahmat&gt;') !== false
    && strpos($mk($toOwner[0]), 'cm:x:' . $cid1) !== false && strpos($mk($toOwner[0]), 'cm:b:' . $cid1) !== false);
$ed = $fake->of('editMessageReplyMarkup');
T::check('kanal tugmasida son yangilandi (1), reaksiya saqlandi', count($ed) === 1 && strpos($mk($ed[0]), 'Izohlar (1)') !== false && strpos($mk($ed[0]), 'rx:0') !== false);
T::check('izohlar ro\'yxatida ko\'rinadi (xavfsiz)', strpos($fake->lastText(), 'post, &lt;rahmat&gt;') !== false);
for ($i = 0; $i < 4; $i++) {
    $press($R1, 'cm:w:' . $cpid);
    $text($R1, 'Yana izoh ' . $i);
}
$press($R1, 'cm:w:' . $cpid);
$text($R1, 'Oltinchi izoh');
T::check('10 daqiqada 5 tadan ortiq emas', strpos($fake->lastText(), 'tez') !== false && $app->comments->count($cpid) === 5);
$press($CU, 'cm:w:' . $cpid);
$text($CU, 'Rahmat! Batafsil: https://sayt.uz');
T::check('egasi havola yoza oladi, ⭐ bilan', $app->comments->count($cpid) === 6 && strpos($fake->lastText(), '⭐') !== false);
// reaksiya ovozi izoh tugmasini o'chirmaydi
$sm4 = $db->one('SELECT * FROM sent_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1', [$CC]);
$fake->reset();
$router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'r' . $upd, 'from' => ['id' => $R2, 'is_bot' => false, 'first_name' => 'X'],
    'data' => 'rx:0', 'message' => ['message_id' => (int) $sm4['message_id'], 'chat' => ['id' => $CC, 'type' => 'channel']]]]);
T::check('reaksiyadan keyin ham «💬 Izohlar (6)»', strpos($mk($fake->of('editMessageReplyMarkup')[0] ?? []), 'Izohlar (6)') !== false);
// moderatsiya
$press($R2, 'cm:x:' . $cid1);
T::check('begona odam o\'chira olmaydi', strpos($fake->lastText(), 'topilmadi') !== false && $app->comments->count($cpid) === 6);
$press($CU, 'cm:x:' . $cid1);
T::check('egasi o\'chirdi, son kamaydi', $app->comments->count($cpid) === 5 && strpos($mk($fake->of('editMessageReplyMarkup')[0] ?? []), 'Izohlar (5)') !== false);
$cid2 = (int) $db->value('SELECT id FROM post_comments WHERE post_id = ? AND user_id = ? AND deleted = 0 ORDER BY id DESC LIMIT 1', [$cpid, $R1]);
$press($CU, 'cm:b:' . $cid2);
T::check('bloklash: hamma izohlari yashirildi', $app->comments->count($cpid) === 1 && $app->comments->isBanned($CU, $R1));
$press($R1, 'cm:w:' . $cpid);
T::check('bloklangan yoza olmaydi', strpos($fake->lastText(), 'cheklagan') !== false && ($app->states->get($R1)['state'] ?? '') !== 'cm_write');
// izohsiz post
$text($CU, '/newpost');
$text($CU, 'Izohsiz post');
$press($CU, 'p:now');
$npid = (int) $db->value('SELECT id FROM scheduled_posts WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$CU]);
T::check('izoh yoqilmagan postda tugma yo\'q', strpos(json_encode($fake->of('sendMessage')), 'start=c_') === false);
$text($R2, '/start c_' . $npid);
T::check('izohsiz post: aniq xabar', strpos($fake->lastText(), 'yoqilmagan') !== false);
$text($R2, '/start c_999999');
T::check('yo\'q post: aniq xabar', strpos($fake->lastText(), 'yoqilmagan') !== false);
