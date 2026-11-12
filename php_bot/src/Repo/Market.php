<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 💰 Reklama birjasi: e'lonlar, suhbatlar (bot orqali), shikoyatlar. */
final class Market
{
    public const CATEGORIES = ['news', 'tech', 'business', 'education', 'entertainment', 'lifestyle', 'sport', 'shop', 'auto', 'other'];
    public const PAGE = 8;
    public const REQUESTS_PER_DAY = 5;
    public const MAX_MESSAGES = 40;
    public const REPORTS_LIMIT = 3;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** E'lon qo'yish / yangilash (bir kanal — bitta e'lon). */
    public function upsert(int $ownerId, array $ch, int $price, string $currency, string $desc, string $cat, int $subs, DateTimeImmutable $nowUtc, ?string $country = null): int
    {
        $country = $country !== null && \PostAssist\Services\Region::valid($country) ? $country : null;
        $now = $nowUtc->format('Y-m-d H:i:s');
        $cat = in_array($cat, self::CATEGORIES, true) ? $cat : 'other';
        $row = $this->db->one('SELECT id, status FROM market_listings WHERE channel_id = ?', [(int) $ch['channel_id']]);
        if ($row) {
            // bloklangan e'lonni egasi o'zi qayta ocha olmaydi
            $this->db->exec("UPDATE market_listings SET owner_id = ?, title = ?, username = ?, category = ?, price = ?, currency = ?, description = ?, subscribers = ?,
                 country = COALESCE(country, ?), status = CASE WHEN status = 'banned' THEN 'banned' ELSE 'active' END, updated_at = ? WHERE id = ?",
                [$ownerId, mb_substr((string) $ch['title'], 0, 255), (string) $ch['username'], $cat, $price, $currency, $desc, $subs, $country, $now, (int) $row['id']]);
            return (int) $row['id'];
        }
        $this->db->exec('INSERT INTO market_listings (owner_id, channel_id, title, username, category, price, currency, description, subscribers, country, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [$ownerId, (int) $ch['channel_id'], mb_substr((string) $ch['title'], 0, 255), (string) $ch['username'],
            $cat, $price, $currency, $desc, $subs, $country, $now, $now]);
        return $this->db->lastId();
    }

    public function get(int $id): ?array
    {
        return $this->db->one('SELECT * FROM market_listings WHERE id = ?', [$id]);
    }

