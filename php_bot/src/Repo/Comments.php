<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 💬 Post izohlari (bot orqali) va egasi bloklagan foydalanuvchilar. */
final class Comments
{
    public const PER_10_MIN = 5;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function add(int $postId, int $ownerId, int $userId, string $name, string $text, DateTimeImmutable $nowUtc): int
    {
        $this->db->exec('INSERT INTO post_comments (post_id, owner_id, user_id, name, text, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            [$postId, $ownerId, $userId, mb_substr($name, 0, 64), mb_substr($text, 0, 1000), $nowUtc->format('Y-m-d H:i:s')]);
        return $this->db->lastId();
    }

    /** Oxirgi izohlar (eskisidan yangisiga). */
    public function list(int $postId, int $limit = 15): array
    {
        return array_reverse($this->db->all('SELECT * FROM post_comments WHERE post_id = ? AND deleted = 0 ORDER BY id DESC LIMIT ' . max(1, $limit), [$postId]));
    }

    public function count(int $postId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM post_comments WHERE post_id = ? AND deleted = 0', [$postId]);
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM post_comments WHERE id = ?', [$id]);
    }

    public function delete(int $id): void
    {
        $this->db->exec('UPDATE post_comments SET deleted = 1 WHERE id = ?', [$id]);
    }

    public function recentBy(int $userId, DateTimeImmutable $sinceUtc): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM post_comments WHERE user_id = ? AND created_at >= ?', [$userId, $sinceUtc->format('Y-m-d H:i:s')]);
    }

    /** Bloklash: shu egasining hamma postlarida izoh yozolmaydi, yozganlari yashiriladi. */
    public function ban(int $ownerId, int $userId, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('INSERT IGNORE INTO comment_bans (owner_id, user_id, created_at) VALUES (?, ?, ?)', [$ownerId, $userId, $nowUtc->format('Y-m-d H:i:s')]);
        $this->db->exec('UPDATE post_comments SET deleted = 1 WHERE owner_id = ? AND user_id = ?', [$ownerId, $userId]);
    }

    public function isBanned(int $ownerId, int $userId): bool
    {
        return $this->db->value('SELECT 1 FROM comment_bans WHERE owner_id = ? AND user_id = ?', [$ownerId, $userId]) !== null;
    }
}
