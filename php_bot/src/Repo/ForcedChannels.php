<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** Majburiy obuna kanallari. */
final class ForcedChannels
{
    public const MAX = 5;
    /** A'zolik tekshiruvi natijasi shuncha daqiqa eslab qolinadi (har xabarda Telegram'dan so'ralmaydi). */
    public const CACHE_MINUTES = 10;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function active(): array
    {
        return $this->db->all('SELECT * FROM forced_channels WHERE is_active = 1 ORDER BY id');
    }

    /** @return string added | exists | limit */
    public function add(int $chatId, string $title, ?string $username, ?string $invite, DateTimeImmutable $nowUtc): string
    {
        $row = $this->db->one('SELECT * FROM forced_channels WHERE chat_id = ?', [$chatId]);
        if ($row && (int) $row['is_active'] === 1) {
            return 'exists';
        }
        if (count($this->active()) >= self::MAX) {
            return 'limit';
        }
        if ($row) {
            $this->db->exec('UPDATE forced_channels SET is_active = 1, title = ?, username = ?, invite_link = ? WHERE id = ?', [$title, $username, $invite, $row['id']]);
        } else {
            $this->db->exec('INSERT INTO forced_channels (chat_id, title, username, invite_link, created_at) VALUES (?, ?, ?, ?, ?)',
                [$chatId, mb_substr($title, 0, 255), $username, $invite, $nowUtc->format('Y-m-d H:i:s')]);
        }
        $this->resetCache();
        return 'added';
    }

    public function remove(int $id): bool
    {
        $ok = $this->db->exec('UPDATE forced_channels SET is_active = 0 WHERE id = ? AND is_active = 1', [$id]) > 0;
        $this->resetCache();
        return $ok;
    }

    /** Ro'yxat o'zgarsa hamma qaytadan tekshiriladi. */
    public function resetCache(): void
    {
        $this->db->exec('UPDATE users SET sub_ok_until = NULL WHERE sub_ok_until IS NOT NULL');
    }

    public function cachedOk(int $userId, string $nowSql): bool
    {
        return $this->db->value('SELECT 1 FROM users WHERE user_id = ? AND sub_ok_until > ?', [$userId, $nowSql]) !== null;
    }

    public function setOk(int $userId, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('UPDATE users SET sub_ok_until = ? WHERE user_id = ?', [$nowUtc->modify('+' . self::CACHE_MINUTES . ' minutes')->format('Y-m-d H:i:s'), $userId]);
    }

    public function clearOk(int $userId): void
    {
        $this->db->exec('UPDATE users SET sub_ok_until = NULL WHERE user_id = ?', [$userId]);
    }
}
