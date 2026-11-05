<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;
use PostAssist\Services\Plans;

/**
 * Karta orqali to'lov cheklari. Qaror (tasdiq/rad) BIR marta: `status = 'pending'` shartli atomik UPDATE — ikki admin
 * bir vaqtda bossa ham tarif bir marta beriladi. Tasdiq, to'lov yozuvi (`payments`, charge_id `card_<id>` UNIQUE) va tarif
 * berish bitta tranzaksiyada.
 */
final class Receipts
{
    public const MAX_PENDING = 3;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function pendingCount(int $userId): int
    {
        return (int) $this->db->value("SELECT COUNT(*) FROM payment_receipts WHERE user_id = ? AND status = 'pending'", [$userId]);
    }

    /** Shu fayl avval ham yuborilganmi (Telegram file_unique_id): oldingi cheklar. */
    public function duplicates(?string $uniqueId, int $exceptId = 0): array
    {
        if ($uniqueId === null || $uniqueId === '') {
            return [];
        }
        return $this->db->all('SELECT id, user_id, status FROM payment_receipts WHERE file_unique_id = ? AND id <> ? ORDER BY id DESC LIMIT 3', [$uniqueId, $exceptId]);
    }

    public function create(int $userId, array $plan, int $amount, string $mediaType, string $fileId, ?string $uniqueId, DateTimeImmutable $nowUtc): int
    {
        $this->db->exec('INSERT INTO payment_receipts (user_id, plan_key, tier, days, amount_uzs, media_type, file_id, file_unique_id, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [$userId, $plan['key'], $plan['tier'], $plan['days'], $amount, $mediaType, $fileId,
            $uniqueId !== null ? mb_substr($uniqueId, 0, 64) : null, $nowUtc->format('Y-m-d H:i:s')]);
        return $this->db->lastId();
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM payment_receipts WHERE id = ?', [$id]);
    }

    /** Karta bilan to'lagan mijozmi (UZ tasdig'idan qayta o'tishi shart emas). */
    public function hasPaid(int $userId): bool
    {
        return $this->db->value("SELECT 1 FROM payments WHERE user_id = ? AND provider IN ('card', 'payme') LIMIT 1", [$userId]) !== null;
    }

    /**
     * Qaror. @return array{status:string, receipt?:array, tier?:string, expires?:string, kept?:bool}
     *   status: ok | rejected | already | not_found | grant_failed
     */
    public function decide(int $id, bool $approve, int $adminId, DateTimeImmutable $nowUtc): array
    {
        $now = $nowUtc->format('Y-m-d H:i:s');
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $r = $this->db->one('SELECT * FROM payment_receipts WHERE id = ? FOR UPDATE', [$id]);
            if (!$r) {
                $pdo->rollBack();
                return ['status' => 'not_found'];
            }
            if ($r['status'] !== 'pending') {
                $pdo->rollBack();
                return ['status' => 'already', 'receipt' => $r];
            }
            $this->db->exec('UPDATE payment_receipts SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?', [$approve ? 'approved' : 'rejected', $adminId, $now, $id]);
            if (!$approve) {
                $pdo->commit();
                return ['status' => 'rejected', 'receipt' => $r];
            }
            $this->db->exec("INSERT IGNORE INTO payments (user_id, provider, amount, currency, payload, charge_id, plan_key, tier, days, created_at)
                 VALUES (?, 'card', ?, 'UZS', ?, ?, ?, ?, ?, ?)", [(int) $r['user_id'], (int) $r['amount_uzs'], 'receipt:' . $id, 'card_' . $id, $r['plan_key'], $r['tier'], (int) $r['days'], $now]);
            $g = Plans::grantInTx($this->db, (int) $r['user_id'], (string) $r['tier'], (int) $r['days'], $nowUtc);
            if (!$g['ok']) {
                $pdo->rollBack(); // chek 'pending' qoladi — admin qayta urinishi mumkin
                return ['status' => 'grant_failed', 'receipt' => $r];
            }
            $pdo->commit();
            return ['status' => 'ok', 'receipt' => $r, 'tier' => $g['tier'], 'expires' => $g['expires'], 'kept' => $g['kept']];
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** @return array{count:int, uzs:int} */
    public function totalsSince(string $utcSql): array
    {
        $r = $this->db->one("SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS s FROM payments WHERE provider = 'card' AND created_at >= ?", [$utcSql]);
        return ['count' => (int) ($r['n'] ?? 0), 'uzs' => (int) ($r['s'] ?? 0)];
    }

    public function pendingList(int $limit = 10): array
    {
        return $this->db->all("SELECT * FROM payment_receipts WHERE status = 'pending' ORDER BY id LIMIT " . max(1, $limit));
    }
}
