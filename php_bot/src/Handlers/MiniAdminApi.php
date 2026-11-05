<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Services\Plans;
use PostAssist\Services\TimeParser;

/**
 * 👑 Mini App super admin paneli (faqat config `admin_ids`). Har amal 403 `admin_only` bilan himoyalangan.
 * Bot admin buyruqlari bilan bir xil manba: statistika, tarif berish, promo-kodlar, karta cheklari, birja bloklash.
 * Hammaga xabar (broadcast) va majburiy obuna — faqat botda (xabarni nusxalash Telegram ichida qulayroq).
 */
final class MiniAdminApi
{
    /** @return array{0:int,1:array} */
    public static function handle(Ctx $ctx, string $action, array $in): array
    {
        $app = $ctx->app;
        if (!$app->isAdmin($ctx->userId)) {
            return [403, ['ok' => false, 'error' => 'admin_only']];
        }
        switch ($action) {
            case 'admin_stats':
                return [200, self::stats($ctx)];
            case 'admin_grant':
                return self::grant($ctx, $in);
            case 'admin_promos':
                return [200, ['ok' => true, 'promos' => array_map(static function ($p) {
                    return ['code' => (string) $p['code'], 'tier' => (string) $p['plan_type'], 'days' => (int) $p['duration_days'],
                        'used' => (int) $p['current_uses'], 'max' => $p['max_uses'] !== null ? (int) $p['max_uses'] : null, 'active' => (int) $p['is_active'] === 1];
                }, $app->promos->listAll(100))]];
            case 'admin_promo_create':
                $max = isset($in['max']) && $in['max'] !== '' && $in['max'] !== null ? (int) $in['max'] : null;
                $r = $app->promos->create((string) ($in['code'] ?? ''), (string) ($in['tier'] ?? 'pro'), (int) ($in['days'] ?? 0), $max, $ctx->userId, $app->now());
                return $r['ok'] ? [200, ['ok' => true, 'code' => $r['code']]] : [400, ['ok' => false, 'error' => 'promo_' . $r['error']]];
            case 'admin_promo_toggle':
                $ok = $app->promos->setActive((string) ($in['code'] ?? ''), !empty($in['active']));
                return $ok ? [200, ['ok' => true]] : [404, ['ok' => false, 'error' => 'not_found']];
            case 'admin_receipts':
                return [200, ['ok' => true, 'receipts' => array_map(static function ($r) use ($ctx) {
                    $u = $ctx->app->users->get((int) $r['user_id']) ?? [];
                    return ['id' => (int) $r['id'], 'user_id' => (int) $r['user_id'], 'user' => trim((string) ($u['full_name'] ?? '') . (!empty($u['username']) ? ' @' . $u['username'] : '')),
                        'plan' => Plans::NAMES[$r['tier']] ?? $r['tier'], 'days' => (int) $r['days'], 'amount' => Plans::fmtUzs((int) $r['amount_uzs']),
                        'at' => TimeParser::show((string) $r['created_at'], $ctx->tz())];
                }, $app->receipts->pendingList(30))]];
            case 'admin_receipt':
                return self::receipt($ctx, (int) ($in['id'] ?? 0), !empty($in['approve']));
            case 'admin_user':
                return self::user($ctx, (int) ($in['id'] ?? 0));
            case 'admin_market_ban':
                $id = (int) ($in['id'] ?? 0);
                if (!$app->users->exists($id)) {
                    return [404, ['ok' => false, 'error' => 'not_found']];
                }
                $app->market->banUser($id, !empty($in['ban']));
                return [200, ['ok' => true]];
        }
        return [404, ['ok' => false, 'error' => 'unknown_action']];
    }

