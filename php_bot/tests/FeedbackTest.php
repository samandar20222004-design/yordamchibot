<?php
// 💬 Fikr-mulohaza: oqim, spam himoyasi, admin javobi, bloklash, Mini App ko'prigi. UxTest muhitidan foydalanadi ($appU, $textU, ...).
declare(strict_types=1);

T::section('💬 Fikr-mulohaza (taklif va xatolar)');

$FU = 7720;
$fbOf = static function () use ($db, $FU): array {
    return $db->all('SELECT * FROM feedback WHERE user_id = ? ORDER BY id', [$FU]);
};
$toAdmin = static function () use ($fake, $ADMIN): array {
    return array_values(array_filter($fake->of('sendMessage', 'sendPhoto'), static function ($p) use ($ADMIN) {
        return (int) $p['chat_id'] === $ADMIN;
    }));
};
$textU($FU, '/start');
$textU($FU, '⚙️ Sozlamalar');
T::check('Sozlamalarda «💬 Taklif / xato» tugmasi', strpos($lastKb(), 'fb:start') !== false);
$pressU($FU, 'set:help');
T::check('Yordam ekranida ham «💬 Taklif / xato»', strpos($lastKb(), 'fb:start') !== false);
$textU($FU, '/feedback');
T::check('/feedback: tur tanlash (xato / taklif / savol)', strpos($lastKb(), 'fb:k:bug') !== false && strpos($lastKb(), 'fb:k:idea') !== false && strpos($lastKb(), 'fb:k:q') !== false);
$pressU($FU, 'fb:k:bug');
T::eq('xato turi tanlandi — matn kutilmoqda', $appU->states->get($FU)['state'] ?? null, 'fb_text');
$textU($FU, 'qisqa');
T::check('juda qisqa matn rad, holat saqlanadi', strpos($fake->lastText(), 'Juda qisqa') !== false && ($appU->states->get($FU)['state'] ?? null) === 'fb_text' && $fbOf() === []);
$textU($FU, str_repeat('a', 2001));
T::check('juda uzun matn rad', strpos($fake->lastText(), 'Juda uzun') !== false && $fbOf() === []);
$textU($FU, 'Post vaqtini tanlasam <b>xato</b> chiqyapti, iltimos tuzating');
$rows = $fbOf();
T::check('murojaat saqlandi va raqami aytildi', count($rows) === 1 && $rows[0]['kind'] === 'bug' && strpos($fake->texts(), '#' . $rows[0]['id']) !== false
    && ($appU->states->get($FU)['state'] ?? null) === null);
$adm = $toAdmin();
T::check('adminga keldi: HTML xavfsiz, javob/hal/blok tugmalari', count($adm) === 1 && strpos($adm[0]['text'], '&lt;b&gt;xato') !== false
    && strpos(json_encode($adm[0]['reply_markup']), 'fb:r:' . $rows[0]['id']) !== false && strpos(json_encode($adm[0]['reply_markup']), 'fb:bl:' . $FU) !== false);
$id1 = (int) $rows[0]['id'];

// spam himoyasi
$pressU($FU, 'fb:k:idea');
$textU($FU, 'Yana bir taklif: qorong\'i mavzu kerak');
T::check('60 soniya ichida ikkinchi xabar rad (kutish vaqti aytiladi)', strpos($fake->lastText(), 'soniyadan keyin') !== false && count($fbOf()) === 1 && $toAdmin() === []);
$clock = $clock->modify('+61 seconds');
$pressU($FU, 'fb:k:bug');
$textU($FU, 'post vaqtini tanlasam   <B>XATO</B> chiqyapti,  iltimos tuzating');
T::check('bir xil matn (harf/bo\'shliq farqi bilan) qayta qabul qilinmaydi', strpos($fake->lastText(), 'allaqachon') !== false && count($fbOf()) === 1);
foreach (['Taklif: shablonlarni papkalarga ajratish', 'Taklif: statistikani PDF qilib yuklash'] as $i => $t) {
    $clock = $clock->modify('+61 seconds');
    $pressU($FU, 'fb:k:idea');
    $textU($FU, $t);
}
T::eq('soatiga 3 ta qabul qilindi', count($fbOf()), 3);
$clock = $clock->modify('+61 seconds');
$pressU($FU, 'fb:k:idea');
$textU($FU, 'To\'rtinchi taklif bir soat ichida');
T::check('soatlik chegara: 4-xabar rad', strpos($fake->lastText(), 'Bir soatda') !== false && count($fbOf()) === 3);
$clock = $clock->modify('+2 hours');

