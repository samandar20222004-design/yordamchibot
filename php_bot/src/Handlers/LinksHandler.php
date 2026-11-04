<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Repo\TrackedLinks;
use PostAssist\Services\TimeParser;

/**
 * 🔗 Manba havolalari: admin yaratadi (`/link_new`), ko'radi (`/links`, `/link KOD`), yoqadi/o'chiradi,
 * foydalanuvchi qayerdan kelganini tekshiradi (`/link_user`). Havola egasi `/mylinks` bilan faqat sonlarni ko'radi.
 */
final class LinksHandler
{
    public static function adminCommand(Ctx $ctx, string $cmd, array $args): bool
    {
        switch ($cmd) {
            case '/links':
                self::listAll($ctx);
                return true;
            case '/link_new':
                self::create($ctx, $args);
                return true;
            case '/link':
                if (!$args) {
                    $ctx->reply($ctx->t('admin_usage', ['usage' => '/link KOD']));
                    return true;
                }
                self::detail($ctx, $args[0]);
                return true;
            case '/link_off':
            case '/link_on':
                if (!$args) {
                    $ctx->reply($ctx->t('admin_usage', ['usage' => $cmd . ' KOD']));
                    return true;
                }
                $on = $cmd === '/link_on';
                $ok = $ctx->app->links->setActive($args[0], $on);
                $ctx->reply($ok ? $ctx->t('toggled', ['code' => Html::e((string) TrackedLinks::normalizeCode($args[0])), 'state' => $ctx->t($on ? 'state_on' : 'state_off')])
                    : $ctx->t('link_none'));
                return true;
            case '/link_user':
                self::userSources($ctx, $args);
                return true;
        }
        return false;
    }

    private static function url(Ctx $ctx, string $code): string
    {
        return 'https://t.me/' . $ctx->app->config->str('bot_username') . '?start=' . TrackedLinks::PREFIX . $code;
    }

    /** /link_new KOD [@egasi|ID] Nomi... */
    private static function create(Ctx $ctx, array $args): void
    {
        if (count($args) < 2) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/link_new KOD [@egasi] Nomi']));
            return;
        }
        $code = array_shift($args);
        $owner = null;
        if (preg_match('/^@\w{3,64}$/', $args[0]) || preg_match('/^\d{5,20}$/', $args[0])) {
            $who = array_shift($args);
            $owner = $who[0] === '@' ? $ctx->app->users->findByUsername($who) : (int) $who;
            if ($owner === null || !$ctx->app->users->exists($owner)) {
                $ctx->reply($ctx->t('link_err_owner_unknown'));
                return;
            }
        }
        $r = $ctx->app->links->create($code, implode(' ', $args), $owner, $ctx->userId, $ctx->app->now());
        if (!$r['ok']) {
            $ctx->reply($ctx->t('link_err_' . $r['error']));
            return;
        }
        $l = $r['link'];
        $ctx->reply($ctx->t('link_created', [
            'title' => Html::e((string) $l['title']), 'url' => Html::e(self::url($ctx, (string) $l['code'])),
            'owner' => $owner !== null ? $ctx->t('link_owner_line', ['id' => $owner]) : '',
        ]));
    }

    private static function line(array $l, bool $withChannel): string
    {
        return ((int) $l['is_active'] === 1 ? '✅' : '⛔️') . ' <code>' . Html::e((string) $l['code']) . '</code> — ' . Html::e(mb_substr((string) $l['title'], 0, 40))
            . "\n    👆" . (int) $l['clicks'] . ' · 🆕' . (int) $l['new_users'] . ($withChannel ? ' · 📢' . (int) $l['with_channel'] : '')
            . ' · 📝' . (int) $l['posted'] . ' · 💎' . (int) $l['paid'];
    }

    private static function listAll(Ctx $ctx): void
    {
        $rows = $ctx->app->links->listAll(null, 50);
        if (!$rows) {
            $ctx->reply($ctx->t('links_empty'));
            return;
        }
        $ctx->reply($ctx->t('links_title', ['n' => count($rows), 'lines' => implode("\n", array_map(static function ($l) {
            return self::line($l, true);
        }, $rows))]));
    }

    private static function detail(Ctx $ctx, string $code): void
    {
        $l = $ctx->app->links->get($code);
        if (!$l) {
            $ctx->reply($ctx->t('link_none'));
            return;
        }
        $owner = $ctx->t('none');
        if ($l['owner_id'] !== null) {
            $u = $ctx->app->users->get((int) $l['owner_id']);
            $owner = AdminHandler::userLabel($u ?: ['user_id' => (int) $l['owner_id']]);
        }
        $users = [];
        foreach ($ctx->app->links->visitors((int) $l['id'], 20) as $v) {
            $marks = ((int) $v['is_new'] === 1 ? '🆕' : '')
                . ((int) $v['has_channel'] === 1 ? '📢' : '') . ($v['first_post_at'] !== null ? '📝' : '')
                . ((int) $v['has_paid'] === 1 || in_array($v['plan_type'], ['pro', 'ultra'], true) ? '💎' : '');
            $users[] = '• ' . AdminHandler::userLabel($v) . ' ' . $marks . ' — ' . TimeParser::show((string) $v['first_at'], $ctx->tz());
        }
        $ctx->reply($ctx->t('link_detail', [
            'title' => Html::e((string) $l['title']), 'state' => $ctx->t((int) $l['is_active'] === 1 ? 'state_on' : 'state_off'),
            'url' => Html::e(self::url($ctx, (string) $l['code'])), 'owner' => $owner,
            'clicks' => (int) $l['clicks'], 'visitors' => (int) $l['visitors'], 'new' => (int) $l['new_users'],
            'ch' => (int) $l['with_channel'], 'posted' => (int) $l['posted'], 'paid' => (int) $l['paid'],
            'users' => $users ? implode("\n", $users) : $ctx->t('none'),
        ]));
    }

    private static function userSources(Ctx $ctx, array $args): void
    {
        if (!$args || !ctype_digit($args[0])) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/link_user ID']));
            return;
        }
        $id = (int) $args[0];
        $rows = $ctx->app->links->sourcesOf($id);
        if (!$rows) {
            $ctx->reply($ctx->t('link_user_none'));
            return;
        }
        $lines = [];
        foreach ($rows as $r) {
            $lines[] = '• <code>' . Html::e((string) $r['code']) . '</code> — ' . Html::e((string) $r['title']) . ((int) $r['is_new'] === 1 ? ' 🆕' : '')
                . ' · ' . TimeParser::show((string) $r['first_at'], $ctx->tz());
        }
        $ctx->reply($ctx->t('link_user_sources', ['id' => $id, 'lines' => implode("\n", $lines)]));
    }

    /** Havola egasi: faqat sonlar (kim kelgani — shaxsiy ma'lumot, faqat adminga). */
    public static function mine(Ctx $ctx): void
    {
        $rows = $ctx->app->links->listAll($ctx->userId, 50);
        if (!$rows) {
            $ctx->reply($ctx->t('mylinks_empty'));
            return;
        }
        $lines = [];
        foreach ($rows as $l) {
            $lines[] = self::line($l, false) . "\n    " . Html::e(self::url($ctx, (string) $l['code']));
        }
        $ctx->reply($ctx->t('mylinks_title', ['lines' => implode("\n", $lines)]));
    }
}
