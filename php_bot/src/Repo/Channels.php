<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

final class Channels
{
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function listFor(int $userId): array
    {
        return $this->db->all('SELECT * FROM channels WHERE user_id = ? AND is_active = 1 ORDER BY id', [$userId]);
    }

    public function countFor(int $userId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM channels WHERE user_id = ? AND is_active = 1', [$userId]);
    }

    /** Faqat egasining faol kanali (IDOR himoyasi: boshqa odamning kanali qaytmaydi). */
    public function getOwned(int $userId, int $id): ?array
    {
        return $this->db->one('SELECT * FROM channels WHERE id = ? AND user_id = ? AND is_active = 1', [$id, $userId]);
    }

    public function byChannelId(int $channelId): ?array
    {
        return $this->db->one('SELECT * FROM channels WHERE channel_id = ?', [$channelId]);
    }

    /**
     * Kanalni ulaydi. Natija: connected | already | taken | limit.
     * Boshqa foydalanuvchining FAOL kanali bo'lsa — taken; nofaol (o'chirilgan) bo'lsa — yangi egaga o'tadi.
     */
    public function connect(int $userId, int $channelId, string $title, ?string $username, int $limit): string
    {
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $row = $this->db->one('SELECT * FROM channels WHERE channel_id = ? FOR UPDATE', [$channelId]);
            if ($row && (int) $row['is_active'] === 1) {
                if ((int) $row['user_id'] === $userId) {
                    $this->db->exec('UPDATE channels SET title = ?, username = ? WHERE id = ?', [$title, $username, $row['id']]);
                    $pdo->commit();
                    return 'already';
                }
                $pdo->rollBack();
                return 'taken';
            }
            if ($limit > 0 && (int) $this->db->value('SELECT COUNT(*) FROM channels WHERE user_id = ? AND is_active = 1 FOR UPDATE', [$userId]) >= $limit) {
                $pdo->rollBack();
                return 'limit';
            }
            if ($row) {
                $this->db->exec('UPDATE channels SET user_id = ?, title = ?, username = ?, is_active = 1, created_at = UTC_TIMESTAMP() WHERE id = ?',
                    [$userId, $title, $username, $row['id']]);
            } else {
                $this->db->exec('INSERT INTO channels (user_id, channel_id, title, username, created_at) VALUES (?, ?, ?, ?, UTC_TIMESTAMP())',
                    [$userId, $channelId, $title, $username]);
            }
            $pdo->commit();
            return 'connected';
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** Kanalni o'chiradi va unga navbatdagi postlarni bekor qiladi. */
    public function deactivate(int $channelId): void
    {
        $this->db->exec('UPDATE channels SET is_active = 0 WHERE channel_id = ?', [$channelId]);
        $this->db->exec("UPDATE scheduled_posts SET status = 'cancelled' WHERE channel_id = ? AND status = 'pending'", [$channelId]);
    }
}
