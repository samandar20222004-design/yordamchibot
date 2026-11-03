<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Credits;
use PostAssist\Repo\Payments;
use PostAssist\Services\Plans;
use PostAssist\Services\TimeParser;

/**
 * Tariflar (FREE/PRO/ULTRA), Telegram Stars to'lovi, promo-kod va do'stlarni taklif qilish.
 * To'lov oqimi: tarif -> muddat -> sendInvoice (XTR) -> pre_checkout_query (tekshiruv) -> successful_payment (tarif beriladi).
 */
final class PlansHandler
{
    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $app = $ctx->app;
        $tier = $app->isAdmin($ctx->userId) ? Plans::ENTERPRISE : $app->tier($ctx->userId);
        $row = $app->users->plan($ctx->userId);
        $until = '';
        if ($tier === Plans::ENTERPRISE) {
            $until = $ctx->t('plan_forever');
        } elseif ($tier !== Plans::FREE && !empty($row['subscription_expires_at'])) {
            $until = $ctx->t('plan_until', ['date' => TimeParser::show((string) $row['subscription_expires_at'], $app->tz())]);
        }
        $lim = static function (string $t, string $k) use ($app): int {
            return Plans::limits($t, $app->config)[$k];
        };
        $text = $ctx->t('plans_title', [
            'plan' => Plans::NAMES[$tier], 'until' => $until,
            'free_ch' => $lim('free', 'channels'), 'free_q' => $lim('free', 'queue'),
            'pro_ch' => $lim('pro', 'channels'), 'pro_q' => $lim('pro', 'queue'),
            'ultra_ch' => $lim('ultra', 'channels'), 'ultra_q' => $lim('ultra', 'queue'),
        ]);
        $kb = $tier === Plans::ENTERPRISE ? null : Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_buy_pro'), 'pl:t:pro'), Keyboards::btn($ctx->t('btn_buy_ultra'), 'pl:t:ultra')],
            [Keyboards::btn($ctx->t('btn_promo'), 'promo:ask')],
        ]);
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    /** Tanlangan tarifning muddatlari (narx va tejam bilan). */
    public static function periods(Ctx $ctx, string $tier): void
    {
        $cat = Plans::catalog($ctx->app->config);
        $prefix = $tier === Plans::ULTRA ? 'u' : '';
        $monthly = $cat[$prefix . '1m']['stars'];
        $lines = [];
        $rows = [];
        foreach (Plans::PERIODS as [$period, $months]) {
            $p = $cat[$prefix . $period];
            $pct = Plans::discount($p['stars'], $monthly, $months);
            $label = $ctx->t('period_' . $period);
            $lines[] = '• ' . $label . ': <b>' . $p['stars'] . '⭐</b>' . ($pct > 0 ? $ctx->t('plan_save', ['pct' => $pct]) : '');
            $rows[] = [Keyboards::btn(self::periodButton($label, $p['stars']), 'pl:b:' . $p['key'])];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_back'), 'pl:show')];
        $icon = $tier === Plans::ULTRA ? '🚀' : '💎';
        $ctx->edit($ctx->t('plans_periods', ['plan' => $icon . ' <b>' . Plans::NAMES[$tier] . '</b>', 'lines' => implode("\n", $lines)]), Keyboards::inline($rows));
    }

    public static function periodButton(string $label, int $stars): string
    {
        return $label . ' — ' . $stars . '⭐';
    }

    /** To'lov oynasi (Telegram Stars). */
    public static function invoice(Ctx $ctx, string $key): void
    {
        $app = $ctx->app;
        $plan = Plans::catalog($app->config)[$key] ?? null;
        if ($plan === null) {
            return;
        }
        if ($app->isAdmin($ctx->userId) || $app->tier($ctx->userId) === Plans::ENTERPRISE) {
            $ctx->reply($ctx->t('pay_enterprise'));
            return;
        }
        $name = Plans::NAMES[$plan['tier']];
        $period = $ctx->t('period_' . $plan['period']);
        $lim = Plans::limits($plan['tier'], $app->config);
        $res = $app->tg->call('sendInvoice', [
            'chat_id' => $ctx->chatId,
            'title' => mb_substr($ctx->t('invoice_title', ['plan' => $name, 'period' => $period]), 0, 32),
            'description' => mb_substr($ctx->t('invoice_desc', ['plan' => $name, 'period' => $period, 'channels' => $lim['channels'], 'queue' => $lim['queue']]), 0, 255),
            'payload' => Payments::payload($plan['key'], $ctx->userId),
            'provider_token' => '',
            'currency' => 'XTR',
            'prices' => [['label' => $name . ' · ' . $period, 'amount' => $plan['stars']]],
        ]);
        if (empty($res['ok'])) {
            $app->log('sendInvoice: ' . ($res['description'] ?? ''));
            $ctx->reply($ctx->t('send_fail', ['reason' => $ctx->t('reason_network')]));
        }
    }

    /** pre_checkout_query: Telegram 10 soniya kutadi — faqat tekshiruv, bazaga yozilmaydi. */
    public static function preCheckout(App $app, array $q): void
    {
        $from = (int) ($q['from']['id'] ?? 0);
        $v = Payments::validate($app->config, (string) ($q['invoice_payload'] ?? ''), (string) ($q['currency'] ?? ''), (int) ($q['total_amount'] ?? 0), $from);
        if ($v['ok'] && $from > 0 && !$app->isAdmin($from) && $app->tier($from) !== Plans::ENTERPRISE) {
            $app->tg->call('answerPreCheckoutQuery', ['pre_checkout_query_id' => (string) ($q['id'] ?? ''), 'ok' => true]);
            return;
        }
        $user = $from > 0 ? $app->users->get($from) : null;
        $lang = I18n::norm($user['lang'] ?? I18n::detect($q['from']['language_code'] ?? null));
        $app->tg->call('answerPreCheckoutQuery', ['pre_checkout_query_id' => (string) ($q['id'] ?? ''), 'ok' => false,
            'error_message' => I18n::t(($v['ok'] ? 'pay_enterprise' : 'precheckout_error'), $lang)]);
    }

    /** successful_payment: tarif beriladi (bir to'lov — bir marta). */
    public static function paid(Ctx $ctx, array $sp): void
    {
        $app = $ctx->app;
        $r = $app->payments->processStars($app->config, $ctx->userId, $sp, $app->now());
        if ($r['status'] === 'invalid') {
            $app->log('to\'lov mos emas: user ' . $ctx->userId . ' ' . ($r['error'] ?? '') . ' ' . json_encode($sp));
            $ctx->replyMenu($ctx->t('pay_invalid'));
            self::notifyAdmins($app, 'admin_pay_problem', ['id' => $ctx->userId, 'error' => Html::e((string) ($r['error'] ?? '')),
                'payload' => Html::e((string) ($sp['invoice_payload'] ?? ''))]);
            return;
        }
        if ($r['status'] === 'duplicate') {
            $ctx->replyMenu($ctx->t('pay_duplicate', ['plan' => Plans::NAMES[$app->tier($ctx->userId)]]));
            return;
        }
        $ctx->replyMenu(self::planResult($ctx, $r['kept'] ? 'pay_kept' : 'pay_ok', $r['tier'], (string) $r['expires']));
        $plan = $r['plan'];
        self::notifyAdmins($app, 'admin_pay_notice', [
            'user' => Html::e($ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId), 'id' => $ctx->userId,
            'plan' => Plans::NAMES[$plan['tier']], 'period' => '{period_' . $plan['period'] . '}', 'stars' => $plan['stars'],
        ]);
    }

    /** Tarif natijasi matni (muddatsiz tarifda sana o'rniga ♾). */
    public static function planResult(Ctx $ctx, string $key, string $tier, string $expires): string
    {
        $date = $tier === Plans::ENTERPRISE || $expires === '' ? '♾' : TimeParser::show($expires, $ctx->app->tz());
        return $ctx->t($key, ['plan' => Plans::NAMES[$tier] ?? $tier, 'date' => $date, 'tz' => Html::e($ctx->app->tzName())]);
    }

    // ------------------------------------------------------------------ promo-kod

    public static function askPromo(Ctx $ctx): void
    {
        if ($ctx->app->isAdmin($ctx->userId) || $ctx->app->tier($ctx->userId) === Plans::ENTERPRISE) {
            $ctx->reply($ctx->t('promo_enterprise'));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'promo_wait');
        $ctx->reply($ctx->t('promo_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    public static function redeem(Ctx $ctx, string $code): void
    {
        $app = $ctx->app;
        if ($app->isAdmin($ctx->userId) || $app->tier($ctx->userId) === Plans::ENTERPRISE) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('promo_enterprise')); // muddatsiz tarifda kod bekorga sarflanmasin
            return;
        }
        $r = $app->promos->redeem($ctx->userId, $code, $app->now());
        if ($r['status'] === 'ok') {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu(self::planResult($ctx, $r['kept'] ? 'promo_kept' : 'promo_ok', $r['tier'], (string) $r['expires']));
            return;
        }
        if ($r['status'] !== 'not_found') {
            $app->states->clear($ctx->userId); // qayta yozish foyda bermaydi
        }
        $ctx->reply($ctx->t('promo_' . $r['status']));
    }

    // ------------------------------------------------------------------ do'stlarni taklif qilish

    public static function referral(Ctx $ctx, bool $edit = false): void
    {
        $app = $ctx->app;
        $link = 'https://t.me/' . $app->config->str('bot_username') . '?start=ref_' . $ctx->userId;
        $s = $app->credits->referralStats($ctx->userId);
        $text = $ctx->t('ref_title', ['link' => Html::e($link), 'top' => Credits::TOP_REWARD, 'base' => Credits::BASE_REWARD,
            'invited' => $s['invited'], 'active' => $s['active'], 'earned' => $s['earned'], 'balance' => $app->credits->balance($ctx->userId)]);
        $share = 'https://t.me/share/url?url=' . rawurlencode($link) . '&text=' . rawurlencode($ctx->t('share_text'));
        $kb = Keyboards::inline([[['text' => $ctx->t('btn_share'), 'url' => $share]]]);
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    /** Do'st birinchi postini qildi — taklif qiluvchiga xabar. */
    public static function notifyReward(App $app, array $r, string $friendName): void
    {
        $user = $app->users->get((int) $r['referrer']);
        if (!$user || (int) $user['is_blocked'] === 1) {
            return;
        }
        $lang = I18n::norm($user['lang'] ?? 'uz');
        $app->tg->sendMessage((int) $r['referrer'], I18n::t('ref_reward_notice', $lang, [
            'name' => Html::e($friendName), 'reward' => $r['reward'], 'balance' => $r['balance'],
        ]));
    }

    /**
     * Hamma adminlarga xabar (har biri o'z tilida). Qiymatdagi `{period_1m}` kabi kalitlar admin tiliga o'giriladi.
     * @param array<string, string|int> $params
     */
    public static function notifyAdmins(App $app, string $key, array $params): void
    {
        foreach ((array) $app->config->get('admin_ids') as $adminId) {
            $u = $app->users->get((int) $adminId);
            $lang = I18n::norm($u['lang'] ?? 'uz');
            $p = [];
            foreach ($params as $k => $v) {
                $p[$k] = is_string($v) && preg_match('/^\{(period_\w+)\}$/', $v, $m) ? I18n::t($m[1], $lang) : $v;
            }
            $app->tg->sendMessage((int) $adminId, I18n::t($key, $lang, $p));
        }
    }
}
