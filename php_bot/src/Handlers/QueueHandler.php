<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\TimeParser;

/** Rejalashtirilgan postlar: ro'yxat (har post bitta tugma), ko'rish, bekor qilish (tasdiq bilan). */
final class QueueHandler
{
    public const LIST_LIMIT = 20;

    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $list = $ctx->app->posts->listPending($ctx->userId, self::LIST_LIMIT);
        if (!$list) {
            if ($edit) {
                $ctx->edit($ctx->t('q_empty'));
            } else {
                $ctx->replyMenu($ctx->t('q_empty'));
            }
            return;
        }
        $text = $ctx->t('q_title', ['n' => $ctx->app->posts->pendingCount($ctx->userId)]);
        $kb = Keyboards::queue($list, $ctx->lang, $ctx->app->tz());
        if ($edit) {
            $ctx->edit($text, $kb);
        } else {
            $ctx->reply($text, $kb);
        }
    }

    /** Ro'yxatdagi qisqa ko'rinish: matnning boshi yoki media turi. */
    public static function previewText(array $post, Ctx $ctx): string
    {
        $plain = trim(Html::plain((string) ($post['text'] ?? '')));
        $label = $post['post_type'] !== 'text' ? $ctx->t('media_label', ['type' => $post['post_type']]) . ' ' : '';
        if (mb_strlen($plain) > 300) {
            $plain = mb_substr($plain, 0, 300) . '…';
        }
        return Html::e($label . $plain);
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $p = $ctx->app->posts->getOwnedPending($ctx->userId, $id);
        if (!$p) {
            $ctx->edit($ctx->t('q_not_found'));
            return;
        }
        $ctx->edit($ctx->t('q_view', [
            'id' => $id, 'channel' => Html::e((string) ($p['channel_title'] ?? $p['channel_id'])),
            'when' => TimeParser::show((string) $p['scheduled_time'], $ctx->app->tz()),
            'tz' => Html::e($ctx->app->tzName()), 'preview' => self::previewText($p, $ctx),
        ]), Keyboards::queueItem($id, $ctx->lang));
    }

    public static function askCancel(Ctx $ctx, int $id): void
    {
        if (!$ctx->app->posts->getOwnedPending($ctx->userId, $id)) {
            $ctx->edit($ctx->t('q_not_found'));
            return;
        }
        $ctx->edit($ctx->t('q_del_ask', ['id' => $id]), Keyboards::confirm($ctx->lang, 'q:dok:' . $id, 'q:v:' . $id));
    }

    public static function cancel(Ctx $ctx, int $id): void
    {
        $ok = $ctx->app->posts->cancel($ctx->userId, $id);
        $ctx->edit($ctx->t($ok ? 'q_deleted' : 'q_not_found', ['id' => $id]));
    }
}
