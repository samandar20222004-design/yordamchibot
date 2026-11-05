<?php
// 11-bosqich: raqobatchilardagi foydali funksiyalar — post sozlamalari va «🔒 Obunachilar uchun» (MiniAppMarketTest.php dan keyin).
declare(strict_types=1);

T::section('W. Post sozlamalari va yashirin matn');
$clock = new DateTimeImmutable('2027-03-01 10:00:00', new DateTimeZone('UTC'));
$FU = 9900;
$FC = -1009900;
$text($FU, '/start');
$fake->chats[$FC] = ['id' => $FC, 'type' => 'channel', 'title' => 'Aksiya kanali'];
$fake->members["{$FC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($FU, $FC, 'Aksiya kanali', null, 0);
$kbF = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$alert = static function () use ($fake): array {
    $a = $fake->of('answerCallbackQuery');
    return $a ? end($a) : [];
};
$text($FU, '/newpost');
$text($FU, 'Bahorgi chegirma! Batafsil: https://example.uz/aksiya');
$press($FU, 'p:more');
T::check('«Qo\'shimcha»: sozlamalar va yashirin matn tugmalari', strpos($kbF(), 'p:o_silent') !== false && strpos($kbF(), 'p:o_nopreview') !== false
    && strpos($kbF(), 'p:o_pin') !== false && strpos($kbF(), 'p:o_protect') !== false && strpos($kbF(), 'p:hidden') !== false);
foreach (['silent', 'nopreview', 'pin', 'protect'] as $o) {
    $press($FU, 'p:o_' . $o);
}
T::eq('sozlamalar saqlandi', $app->states->get($FU)['data']['draft']['options'] ?? null, 'silent,nopreview,pin,protect');
T::check('yoqilganlari ✅ bilan', substr_count(json_decode('"' . str_replace('"', '\"', $kbF()) . '"') ?? $kbF(), '✅') >= 4 || substr_count($kbF(), '✅') >= 4);
$press($FU, 'p:o_pin');
T::eq('qayta bosish o\'chiradi', $app->states->get($FU)['data']['draft']['options'] ?? null, 'silent,nopreview,protect');
$press($FU, 'p:o_pin');
$press($FU, 'p:hidden');
T::eq('yashirin matn so\'raladi', $app->states->get($FU)['state'] ?? null, 'post_hidden');
$text($FU, str_repeat('a', 181));
T::check('uzun yashirin matn rad', strpos($fake->lastText(), '180') !== false && ($app->states->get($FU)['state'] ?? '') === 'post_hidden');
$text($FU, 'Promo-kod: BAHOR27 (−30%)');
$prev = $fake->of('sendMessage')[0] ?? [];
T::check('preview: «🔒 Obunachilar uchun» tugmasi', strpos($mk($prev), '"callback_data":"hd"') !== false && strpos($fake->texts(), 'Yashirin matn: Promo-kod') !== false);
T::check('preview ham sozlamalar bilan (ovozsiz, himoya, havola ko\'rinishisiz)', !empty($prev['disable_notification']) && !empty($prev['protect_content']) && isset($prev['link_preview_options']));
$press($FU, 'hd');
T::check('preview\'da egasi yashirin matnni ko\'radi', in_array($alert()['show_alert'] ?? '', [true, 'true'], true) && strpos((string) ($alert()['text'] ?? ''), 'BAHOR27') !== false);
$press($FU, 'p:now');
$out = array_values(array_filter($fake->of('sendMessage'), function ($p) use ($FC) { return (int) $p['chat_id'] === $FC; }));
T::check('kanalga: ovozsiz, himoyali, havola ko\'rinishisiz, yashirin tugma bilan', count($out) === 1 && !empty($out[0]['disable_notification']) && !empty($out[0]['protect_content'])
    && strpos(json_encode($out[0]['link_preview_options'] ?? ''), 'is_disabled') !== false && strpos($mk($out[0]), '"callback_data":"hd"') !== false);
$pins = $fake->of('pinChatMessage');
T::check('📌 post kanalda pin qilindi (ovozsiz)', count($pins) === 1 && (int) $pins[0]['chat_id'] === $FC && !empty($pins[0]['disable_notification']));
$sm = $db->one('SELECT * FROM sent_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1', [$FC]);
T::check('yuborilgan xabarda yashirin matn saqlandi', $sm !== null && strpos((string) $sm['hidden_text'], 'BAHOR27') !== false);

// kanalda bosish
$chPress = static function (int $uid, int $mid) use (&$upd, $router, $fake, $FC) {
    $fake->reset();
    $router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'h' . $upd, 'from' => ['id' => $uid, 'is_bot' => false, 'first_name' => 'X', 'language_code' => 'uz'],
        'data' => 'hd', 'message' => ['message_id' => $mid, 'chat' => ['id' => $FC, 'type' => 'channel'], 'text' => 'post']]]);
};
$MID = (int) $sm['message_id'];
$fake->members["{$FC}|7001"] = ['status' => 'member'];
$chPress(7001, $MID);
T::check('obunachi: yashirin matn ko\'rinadi', in_array($alert()['show_alert'] ?? '', [true, 'true'], true) && strpos((string) $alert()['text'], 'BAHOR27') !== false);
$fake->members["{$FC}|7002"] = ['status' => 'left'];
$chPress(7002, $MID);
T::check('obuna bo\'lmagan: «avval obuna bo\'ling», matn yo\'q', strpos((string) $alert()['text'], 'obuna bo\'ling') !== false && strpos((string) $alert()['text'], 'BAHOR27') === false);
$chPress(7003, $MID); // getChatMember xato
T::check('tekshirib bo\'lmasa — matn ko\'rsatilmaydi', strpos((string) $alert()['text'], 'BAHOR27') === false);
$fake->members["{$FC}|7004"] = ['status' => 'restricted', 'is_member' => true];
$chPress(7004, $MID);
T::check('cheklangan, lekin a\'zo — ko\'radi', strpos((string) $alert()['text'], 'BAHOR27') !== false);
$chPress(7001, 999999);
T::check('boshqa xabar — jim javob', ($alert()['text'] ?? '') === '' && in_array($alert()['show_alert'] ?? false, [false, 'false'], true));

