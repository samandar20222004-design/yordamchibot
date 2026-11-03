<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;

final class AdminHandler
{
    public static function show(Ctx $ctx): void
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return;
        }
        $db = $ctx->app->db;
        // «bugun» — foydalanuvchi mintaqasidagi kun boshi (UTC'ga o'tkazilgan)
        $today = $ctx->app->now()->setTimezone($ctx->app->tz())->setTime(0, 0, 0)->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        $ctx->replyMenu($ctx->t('admin_stats', [
            'users' => (int) $db->value('SELECT COUNT(*) FROM users'),
            'users_today' => (int) $db->value('SELECT COUNT(*) FROM users WHERE created_at >= ?', [$today]),
            'channels' => (int) $db->value('SELECT COUNT(*) FROM channels WHERE is_active = 1'),
            'pending' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status IN ('pending', 'processing')"),
            'sent_today' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'sent' AND sent_at >= ?", [$today]),
            'failed_today' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed' AND created_at >= ?", [$today]),
        ]));
    }
}