    private static function stats(Ctx $ctx): array
    {
        $app = $ctx->app;
        $db = $app->db;
        $today = $app->now()->setTimezone($app->tz())->setTime(0, 0, 0)->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        $now = $app->nowSql();
        $pay = $app->payments->totalsSince($today);
        $card = $app->receipts->totalsSince($today);
        $days = [];
        for ($i = 6; $i >= 0; $i--) {
            $from = $app->now()->setTimezone($app->tz())->setTime(0, 0, 0)->modify('-' . $i . ' days');
            $to = $from->modify('+1 day');
            $days[] = ['day' => $from->format('d.m'), 'n' => (int) $db->value('SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ?',
                [$from->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s'), $to->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s')])];
        }
        return ['ok' => true,
            'users' => (int) $db->value('SELECT COUNT(*) FROM users'),
            'users_today' => (int) $db->value('SELECT COUNT(*) FROM users WHERE created_at >= ?', [$today]),
            'channels' => (int) $db->value('SELECT COUNT(*) FROM channels WHERE is_active = 1'),
            'pending' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status IN ('pending', 'processing')"),
            'sent_today' => (int) $db->value("SELECT COUNT(*) FROM sent_messages WHERE created_at >= ?", [$today]),
            'failed_today' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed' AND created_at >= ?", [$today]),
            'pro' => (int) $db->value("SELECT COUNT(*) FROM users WHERE plan_type = 'pro' AND subscription_expires_at > ?", [$now]),
            'ultra' => (int) $db->value("SELECT COUNT(*) FROM users WHERE plan_type = 'ultra' AND subscription_expires_at > ?", [$now]),
            'stars_today' => $pay['stars'], 'pays_today' => $pay['count'], 'card_today' => Plans::fmtUzs($card['uzs']), 'card_count' => $card['count'],
            'pending_receipts' => (int) $db->value("SELECT COUNT(*) FROM payment_receipts WHERE status = 'pending'"),
            'new_users' => $days];
    }

    private static function grant(Ctx $ctx, array $in): array
    {
        $app = $ctx->app;
        $id = (int) ($in['user_id'] ?? 0);
        $tier = (string) ($in['tier'] ?? Plans::PRO);
        $days = (int) ($in['days'] ?? 0);
        if (!$app->users->exists($id)) {
            return [404, ['ok' => false, 'error' => 'user_unknown']];
        }
        $r = Plans::grant($app->db, $id, $tier, $days, $app->now());
        if (!$r['ok']) {
            return [400, ['ok' => false, 'error' => 'bad_grant']];
        }
        if ($r['tier'] !== Plans::ENTERPRISE) {
            $u = $app->users->get($id);
            $lang = I18n::norm($u['lang'] ?? 'uz');
            $app->tg->sendMessage($id, I18n::t('grant_notice', $lang, ['plan' => Plans::NAMES[$r['tier']],
                'date' => TimeParser::show((string) $r['expires'], $app->tzFor($id)), 'tz' => Html::e($app->tzFor($id)->getName())]));
        }
        return [200, ['ok' => true, 'tier' => $r['tier'], 'expires' => $r['tier'] === Plans::ENTERPRISE ? '♾' : TimeParser::show((string) $r['expires'], $ctx->tz())]];
    }

    private static function receipt(Ctx $ctx, int $id, bool $approve): array
    {
        $app = $ctx->app;
        $r = $app->receipts->decide($id, $approve, $ctx->userId, $app->now());
        if ($r['status'] === 'not_found') {
            return [404, ['ok' => false, 'error' => 'not_found']];
        }
        if ($r['status'] === 'already' || $r['status'] === 'grant_failed') {
            return [409, ['ok' => false, 'error' => 'receipt_' . $r['status']]];
        }
        CardHandler::notifyDecision($app, $r);
        return [200, ['ok' => true, 'status' => $r['status']]];
    }

    private static function user(Ctx $ctx, int $id): array
    {
        $app = $ctx->app;
        $u = $app->users->get($id);
        if (!$u) {
            return [404, ['ok' => false, 'error' => 'user_unknown']];
        }
        $plan = $app->users->plan($id);
        $tier = $app->isAdmin($id) ? Plans::ENTERPRISE : $app->tier($id);
        $s = $app->posts->userStats($id);
        return [200, ['ok' => true, 'user' => ['id' => $id, 'name' => (string) ($u['full_name'] ?? ''), 'username' => (string) ($u['username'] ?? ''),
            'lang' => (string) $u['lang'], 'tier' => Plans::NAMES[$tier], 'expires' => !empty($plan['subscription_expires_at']) ? TimeParser::show((string) $plan['subscription_expires_at'], $ctx->tz()) : null,
            'channels' => $app->channels->countFor($id), 'pending' => $s['pending'], 'sent' => $s['sent'], 'credits' => $app->credits->balance($id),
            'market_banned' => $app->market->isBanned($id), 'blocked' => (int) ($u['is_blocked'] ?? 0) === 1,
            'joined' => TimeParser::show((string) $u['created_at'], $ctx->tz())]]];
    }
}
