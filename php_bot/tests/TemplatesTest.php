<?php
// 16-bosqich: shablonlar (RssTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Services\Plans;

T::section('AB. Shablonlar');
$TU = 9960;
$TC = -1009960;
$text($TU, '/start');
$fake->chats[$TC] = ['id' => $TC, 'type' => 'channel', 'title' => 'Shablon kanali'];
$fake->members["{$TC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($TU, $TC, 'Shablon kanali', null, 0);
$kbT2 = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$text($TU, '/newpost');
T::check('shablon yo\'q: post boshida tugma ko\'rinmaydi', strpos($kbT2(), 'tpl:list') === false);
$send($TU, ['photo' => [['file_id' => 'PHOTO_TPL_1', 'width' => 10, 'height' => 10]], 'caption' => 'Haftalik aksiya', 'caption_entities' => [['type' => 'bold', 'offset' => 0, 'length' => 8]]]);
$press($TU, 'p:more');
$press($TU, 'p:btn');
$text($TU, 'Buyurtma - https://shop.uz');
$press($TU, 'p:more');
$press($TU, 'p:o_silent');
$press($TU, 'p:hidden');
$text($TU, 'Kod: TPL10');
$press($TU, 'p:more');
T::check('«Qo\'shimcha»da «💾 Shablon qilish»', strpos($kbT2(), 'p:tsave') !== false);
$press($TU, 'p:tsave');
T::eq('nom so\'raladi', $app->states->get($TU)['state'] ?? null, 'post_tname');
$text($TU, str_repeat('n', 41));
T::check('uzun nom rad', strpos($fake->lastText(), '40') !== false);
$text($TU, 'Haftalik  aksiya');
$tid = (int) $db->value('SELECT id FROM post_templates WHERE user_id = ?', [$TU]);
T::check('saqlandi va preview qaytdi (post yo\'qolmadi)', $tid > 0 && strpos($fake->texts(), 'Shablon saqlandi') !== false && ($app->states->get($TU)['state'] ?? '') === 'post_preview');
T::eq('nom bo\'shliqlari tozalandi', $db->value('SELECT name FROM post_templates WHERE id = ?', [$tid]), 'Haftalik aksiya');
$press($TU, 'p:cancel');
$text($TU, '/newpost');
T::check('shablon bor: post boshida «📝 Shablonlar»', strpos($kbT2(), 'tpl:list') !== false);
$press($TU, 'tpl:list');
T::check('ro\'yxat: tanlash va o\'chirish', strpos($kbT2(), 'tpl:u:' . $tid) !== false && strpos($kbT2(), 'tpl:d:' . $tid) !== false);
$press($TU, 'tpl:u:' . $tid);
$st = $app->states->get($TU);
$d = $st['data']['draft'] ?? [];
T::check('shablondan post: rasm, formatlash, tugma, sozlama, yashirin matn tiklandi', ($st['state'] ?? '') === 'post_preview' && $d['type'] === 'photo' && $d['file_id'] === 'PHOTO_TPL_1'
    && strpos((string) $d['text'], '<b>Haftalik</b>') !== false && $d['button_url'] === 'https://shop.uz' && $d['options'] === 'silent' && strpos((string) $d['hidden'], 'TPL10') !== false);
$ph = $fake->of('sendPhoto');
T::check('preview: rasm, tugma, yashirin tugma, ovozsiz', count($ph) === 1 && strpos($mk($ph[0]), 'shop.uz') !== false && strpos($mk($ph[0]), '"callback_data":"hd"') !== false && !empty($ph[0]['disable_notification']));
$press($TU, 'p:now');
T::eq('shablondan kanalga chiqdi', count(array_filter($fake->of('sendPhoto'), function ($p) use ($TC) { return (int) $p['chat_id'] === $TC; })), 1);
T::eq('ishlatilgan soni', (int) $db->value('SELECT used FROM post_templates WHERE id = ?', [$tid]), 1);
$press($ADMIN, 'tpl:u:' . $tid);
T::check('begona shablon ochilmaydi (IDOR)', strpos($fake->lastText(), 'topilmadi') !== false);
$press($ADMIN, 'tpl:dok:' . $tid);
T::eq('begona odam o\'chira olmaydi', (int) $db->value('SELECT COUNT(*) FROM post_templates WHERE id = ?', [$tid]), 1);
// limit (bepul 3)
foreach ([1, 2] as $i) {
    $app->templates->create($TU, 'T' . $i, ['type' => 'text', 'text' => 'x', 'file_id' => null], $clock);
}
$text($TU, '/newpost');
$text($TU, 'Yana bir post');
$press($TU, 'p:tsave');
T::check('bepul: 3 tadan ortiq emas', strpos($fake->lastText(), '3 ta shablon') !== false && ($app->states->get($TU)['state'] ?? '') !== 'post_tname');
T::eq('limitlar: free 3, admin 100', [$app->templateLimit($TU), $app->templateLimit($ADMIN)], [3, 100]);
$press($TU, 'tpl:d:' . $tid);
T::check('o\'chirish: tasdiq', strpos($kbT2(), 'tpl:dok:' . $tid) !== false);
$press($TU, 'tpl:dok:' . $tid);
T::eq('o\'chirildi', (int) $db->value('SELECT COUNT(*) FROM post_templates WHERE id = ?', [$tid]), 0);
$text($TU, '/templates');
T::check('/templates ishlaydi', strpos($fake->lastText(), 'Shablonlar') !== false);
