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

    public function __construct(string $token, string $base = 'https://api.telegram.org', ?callable $transport = null)
    {
        $this->token = $token;
        $this->base = rtrim($base, '/');
        $this->transport = $transport;
    }

    /** @param array<string, mixed> $params */
    public function call(string $method, array $params = []): array
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
            CURLOPT_POSTFIELDS => http_build_query($params),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => 30,
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
