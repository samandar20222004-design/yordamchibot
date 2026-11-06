<?php
// 📱 Mini App testi (IntegrationTest.php -> Phase4Test.php dan keyin; o'sha o'zgaruvchilar).
declare(strict_types=1);

use PostAssist\App;
use PostAssist\Config;
use PostAssist\I18n;
use PostAssist\Handlers\MiniAppApi;
use PostAssist\Keyboards;
use PostAssist\Services\Ai;
use PostAssist\Telegram;

T::section('O. Mini App: imzo, API, xavfsizlik, bot bilan bog\'lanish');
$token = $config->str('bot_token');
$mkInit = static function (array $user, int $authDate, string $tok) {
    $pairs = ['auth_date' => (string) $authDate, 'query_id' => 'AAH', 'user' => json_encode($user, JSON_UNESCAPED_UNICODE)];
    ksort($pairs);
    $lines = [];
    foreach ($pairs as $k => $v) {
        $lines[] = $k . '=' . $v;
    }
    $pairs['hash'] = hash_hmac('sha256', implode("\n", $lines), hash_hmac('sha256', $tok, 'WebAppData', true));
    return http_build_query($pairs);
};
$W = $U2;
$wUser = ['id' => $W, 'first_name' => 'Vali', 'username' => 'ali' . $W, 'language_code' => 'uz'];
$init = $mkInit($wUser, $clock->getTimestamp() - 60, $token);
$call = static function (string $action, array $in = [], ?string $init2 = null, ?array $file = null) use ($app, &$init, $fake): array {
    $fake->reset();
    return MiniAppApi::handle($app, $action, $in, $init2 ?? $init, $file);
};

// imzo
T::eq('imzosiz so\'rov rad (401)', $call('me', [], '')[0], 401);
T::eq('soxta imzo rad', $call('me', [], str_replace('hash=', 'hash=0', $init))[0], 401);
T::eq('boshqa bot tokeni bilan imzo rad', $call('me', [], $mkInit($wUser, $clock->getTimestamp(), '999:' . str_repeat('B', 35)))[0], 401);
T::eq('foydalanuvchi ma\'lumoti almashtirilsa rad', $call('me', [], str_replace(urlencode('"id":' . $W), urlencode('"id":' . $ADMIN), $init))[0], 401);
T::eq('eskirgan imzo (25 soat) rad', $call('me', [], $mkInit($wUser, $clock->getTimestamp() - 90000, $token))[0], 401);
T::check('to\'g\'ri imzo: verify foydalanuvchini qaytaradi', (MiniAppApi::verify($init, $token, $clock->getTimestamp())['id'] ?? 0) === $W);
[$st, $me] = $call('me');
T::check('me: tarif, kanallar, mintaqa, AI holati', $st === 200 && $me['ok'] && $me['plan']['tier'] === 'pro' && count($me['channels']) === 1
    && $me['user']['timezone'] === 'Europe/Moscow' && $me['ai']['enabled'] === false && $me['bot'] === 'PostAssistrobot');
$chId = (int) $me['channels'][0]['id'];
T::eq('noma\'lum amal: 404', $call('hack')[0], 404);

// post yaratish: hozir
[$st, $r] = $call('post_create', ['channel_id' => $chId, 'text' => '<b>Mini App</b> posti <script>x</script>', 'button_text' => 'Batafsil',
    'button_url' => 'sayt.uz', 'reactions' => '👍 🔥', 'when' => 'now']);
$sent = $fake->of('sendMessage')[0] ?? [];
T::check('hozir yuborish: kanalga ketdi, HTML tozalangan, tugma va reaksiya bilan', $st === 200 && ($r['status'] ?? '') === 'sent'
    && (int) ($sent['chat_id'] ?? 0) === $CH && strpos((string) $sent['text'], '<b>Mini App</b> posti') === 0 && strpos((string) $sent['text'], '<script>') === false
    && strpos($mk($sent), 'https:\/\/sayt.uz') !== false && strpos($mk($sent), 'rx:1') !== false, json_encode($r));
