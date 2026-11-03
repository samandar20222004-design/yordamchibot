<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Config;
use PostAssist\Db;
use PostAssist\Services\Plans;

/**
 * Telegram Stars to'lovlari. Qoidalar (Python `handlers/subscription.py` bilan bir xil):
 *  - payload `sub_stars_<kalit>_<user_id>`, valyuta `XTR`, summa katalog narxiga TENG bo'lishi shart;
 *  - payload ichidagi ID to'lovchining o'zi (boshqa birovga to'lab bo'lmaydi);
 *  - `telegram_payment_charge_id` UNIQUE — bir to'lov ikki marta tarif bermaydi.
 */
final class Payments
{
    public const PAYLOAD_RE = '/^sub_stars_(u?(?:1m|3m|6m|1y))_(\d{1,20})$/';

    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function payload(string $planKey, int $userId): string
    {
        return 'sub_stars_' . $planKey . '_' . $userId;
    }

    /**
     * To'lovdan oldingi tekshiruv (pre_checkout_query) va to'lovdan keyingi tekshiruv uchun umumiy.
     * @return array{ok:bool, plan?:array, error?:string}
     */
    public static function validate(?Config $config, string $payload, string $currency, int $amount, int $payerId): array
    {
        if (!preg_match(self::PAYLOAD_RE, $payload, $m)) {
            return ['ok' => false, 'error' => 'bad_payload'];
        }
        if ((int) $m[2] !== $payerId) {
            return ['ok' => false, 'error' => 'wrong_user'];
        }
        $plan = Plans::catalog($config)[$m[1]] ?? null;
        if ($plan === null) {
            return ['ok' => false, 'error' => 'bad_payload'];
        }
        if ($currency !== 'XTR' || $amount !== $plan['stars']) {
            return ['ok' => false, 'error' => 'bad_amount'];
        }
        return ['ok' => true, 'plan' => $plan];
    }

    /**
     * Muvaffaqiyatli to'lovni yozadi va tarif beradi — bitta tranzaksiyada.
     * @return array{status:string, tier?:string, expires?:string, kept?:bool, plan?:array, error?:string}
     *   status: ok | duplicate | invalid
     */
    public function processStars(?Config $config, int $userId, array $sp, DateTimeImmutable $nowUtc): array
    {
        $payload = (string) ($sp['invoice_payload'] ?? '');
        $currency = (string) ($sp['currency'] ?? '');
        $amount = (int) ($sp['total_amount'] ?? 0);
        $charge = trim((string) ($sp['telegram_payment_charge_id'] ?? ''));
        $v = self::validate($config, $payload, $currency, $amount, $userId);
        if (!$v['ok'] || $charge === '') {
            return ['status' => 'invalid', 'error' => $v['error'] ?? 'no_charge'];
        }
        $plan = $v['plan'];
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $ins = $this->db->exec(
                "INSERT IGNORE INTO payments (user_id, provider, amount, currency, payload, charge_id, plan_key, tier, days, created_at)
                 VALUES (?, 'stars', ?, ?, ?, ?, ?, ?, ?, ?)",
                [$userId, $amount, $currency, $payload, mb_substr($charge, 0, 128), $plan['key'], $plan['tier'], $plan['days'], $nowUtc->format('Y-m-d H:i:s')]
            );
            if ($ins === 0) {
                $pdo->rollBack();
                return ['status' => 'duplicate', 'plan' => $plan];
            }
            $g = Plans::grantInTx($this->db, $userId, $plan['tier'], $plan['days'], $nowUtc);
            if (!$g['ok']) {
                $pdo->rollBack();
                return ['status' => 'invalid', 'error' => $g['error'] ?? 'grant'];
            }
            $pdo->commit();
            return ['status' => 'ok', 'tier' => $g['tier'], 'expires' => $g['expires'], 'kept' => $g['kept'], 'plan' => $plan];
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** @return array{count:int, stars:int} berilgan vaqtdan beri */
    public function totalsSince(string $utcSql): array
    {
        $r = $this->db->one("SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS s FROM payments WHERE currency = 'XTR' AND created_at >= ?", [$utcSql]);
        return ['count' => (int) ($r['n'] ?? 0), 'stars' => (int) ($r['s'] ?? 0)];
    }
}
