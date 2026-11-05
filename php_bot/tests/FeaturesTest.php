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
