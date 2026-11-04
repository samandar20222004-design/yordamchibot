<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\Html;
use PostAssist\Telegram;

/**
 * Postni Telegram so'roviga aylantiradi va yuboradi. Bepul tarifda postning BOSHIGA `🤖 @bot\n\n` nishoni qo'yiladi
 * (Python `apply_post_watermark` bilan bir xil); matn limitga to'lgan bo'lsa nishon QO'YILMAYDI.
 */
final class PostRender
{
    public const TEXT_LIMIT = 4096;
    public const CAPTION_LIMIT = 1024;
    public const TYPES = ['text', 'photo', 'video', 'animation', 'document', 'audio', 'album'];
    public const ALBUM_MAX = 10;
    /** Tayyor reaksiya to'plamlari (o'z reaksiyasini ham yozish mumkin: 1–6 ta emoji). */
    public const REACTION_SETS = ['👍,👎', '❤️,🔥,😂', '👍,❤️,🔥,👏', '🔥,😍,😮,😢,😡'];

    public static function limitFor(string $type): int
    {
        return $type === 'text' ? self::TEXT_LIMIT : self::CAPTION_LIMIT;
    }

    public static function watermark(string $html, string $type, string $botUsername, bool $free): string
    {
        if (!$free || $botUsername === '') {
            return $html;
        }
        $mark = '🤖 @' . $botUsername . "\n\n";
        if (Html::utf16Len(Html::plain($html)) + Html::utf16Len($mark) > self::limitFor($type)) {
            return $html;
        }
        return Html::e($mark) . $html;
    }

    /** Xabardan qoralama: ['type','file_id','text'] yoki null (qo'llanmaydigan tur). */
    public static function draftFromMessage(array $msg): ?array
    {
        $text = isset($msg['text']) ? Html::fromEntities((string) $msg['text'], $msg['entities'] ?? []) : null;
        $caption = Html::fromEntities((string) ($msg['caption'] ?? ''), $msg['caption_entities'] ?? []);
        if ($text !== null) {
            return ['type' => 'text', 'file_id' => null, 'text' => $text];
        }
        if (!empty($msg['photo'])) {
            $p = end($msg['photo']);
            return ['type' => 'photo', 'file_id' => (string) $p['file_id'], 'text' => $caption];
        }
        foreach (['video', 'animation', 'document', 'audio'] as $t) {
            if (!empty($msg[$t]['file_id'])) {
                // GIF: Telegram `animation` bilan birga `document` ham yuboradi — animation birinchi tekshiriladi
                if ($t === 'document' && !empty($msg['animation'])) {
                    continue;
                }
                return ['type' => $t, 'file_id' => (string) $msg[$t]['file_id'], 'text' => $caption];
            }
        }
        return null;
    }

    /** @return array<int, array<int, array<string,string>>> */
    public static function urlRows(?string $btnText, ?string $btnUrl): array
    {
        return ($btnText && $btnUrl) ? [[['text' => $btnText, 'url' => $btnUrl]]] : [];
    }

    /** @return array<int, string> "👍,❤️" -> ['👍','❤️'] */
    public static function reactionList(?string $reactions): array
    {
        if ($reactions === null || trim($reactions) === '') {
            return [];
        }
        return array_values(array_filter(array_map('trim', explode(',', $reactions)), static function ($x) {
            return $x !== '';
        }));
    }

    /**
     * Foydalanuvchi yozgan reaksiyalar: probel yoki vergul bilan ajratilgan 1–6 ta emoji (har biri ≤8 belgi, harf/raqamsiz).
     * Noto'g'ri bo'lsa null.
     */
    public static function parseReactions(string $input): ?string
    {
        $parts = preg_split('/[\s,]+/u', trim($input), -1, PREG_SPLIT_NO_EMPTY) ?: [];
        if (count($parts) < 1 || count($parts) > 6) {
            return null;
        }
        foreach ($parts as $p) {
            if (mb_strlen($p) > 8 || preg_match('/[\p{L}\p{N}<>&"\'`]/u', $p)) {
                return null;
            }
        }
        return implode(',', array_values(array_unique($parts)));
    }

    /** Reaksiya tugmalari qatori (son 0 bo'lsa faqat emoji). Callback: rx:<tartib raqami>. */
    public static function reactionRow(?string $reactions, array $counts = []): array
    {
        $row = [];
        foreach (self::reactionList($reactions) as $i => $e) {
            $n = (int) ($counts[$i] ?? 0);
            $row[] = ['text' => $n > 0 ? $e . ' ' . $n : $e, 'callback_data' => 'rx:' . $i];
        }
        return $row ? [$row] : [];
    }

