<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/**
 * 👥 Jamoa: ULTRA egasi + 2 yordamchi (Python ULTRA_TEAM_SEATS). Yordamchi bir martalik havola bilan qo'shiladi
 * (bazada token XESHI; 7 kun; bir marta). Yordamchi «ish joyi»ni tanlaydi: o'zi yoki egasi — egasining ish joyida
 * kanal, navbat, limit va AI egasiniki, post egasi nomidan (created_by — yordamchi). Ruxsatlar: create, send_now, delete, ai.
 */
final class Team
{
    public const PERMS = ['create', 'send_now', 'delete', 'ai'];
    public const PRESETS = ['all' => ['create', 'send_now', 'delete', 'ai'], 'editor' => ['create', 'ai'], 'viewer' => []];
    public const INVITE_DAYS = 7;
    public const INVITES_PER_DAY = 10;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function hash(string $token): string
    {
        return hash('sha256', $token);
    }

    public function members(int $ownerId): array
    {
        return $this->db->all('SELECT m.member_id, m.perms, m.created_at, u.username, u.full_name FROM team_members m LEFT JOIN users u ON u.user_id = m.member_id
             WHERE m.owner_id = ? ORDER BY m.created_at', [$ownerId]);
    }

    public function count(int $ownerId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM team_members WHERE owner_id = ?', [$ownerId]);
    }

    /** Foydalanuvchi qaysi egalarning yordamchisi. */
    public function ownersOf(int $memberId): array
    {
        return $this->db->all('SELECT m.owner_id, m.perms, u.username, u.full_name FROM team_members m LEFT JOIN users u ON u.user_id = m.owner_id
             WHERE m.member_id = ? ORDER BY m.created_at', [$memberId]);
    }

    /** @return array<int, string>|null ruxsatlar yoki null (a'zo emas) */
    public function perms(int $ownerId, int $memberId): ?array
    {
        $p = $this->db->value('SELECT perms FROM team_members WHERE owner_id = ? AND member_id = ?', [$ownerId, $memberId]);
        return $p === null ? null : array_values(array_intersect(self::PERMS, explode(',', (string) $p)));
    }

    /** @return array{token?:string, error?:string} token (bir marta ko'rsatiladi) yoki xato: preset | full | limit */
    public function createInvite(int $ownerId, string $preset, int $seats, DateTimeImmutable $nowUtc): array
    {
        if (!isset(self::PRESETS[$preset])) {
            return ['error' => 'preset'];
        }
        if ($this->count($ownerId) >= $seats) {
            return ['error' => 'full'];
        }
        $since = $nowUtc->modify('-1 day')->format('Y-m-d H:i:s');
        if ((int) $this->db->value('SELECT COUNT(*) FROM team_invites WHERE owner_id = ? AND created_at > ?', [$ownerId, $since]) >= self::INVITES_PER_DAY) {
            return ['error' => 'limit'];
        }
        $token = bin2hex(random_bytes(12));
        $this->db->exec('INSERT INTO team_invites (owner_id, token_hash, perms, expires_at, created_at) VALUES (?, ?, ?, ?, ?)', [$ownerId, self::hash($token),
            implode(',', self::PRESETS[$preset]), $nowUtc->modify('+' . self::INVITE_DAYS . ' days')->format('Y-m-d H:i:s'), $nowUtc->format('Y-m-d H:i:s')]);
        return ['token' => $token];
    }

    /**
     * Taklifni qabul qilish (atomik: token qulflanadi, bir marta).
     * @param callable $seatsOf fn(int $ownerId): int — egasining hozirgi o'rinlari (tarif tushgan bo'lsa 0)
     * @return array{status:string, owner?:int, perms?:array} status: ok | already | invalid | self | full | no_seats
     */
    public function accept(string $token, int $memberId, callable $seatsOf, DateTimeImmutable $nowUtc): array
    {
        if (!preg_match('/^[a-f0-9]{24}$/', $token)) {
            return ['status' => 'invalid'];
        }
        $now = $nowUtc->format('Y-m-d H:i:s');
        $pdo = $this->db->pdo();
        $pdo->beginTransaction();
        try {
            $inv = $this->db->one('SELECT * FROM team_invites WHERE token_hash = ? FOR UPDATE', [self::hash($token)]);
            if (!$inv || $inv['used_by'] !== null || (string) $inv['expires_at'] <= $now) {
                $pdo->rollBack();
                return ['status' => 'invalid'];
            }
            $owner = (int) $inv['owner_id'];
            if ($owner === $memberId) {
                $pdo->rollBack();
                return ['status' => 'self'];
            }
            $this->db->value('SELECT user_id FROM users WHERE user_id = ? FOR UPDATE', [$owner]);
            if ($this->perms($owner, $memberId) !== null) {
                $pdo->rollBack();
                return ['status' => 'already', 'owner' => $owner];
            }
            $seats = $seatsOf($owner);
            if ($seats <= 0) {
                $pdo->rollBack();
                return ['status' => 'no_seats'];
            }
            if ($this->count($owner) >= $seats) {
                $pdo->rollBack();
                return ['status' => 'full'];
            }
            $this->db->exec('INSERT INTO team_members (owner_id, member_id, perms, created_at) VALUES (?, ?, ?, ?)', [$owner, $memberId, (string) $inv['perms'], $now]);
            $this->db->exec('UPDATE team_invites SET used_by = ?, used_at = ? WHERE id = ?', [$memberId, $now, (int) $inv['id']]);
            $this->db->exec('UPDATE users SET workspace_owner = ? WHERE user_id = ?', [$owner, $memberId]);
            $pdo->commit();
            return ['status' => 'ok', 'owner' => $owner, 'perms' => array_values(array_filter(explode(',', (string) $inv['perms'])))];
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    public function remove(int $ownerId, int $memberId): bool
    {
        $ok = $this->db->exec('DELETE FROM team_members WHERE owner_id = ? AND member_id = ?', [$ownerId, $memberId]) > 0;
        $this->db->exec('UPDATE users SET workspace_owner = NULL WHERE user_id = ? AND workspace_owner = ?', [$memberId, $ownerId]);
        return $ok;
    }

    public function workspace(int $userId): ?int
    {
        $v = $this->db->value('SELECT workspace_owner FROM users WHERE user_id = ?', [$userId]);
        return $v === null ? null : (int) $v;
    }

    public function setWorkspace(int $userId, ?int $ownerId): void
    {
        $this->db->exec('UPDATE users SET workspace_owner = ? WHERE user_id = ?', [$ownerId, $userId]);
    }
}
