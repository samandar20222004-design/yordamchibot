<?php
// Botni to'liq tekshirish: https://domen.uz/PostAssist/check.php?key=CRON_KEY
// Hech qanday maxfiy qiymat (token, parol, kalit) ko'rsatilmaydi; hech narsa o'zgartirilmaydi.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Services\HealthCheck;

$cfg = postassist_config();
$cli = PHP_SAPI === 'cli';
if (!$cli) {
    $key = (string) ($cfg['cron_key'] ?? '');
    if (strlen($key) < 16 || !hash_equals($key, (string) ($_GET['key'] ?? ''))) {
        http_response_code(403);
        exit('forbidden');
    }
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store');
}
@set_time_limit(60);
try {
    $app = App::fromConfig($cfg);
    $rows = (new HealthCheck($app, $cfg, __DIR__))->run(!isset($_GET['noai']));
} catch (Throwable $e) {
    $rows = [['fail', 'Baza / sozlama', 'ulanib bo\'lmadi: config.php dagi db_* qiymatlarini tekshiring']];
}
$icon = ['ok' => '✅', 'warn' => '⚠️', 'fail' => '❌'];
if ($cli) {
    foreach ($rows as [$lv, $name, $detail]) {
        echo $icon[$lv] . ' ' . $name . ': ' . $detail . "\n";
    }
    echo "\n" . HealthCheck::summary($rows) . "\n";
    exit;
}
$e = static function (string $s): string {
    return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
};
echo '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PostAssist — tekshiruv</title>'
    . '<style>body{font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px;background:#f4f6f9;color:#111}h1{font-size:19px}'
    . '.s{padding:12px 14px;border-radius:10px;font-weight:600;margin:12px 0;background:#fff}.r{background:#fff;border-radius:10px;padding:10px 14px;margin:6px 0}'
    . '.fail{border-left:5px solid #e5484d}.warn{border-left:5px solid #f5a524}.ok{border-left:5px solid #30a46c}'
    . '.d{color:#555;white-space:pre-wrap;word-break:break-word;font-size:13px}</style>';
echo '<h1>🔎 PostAssist — umumiy tekshiruv</h1><div class="s">' . $e(HealthCheck::summary($rows)) . '</div>';
foreach ($rows as [$lv, $name, $detail]) {
    echo '<div class="r ' . $lv . '"><b>' . $icon[$lv] . ' ' . $e($name) . '</b><div class="d">' . $e($detail) . '</div></div>';
}
echo '<p class="d">AI so\'rovisiz tezroq: <code>?key=...&amp;noai=1</code>. Sahifani yangilab qayta tekshirishingiz mumkin.</p>';
