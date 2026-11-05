<?php
// 17-bosqich: kanal statistikasi + Mini App shablonlari (TemplatesTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Handlers\MiniAppApi;
use PostAssist\Handlers\StatsHandler;
use PostAssist\Services\Scheduler;

T::section('AC. Kanal statistikasi');
T::eq('grafik: o\'sish', StatsHandler::sparkline([['n' => 100], ['n' => 150], ['n' => 200]]), '▁▅█');
T::eq('grafik: o\'zgarishsiz', StatsHandler::sparkline([['n' => 5], ['n' => 5]]), '▄▄');
T::eq('grafik: bitta nuqta — yo\'q', StatsHandler::sparkline([['n' => 5]]), '');
$SU = 9970;
$SC = -1009970;
$text($SU, '/start');
$fake->chats[$SC] = ['id' => $SC, 'type' => 'channel', 'title' => 'Statistika kanali'];
$fake->members["{$SC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($SU, $SC, 'Statistika kanali', null, 0);
$SREF = (int) $db->value('SELECT id FROM channels WHERE channel_id = ?', [$SC]);
$sched = new Scheduler($app, static function (int $us): void {
});
$counts = [1000, 1010, 1030, 1025, 1100];
$clock = new DateTimeImmutable('2027-05-01 08:00:00', new DateTimeZone('UTC'));
foreach ($counts as $i => $n) {
    $fake->forced['getChatMemberCount'] = array_fill(0, 200, ['ok' => true, 'result' => $n]);
    $sched->run(5);
    if ($i < count($counts) - 1) {
        $clock = $clock->modify('+1 day');
    }
}
$fake->forced['getChatMemberCount'] = [];
T::eq('cron: har kuni bitta o\'lchov', (int) $db->value('SELECT COUNT(*) FROM channel_stats WHERE channel_id = ?', [$SC]), 5);
$sched->run(5);
T::eq('o\'sha kuni qayta o\'lchanmaydi', (int) $db->value('SELECT COUNT(*) FROM channel_stats WHERE channel_id = ?', [$SC]), 5);
// post, reaksiya va yashirin matn faolligi
$text($SU, '/newpost');
$text($SU, 'Statistika uchun post');
$press($SU, 'p:rx');
$press($SU, 'px:0');
$press($SU, 'p:hidden');
$text($SU, 'Sir');
$press($SU, 'p:now');
$sm3 = $db->one('SELECT * FROM sent_messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1', [$SC]);
foreach ([8001, 8002] as $voter) {
    $router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'v' . $upd, 'from' => ['id' => $voter, 'is_bot' => false, 'first_name' => 'V'],
        'data' => 'rx:0', 'message' => ['message_id' => (int) $sm3['message_id'], 'chat' => ['id' => $SC, 'type' => 'channel']]]]);
}
$fake->members["{$SC}|8001"] = ['status' => 'member'];
foreach ([8001, 8003] as $u) {
    $router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'h' . $upd, 'from' => ['id' => $u, 'is_bot' => false, 'first_name' => 'V'],
        'data' => 'hd', 'message' => ['message_id' => (int) $sm3['message_id'], 'chat' => ['id' => $SC, 'type' => 'channel']]]]);
}
$st = StatsHandler::channelStats($app, $SU)[0];
T::check('obunachilar va o\'sish (bugun, 7 kun)', $st['subscribers'] === 1100 && $st['d1'] === 75 && $st['d7'] === null && count($st['series']) === 5);
T::check('postlar, reaksiyalar, yashirin matn hisoblandi', $st['posts7'] === 1 && $st['votes30'] === 2 && $st['opens30'] === 1 && $st['locked30'] === 1
    && $st['top'] !== null && $st['top']['votes'] === 2);
$text($SU, '📊 Statistika');
T::check('statistika: kanal qatori va tugmasi', strpos($fake->lastText(), 'Statistika kanali') !== false && strpos($fake->lastText(), '1 100') !== false
    && strpos($kbR(), 'st:c:' . $SREF) !== false && strpos($kbR(), 'q:list') !== false);
