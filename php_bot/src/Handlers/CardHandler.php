<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Receipts;
use PostAssist\Services\Plans;
use PostAssist\Services\TimeParser;

/**
 * 💳 Karta orqali to'lov (so'm): tarif -> muddat -> karta rekvizitlari -> chek (rasm/PDF) -> adminlarga -> ✅/❌.
 * So'm faqat tasdiqlangan O'zbekiston foydalanuvchisiga (o'z kontakti +998, raqam saqlanmaydi) yoki avval karta bilan to'laganga.
 * Boshqalar uchun — Telegram Stars. Yoqish: config.php `card_number` (+ `card_holder`).
 */
final class CardHandler
{
    public static function enabled(App $app): bool
    {
        return $app->config->str('card_number') !== '';
    }

    /** «💳 Karta (so'm)» bosildi. */
    public static function start(Ctx $ctx): void
    {
        $app = $ctx->app;
        if (!self::enabled($app)) {
            $ctx->reply($ctx->t('card_off'), Keyboards::nav($ctx->lang, 'pl:show'));
            return;
        }
        if ($app->isAdmin($ctx->userId) || $app->tier($ctx->userId) === Plans::ENTERPRISE) {
            $ctx->reply($ctx->t('pay_enterprise'), Keyboards::nav($ctx->lang, 'pl:show'));
            return;
        }
        if (!$app->users->isUzVerified($ctx->userId) && !$app->receipts->hasPaid($ctx->userId)) {
            $app->states->set($ctx->userId, 'uz_verify');
            $ctx->reply($ctx->t('uz_verify_ask'), [
                'keyboard' => [[['text' => $ctx->t('btn_share_phone'), 'request_contact' => true]], [['text' => $ctx->t('btn_cancel')]]],
                'resize_keyboard' => true, 'one_time_keyboard' => true,
            ]);
            return;
        }
        self::tiers($ctx);
    }

