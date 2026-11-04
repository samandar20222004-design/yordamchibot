<?php
// Telegram webhook: Telegram har bir yangilanishni shu faylga POST qiladi.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Router;

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    http_response_code(405);
    exit('POST only');
}
try {
    $cfg = postassist_config();
} catch (Throwable $e) {
    http_response_code(500);
    exit('config');
}
$secret = (string) ($cfg['webhook_secret'] ?? '');
$given = (string) ($_SERVER['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] ?? '');
if ($secret === '' || !hash_equals($secret, $given)) {
    http_response_code(403);
    exit('forbidden');
}
$body = file_get_contents('php://input', false, null, 0, 1048576);
$update = json_decode((string) $body, true);
if (!is_array($update)) {
    http_response_code(400);
    exit('bad request');
}
@set_time_limit(55);
$app = null;
$released = false;
try {
    $app = App::fromConfig($cfg);
    // Albom qismlarini kutish uchun: Telegram'ga «ok» darhol qaytariladi, ish esa davom etadi
    $app->releaseClient = static function () use (&$released): void {
        if ($released || headers_sent()) {
            return;
        }
        $released = true;
        ignore_user_abort(true);
        http_response_code(200);
        header('Content-Type: text/plain');
        header('Content-Length: 2');
        header('Connection: close');
        echo 'ok';
        while (ob_get_level() > 0) {
            @ob_end_flush();
        }
        flush();
        if (function_exists('fastcgi_finish_request')) {
            fastcgi_finish_request();
        } elseif (function_exists('litespeed_finish_request')) {
            litespeed_finish_request();
        }
    };
    (new Router($app))->handle($update);
} catch (Throwable $e) {
    // Xato tafsiloti faqat logga (foydalanuvchiga emas); Telegram qayta yubormasligi uchun 200 qaytariladi.
    $line = get_class($e) . ': ' . $e->getMessage() . ' @ ' . basename($e->getFile()) . ':' . $e->getLine();
    if ($app !== null) {
        $app->log('webhook xato: ' . $line);
    } else {
        @file_put_contents(__DIR__ . '/storage/bot.log', '[' . gmdate('Y-m-d H:i:s') . "] webhook xato: {$line}\n", FILE_APPEND | LOCK_EX);
    }
}
if (!$released) {
    http_response_code(200);
    echo 'ok';
}
