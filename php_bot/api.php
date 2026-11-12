<?php
// 📱 Mini App API: app.php shu faylga so'rov yuboradi. Har so'rov Telegram initData imzosi bilan tekshiriladi.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Handlers\MiniAppApi;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
$out = static function (int $code, array $data): void {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
};
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    $out(405, ['ok' => false, 'error' => 'method']);
    exit;
}
$action = (string) ($_GET['a'] ?? '');
if (!preg_match('/^[a-z_]{2,20}$/', $action)) {
    $out(400, ['ok' => false, 'error' => 'action']);
    exit;
}
$initData = (string) ($_SERVER['HTTP_X_TELEGRAM_INIT_DATA'] ?? '');
$file = null;
$in = [];
if ($action === 'upload') {
    $f = $_FILES['file'] ?? null;
    if (is_array($f) && is_string($f['tmp_name'] ?? null) && is_uploaded_file($f['tmp_name'])) {
        $file = $f;
    }
} else {
    $raw = (string) file_get_contents('php://input', false, null, 0, 262144);
    $in = $raw !== '' ? json_decode($raw, true) : [];
    if (!is_array($in)) {
        $out(400, ['ok' => false, 'error' => 'json']);
        exit;
    }
}
try {
    $app = App::fromConfig(postassist_config());
    [$code, $data] = MiniAppApi::handle($app, $action, $in, $initData, $file);
    $out($code, $data);
} catch (Throwable $e) {
    postassist_log('api xato: ' . get_class($e) . ': ' . $e->getMessage() . ' @ ' . basename($e->getFile()) . ':' . $e->getLine());
    $out(500, ['ok' => false, 'error' => 'server']);
}
