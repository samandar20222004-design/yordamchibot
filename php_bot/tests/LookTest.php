<?php
// 27-bosqich: premium emoji va rangli tugmalar (CountriesTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\LookHandler;
use PostAssist\Services\Look;

T::section('AN. Bot ko\'rinishi: rangli tugmalar va premium emoji');
T::eq('rang: asosiy / xavfli / yo\'l', [Look::styleFor('p:now'), Look::styleFor('p:cancel'), Look::styleFor('q:dok:5'), Look::styleFor('p:time'), Look::styleFor('rx:0')],
    ['success', 'danger', 'danger', 'primary', null]);
$look = $app->look;
$look->clearMap();
$look->set(Look::KEY_STYLES, '1');
$d = $look->decorate('sendMessage', ['chat_id' => 5, 'text' => '🤖 Salom', 'parse_mode' => 'HTML',
    'reply_markup' => ['inline_keyboard' => [[['text' => '🚀 Yubor', 'callback_data' => 'p:now'], ['text' => 'Sayt', 'url' => 'https://x.uz']]]]]);
T::check('premiumsiz: faqat rang, matn o\'zgarmaydi', $d['text'] === '🤖 Salom' && $d['reply_markup']['inline_keyboard'][0][0]['style'] === 'success'
    && !isset($d['reply_markup']['inline_keyboard'][0][1]['style']) && !isset($d['reply_markup']['inline_keyboard'][0][0]['icon_custom_emoji_id']));
$look->addMap(['🤖' => '5368324170671202286', '✍️' => '5395444784611480792']);
$d = $look->decorate('sendMessage', ['chat_id' => 5, 'text' => "🤖 <b>Salom</b> ✍️ <code>🤖</code>", 'parse_mode' => 'HTML',
    'reply_markup' => ['inline_keyboard' => [[['text' => '✍️ Yozish', 'callback_data' => 'cm:w:1']]], ['keyboard' => []]]]);
T::check('premium: matnda <tg-emoji> (code ichida emas), FE0F farqsiz', substr_count($d['text'], '<tg-emoji') === 2 && strpos($d['text'], '<code>🤖</code>') !== false
    && strpos($d['text'], 'emoji-id="5395444784611480792">✍️</tg-emoji>') !== false);
$b = $d['reply_markup']['inline_keyboard'][0][0];
T::check('premium: tugmada jonli belgi, matndan oddiy emoji olinadi', $b['icon_custom_emoji_id'] === '5395444784611480792' && $b['text'] === 'Yozish' && $b['style'] === 'success');
$dc = $look->decorate('sendMessage', ['chat_id' => -1001, 'text' => '🤖 Kanal', 'parse_mode' => 'HTML']);
T::eq('kanalda premium qo\'llanmaydi', $dc['text'], '🤖 Kanal');
$dr = $look->decorate('sendMessage', ['chat_id' => 5, 'text' => '🤖 Post matni', 'parse_mode' => 'HTML', '_raw' => true]);
T::check('post (_raw): matn o\'zgarmaydi, belgi olinadi', $dr['text'] === '🤖 Post matni' && !isset($dr['_raw']));
T::eq('custom emoji ajratish (UTF-16)', LookHandler::extract(['text' => "a🤖✍️", 'entities' => [['type' => 'custom_emoji', 'offset' => 1, 'length' => 2, 'custom_emoji_id' => '111111'],
    ['type' => 'custom_emoji', 'offset' => 3, 'length' => 2, 'custom_emoji_id' => '222222']]]), ['🤖' => '111111', '✍️' => '222222']);
T::eq('custom emoji stikeri', LookHandler::extract(['sticker' => ['emoji' => '🔥', 'custom_emoji_id' => '333333']]), ['🔥' => '333333']);

// admin oqimi
$look->clearMap();
$text($U2, '/emoji');
T::check('oddiy foydalanuvchiga /emoji yo\'q', ($app->states->get($U2)['state'] ?? '') !== 'emoji_wait');
$text($ADMIN, '/emoji');
T::check('admin: ko\'rinish ekrani va kutish', ($app->states->get($ADMIN)['state'] ?? '') === 'emoji_wait' && strpos($fake->lastText(), 'Bot ko') !== false);
$send($ADMIN, ['text' => 'oddiy 🤖']);
T::check('oddiy emoji — tushuntirish', strpos($fake->lastText(), 'topilmadi') !== false);
$send($ADMIN, ['text' => '🤖✍️📢', 'entities' => [['type' => 'custom_emoji', 'offset' => 0, 'length' => 2, 'custom_emoji_id' => '5368324170671202286'],
    ['type' => 'custom_emoji', 'offset' => 2, 'length' => 2, 'custom_emoji_id' => '5395444784611480792'], ['type' => 'custom_emoji', 'offset' => 4, 'length' => 2, 'custom_emoji_id' => '5424818078833715060']]]);
T::check('3 ta belgi saqlandi', count($look->map()) === 3 && $look->premiumOn() && strpos($fake->texts(), '3 ta belgi saqlandi') !== false);
// foydalanuvchi bosh menyusi: belgili tugmalar va belgisiz matn ham ishlaydi
$PE = 9996;
$text($PE, '/start');
$mm = $fake->of('sendMessage');
$kbS = json_encode(json_decode((string) (end($mm)['reply_markup'] ?? '{}'), true), JSON_UNESCAPED_UNICODE);
T::check('bosh menyu tugmasida premium belgi (✍️ Post yaratish)', strpos($kbS, '5395444784611480792') !== false && strpos($kbS, '"text":"Post yaratish"') !== false);
$text($PE, 'Post yaratish');
T::check('belgisiz tugma matni ham menyu sifatida taniladi', ($app->states->get($PE)['state'] ?? '') === 'post_content' || strpos($fake->lastText(), 'kanal') !== false);
// Telegram rad etsa: oddiy holda qayta yuboriladi va premium o'chadi
$fake->reset();
$fake->forced['sendMessage'] = [['ok' => false, 'error_code' => 400, 'description' => "Bad Request: can't use custom emoji"], ['ok' => true, 'result' => ['message_id' => 1]]];
$r = $app->tg->sendMessage($PE, '🤖 Sinov', ['inline_keyboard' => [[['text' => '✍️ Yozish', 'callback_data' => 'x']]]]);
$sm = $fake->of('sendMessage');
T::check('rad etilsa: ikkinchi urinish premiumsiz, xabar yetdi', !empty($r['ok']) && count($sm) === 2 && strpos((string) $sm[0]['text'], 'tg-emoji') !== false
    && strpos((string) $sm[1]['text'], 'tg-emoji') === false && strpos((string) $sm[1]['reply_markup'], 'icon_custom_emoji_id') === false);
T::eq('premium avtomatik o\'chdi', $look->premiumOn(), false);
$fake->reset();
$fake->forced['sendMessage'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: chat not found'], ['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: chat not found']];
$look->set(Look::KEY_ON, '1');
$app->tg->sendMessage($PE, '🤖 Sinov');
T::eq('boshqa xato (chat yo\'q): qatlam o\'chirilmaydi', $look->premiumOn(), true);
$press($ADMIN, 'emj:st');
T::eq('admin: ranglarni o\'chirish', $look->stylesOn(), false);
$press($ADMIN, 'emj:st');
$press($ADMIN, 'emj:clr');
T::eq('admin: belgilarni tozalash', $look->map(), []);
$text($ADMIN, '/admin');
T::check('admin panelda «✨ Bot ko\'rinishi»', strpos(json_encode($fake->of('sendMessage'), JSON_UNESCAPED_UNICODE), 'a:look') !== false);
$app->states->clear($ADMIN);
