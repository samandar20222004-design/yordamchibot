<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 🤖 Autopilot: har kuni belgilangan vaqtda AI kanal mavzusida post yozadi (tekshirib yoki avtomatik). */
final class Autopilots
{
    public const MODES = ['review', 'auto'];
    /** Kechikish chegarasi: cron uzoq to'xtab qolsa, eskirgan kunning posti yozilmaydi. */
    public const LATE_MINUTES = 360;
    public const RECENT = 5;
    public const DRAFT_HOURS = 48;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** @return int|null yangi id; null — shu kanalda allaqachon bor */
    public function create(int $userId, int $channelRef, string $topic, string $style, int $minute, string $mode, ?string $lastRun, DateTimeImmutable $nowUtc): ?int
    {
        $n = $this->db->exec('INSERT IGNORE INTO autopilots (user_id, channel_ref, topic, style, post_time, mode, active, last_run, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)', [$userId, $channelRef, mb_substr($topic, 0, 500), $style, $minute,
            in_array($mode, self::MODES, true) ? $mode : 'review', $lastRun, $nowUtc->format('Y-m-d H:i:s')]);
        return $n > 0 ? $this->db->lastId() : null;
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM autopilots WHERE id = ?', [$id]);
    }

    /** Faqat egasiniki (IDOR himoyasi). */
    public function getOwned(int $userId, int $id): ?array
    {
        return $this->db->one('SELECT * FROM autopilots WHERE id = ? AND user_id = ?', [$id, $userId]);
    }

    public function listFor(int $userId): array
    {
        return $this->db->all('SELECT a.*, c.title AS channel_title FROM autopilots a LEFT JOIN channels c ON c.id = a.channel_ref
            WHERE a.user_id = ? ORDER BY a.id', [$userId]);
    }

    public function countFor(int $userId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM autopilots WHERE user_id = ?', [$userId]);
    }

    public function hasChannel(int $userId, int $channelRef): bool
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM autopilots WHERE user_id = ? AND channel_ref = ?', [$userId, $channelRef]) > 0;
    }

    public function setActive(int $id, bool $on): void
    {
        $this->db->exec('UPDATE autopilots SET active = ? WHERE id = ?', [$on ? 1 : 0, $id]);
    }

    public function setLastRun(int $id, string $day): void
    {
        $this->db->exec('UPDATE autopilots SET last_run = ? WHERE id = ?', [$day, $id]);
    }

    public function delete(int $userId, int $id): bool
    {
        $this->db->exec("UPDATE autopilot_drafts SET status = 'gone' WHERE autopilot_id = ? AND status = 'new'", [$id]);
        return $this->db->exec('DELETE FROM autopilots WHERE id = ? AND user_id = ?', [$id, $userId]) > 0;
    }

    /** Bugun hali ishlamagan faol autopilotlar (vaqti foydalanuvchi mintaqasida tekshiriladi). */
    public function candidates(string $minDay, int $limit = 50): array
    {
        return $this->db->all('SELECT * FROM autopilots WHERE active = 1 AND (last_run IS NULL OR last_run < ?) ORDER BY id LIMIT ' . max(1, $limit), [$minDay]);
    }

    /** Bugungi ishni band qilish: ikki parallel cron bir kunni ikki marta ishlatmaydi. */
    public function claimDay(int $id, string $day): bool
    {
        return $this->db->exec('UPDATE autopilots SET last_run = ? WHERE id = ? AND active = 1 AND (last_run IS NULL OR last_run < ?)', [$day, $id, $day]) === 1;
    }

    /** Oxirgi postlarning birinchi qatorlari (AI takrorlamasligi uchun). @return string[] */
    public static function recent(array $ap): array
    {
        $r = json_decode((string) ($ap['recent'] ?? ''), true);
        return is_array($r) ? array_values(array_filter($r, 'is_string')) : [];
    }

    public function pushRecent(int $id, string $line): void
    {
        $ap = $this->get($id);
        if (!$ap) {
            return;
        }
        $r = self::recent($ap);
        array_unshift($r, mb_substr($line, 0, 120));
        $this->db->exec('UPDATE autopilots SET recent = ? WHERE id = ?', [json_encode(array_slice($r, 0, self::RECENT), JSON_UNESCAPED_UNICODE), $id]);
    }

    // ------------------------------------------------------------- qoralamalar (tekshirib rejimi)

    public function addDraft(array $ap, string $text, DateTimeImmutable $nowUtc): int
    {
        $this->db->exec('INSERT INTO autopilot_drafts (autopilot_id, user_id, channel_ref, text, status, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            [(int) $ap['id'], (int) $ap['user_id'], (int) $ap['channel_ref'], $text, 'new', $nowUtc->format('Y-m-d H:i:s')]);
        return $this->db->lastId();
    }

    /** Faol (ishlatilmagan, eskirmagan) qoralama — faqat egasiniki. */
    public function draft(int $userId, int $id, DateTimeImmutable $nowUtc): ?array
    {
        return $this->db->one("SELECT * FROM autopilot_drafts WHERE id = ? AND user_id = ? AND status = 'new' AND created_at >= ?",
            [$id, $userId, $nowUtc->modify('-' . self::DRAFT_HOURS . ' hours')->format('Y-m-d H:i:s')]);
    }

    /** Qoralamani bir marta ishlatish (ikki marta bosish — bitta post). */
    public function takeDraft(int $id, string $status): bool
    {
        return $this->db->exec("UPDATE autopilot_drafts SET status = ? WHERE id = ? AND status = 'new'", [$status, $id]) === 1;
    }

    public function updateDraft(int $id, string $text): void
    {
        $this->db->exec("UPDATE autopilot_drafts SET text = ? WHERE id = ? AND status = 'new'", [$text, $id]);
    }

    public function cleanup(DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('DELETE FROM autopilot_drafts WHERE created_at < ?', [$nowUtc->modify('-7 days')->format('Y-m-d H:i:s')]);
    }
}
