<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/**
 * 🔗 Manba havolalari: `https://t.me/<bot>?start=s_<kod>` — kim qaysi reklama/hamkor havolasidan keldi
 * (Python `repositories/tracked_links_repository.py` bilan bir xil qoidalar):
 *  - kod `[a-z0-9_]`, 2–24 belgi; bitta foydalanuvchi + bitta havola = bitta qator;
 *  - `is_new` — shu havola bilan ro'yxatdan o'tgan (birinchi tegish; keyin boshqa havola bossa ham o'zgarmaydi);
 *  - `clicks` — har bir /start (takrorlar bilan); `first_post_at` — birinchi post saqlanganda bir marta.
 */
final class TrackedLinks
{
    public const CODE_RE = '/^[a-z0-9_]{2,24}$/';
    public const PREFIX = 's_';
    public const TITLE_MAX = 80;
    public const MAX_LINKS = 500;

    /** Statistika — alohida guruhlangan jadval (ONLY_FULL_GROUP_BY yoqilgan MySQL/MariaDB'da ham ishlaydi). */
    private const STATS_JOIN = "LEFT JOIN (SELECT v.link_id,
            COUNT(*) AS visitors,
            SUM(v.is_new) AS new_users,
            SUM(CASE WHEN v.is_new = 1 AND (v.first_post_at IS NOT NULL OR EXISTS (SELECT 1 FROM channels c WHERE c.user_id = v.user_id)) THEN 1 ELSE 0 END) AS with_channel,
            SUM(CASE WHEN v.is_new = 1 AND v.first_post_at IS NOT NULL THEN 1 ELSE 0 END) AS posted,
            SUM(CASE WHEN v.is_new = 1 AND (EXISTS (SELECT 1 FROM payments p WHERE p.user_id = v.user_id)
                OR EXISTS (SELECT 1 FROM users u WHERE u.user_id = v.user_id AND u.plan_type IN ('pro', 'ultra'))) THEN 1 ELSE 0 END) AS paid
        FROM tracked_link_visits v GROUP BY v.link_id) s ON s.link_id = l.id";
    private const STATS_COLS = 'COALESCE(s.visitors, 0) AS visitors, COALESCE(s.new_users, 0) AS new_users, COALESCE(s.with_channel, 0) AS with_channel,
        COALESCE(s.posted, 0) AS posted, COALESCE(s.paid, 0) AS paid';

    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public static function normalizeCode(string $raw): ?string
    {
        $code = (string) preg_replace('/[\s\-]+/u', '_', strtolower(trim($raw)));
        return preg_match(self::CODE_RE, $code) ? $code : null;
    }

    public static function codeFromPayload(string $arg): ?string
    {
        if (strpos($arg, self::PREFIX) !== 0) {
            return null;
        }
        $code = substr($arg, strlen(self::PREFIX));
        return preg_match(self::CODE_RE, $code) ? $code : null;
    }

    /** @return array{ok:bool, error?:string, link?:array} error: bad_code|bad_title|exists|limit|owner_unknown */
    public function create(string $rawCode, string $title, ?int $ownerId, ?int $createdBy, DateTimeImmutable $nowUtc): array
    {
        $code = self::normalizeCode($rawCode);
        if ($code === null) {
            return ['ok' => false, 'error' => 'bad_code'];
        }
        $title = mb_substr(trim((string) preg_replace('/\s+/u', ' ', $title)), 0, self::TITLE_MAX);
        if ($title === '') {
            return ['ok' => false, 'error' => 'bad_title'];
        }
        if ($ownerId !== null && $this->db->value('SELECT 1 FROM users WHERE user_id = ?', [$ownerId]) === null) {
            return ['ok' => false, 'error' => 'owner_unknown'];
        }
        if ((int) $this->db->value('SELECT COUNT(*) FROM tracked_links') >= self::MAX_LINKS) {
            return ['ok' => false, 'error' => 'limit'];
        }
        $ins = $this->db->exec('INSERT IGNORE INTO tracked_links (code, title, owner_id, created_by, created_at) VALUES (?, ?, ?, ?, ?)',
            [$code, $title, $ownerId, $createdBy, $nowUtc->format('Y-m-d H:i:s')]);
        if ($ins === 0) {
            return ['ok' => false, 'error' => 'exists'];
        }
        return ['ok' => true, 'link' => $this->get($code)];
    }

    /** Havola + statistika. */
    public function get(string $rawCode): ?array
    {
        $code = self::normalizeCode($rawCode);
        if ($code === null) {
            return null;
        }
        return $this->db->one('SELECT l.*, ' . self::STATS_COLS . ' FROM tracked_links l ' . self::STATS_JOIN . ' WHERE l.code = ?', [$code]);
    }

    public function listAll(?int $ownerId = null, int $limit = 50): array
    {
        $where = $ownerId !== null ? 'WHERE l.owner_id = ?' : '';
        return $this->db->all('SELECT l.*, ' . self::STATS_COLS . ' FROM tracked_links l ' . self::STATS_JOIN
            . " {$where} ORDER BY l.created_at DESC, l.id DESC LIMIT " . max(1, min(200, $limit)), $ownerId !== null ? [$ownerId] : []);
    }

    /** Havola orqali kelganlar (oxirgilari birinchi). */
    public function visitors(int $linkId, int $limit = 20): array
    {
        return $this->db->all("SELECT v.user_id, v.is_new, v.first_at, v.first_post_at, u.username, u.full_name, u.plan_type,
                EXISTS (SELECT 1 FROM channels c WHERE c.user_id = v.user_id) AS has_channel,
                EXISTS (SELECT 1 FROM payments p WHERE p.user_id = v.user_id) AS has_paid
             FROM tracked_link_visits v LEFT JOIN users u ON u.user_id = v.user_id
             WHERE v.link_id = ? ORDER BY v.first_at DESC, v.user_id DESC LIMIT " . max(1, min(50, $limit)), [$linkId]);
    }

    /** Foydalanuvchi qaysi havolalar orqali kelgan. */
    public function sourcesOf(int $userId): array
    {
        return $this->db->all('SELECT l.code, l.title, v.is_new, v.first_at FROM tracked_link_visits v JOIN tracked_links l ON l.id = v.link_id
             WHERE v.user_id = ? ORDER BY v.first_at', [$userId]);
    }

    public function setActive(string $rawCode, bool $active): bool
    {
        $code = self::normalizeCode($rawCode);
        return $code !== null && $this->db->exec('UPDATE tracked_links SET is_active = ? WHERE code = ?', [$active ? 1 : 0, $code]) > 0;
    }

    /** Faol havola (start'da egasini aniqlash uchun). */
    public function active(string $code): ?array
    {
        return $this->db->one('SELECT * FROM tracked_links WHERE code = ? AND is_active = 1', [$code]);
    }

    /** /start s_<kod>: bosishni va tashrifni yozadi. is_new — foydalanuvchi aynan hozir ro'yxatdan o'tdi (birinchi tegish). */
    public function recordVisit(int $linkId, int $userId, bool $isNew, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('UPDATE tracked_links SET clicks = clicks + 1 WHERE id = ?', [$linkId]);
        if ($isNew && $this->db->value('SELECT 1 FROM tracked_link_visits WHERE user_id = ? AND is_new = 1', [$userId]) !== null) {
            $isNew = false;
        }
        $this->db->exec('INSERT IGNORE INTO tracked_link_visits (link_id, user_id, is_new, first_at) VALUES (?, ?, ?, ?)',
            [$linkId, $userId, $isNew ? 1 : 0, $nowUtc->format('Y-m-d H:i:s')]);
    }

    /** Birinchi post saqlandi — havola orqali kelgan yangi foydalanuvchi uchun bir marta yoziladi. */
    public function markFirstPost(int $userId, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('UPDATE tracked_link_visits SET first_post_at = ? WHERE user_id = ? AND is_new = 1 AND first_post_at IS NULL',
            [$nowUtc->format('Y-m-d H:i:s'), $userId]);
    }
}
