<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

/**
 * Albom (media group) yig'uvchi. Telegram albomning har faylini alohida yangilanish qilib yuboradi. Har qism yoziladi;
 * so'ng ~2 soniya yangi qism kelmasa — albom tayyor. Kim birinchi «tayyor» deb belgilasa (album_done PRIMARY KEY), faqat o'sha
 * postni yig'adi (ikki marta preview chiqmaydi). Jarayon uzilib qolsa, cron.php 10 soniyadan eski albomlarni yig'adi.
 */
final class Albums
{
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function add(int $userId, string $groupId, int $messageId, string $type, string $fileId, string $captionHtml, int $nowMs): void
    {
        $this->db->exec('INSERT IGNORE INTO album_items (user_id, group_id, message_id, item_type, file_id, caption, recv_ms) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [$userId, mb_substr($groupId, 0, 64), $messageId, $type, $fileId, $captionHtml, $nowMs]);
    }

    public function isDone(int $userId, string $groupId): bool
    {
        return $this->db->value('SELECT 1 FROM album_done WHERE user_id = ? AND group_id = ?', [$userId, mb_substr($groupId, 0, 64)]) !== null;
    }

    /** Shu qismdan keyin yangi qism keldimi (oxirgi qism emasmi). */
    public function hasNewer(int $userId, string $groupId, int $messageId): bool
    {
        return (int) $this->db->value('SELECT MAX(message_id) FROM album_items WHERE user_id = ? AND group_id = ?', [$userId, mb_substr($groupId, 0, 64)]) > $messageId;
    }

    /** Atomik: albomni yig'ish huquqi (faqat bitta jarayon true oladi). */
    public function claim(int $userId, string $groupId): bool
    {
        return $this->db->exec('INSERT IGNORE INTO album_done (user_id, group_id, created_at) VALUES (?, ?, UTC_TIMESTAMP())', [$userId, mb_substr($groupId, 0, 64)]) > 0;
    }

    /** @return array<int, array> qismlar xabar tartibida */
    public function items(int $userId, string $groupId): array
    {
        return $this->db->all('SELECT * FROM album_items WHERE user_id = ? AND group_id = ? ORDER BY message_id', [$userId, mb_substr($groupId, 0, 64)]);
    }

    public function drop(int $userId, string $groupId): void
    {
        $this->db->exec('DELETE FROM album_items WHERE user_id = ? AND group_id = ?', [$userId, mb_substr($groupId, 0, 64)]);
    }

    /** Uzilib qolgan (eng oxirgi qismi $beforeMs dan oldin kelgan) va yig'ilmagan albomlar. */
    public function stale(int $beforeMs): array
    {
        return $this->db->all('SELECT i.user_id, i.group_id FROM album_items i LEFT JOIN album_done d ON d.user_id = i.user_id AND d.group_id = i.group_id
             WHERE d.user_id IS NULL GROUP BY i.user_id, i.group_id HAVING MAX(i.recv_ms) < ? LIMIT 50', [$beforeMs]);
    }

    public function cleanup(int $beforeMs): void
    {
        $this->db->exec('DELETE FROM album_items WHERE recv_ms < ?', [$beforeMs]);
        $this->db->exec('DELETE FROM album_done WHERE created_at < UTC_TIMESTAMP() - INTERVAL 2 DAY');
    }
}
