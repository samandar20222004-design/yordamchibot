<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

/**
 * AI so'rovlari hisobi. So'rovdan OLDIN joy band qilinadi (atomik, foydalanuvchi qatori qulflanadi — parallel bosishda ham
 * limitdan oshmaydi); AI xato bersa — qaytariladi. Avval kunlik limit, u tugasa — ballar (1 so'rov = 1 ball).
 */
final class AiUsage
{
    private Db $db;
    private Credits $credits;

    public function __construct(Db $db, Credits $credits)
    {
        $this->db = $db;
        $this->credits = $credits;
    }

    public function usedOn(int $userId, string $day): int
    {
        return (int) $this->db->value('SELECT used FROM ai_usage WHERE user_id = ? AND day = ?', [$userId, $day]);
    }

    /**
     * Daqiqalik cheklov (atomik, 60 soniyalik oyna). true — ruxsat; false — juda tez.
     * Jadval hali yo'q bo'lsa (setup.php ishga tushmagan) — ruxsat beriladi (bot to'xtamaydi).
     */
    public function rateAllow(int $userId, int $perMinute, string $nowSql): bool
    {
        if ($perMinute <= 0) {
            return true;
        }
        try {
            // MySQL ON DUPLICATE KEY UPDATE chapdan o'ngga: cnt eski win_start bilan hisoblanadi
            $this->db->exec('INSERT INTO ai_rate (user_id, win_start, cnt) VALUES (?, ?, 1)
                 ON DUPLICATE KEY UPDATE cnt = IF(win_start <= ? - INTERVAL 60 SECOND, 1, cnt + 1),
                 win_start = IF(win_start <= ? - INTERVAL 60 SECOND, ?, win_start)', [$userId, $nowSql, $nowSql, $nowSql, $nowSql]);
            return (int) $this->db->value('SELECT cnt FROM ai_rate WHERE user_id = ?', [$userId]) <= $perMinute;
        } catch (\Throwable $e) {
            return true;
        }
    }

    /** Daqiqalik oyna qachon ochiladi (soniya). */
    public function rateWait(int $userId, string $nowSql): int
    {
        try {
            $start = (string) $this->db->value('SELECT win_start FROM ai_rate WHERE user_id = ?', [$userId]);
        } catch (\Throwable $e) {
            return 0;
        }
        return $start === '' ? 0 : max(1, 60 - (strtotime($nowSql . ' UTC') - strtotime($start . ' UTC')));
    }

    /**
     * @param int $limit kunlik limit (0 = cheksiz)
     * @param int $perMinute daqiqalik cheklov (0 = cheksiz)
     * @return string|null daily | credit | unlimited | rate (juda tez — hech narsa band qilinmadi), yoki null (limit ham, ball ham tugagan)
     */
    public function reserve(int $userId, int $limit, string $day, string $nowSql, int $perMinute = 0): ?string
    {
        if (!$this->rateAllow($userId, $perMinute, $nowSql)) {
            return 'rate';
        }
        if ($limit <= 0) {
            return 'unlimited';
        }
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $this->db->value('SELECT user_id FROM users WHERE user_id = ? FOR UPDATE', [$userId]);
            $this->db->exec('INSERT IGNORE INTO ai_usage (user_id, day, used) VALUES (?, ?, 0)', [$userId, $day]);
            $used = (int) $this->db->value('SELECT used FROM ai_usage WHERE user_id = ? AND day = ? FOR UPDATE', [$userId, $day]);
            $src = null;
            if ($used < $limit) {
                $this->db->exec('UPDATE ai_usage SET used = used + 1 WHERE user_id = ? AND day = ?', [$userId, $day]);
                $src = 'daily';
            } elseif ((int) $this->db->value('SELECT ai_credits FROM users WHERE user_id = ?', [$userId]) > 0) {
                $this->credits->addInTx($userId, -1, 'ai', null, $nowSql);
                $src = 'credit';
            }
            $pdo->commit();
            return $src;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** AI javob bermadi — band qilingan joy qaytadi (o'sha manbaga). */
    public function refund(int $userId, string $source, string $day, string $nowSql): void
    {
        if ($source === 'daily') {
            $this->db->exec('UPDATE ai_usage SET used = GREATEST(used - 1, 0) WHERE user_id = ? AND day = ?', [$userId, $day]);
        } elseif ($source === 'credit') {
            $this->credits->add($userId, 1, 'ai_refund', null, new \DateTimeImmutable($nowSql, new \DateTimeZone('UTC')));
        }
    }

    public function cleanup(string $beforeDay): void
    {
        $this->db->exec('DELETE FROM ai_usage WHERE day < ?', [$beforeDay]);
        try {
            $this->db->exec('DELETE FROM ai_rate WHERE win_start < ?', [$beforeDay]);
        } catch (\Throwable $e) {
        }
    }
}