    /** O'z kontakti keldi (holat `uz_verify`). */
    public static function contact(Ctx $ctx): void
    {
        $c = $ctx->message['contact'] ?? null;
        $text = trim((string) ($ctx->message['text'] ?? ''));
        if ($c === null && $text === $ctx->t('btn_cancel')) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cancelled'));
            return;
        }
        if (!is_array($c)) {
            $ctx->reply($ctx->t('uz_verify_ask'));
            return;
        }
        if ((int) ($c['user_id'] ?? 0) !== $ctx->userId) {
            $ctx->reply($ctx->t('uz_verify_not_own')); // boshqa odam kontakti
            return;
        }
        $digits = (string) preg_replace('/\D+/', '', (string) ($c['phone_number'] ?? ''));
        $ctx->app->states->clear($ctx->userId);
        if (!preg_match('/^998\d{9}$/', $digits)) {
            $ctx->app->users->markPhoneVerified($ctx->userId);
            $ctx->replyMenu($ctx->t('uz_verify_foreign')); // raqam saqlanmaydi
            return;
        }
        $ctx->app->users->markUzVerified($ctx->userId);
        $ctx->replyMenu($ctx->t('uz_verify_ok'));
        self::tiers($ctx);
    }

    public static function tiers(Ctx $ctx): void
    {
        $uzs = Plans::uzs($ctx->app->config);
        $ctx->reply($ctx->t('card_pick_tier', ['pro' => Plans::fmtUzs($uzs['1m']), 'ultra' => Plans::fmtUzs($uzs['u1m'])]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_buy_pro'), 'pl:ct:pro'), Keyboards::btn($ctx->t('btn_buy_ultra'), 'pl:ct:ultra')],
            Keyboards::navRow($ctx->lang, 'pl:show'),
        ]));
    }

    public static function periods(Ctx $ctx, string $tier): void
    {
        $cat = Plans::catalog($ctx->app->config);
        $uzs = Plans::uzs($ctx->app->config);
        $prefix = $tier === Plans::ULTRA ? 'u' : '';
        $monthly = $uzs[$prefix . '1m'];
        $lines = [];
        $rows = [];
        foreach (Plans::PERIODS as [$period, $months]) {
            $key = $prefix . $period;
            $pct = Plans::discount($uzs[$key], $monthly, $months);
            $label = $ctx->t('period_' . $period);
            $lines[] = '• ' . $label . ': <b>' . Plans::fmtUzs($uzs[$key]) . '</b> ' . $ctx->t('som') . ($pct > 0 ? $ctx->t('plan_save', ['pct' => $pct]) : '');
            $rows[] = [Keyboards::btn($label . ' — ' . Plans::fmtUzs($uzs[$key]), 'pl:cb:' . $cat[$key]['key'])];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'pl:card');
        $icon = $tier === Plans::ULTRA ? '🚀' : '💎';
        $ctx->edit($ctx->t('card_periods', ['plan' => $icon . ' <b>' . Plans::NAMES[$tier] . '</b>', 'lines' => implode("\n", $lines)]), Keyboards::inline($rows));
    }

    /** Muddat tanlandi: rekvizitlar va chek kutish. */
    public static function details(Ctx $ctx, string $key): void
    {
        $app = $ctx->app;
        $plan = Plans::catalog($app->config)[$key] ?? null;
        if ($plan === null || !self::enabled($app)) {
            return;
        }
        $amount = Plans::uzs($app->config)[$key];
        $app->states->set($ctx->userId, 'receipt_wait', ['key' => $key, 'amount' => $amount]);
        $holder = $app->config->str('card_holder');
        $ctx->edit($ctx->t('card_pay_info', [
            'plan' => Plans::NAMES[$plan['tier']], 'period' => $ctx->t('period_' . $plan['period']), 'amount' => Plans::fmtUzs($amount),
            'card' => Html::e($app->config->str('card_number')), 'holder' => $holder !== '' ? Html::e($holder) : '—',
        ]), Keyboards::nav($ctx->lang, 'pl:ct:' . $plan['tier']));
    }

    /** Chek (rasm yoki PDF) keldi — holat `receipt_wait`. */
    public static function receipt(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $msg = $ctx->message ?? [];
        $type = null;
        $fileId = null;
        $unique = null;
        if (!empty($msg['photo']) && is_array($msg['photo'])) {
            $p = end($msg['photo']);
            $type = 'photo';
            $fileId = (string) ($p['file_id'] ?? '');
            $unique = (string) ($p['file_unique_id'] ?? '');
        } elseif (!empty($msg['document']['file_id'])) {
            $d = $msg['document'];
            $mime = strtolower((string) ($d['mime_type'] ?? ''));
            if (($mime === 'application/pdf' || strpos($mime, 'image/') === 0) && (int) ($d['file_size'] ?? 0) <= 10485760) {
                $type = 'document';
                $fileId = (string) $d['file_id'];
                $unique = (string) ($d['file_unique_id'] ?? '');
            }
        }
        if ($type === null || $fileId === '') {
            $ctx->reply($ctx->t('receipt_bad_media'), Keyboards::nav($ctx->lang, 'pl:show'));
            return;
        }
        $plan = Plans::catalog($app->config)[(string) ($state['data']['key'] ?? '')] ?? null;
        $amount = (int) ($state['data']['amount'] ?? 0);
        if ($plan === null || $amount <= 0) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if ($app->receipts->pendingCount($ctx->userId) >= Receipts::MAX_PENDING) {
            $ctx->reply($ctx->t('receipt_too_many', ['n' => Receipts::MAX_PENDING]), Keyboards::nav($ctx->lang));
            return;
        }
        if (!$app->states->take($ctx->userId, 'receipt_wait')) {
            return; // parallel ikkinchi so'rov
        }
        $id = $app->receipts->create($ctx->userId, $plan, $amount, $type, $fileId, $unique !== '' ? $unique : null, $app->now());
        $dups = $app->receipts->duplicates($unique !== '' ? $unique : null, $id);
        $name = Html::e($ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId);
        $u = $app->users->get($ctx->userId);
        $handle = !empty($u['username']) ? ' @' . Html::e((string) $u['username']) : '';
        foreach ((array) $app->config->get('admin_ids') as $adminId) {
            $adminId = (int) $adminId;
            if ($adminId === $ctx->userId) {
                continue;
            }
            $au = $app->users->get($adminId);
            $lang = I18n::norm($au['lang'] ?? 'uz');
            $caption = I18n::t('receipt_admin_caption', $lang, [
                'id' => $id, 'user' => $name . $handle . ' (<code>' . $ctx->userId . '</code>)', 'plan' => Plans::NAMES[$plan['tier']],
                'period' => I18n::t('period_' . $plan['period'], $lang), 'amount' => Plans::fmtUzs($amount),
                'when' => TimeParser::show($app->nowSql(), $app->tzFor($adminId)),
                'dup' => $dups ? "\n" . I18n::t('receipt_dup_line', $lang, ['id' => $dups[0]['id'], 'status' => Html::e((string) $dups[0]['status'])]) : '',
            ]);
            $kb = Keyboards::inline([[Keyboards::btn(I18n::t('btn_rc_ok', $lang), 'rc:ok:' . $id), Keyboards::btn(I18n::t('btn_rc_no', $lang), 'rc:no:' . $id)]]);
            $app->tg->call($type === 'photo' ? 'sendPhoto' : 'sendDocument', ['chat_id' => $adminId, $type === 'photo' ? 'photo' : 'document' => $fileId,
                'caption' => $caption, 'parse_mode' => 'HTML', 'reply_markup' => $kb]);
        }
        $ctx->replyMenu($ctx->t('receipt_saved', ['id' => $id]));
    }

    /** Admin ✅/❌ bosdi. */
    public static function decide(Ctx $ctx, string $act, int $id): void
    {
        $app = $ctx->app;
        if (!$app->isAdmin($ctx->userId)) {
            return;
        }
        $r = $app->receipts->decide($id, $act === 'ok', $ctx->userId, $app->now());
        $msg = $ctx->callback['message'] ?? [];
        $clear = static function (string $note) use ($ctx, $msg): void {
            if (!empty($msg['message_id'])) {
                $ctx->app->tg->call('editMessageReplyMarkup', ['chat_id' => $ctx->chatId, 'message_id' => (int) $msg['message_id'], 'reply_markup' => ['inline_keyboard' => []]]);
            }
            $ctx->reply($note);
        };
        switch ($r['status']) {
            case 'not_found':
                $ctx->reply($ctx->t('receipt_not_found'));
                return;
            case 'already':
                $clear($ctx->t('receipt_already', ['id' => $id]));
                return;
            case 'grant_failed':
                $ctx->reply($ctx->t('receipt_grant_failed', ['id' => $id]));
                return;
        }
        $rec = $r['receipt'];
        $uid = (int) $rec['user_id'];
        $user = $app->users->get($uid);
        $lang = I18n::norm($user['lang'] ?? 'uz');
        if ($r['status'] === 'ok') {
            $date = $r['tier'] === Plans::ENTERPRISE ? '♾' : TimeParser::show((string) $r['expires'], $app->tzFor($uid));
            $app->tg->sendMessage($uid, I18n::t($r['kept'] ? 'pay_kept' : 'pay_ok', $lang, ['plan' => Plans::NAMES[$r['tier']] ?? $r['tier'], 'date' => $date,
                'tz' => Html::e($app->tzFor($uid)->getName())]));
            $clear($ctx->t('receipt_done_ok', ['id' => $id]));
            return;
        }
        $app->tg->sendMessage($uid, I18n::t('receipt_user_rejected', $lang, ['id' => $id]));
        $clear($ctx->t('receipt_done_no', ['id' => $id]));
    }
}
