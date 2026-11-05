<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 📅 AI kontent-reja: mavzu bo'yicha g'oyalar ro'yxati (har biridan bir bosishda post). */
final class ContentPlans
{
    public const ITEMS = 7;
    public const KEEP = 5;
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** @param string[] $ideas */
    public function create(int $userId, string $topic, array $ideas, DateTimeImmutable $nowUtc): int
    {
        $items = array_map(static function (string $t): array {
            return ['t' => $t, 'done' => false];
        }, array_values($ideas));
        $this->db->exec('INSERT INTO content_plans (user_id, topic, items, created_at) VALUES (?, ?, ?, ?)',
            [$userId, mb_substr($topic, 0, 500), json_encode($items, JSON_UNESCAPED_UNICODE), $nowUtc->format('Y-m-d H:i:s')]);
        $id = $this->db->lastId();
        // eski rejalar: faqat oxirgi KEEP tasi saqlanadi
        $old = $this->db->all('SELECT id FROM content_plans WHERE user_id = ? ORDER BY id DESC LIMIT 100 OFFSET ' . self::KEEP, [$userId]);
        foreach ($old as $o) {
            $this->db->exec('DELETE FROM content_plans WHERE id = ?', [(int) $o['id']]);
        }
        return $id;
    }

    /** @return array{id:int, topic:string, items:array<int,array{t:string,done:bool}>}|null faqat egasiniki */
    public function get(int $userId, int $id): ?array
    {
        $row = $this->db->one('SELECT * FROM content_plans WHERE id = ? AND user_id = ?', [$id, $userId]);
        return $row ? self::decode($row) : null;
    }

    public function latest(int $userId): ?array
    {
        $row = $this->db->one('SELECT * FROM content_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1', [$userId]);
        return $row ? self::decode($row) : null;
    }

    public function markDone(int $userId, int $id, int $n): void
    {
        $p = $this->get($userId, $id);
        if ($p === null || !isset($p['items'][$n])) {
            return;
        }
        $p['items'][$n]['done'] = true;
        $this->db->exec('UPDATE content_plans SET items = ? WHERE id = ? AND user_id = ?',
            [json_encode($p['items'], JSON_UNESCAPED_UNICODE), $id, $userId]);
    }

    private static function decode(array $row): array
    {
        $items = json_decode((string) $row['items'], true);
        return ['id' => (int) $row['id'], 'topic' => (string) $row['topic'], 'items' => is_array($items) ? array_values($items) : []];
    }

    /**
     * AI javobidan g'oyalar: har qator — bitta g'oya; raqam, belgi va qo'shtirnoqlar olib tashlanadi, takrorlar tashlanadi.
     * @return string[]
     */
    public static function parseIdeas(string $plain, int $max = self::ITEMS): array
    {
        $out = [];
        $seen = [];
        foreach (preg_split('/\R/u', $plain) ?: [] as $line) {
            $line = trim((string) preg_replace('/^\s*(?:\d{1,2}\s*[.)\-:]|[-•*–—✅▪️🔹]+)\s*/u', '', $line));
            $line = trim($line, " \t\"'«»“”*");
            $len = mb_strlen($line);
            if ($len < 5 || $len > 200) {
                continue;
            }
            $key = mb_strtolower($line);
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $out[] = $line;
            if (count($out) >= $max) {
                break;
            }
        }
        return $out;
    }
}
