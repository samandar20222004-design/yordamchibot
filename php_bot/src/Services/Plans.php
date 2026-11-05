<?php
declare(strict_types=1);

namespace PostAssist\Services;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\Config;
use PostAssist\Db;

/**
 * Tariflar (Python `config.TARIFF_CATALOG` / `TIER_LIMITS` va `services/plan_sql.py` bilan bir xil):
 *  - kalitlar: PRO `1m 3m 6m 1y`, ULTRA `u1m u3m u6m u1y`; kunlar 30/90/180/365;
 *  - Stars narxi — xalqaro narx (O'zbekiston asosidan x1,7, 5 ga yaxlitlangan): PRO 195/510/910/1650, ULTRA 470/1180/2260/4180;
 *  - tarif berish: `enterprise` hech qachon o'zgarmaydi; faol ULTRA PRO olsa ham ULTRA qoladi (muddat qo'shiladi);
 *    muddat = max(joriy muddat, hozir) + kunlar (qolgan kunlar yo'qolmaydi).
 */
final class Plans
{
    public const FREE = 'free';
    public const PRO = 'pro';
    public const ULTRA = 'ultra';
    public const ENTERPRISE = 'enterprise';
    public const PERIODS = [['1m', 1, 30], ['3m', 3, 90], ['6m', 6, 180], ['1y', 12, 365]];
    public const DEFAULT_STARS = [
        '1m' => 195, '3m' => 510, '6m' => 910, '1y' => 1650,
        'u1m' => 470, 'u3m' => 1180, 'u6m' => 2260, 'u1y' => 4180,
    ];
    public const DEFAULT_LIMITS = [
        'free' => ['channels' => 3, 'queue' => 40],
        'pro' => ['channels' => 10, 'queue' => 300],
        'ultra' => ['channels' => 30, 'queue' => 900],
    ];
    /** So'mdagi narxlar (karta orqali; Python PAYMENT_PRICE_*_UZS / ULTRA_PRICE_*_UZS). */
    public const DEFAULT_UZS = [
        '1m' => 29000, '3m' => 75000, '6m' => 135000, '1y' => 245000,
        'u1m' => 69000, 'u3m' => 175000, 'u6m' => 335000, 'u1y' => 620000,
    ];
    /** Kunlik AI so'rovlari (Python FREE_DAILY_AI / PRO_DAILY_AI / ULTRA_DAILY_AI). */
    public const DEFAULT_AI = ['free' => 5, 'pro' => 40, 'ultra' => 100];
    public const NAMES = ['free' => 'FREE', 'pro' => 'PRO', 'ultra' => 'ULTRA', 'enterprise' => 'ENTERPRISE'];
    public const MAX_GRANT_DAYS = 3650;

    /** @return array<string, array{key:string,tier:string,period:string,months:int,days:int,stars:int}> */
    public static function catalog(?Config $c = null): array
    {
        $prices = self::DEFAULT_STARS;
        $over = $c !== null ? $c->get('stars_prices') : null;
        if (is_array($over)) {
            foreach ($over as $k => $v) {
                if (isset($prices[$k]) && (int) $v > 0) {
                    $prices[$k] = (int) $v;
                }
            }
        }
        $out = [];
        foreach ([self::PRO, self::ULTRA] as $tier) {
            foreach (self::PERIODS as [$period, $months, $days]) {
                $key = ($tier === self::ULTRA ? 'u' : '') . $period;
                $out[$key] = ['key' => $key, 'tier' => $tier, 'period' => $period, 'months' => $months, 'days' => $days, 'stars' => $prices[$key]];
            }
        }
        return $out;
    }

    /** @return array<string, int> kalit => so'm (config.php `uzs_prices` bilan o'zgaradi) */
    public static function uzs(?Config $c = null): array
    {
        $prices = self::DEFAULT_UZS;
        $over = $c !== null ? $c->get('uzs_prices') : null;
        if (is_array($over)) {
            foreach ($over as $k => $v) {
                if (isset($prices[$k]) && (int) $v >= 1000) {
                    $prices[$k] = (int) $v;
                }
            }
        }
        return $prices;
    }

    /** 29000 -> «29 000». */
    public static function fmtUzs(int $n): string
    {
        return number_format($n, 0, '', ' ');
    }

    /** Uzoq tarifning 1 oylik narxga nisbatan tejami (butun foiz, Python `plan_discount_percent` bilan bir xil). */
    public static function discount(int $total, int $monthly, int $months): int
    {
        if ($total <= 0 || $monthly <= 0 || $months <= 0) {
            return 0;
        }
        return max(0, (int) round((1 - $total / ($monthly * $months)) * 100));
    }