// reaksiya bosilganda yashirin tugma yo'qolmaydi
$text($FU, '/newpost');
$text($FU, 'Sizga qaysi biri yoqadi?');
$press($FU, 'p:rx');
$press($FU, 'px:0');
$press($FU, 'p:hidden');
$text($FU, 'Javob: ikkinchisi');
$press($FU, 'p:now');
$sm2 = $db->one('SELECT * FROM sent_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1', [$FC]);
$fake->reset();
$router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'r' . $upd, 'from' => ['id' => 7001, 'is_bot' => false, 'first_name' => 'X'],
    'data' => 'rx:0', 'message' => ['message_id' => (int) $sm2['message_id'], 'chat' => ['id' => $FC, 'type' => 'channel']]]]);
$ed = $fake->of('editMessageReplyMarkup');
T::check('reaksiya ovozidan keyin ham «🔒» tugmasi qoladi', count($ed) === 1 && strpos($mk($ed[0]), '"callback_data":"hd"') !== false && strpos($mk($ed[0]), 'rx:0') !== false);
T::eq('optionsString: noma\'lum qiymatlar tashlanadi', \PostAssist\Services\PostRender::optionsString('pin,hack,silent'), 'silent,pin');

T::section('X. Yuborilgan postni tahrirlash va o\'chirish');
$smA = (int) $sm['id'];
$text($FU, '/sent');
T::check('/sent: ro\'yxatda yuborilgan postlar', strpos($kbF(), 's:v:' . $smA) !== false && strpos($kbF(), 's:v:' . (int) $sm2['id']) !== false);
$text($FU, '/queue');
T::check('navbat ekranida «📤 Yuborilganlar»', strpos($kbF(), 's:list') !== false);
$press($FU, 's:v:' . $smA);
T::check('post ko\'rinishi: kanal, matn, tahrir/o\'chirish tugmalari', strpos($fake->lastText(), 'Aksiya kanali') !== false && strpos($fake->lastText(), 'Bahorgi chegirma') !== false
    && strpos($kbF(), 's:e:' . $smA) !== false && strpos($kbF(), 's:d:' . $smA) !== false);
