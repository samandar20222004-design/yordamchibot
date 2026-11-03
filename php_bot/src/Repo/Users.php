<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

final class Users
{
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /**
     * Foydalanuvchini saqlaydi. Yangi bo'lsa ['is_new'=>true]; referal faqat yangi foydalanuvchiga va o'zini taklif qilmasa yoziladi.
     * @return array{is_new:bool, lang:string, lang_chosen:bool}
     */
    public function upsert(int $id, string $username, string $fullName, string $lang, ?int $referrer = null): array
    {
        $ref = ($referrer !== null && $referrer !== $id && $this->exists($referrer)) ? $referrer : null;
        $ins = $this->db->exec(
            'INSERT IGNORE INTO users (user_id, username, full_name, lang, referrer_id, created_at, last_active_at)
             VALUES (?, ?, ?, ?, ?, UTC_TIMESTAMP(), UTC_TIMESTAMP())',
            [$id, mb_substr($username, 0, 64), mb_substr($fullName, 0, 255), $lang, $ref]
        );
        if ($ins === 0) {
            $this->db->exec('UPDATE users SET username = ?, full_name = ?, last_active_at = UTC_TIMESTAMP() WHERE user_id = ?',
                [mb_substr($username, 0, 64), mb_substr($fullName, 0, 255), $id]);
        }
        $row = $this->get($id);
        return ['is_new' => $ins > 0, 'lang' => (string) ($row['lang'] ?? $lang), 'lang_chosen' => (bool) ($row['lang_chosen'] ?? false)];
    }

    public function exists(int $id): bool
    {
        return $this->db->value('SELECT 1 FROM users WHERE user_id = ?', [$id]) !== null;
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM users WHERE user_id = ?', [$id]);
    }

    public function setLang(int $id, string $lang): void
    {
        $this->db->exec('UPDATE users SET lang = ?, lang_chosen = 1 WHERE user_id = ?', [$lang, $id]);
    }

    public function isFree(int $id): bool
    {
        return ((string) $this->db->value('SELECT plan_type FROM users WHERE user_id = ?', [$id]) ?: 'free') === 'free';
    }

    public function markBlocked(int $id, bool $blocked): void
    {
        $this->db->exec('UPDATE users SET is_blocked = ? WHERE user_id = ?', [$blocked ? 1 : 0, $id]);
    }
}
