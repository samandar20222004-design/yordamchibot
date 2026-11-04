<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Services\PostRender;

/**
 * Kanal postidagi reaksiya tugmalari (👍 3 · ❤️ 1). Bosilganda ovoz yoziladi (bir kishi — bitta reaksiya,
 * qayta bossa olib tashlanadi) va tugmalardagi sonlar yangilanadi.
 */
final class ReactionHandler
{
    public static function press(App $app, array $cq, int $idx): void
    {
        $id = (string) ($cq['id'] ?? '');
        $chat = (int) ($cq['message']['chat']['id'] ?? 0);
        $mid = (int) ($cq['message']['message_id'] ?? 0);
        $uid = (int) ($cq['from']['id'] ?? 0);
        $row = ($chat !== 0 && $mid > 0) ? $app->messages->find($chat, $mid) : null;
        $list = $row ? PostRender::reactionList($row['reactions']) : [];
        if ($uid <= 0 || !isset($list[$idx])) {
            $app->tg->answerCallback($id); // preview yoki eski xabar — jim
            return;
        }
        $r = $app->messages->vote($chat, $mid, $uid, $idx, $app->nowSql());
        $app->tg->answerCallback($id, $r === 'removed' ? '↩️' : $list[$idx]);
        $rows = PostRender::postRows($row, $app->messages->counts($chat, $mid));
        $app->tg->call('editMessageReplyMarkup', ['chat_id' => $chat, 'message_id' => $mid, 'reply_markup' => ['inline_keyboard' => $rows]]);
    }
}