    /** @return array{channels:int, queue:int} 0 = cheksiz */
    public static function limits(string $tier, ?Config $c = null): array
    {
        if ($tier === self::ENTERPRISE) {
            return ['channels' => 0, 'queue' => 0];
        }
        $lim = self::DEFAULT_LIMITS[$tier] ?? self::DEFAULT_LIMITS['free'];
        if ($c !== null && $tier === self::FREE) {
            // 1-bosqich sozlamalari (config.php) saqlanadi
            $lim = ['channels' => $c->int('free_max_channels') ?: $lim['channels'], 'queue' => $c->int('free_max_queued') ?: $lim['queue']];
        }
        $over = $c !== null ? $c->get('tier_limits') : null;
        if (is_array($over) && isset($over[$tier]) && is_array($over[$tier])) {
            $lim = ['channels' => (int) ($over[$tier]['channels'] ?? $lim['channels']), 'queue' => (int) ($over[$tier]['queue'] ?? $lim['queue'])];
        }
        return $lim;
    }

    /** Kunlik AI limiti (0 = cheksiz). config.php `ai_daily` => ['free' => 5, ...] bilan o'zgartiriladi. */
    public static function aiDaily(string $tier, ?Config $c = null): int
    {
        if ($tier === self::ENTERPRISE) {
            return 0;
        }
        $v = self::DEFAULT_AI[$tier] ?? self::DEFAULT_AI['free'];
        $over = $c !== null ? $c->get('ai_daily') : null;
        if (is_array($over) && isset($over[$tier]) && (int) $over[$tier] >= 0) {
            $v = (int) $over[$tier];
        }
        return max(0, $v);
    }

    /** Amaldagi tarif: muddati o'tgan pro/ultra = free; enterprise muddatsiz. */
    public static function effective(?string $planType, ?string $expiresSql, DateTimeImmutable $nowUtc): string
    {
        $p = (string) $planType;
        if ($p === self::ENTERPRISE) {
            return self::ENTERPRISE;
        }
        if (($p === self::PRO || $p === self::ULTRA) && $expiresSql !== null && $expiresSql !== ''
            && new DateTimeImmutable($expiresSql, new DateTimeZone('UTC')) > $nowUtc) {
            return $p;
        }
        return self::FREE;
    }

    /**
     * Tarif berish (ochiq tranzaksiya ICHIDA chaqiriladi: foydalanuvchi qatori qulflanadi).
     * @return array{ok:bool, tier?:string, expires?:string, kept?:bool, error?:string}
     */
    public static function grantInTx(Db $db, int $userId, string $tier, int $days, DateTimeImmutable $nowUtc): array
    {
        if (($tier !== self::PRO && $tier !== self::ULTRA) || $days <= 0 || $days > self::MAX_GRANT_DAYS) {
            return ['ok' => false, 'error' => 'bad_plan'];
        }
        $row = $db->one('SELECT plan_type, subscription_expires_at FROM users WHERE user_id = ? FOR UPDATE', [$userId]);
        if (!$row) {
            return ['ok' => false, 'error' => 'no_user'];
        }
        if ((string) $row['plan_type'] === self::ENTERPRISE) {
            return ['ok' => true, 'tier' => self::ENTERPRISE, 'expires' => (string) ($row['subscription_expires_at'] ?? ''), 'kept' => true];
        }
        $current = self::effective($row['plan_type'], $row['subscription_expires_at'], $nowUtc);
        $newTier = ($tier === self::PRO && $current === self::ULTRA) ? self::ULTRA : $tier;
        $base = $nowUtc;
        if ($current !== self::FREE && $row['subscription_expires_at']) {
            $exp = new DateTimeImmutable((string) $row['subscription_expires_at'], new DateTimeZone('UTC'));
            if ($exp > $base) {
                $base = $exp;
            }
        }
        $expires = $base->modify('+' . $days . ' days')->format('Y-m-d H:i:s');
        $db->exec('UPDATE users SET plan_type = ?, subscription_expires_at = ?, plan_reminder_for = NULL WHERE user_id = ?', [$newTier, $expires, $userId]);
        return ['ok' => true, 'tier' => $newTier, 'expires' => $expires, 'kept' => $newTier !== $tier];
    }

    /** Alohida tranzaksiyada tarif berish (admin /grant_pro). */
    public static function grant(Db $db, int $userId, string $tier, int $days, DateTimeImmutable $nowUtc): array
    {
        $pdo = $db->pdo();
        $pdo->beginTransaction();
        try {
            $r = self::grantInTx($db, $userId, $tier, $days, $nowUtc);
            if ($r['ok']) {
                $pdo->commit();
            } else {
                $pdo->rollBack();
            }
            return $r;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }
}
