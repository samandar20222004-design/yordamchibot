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
    public const TYPES = ['text', 'photo', 'video', 'animation', 'document', 'audio'];

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

    /** Postni chatga yuboradi; $extraRows — URL tugma ostiga qo'shiladigan boshqaruv tugmalari (preview uchun). */
    public static function send(Telegram $tg, int $chatId, array $post, string $botUsername, bool $free, array $extraRows = []): array
    {
        $type = (string) $post['post_type'];
        $html = self::watermark((string) ($post['text'] ?? ''), $type, $botUsername, $free);
        $rows = array_merge(self::urlRows($post['button_text'] ?? null, $post['button_url'] ?? null), $extraRows);
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
