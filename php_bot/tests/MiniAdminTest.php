<?php
// 23–24-bosqich: Mini App — izohlar (egasi) va super admin paneli (PollTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;

T::section('AJ. Mini App: izohlar (kanal egasi)');
$ma = static function (int $uid, string $action, array $in = []) use ($app, $fake, $mkInit, &$clock, $token): array {
    $fake->reset();
    return MiniAppApi::handle($app, $action, $in, $mkInit(['id' => $uid, 'first_name' => 'Ega', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token));
};
[$s, $r] = $ma($CU, 'comments');
T::check('egasi o\'z postlaridagi izohlarni ko\'radi', $s === 200 && count($r['comments']) >= 1 && $r['comments'][0]['post'] !== '');
[, $r0] = $ma($R2, 'comments');
T::eq('begona — bo\'sh ro\'yxat', $r0['comments'], []);
$app->comments->add($cpid, $CU, $R2, 'Mehmon', 'Savolim bor', $clock);
$cidM = (int) $db->value('SELECT id FROM post_comments WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$R2]);
T::eq('begona odam o\'chira olmaydi', $ma($R2, 'comment_mod', ['id' => $cidM, 'act' => 'del'])[0], 404);
[$s2] = $ma($CU, 'comment_mod', ['id' => $cidM, 'act' => 'del']);
T::check('egasi o\'chirdi, kanal tugmasi yangilandi', $s2 === 200 && (int) $db->value('SELECT deleted FROM post_comments WHERE id = ?', [$cidM]) === 1
    && count($fake->of('editMessageReplyMarkup')) >= 1);
[$s3] = $ma($CU, 'comment_reply', ['post_id' => $cpid, 'text' => 'Javob: https://sayt.uz da batafsil']);
T::check('egasi javob yozdi (havola mumkin)', $s3 === 200 && strpos((string) $db->value('SELECT text FROM post_comments WHERE post_id = ? ORDER BY id DESC LIMIT 1', [$cpid]), 'sayt.uz') !== false);
T::eq('begona postga javob yozib bo\'lmaydi', $ma($R2, 'comment_reply', ['post_id' => $cpid, 'text' => 'Salom hammaga'])[0], 404);
T::eq('qisqa javob rad', $ma($CU, 'comment_reply', ['post_id' => $cpid, 'text' => 'a'])[1]['error'] ?? null, 'comment_len');
$app->comments->add($cpid, $CU, 8103, 'Spam', 'Spam izoh', $clock);
$cidB = (int) $db->value('SELECT id FROM post_comments WHERE user_id = 8103 ORDER BY id DESC LIMIT 1');
$ma($CU, 'comment_mod', ['id' => $cidB, 'act' => 'ban']);
T::check('bloklash Mini App\'dan', $app->comments->isBanned($CU, 8103));

T::section('AK. Mini App: super admin paneli');
T::eq('oddiy foydalanuvchiga yopiq', $ma($CU, 'admin_stats')[1]['error'] ?? null, 'admin_only');
T::eq('oddiy foydalanuvchi tarif bera olmaydi', $ma($CU, 'admin_grant', ['user_id' => $CU, 'tier' => 'ultra', 'days' => 30])[1]['error'] ?? null, 'admin_only');
[$sa, $ra] = $ma($ADMIN, 'admin_stats');
T::check('statistika: foydalanuvchilar, kanallar, 7 kunlik grafik', $sa === 200 && $ra['users'] > 10 && $ra['channels'] > 0 && count($ra['new_users']) === 7);
[$sg, $rg] = $ma($ADMIN, 'admin_grant', ['user_id' => $R2, 'tier' => 'ultra', 'days' => 7]);
T::check('tarif berildi va foydalanuvchiga xabar', $sg === 200 && $rg['tier'] === 'ultra' && $app->tier($R2) === 'ultra'
    && count(array_filter($fake->of('sendMessage'), function ($p) use ($R2) { return (int) $p['chat_id'] === $R2; })) === 1);
T::eq('noma\'lum foydalanuvchi', $ma($ADMIN, 'admin_grant', ['user_id' => 123, 'tier' => 'pro', 'days' => 7])[1]['error'] ?? null, 'user_unknown');
T::eq('noto\'g\'ri kun', $ma($ADMIN, 'admin_grant', ['user_id' => $R2, 'tier' => 'pro', 'days' => 0])[1]['error'] ?? null, 'bad_grant');
[$su, $ru] = $ma($ADMIN, 'admin_user', ['id' => $R2]);
T::check('foydalanuvchi kartasi', $su === 200 && $ru['user']['tier'] === 'ULTRA' && $ru['user']['market_banned'] === false);
$ma($ADMIN, 'admin_market_ban', ['id' => $R2, 'ban' => true]);
T::eq('birjadan bloklash', $app->market->isBanned($R2), true);
$ma($ADMIN, 'admin_market_ban', ['id' => $R2, 'ban' => false]);
T::eq('blokni olish', $app->market->isBanned($R2), false);
[$sp, $rp] = $ma($ADMIN, 'admin_promo_create', ['code' => 'mini27', 'tier' => 'pro', 'days' => 14, 'max' => '5']);
T::check('promo yaratildi (katta harf)', $sp === 200 && $rp['code'] === 'MINI27');
T::eq('takror kod rad', $ma($ADMIN, 'admin_promo_create', ['code' => 'MINI27', 'tier' => 'pro', 'days' => 14])[1]['error'] ?? null, 'promo_exists');
T::eq('noto\'g\'ri tarif rad', $ma($ADMIN, 'admin_promo_create', ['code' => 'XYZ99', 'tier' => 'enterprise', 'days' => 14])[1]['error'] ?? null, 'promo_bad_plan');
[, $rl] = $ma($ADMIN, 'admin_promos');
$mini = array_values(array_filter($rl['promos'], function ($p) { return $p['code'] === 'MINI27'; }));
T::check('ro\'yxatda: 0/5, faol', count($mini) === 1 && $mini[0]['max'] === 5 && $mini[0]['active'] === true);
$ma($ADMIN, 'admin_promo_toggle', ['code' => 'MINI27', 'active' => false]);
T::eq('o\'chirildi', (int) $db->value("SELECT is_active FROM promo_codes WHERE code = 'MINI27'"), 0);
// chek: yaratish va Mini App'dan tasdiqlash
$plan1 = \PostAssist\Services\Plans::catalog($app->config)['1m'];
$rid = $app->receipts->create($R1, $plan1, 29000, 'photo', 'RCPT1', 'U1', $clock);
[, $rr] = $ma($ADMIN, 'admin_receipts');
T::check('kutilayotgan cheklar ro\'yxati', count(array_filter($rr['receipts'], function ($x) use ($rid) { return $x['id'] === $rid; })) === 1);
[$sd, $rd] = $ma($ADMIN, 'admin_receipt', ['id' => $rid, 'approve' => true]);
T::check('chek tasdiqlandi: tarif va xabar', $sd === 200 && $rd['status'] === 'ok' && $app->tier($R1) === 'pro'
    && count(array_filter($fake->of('sendMessage'), function ($p) use ($R1) { return (int) $p['chat_id'] === $R1; })) === 1);
T::eq('ikkinchi qaror rad', $ma($ADMIN, 'admin_receipt', ['id' => $rid, 'approve' => false])[1]['error'] ?? null, 'receipt_already');
$appSrc5 = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: admin sahifasi va izohlar kartasi', strpos($appSrc5, 'id="p-admin"') !== false && strpos($appSrc5, "api('admin_stats')") !== false
    && strpos($appSrc5, "api('comments')") !== false);
