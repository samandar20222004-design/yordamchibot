<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 📰 RSS lentalari: qaysi kanalga, oxirgi ko'rilgan element, keyingi tekshiruv vaqti. */
final class RssFeeds
{
    public const FAILS_LIMIT = 10;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function create(int $userId, int $channelRef, string $url, string $title, ?string $lastItem, DateTimeImmutable $nowUtc, DateTimeImmutable $nextUtc): ?int
    {
        $now = $nowUtc->format('Y-m-d H:i:s');
        $n = $this->db->exec('INSERT IGNORE INTO rss_feeds (user_id, channel_ref, url, url_hash, title, last_item, next_check, last_check, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [$userId, $channelRef, $url, sha1(strtolower($url)), mb_substr($title, 0, 160), $lastItem, $nextUtc->format('Y-m-d H:i:s'), $now, $now]);
        return $n > 0 ? $this->db->lastId() : null;
    }

    public function getOwned(int $userId, int $id): ?array
    {
        return $this->db->one('SELECT f.*, c.title AS channel_title FROM rss_feeds f LEFT JOIN channels c ON c.id = f.channel_ref WHERE f.id = ? AND f.user_id = ?', [$id, $userId]);
    }

    public function listFor(int $userId): array
    {
        return $this->db->all('SELECT f.*, c.title AS channel_title FROM rss_feeds f LEFT JOIN channels c ON c.id = f.channel_ref WHERE f.user_id = ? ORDER BY f.id', [$userId]);
    }

    public function countFor(int $userId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM rss_feeds WHERE user_id = ?', [$userId]);
    }

    public function setActive(int $id, bool $on, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('UPDATE rss_feeds SET active = ?, fails = 0, next_check = ? WHERE id = ?', [$on ? 1 : 0, $nowUtc->format('Y-m-d H:i:s'), $id]);
    }

    public function delete(int $userId, int $id): bool
    {
        return $this->db->exec('DELETE FROM rss_feeds WHERE id = ? AND user_id = ?', [$id, $userId]) > 0;
    }

    /** Tekshirish vaqti kelganlar. */
    public function due(DateTimeImmutable $nowUtc, int $limit): array
    {
        return $this->db->all('SELECT * FROM rss_feeds WHERE active = 1 AND next_check <= ? ORDER BY next_check LIMIT ' . max(1, $limit), [$nowUtc->format('Y-m-d H:i:s')]);
    }

    /** Ikki parallel cron bitta lentani ikki marta olmasin: keyingi vaqt oldindan suriladi. */
    public function claim(array $f, DateTimeImmutable $nextUtc): bool
    {
        return $this->db->exec('UPDATE rss_feeds SET next_check = ? WHERE id = ? AND next_check = ?', [$nextUtc->format('Y-m-d H:i:s'), (int) $f['id'], $f['next_check']]) === 1;
    }

    public function checked(int $id, ?string $lastItem, int $posted, DateTimeImmutable $nowUtc): void
    {
        $this->db->exec('UPDATE rss_feeds SET fails = 0, last_check = ?, last_item = COALESCE(?, last_item), posted = posted + ? WHERE id = ?',
            [$nowUtc->format('Y-m-d H:i:s'), $lastItem, $posted, $id]);
    }

    /** @return int ketma-ket xatolar soni */
    public function failed(int $id, DateTimeImmutable $nowUtc): int
    {
        $this->db->exec('UPDATE rss_feeds SET fails = fails + 1, last_check = ? WHERE id = ?', [$nowUtc->format('Y-m-d H:i:s'), $id]);
        return (int) $this->db->value('SELECT fails FROM rss_feeds WHERE id = ?', [$id]);
    }
}