$press($SU, 'st:c:' . $SREF);
T::check('kanal sahifasi: grafik, o\'sish, faollik, eng yaxshi post', strpos($fake->lastText(), '+75') !== false && strpos($fake->lastText(), '▁') !== false
    && strpos($fake->lastText(), 'Statistika uchun post') !== false && strpos($fake->lastText(), 'ochildi <b>1</b>') !== false);
$press($ADMIN, 'st:c:' . $SREF);
T::check('begona kanal statistikasi ko\'rinmaydi', strpos($fake->lastText(), '+75') === false);
$fake->forced['getChatMemberCount'] = [['ok' => true, 'result' => 1123]];
$press($SU, 'st:r:' . $SREF);
T::check('🔄 Yangilash: hozirgi qiymat', strpos($fake->lastText(), '1 123') !== false && strpos($fake->lastText(), '+98') !== false);
$fake->forced['getChatMemberCount'] = [];
$mcallS = static function (int $uid, string $action, array $in = []) use ($app, $fake, $mkInit, &$clock, $token): array {
    $fake->reset();
    return MiniAppApi::handle($app, $action, $in, $mkInit(['id' => $uid, 'first_name' => 'U', 'language_code' => 'uz'], $clock->getTimestamp() - 30, $token));
};
[$s1, $r1] = $mcallS($SU, 'stats');
T::check('Mini App: stats API', $s1 === 200 && $r1['channels'][0]['subscribers'] === 1123 && count($r1['channels'][0]['series']) === 5);

T::section('AD. Mini App: shablonlar');
[$s2, $r2] = $mcallS($SU, 'template_save', ['name' => 'Mini shablon', 'type' => 'text', 'text' => '<b>Salom</b> dunyo', 'button_text' => 'Sayt', 'button_url' => 'sayt.uz',
    'options' => ['silent'], 'hidden' => 'Yashirin']);
T::check('saqlandi', $s2 === 200 && $r2['ok'] === true);
[, $r3] = $mcallS($SU, 'templates');
T::check('ro\'yxatda', count($r3['templates']) === 1 && $r3['templates'][0]['name'] === 'Mini shablon' && $r3['max'] === 3);
[$s4, $r4] = $mcallS($SU, 'template', ['id' => $r2['id']]);
T::check('ochildi: matn, tugma, sozlama, yashirin matn', $s4 === 200 && $r4['template']['text'] === '<b>Salom</b> dunyo' && $r4['template']['button_url'] === 'https://sayt.uz'
    && $r4['template']['options'] === ['silent'] && $r4['template']['hidden'] === 'Yashirin');
T::eq('begona shablon ochilmaydi', $mcallS($ADMIN, 'template', ['id' => $r2['id']])[0], 404);
T::eq('nomsiz rad', $mcallS($SU, 'template_save', ['name' => ' ', 'type' => 'text', 'text' => 'x'])[1]['error'] ?? null, 'name');
T::eq('noto\'g\'ri tugma rad', $mcallS($SU, 'template_save', ['name' => 'B', 'type' => 'text', 'text' => 'x', 'button_text' => 'A', 'button_url' => 'javascript:1'])[1]['error'] ?? null, 'button');
$mcallS($SU, 'template_save', ['name' => 'T2', 'type' => 'text', 'text' => 'x']);
$mcallS($SU, 'template_save', ['name' => 'T3', 'type' => 'text', 'text' => 'x']);
T::eq('bepul limit (3)', $mcallS($SU, 'template_save', ['name' => 'T4', 'type' => 'text', 'text' => 'x'])[1]['error'] ?? null, 'tpl_limit');
$appSrc4 = (string) file_get_contents(__DIR__ . '/../app.php');
T::check('app.php: statistika kartasi va shablon tanlash/saqlash', strpos($appSrc4, "api('stats')") !== false && strpos($appSrc4, 'tpl-sel') !== false && strpos($appSrc4, "api('template_save'") !== false);
