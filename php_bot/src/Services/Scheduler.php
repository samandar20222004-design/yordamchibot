<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\App;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Telegram;

/**
 * Vaqti kelgan postlarni kanalga yuboradi (cron.php har daqiqada chaqiradi).
 * Himoya: MySQL qulfi (ikki cron bir vaqtda ishlamaydi), atomik egallash (bitta post ikki marta ketmaydi),
 * 'processing' da qolib ketganlarni tiklash, vaqtinchalik xatoda 3 marta qayta urinish (1, 5, 15 daqiqa),
 * Telegram tezlik chegarasi: umumiy ~25 xabar/s, bitta kanalga 1 xabar/s.
 */
final class Scheduler
{
    public const LOCK = 'postassist_cron';
    public const MAX_ATTEMPTS = 3;
    private const RETRY_DELAYS = [60, 300, 900];

    private App $app;
    /** @var array<int, float> kanal => oxirgi yuborish vaqti */
    private array $lastByChannel = [];
    /** @var callable testlar uchun: fn(int $micro): void */
    private $sleeper;

    public function __construct(App $app, ?callable $sleeper = null)
    {
        $this->app = $app;
        $this->sleeper = $sleeper ?? static function (int $micro): void {
            usleep($micro);
        };
    }

    /** @return array{sent:int, retry:int, failed:int, locked:bool} */
    public function run(int $budgetSec = 50): array
    {
        $stats = ['sent' => 0, 'retry' => 0, 'failed' => 0, 'locked' => false];
        if (!$this->app->db->lock(self::LOCK, 0)) {
            $stats['locked'] = true;
            return $stats;
        }
        $started = microtime(true);
        try {
            $this->app->posts->recoverStuck();
            while (microtime(true) - $started < $budgetSec) {
                $ids = $this->app->posts->dueIds($this->app->nowSql(), 50);
                if (!$ids) {
                    break;
                }
                foreach ($ids as $id) {
                    if (microtime(true) - $started >= $budgetSec) {
                        break 2;
                    }
                    if (!$this->app->posts->claim($id)) {
                        continue;
                    }
                    $post = $this->app->posts->get($id);
                    if (!$post) {
                        continue;
                    }
                    $this->pace((int) $post['channel_id']);
                    $r = $this->deliver($post);
                    $stats[$r['status']]++;
                }
            }
            \PostAssist\Handlers\BroadcastHandler::work($this->app, $started + $budgetSec);
            \PostAssist\Handlers\AutopilotHandler::work($this->app, $this, $started + $budgetSec);
            \PostAssist\Handlers\RssHandler::work($this->app, $this, $started + $budgetSec);
            \PostAssist\Handlers\StatsHandler::collect($this->app, $started + $budgetSec);
            $this->autoDelete();
            $this->finishStaleAlbums();
            $this->planMaintenance();
            $this->cleanup();
        } finally {
            $this->app->db->unlock(self::LOCK);
        }
        return $stats;
    }

    private function pace(int $channelId): void
    {
        $now = microtime(true);
        $wait = 0.04; // umumiy ~25/s
        if (isset($this->lastByChannel[$channelId])) {
            $wait = max($wait, 1.0 - ($now - $this->lastByChannel[$channelId]));
        }
        if ($wait > 0) {
            ($this->sleeper)((int) ($wait * 1_000_000));
        }
        $this->lastByChannel[$channelId] = microtime(true);
    }