// rejalash
[$st, $r] = $call('post_create', ['channel_id' => $chId, 'text' => 'Ertangi post', 'when' => $clock->modify('+1 day')->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d') . 'T09:00']);
$pid = (int) ($r['id'] ?? 0);
T::check('vaqtga rejalash: foydalanuvchi mintaqasida (Moskva 09:00 = 06:00 UTC)', $st === 200 && ($r['status'] ?? '') === 'scheduled'
    && substr((string) $db->value('SELECT scheduled_time FROM scheduled_posts WHERE id = ?', [$pid]), 11) === '06:00:00');
[$st, $r] = $call('post_create', ['channel_id' => $chId, 'text' => 'Har kuni', 'repeat' => 'twice', 'time2' => '18:30',
    'when' => $clock->modify('+2 days')->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d') . 'T09:00', 'delete_after' => 1440]);
$tw = $db->one('SELECT * FROM scheduled_posts WHERE id = ?', [(int) ($r['id'] ?? 0)]);
T::check('takror (kuniga 2 marta) va avto-o\'chirish saqlanadi', ($tw['recurrence_type'] ?? '') === 'twice' && (int) $tw['recurrence_day'] === 1110 && (int) $tw['delete_after'] === 1440);
// tekshiruvlar
$bad = static function (array $in) use ($call, $chId): string {
    [$st, $r] = $call('post_create', $in + ['channel_id' => $chId, 'text' => 'Matn', 'when' => 'now']);
    return $st . ':' . ($r['error'] ?? '');
};
$foreign = (int) $app->channels->listFor($ADMIN)[0]['id'];
T::eq('begona kanal (IDOR)', $bad(['channel_id' => $foreign]), '400:channel');
T::eq('bo\'sh matn', $bad(['text' => '<b></b>']), '400:empty');
T::eq('juda uzun matn', $bad(['text' => str_repeat('a', 4100)]), '400:too_long');
T::eq('rasm izohi 1024 dan oshsa', $bad(['type' => 'photo', 'file_id' => 'AgACAgIAAxkBAAIB', 'text' => str_repeat('a', 1100)]), '400:too_long');
T::eq('noto\'g\'ri tugma havolasi', $bad(['button_text' => 'X', 'button_url' => 'javascript:alert(1)']), '400:button');
T::eq('o\'tgan vaqt', $bad(['when' => '2020-01-01T10:00']), '400:past');
T::eq('noto\'g\'ri vaqt formati', $bad(['when' => '31.12 10:00']), '400:bad_time');
T::eq('noto\'g\'ri reaksiya', $bad(['reactions' => 'salom']), '400:reactions');
T::eq('noto\'g\'ri avto-o\'chirish', $bad(['delete_after' => 7]), '400:delete_after');
T::eq('noto\'g\'ri media file_id', $bad(['type' => 'photo', 'file_id' => '../x']), '400:file');
T::eq('takror: ikki vaqt bir xil', $bad(['repeat' => 'twice', 'time2' => '09:00', 'when' => $clock->modify('+1 day')->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d') . 'T09:00']), '400:repeat');
// ro'yxat, tahrir, bekor
[$st, $r] = $call('posts');
T::check('posts: navbat ro\'yxati, takror belgisi', $st === 200 && count($r['posts']) >= 2 && in_array('Kuniga 2 marta: 09:00 va 18:30', array_column($r['posts'], 'repeat'), true));
[$st, $r] = $call('post_update', ['id' => $pid, 'text' => '<i>Tahrirlandi</i>', 'when' => $clock->modify('+3 days')->setTimezone(new DateTimeZone('Europe/Moscow'))->format('Y-m-d') . 'T12:30']);
T::check('tahrir: matn va vaqt', $st === 200 && $db->value('SELECT text FROM scheduled_posts WHERE id = ?', [$pid]) === '<i>Tahrirlandi</i>'
    && substr((string) $db->value('SELECT scheduled_time FROM scheduled_posts WHERE id = ?', [$pid]), 11) === '09:30:00');
$adminInit = $mkInit(['id' => $ADMIN, 'first_name' => 'Admin'], $clock->getTimestamp(), $token);
T::eq('begona postni tahrirlab bo\'lmaydi (IDOR)', $call('post_update', ['id' => $pid, 'text' => 'buzildi'], $adminInit)[0], 404);
T::eq('begona postni bekor qilib bo\'lmaydi', $call('post_cancel', ['id' => $pid], $adminInit)[0], 404);
T::eq('post bekor qilindi', [$call('post_cancel', ['id' => $pid])[0], $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$pid])], [200, 'cancelled']);
// sozlamalar
T::eq('til va mintaqa', [$call('settings', ['lang' => 'ru'])[0], $call('settings', ['timezone' => 'Asia/Tashkent'])[0],
    $app->users->get($W)['lang'], $app->users->get($W)['timezone']], [200, 200, 'ru', 'Asia/Tashkent']);
T::eq('noto\'g\'ri til / mintaqa', [$call('settings', ['lang' => 'de'])[1]['error'] ?? '', $call('settings', ['timezone' => 'Mars/X'])[1]['error'] ?? ''], ['lang', 'timezone']);
$call('settings', ['lang' => 'uz', 'timezone' => 'Europe/Moscow']);
// qoralama (botdan davom ettirish)
$app->states->set($W, 'post_preview', ['draft' => ['type' => 'text', 'file_id' => null, 'text' => '<b>Bot qoralamasi</b>', 'button_text' => 'A', 'button_url' => 'https://a.uz'], 'channel' => $chId]);
[$st, $r] = $call('draft');
T::check('botdagi qoralama Mini App\'da ochiladi', $st === 200 && ($r['draft']['text'] ?? '') === '<b>Bot qoralamasi</b>' && ($r['draft']['channel_id'] ?? 0) === $chId);
$app->states->clear($W);
T::eq('qoralama yo\'q bo\'lsa null', $call('draft')[1]['draft'], null);
// yuklash
$tmp = tempnam(sys_get_temp_dir(), 'pa');
file_put_contents($tmp, "\xFF\xD8\xFF\xE0" . str_repeat("\0", 100));
$fake->forced['sendPhoto'] = [['ok' => true, 'result' => ['message_id' => 555, 'photo' => [['file_id' => 'small'], ['file_id' => 'AgACBIGPHOTO123']]]]];
[$st, $r] = MiniAppApi::handle($app, 'upload', [], $init, ['error' => UPLOAD_ERR_OK, 'tmp_name' => $tmp, 'size' => 104]);
T::check('rasm yuklash: file_id olinadi, yordamchi xabar o\'chiriladi', $st === 200 && ($r['file_id'] ?? '') === 'AgACBIGPHOTO123'
    && count($fake->of('deleteMessage')) === 1);
file_put_contents($tmp, '<?php echo 1;');
T::eq('PHP fayl rasm sifatida yuklanmaydi', MiniAppApi::handle($app, 'upload', [], $init, ['error' => UPLOAD_ERR_OK, 'tmp_name' => $tmp, 'size' => 13])[1]['error'] ?? '', 'file_type');
T::eq('juda katta fayl', MiniAppApi::handle($app, 'upload', [], $init, ['error' => UPLOAD_ERR_OK, 'tmp_name' => $tmp, 'size' => 20000000])[1]['error'] ?? '', 'too_big');
T::eq('fayl yo\'q', MiniAppApi::handle($app, 'upload', [], $init, null)[1]['error'] ?? '', 'upload');
@unlink($tmp);
T::eq('mp4 aniqlanadi', MiniAppApi::sniff((static function () {
    $f = tempnam(sys_get_temp_dir(), 'v');
    file_put_contents($f, "\0\0\0\x18ftypmp42" . str_repeat("\0", 20));
    return $f;
})()), 'video/mp4');
[$st, $r] = $call('post_create', ['channel_id' => $chId, 'type' => 'photo', 'file_id' => 'AgACBIGPHOTO123', 'text' => 'Rasmli', 'when' => 'now']);
T::check('yuklangan rasm bilan post', ($r['status'] ?? '') === 'sent' && ($fake->of('sendPhoto')[0]['photo'] ?? '') === 'AgACBIGPHOTO123');
// AI
T::eq('AI o\'chiq', $call('ai', ['mode' => 'post', 'topic' => 'Mavzu', 'style' => 'news'])[1]['error'] ?? '', 'ai_disabled');
$aiQueue = [[200, json_encode(['candidates' => [['content' => ['parts' => [['text' => '**AI** posti']]]]]])]];
$app->ai = new Ai(new Config(['gemini_api_key' => 'K']), $aiT);
[$st, $r] = $call('ai', ['mode' => 'post', 'topic' => 'Yangi kurs', 'style' => 'sales']);
T::eq('AI post', [$st, $r['text'] ?? ''], [200, '<b>AI</b> posti']);
$aiQueue = [[200, json_encode(['candidates' => [['content' => ['parts' => [['text' => 'Short']]]]]])]];
T::eq('AI tahrir (tarjima)', $call('ai', ['mode' => 'edit', 'text' => 'Qisqa matn', 'action' => 'tr_en'])[1]['text'] ?? '', 'Short');
T::eq('AI: noto\'g\'ri uslub / bo\'sh matn', [$call('ai', ['mode' => 'post', 'topic' => 'Mavzu', 'style' => 'x'])[1]['error'] ?? '',
    $call('ai', ['mode' => 'edit', 'text' => '', 'action' => 'improve'])[1]['error'] ?? ''], ['bad_input', 'bad_input']);
$db->exec('UPDATE ai_usage SET used = 40 WHERE user_id = ? AND day = ?', [$W, $app->today()]);
$db->exec('UPDATE users SET ai_credits = 0 WHERE user_id = ?', [$W]);
T::eq('AI limiti tugadi: 429', $call('ai', ['mode' => 'post', 'topic' => 'Yana mavzu', 'style' => 'news'])[0], 429);
$db->exec('UPDATE ai_usage SET used = 0 WHERE user_id = ? AND day = ?', [$W, $app->today()]);
$used0 = $app->aiUsage->usedOn($W, $app->today());
$aiQueue = [[500, '']];
T::check('AI xatosi: 502 va limit qaytadi', $call('ai', ['mode' => 'post', 'topic' => 'Mavzu bor', 'style' => 'news'])[0] === 502
    && $app->aiUsage->usedOn($W, $app->today()) === $used0);
$app->ai = new Ai(new Config([]));

// bot <-> Mini App
T::eq('webhook manzilisiz Mini App o\'chiq', $app->miniAppUrl(), null);
$app2 = new App(new Config(['bot_token' => $token, 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN],
    'webhook_url' => 'https://bot.uz/PostAssist/webhook.php']), $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
T::eq('Mini App manzili webhook\'dan', [$app2->miniAppUrl(), $app2->miniAppUrl('tab=post')], ['https://bot.uz/PostAssist/app.php', 'https://bot.uz/PostAssist/app.php?tab=post']);
$app3 = new App(new Config(['bot_token' => $token, 'webhook_url' => 'http://bot.uz/webhook.php']), $db, new Telegram('x', 'https://x', $fake));
T::eq('HTTPS bo\'lmasa — o\'chiq', $app3->miniAppUrl(), null);
$app4 = new App(new Config(['bot_token' => $token, 'webhook_url' => 'https://bot.uz/webhook.php', 'miniapp_enabled' => false]), $db, new Telegram('x', 'https://x', $fake));
T::eq('miniapp_enabled=false — o\'chiq', $app4->miniAppUrl(), null);
$router2 = new PostAssist\Router($app2);
$fake->reset();
$router2->handle(['update_id' => $upd++, 'message' => ['message_id' => 1, 'from' => $from($W), 'chat' => ['id' => $W, 'type' => 'private'], 'text' => '/app']]);
T::check('/app: web_app tugmasi', strpos($mk($fake->of('sendMessage')[0] ?? []), 'web_app') !== false && strpos($mk($fake->of('sendMessage')[0] ?? []), 'app.php') !== false);
T::check('asosiy (pastki) menyuda Mini App takrorlanmaydi — u Telegram menyu tugmasida', strpos(json_encode(Keyboards::main('uz', false, false, 'https://bot.uz/app.php')), 'web_app') === false);
$fake->reset();
$router2->handle(['update_id' => $upd++, 'message' => ['message_id' => 2, 'from' => $from($W), 'chat' => ['id' => $W, 'type' => 'private'], 'text' => '/newpost']]);
$fake->reset();
$router2->handle(['update_id' => $upd++, 'message' => ['message_id' => 3, 'from' => $from($W), 'chat' => ['id' => $W, 'type' => 'private'], 'text' => 'Mini App sinov']]);
T::check('post preview\'da «📱 Mini App\'da» (tab=post)', strpos($mk($fake->of('sendMessage')[0] ?? []), 'app.php?tab=post') !== false, $fake->texts() . ' | ' . $mk($fake->of('sendMessage')[0] ?? []));
$app->states->clear($W);

// app.php sahifasi
$html = (string) shell_exec(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(dirname(__DIR__) . '/app.php') . ' 2>&1');
T::check('app.php: sahifa chiqadi, PHP xatosiz, 3 til matni ichida', strpos($html, '<!doctype html>') === 0 && strpos($html, 'Fatal') === false
    && strpos($html, 'Warning') === false && strpos($html, '"ma_tab_home"') !== false && strpos($html, 'nonce="') !== false);
if (preg_match('#<script nonce="[^"]+">(.*)</script>#s', $html, $js)) {
    $jsFile = tempnam(sys_get_temp_dir(), 'js') . '.js';
    file_put_contents($jsFile, $js[1]);
    $node = trim((string) shell_exec('command -v node 2>/dev/null'));
    if ($node !== '') {
        exec(escapeshellarg($node) . ' --check ' . escapeshellarg($jsFile) . ' 2>&1', $o, $code);
        T::check('app.php JavaScript sintaksisi to\'g\'ri (node --check)', $code === 0, implode("\n", $o));
    } else {
        T::skip('JavaScript sintaksisi', 'node topilmadi');
    }
    @unlink($jsFile);
}
foreach (I18n::LANGS as $l) {
    $miss = [];
    preg_match_all('/data-t="(ma_[a-z0-9_]+)"/', (string) file_get_contents(dirname(__DIR__) . '/app.php'), $mm);
    foreach (array_unique($mm[1]) as $k) {
        if (!isset(I18n::table($l)[$k])) {
            $miss[] = $k;
        }
    }
    T::eq("[{$l}] Mini App sahifasidagi barcha matnlar bor", $miss, []);
}
