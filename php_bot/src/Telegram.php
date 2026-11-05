<?php
declare(strict_types=1);

namespace PostAssist;

/**
 * Telegram Bot API mijozi (curl). Natija har doim massiv: muvaffaqiyatda ['ok'=>true,'result'=>...],
 * xatoda ['ok'=>false,'error_code'=>..,'description'=>..,'parameters'=>..]. Istisno ko'tarmaydi.
 * Testlar uchun tarmoq qatlami (`$transport`) almashtiriladi: fn(string $method, array $params): array.
 */
final class Telegram
{
    private string $token;
    private string $base;
    /** @var callable|null */
    private $transport;
    /** @var callable|null testlar uchun: fn(string $url): ?string */
    private $downloader;
    /** @var callable|null ko'rinish qatlami: fn(method, params, premium, styles): params */
    private $decorator;
    /** @var callable|null qatlam rad etilganda: fn(string $what, array $response) */
    private $onDecorFail;

    public function __construct(string $token, string $base = 'https://api.telegram.org', ?callable $transport = null)
    {
        $this->token = $token;
        $this->base = rtrim($base, '/');
        $this->transport = $transport;
    }

    public function setDecorator(?callable $decorator, ?callable $onFail = null): void
    {
        $this->decorator = $decorator;
        $this->onDecorFail = $onFail;
    }

    /**
     * So'rov. Ko'rinish qatlami (premium emoji, rangli tugmalar) bo'lsa qo'llanadi; Telegram 400 bilan rad etsa —
     * avval premium emojisiz, keyin rangsiz qayta yuboriladi va o'sha qatlam o'chiriladi (xabar baribir yetadi).
     * @param array<string, mixed> $params
     */
    public function call(string $method, array $params = []): array
    {
        if ($this->decorator === null) {
            unset($params['_raw']);
            return $this->send($method, $params);
        }
        $plain = $params;
        unset($plain['_raw']);
        $d = ($this->decorator)($method, $params, true, true);
        $res = $this->send($method, $d);
        if (!empty($res['ok']) || (int) ($res['error_code'] ?? 0) !== 400 || $d == $plain) {
            return $res;
        }
        $d2 = ($this->decorator)($method, $params, false, true);
        if ($d2 != $d) {
            $res2 = $this->send($method, $d2);
            if (!empty($res2['ok'])) {
                if ($this->onDecorFail) {
                    ($this->onDecorFail)('premium', $res);
                }
                return $res2;
            }
        }
        $d3 = ($this->decorator)($method, $params, false, false);
        if ($d3 != $d2) {
            $res3 = $this->send($method, $d3);
            if (!empty($res3['ok'])) {
                if ($this->onDecorFail) {
                    ($this->onDecorFail)('styles', $res);
                }
                return $res3;
            }
        }
        return $res;
    }

    /** @param array<string, mixed> $params */
    private function send(string $method, array $params): array
    {
        foreach ($params as $k => $v) {
            if (is_array($v)) {
                $params[$k] = json_encode($v, JSON_UNESCAPED_UNICODE);
            } elseif (is_bool($v)) {
                $params[$k] = $v ? 'true' : 'false';
            } elseif ($v === null) {
                unset($params[$k]);
            }
        }
        if ($this->transport !== null) {
            return ($this->transport)($method, $params);
        }
        return $this->http($method, $params);
    }

    /** @param array<string, mixed> $params */
    private function http(string $method, array $params): array
    {
        $ch = curl_init($this->base . '/bot' . $this->token . '/' . $method);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            // fayl bo'lsa multipart (CURLFile), aks holda oddiy forma
            CURLOPT_POSTFIELDS => self::hasFile($params) ? $params : http_build_query($params),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => self::hasFile($params) ? 120 : 30,
        ]);
        $body = curl_exec($ch);
        $err = curl_error($ch);
        curl_close($ch);
        if ($body === false || $body === '') {
            return ['ok' => false, 'error_code' => 0, 'description' => 'network: ' . ($err ?: 'empty response')];
        }
        $data = json_decode((string) $body, true);
        if (!is_array($data)) {
            return ['ok' => false, 'error_code' => 0, 'description' => 'bad json'];
        }
        return $data;
    }

    public function setDownloader(?callable $d): void
    {
        $this->downloader = $d;
    }

    /**
     * Telegram faylini yuklab oladi (rasm, ovoz). Hajm $maxBytes dan oshsa yoki xato bo'lsa — null.
     * Manzilda bot tokeni bor — hech qachon logga yozilmaydi.
     * @return array{0:string,1:string}|null [baytlar, fayl yo'li]
     */
    public function fetchFile(string $fileId, int $maxBytes): ?array
    {
        $r = $this->call('getFile', ['file_id' => $fileId]);
        $path = (string) ($r['result']['file_path'] ?? '');
        if (empty($r['ok']) || $path === '' || !preg_match('#^[A-Za-z0-9_/.\-]+$#', $path) || strpos($path, '..') !== false || (int) ($r['result']['file_size'] ?? 0) > $maxBytes) {
            return null;
        }
        $url = $this->base . '/file/bot' . $this->token . '/' . $path;
        if ($this->downloader !== null) {
            $bytes = ($this->downloader)($url);
        } else {
            $ch = curl_init($url);
            curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 40, CURLOPT_FOLLOWLOCATION => false]);
            $bytes = curl_exec($ch);
            $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
            curl_close($ch);
            if ($code !== 200) {
                $bytes = false;
            }
        }
        return (is_string($bytes) && $bytes !== '' && strlen($bytes) <= $maxBytes) ? [$bytes, $path] : null;
    }

    private static function hasFile(array $params): bool
    {
        foreach ($params as $v) {
            if ($v instanceof \CURLFile) {
                return true;
            }
        }
        return false;
    }

    // ------------------------------------------------------------- qisqa yordamchilar

    public function sendMessage(int $chatId, string $text, ?array $markup = null, bool $preview = false): array
    {
        return $this->call('sendMessage', [
            'chat_id' => $chatId, 'text' => $text, 'parse_mode' => 'HTML',
            'reply_markup' => $markup, 'link_preview_options' => ['is_disabled' => !$preview],
        ]);
    }

    public function editMessageText(int $chatId, int $messageId, string $text, ?array $markup = null): array
    {
        return $this->call('editMessageText', [
            'chat_id' => $chatId, 'message_id' => $messageId, 'text' => $text, 'parse_mode' => 'HTML',
            'reply_markup' => $markup, 'link_preview_options' => ['is_disabled' => true],
        ]);
    }

    public function answerCallback(string $id, string $text = '', bool $alert = false): array
    {
        return $this->call('answerCallbackQuery', ['callback_query_id' => $id, 'text' => $text, 'show_alert' => $alert]);
    }

    /** Xato tavsifi qayta urinishga arziydimi (tarmoq, 429, 5xx). */
    public static function isTemporary(array $res): bool
    {
        $code = (int) ($res['error_code'] ?? 0);
        return $code === 0 || $code === 429 || $code >= 500;
    }

    public static function retryAfter(array $res): int
    {
        return (int) ($res['parameters']['retry_after'] ?? 0);
    }
}
