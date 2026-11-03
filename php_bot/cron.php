<?php
// Rejalashtirilgan postlarni yuborish. Hostingda HAR DAQIQADA ishga tushiring:
//   php /home/USER/postassist/cron.php
// yoki (CLI cron bo'lmasa) brauzer/URL orqali: https://domen.uz/postassist/cron.php?key=CRON_KEY
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Services\Scheduler;

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
@set_time_limit(60);
$app = App::fromConfig($cfg);
try {
    $r = (new Scheduler($app))->run(50);
    echo $r['locked'] ? "boshqa cron ishlayapti\n" : "yuborildi={$r['sent']} qayta={$r['retry']} xato={$r['failed']}\n";
} catch (Throwable $e) {
    $app->log('cron xato: ' . get_class($e) . ': ' . $e->getMessage());
    if ($cli) {
        fwrite(STDERR, "cron xato: " . $e->getMessage() . "\n");
    }
    http_response_code(500);
    echo "xato\n";
}
