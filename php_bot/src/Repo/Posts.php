<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

final class Posts
{
    public const STUCK_MINUTES = 10;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function pendingCount(int $userId): int
    {
        return (int) $this->db->value("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND status IN ('pending', 'processing')", [$userId]);
    }

    public function create(int $userId, int $channelId, array $draft, string $utcSql, bool $notify): int
    {
        $this->db->exec(
            'INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, file_id, button_text, button_url, scheduled_time, notify_owner, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, UTC_TIMESTAMP())',
            [$userId, $channelId, $draft['type'], $draft['text'], $draft['file_id'], $draft['button_text'] ?? null,
                $draft['button_url'] ?? null, $utcSql, $notify ? 1 : 0]
        );
        return $this->db->lastId();
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT p.*, c.title AS channel_title FROM scheduled_posts p LEFT JOIN channels c ON c.channel_id = p.channel_id WHERE p.id = ?', [$id]);
    }

    public function getOwnedPending(int $userId, int $id): ?array
    {
        return $this->db->one("SELECT p.*, c.title AS channel_title FROM scheduled_posts p LEFT JOIN channels c ON c.channel_id = p.channel_id
             WHERE p.id = ? AND p.user_id = ? AND p.status = 'pending'", [$id, $userId]);
    }

    public function listPending(int $userId, int $limit = 20): array
    {
        return $this->db->all("SELECT p.*, c.title AS channel_title FROM scheduled_posts p LEFT JOIN channels c ON c.channel_id = p.channel_id
             WHERE p.user_id = ? AND p.status = 'pending' ORDER BY p.scheduled_time, p.id LIMIT " . max(1, min(50, $limit)), [$userId]);
    }

    /** Faqat egasi va faqat hali chiqmagan postni bekor qiladi. */
    public function cancel(int $userId, int $id): bool
    {
        return $this->db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status = 'pending'", [$id, $userId]) > 0;
    }

    /** Vaqti kelgan postlar ID'lari (eskisi birinchi). */
    public function dueIds(string $nowUtcSql, int $limit): array
    {
        return array_map('intval', array_column($this->db->all(
            "SELECT id FROM scheduled_posts WHERE status = 'pending' AND scheduled_time <= ? ORDER BY scheduled_time, id LIMIT " . max(1, $limit),
            [$nowUtcSql]
        ), 'id'));
    }

    /** Atomik egallash: faqat bitta jarayon 'processing' ga o'tkaza oladi. */
    public function claim(int $id): bool
    {
        return $this->db->exec("UPDATE scheduled_posts SET status = 'processing', processing_started_at = UTC_TIMESTAMP() WHERE id = ? AND status = 'pending'", [$id]) > 0;
    }

    public function markSent(int $id, ?int $messageId): void
    {
        $this->db->exec("UPDATE scheduled_posts SET status = 'sent', message_id = ?, sent_at = UTC_TIMESTAMP(), last_error = NULL WHERE id = ?", [$messageId, $id]);
    }

    public function markFailed(int $id, string $error): void
    {
        $this->db->exec("UPDATE scheduled_posts SET status = 'failed', last_error = ?, attempt_count = attempt_count + 1 WHERE id = ?", [mb_substr($error, 0, 255), $id]);
    }

    /** Vaqtinchalik xato: keyinroq qayta urinish. */
    public function retryLater(int $id, string $error, string $retryAtUtcSql): void
    {
        $this->db->exec(
            "UPDATE scheduled_posts SET status = 'pending', last_error = ?, attempt_count = attempt_count + 1, scheduled_time = ? WHERE id = ?",
            [mb_substr($error, 0, 255), $retryAtUtcSql, $id]
        );
    }

    /** Jarayon yiqilib 'processing' da qolgan postlar qaytadan navbatga (urinish soni +1). */
    public function recoverStuck(): int
    {
        return $this->db->exec("UPDATE scheduled_posts SET status = 'pending', attempt_count = attempt_count + 1
             WHERE status = 'processing' AND processing_started_at < UTC_TIMESTAMP() - INTERVAL " . self::STUCK_MINUTES . ' MINUTE');
    }

    public function userStats(int $userId): array
    {
        $rows = $this->db->all('SELECT status, COUNT(*) AS n FROM scheduled_posts WHERE user_id = ? GROUP BY status', [$userId]);
        $out = ['pending' => 0, 'sent' => 0, 'failed' => 0];
        foreach ($rows as $r) {
            if ($r['status'] === 'processing') {
                $out['pending'] += (int) $r['n'];
            } elseif (isset($out[$r['status']])) {
                $out[$r['status']] += (int) $r['n'];
            }
        }
        return $out;
    }
}