$press($ADMIN, 's:v:' . $smA);
T::check('begona odam ko\'ra olmaydi (IDOR)', strpos($fake->lastText(), 'topilmadi') !== false);
$press($FU, 's:e:' . $smA);
T::eq('tahrir: yangi matn kutiladi', $app->states->get($FU)['state'] ?? null, 'sent_edit');
$send($FU, ['photo' => [['file_id' => 'PH', 'width' => 1, 'height' => 1]]]);
T::check('rasm yuborilsa — faqat matn', strpos($fake->lastText(), 'Faqat matn') !== false);
$send($FU, ['text' => 'Yangilangan aksiya: -40%', 'entities' => [['type' => 'bold', 'offset' => 0, 'length' => 11]]]);
$ed = $fake->of('editMessageText');
T::check('kanaldagi xabar tahrirlandi: formatlash, nishon (bepul), tugmalar saqlandi', count($ed) === 1 && (int) $ed[0]['chat_id'] === $FC && (int) $ed[0]['message_id'] === $MID
    && strpos((string) $ed[0]['text'], '<b>Yangilangan</b>') !== false && strpos((string) $ed[0]['text'], '@PostAssistrobot') !== false
    && strpos($mk($ed[0]), '"callback_data":"hd"') !== false);
T::check('tahrir natijasi aytildi va belgi qo\'yildi', strpos($fake->lastText(), 'yangilandi') !== false && $app->states->get($FU) === null
    && strpos((string) $db->value('SELECT edited_text FROM sent_messages WHERE id = ?', [$smA]), 'Yangilangan') !== false);
