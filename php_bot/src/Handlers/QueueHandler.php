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

    // ------------------------------------------------------------------ navbatdagi post: hozir yuborish, vaqtni o'zgartirish, nusxa

    /** «🚀 Hozir»: navbatdagi postni kutmasdan kanalga chiqaradi. */
    public static function sendNow(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        if (!$ctx->can('send_now')) {
            $ctx->reply($ctx->t('team_no_perm_now'), Keyboards::nav($ctx->lang, 'q:v:' . $id));
            return;
        }
        $p = $app->posts->getOwnedPending($ctx->ownerId(), $id);
        if (!$p) {
            $ctx->edit($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $app->posts->updatePending($ctx->ownerId(), $id, null, $app->nowSql());
        $r = ['status' => 'retry', 'reason' => ''];
        if ($app->posts->claim($id)) {
            $r = (new \PostAssist\Services\Scheduler($app))->deliver($app->posts->get($id) ?? []);
        }
        $name = Html::e((string) ($p['channel_title'] ?? $p['channel_id']));
        $text = $r['status'] === 'sent' ? $ctx->t('send_ok', ['channel' => $name])
            : ($r['status'] === 'retry' ? $ctx->t('send_retry') : $ctx->t('send_fail', ['reason' => $ctx->t((string) $r['reason'])]));
        if ($r['status'] === 'sent' && !empty($r['next'])) {
            $text .= "\n🔄 " . $ctx->t('rep_next', ['when' => TimeParser::show($r['next']->format('Y-m-d H:i:s'), $ctx->tz())]);
        }
        $ctx->edit($text, Keyboards::inline([[Keyboards::btn($ctx->t('btn_scheduled'), 'q:list'), Keyboards::btn($ctx->t('btn_home'), 'm:home')]]));
    }

    /** «🕒 Vaqt»: yangi vaqtni so'raydi (matn: 18:30, ertaga 9:00, +30 …) yoki tezkor tugmalar. */
    public static function askTime(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('create') || !$ctx->app->posts->getOwnedPending($ctx->ownerId(), $id)) {
            $ctx->edit($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'q_time', ['id' => $id]);
        $b = static function (string $k, string $code) use ($ctx, $id) {
            return Keyboards::btn($ctx->t($k), 'q:tq:' . $id . ':' . $code);
        };
        $ctx->edit($ctx->t('q_time_ask', ['tz' => Html::e($ctx->tzName())]), Keyboards::inline([
            [$b('btn_t_1h', '1h'), $b('btn_t_today18', 'today18')],
            [$b('btn_t_tom09', 'tom09'), Keyboards::btn($ctx->t('btn_back'), 'q:v:' . $id)],
        ]));
    }

    public static function quickTime(Ctx $ctx, int $id, string $code): void
    {
        $utc = TimeParser::quick($code, $ctx->tz(), $ctx->app->now());
        if ($utc !== null) {
            self::applyTime($ctx, $id, $utc);
        }
    }

    /** Matn bilan yangi vaqt (holat q_time). */
    public static function timeInput(Ctx $ctx, array $state): void
    {
        $r = TimeParser::parse((string) ($ctx->message['text'] ?? ''), $ctx->tz(), $ctx->app->now());
        if (!$r['ok']) {
            $key = ['past' => 'time_past', 'too_far' => 'time_too_far'][$r['error']] ?? 'time_bad';
            $ctx->reply($ctx->t($key), Keyboards::nav($ctx->lang, 'q:v:' . (int) ($state['data']['id'] ?? 0)));
            return;
        }
        self::applyTime($ctx, (int) ($state['data']['id'] ?? 0), $r['utc']);
    }

    private static function applyTime(Ctx $ctx, int $id, \DateTimeImmutable $utc): void
    {
        $ctx->app->states->clear($ctx->userId);
        $ok = $ctx->can('create') && $ctx->app->posts->updatePending($ctx->ownerId(), $id, null, $utc->format('Y-m-d H:i:s'));
        if (!$ok) {
            $ctx->reply($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $ctx->reply($ctx->t('q_time_ok', ['when' => TimeParser::show($utc->format('Y-m-d H:i:s'), $ctx->tz())]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_q_open'), 'q:v:' . $id), Keyboards::btn($ctx->t('btn_scheduled'), 'q:list')],
        ]));
    }

    /** «📋 Nusxa»: postni yangi qoralama sifatida ochadi (boshqa kanal yoki vaqtga qayta ishlatish uchun). */
    public static function duplicate(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('create')) {
            $ctx->replyMenu($ctx->t('team_no_perm'));
            return;
        }
        $p = $ctx->app->posts->getOwnedPending($ctx->ownerId(), $id);
        if (!$p) {
            $ctx->edit($ctx->t('q_not_found'), Keyboards::nav($ctx->lang, 'q:list'));
            return;
        }
        $media = $p['media'] ?? null;
        $media = is_string($media) ? json_decode($media, true) : $media;
        $draft = ['type' => (string) $p['post_type'], 'file_id' => $p['file_id'], 'text' => (string) $p['text'], 'media' => is_array($media) ? $media : null,
            'button_text' => $p['button_text'], 'button_url' => $p['button_url'],
            'buttons' => \PostAssist\Services\PostRender::buttonList($p) ?: null, 'reactions' => $p['reactions'],
            'delete_after' => $p['delete_after'] !== null ? (int) $p['delete_after'] : null, 'options' => $p['options'] ?? null, 'hidden' => $p['hidden_text'] ?? null];
        PostHandler::applyDraft($ctx, ['state' => 'post_content', 'data' => ['draft' => $draft]], $draft);
    }
}
