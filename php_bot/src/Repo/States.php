<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

/** Suhbat holati: bitta foydalanuvchi = bitta holat. 48 soatdan eski holat yo'q deb hisoblanadi. */
final class States
{
    public const TTL_HOURS = 48;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** @return array{state:string, data:array}|null */
    public function get(int $userId): ?array
    {
        $row = $this->db->one(
            'SELECT state, data FROM user_states WHERE user_id = ? AND updated_at > UTC_TIMESTAMP() - INTERVAL ' . self::TTL_HOURS . ' HOUR',
            [$userId]
        );
        if (!$row) {
            return null;
        }
        $data = json_decode((string) $row['data'], true);
        return ['state' => (string) $row['state'], 'data' => is_array($data) ? $data : []];
    }

    public function set(int $userId, string $state, array $data = []): void
    {
        $this->db->exec(
            'INSERT INTO user_states (user_id, state, data, updated_at) VALUES (?, ?, ?, UTC_TIMESTAMP())
             ON DUPLICATE KEY UPDATE state = VALUES(state), data = VALUES(data), updated_at = VALUES(updated_at)',
            [$userId, $state, json_encode($data, JSON_UNESCAPED_UNICODE)]
        );
    }

    /** Holatni atomik oladi (o'chiradi): ikki parallel so'rovdan faqat bittasi true oladi (ikki marta yuborishdan himoya). */
    public function take(int $userId, string $state): bool
    {
        return $this->db->exec('DELETE FROM user_states WHERE user_id = ? AND state = ?', [$userId, $state]) > 0;
    }

    public function clear(int $userId): void
    {
        $this->db->exec('DELETE FROM user_states WHERE user_id = ?', [$userId]);
    }
}
