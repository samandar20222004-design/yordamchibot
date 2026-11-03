<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;
use PostAssist\Services\Plans;

/**
 * Promo-kodlar (Python `PromoService` qoidalari):
 *  - kod normallashtiriladi (ko'rinmas belgi, qo'shtirnoq, probel olinadi; katta harf);
 *  - faqat pro/ultra beradi; bir foydalanuvchi bir kodni bir marta; muddat, faollik va maks. foydalanish tekshiriladi;
 *  - noto'g'ri urinishlar: 10 daqiqada 5 ta — keyin vaqtincha to'siladi (kod taxmin qilishga qarshi).
 */
final class Promos
{
    public const CODE_RE = '/^[A-Z0-9_-]{3,32}$/';
    public const MAX_FAILS = 5;
    public const FAIL_WINDOW_SEC = 600;

    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function normalize(string $raw): ?string
    {
        $s = (string) preg_replace('/[\x{200B}-\x{200F}\x{2060}\x{FEFF}\x{00AD}]/u', '', $raw);
        $s = (string) preg_replace('/[\s\'"`«»‘’“”„]+/u', '', $s);
        $s = strtoupper($s);
        return preg_match(self::CODE_RE, $s) ? $s : null;
    }

    /** @return array{ok:bool, error?:string, code?:string} */
    public function create(string $raw, string $tier, int $days, ?int $maxUses, ?int $createdBy, DateTimeImmutable $nowUtc): array
    {
        $code = self::normalize($raw);
        if ($code === null) {
            return ['ok' => false, 'error' => 'bad_code'];
        }
        if (($tier !== Plans::PRO && $tier !== Plans::ULTRA) || $days <= 0 || $days > Plans::MAX_GRANT_DAYS) {
            return ['ok' => false, 'error' => 'bad_plan'];
        }
        if ($maxUses !== null && ($maxUses <= 0 || $maxUses > 1000000)) {
            return ['ok' => false, 'error' => 'bad_max'];
        }
        $ins = $this->db->exec('INSERT IGNORE INTO promo_codes (code, plan_type, duration_days, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            [$code, $tier, $days, $maxUses, $createdBy, $nowUtc->format('Y-m-d H:i:s')]);
        return $ins > 0 ? ['ok' => true, 'code' => $code] : ['ok' => false, 'error' => 'exists'];
    }

    public function get(string $raw): ?array
    {
        $code = self::normalize($raw);
        return $code === null ? null : $this->db->one('SELECT * FROM promo_codes WHERE code = ?', [$code]);
    }

    public function listAll(int $limit = 50): array
    {
        return $this->db->all('SELECT * FROM promo_codes ORDER BY created_at DESC, id DESC LIMIT ' . max(1, min(200, $limit)));
    }

    public function recentRedemptions(int $promoId, int $limit = 15): array
    {
        return $this->db->all('SELECT r.user_id, r.redeemed_at, u.username, u.full_name FROM promo_redemptions r LEFT JOIN users u ON u.user_id = r.user_id
             WHERE r.promo_id = ? ORDER BY r.redeemed_at DESC LIMIT ' . max(1, min(50, $limit)), [$promoId]);
    }

    public function setActive(string $raw, bool $active): bool
    {
        $code = self::normalize($raw);
        return $code !== null && $this->db->exec('UPDATE promo_codes SET is_active = ? WHERE code = ?', [$active ? 1 : 0, $code]) > 0;
    }

    /** Kodni butunlay o'chiradi (tarixi bilan). Foydalanuvchilar olgan tarif saqlanadi. */
    public function delete(string $raw): bool
    {
        $row = $this->get($raw);
        if (!$row) {
            return false;
        }
        $this->db->exec('DELETE FROM promo_redemptions WHERE promo_id = ?', [(int) $row['id']]);
        return $this->db->exec('DELETE FROM promo_codes WHERE id = ?', [(int) $row['id']]) > 0;
    }

    /**
     * Foydalanuvchi kodni kiritdi.
     * @return array{status:string, tier?:string, expires?:string, days?:int, kept?:bool}
     *   status: ok | rate_limited | not_found | inactive | expired | exhausted | already | bad_plan
     */
    public function redeem(int $userId, string $raw, DateTimeImmutable $nowUtc): array
    {
        $now = $nowUtc->format('Y-m-d H:i:s');
        $since = $nowUtc->modify('-' . self::FAIL_WINDOW_SEC . ' seconds')->format('Y-m-d H:i:s');
        $fails = (int) $this->db->value('SELECT COUNT(*) FROM promo_attempts WHERE user_id = ? AND created_at > ?', [$userId, $since]);
        if ($fails >= self::MAX_FAILS) {
            return ['status' => 'rate_limited'];
        }
        $code = self::normalize($raw);
        if ($code === null) {
            $this->fail($userId, $now);
            return ['status' => 'not_found'];
        }
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $p = $this->db->one('SELECT * FROM promo_codes WHERE code = ? FOR UPDATE', [$code]);
            $status = null;
            if (!$p) {
                $status = 'not_found';
            } elseif ((int) $p['is_active'] !== 1) {
                $status = 'inactive';
            } elseif ($p['expires_at'] !== null && (string) $p['expires_at'] <= $now) {
                $status = 'expired';
            } elseif ($p['plan_type'] !== Plans::PRO && $p['plan_type'] !== Plans::ULTRA) {
                $status = 'bad_plan';
            } elseif ($p['max_uses'] !== null && (int) $p['current_uses'] >= (int) $p['max_uses']) {
                $status = 'exhausted';
            } elseif ($this->db->exec('INSERT IGNORE INTO promo_redemptions (promo_id, user_id, redeemed_at) VALUES (?, ?, ?)', [(int) $p['id'], $userId, $now]) === 0) {
                $status = 'already';
            }
            if ($status !== null) {
                $pdo->rollBack();
                if ($status === 'not_found') {
                    $this->fail($userId, $now);
                }
                return ['status' => $status];
            }
            $this->db->exec('UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?', [(int) $p['id']]);
            $g = Plans::grantInTx($this->db, $userId, (string) $p['plan_type'], (int) $p['duration_days'], $nowUtc);
            if (!$g['ok']) {
                $pdo->rollBack();
                return ['status' => 'bad_plan'];
            }
            $pdo->commit();
            return ['status' => 'ok', 'tier' => $g['tier'], 'expires' => $g['expires'], 'days' => (int) $p['duration_days'], 'kept' => $g['kept']];
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    private function fail(int $userId, string $now): void
    {
        $this->db->exec('INSERT INTO promo_attempts (user_id, created_at) VALUES (?, ?)', [$userId, $now]);
    }

    public function cleanupAttempts(string $beforeUtcSql): void
    {
        $this->db->exec('DELETE FROM promo_attempts WHERE created_at < ?', [$beforeUtcSql]);
    }
}
