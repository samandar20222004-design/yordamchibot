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
    public const TYPES = ['text', 'photo', 'video', 'animation', 'document', 'audio', 'album', 'poll'];
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
        return array_merge(self::urlRows($post['button_text'] ?? null, $post['button_url'] ?? null), self::hiddenRow($post['hidden_text'] ?? null),
            self::reactionRow($post['reactions'] ?? null, $counts), self::commentsRow($post));
    }

    /** 💬 Izohlar: bot chatiga havola (`?start=c_<post>`), yonida izohlar soni. */
    public static function commentsRow(array $post): array
    {
        $label = trim((string) ($post['comments_label'] ?? ''));
        $bot = (string) ($post['bot'] ?? '');
        if ($label === '' || $bot === '') {
            return [];
        }
        $pid = (int) ($post['post_id'] ?? $post['id'] ?? 0);
        $n = (int) ($post['comments_count'] ?? 0);
        return [[['text' => $label . ($n > 0 ? ' (' . $n . ')' : ''), 'url' => 'https://t.me/' . $bot . '?start=c_' . $pid]]];
    }

    /** Post sozlamalari: ovozsiz, havola ko'rinishisiz, pin, nusxa himoyasi. */
    public const OPTIONS = ['silent', 'nopreview', 'pin', 'protect', 'comments', 'multi'];

    /** @param string|array|null $opts @return string[] */
    public static function options($opts): array
    {
        $list = is_array($opts) ? $opts : explode(',', (string) $opts);
        return array_values(array_intersect(self::OPTIONS, array_map('trim', $list)));
    }

    /** @param string|array|null $opts */
    public static function optionsString($opts): ?string
    {
        $o = self::options($opts);
        return $o ? implode(',', $o) : null;
    }

    /** 🔒 Yashirin matn (faqat obunachilarga): JSON {"l": tugma yorlig'i, "t": matn}. */
    public static function hiddenJson(string $label, string $text): string
    {
        return (string) json_encode(['l' => $label, 't' => $text], JSON_UNESCAPED_UNICODE);
    }

    /** @return array{l:string,t:string}|null */
    public static function hidden(?string $json): ?array
    {
        $h = $json !== null && $json !== '' ? json_decode($json, true) : null;
        return is_array($h) && trim((string) ($h['t'] ?? '')) !== '' ? ['l' => (string) ($h['l'] ?? '🔒'), 't' => (string) $h['t']] : null;
    }

    public static function hiddenRow(?string $json): array
    {
        $h = self::hidden($json);
        return $h ? [[['text' => mb_substr($h['l'], 0, 40), 'callback_data' => 'hd']]] : [];
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
        $post['bot'] = $post['bot'] ?? $botUsername;
        $opts = self::options($post['options'] ?? null);
        $flags = ['_raw' => true]; // ko'rinish qatlami post matniga tegmaydi
        if (in_array('silent', $opts, true)) {
            $flags['disable_notification'] = true;
        }
        if (in_array('protect', $opts, true)) {
            $flags['protect_content'] = true;
        }
        $html = self::watermark((string) ($post['text'] ?? ''), $type === 'album' ? 'photo' : $type, $botUsername, $free);
        if ($type === 'poll') {
            return $tg->call('sendPoll', self::pollParams($chatId, $post, $botUsername, $free, in_array('multi', $opts, true)) + $flags);
        }
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
            return $tg->call('sendMediaGroup', ['chat_id' => $chatId, 'media' => $media] + $flags);
        }
        $rows = array_merge(self::postRows($post), $extraRows);
        $markup = $rows ? ['inline_keyboard' => $rows] : null;
        if ($type === 'text') {
            return $tg->call('sendMessage', ['chat_id' => $chatId, 'text' => $html, 'parse_mode' => 'HTML', 'reply_markup' => $markup] + $flags
                + (in_array('nopreview', $opts, true) ? ['link_preview_options' => ['is_disabled' => true]] : []));
        }
        $method = ['photo' => 'sendPhoto', 'video' => 'sendVideo', 'animation' => 'sendAnimation',
            'document' => 'sendDocument', 'audio' => 'sendAudio'][$type] ?? null;
        if ($method === null) {
            return ['ok' => false, 'error_code' => 400, 'description' => 'unsupported post type'];
        }
        return $tg->call($method, ['chat_id' => $chatId, $type => (string) $post['file_id'], 'caption' => $html,
            'parse_mode' => 'HTML', 'reply_markup' => $markup] + $flags);
    }

    /** So'rovnoma ma'lumoti (media ustunidan). @return array{options:string[], quiz:?int} */
    public static function pollData(array $post): array
    {
        $m = $post['media'] ?? null;
        if (is_string($m)) {
            $m = json_decode($m, true);
        }
        $opts = is_array($m) && is_array($m['options'] ?? null) ? array_values(array_filter(array_map('strval', $m['options']), 'strlen')) : [];
        $quiz = is_array($m) && isset($m['quiz']) && is_int($m['quiz']) && isset($opts[$m['quiz']]) ? $m['quiz'] : null;
        return ['options' => array_slice($opts, 0, 10), 'quiz' => $quiz];
    }

    /** sendPoll parametrlari: kanal so'rovnomasi anonim; bepul tarifda savol oxiriga nishon (sig'sa). */
    public static function pollParams(int $chatId, array $post, string $botUsername, bool $free, bool $multi): array
    {
        $d = self::pollData($post);
        $q = trim(Html::plain((string) ($post['text'] ?? '')));
        $mark = ' · 🤖 @' . $botUsername;
        if ($free && $botUsername !== '' && mb_strlen($q . $mark) <= 300) {
            $q .= $mark;
        }
        $p = ['chat_id' => $chatId, 'question' => mb_substr($q, 0, 300), 'is_anonymous' => true,
            'options' => array_map(static function (string $o): array {
                return ['text' => $o];
            }, $d['options'])];
        if ($d['quiz'] !== null) {
            $p['type'] = 'quiz';
            $p['correct_option_id'] = $d['quiz'];
        } elseif ($multi) {
            $p['allows_multiple_answers'] = true;
        }
        return $p;
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
