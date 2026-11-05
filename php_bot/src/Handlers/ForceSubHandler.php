<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;

/**
 * 🔒 Majburiy obuna. Foydalanuvchi belgilangan kanallarga a'zo bo'lmaguncha bot ishlamaydi (adminlar mustasno).
 * A'zolik tekshiruvi 10 daqiqa eslab qolinadi. Xavfsiz qoida: Telegram tekshiruvga javob bermasa (bot kanalda admin
 * emas, tarmoq xatosi) — foydalanuvchi O'TKAZILADI, shunda bot noto'g'ri sozlama tufayli hammaga yopilib qolmaydi.
 */
final class ForceSubHandler
{
    private const MEMBER = ['creator', 'administrator', 'member'];

    /**
     * Foydalanuvchi hamma kanalga a'zomi? Bo'lmasa — a'zo bo'lmagan kanallar ro'yxati.
     * @return array<int, array> yetishmayotgan kanallar (bo'sh = o'tdi)
     */
    public static function missing(App $app, int $userId): array
    {
        $channels = $app->forced->active();
        if (!$channels || $app->isAdmin($userId) || $app->forced->cachedOk($userId, $app->nowSql())) {
            return [];
        }
        $missing = [];
        foreach ($channels as $c) {
            $r = $app->tg->call('getChatMember', ['chat_id' => (int) $c['chat_id'], 'user_id' => $userId]);
            if (empty($r['ok'])) {
                $app->log('majburiy obuna tekshiruvi: ' . ($r['description'] ?? '')); // fail-open
                continue;
            }
            $st = (string) ($r['result']['status'] ?? '');
            if (in_array($st, self::MEMBER, true) || ($st === 'restricted' && !empty($r['result']['is_member']))) {
                continue;
            }
            $missing[] = $c;
        }
        if (!$missing) {
            $app->forced->setOk($userId, $app->now());
        }
        return $missing;
    }

    /** Darvoza: o'tsa true; o'tmasa foydalanuvchiga obuna bo'lish ekrani ko'rsatiladi va false. */
    public static function gate(Ctx $ctx): bool
    {
        $missing = self::missing($ctx->app, $ctx->userId);
        if (!$missing) {
            return true;
        }
        self::show($ctx, $missing);
        return false;
    }

    private static function show(Ctx $ctx, array $missing, bool $again = false): void
    {
        $rows = [];
        foreach ($missing as $c) {
            $url = !empty($c['username']) ? 'https://t.me/' . $c['username'] : (string) ($c['invite_link'] ?? '');
            if ($url !== '') {
                $rows[] = [['text' => '📢 ' . mb_substr((string) ($c['title'] ?: $c['chat_id']), 0, 30), 'url' => $url]];
            }
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_fs_check'), 'fs:check')];
        $ctx->reply(($again ? $ctx->t('fs_not_yet') . "\n\n" : '') . $ctx->t('fs_gate'), Keyboards::inline($rows));
    }

    /** «✅ Tekshirish» bosildi. */
    public static function check(Ctx $ctx): void
    {
        $ctx->app->forced->clearOk($ctx->userId);
        $missing = self::missing($ctx->app, $ctx->userId);
        if ($missing) {
            self::show($ctx, $missing, true);
            return;
        }
        $ctx->app->states->clear($ctx->userId);
        $ctx->replyMenu($ctx->t('fs_ok'));
    }

    // ------------------------------------------------------------------ admin

    public static function listAll(Ctx $ctx): void
    {
        $rows = $ctx->app->forced->active();
        if (!$rows) {
            $ctx->reply($ctx->t('fs_empty'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        $lines = [];
        foreach ($rows as $c) {
            $lines[] = '• <code>' . (int) $c['id'] . '</code> — ' . Html::e((string) ($c['title'] ?: $c['chat_id'])) . (!empty($c['username']) ? ' @' . Html::e((string) $c['username']) : '');
        }
        $ctx->reply($ctx->t('fs_list_title', ['n' => count($rows), 'lines' => implode("\n", $lines)]), Keyboards::nav($ctx->lang, 'a:stats'));
    }

    /** /force_add @kanal | -100... : bot shu kanalda admin bo'lishi kerak (a'zolikni tekshira olishi uchun). */
    public static function add(Ctx $ctx, array $args): void
    {
        $app = $ctx->app;
        if (!$args) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/force_add @kanal']));
            return;
        }
        $ref = trim($args[0]);
        if (preg_match('#^(?:https?://)?t\.me/([A-Za-z0-9_]+)$#', $ref, $m)) {
            $ref = '@' . $m[1];
        }
        if (!preg_match('/^(@[A-Za-z][A-Za-z0-9_]{3,31}|-100\d{5,})$/', $ref)) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/force_add @kanal']));
            return;
        }
        $info = $app->tg->call('getChat', ['chat_id' => ctype_digit(ltrim($ref, '-')) ? (int) $ref : $ref]);
        if (empty($info['ok']) || ($info['result']['type'] ?? '') !== 'channel') {
            $ctx->reply($ctx->t('fs_err_chat'));
            return;
        }
        $chat = $info['result'];
        $bot = $app->tg->call('getChatMember', ['chat_id' => (int) $chat['id'], 'user_id' => ChannelHandler::botId($app)]);
        if (empty($bot['ok']) || !in_array($bot['result']['status'] ?? '', ['administrator', 'creator'], true)) {
            $ctx->reply($ctx->t('fs_err_bot'));
            return;
        }
        $invite = null;
        if (empty($chat['username'])) {
            $link = $app->tg->call('exportChatInviteLink', ['chat_id' => (int) $chat['id']]);
            $invite = (!empty($link['ok']) && is_string($link['result'] ?? null)) ? (string) $link['result'] : null;
        }
        $r = $app->forced->add((int) $chat['id'], (string) ($chat['title'] ?? ''), !empty($chat['username']) ? (string) $chat['username'] : null, $invite, $app->now());
        $ctx->reply($ctx->t($r === 'added' ? 'fs_added' : 'fs_' . $r, ['title' => Html::e((string) ($chat['title'] ?? '')), 'max' => \PostAssist\Repo\ForcedChannels::MAX]), Keyboards::nav($ctx->lang, 'a:stats'));
    }

    public static function remove(Ctx $ctx, array $args): void
    {
        if (!$args || !ctype_digit($args[0])) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/force_del ID']));
            return;
        }
        $ctx->reply($ctx->t($ctx->app->forced->remove((int) $args[0]) ? 'fs_deleted' : 'fs_none'), Keyboards::nav($ctx->lang, 'a:stats'));
    }
}
