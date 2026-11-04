<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

/** Kanalga chiqqan xabarlar (reaksiya tugmalari va avto-o'chirish uchun). */
final class Messages
{
    public const MAX_DELETE_ATTEMPTS = 3;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** @param array<int, int> $ids xabar ID'lari (albomda bir nechta; birinchisi asosiy) */
    public function record(array $post, int $chatId, array $ids, ?string $deleteAtUtcSql, string $nowSql): void
    {
        if (!$ids) {
            return;
        }
        $extra = array_slice($ids, 1);
        $this->db->exec('INSERT IGNORE INTO sent_messages (post_id, chat_id, message_id, extra_ids, reactions, button_text, button_url, delete_at, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [(int) $post['id'], $chatId, $ids[0], $extra ? implode(',', $extra) : null,
            $post['post_type'] === 'album' ? null : ($post['reactions'] ?? null), $post['button_text'] ?? null, $post['button_url'] ?? null,
            $deleteAtUtcSql, $nowSql]);
    }

    public function find(int $chatId, int $messageId): ?array
    {
        return $this->db->one('SELECT * FROM sent_messages WHERE chat_id = ? AND message_id = ?', [$chatId, $messageId]);
    }

    /**
     * Reaksiya bosildi: yangi bo'lsa qo'yiladi, xuddi shuni bossa olib tashlanadi, boshqasini bossa almashtiriladi.
     * @return string added|removed|changed
     */
    public function vote(int $chatId, int $messageId, int $userId, int $idx, string $nowSql): string
    {
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $cur = $this->db->value('SELECT idx FROM reaction_votes WHERE chat_id = ? AND message_id = ? AND user_id = ? FOR UPDATE', [$chatId, $messageId, $userId]);
            if ($cur === null) {
                $this->db->exec('INSERT INTO reaction_votes (chat_id, message_id, user_id, idx, created_at) VALUES (?, ?, ?, ?, ?)
                     ON DUPLICATE KEY UPDATE idx = VALUES(idx)', [$chatId, $messageId, $userId, $idx, $nowSql]);
                $r = 'added';
            } elseif ((int) $cur === $idx) {
                $this->db->exec('DELETE FROM reaction_votes WHERE chat_id = ? AND message_id = ? AND user_id = ?', [$chatId, $messageId, $userId]);
                $r = 'removed';
            } else {
                $this->db->exec('UPDATE reaction_votes SET idx = ? WHERE chat_id = ? AND message_id = ? AND user_id = ?', [$idx, $chatId, $messageId, $userId]);
                $r = 'changed';
            }
            $pdo->commit();
            return $r;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** @return array<int, int> tartib raqami => ovozlar soni */
    public function counts(int $chatId, int $messageId): array
    {
        $out = [];
        foreach ($this->db->all('SELECT idx, COUNT(*) AS n FROM reaction_votes WHERE chat_id = ? AND message_id = ? GROUP BY idx', [$chatId, $messageId]) as $r) {
            $out[(int) $r['idx']] = (int) $r['n'];
        }
        return $out;
    }

    public function dueForDelete(string $nowSql, int $limit = 50): array
    {
        return $this->db->all('SELECT * FROM sent_messages WHERE deleted = 0 AND delete_at IS NOT NULL AND delete_at <= ? ORDER BY delete_at LIMIT ' . max(1, $limit), [$nowSql]);
    }

    public function markDeleted(int $id): void
    {
        $this->db->exec('UPDATE sent_messages SET deleted = 1 WHERE id = ?', [$id]);
    }

    /** Vaqtinchalik xato: 5 daqiqadan keyin yana (ko'pi bilan 3 marta, keyin o'chirilgan deb belgilanadi). */
    public function deleteLater(int $id, string $retryAtSql): void
    {
        $this->db->exec('UPDATE sent_messages SET delete_attempts = delete_attempts + 1, delete_at = ?,
             deleted = CASE WHEN delete_attempts + 1 >= ? THEN 1 ELSE 0 END WHERE id = ?', [$retryAtSql, self::MAX_DELETE_ATTEMPTS, $id]);
    }

    public function cleanup(): void
    {
        // Reaksiya va avto-o'chirish uchun 60 kun yetadi
        $this->db->exec('DELETE FROM sent_messages WHERE created_at < UTC_TIMESTAMP() - INTERVAL 60 DAY AND (deleted = 1 OR delete_at IS NULL)');
        $this->db->exec('DELETE v FROM reaction_votes v LEFT JOIN sent_messages s ON s.chat_id = v.chat_id AND s.message_id = v.message_id WHERE s.id IS NULL
             AND v.created_at < UTC_TIMESTAMP() - INTERVAL 60 DAY');
    }
}