    /** Kanal postining klaviaturasi: havolali tugma + reaksiyalar. */
    public static function postRows(array $post, array $counts = []): array
    {
        return array_merge(self::urlRows($post['button_text'] ?? null, $post['button_url'] ?? null), self::reactionRow($post['reactions'] ?? null, $counts));
    }

    /** @return array<int, array{0:string,1:string}> albom fayllari [[tur, file_id], ...] */
    public static function albumMedia(array $post): array
    {
        $m = $post['media'] ?? null;
        if (is_string($m)) {
            $m = json_decode($m, true);
        }
        $out = [];
        foreach (is_array($m) ? $m : [] as $it) {
            if (is_array($it) && isset($it[0], $it[1]) && in_array($it[0], ['photo', 'video', 'document', 'audio'], true)) {
                $out[] = [(string) $it[0], (string) $it[1]];
            }
        }
        return array_slice($out, 0, self::ALBUM_MAX);
    }

    /**
     * Albom qismlari birga yuborila oladimi: rasm+video aralash mumkin; hujjat faqat hujjat bilan; audio faqat audio bilan.
     * @param array<int, array{0:string,1:string}> $items
     */
    public static function albumValid(array $items): bool
    {
        if (count($items) < 2) {
            return false;
        }
        $kinds = array_unique(array_map(static function ($it) {
            return $it[0] === 'photo' || $it[0] === 'video' ? 'visual' : $it[0];
        }, $items));
        return count($kinds) === 1;
    }

    /** Postni chatga yuboradi; $extraRows — post tugmalari ostiga qo'shiladigan boshqaruv tugmalari (preview uchun). */
    public static function send(Telegram $tg, int $chatId, array $post, string $botUsername, bool $free, array $extraRows = []): array
    {
        $type = (string) $post['post_type'];
        $html = self::watermark((string) ($post['text'] ?? ''), $type === 'album' ? 'photo' : $type, $botUsername, $free);
        if ($type === 'album') {
            $media = [];
            foreach (self::albumMedia($post) as $i => [$t, $fid]) {
                $item = ['type' => $t, 'media' => $fid];
                if ($i === 0 && $html !== '') {
                    $item['caption'] = $html;
                    $item['parse_mode'] = 'HTML';
                }
                $media[] = $item;
            }
            if (count($media) < 2) {
                return ['ok' => false, 'error_code' => 400, 'description' => 'album: not enough media'];
            }
            return $tg->call('sendMediaGroup', ['chat_id' => $chatId, 'media' => $media]);
        }
        $rows = array_merge(self::postRows($post), $extraRows);
        $markup = $rows ? ['inline_keyboard' => $rows] : null;
        if ($type === 'text') {
            return $tg->call('sendMessage', ['chat_id' => $chatId, 'text' => $html, 'parse_mode' => 'HTML', 'reply_markup' => $markup]);
        }
        $method = ['photo' => 'sendPhoto', 'video' => 'sendVideo', 'animation' => 'sendAnimation',
            'document' => 'sendDocument', 'audio' => 'sendAudio'][$type] ?? null;
        if ($method === null) {
            return ['ok' => false, 'error_code' => 400, 'description' => 'unsupported post type'];
        }
        return $tg->call($method, ['chat_id' => $chatId, $type => (string) $post['file_id'], 'caption' => $html,
            'parse_mode' => 'HTML', 'reply_markup' => $markup]);
    }

    /** Yuborish natijasidan xabar ID'lari (albomda bir nechta). @return array<int, int> */
    public static function messageIds(array $res): array
    {
        $r = $res['result'] ?? null;
        if (!is_array($r)) {
            return [];
        }
        if (isset($r['message_id'])) {
            return [(int) $r['message_id']];
        }
        $ids = [];
        foreach ($r as $m) {
            if (is_array($m) && isset($m['message_id'])) {
                $ids[] = (int) $m['message_id'];
            }
        }
        return $ids;
    }

    /** Telegram xatosidan foydalanuvchiga ko'rsatiladigan sabab kaliti. */
    public static function reasonKey(array $res): string
    {
        $d = strtolower((string) ($res['description'] ?? ''));
        $code = (int) ($res['error_code'] ?? 0);
        if ((strpos($d, 'not enough rights') !== false) || (strpos($d, 'administrator') !== false) || (strpos($d, 'write_forbidden') !== false)
            || (strpos($d, 'kicked') !== false) || (strpos($d, 'not a member') !== false) || $code === 403) {
            return 'reason_not_admin';
        }
        if ((strpos($d, 'chat not found') !== false)) {
            return 'reason_chat_not_found';
        }
        if ($code === 400) {
            return 'reason_format';
        }
        if ($code === 0 || $code >= 500 || $code === 429) {
            return 'reason_network';
        }
        return 'reason_unknown';
    }
}
