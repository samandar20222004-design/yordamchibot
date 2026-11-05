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
        $list = $ctx->app->posts->listPending($ctx->ownerId(), self::LIST_LIMIT);
        if (!$list) {
            $kb = Keyboards::inline([[Keyboards::btn($ctx->t('btn_sent_list'), 's:list')], [Keyboards::btn($ctx->t('btn_new_post'), 'p:new'), Keyboards::btn($ctx->t('btn_home'), 'm:home')]]);
            if ($edit) {
                $ctx->edit($ctx->t('q_empty'), $kb);
            } else {
                $ctx->reply($ctx->t('q_empty'), $kb);
            }
            return;
        }
        $text = $ctx->workspaceLine() . $ctx->t('q_title', ['n' => $ctx->app->posts->pendingCount($ctx->ownerId())]);
        $kb = Keyboards::queue($list, $ctx->lang, $ctx->tz());
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
        $type = $post['post_type'] === 'album' ? 'album ×' . count(\PostAssist\Services\PostRender::albumMedia($post)) : $post['post_type'];
        $label = $post['post_type'] !== 'text' ? $ctx->t('media_label', ['type' => $type]) . ' ' : '';
        if (mb_strlen($plain) > 300) {
            $plain = mb_substr($plain, 0, 300) . '…';
        }
        return Html::e($label . $plain);
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $p = $ctx->app->posts->getOwnedPending($ctx->ownerId(), $id);
        if (!$p) {
            $ctx->edit($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $extra = '';
        if (!empty($p['recurrence_type'])) {
            $extra .= "\n🔄 " . PostHandler::repeatLabel($ctx, ['type' => $p['recurrence_type'], 'time' => (int) $p['recurrence_time'],
                'day' => $p['recurrence_day'] !== null ? (int) $p['recurrence_day'] : null]) . ' · ' . $ctx->t('rep_sent', ['n' => (int) $p['sent_count']]);
        }
        if ((int) ($p['delete_after'] ?? 0) > 0) {
            $extra .= "\n⏳ " . $ctx->t('ad_after', ['h' => intdiv((int) $p['delete_after'], 60)]);
        }
        if (!empty($p['reactions'])) {
            $extra .= "\n👍 " . Html::e(str_replace(',', ' ', (string) $p['reactions']));
        }
        $ctx->edit($ctx->t('q_view', [
            'id' => $id, 'channel' => Html::e((string) ($p['channel_title'] ?? $p['channel_id'])),
            'when' => TimeParser::show((string) $p['scheduled_time'], $ctx->tz()),
            'tz' => Html::e($ctx->tzName()), 'preview' => self::previewText($p, $ctx),
        ]) . $extra, Keyboards::queueItem($id, $ctx->lang));
    }

    public static function askCancel(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('delete')) {
            $ctx->edit($ctx->t('team_no_perm'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        if (!$ctx->app->posts->getOwnedPending($ctx->ownerId(), $id)) {
            $ctx->edit($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $ctx->edit($ctx->t('q_del_ask', ['id' => $id]), Keyboards::confirm($ctx->lang, 'q:dok:' . $id, 'q:v:' . $id));
    }

    public static function cancel(Ctx $ctx, int $id): void
    {
        $ok = $ctx->can('delete') && $ctx->app->posts->cancel($ctx->ownerId(), $id);
        $ctx->edit($ctx->t($ok ? 'q_deleted' : 'q_not_found', ['id' => $id]), Keyboards::nav($ctx->lang, 'q:list'));
    }
}
