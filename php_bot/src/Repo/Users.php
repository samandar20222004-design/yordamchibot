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

    public function setTimezone(int $id, ?string $tz): void
    {
        $this->db->exec('UPDATE users SET timezone = ? WHERE user_id = ?', [$tz, $id]);
    }

    /** @return array{plan_type:string, subscription_expires_at:?string}|null */
    public function plan(int $id): ?array
    {
        return $this->db->one('SELECT plan_type, subscription_expires_at FROM users WHERE user_id = ?', [$id]);
    }

    public function findByUsername(string $username): ?int
    {
        $u = ltrim(trim($username), '@');
        if (!preg_match('/^[A-Za-z0-9_]{3,64}$/', $u)) {
            return null;
        }
        $v = $this->db->value('SELECT user_id FROM users WHERE username = ? ORDER BY last_active_at DESC LIMIT 1', [$u]);
        return $v === null ? null : (int) $v;
    }

    /** Muddati o'tgan pro/ultra foydalanuvchilar (cron tarifni free ga tushiradi). */
    public function expiredPaid(string $nowSql, int $limit = 200): array
    {
        return $this->db->all("SELECT user_id, plan_type, lang FROM users WHERE plan_type IN ('pro', 'ultra')
             AND (subscription_expires_at IS NULL OR subscription_expires_at <= ?) LIMIT " . max(1, $limit), [$nowSql]);
    }

    /** Faqat hali ham muddati o'tgan bo'lsa (shu orada uzaytirilmagan) free ga tushiradi. */
    public function downgradeIfExpired(int $id, string $planType, string $nowSql): bool
    {
        return $this->db->exec("UPDATE users SET plan_type = 'free', plan_reminder_for = NULL WHERE user_id = ? AND plan_type = ?
             AND (subscription_expires_at IS NULL OR subscription_expires_at <= ?)", [$id, $planType, $nowSql]) > 0;
    }

    /** Muddati 24 soat ichida tugaydigan, hali eslatilmaganlar. */
    public function expiringSoon(string $nowSql, string $untilSql, int $limit = 200): array
    {
        return $this->db->all("SELECT user_id, plan_type, subscription_expires_at, lang FROM users WHERE plan_type IN ('pro', 'ultra')
             AND subscription_expires_at > ? AND subscription_expires_at <= ?
             AND (plan_reminder_for IS NULL OR plan_reminder_for <> subscription_expires_at) LIMIT " . max(1, $limit), [$nowSql, $untilSql]);
    }

    /** Eslatma bir marta: kim birinchi belgilasa o'sha yuboradi. */
    public function claimReminder(int $id, string $expiresSql): bool
    {
        return $this->db->exec('UPDATE users SET plan_reminder_for = subscription_expires_at WHERE user_id = ? AND subscription_expires_at = ?
             AND (plan_reminder_for IS NULL OR plan_reminder_for <> subscription_expires_at)', [$id, $expiresSql]) > 0;
    }

    public function markBlocked(int $id, bool $blocked): void
    {
        $this->db->exec('UPDATE users SET is_blocked = ? WHERE user_id = ?', [$blocked ? 1 : 0, $id]);
    }
}
