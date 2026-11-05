<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\I18n;
use PostAssist\Keyboards;

/**
 * 📣 Hammaga xabar (faqat adminlar). Admin istalgan xabarni (matn, rasm, video, formatlash, tugma) yuboradi — bot uni
 * copyMessage bilan nusxalaydi (shuning uchun hamma narsa saqlanadi). Avval adminga ko'rsatiladi, tasdiqlansa — cron
 * bo'laklab yuboradi (hosting bitta so'rovda minglab xabar yubora olmaydi). Bloklagan foydalanuvchi belgilanadi.
 */
final class BroadcastHandler
{
    /** Cron bir marta ishga tushganda ko'pi bilan shuncha soniya yuboradi. */
    public const BUDGET_SEC = 40;
    /** Telegram chegarasi ~30 xabar/s; xavfsiz tezlik. */
    public const PER_SECOND = 20;

    public static function start(Ctx $ctx): void
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return;
        }
        $ctx->app->states->set($ctx->userId, 'bc_wait');
        $ctx->reply($ctx->t('bc_ask', ['n' => $ctx->app->broadcasts->audience()]), Keyboards::nav($ctx->lang, 'a:stats'));
    }

    /** Admin xabarni yubordi — ko'rsatiladi va tasdiq so'raladi. */
    public static function received(Ctx $ctx): void
    {
        $msg = $ctx->message ?? [];
        if (empty($msg['message_id'])) {
            return;
        }
        $ctx->app->states->set($ctx->userId, 'bc_confirm', ['chat' => $ctx->chatId, 'mid' => (int) $msg['message_id']]);
        $res = $ctx->app->tg->call('copyMessage', ['chat_id' => $ctx->chatId, 'from_chat_id' => $ctx->chatId, 'message_id' => (int) $msg['message_id']]);
        if (empty($res['ok'])) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->reply($ctx->t('bc_copy_failed'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        $ctx->reply($ctx->t('bc_confirm', ['n' => $ctx->app->broadcasts->audience()]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_bc_go'), 'bc:go'), Keyboards::btn($ctx->t('btn_cancel'), 'bc:no')],
        ]));
    }

    public static function confirm(Ctx $ctx, bool $go): void
    {
        $app = $ctx->app;
        if (!$app->isAdmin($ctx->userId)) {
            return;
        }
        $st = $ctx->state();
        if (!$go) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cancelled'));
            return;
        }
        if ($st === null || $st['state'] !== 'bc_confirm' || !$app->states->take($ctx->userId, 'bc_confirm')) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $id = $app->broadcasts->start($ctx->userId, (int) $st['data']['chat'], (int) $st['data']['mid'], $app->now());
        if ($id === null) {
            $ctx->replyMenu($ctx->t('bc_busy'));
            return;
        }
        $ctx->replyMenu($ctx->t('bc_started', ['id' => $id, 'n' => $app->broadcasts->get($id)['total']]));
    }

    public static function status(Ctx $ctx): void
    {
        $b = $ctx->app->broadcasts->latest();
        if (!$b) {
            $ctx->reply($ctx->t('bc_none'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        $ctx->reply($ctx->t('bc_status', ['id' => $b['id'], 'sent' => $b['sent'], 'total' => $b['total'], 'blocked' => $b['blocked'], 'failed' => $b['failed'],
            'state' => $ctx->t('bc_state_' . $b['status'])]), Keyboards::nav($ctx->lang, 'a:stats'));
    }

    public static function stop(Ctx $ctx): void
    {
        $b = $ctx->app->broadcasts->running();
        if (!$b || !$ctx->app->broadcasts->finish((int) $b['id'], 'stopped', $ctx->app->now())) {
            $ctx->reply($ctx->t('bc_none'));
            return;
        }
        $ctx->reply($ctx->t('bc_stopped', ['id' => $b['id']]));
    }

    /**
     * Cron: faol yuborishni bo'laklab bajaradi. Kursor har foydalanuvchidan keyin yangilanadi (uzilsa ham ikki marta yubormaydi).
     * @return array{sent:int, blocked:int, failed:int, done:bool}
     */
    public static function work(App $app, float $deadline): array
    {
        $out = ['sent' => 0, 'blocked' => 0, 'failed' => 0, 'done' => false];
        $b = $app->broadcasts->running();
        if (!$b) {
            return $out;
        }
        $id = (int) $b['id'];
        $cursor = (int) $b['last_user_id'];
        while (microtime(true) < $deadline) {
            $users = $app->broadcasts->nextUsers($cursor, 25);
            if (!$users) {
                if ($app->broadcasts->finish($id, 'done', $app->now())) {
                    self::notifyDone($app, $app->broadcasts->get($id) ?? $b);
                }
                $out['done'] = true;
                return $out;
            }
            foreach ($users as $uid) {
                if (microtime(true) >= $deadline) {
                    return $out;
                }
                $res = $app->tg->call('copyMessage', ['chat_id' => $uid, 'from_chat_id' => (int) $b['from_chat'], 'message_id' => (int) $b['message_id']]);
                $code = (int) ($res['error_code'] ?? 0);
                $desc = strtolower((string) ($res['description'] ?? ''));
                if (!empty($res['ok'])) {
                    $kind = 'sent';
                } elseif ($code === 429) {
                    return $out; // Telegram sekinlashishni so'radi — kursor o'zgarmaydi, keyingi cron davom ettiradi
                } elseif (strpos($desc, 'message to copy not found') !== false) {
                    $app->broadcasts->finish($id, 'stopped', $app->now()); // admin xabarni o'chirib yuborgan
                    $app->tg->sendMessage((int) $b['admin_id'], I18n::t('bc_source_gone', self::lang($app, (int) $b['admin_id']), ['id' => $id]));
                    return $out;
                } elseif ($code === 403 || strpos($desc, 'chat not found') !== false || strpos($desc, 'user is deactivated') !== false) {
                    $app->users->markBlocked($uid, true); // botni bloklagan / hisob o'chgan
                    $kind = 'blocked';
                } else {
                    $kind = 'failed';
                }
                $app->broadcasts->advance($id, $uid, $kind);
                $cursor = $uid;
                $out[$kind]++;
                $app->sleepMs((int) (1000 / self::PER_SECOND));
            }
        }
        return $out;
    }

    private static function lang(App $app, int $userId): string
    {
        return I18n::norm($app->users->get($userId)['lang'] ?? 'uz');
    }

    private static function notifyDone(App $app, array $b): void
    {
        $app->tg->sendMessage((int) $b['admin_id'], I18n::t('bc_done', self::lang($app, (int) $b['admin_id']), [
            'id' => $b['id'], 'sent' => $b['sent'], 'blocked' => $b['blocked'], 'failed' => $b['failed'], 'total' => $b['total'],
        ]));
    }
}
