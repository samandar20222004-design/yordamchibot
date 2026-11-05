<?php
// Payme Merchant API: Payme (paycom.uz) to'lov holatlarini shu manzilga JSON-RPC bilan yuboradi.
// Kabinetda «Endpoint URL»: https://<domen>/<papka>/payme.php  (Login: Paycom, kalit — config.php `payme_key`)
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\App;
use PostAssist\Services\Payme;

header('Content-Type: application/json; charset=utf-8');
$out = static function (array $r): void {
    echo json_encode($r, JSON_UNESCAPED_UNICODE);
    exit;
};
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    $out(Payme::error(null, Payme::ERR_TRANSPORT, null)); // Payme xatolarni ham HTTP 200 bilan kutadi
}
$body = (string) file_get_contents('php://input', false, null, 0, 65536);
$payload = json_decode($body, true);
if (!is_array($payload)) {
    $out(Payme::error(null, Payme::ERR_PARSE, null));
}
// Ba'zi hostinglar (CGI/FastCGI) Authorization sarlavhasini o'chiradi — .htaccess uni HTTP_AUTHORIZATION ga o'tkazadi
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
if ($auth === null && function_exists('getallheaders')) {
    foreach ((array) getallheaders() as $k => $v) {
        if (strcasecmp((string) $k, 'Authorization') === 0) {
            $auth = (string) $v;
        }
    }
}
try {
    $app = App::fromConfig(postassist_config());
} catch (Throwable $e) {
    $out(Payme::error($payload['id'] ?? null, Payme::ERR_SYSTEM, null));
}
$out((new Payme($app))->handle($payload, $auth !== null ? (string) $auth : null));
