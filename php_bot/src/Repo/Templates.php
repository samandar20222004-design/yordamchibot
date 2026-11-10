<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use DateTimeImmutable;
use PostAssist\Db;

/** 📝 Post shablonlari: matn, media, tugma, reaksiya va sozlamalar bilan tayyor qolip. */
final class Templates
{
    /** Shablonga yoziladigan qoralama kalitlari. */
    public const KEYS = ['type', 'file_id', 'text', 'media', 'button_text', 'button_url', 'buttons', 'reactions', 'delete_after', 'options', 'hidden'];
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    public function create(int $userId, string $name, array $draft, DateTimeImmutable $nowUtc): int
    {
        $d = array_intersect_key($draft, array_flip(self::KEYS));
        $this->db->exec('INSERT INTO post_templates (user_id, name, draft, created_at) VALUES (?, ?, ?, ?)',
            [$userId, mb_substr($name, 0, 60), json_encode($d, JSON_UNESCAPED_UNICODE), $nowUtc->format('Y-m-d H:i:s')]);
        return $this->db->lastId();
    }

    public function listFor(int $userId): array
    {
        return $this->db->all('SELECT id, name, used, draft FROM post_templates WHERE user_id = ? ORDER BY used DESC, id DESC', [$userId]);
    }

    public function countFor(int $userId): int
    {
        return (int) $this->db->value('SELECT COUNT(*) FROM post_templates WHERE user_id = ?', [$userId]);
    }

    /** @return array{id:int,name:string,draft:array}|null faqat egasiniki */
    public function getOwned(int $userId, int $id): ?array
    {
        $r = $this->db->one('SELECT * FROM post_templates WHERE id = ? AND user_id = ?', [$id, $userId]);
        if (!$r) {
            return null;
        }
        $d = json_decode((string) $r['draft'], true);
        if (!is_array($d) || !isset($d['type'])) {
            return null;
        }
        return ['id' => (int) $r['id'], 'name' => (string) $r['name'], 'draft' => array_intersect_key($d, array_flip(self::KEYS)) + ['file_id' => null, 'text' => '']];
    }

    public function touch(int $id): void
    {
        $this->db->exec('UPDATE post_templates SET used = used + 1 WHERE id = ?', [$id]);
    }

    public function delete(int $userId, int $id): bool
    {
        return $this->db->exec('DELETE FROM post_templates WHERE id = ? AND user_id = ?', [$id, $userId]) > 0;
    }
}
