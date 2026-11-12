<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/**
 * 💬 Fikr-mulohaza (xato / taklif / savol). Spam himoyasi: bitta xabardan keyin 60 s kutish, soatiga 3, kuniga 10 ta,
 * 24 soat ichida bir xil matn qayta qabul qilinmaydi, admin bloklagan foydalanuvchidan qabul qilinmaydi.
 */
final class Feedback
{
    public const KINDS = ['bug', 'idea', 'q'];
    public const MIN_LEN = 10;
    public const MAX_LEN = 2000;
    public const COOLDOWN = 60;
    public const PER_HOUR = 3;
    public const PER_DAY = 10;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function hash(string $body): string
    {
        // katta-kichik harf va bo'shliqlar farqi «yangi» xabar hisoblanmaydi
        return sha1(mb_strtolower((string) preg_replace('/\s+/u', ' ', trim($body))));
    }

    /** null = ruxsat; aks holda sabab: blocked | wait | hour | day | dup. Kutish soniyasi $wait ga yoziladi. */
    public function check(int $userId, string $body, DateTimeImmutable $nowUtc, ?int &$wait = null): ?string
    {
        $wait = 0;
        if ($this->isBlocked($userId)) {
            return 'blocked';
        }
        $now = $nowUtc->getTimestamp();
        $last = $this->db->value('SELECT MAX(created_at) FROM feedback WHERE user_id = ?', [$userId]);
        if ($last !== null) {
            $ago = $now - (new DateTimeImmutable((string) $last, new \DateTimeZone('UTC')))->getTimestamp();
            if ($ago < self::COOLDOWN) {
                $wait = self::COOLDOWN - $ago;
                return 'wait';
            }
        }
        $since = static function (int $sec) use ($nowUtc): string {
            return $nowUtc->modify('-' . $sec . ' seconds')->format('Y-m-d H:i:s');
        };
        if ((int) $this->db->value('SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?', [$userId, $since(3600)]) >= self::PER_HOUR) {
            return 'hour';
        }
        if ((int) $this->db->value('SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?', [$userId, $since(86400)]) >= self::PER_DAY) {
            return 'day';
        }
        if ($this->db->value('SELECT 1 FROM feedback WHERE user_id = ? AND body_hash = ? AND created_at >= ? LIMIT 1', [$userId, self::hash($body), $since(86400)]) !== null) {
            return 'dup';
        }
        return null;
    }

    public function create(int $userId, string $kind, string $body, ?string $fileId, DateTimeImmutable $nowUtc): int
    {
        $this->db->exec('INSERT INTO feedback (user_id, kind, body, body_hash, file_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            [$userId, $kind, $body, self::hash($body), $fileId, $nowUtc->format('Y-m-d H:i:s')]);
        return $this->db->lastId();
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM feedback WHERE id = ?', [$id]);
    }

    /** Holatni o'zgartiradi; true — haqiqatan o'zgardi (ikki admin bir vaqtda bossa, biri). */
    public function setStatus(int $id, string $status, DateTimeImmutable $nowUtc): bool
    {
        return $this->db->exec('UPDATE feedback SET status = ?, answered_at = ? WHERE id = ? AND status <> ?',
            [$status, $nowUtc->format('Y-m-d H:i:s'), $id, $status]) > 0;
    }

    public function open(int $limit = 15): array
    {
        return $this->db->all("SELECT f.*, u.full_name, u.username FROM feedback f LEFT JOIN users u ON u.user_id = f.user_id
            WHERE f.status = 'open' ORDER BY f.id DESC LIMIT " . max(1, min(50, $limit)));
    }

    public function openCount(): int
    {
        return (int) $this->db->value("SELECT COUNT(*) FROM feedback WHERE status = 'open'");
    }

    public function isBlocked(int $userId): bool
    {
        return $this->db->value('SELECT 1 FROM feedback_blocks WHERE user_id = ?', [$userId]) !== null;
    }

    public function block(int $userId, bool $on, DateTimeImmutable $nowUtc): void
    {
        if ($on) {
            $this->db->exec('INSERT IGNORE INTO feedback_blocks (user_id, created_at) VALUES (?, ?)', [$userId, $nowUtc->format('Y-m-d H:i:s')]);
        } else {
            $this->db->exec('DELETE FROM feedback_blocks WHERE user_id = ?', [$userId]);
        }
    }
}
