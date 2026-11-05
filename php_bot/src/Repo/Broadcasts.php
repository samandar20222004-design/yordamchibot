<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** Hammaga xabar: bitta faol yuborish; cron kursor (last_user_id) bo'yicha bo'laklab yuboradi — qayta ishga tushsa ham ikki marta yubormaydi. */
final class Broadcasts
{
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function audience(): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM users WHERE is_blocked = 0');
    }

    public function running(): ?array
    {
        return $this->db->one("SELECT * FROM broadcasts WHERE status = 'running' ORDER BY id LIMIT 1");
    }

    public function latest(): ?array
    {
        return $this->db->one('SELECT * FROM broadcasts ORDER BY id DESC LIMIT 1');
    }

    /** @return int|null yangi ID yoki null (boshqasi hali ishlayapti) */
    public function start(int $adminId, int $fromChat, int $messageId, DateTimeImmutable $nowUtc): ?int
    {
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            if ($this->db->value("SELECT 1 FROM broadcasts WHERE status = 'running' FOR UPDATE") !== null) {
                $pdo->rollBack();
                return null;
            }
            $this->db->exec('INSERT INTO broadcasts (admin_id, from_chat, message_id, total, created_at) VALUES (?, ?, ?, ?, ?)',
                [$adminId, $fromChat, $messageId, $this->audience(), $nowUtc->format('Y-m-d H:i:s')]);
            $id = $this->db->lastId();
            $pdo->commit();
            return $id;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** @return array<int, int> keyingi foydalanuvchilar (kursordan keyin, bloklanmagan) */
    public function nextUsers(int $afterId, int $limit): array
    {
        return array_map('intval', array_column($this->db->all('SELECT user_id FROM users WHERE user_id > ? AND is_blocked = 0 ORDER BY user_id LIMIT ' . max(1, $limit), [$afterId]), 'user_id'));
    }

    /** Bitta foydalanuvchi natijasi: kursor va hisoblagich bir UPDATE'da. $kind: sent | blocked | failed */
    public function advance(int $id, int $userId, string $kind): void
    {
        $col = ['sent' => 'sent', 'blocked' => 'blocked', 'failed' => 'failed'][$kind] ?? 'failed';
        $this->db->exec("UPDATE broadcasts SET last_user_id = ?, {$col} = {$col} + 1 WHERE id = ? AND status = 'running'", [$userId, $id]);
    }

    public function finish(int $id, string $status, DateTimeImmutable $nowUtc): bool
    {
        return $this->db->exec("UPDATE broadcasts SET status = ?, finished_at = ? WHERE id = ? AND status = 'running'", [$status, $nowUtc->format('Y-m-d H:i:s'), $id]) > 0;
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM broadcasts WHERE id = ?', [$id]);
    }
}