// rasm + izoh
$pressU($FU, 'fb:k:bug');
$sendU($FU, ['photo' => [['file_id' => 'small'], ['file_id' => 'BIGPHOTO']], 'caption' => 'Skrinshot: tugma ishlamayapti']);
$adm = $toAdmin();
T::check('rasm + izoh: saqlandi va adminga rasm ham bordi', count($fbOf()) === 4 && end($fbOf())['file_id'] === 'BIGPHOTO'
    && $adm && $adm[0]['photo'] === 'BIGPHOTO');

// admin: ro'yxat, javob, hal qilindi
$textU($ADMIN, '/feedback');
T::check('admin /feedback: ochiq murojaatlar ro\'yxati', strpos($fake->lastText(), 'Ochiq murojaatlar: 4') !== false && strpos($lastKb(), 'fb:v:' . $id1) !== false);
$pressU($ADMIN, 'a:fb');
T::check('admin panel «💬 Murojaatlar» ham ro\'yxatni ochadi', strpos($fake->lastText(), 'Ochiq murojaatlar') !== false);
$pressU($FU, 'fb:r:' . $id1);
T::check('oddiy foydalanuvchi admin tugmasini bosa olmaydi', ($appU->states->get($FU)['state'] ?? null) === null && $fake->of('sendMessage') === []);
$pressU($ADMIN, 'fb:r:' . $id1);
T::eq('admin javob yozish holatida', $appU->states->get($ADMIN)['state'] ?? null, 'fb_reply');
$textU($ADMIN, 'Rahmat, tuzatdik! <yangilang>');
$toUser = array_values(array_filter($fake->of('sendMessage'), static function ($p) use ($FU) {
    return (int) $p['chat_id'] === $FU;
}));
T::check('javob foydalanuvchiga bordi (HTML xavfsiz), holat answered', $toUser && strpos($toUser[0]['text'], '&lt;yangilang&gt;') !== false
    && strpos($toUser[0]['text'], '#' . $id1) !== false && $appU->feedback->get($id1)['status'] === 'answered');
$pressU($ADMIN, 'fb:ok:' . $id1);
T::check('hal qilindi: foydalanuvchiga xabar, holat done', $appU->feedback->get($id1)['status'] === 'done' && strpos($fake->texts(), 'hal qilindi') !== false);
$pressU($ADMIN, 'fb:ok:' . $id1);
T::check('ikkinchi «hal qilindi» foydalanuvchiga qayta xabar yubormaydi', count(array_filter($fake->of('sendMessage'), static function ($p) use ($FU) {
    return (int) $p['chat_id'] === $FU;
})) === 0);

// bloklash
$pressU($ADMIN, 'fb:bl:' . $FU);
T::check('admin bloklaydi', $appU->feedback->isBlocked($FU));
$clock = $clock->modify('+2 hours');
$pressU($FU, 'fb:start');
T::check('bloklangan foydalanuvchi yozolmaydi', strpos($fake->lastText(), 'cheklangansiz') !== false);
$pressU($FU, 'fb:k:idea');
T::check('bloklanganda tur tanlash ham ishlamaydi', ($appU->states->get($FU)['state'] ?? null) === null);
$pressU($ADMIN, 'fb:ub:' . $FU);
T::check('blokdan chiqarildi', !$appU->feedback->isBlocked($FU));

// Mini App ko'prigi: Profil -> Taklif va xatolar
[$st, $r] = $br(['d' => 'fb:start']);
T::check('Mini App: fikr-mulohaza ekrani, orqaga/menyu tugmalarisiz', $st === 200 && strpos(json_encode($r), 'fb:k:bug') !== false && strpos(json_encode($r), 'm:home') === false);
$br(['d' => 'fb:k:idea']);
[$st, $r] = $br(['t' => 'Mini App\'dan taklif: tugmalarni kattaroq qiling']);
T::check('Mini App: matn yuborildi, raqam qaytdi', strpos(json_encode($r, JSON_UNESCAPED_UNICODE), 'Rahmat') !== false
    && (int) $db->value('SELECT COUNT(*) FROM feedback WHERE user_id = ?', [$B]) === 1);
T::check('app.php: Profilda «Taklif va xatolar»', strpos($appSrcU, 'data-br="fb:start"') !== false);
T::check('bot buyruqlari ro\'yxatida /feedback (3 tilda)', count(array_filter(['uz', 'ru', 'en'], static function ($l) {
    return in_array('feedback', array_column(PostAssist\Services\BotCommands::forLang($l), 'command'), true);
})) === 3);
