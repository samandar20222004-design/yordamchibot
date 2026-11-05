<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;

/**
 * 📊 Statistika: umumiy (postlar) va har kanal bo'yicha — obunachilar o'sishi (kunlik o'lchov, cron), 14 kunlik grafik,
 * 7/30 kunda chiqqan postlar, reaksiya ovozlari, 🔒 yashirin matn ochilishlari va eng ko'p reaksiya olgan post.
 * Bot API kanal postlari ko'rishlar sonini bermaydi — shuning uchun ko'rishlar ko'rsatilmaydi (soxta raqam yo'q).
 */
final class StatsHandler
{
    public const PER_RUN = 30;
    private const BARS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

    /** Bot va Mini App uchun umumiy ma'lumot. */
    public static function channelStats(App $app, int $owner): array
    {
        $today = $app->now()->format('Y-m-d');
        $day = static function (int $ago) use ($app): string {
            return $app->now()->modify('-' . $ago . ' days')->format('Y-m-d');
        };
        $out = [];
        foreach ($app->channels->listFor($owner) as $c) {
            $cid = (int) $c['channel_id'];
            $now = $app->stats->at($cid, $today);
            $diff = static function (int $ago) use ($app, $cid, $now, $day): ?int {
                $was = $app->stats->at($cid, $day($ago));
                return $now !== null && $was !== null ? $now - $was : null;
            };
            $series = [];
            foreach ($app->stats->series($cid, $day(13), $today) as $d => $n) {
                $series[] = ['day' => $d, 'n' => $n];
            }
            $a7 = $app->stats->activity($owner, $cid, $app->now()->modify('-7 days')->format('Y-m-d H:i:s'));
            $a30 = $app->stats->activity($owner, $cid, $app->now()->modify('-30 days')->format('Y-m-d H:i:s'));
            $top = $a30['top'] ? trim(\PostAssist\Html::plain((string) $a30['top']['text'])) : '';
            $out[] = ['id' => (int) $c['id'], 'title' => (string) ($c['title'] ?: $cid), 'subscribers' => $now,
                'd1' => $diff(1), 'd7' => $diff(7), 'd30' => $diff(30), 'series' => $series,
                'posts7' => $a7['posts'], 'posts30' => $a30['posts'], 'votes30' => $a30['votes'], 'opens30' => $a30['opens'], 'locked30' => $a30['locked'],
                'top' => $a30['top'] ? ['text' => mb_substr($top !== '' ? $top : '[' . $a30['top']['post_type'] . ']', 0, 80), 'votes' => (int) $a30['top']['n']] : null];
        }
        return $out;
    }

    /** 14 kunlik obunachilar grafigi (▁▂▃…█). */
    public static function sparkline(array $series): string
    {
        $vals = array_column($series, 'n');
        if (count($vals) < 2) {
            return '';
        }
        $min = min($vals);
        $max = max($vals);
        $out = '';
        foreach ($vals as $v) {
            $out .= self::BARS[$max === $min ? 3 : (int) round(($v - $min) / ($max - $min) * 7)];
        }
        return $out;
    }

    private static function signed(?int $n): string
    {
        if ($n === null) {
            return '—';
        }
        return ($n > 0 ? '+' : '') . number_format($n, 0, '', ' ');
    }

    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $app = $ctx->app;
        $own = $ctx->ownerId();
        $s = $app->posts->userStats($own);
        $lines = [];
        $rows = [];
        foreach (self::channelStats($app, $own) as $c) {
            $lines[] = '📢 <b>' . Html::e(mb_substr($c['title'], 0, 40)) . '</b> — 👥 ' . ($c['subscribers'] !== null ? number_format($c['subscribers'], 0, '', ' ') : '…')
                . ' (' . $ctx->t('st_week') . ' ' . self::signed($c['d7']) . ')';
            $rows[] = [Keyboards::btn('📊 ' . mb_substr($c['title'], 0, 30), 'st:c:' . $c['id'])];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_scheduled'), 'q:list'), Keyboards::btn($ctx->t('btn_sent_list'), 's:list')];
        $rows[] = [Keyboards::btn($ctx->t('btn_plans'), 'pl:show'), Keyboards::btn($ctx->t('btn_home'), 'm:home')];
        $text = $ctx->t('stats_user', ['channels' => count($lines), 'pending' => $s['pending'], 'sent' => $s['sent'], 'failed' => $s['failed']])
            . ($lines ? "\n\n" . implode("\n", $lines) . "\n\n" . $ctx->t('st_pick') : '');
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    public static function channel(Ctx $ctx, int $ref): void
    {
        $c = null;
        foreach (self::channelStats($ctx->app, $ctx->ownerId()) as $x) {
            if ($x['id'] === $ref) {
                $c = $x;
            }
        }
        if ($c === null) {
            self::show($ctx, true);
            return;
        }
        $spark = self::sparkline($c['series']);
        $text = $ctx->t('st_channel', [
            'title' => Html::e($c['title']),
            'subs' => $c['subscribers'] !== null ? number_format($c['subscribers'], 0, '', ' ') : '—',
            'd1' => self::signed($c['d1']), 'd7' => self::signed($c['d7']), 'd30' => self::signed($c['d30']),
            'posts7' => $c['posts7'], 'posts30' => $c['posts30'], 'votes' => $c['votes30'], 'opens' => $c['opens30'], 'locked' => $c['locked30'],
        ]) . ($spark !== '' ? "\n\n" . $ctx->t('st_chart') . "\n<code>" . $spark . '</code>' : "\n\n" . $ctx->t('st_no_history'))
            . ($c['top'] !== null ? "\n\n" . $ctx->t('st_top', ['text' => Html::e($c['top']['text']), 'n' => $c['top']['votes']]) : '');
        $ctx->edit($text, Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_st_refresh'), 'st:r:' . $ref)],
            Keyboards::navRow($ctx->lang, 'st:show'),
        ]));
    }

    /** «🔄 Yangilash»: obunachilar hozir o'lchanadi (bugungi qiymat). */
    public static function refresh(Ctx $ctx, int $ref): void
    {
        $ch = $ctx->app->channels->getOwned($ctx->ownerId(), $ref);
        if ($ch !== null) {
            $r = $ctx->app->tg->call('getChatMemberCount', ['chat_id' => (int) $ch['channel_id']]);
            if (!empty($r['ok']) && is_int($r['result'] ?? null)) {
                $ctx->app->stats->save((int) $ch['channel_id'], $ctx->app->now()->format('Y-m-d'), (int) $r['result']);
            }
        }
        self::channel($ctx, $ref);
    }

    /** Cron: har kanal kuniga bir marta o'lchanadi (UTC kun). @return int o'lchanganlar */
    public static function collect(App $app, float $deadline): int
    {
        $day = $app->now()->format('Y-m-d');
        $n = 0;
        foreach ($app->stats->pending($day, self::PER_RUN) as $cid) {
            if (microtime(true) >= $deadline - 1) {
                break;
            }
            $r = $app->tg->call('getChatMemberCount', ['chat_id' => $cid]);
            $app->stats->save($cid, $day, !empty($r['ok']) && is_int($r['result'] ?? null) ? (int) $r['result'] : -1);
            $n++;
        }
        if ($n > 0 && (int) $app->now()->format('G') === 3) {
            $app->stats->cleanup($app->now()->modify('-180 days')->format('Y-m-d'));
        }
        return $n;
    }
}