    /**
     * Katalog: faol e'lonlar (egasi ban qilinmagan).
     * Tartib: ko'ruvchining o'z davlati → yaqin davlatlar → Global → boshqalar; har guruh ichida obunachi bo'yicha.
     * $only — faqat shu davlat (boshqa davlat uchun reklama qidirish); $q — kanal nomi yoki @username bo'yicha qidiruv.
     * @return array{rows:array, total:int}
     */
    public function catalog(?string $cat, int $page, string $viewer = '', ?string $only = null, string $q = ''): array
    {
        $where = "l.status = 'active' AND u.market_banned = 0";
        $args = [];
        if ($cat !== null) {
            $where .= ' AND l.category = ?';
            $args[] = $cat;
        }
        if ($only !== null && $only !== '') {
            $where .= $only === \PostAssist\Services\Region::GLOBAL ? " AND (l.country IS NULL OR l.country = 'ZZ')" : ' AND l.country = ?';
            if ($only !== \PostAssist\Services\Region::GLOBAL) {
                $args[] = $only;
            }
        }
        $q = trim(ltrim(trim($q), '@'));
        if ($q !== '') {
            $like = '%' . addcslashes(mb_substr($q, 0, 64), '%_\\') . '%';
            $where .= ' AND (l.title LIKE ? OR l.username LIKE ? OR l.description LIKE ?)';
            array_push($args, $like, $like, $like);
        }
        $near = \PostAssist\Services\Region::near($viewer);
        $order = 'CASE WHEN l.country = ? THEN 0' . ($near ? ' WHEN l.country IN (' . implode(',', array_fill(0, count($near), '?')) . ') THEN 1' : '')
            . " WHEN l.country IS NULL OR l.country = 'ZZ' THEN 2 ELSE 3 END";
        $orderArgs = array_merge([$viewer], $near);
        $total = (int) $this->db->value("SELECT COUNT(*) FROM market_listings l JOIN users u ON u.user_id = l.owner_id WHERE {$where}", $args);
        $rows = $this->db->all("SELECT l.* FROM market_listings l JOIN users u ON u.user_id = l.owner_id WHERE {$where}
             ORDER BY {$order}, l.subscribers DESC, l.id DESC LIMIT " . self::PAGE . ' OFFSET ' . max(0, $page) * self::PAGE, array_merge($args, $orderArgs));
        return ['rows' => $rows, 'total' => $total];
    }

    /** Faol e'lonlar bor davlatlar: kod => soni (Global — «ZZ»). @return array<string,int> */
    public function countries(): array
    {
        $out = [];
        foreach ($this->db->all("SELECT COALESCE(l.country, 'ZZ') AS c, COUNT(*) AS n FROM market_listings l JOIN users u ON u.user_id = l.owner_id
             WHERE l.status = 'active' AND u.market_banned = 0 GROUP BY COALESCE(l.country, 'ZZ') ORDER BY n DESC") as $r) {
            $out[(string) $r['c']] = (int) $r['n'];
        }
        return $out;
    }

    public function setCountry(int $id, int $ownerId, string $country): bool
    {
        return \PostAssist\Services\Region::valid($country)
            && $this->db->exec('UPDATE market_listings SET country = ? WHERE id = ? AND owner_id = ?', [$country, $id, $ownerId]) > 0;
    }

    /** Eski e'lonlar (davlati yo'q): egasining davlatini yozadi. @param callable $countryOf fn(int $ownerId): string */
    public function backfillCountries(callable $countryOf): int
    {
        $n = 0;
        foreach ($this->db->all('SELECT id, owner_id FROM market_listings WHERE country IS NULL LIMIT 1000') as $r) {
            $this->db->exec('UPDATE market_listings SET country = ? WHERE id = ?', [$countryOf((int) $r['owner_id']), (int) $r['id']]);
            $n++;
        }
        return $n;
    }

    public function mine(int $ownerId): array
    {
        return $this->db->all('SELECT * FROM market_listings WHERE owner_id = ? ORDER BY id', [$ownerId]);
    }

    public function setStatus(int $id, string $status): bool
    {
        return $this->db->exec('UPDATE market_listings SET status = ? WHERE id = ?', [$status, $id]) > 0;
    }

    public function delete(int $ownerId, int $id): bool
    {
        return $this->db->exec("DELETE FROM market_listings WHERE id = ? AND owner_id = ? AND status <> 'banned'", [$id, $ownerId]) > 0;
    }

    public function setSubscribers(int $id, int $n): void
    {
        $this->db->exec('UPDATE market_listings SET subscribers = ? WHERE id = ?', [$n, $id]);
    }

    // ------------------------------------------------------------------ suhbatlar

    public function thread(int $id): ?array
    {
        return $this->db->one('SELECT t.*, l.title, l.username FROM market_threads t JOIN market_listings l ON l.id = t.listing_id WHERE t.id = ?', [$id]);
    }

    public function threadFor(int $listingId, int $buyerId): ?array
    {
        return $this->db->one('SELECT * FROM market_threads WHERE listing_id = ? AND buyer_id = ?', [$listingId, $buyerId]);
    }

    public function newThreadsToday(int $buyerId, string $sinceSql): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM market_threads WHERE buyer_id = ? AND created_at >= ?', [$buyerId, $sinceSql]);
    }

    public function openThread(array $listing, int $buyerId, DateTimeImmutable $nowUtc): int
    {
        $now = $nowUtc->format('Y-m-d H:i:s');
        $this->db->exec('INSERT IGNORE INTO market_threads (listing_id, buyer_id, owner_id, created_at, last_at) VALUES (?, ?, ?, ?, ?)',
            [(int) $listing['id'], $buyerId, (int) $listing['owner_id'], $now, $now]);
        return (int) $this->db->value('SELECT id FROM market_threads WHERE listing_id = ? AND buyer_id = ?', [(int) $listing['id'], $buyerId]);
    }

    /** @return string ok | full | dup */
    public function addMessage(int $threadId, int $senderId, string $body, string $hash, DateTimeImmutable $nowUtc): string
    {
        $t = $this->db->one('SELECT messages FROM market_threads WHERE id = ?', [$threadId]);
        if ((int) ($t['messages'] ?? 0) >= self::MAX_MESSAGES) {
            return 'full';
        }
        $last = $this->db->value('SELECT norm_hash FROM market_messages WHERE thread_id = ? AND sender_id = ? ORDER BY id DESC LIMIT 1', [$threadId, $senderId]);
        if ($last === $hash) {
            return 'dup';
        }
        $now = $nowUtc->format('Y-m-d H:i:s');
        $this->db->exec('INSERT INTO market_messages (thread_id, sender_id, body, norm_hash, created_at) VALUES (?, ?, ?, ?, ?)', [$threadId, $senderId, $body, $hash, $now]);
        $this->db->exec('UPDATE market_threads SET messages = messages + 1, last_at = ? WHERE id = ?', [$now, $threadId]);
        return 'ok';
    }

    public function messages(int $threadId, int $limit = 10): array
    {
        return array_reverse($this->db->all('SELECT * FROM market_messages WHERE thread_id = ? ORDER BY id DESC LIMIT ' . max(1, $limit), [$threadId]));
    }

    public function threadsOf(int $userId, int $limit = 15): array
    {
        return $this->db->all('SELECT t.*, l.title, l.username FROM market_threads t JOIN market_listings l ON l.id = t.listing_id
             WHERE (t.buyer_id = ? OR t.owner_id = ?) AND t.messages > 0 ORDER BY t.last_at DESC LIMIT ' . max(1, $limit), [$userId, $userId]);
    }

    public function blockThread(int $id): void
    {
        $this->db->exec("UPDATE market_threads SET status = 'blocked' WHERE id = ?", [$id]);
    }

    // ------------------------------------------------------------------ shikoyatlar

    /** @return int|null shikoyatlar soni (yangi bo'lsa) yoki null (oldin shikoyat qilgan) */
    public function report(string $kind, int $targetId, int $reporterId, DateTimeImmutable $nowUtc): ?int
    {
        if ($this->db->exec('INSERT IGNORE INTO market_reports (kind, target_id, reporter_id, created_at) VALUES (?, ?, ?, ?)',
            [$kind, $targetId, $reporterId, $nowUtc->format('Y-m-d H:i:s')]) === 0) {
            return null;
        }
        $n = (int) $this->db->value('SELECT COUNT(*) FROM market_reports WHERE kind = ? AND target_id = ?', [$kind, $targetId]);
        if ($kind === 'listing') {
            $this->db->exec('UPDATE market_listings SET reports = ? WHERE id = ?', [$n, $targetId]);
        }
        return $n;
    }

    public function reportCount(string $kind, int $targetId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM market_reports WHERE kind = ? AND target_id = ?', [$kind, $targetId]);
    }

    public function banUser(int $userId, bool $ban): bool
    {
        return $this->db->exec('UPDATE users SET market_banned = ? WHERE user_id = ?', [$ban ? 1 : 0, $userId]) > 0;
    }

    public function isBanned(int $userId): bool
    {
        return (int) $this->db->value('SELECT market_banned FROM users WHERE user_id = ?', [$userId]) === 1;
    }
}
