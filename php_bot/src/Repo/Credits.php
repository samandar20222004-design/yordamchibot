<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/**
 * Ballar (AI kreditlari) va referal mukofoti. Qoida (Python `users_repository.referral_reward_for`):
 * taklif qilingan do'st BIRINCHI postini saqlaganda taklif qiluvchiga: 1–3-do'st uchun +3, keyingilari uchun +1.
 * Har bir do'st uchun faqat bir marta (users.referral_rewarded_at), parallel postlarda ham.
 */
final class Credits
{
    public const TOP_FRIENDS = 3;
    public const TOP_REWARD = 3;
    public const BASE_REWARD = 1;

    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function rewardFor(int $friendNumber): int
    {
        return max(1, $friendNumber) <= self::TOP_FRIENDS ? self::TOP_REWARD : self::BASE_REWARD;
    }

    public function balance(int $userId): int
    {
        return (int) $this->db->value('SELECT ai_credits FROM users WHERE user_id = ?', [$userId]);
    }

    /** Ochiq tranzaksiya ICHIDA: ball qo'shadi (manfiy = ayiradi, 0 dan pastga tushmaydi) va tarixga yozadi. */
    public function addInTx(int $userId, int $amount, string $op, ?string $ref, string $nowSql): ?int
    {
        $cur = $this->db->value('SELECT ai_credits FROM users WHERE user_id = ? FOR UPDATE', [$userId]);
        if ($cur === null) {
            return null;
        }
        $new = max(0, (int) $cur + $amount);
        $this->db->exec('UPDATE users SET ai_credits = ? WHERE user_id = ?', [$new, $userId]);
        $this->db->exec('INSERT INTO credits_ledger (user_id, amount, balance_after, operation_type, reference_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            [$userId, $new - (int) $cur, $new, mb_substr($op, 0, 32), $ref !== null ? mb_substr($ref, 0, 64) : null, $nowSql]);
        return $new;
    }

    public function add(int $userId, int $amount, string $op, ?string $ref, DateTimeImmutable $nowUtc): ?int
    {
        return $this->tx(function () use ($userId, $amount, $op, $ref, $nowUtc) {
            return $this->addInTx($userId, $amount, $op, $ref, $nowUtc->format('Y-m-d H:i:s'));
        });
    }

    /**
     * Do'st birinchi postini saqladi — taklif qiluvchiga mukofot (faqat bir marta).
     * @return array{referrer:int, reward:int, friend:int, balance:int}|null
     */
    public function rewardReferral(int $userId, DateTimeImmutable $nowUtc): ?array
    {
        $now = $nowUtc->format('Y-m-d H:i:s');
        // Tez yo'l: mukofot allaqachon berilgan yoki taklif qiluvchi yo'q — tranzaksiyasiz chiqamiz
        if ($this->db->value('SELECT 1 FROM users WHERE user_id = ? AND referrer_id IS NOT NULL AND referral_rewarded_at IS NULL', [$userId]) === null) {
            return null;
        }
        return $this->tx(function () use ($userId, $now) {
            $claimed = $this->db->exec('UPDATE users SET referral_rewarded_at = ? WHERE user_id = ? AND referrer_id IS NOT NULL AND referral_rewarded_at IS NULL',
                [$now, $userId]);
            if ($claimed === 0) {
                return null; // parallel so'rov allaqachon oldi
            }
            $ref = (int) $this->db->value('SELECT referrer_id FROM users WHERE user_id = ?', [$userId]);
            if ($ref <= 0 || $ref === $userId || $this->db->value('SELECT 1 FROM users WHERE user_id = ? FOR UPDATE', [$ref]) === null) {
                return null;
            }
            $n = (int) $this->db->value('SELECT COUNT(*) FROM users WHERE referrer_id = ? AND referral_rewarded_at IS NOT NULL FOR UPDATE', [$ref]);
            $reward = self::rewardFor($n);
            $balance = (int) $this->addInTx($ref, $reward, 'referral', 'friend:' . $userId, $now);
            return ['referrer' => $ref, 'reward' => $reward, 'friend' => $n, 'balance' => $balance];
        });
    }

    /** @return array{invited:int, active:int, earned:int} */
    public function referralStats(int $userId): array
    {
        return [
            'invited' => (int) $this->db->value('SELECT COUNT(*) FROM users WHERE referrer_id = ?', [$userId]),
            'active' => (int) $this->db->value('SELECT COUNT(*) FROM users WHERE referrer_id = ? AND referral_rewarded_at IS NOT NULL', [$userId]),
            'earned' => (int) $this->db->value("SELECT COALESCE(SUM(amount), 0) FROM credits_ledger WHERE user_id = ? AND operation_type = 'referral'", [$userId]),
        ];
    }

    /** @return mixed */
    private function tx(callable $fn)
    {
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $r = $fn();
            $pdo->commit();
            return $r;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }
}
