<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;

/**
 * Kanallar: ro'yxat, ulash (forward yoki @username), o'chirish.
 * Ulashda tekshiriladi: bu kanal; bot admin va xabar joylay oladi; foydalanuvchining o'zi kanal admini/egasi.
 */
final class ChannelHandler
{
    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $list = $ctx->app->channels->listFor($ctx->userId);
        $limit = $ctx->app->channelLimit($ctx->userId);
        $canAdd = $limit === 0 || count($list) < $limit;
        $text = $list ? $ctx->t('ch_list_title', ['n' => count($list), 'max' => $limit === 0 ? '∞' : $limit]) : $ctx->t('ch_list_empty');
        $kb = Keyboards::channels($list, $ctx->lang, $canAdd);
        if ($edit) {
            $ctx->edit($text, $kb);
        } else {
            $ctx->reply($text, $kb);
        }
    }

    public static function askAdd(Ctx $ctx): void
    {
        $ctx->app->states->set($ctx->userId, 'ch_wait');
        $ctx->reply($ctx->t('ch_add_howto'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'ch:list')]]));
    }

    /** Forward qilingan post yoki @username / t.me havola / -100... ID dan kanal. */
    public static function receive(Ctx $ctx): void
    {
        $app = $ctx->app;
        $msg = $ctx->message ?? [];
        $chat = null;
        if (isset($msg['forward_origin']['chat']) && is_array($msg['forward_origin']['chat'])) {
            $chat = $msg['forward_origin']['chat'];
        } elseif (isset($msg['forward_from_chat']) && is_array($msg['forward_from_chat'])) {
            $chat = $msg['forward_from_chat'];
        }
        $ref = null;
        if ($chat !== null) {
            $ref = (int) $chat['id'];
        } else {
            $text = trim((string) ($msg['text'] ?? ''));
            if (preg_match('/^(?:https?:\/\/)?(?:t\.me\/|telegram\.me\/)?@?([A-Za-z][A-Za-z0-9_]{3,31})\/?$/', $text, $m)) {
                $ref = '@' . $m[1];
            } elseif (preg_match('/^-100\d{5,15}$/', $text)) {
                $ref = (int) $text;
            }
        }
        if ($ref === null) {
            $ctx->reply($ctx->t('ch_not_found'));
            return;
        }
        $info = $app->tg->call('getChat', ['chat_id' => $ref]);
        if (empty($info['ok']) || !isset($info['result']['id'])) {
            $ctx->reply($ctx->t('ch_not_found'));
            return;
        }
        $c = $info['result'];
        if (($c['type'] ?? '') !== 'channel') {
            $ctx->reply($ctx->t('ch_not_channel'));
            return;
        }
        $channelId = (int) $c['id'];
        $botId = self::botId($app);
        $botMember = $app->tg->call('getChatMember', ['chat_id' => $channelId, 'user_id' => $botId]);
        $bs = (string) ($botMember['result']['status'] ?? '');
        if (empty($botMember['ok']) || ($bs !== 'administrator' && $bs !== 'creator')) {
            $ctx->reply($ctx->t('ch_bot_not_admin'));
            return;
        }
        if ($bs === 'administrator' && empty($botMember['result']['can_post_messages'])) {
            $ctx->reply($ctx->t('ch_bot_no_post_right'));
            return;
        }
        $userMember = $app->tg->call('getChatMember', ['chat_id' => $channelId, 'user_id' => $ctx->userId]);
        $us = (string) ($userMember['result']['status'] ?? '');
        if (empty($userMember['ok']) || ($us !== 'administrator' && $us !== 'creator')) {
            $ctx->reply($ctx->t('ch_user_not_admin'));
            return;
        }
        $title = mb_substr((string) ($c['title'] ?? $channelId), 0, 255);
        $username = isset($c['username']) ? mb_substr((string) $c['username'], 0, 64) : null;
        $limit = $app->channelLimit($ctx->userId);
        $res = $app->channels->connect($ctx->userId, $channelId, $title, $username, $limit);
        $safe = Html::e($title);
        switch ($res) {
            case 'connected':
                $app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('ch_connected', ['title' => $safe]));
                return;
            case 'already':
                $app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('ch_already', ['title' => $safe]));
                return;
            case 'taken':
                $ctx->reply($ctx->t('ch_taken'));
                return;
            default:
                $ctx->reply($ctx->t('ch_limit', ['max' => $limit]));
        }
    }

    public static function askDelete(Ctx $ctx, int $id): void
    {
        $ch = $ctx->app->channels->getOwned($ctx->userId, $id);
        if (!$ch) {
            self::show($ctx, true);
            return;
        }
        $ctx->edit($ctx->t('ch_del_ask', ['title' => Html::e((string) $ch['title'])]),
            Keyboards::confirm($ctx->lang, 'ch:delok:' . $id, 'ch:list'));
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        $ch = $ctx->app->channels->getOwned($ctx->userId, $id);
        if ($ch) {
            $ctx->app->channels->deactivate((int) $ch['channel_id']);
            $ctx->edit($ctx->t('ch_deleted', ['title' => Html::e((string) $ch['title'])]), Keyboards::nav($ctx->lang, 'ch:list'));
        }
        self::show($ctx);
    }

    /** Bot kanaldan chiqarildi yoki admin huquqi olindi — kanal o'chiriladi va egasiga xabar boradi. */
    public static function memberChanged(App $app, array $upd): void
    {
        if (($upd['chat']['type'] ?? '') !== 'channel') {
            return;
        }
        $status = (string) ($upd['new_chat_member']['status'] ?? '');
        $canPost = $status === 'creator' || ($status === 'administrator' && !empty($upd['new_chat_member']['can_post_messages']));
        if ($canPost) {
            return;
        }
        $channelId = (int) $upd['chat']['id'];
        $row = $app->channels->byChannelId($channelId);
        if (!$row || (int) $row['is_active'] !== 1) {
            return;
        }
        $app->channels->deactivate($channelId);
        $owner = $app->users->get((int) $row['user_id']);
        $lang = I18n::norm($owner['lang'] ?? 'uz');
        $app->tg->sendMessage((int) $row['user_id'], I18n::t('ch_removed_notice', $lang, ['title' => Html::e((string) $row['title'])]));
    }

    public static function botId(App $app): int
    {
        return (int) explode(':', $app->config->str('bot_token'), 2)[0];
    }
}