    /**
     * Egallangan ('processing') postni yuboradi. Natija: status sent|retry|failed, reason — sabab kaliti.
     * @return array{status:string, reason:string, result:array}
     */
    public function deliver(array $post): array
    {
        $app = $this->app;
        $id = (int) $post['id'];
        $owner = (int) $post['user_id'];
        if ($post['post_type'] !== 'album' && in_array('comments', PostRender::options($post['options'] ?? null), true)) {
            $post['comments_label'] = I18n::t('cm_btn', I18n::norm((string) ($app->users->get($owner)['lang'] ?? 'uz')));
            $post['comments_count'] = $app->comments->count($id);
        }
        $res = PostRender::send($app->tg, (int) $post['channel_id'], $post, $app->config->str('bot_username'), $app->isFree($owner));
        if (!empty($res['ok'])) {
            $ids = PostRender::messageIds($res);
            $deleteAt = (int) ($post['delete_after'] ?? 0) > 0 ? $app->now()->modify('+' . (int) $post['delete_after'] . ' minutes')->format('Y-m-d H:i:s') : null;
            $app->messages->record($post, (int) $post['channel_id'], $ids, $deleteAt, $app->nowSql());
            if ($ids && in_array('pin', PostRender::options($post['options'] ?? null), true)) {
                $pin = $app->tg->call('pinChatMessage', ['chat_id' => (int) $post['channel_id'], 'message_id' => $ids[0], 'disable_notification' => true]);
                if (empty($pin['ok'])) {
                    $app->log('pin #' . $id . ': ' . ($pin['description'] ?? '')); // post chiqdi, pin bo'lmasa ham xato emas
                }
            }
            $next = null;
            if (!empty($post['recurrence_type'])) {
                $next = Recurrence::next((string) $post['recurrence_type'], (int) $post['recurrence_time'],
                    $post['recurrence_day'] !== null ? (int) $post['recurrence_day'] : null, $app->now(), $app->tzFor($owner));
            }
            if ($next !== null) {
                $app->posts->rescheduleAfterSend($id, $ids[0] ?? null, $next->format('Y-m-d H:i:s'));
            } else {
                $app->posts->markSent($id, $ids[0] ?? null);
            }
            // takroriy postda faqat birinchi chiqishda xabar beriladi (har kuni xabar — ortiqcha)
            if ((int) $post['notify_owner'] === 1 && (int) ($post['sent_count'] ?? 0) === 0) {
                $this->notify($owner, $next !== null ? 'post_sent_repeat_notice' : 'post_sent_notice', $post, '',
                    $next !== null ? $next->format('Y-m-d H:i:s') : null);
            }
            return ['status' => 'sent', 'reason' => '', 'result' => $res, 'next' => $next];
        }
        $reason = PostRender::reasonKey($res);
        $attempts = (int) $post['attempt_count'];
        if (Telegram::isTemporary($res) && $attempts < self::MAX_ATTEMPTS) {
            $delay = max(Telegram::retryAfter($res), self::RETRY_DELAYS[min($attempts, count(self::RETRY_DELAYS) - 1)]);
            $app->posts->retryLater($id, (string) ($res['description'] ?? ''), $app->now()->modify('+' . $delay . ' seconds')->format('Y-m-d H:i:s'));
            return ['status' => 'retry', 'reason' => $reason, 'result' => $res];
        }
        $app->posts->markFailed($id, (string) ($res['description'] ?? 'error'));
        if ((int) $post['notify_owner'] === 1) {
            $this->notify($owner, 'post_failed_notice', $post, $reason);
        }
        $app->log("post #{$id} chiqmadi: " . ($res['description'] ?? ''));
        return ['status' => 'failed', 'reason' => $reason, 'result' => $res];
    }

    private function notify(int $owner, string $key, array $post, string $reason = '', ?string $nextSql = null): void
    {
        $user = $this->app->users->get($owner);
        $lang = I18n::norm($user['lang'] ?? 'uz');
        $tz = $this->app->tzFor($owner);
        $this->app->tg->sendMessage($owner, I18n::t($key, $lang, [
            'channel' => Html::e((string) ($post['channel_title'] ?? $post['channel_id'])),
            'when' => TimeParser::show((string) $post['scheduled_time'], $tz),
            'next' => $nextSql !== null ? TimeParser::show($nextSql, $tz) : '',
            'reason' => $reason !== '' ? I18n::t($reason, $lang) : '',
        ]));
    }