$press($FU, 's:e:' . $smA);
$fake->forced['editMessageText'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: message to edit not found']];
$text($FU, 'Yana bir tahrir');
T::check('Telegram rad etsa: sabab aytiladi, holat saqlanadi', strpos($fake->lastText(), 'Tahrirlab bo\'lmadi') !== false && ($app->states->get($FU)['state'] ?? '') === 'sent_edit');
$fake->forced['editMessageText'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: message is not modified']];
$text($FU, 'Yana bir tahrir');
T::check('«not modified» — xato emas', strpos($fake->lastText(), 'yangilandi') !== false);
$press($FU, 's:d:' . $smA);
T::check('o\'chirish: tasdiq so\'raladi', strpos($kbF(), 's:dok:' . $smA) !== false && count($fake->of('deleteMessage')) === 0);
$press($ADMIN, 's:dok:' . $smA);
T::eq('begona odam o\'chira olmaydi', count($fake->of('deleteMessage')), 0);
$press($FU, 's:dok:' . $smA);
$dm = $fake->of('deleteMessage');
T::check('kanaldan o\'chirildi va ro\'yxatdan chiqdi', count($dm) === 1 && (int) $dm[0]['message_id'] === $MID
    && (int) $db->value('SELECT deleted FROM sent_messages WHERE id = ?', [$smA]) === 1);
$text($FU, '/sent');
T::check('o\'chirilgan post ro\'yxatda yo\'q', strpos($kbF(), 's:v:' . $smA) === false);

T::section('Y. Bir nechta kanalga birdan');
$FC2 = -1009902;
$FC3 = -1009903;
foreach ([$FC2 => 'Ikkinchi kanal', $FC3 => 'Uchinchi kanal'] as $cid => $ttl) {
    $fake->chats[$cid] = ['id' => $cid, 'type' => 'channel', 'title' => $ttl];
    $fake->members["{$cid}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
    $app->channels->connect($FU, $cid, $ttl, null, 0);
}
$R1 = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$FC]);
$R2 = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$FC2]);
$R3 = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$FC3]);
$ROTHER = (int) $db->value('SELECT id FROM channels WHERE user_id <> ? AND is_active = 1 LIMIT 1', [$FU]);
$text($FU, '/newpost');
$text($FU, 'Hamma kanallarga e\'lon');
$press($FU, 'p:ch:' . $R1);
$press($FU, 'p:more');
T::check('«Qo\'shimcha»da «📢 Yana kanallar»', strpos($kbF(), 'p:mc') !== false);
$press($FU, 'p:mc');
T::check('boshqa kanallar ro\'yxati (asosiysiz)', strpos($kbF(), 'pm:' . $R2) !== false && strpos($kbF(), 'pm:' . $R3) !== false && strpos($kbF(), 'pm:' . $R1) === false);
$press($FU, 'pm:' . $R2);
$press($FU, 'pm:' . $ROTHER);
T::eq('faqat o\'z kanali qo\'shiladi (IDOR)', $app->states->get($FU)['data']['extra'] ?? null, [$R2]);
$press($FU, 'p:more');
T::check('tanlangan soni ko\'rinadi (+1)', strpos($kbF(), '(+1)') !== false && strpos($fake->lastText(), 'Ikkinchi kanal') !== false);
$fake->reset();
$press($FU, 'p:now');
$byChat = static function (int $cid) use ($fake): int {
    return count(array_filter($fake->of('sendMessage'), function ($p) use ($cid) { return (int) $p['chat_id'] === $cid; }));
};
T::check('ikkala kanalga chiqdi, natija har kanal bo\'yicha', $byChat($FC) === 1 && $byChat($FC2) === 1 && $byChat($FC3) === 0
    && strpos($fake->lastText(), '✅ Aksiya kanali') !== false && strpos($fake->lastText(), '✅ Ikkinchi kanal') !== false);
// biri xato bersa
$text($FU, '/newpost');
$text($FU, 'Ikkinchi e\'lon');
$press($FU, 'p:ch:' . $R1);
$press($FU, 'p:mc');
$press($FU, 'pm:' . $R3);
$fake->reset();
$fake->forced['sendMessage'] = [['ok' => true, 'result' => ['message_id' => 5501]], ['ok' => false, 'error_code' => 403, 'description' => 'Forbidden: bot is not a member']];
$press($FU, 'p:now');
T::check('bir kanal xato: qolgani chiqadi, sabab aytiladi', strpos($fake->lastText(), '✅ Aksiya kanali') !== false && strpos($fake->lastText(), '❌ Uchinchi kanal') !== false);
// rejalashtirish ham hamma kanalga, navbat limiti umumiy
$db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE user_id = ? AND status = 'pending'", [$FU]);
$text($FU, '/newpost');
$text($FU, 'Ertangi e\'lon');
$press($FU, 'p:ch:' . $R1);
$press($FU, 'p:mc');
$press($FU, 'pm:' . $R2);
$press($FU, 'pm:' . $R3);
$press($FU, 'p:time');
$press($FU, 't:tom09');
T::check('rejalashtirildi: 3 kanal, 3 ta post', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$FU]) === 3
    && strpos($fake->lastText(), 'Uchinchi kanal') !== false);
$text($FU, '/newpost');
$text($FU, 'Yana bitta');
$press($FU, 'p:ch:' . $R1);
$press($FU, 'p:mc');
$press($FU, 'pm:' . $R2);
$press($FU, 'p:time');
$press($FU, 't:tom09');
T::check('navbat limiti (bepul 3) hamma kanal uchun sanaladi', strpos($fake->lastText(), '3') !== false
    && (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status = 'pending'", [$FU]) === 3);
$press($FU, 'm:home');
