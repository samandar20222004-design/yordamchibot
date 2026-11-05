<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Comments;
use PostAssist\Services\PostRender;

/**
 * 💬 Izohlar: kanal postidagi «💬 Izohlar» tugmasi botni ochadi (`/start c_<post>`), o'quvchi izohlarni ko'radi va yozadi.
 * Kanalga muhokama guruhi ulashning hojati yo'q. Himoya: 2–500 belgi, 10 daqiqada 5 ta, havola faqat egasiga ruxsat,
 * egasi har izoh haqida xabar oladi va 🗑 o'chira / 🚫 bloklay oladi. Tugmadagi son har izohdan keyin yangilanadi.
 */
final class CommentsHandler
{
    public const MIN = 2;
    public const MAX = 500;

    private static function post(App $app, int $pid): ?array
    {
        $p = $app->posts->get($pid);
        return $p && in_array('comments', PostRender::options($p['options'] ?? null), true) && $p['post_type'] !== 'album' ? $p : null;
    }

    public static function open(Ctx $ctx, int $pid, bool $edit = false): void
    {
        $app = $ctx->app;
        $p = self::post($app, $pid);
        if ($p === null) {
            $ctx->replyMenu($ctx->t('cm_off'));
            return;
        }
        $snippet = trim(Html::plain((string) $p['text']));
        $snippet = mb_strlen($snippet) > 200 ? mb_substr($snippet, 0, 200) . '…' : ($snippet !== '' ? $snippet : '[' . $p['post_type'] . ']');
        $owner = (int) $p['user_id'];
        $lines = [];
        foreach ($app->comments->list($pid) as $c) {
            $lines[] = ((int) $c['user_id'] === $owner ? '⭐ ' : '') . '<b>' . Html::e((string) $c['name']) . '</b>: ' . Html::e((string) $c['text']);
        }
        $text = $ctx->t('cm_title', ['post' => Html::e($snippet), 'n' => $app->comments->count($pid)]) . "\n\n"
            . ($lines ? implode("\n\n", $lines) : $ctx->t('cm_empty'));
        $kb = Keyboards::inline([[Keyboards::btn($ctx->t('btn_cm_write'), 'cm:w:' . $pid), Keyboards::btn($ctx->t('btn_cm_refresh'), 'cm:v:' . $pid)]]);
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    public static function ask(Ctx $ctx, int $pid): void
    {
        $p = self::post($ctx->app, $pid);
        if ($p === null) {
            $ctx->replyMenu($ctx->t('cm_off'));
            return;
        }
        if ($ctx->app->comments->isBanned((int) $p['user_id'], $ctx->userId)) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->reply($ctx->t('cm_banned'));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'cm_write', ['pid' => $pid]);
        $ctx->reply($ctx->t('cm_ask', ['max' => self::MAX]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'cm:v:' . $pid)]]));
    }

    /** Izoh matni keldi (holat cm_write). */
    public static function input(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $pid = (int) ($state['data']['pid'] ?? 0);
        $p = self::post($app, $pid);
        if ($p === null) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cm_off'));
            return;
        }
        $owner = (int) $p['user_id'];
        $text = trim((string) ($ctx->message['text'] ?? ''));
        $len = mb_strlen($text);
        if ($len < self::MIN || $len > self::MAX) {
            $ctx->reply($ctx->t('cm_len', ['min' => self::MIN, 'max' => self::MAX]));
            return;
        }
        if ($app->comments->isBanned($owner, $ctx->userId)) {
            $app->states->clear($ctx->userId);
            $ctx->reply($ctx->t('cm_banned'));
            return;
        }
        if ($ctx->userId !== $owner && preg_match('#(https?://|www\.|t\.me/|telegram\.me/|@[A-Za-z0-9_]{5,})#i', $text)) {
            $ctx->reply($ctx->t('cm_no_links'));
            return;
        }
        if ($ctx->userId !== $owner && $app->comments->recentBy($ctx->userId, $app->now()->modify('-10 minutes')) >= Comments::PER_10_MIN) {
            $ctx->reply($ctx->t('cm_slow'));
            return;
        }
        $name = $ctx->firstName !== '' ? $ctx->firstName : 'User';
        $id = $app->comments->add($pid, $owner, $ctx->userId, $name, $text, $app->now());
        $app->states->clear($ctx->userId);
        self::refreshButtons($app, $pid);
        if ($ctx->userId !== $owner) {
            $lang = I18n::norm((string) ($app->users->get($owner)['lang'] ?? 'uz'));
            $app->tg->sendMessage($owner, I18n::t('cm_new', $lang, ['name' => Html::e($name), 'text' => Html::e($text)]), Keyboards::inline([
                [Keyboards::btn(I18n::t('btn_cm_del', $lang), 'cm:x:' . $id), Keyboards::btn(I18n::t('btn_cm_ban', $lang), 'cm:b:' . $id)],
                [['text' => I18n::t('btn_cm_open', $lang), 'url' => 'https://t.me/' . $app->config->str('bot_username') . '?start=c_' . $pid]],
            ]));
        }
        $ctx->reply($ctx->t('cm_added'));
        self::open($ctx, $pid);
    }

    /** Kanaldagi «💬 Izohlar (N)» tugmasini yangilash (postning oxirgi 3 xabari). */
    public static function refreshButtons(App $app, int $pid): void
    {
        foreach ($app->messages->latestForPost($pid, 3) as $row) {
            if (trim((string) ($row['comments_label'] ?? '')) === '') {
                continue;
            }
            $app->tg->call('editMessageReplyMarkup', ['chat_id' => (int) $row['chat_id'], 'message_id' => (int) $row['message_id'],
                'reply_markup' => ['inline_keyboard' => $app->messageRows($row)]]);
        }
    }

    /** O'chirish ('x') yoki bloklash ('b') — faqat egasi (bot va Mini App uchun umumiy). @return array|null izoh */
    public static function applyModeration(Ctx $ctx, string $act, int $id): ?array
    {
        $app = $ctx->app;
        $c = $app->comments->get($id);
        if ($c === null || (int) $c['owner_id'] !== $ctx->ownerId() || !$ctx->can('delete')) {
            return null;
        }
        if ($act === 'b') {
            $app->comments->ban((int) $c['owner_id'], (int) $c['user_id'], $app->now());
        } else {
            $app->comments->delete($id);
        }
        self::refreshButtons($app, (int) $c['post_id']);
        return $c;
    }

    /** Egasi: 🗑 o'chirish yoki 🚫 bloklash. */
    public static function moderate(Ctx $ctx, string $act, int $id): void
    {
        $c = self::applyModeration($ctx, $act, $id);
        if ($c === null) {
            $ctx->reply($ctx->t('cm_not_found'));
            return;
        }
        $ctx->edit($ctx->t($act === 'b' ? 'cm_banned_done' : 'cm_deleted', ['name' => Html::e((string) $c['name'])]));
    }
}