    /** Muddati kelgan avto-o'chiriladigan postlar (24 soatlik e'lon va h.k.). @return int o'chirilganlar */
    public function autoDelete(): int
    {
        $app = $this->app;
        $n = 0;
        foreach ($app->messages->dueForDelete($app->nowSql(), 50) as $m) {
            $ids = array_merge([(int) $m['message_id']], array_map('intval', array_filter(explode(',', (string) $m['extra_ids']))));
            $temporary = false;
            foreach ($ids as $mid) {
                $r = $app->tg->call('deleteMessage', ['chat_id' => (int) $m['chat_id'], 'message_id' => $mid]);
                if (empty($r['ok']) && Telegram::isTemporary($r)) {
                    $temporary = true;
                }
            }
            if ($temporary) {
                $app->messages->deleteLater((int) $m['id'], $app->now()->modify('+5 minutes')->format('Y-m-d H:i:s'));
            } else {
                $app->messages->markDeleted((int) $m['id']); // o'chdi yoki allaqachon yo'q / o'chirib bo'lmaydi
                $n++;
            }
        }
        return $n;
    }

    /** Jarayoni uzilib qolgan albomlarni yig'ish (oxirgi qismdan 10 soniya o'tgan). */
    public function finishStaleAlbums(): int
    {
        $n = 0;
        foreach ($this->app->albums->stale($this->app->nowMs() - 10000) as $g) {
            if (\PostAssist\Handlers\PostHandler::finishAlbum($this->app, (int) $g['user_id'], (string) $g['group_id'])) {
                $n++;
            }
        }
        return $n;
    }

    /**
     * Tarif muddati: 24 soat qolganda bir marta eslatma; muddat tugaganda FREE ga tushirish va xabar.
     * (Muddati o'tgan tarif baribir FREE hisoblanadi — `Plans::effective`; bu yerda faqat bazani tartiblash va xabar.)
     * @return array{reminded:int, expired:int}
     */
    public function planMaintenance(): array
    {
        $app = $this->app;
        $now = $app->nowSql();
        $out = ['reminded' => 0, 'expired' => 0];
        foreach ($app->users->expiringSoon($now, $app->now()->modify('+24 hours')->format('Y-m-d H:i:s')) as $u) {
            if ($app->users->claimReminder((int) $u['user_id'], (string) $u['subscription_expires_at'])) {
                $lang = I18n::norm($u['lang'] ?? 'uz');
                $app->tg->sendMessage((int) $u['user_id'], I18n::t('plan_reminder', $lang, [
                    'plan' => Plans::NAMES[$u['plan_type']] ?? 'PRO', 'date' => TimeParser::show((string) $u['subscription_expires_at'], $app->tzFor((int) $u['user_id'])),
                ]));
                $out['reminded']++;
            }
        }
        foreach ($app->users->expiredPaid($now) as $u) {
            if ($app->users->downgradeIfExpired((int) $u['user_id'], (string) $u['plan_type'], $now)) {
                $lang = I18n::norm($u['lang'] ?? 'uz');
                $app->tg->sendMessage((int) $u['user_id'], I18n::t('plan_expired', $lang, ['plan' => Plans::NAMES[$u['plan_type']] ?? 'PRO']));
                $out['expired']++;
            }
        }
        return $out;
    }

    /** Eski yozuvlarni tozalash (Python versiyadagi kabi: yakunlangan postlar 30 kundan keyin). */
    private function cleanup(): void
    {
        $db = $this->app->db;
        $db->exec('DELETE FROM processed_updates WHERE created_at < UTC_TIMESTAMP() - INTERVAL 2 DAY');
        $db->exec('DELETE FROM user_states WHERE updated_at < UTC_TIMESTAMP() - INTERVAL 3 DAY');
        $db->exec('DELETE FROM promo_attempts WHERE created_at < UTC_TIMESTAMP() - INTERVAL 1 DAY');
        $this->app->messages->cleanup();
        $this->app->albums->cleanup($this->app->nowMs() - 86400000);
        $db->exec("DELETE FROM scheduled_posts WHERE status IN ('sent', 'failed', 'cancelled') AND created_at < UTC_TIMESTAMP() - INTERVAL 30 DAY");
    }
}
