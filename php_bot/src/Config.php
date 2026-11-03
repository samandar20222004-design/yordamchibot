<?php
declare(strict_types=1);

namespace PostAssist;

/** Konfiguratsiya qiymatlari (config.php) — tekshirilgan va standart qiymatlar bilan. */
final class Config
{
    /** @var array<string, mixed> */
    private array $v;

    /** @param array<string, mixed> $values */
    public function __construct(array $values)
    {
        $defaults = [
            'bot_token' => '', 'bot_username' => '', 'admin_ids' => [],
            'db_host' => 'localhost', 'db_port' => 3306, 'db_name' => '', 'db_user' => '', 'db_pass' => '',
            'webhook_secret' => '', 'webhook_url' => '', 'cron_key' => '',
            'timezone' => 'Asia/Tashkent', 'free_max_channels' => 3, 'free_max_queued' => 40,
            'api_base' => 'https://api.telegram.org',
        ];
        $this->v = array_merge($defaults, $values);
        $this->v['admin_ids'] = array_values(array_map('intval', (array) $this->v['admin_ids']));
        $this->v['bot_username'] = ltrim((string) $this->v['bot_username'], '@');
    }

    /** @return mixed */
    public function get(string $key)
    {
        return $this->v[$key] ?? null;
    }

    public function str(string $key): string
    {
        return (string) ($this->v[$key] ?? '');
    }

    public function int(string $key): int
    {
        return (int) ($this->v[$key] ?? 0);
    }

    public function isAdmin(int $userId): bool
    {
        return in_array($userId, $this->v['admin_ids'], true);
    }

    public function tz(): \DateTimeZone
    {
        try {
            return new \DateTimeZone($this->str('timezone') ?: 'Asia/Tashkent');
        } catch (\Throwable $e) {
            return new \DateTimeZone('Asia/Tashkent');
        }
    }

    /** Konfiguratsiyadagi majburiy qiymatlar bo'sh bo'lsa — ro'yxat (setup.php ko'rsatadi). */
    public function problems(): array
    {
        $out = [];
        if (!preg_match('/^\d{5,}:[A-Za-z0-9_-]{20,}$/', $this->str('bot_token'))) {
            $out[] = 'bot_token';
        }
        foreach (['bot_username', 'db_name', 'db_user'] as $k) {
            if ($this->str($k) === '') {
                $out[] = $k;
            }
        }
        if (!preg_match('/^[A-Za-z0-9_-]{16,256}$/', $this->str('webhook_secret'))) {
            $out[] = 'webhook_secret (kamida 16 belgi: A-Z a-z 0-9 _ -)';
        }
        if (strlen($this->str('cron_key')) < 16) {
            $out[] = 'cron_key (kamida 16 belgi)';
        }
        return $out;
    }
}
