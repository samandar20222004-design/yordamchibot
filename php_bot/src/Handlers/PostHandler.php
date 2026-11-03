<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\Links;
use PostAssist\Services\PostRender;
use PostAssist\Services\Scheduler;
use PostAssist\Services\TimeParser;

/**
 * Oddiy post: kontent -> (kanal tanlash) -> ko'rinish (preview) -> hozir yuborish | vaqt belgilash.
 * Holat `user_states` da: post_content | post_pick | post_preview | post_btn | post_edit | post_time,
 * ma'lumot: ['draft' => [type, file_id, text, button_text, button_url], 'channel' => channels.id].
 */
final class PostHandler
{
    public static function begin(Ctx $ctx): void
    {
        if ($ctx->app->channels->countFor($ctx->userId) === 0) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        $ctx->app->states->set($ctx->userId, 'post_content');
        $ctx->reply($ctx->t('post_ask_content'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    /** Post kontenti keldi (yangi yoki tahrir). */
    public static function content(Ctx $ctx, array $state): void
    {
        $draft = PostRender::draftFromMessage($ctx->message ?? []);
        if ($draft === null) {
            $ctx->reply($ctx->t('post_unsupported'));
            return;
        }
        $len = Html::utf16Len(Html::plain((string) $draft['text']));
        $max = PostRender::limitFor($draft['type']);
        if ($len > $max) {
            $ctx->reply($ctx->t($draft['type'] === 'text' ? 'post_too_long_text' : 'post_too_long_caption', ['len' => $len, 'max' => $max]));
            return;
        }
        if ($draft['type'] === 'text' && trim(Html::plain($draft['text'])) === '') {
            $ctx->reply($ctx->t('post_unsupported'));
            return;
        }
        $data = $state['data'];
        $old = $data['draft'] ?? [];
        $draft['button_text'] = $old['button_text'] ?? null;
        $draft['button_url'] = $old['button_url'] ?? null;
        $data['draft'] = $draft;
        if (empty($data['channel']) || !$ctx->app->channels->getOwned($ctx->userId, (int) $data['channel'])) {
            $channels = $ctx->app->channels->listFor($ctx->userId);
            if (!$channels) {
                $ctx->app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('ch_need_first'));
                return;
            }
            if (count($channels) > 1) {
                $ctx->app->states->set($ctx->userId, 'post_pick', $data);
                $ctx->reply($ctx->t('post_pick_channel'), Keyboards::pickChannel($channels, $ctx->lang));
                return;
            }
            $data['channel'] = (int) $channels[0]['id'];
        }
        self::preview($ctx, $data);
    }

    public static function pickChannel(Ctx $ctx, int $id): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        if (!$ctx->app->channels->getOwned($ctx->userId, $id)) {
            $ctx->reply($ctx->t('post_pick_channel'), Keyboards::pickChannel($ctx->app->channels->listFor($ctx->userId), $ctx->lang));
            return;
        }
        $data = $st['data'];
        $data['channel'] = $id;
        self::preview($ctx, $data);
    }

    /** Postni foydalanuvchiga xuddi kanaldagidek ko'rsatadi (nishon bilan) va boshqaruv tugmalari. */
    public static function preview(Ctx $ctx, array $data): void
    {
        $ctx->app->states->set($ctx->userId, 'post_preview', $data);
        $d = $data['draft'];
        $post = ['post_type' => $d['type'], 'text' => $d['text'], 'file_id' => $d['file_id'],
            'button_text' => $d['button_text'] ?? null, 'button_url' => $d['button_url'] ?? null];
        $rows = Keyboards::previewRows($ctx->lang, !empty($d['button_url']));
        $res = PostRender::send($ctx->app->tg, $ctx->chatId, $post, $ctx->app->config->str('bot_username'), $ctx->app->isFree($ctx->userId), $rows);
        if (empty($res['ok'])) {
            $ctx->reply($ctx->t('send_fail', ['reason' => $ctx->t(PostRender::reasonKey($res))]), Keyboards::inline($rows));
            return;
        }
        $ctx->reply($ctx->t('post_preview_hint'));
    }

    /** Preview tugmalari. */
    public static function action(Ctx $ctx, string $act): void
    {
        if ($act === 'cancel') {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cancelled'));
            return;
        }
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        switch ($act) {
            case 'now':
                self::sendNow($ctx, $data, $st['state']);
                return;
            case 'time':
                $ctx->app->states->set($ctx->userId, 'post_time', $data);
                $ctx->reply($ctx->t('time_ask', ['tz' => Html::e($ctx->app->tzName())]), Keyboards::times($ctx->lang));
                return;
            case 'btn':
                $ctx->app->states->set($ctx->userId, 'post_btn', $data);
                $ctx->reply($ctx->t('post_btn_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
                return;
            case 'btndel':
                $data['draft']['button_text'] = null;
                $data['draft']['button_url'] = null;
                self::preview($ctx, $data);
                return;
            case 'edit':
                $ctx->app->states->set($ctx->userId, 'post_edit', $data);
                $ctx->reply($ctx->t('post_edit_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
                return;
            case 'back':
                self::preview($ctx, $data);
                return;
        }
    }

    public static function buttonInput(Ctx $ctx, array $state): void
    {
        $parsed = Links::parseButton((string) ($ctx->message['text'] ?? ''));
        if ($parsed === null) {
            $ctx->reply($ctx->t('post_btn_bad'));
            return;
        }
        $data = $state['data'];
        $data['draft']['button_text'] = $parsed[0];
        $data['draft']['button_url'] = $parsed[1];
        self::preview($ctx, $data);
    }

    public static function timeInput(Ctx $ctx, array $state): void
    {
        $r = TimeParser::parse((string) ($ctx->message['text'] ?? ''), $ctx->app->tz(), $ctx->app->now());
        if (!$r['ok']) {
            $key = ['past' => 'time_past', 'too_far' => 'time_too_far'][$r['error']] ?? 'time_bad';
            $ctx->reply($ctx->t($key));
            return;
        }
        self::schedule($ctx, $state['data'], $r['utc'], $state['state']);
    }

    public static function quickTime(Ctx $ctx, string $code): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $utc = TimeParser::quick($code, $ctx->app->tz(), $ctx->app->now());
        if ($utc !== null) {
            self::schedule($ctx, $st['data'], $utc, $st['state']);
        }
    }

    private static function schedule(Ctx $ctx, array $data, DateTimeImmutable $utc, string $stateName): void
    {
        $channel = $ctx->app->channels->getOwned($ctx->userId, (int) ($data['channel'] ?? 0));
        if (!$channel) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (!self::queueHasRoom($ctx)) {
            return;
        }
        if (!$ctx->app->states->take($ctx->userId, $stateName)) {
            return; // ikkinchi parallel bosish — post allaqachon yaratildi
        }
        $utcSql = $utc->format('Y-m-d H:i:s');
        $ctx->app->posts->create($ctx->userId, (int) $channel['channel_id'], $data['draft'], $utcSql, true);
        self::afterSaved($ctx);
        $ctx->replyMenu($ctx->t('post_scheduled', [
            'channel' => Html::e((string) $channel['title']),
            'when' => TimeParser::show($utcSql, $ctx->app->tz()),
            'tz' => Html::e($ctx->app->tzName()),
        ]));
    }

    /** «Hozir yuborish»: navbatga qo'yiladi va darhol yuboriladi; natija rostdan aytiladi. */
    private static function sendNow(Ctx $ctx, array $data, string $stateName): void
    {
        $channel = $ctx->app->channels->getOwned($ctx->userId, (int) ($data['channel'] ?? 0));
        if (!$channel) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (!self::queueHasRoom($ctx)) {
            return;
        }
        if (!$ctx->app->states->take($ctx->userId, $stateName)) {
            return; // ikkinchi parallel bosish — post allaqachon yuborilmoqda
        }
        $id = $ctx->app->posts->create($ctx->userId, (int) $channel['channel_id'], $data['draft'], $ctx->app->nowSql(), false);
        self::afterSaved($ctx);
        if (!$ctx->app->posts->claim($id)) {
            $ctx->replyMenu($ctx->t('send_retry'));
            return;
        }
        $post = $ctx->app->posts->get($id);
        $r = (new Scheduler($ctx->app))->deliver($post ?? []);
        $name = Html::e((string) $channel['title']);
        if ($r['status'] === 'sent') {
            $ctx->replyMenu($ctx->t('send_ok', ['channel' => $name]));
        } elseif ($r['status'] === 'retry') {
            $ctx->replyMenu($ctx->t('send_retry'));
        } else {
            $ctx->replyMenu($ctx->t('send_fail', ['reason' => $ctx->t($r['reason'])]));
        }
    }

    /** Post saqlandi: referal mukofoti (birinchi post) va manba havolasi belgisi. */
    private static function afterSaved(Ctx $ctx): void
    {
        $r = $ctx->app->afterPostSaved($ctx->userId);
        if ($r !== null) {
            PlansHandler::notifyReward($ctx->app, $r, $ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId);
        }
    }

    private static function queueHasRoom(Ctx $ctx): bool
    {
        $limit = $ctx->app->queueLimit($ctx->userId);
        if ($limit > 0 && $ctx->app->posts->pendingCount($ctx->userId) >= $limit) {
            $ctx->reply($ctx->t('queue_limit', ['max' => $limit]));
            return false;
        }
        return true;
    }

    /** Qoralamali holat (bo'lmasa foydalanuvchiga aytiladi va null). */
    private static function draftState(Ctx $ctx): ?array
    {
        $st = $ctx->state();
        if ($st === null || empty($st['data']['draft']) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return null;
        }
        return $st;
    }
}
