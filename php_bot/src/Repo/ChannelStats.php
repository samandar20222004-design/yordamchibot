<?php
declare(strict_types=1);

namespace PostAssist\Repo;

use PostAssist\Db;

/** 📊 Kanal statistikasi: kunlik obunachilar soni (cron), postlar, reaksiyalar, yashirin matn ochilishlari. */
final class ChannelStats
{
    private Db $db;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    /** Bugun hali o'lchanmagan faol kanallar (bir kanal bir necha egada bo'lsa ham bir marta). @return int[] */
    public function pending(string $day, int $limit): array
    {
        return array_map('intval', array_column($this->db->all('SELECT DISTINCT c.channel_id FROM channels c
             LEFT JOIN channel_stats s ON s.channel_id = c.channel_id AND s.day = ? WHERE c.is_active = 1 AND s.channel_id IS NULL LIMIT ' . max(1, $limit), [$day]), 'channel_id'));
    }

    /** $n < 0 — o'lchab bo'lmadi (bugun qayta urinilmaydi). */
    public function save(int $channelId, string $day, int $n): void
    {
        $this->db->exec('INSERT INTO channel_stats (channel_id, day, subscribers) VALUES (?, ?, ?) ON DUPLICATE KEY UPDATE subscribers = VALUES(subscribers)', [$channelId, $day, $n]);
    }

    /** @return array<string,int> kun => obunachilar (faqat muvaffaqiyatli o'lchovlar) */
    public function series(int $channelId, string $fromDay, ?string $toDay = null): array
    {
        $out = [];
        foreach ($this->db->all('SELECT day, subscribers FROM channel_stats WHERE channel_id = ? AND day >= ? AND day <= ? AND subscribers >= 0 ORDER BY day', [$channelId, $fromDay, $toDay ?? '9999-12-31']) as $r) {
            $out[(string) $r['day']] = (int) $r['subscribers'];
        }
        return $out;
    }

    /** Oxirgi o'lchov shu kundan oldingi yoki shu kun (o'sishni hisoblash uchun). */
    public function at(int $channelId, string $day): ?int
    {
        $v = $this->db->value('SELECT subscribers FROM channel_stats WHERE channel_id = ? AND day <= ? AND subscribers >= 0 ORDER BY day DESC LIMIT 1', [$channelId, $day]);
        return $v === null ? null : (int) $v;
    }

    /** Egasining postlari shu kanalda: soni, reaksiyalar, yashirin matn ochilishlari. */
    public function activity(int $ownerId, int $channelId, string $sinceSql): array
    {
        $r = $this->db->one('SELECT COUNT(*) AS posts, COALESCE(SUM(sm.hidden_opens), 0) AS opens, COALESCE(SUM(sm.hidden_locked), 0) AS locked
             FROM sent_messages sm JOIN scheduled_posts sp ON sp.id = sm.post_id WHERE sp.user_id = ? AND sm.chat_id = ? AND sm.created_at >= ?', [$ownerId, $channelId, $sinceSql]) ?? [];
        $votes = (int) $this->db->value('SELECT COUNT(*) FROM reaction_votes v JOIN sent_messages sm ON sm.chat_id = v.chat_id AND sm.message_id = v.message_id
             JOIN scheduled_posts sp ON sp.id = sm.post_id WHERE sp.user_id = ? AND v.chat_id = ? AND sm.created_at >= ?', [$ownerId, $channelId, $sinceSql]);
        $top = $this->db->one('SELECT sp.text, sp.post_type, COUNT(v.user_id) AS n FROM sent_messages sm JOIN scheduled_posts sp ON sp.id = sm.post_id
             JOIN reaction_votes v ON v.chat_id = sm.chat_id AND v.message_id = sm.message_id WHERE sp.user_id = ? AND sm.chat_id = ? AND sm.created_at >= ?
             GROUP BY sm.id, sp.text, sp.post_type ORDER BY n DESC LIMIT 1', [$ownerId, $channelId, $sinceSql]);
        return ['posts' => (int) ($r['posts'] ?? 0), 'votes' => $votes, 'opens' => (int) ($r['opens'] ?? 0), 'locked' => (int) ($r['locked'] ?? 0), 'top' => $top];
    }

    public function cleanup(string $beforeDay): void
    {
        $this->db->exec('DELETE FROM channel_stats WHERE day < ?', [$beforeDay]);
    }
}
