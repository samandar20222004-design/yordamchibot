<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Promos;
use PostAssist\Services\Plans;
use PostAssist\Services\TimeParser;

/** Admin panel va buyruqlari (faqat config.php dagi admin_ids). */
final class AdminHandler
{
    public static function show(Ctx $ctx): void
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return;
        }
        $db = $ctx->app->db;
        // «bugun» — bot mintaqasidagi kun boshi (UTC'ga o'tkazilgan)
        $today = $ctx->app->now()->setTimezone($ctx->app->tz())->setTime(0, 0, 0)->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d H:i:s');
        $now = $ctx->app->nowSql();
        $pay = $ctx->app->payments->totalsSince($today);
        $card = $ctx->app->receipts->totalsSince($today);
        $ctx->reply($ctx->t('admin_stats', [
            'users' => (int) $db->value('SELECT COUNT(*) FROM users'),
            'users_today' => (int) $db->value('SELECT COUNT(*) FROM users WHERE created_at >= ?', [$today]),
            'channels' => (int) $db->value('SELECT COUNT(*) FROM channels WHERE is_active = 1'),
            'pending' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status IN ('pending', 'processing')"),
            'sent_today' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'sent' AND sent_at >= ?", [$today]),
            'failed_today' => (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed' AND created_at >= ?", [$today]),
            'pro' => (int) $db->value("SELECT COUNT(*) FROM users WHERE plan_type = 'pro' AND subscription_expires_at > ?", [$now]),
            'ultra' => (int) $db->value("SELECT COUNT(*) FROM users WHERE plan_type = 'ultra' AND subscription_expires_at > ?", [$now]),
            'stars_today' => $pay['stars'], 'pays_today' => $pay['count'],
            'card_today' => Plans::fmtUzs($card['uzs']), 'card_count' => $card['count'],
            'pending_receipts' => (int) $db->value("SELECT COUNT(*) FROM payment_receipts WHERE status = 'pending'"),
        ]), Keyboards::admin($ctx->lang));
    }

    /** Admin buyruqlari. Admin bo'lmasa yoki buyruq noma'lum bo'lsa false (Router «tushunmadim» deydi). */
    public static function command(Ctx $ctx, string $cmd, array $args): bool
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return false;
        }
        switch ($cmd) {
            case '/admin_help':
                $ctx->reply($ctx->t('admin_help') . "\n\n" . $ctx->t('admin_help2'), Keyboards::nav($ctx->lang, 'a:stats'));
                return true;
            case '/broadcast':
                BroadcastHandler::start($ctx);
                return true;
            case '/broadcast_status':
                BroadcastHandler::status($ctx);
                return true;
            case '/broadcast_stop':
                BroadcastHandler::stop($ctx);
                return true;
            case '/force_list':
                ForceSubHandler::listAll($ctx);
                return true;
            case '/force_add':
                ForceSubHandler::add($ctx, $args);
                return true;
            case '/force_del':
                ForceSubHandler::remove($ctx, $args);
                return true;
            case '/receipts':
                self::receipts($ctx);
                return true;
            case '/grant_pro':
                self::grant($ctx, $args);
                return true;
            case '/create_promo':
                self::createPromo($ctx, $args);
                return true;
            case '/promos':
                self::promos($ctx);
                return true;
            case '/promo':
                if (!$args) {
                    return false; // Router oddiy foydalanuvchi kabi promo so'raydi
                }
                self::promo($ctx, $args[0]);
                return true;
            case '/promo_off':
            case '/promo_on':
                if (!$args) {
                    $ctx->reply($ctx->t('admin_usage', ['usage' => $cmd . ' KOD']));
                    return true;
                }
                $on = $cmd === '/promo_on';
                $ok = $ctx->app->promos->setActive($args[0], $on);
                $ctx->reply($ok ? $ctx->t('toggled', ['code' => Html::e((string) Promos::normalize($args[0])), 'state' => $ctx->t($on ? 'state_on' : 'state_off')]) : $ctx->t('promo_none'));
                return true;
            case '/promo_del':
                self::promoDelete($ctx, $args);
                return true;
        }
        return LinksHandler::adminCommand($ctx, $cmd, $args);
    }

    /** Hali ko'rib chiqilmagan cheklar (admin xabarini yo'qotib qo'ygan bo'lsa). */
    private static function receipts(Ctx $ctx): void
    {
        $list = $ctx->app->receipts->pendingList(10);
        if (!$list) {
            $ctx->reply($ctx->t('receipts_none'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        foreach ($list as $r) {
            $kb = Keyboards::inline([[Keyboards::btn($ctx->t('btn_rc_ok'), 'rc:ok:' . (int) $r['id']), Keyboards::btn($ctx->t('btn_rc_no'), 'rc:no:' . (int) $r['id'])]]);
            $cap = $ctx->t('receipt_admin_caption', ['id' => (int) $r['id'], 'user' => '<code>' . (int) $r['user_id'] . '</code>', 'plan' => Plans::NAMES[$r['tier']] ?? Html::e((string) $r['tier']),
                'period' => (int) $r['days'] . ' ' . $ctx->t('days_short'), 'amount' => Plans::fmtUzs((int) $r['amount_uzs']), 'when' => TimeParser::show((string) $r['created_at'], $ctx->tz()), 'dup' => '']);
            $ctx->app->tg->call($r['media_type'] === 'photo' ? 'sendPhoto' : 'sendDocument', ['chat_id' => $ctx->chatId, $r['media_type'] === 'photo' ? 'photo' : 'document' => $r['file_id'],
                'caption' => $cap, 'parse_mode' => 'HTML', 'reply_markup' => $kb]);
        }
    }

    private static function grant(Ctx $ctx, array $args): void
    {
        if (count($args) < 2 || !ctype_digit($args[0]) || !preg_match('/^\d{1,5}$/', $args[1])) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/grant_pro ID KUN [pro|ultra]']));
            return;
        }
        $id = (int) $args[0];
        $days = (int) $args[1];
        $tier = strtolower($args[2] ?? Plans::PRO);
        if (!$ctx->app->users->exists($id)) {
            $ctx->reply($ctx->t('admin_user_unknown', ['id' => $id]));
            return;
        }
        $r = Plans::grant($ctx->app->db, $id, $tier, $days, $ctx->app->now());
        if (!$r['ok']) {
            $ctx->reply($ctx->t('admin_bad_days'));
            return;
        }
        $date = $r['tier'] === Plans::ENTERPRISE ? '♾' : TimeParser::show((string) $r['expires'], $ctx->tz());
        $userDate = $r['tier'] === Plans::ENTERPRISE ? '♾' : TimeParser::show((string) $r['expires'], $ctx->app->tzFor($id));
        $ctx->reply($ctx->t('admin_grant_ok', ['id' => $id, 'plan' => Plans::NAMES[$r['tier']], 'date' => $date]));
        if ($r['tier'] !== Plans::ENTERPRISE) {
            $u = $ctx->app->users->get($id);
            $lang = I18n::norm($u['lang'] ?? 'uz');
            $ctx->app->tg->sendMessage($id, I18n::t('grant_notice', $lang, ['plan' => Plans::NAMES[$r['tier']], 'date' => $userDate, 'tz' => Html::e($ctx->app->tzFor($id)->getName())]));
        }
    }

    private static function createPromo(Ctx $ctx, array $args): void
    {
        $usage = '/create_promo KOD KUN [LIMIT] [pro|ultra]';
        if (count($args) < 2 || !preg_match('/^\d{1,5}$/', $args[1])) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => $usage]));
            return;
        }
        $max = null;
        $tier = Plans::PRO;
        foreach (array_slice($args, 2) as $a) {
            $low = strtolower($a);
            if ($low === Plans::PRO || $low === Plans::ULTRA) {
                $tier = $low;
            } elseif (ctype_digit($a)) {
                $max = (int) $a;
            } else {
                $ctx->reply($ctx->t('admin_usage', ['usage' => $usage]));
                return;
            }
        }
        $r = $ctx->app->promos->create($args[0], $tier, (int) $args[1], $max, $ctx->userId, $ctx->app->now());
        if (!$r['ok']) {
            $ctx->reply($ctx->t($r['error'] === 'bad_plan' ? 'admin_bad_days' : 'promo_err_' . $r['error']));
            return;
        }
        $ctx->reply($ctx->t('promo_created', ['code' => Html::e($r['code']), 'plan' => Plans::NAMES[$tier], 'days' => (int) $args[1],
            'max' => $max === null ? $ctx->t('unlimited') : $max]));
    }

    private static function promos(Ctx $ctx): void
    {
        $rows = $ctx->app->promos->listAll(50);
        if (!$rows) {
            $ctx->reply($ctx->t('promos_empty'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        $lines = [];
        foreach ($rows as $p) {
            $lines[] = ((int) $p['is_active'] === 1 ? '✅' : '⛔️') . ' <code>' . Html::e((string) $p['code']) . '</code> · '
                . (Plans::NAMES[$p['plan_type']] ?? Html::e((string) $p['plan_type'])) . ' ' . (int) $p['duration_days'] . ' ' . $ctx->t('days_short')
                . ' · ' . (int) $p['current_uses'] . '/' . ($p['max_uses'] === null ? '∞' : (int) $p['max_uses']);
        }
        $ctx->reply($ctx->t('promos_title', ['n' => count($rows), 'lines' => implode("\n", $lines)]), Keyboards::nav($ctx->lang, 'a:stats'));
    }

    private static function promo(Ctx $ctx, string $code): void
    {
        $p = $ctx->app->promos->get($code);
        if (!$p) {
            $ctx->reply($ctx->t('promo_none'));
            return;
        }
        $users = [];
        foreach ($ctx->app->promos->recentRedemptions((int) $p['id']) as $r) {
            $users[] = '• ' . self::userLabel($r) . ' — ' . TimeParser::show((string) $r['redeemed_at'], $ctx->tz());
        }
        $ctx->reply($ctx->t('promo_detail', [
            'code' => Html::e((string) $p['code']), 'state' => $ctx->t((int) $p['is_active'] === 1 ? 'state_on' : 'state_off'),
            'plan' => Plans::NAMES[$p['plan_type']] ?? Html::e((string) $p['plan_type']), 'days' => (int) $p['duration_days'],
            'used' => (int) $p['current_uses'], 'max' => $p['max_uses'] === null ? '∞' : (int) $p['max_uses'],
            'created' => TimeParser::show((string) $p['created_at'], $ctx->tz()),
            'users' => $users ? implode("\n", $users) : $ctx->t('none'),
        ]));
    }

    private static function promoDelete(Ctx $ctx, array $args): void
    {
        if (!$args) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => '/promo_del KOD ok']));
            return;
        }
        $p = $ctx->app->promos->get($args[0]);
        if (!$p) {
            $ctx->reply($ctx->t('promo_none'));
            return;
        }
        $code = Html::e((string) $p['code']);
        if (strtolower($args[1] ?? '') !== 'ok') {
            $ctx->reply($ctx->t('promo_del_ask', ['code' => $code]));
            return;
        }
        $ctx->app->promos->delete((string) $p['code']);
        $ctx->reply($ctx->t('promo_deleted', ['code' => $code]));
    }

    /** «Ism (@username, ID)» — hammasi escape qilingan. */
    public static function userLabel(array $r): string
    {
        $name = trim((string) ($r['full_name'] ?? ''));
        $out = $name !== '' ? Html::e(mb_substr($name, 0, 40)) . ' ' : '';
        if (!empty($r['username'])) {
            $out .= '@' . Html::e((string) $r['username']) . ' ';
        }
        return $out . '<code>' . (int) $r['user_id'] . '</code>';
    }
}
