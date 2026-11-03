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
        $res = PostRender::send($app->tg, (int) $post['channel_id'], $post, $app->config->str('bot_username'), $app->isFree($owner));
        if (!empty($res['ok'])) {
            $app->posts->markSent($id, isset($res['result']['message_id']) ? (int) $res['result']['message_id'] : null);
            if ((int) $post['notify_owner'] === 1) {
                $this->notify($owner, 'post_sent_notice', $post);
            }
            return ['status' => 'sent', 'reason' => '', 'result' => $res];
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

    private function notify(int $owner, string $key, array $post, string $reason = ''): void
    {
        $user = $this->app->users->get($owner);
        $lang = I18n::norm($user['lang'] ?? 'uz');
        $this->app->tg->sendMessage($owner, I18n::t($key, $lang, [
            'channel' => Html::e((string) ($post['channel_title'] ?? $post['channel_id'])),
            'when' => TimeParser::show((string) $post['scheduled_time'], $this->app->tz()),
            'reason' => $reason !== '' ? I18n::t($reason, $lang) : '',
        ]));
    }

    /** Eski yozuvlarni tozalash (Python versiyadagi kabi: yakunlangan postlar 30 kundan keyin). */
    private function cleanup(): void
    {
        $db = $this->app->db;
        $db->exec('DELETE FROM processed_updates WHERE created_at < UTC_TIMESTAMP() - INTERVAL 2 DAY');
        $db->exec('DELETE FROM user_states WHERE updated_at < UTC_TIMESTAMP() - INTERVAL 3 DAY');
        $db->exec("DELETE FROM scheduled_posts WHERE status IN ('sent', 'failed', 'cancelled') AND created_at < UTC_TIMESTAMP() - INTERVAL 30 DAY");
    }
}
