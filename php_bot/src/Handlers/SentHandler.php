<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\PostRender;
use PostAssist\Services\TimeParser;

/**
 * 📤 Yuborilgan postlar: kanalga chiqqan postni ko'rish, matnini (izohini) TAHRIRLASH va kanaldan O'CHIRISH.
 * Tahrirda tugma, reaksiya (ovozlar bilan) va yashirin matn saqlanadi; bepul tarifda nishon qayta qo'yiladi.
 * Ruxsatlar: tahrir — `create`, o'chirish — `delete` (jamoa yordamchilari uchun).
 */
final class SentHandler
{
    public static function show(Ctx $ctx, bool $edit = true): void
    {
        $list = $ctx->app->messages->listSent($ctx->ownerId(), 15);
        $rows = [];
        foreach ($list as $m) {
            $when = TimeParser::show((string) $m['created_at'], $ctx->tz());
            $plain = trim(Html::plain((string) ($m['edited_text'] ?? $m['text'] ?? '')));
            $icon = $m['post_type'] === 'text' ? '📄' : ($m['post_type'] === 'album' ? '🖼' : '📎');
            $rows[] = [Keyboards::btn($icon . ' ' . mb_substr($when, 0, 11) . ' · ' . mb_substr($plain !== '' ? $plain : (string) $m['channel_title'], 0, 22), 's:v:' . (int) $m['id'])];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_scheduled'), 'q:list'), Keyboards::btn($ctx->t('btn_home'), 'm:home')];
        $text = $list ? $ctx->t('sent_title') : $ctx->t('sent_empty');
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $m = $ctx->app->messages->getOwnedSent($ctx->ownerId(), $id);
        if ($m === null) {
            $ctx->edit($ctx->t('sent_not_found'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        $plain = trim(Html::plain((string) ($m['edited_text'] ?? $m['text'] ?? '')));
        $ctx->edit($ctx->t('sent_view', [
            'channel' => Html::e((string) ($m['channel_title'] ?? $m['chat_id'])),
            'when' => TimeParser::show((string) $m['created_at'], $ctx->tz()),
            'preview' => Html::e(mb_strlen($plain) > 300 ? mb_substr($plain, 0, 300) . '…' : $plain),
            'edited' => $m['edited_text'] !== null ? $ctx->t('sent_edited_mark') : '',
        ]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_sent_edit'), 's:e:' . $id), Keyboards::btn($ctx->t('btn_sent_del'), 's:d:' . $id)],
            Keyboards::navRow($ctx->lang, 's:list'),
        ]));
    }

    public static function askEdit(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('create')) {
            $ctx->reply($ctx->t('team_no_perm'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        $m = $ctx->app->messages->getOwnedSent($ctx->ownerId(), $id);
        if ($m === null) {
            $ctx->reply($ctx->t('sent_not_found'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        if ($m['post_type'] === 'poll') {
            $ctx->reply($ctx->t('sent_poll_noedit'), Keyboards::nav($ctx->lang, 's:v:' . $id));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'sent_edit', ['id' => $id]);
        $ctx->reply($ctx->t('sent_edit_ask'), Keyboards::nav($ctx->lang, 's:v:' . $id));
    }

    /** Yangi matn keldi (holat sent_edit): kanaldagi xabar tahrirlanadi. */
    public static function editInput(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $id = (int) ($state['data']['id'] ?? 0);
        $m = $app->messages->getOwnedSent($ctx->ownerId(), $id);
        if ($m === null || !$ctx->can('create')) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('sent_not_found'));
            return;
        }
        $msg = $ctx->message ?? [];
        if (!isset($msg['text'])) {
            $ctx->reply($ctx->t('sent_edit_text_only'));
            return;
        }
        $html = Html::fromEntities((string) $msg['text'], $msg['entities'] ?? []);
        $type = (string) $m['post_type'];
        $limitType = $type === 'album' ? 'photo' : $type;
        $max = PostRender::limitFor($limitType);
        $len = Html::utf16Len(Html::plain($html));
        if ($len > $max) {
            $ctx->reply($ctx->t($type === 'text' ? 'post_too_long_text' : 'post_too_long_caption', ['len' => $len, 'max' => $max]));
            return;
        }
        $out = PostRender::watermark($html, $limitType, $app->config->str('bot_username'), $app->isFree($ctx->ownerId()));
        $params = ['chat_id' => (int) $m['chat_id'], 'message_id' => (int) $m['message_id'], 'parse_mode' => 'HTML'];
        if ($type !== 'album') {
            $rows = $app->messageRows($m);
            if ($rows) {
                $params['reply_markup'] = ['inline_keyboard' => $rows];
            }
        }
        $res = $type === 'text'
            ? $app->tg->call('editMessageText', $params + ['text' => $out])
            : $app->tg->call('editMessageCaption', $params + ['caption' => $out]);
        $notModified = strpos((string) ($res['description'] ?? ''), 'not modified') !== false;
        if (empty($res['ok']) && !$notModified) {
            $ctx->reply($ctx->t('sent_edit_fail', ['reason' => $ctx->t(PostRender::reasonKey($res))]), Keyboards::nav($ctx->lang, 's:v:' . $id));
            return;
        }
        $app->states->clear($ctx->userId);
        $app->messages->setText($id, $html);
        $ctx->reply($ctx->t('sent_edit_ok', ['channel' => Html::e((string) ($m['channel_title'] ?? ''))]),
            Keyboards::inline([[Keyboards::btn($ctx->t('btn_sent_list'), 's:list')], Keyboards::navRow($ctx->lang)]));
    }

    public static function askDelete(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('delete')) {
            $ctx->edit($ctx->t('team_no_perm'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        if ($ctx->app->messages->getOwnedSent($ctx->ownerId(), $id) === null) {
            $ctx->edit($ctx->t('sent_not_found'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        $ctx->edit($ctx->t('sent_del_confirm'), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_sent_del'), 's:dok:' . $id), Keyboards::btn($ctx->t('btn_back'), 's:v:' . $id)],
        ]));
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $m = $ctx->can('delete') ? $app->messages->getOwnedSent($ctx->ownerId(), $id) : null;
        if ($m === null) {
            $ctx->edit($ctx->t('sent_not_found'), Keyboards::nav($ctx->lang, 's:list'));
            return;
        }
        $ids = array_merge([(int) $m['message_id']], array_map('intval', array_filter(explode(',', (string) ($m['extra_ids'] ?? '')))));
        $ok = true;
        foreach ($ids as $mid) {
            $r = $app->tg->call('deleteMessage', ['chat_id' => (int) $m['chat_id'], 'message_id' => $mid]);
            $gone = strpos(strtolower((string) ($r['description'] ?? '')), 'not found') !== false;
            $ok = $ok && (!empty($r['ok']) || $gone);
        }
        if (!$ok) {
            $ctx->edit($ctx->t('sent_del_fail'), Keyboards::nav($ctx->lang, 's:v:' . $id));
            return;
        }
        $app->messages->markDeleted($id);
        $ctx->edit($ctx->t('sent_deleted'), Keyboards::nav($ctx->lang, 's:list'));
    }
}
