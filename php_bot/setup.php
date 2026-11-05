<?php
// Bir martalik sozlash: bazada jadvallar, Telegram webhook va buyruqlar menyusi.
//   php setup.php            (SSH/terminal)
//   https://domen.uz/postassist/setup.php?key=CRON_KEY   (brauzer)
// Qayta ishga tushirish xavfsiz.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Config;
use PostAssist\I18n;
use PostAssist\Schema;

$cli = PHP_SAPI === 'cli';
$cfg = postassist_config();
if (!$cli) {
    $key = (string) ($cfg['cron_key'] ?? '');
    if (strlen($key) < 16 || !hash_equals($key, (string) ($_GET['key'] ?? ''))) {
        http_response_code(403);
        exit('forbidden');
    }
    header('Content-Type: text/plain; charset=utf-8');
}
$out = static function (string $s): void {
    echo $s . "\n";
};
if (version_compare(PHP_VERSION, '7.4.0', '<')) {
    $out('XATO: PHP 7.4 yoki yangi kerak, sizda ' . PHP_VERSION);
    exit(1);
}
foreach (['pdo_mysql', 'curl', 'mbstring', 'json'] as $ext) {
    $out(sprintf('%-10s %s', $ext, extension_loaded($ext) ? 'OK' : 'YO\'Q — hosting panelida yoqing'));
}
$problems = (new Config($cfg))->problems();
if ($problems) {
    $out('config.php da to\'ldirilmagan: ' . implode(', ', $problems));
    exit(1);
}
try {
    $app = App::fromConfig($cfg);
} catch (Throwable $e) {
    $msg = $e->getMessage();
    $out('XATO: bazaga ulanib bo\'lmadi.');
    $out('Sabab: ' . $msg);
    if (stripos($msg, 'Access denied') !== false) {
        $out('Maslahat: db_user yoki db_pass noto\'g\'ri (yoki foydalanuvchiga bu bazaga huquq berilmagan).');
    } elseif (stripos($msg, 'Unknown database') !== false) {
        $out('Maslahat: db_name noto\'g\'ri — panelda baza nomini aynan (prefiksi bilan) yozing.');
    } elseif (stripos($msg, 'getaddrinfo') !== false || stripos($msg, 'Connection refused') !== false || stripos($msg, 'No such file') !== false) {
        $out('Maslahat: db_host noto\'g\'ri — panelda bazaning server manzilini tekshiring (odatda localhost).');
    }
    exit(1);
}
try {
    $changes = Schema::apply($app->db, (string) file_get_contents(__DIR__ . '/sql/schema.sql'));
} catch (Throwable $e) {
    $out('XATO: jadvallar yaratilmadi.');
    $out('Sabab: ' . $e->getMessage());
    exit(1);
}
$out('Baza jadvallari: OK' . ($changes ? ' (yangilandi: ' . implode(', ', $changes) . ')' : ''));

$url = (string) ($cfg['webhook_url'] ?? '');
if (strpos($url, 'https://') !== 0) {
    $out('webhook_url https:// bilan boshlanishi kerak');
    exit(1);
}
$r = $app->tg->call('setWebhook', [
    'url' => $url, 'secret_token' => (string) $cfg['webhook_secret'],
    'allowed_updates' => ['message', 'callback_query', 'my_chat_member', 'pre_checkout_query'], 'max_connections' => 20,
]);
$out('Webhook: ' . (!empty($r['ok']) ? 'OK' : 'XATO — ' . ($r['description'] ?? '')));

$commands = [
    'uz' => ['start' => 'Bosh menyu', 'newpost' => 'Yangi post', 'app' => 'Mini App', 'ai' => 'AI bilan post', 'contentplan' => 'AI kontent-reja', 'autopilot' => 'Autopilot (har kuni AI post)', 'market' => 'Reklama birjasi', 'rss' => 'RSS avtopost', 'templates' => 'Shablonlar', 'report' => 'Haftalik hisobot', 'stats' => 'Statistika', 'sent' => 'Yuborilgan postlar', 'queue' => 'Rejalashtirilgan postlar', 'channels' => 'Kanallarim', 'settings' => 'Sozlamalar', 'plans' => 'Tariflar', 'invite' => 'Do\'stlarni taklif qilish', 'help' => 'Yordam'],
    'ru' => ['start' => 'Главное меню', 'newpost' => 'Новый пост', 'app' => 'Mini App', 'ai' => 'Пост с AI', 'contentplan' => 'AI контент-план', 'autopilot' => 'Автопилот (AI-пост каждый день)', 'market' => 'Биржа рекламы', 'rss' => 'RSS-автопостинг', 'templates' => 'Шаблоны', 'report' => 'Недельный отчёт', 'stats' => 'Статистика', 'sent' => 'Отправленные посты', 'queue' => 'Запланированные посты', 'channels' => 'Мои каналы', 'settings' => 'Настройки', 'plans' => 'Тарифы', 'invite' => 'Пригласить друзей', 'help' => 'Помощь'],
    'en' => ['start' => 'Main menu', 'newpost' => 'New post', 'app' => 'Mini App', 'ai' => 'Post with AI', 'contentplan' => 'AI content plan', 'autopilot' => 'Autopilot (daily AI post)', 'market' => 'Ad market', 'rss' => 'RSS autopost', 'templates' => 'Templates', 'report' => 'Weekly report', 'stats' => 'Statistics', 'sent' => 'Sent posts', 'queue' => 'Scheduled posts', 'channels' => 'My channels', 'settings' => 'Settings', 'plans' => 'Plans', 'invite' => 'Invite friends', 'help' => 'Help'],
];
foreach (I18n::LANGS as $lang) {
    $list = [];
    foreach ($commands[$lang] as $c => $d) {
        $list[] = ['command' => $c, 'description' => $d];
    }
    $params = ['commands' => $list];
    if ($lang !== 'uz') {
        $params['language_code'] = $lang;
    }
    $r = $app->tg->call('setMyCommands', $params);
    $out("Buyruqlar ({$lang}): " . (!empty($r['ok']) ? 'OK' : 'XATO — ' . ($r['description'] ?? '')));
}
$mini = $app->miniAppUrl();
if ($mini !== null) {
    $r = $app->tg->call('setChatMenuButton', ['menu_button' => ['type' => 'web_app', 'text' => 'Mini App', 'web_app' => ['url' => $mini]]]);
    $out('Mini App menyu tugmasi: ' . (!empty($r['ok']) ? 'OK — ' . $mini : 'XATO — ' . ($r['description'] ?? '')));
} else {
    $out('Mini App: o\'chiq (webhook_url https://.../webhook.php bo\'lishi kerak yoki miniapp_url yozing)');
}
$out('Tayyor. Endi cron.php ni har daqiqaga qo\'ying (README.md).');
