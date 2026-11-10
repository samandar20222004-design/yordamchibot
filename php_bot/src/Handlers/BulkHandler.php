<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\PostRender;
use PostAssist\Services\TimeParser;

/**
 * 📦 Ko'p post rejasi: bir nechta xabarni (matn, rasm, video, GIF, hujjat, audio) ketma-ket yuborasiz → «✅ Tayyor» →
 * kanal → birinchi post vaqti → oraliq (1/3/6/12 soat yoki har kuni). Har biri alohida rejalashtirilgan postga aylanadi.
 * Albom (2–10 fayl) bitta post bo'lib qo'shiladi. Ko'pi bilan 30 ta; navbat limiti tekshiriladi.
 */
final class BulkHandler
{
    public const MAX = 30;
    public const GAPS = [60, 180, 360, 720, 1440];

    public static function start(Ctx $ctx): void
    {
        if (!$ctx->can('create')) {
            $ctx->replyMenu($ctx->t('team_no_perm'));
            return;
        }
        if ($ctx->app->channels->countFor($ctx->ownerId()) === 0) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        $ctx->app->states->set($ctx->userId, 'bulk', ['items' => []]);
        $ctx->reply($ctx->t('bk_ask', ['max' => self::MAX]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    private static function doneKb(Ctx $ctx, int $n): array
    {
        return Keyboards::inline([[Keyboards::btn($ctx->t('btn_bk_done', ['n' => $n]), 'bk:done'), Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]);
    }

    /** Navbatdagi xabar (holat bulk). Albom — bitta post (oddiy postdagi kabi yig'iladi). */
    public static function add(Ctx $ctx, array $state): void
    {
        $msg = $ctx->message ?? [];
        if (!empty($msg['media_group_id'])) {
            $group = (string) $msg['media_group_id'];
            if (($state['data']['last_group'] ?? null) === $group && $ctx->app->albums->isDone($ctx->userId, $group)) {
                self::albumLate($ctx, $state); // server band bo'lib kechikkan qism — oxirgi albomga qo'shiladi
                return;
            }
            PostHandler::albumItem($ctx, $group);
            return;
        }
        $d = PostRender::draftFromMessage($msg);
        if ($d === null || ($d['type'] === 'text' && trim(Html::plain($d['text'])) === '')) {
            $ctx->reply($ctx->t('post_unsupported'), self::doneKb($ctx, count((array) ($state['data']['items'] ?? []))));
            return;
        }
        self::addDraft($ctx, $state, $d);
    }

    /** Tayyor qoralamani ro'yxatga qo'shadi (matn, media yoki albom). */
    public static function addDraft(Ctx $ctx, array $state, array $d): void
    {
        $items = (array) ($state['data']['items'] ?? []);
        if (count($items) >= self::MAX) {
            $ctx->reply($ctx->t('bk_full', ['max' => self::MAX]), self::doneKb($ctx, count($items)));
            return;
        }
        $len = Html::utf16Len(Html::plain((string) $d['text']));
        $max = PostRender::limitFor($d['type'] === 'album' ? 'photo' : $d['type']);
        if ($len > $max) {
            $ctx->reply($ctx->t($d['type'] === 'text' ? 'post_too_long_text' : 'post_too_long_caption', ['len' => $len, 'max' => $max]), self::doneKb($ctx, count($items)));
            return;
        }
        $group = $d['group'] ?? null;
        unset($d['group']);
        $items[] = $d;
        $ctx->app->states->set($ctx->userId, 'bulk', ['items' => $items, 'last_group' => $group] + $state['data']);
        $ctx->reply($ctx->t($d['type'] === 'album' ? 'bk_added_album' : 'bk_added', ['n' => count($items), 'k' => count($d['media'] ?? [])]), self::doneKb($ctx, count($items)));
    }

    /** Yig'ilgan albomga kechikib kelgan qism. */
    private static function albumLate(Ctx $ctx, array $state): void
    {
        $items = (array) ($state['data']['items'] ?? []);
        $i = count($items) - 1;
        $d = PostRender::draftFromMessage($ctx->message ?? []);
        if ($i < 0 || ($items[$i]['type'] ?? '') !== 'album' || $d === null || !in_array($d['type'], ['photo', 'video', 'document', 'audio'], true)) {
            return;
        }
        $media = (array) $items[$i]['media'];
        foreach ($media as $m) {
            if ($m[1] === $d['file_id']) {
                return;
            }
        }
        $next = array_merge($media, [[$d['type'], (string) $d['file_id']]]);
        if (count($next) > PostRender::ALBUM_MAX || !PostRender::albumValid($next)) {
            return;
        }
        $items[$i]['media'] = $next;
        if (trim((string) $items[$i]['text']) === '' && trim((string) $d['text']) !== '') {
            $items[$i]['text'] = $d['text'];
        }
        $ctx->app->states->set($ctx->userId, 'bulk', ['items' => $items] + $state['data']);
    }

    private static function bulkState(Ctx $ctx): ?array
    {
        $st = $ctx->state();
        if ($st === null || strpos($st['state'], 'bulk') !== 0 || empty($st['data']['items'])) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return null;
        }
        return $st;
    }

    public static function done(Ctx $ctx): void
    {
        $st = self::bulkState($ctx);
        if ($st === null) {
            return;
        }
        $channels = $ctx->app->channels->listFor($ctx->ownerId());
        if (count($channels) > 1) {
            $rows = [];
            foreach ($channels as $c) {
                $rows[] = [Keyboards::btn('📢 ' . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'bk:ch:' . (int) $c['id'])];
            }
            $rows[] = [Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')];
            $ctx->app->states->set($ctx->userId, 'bulk_pick', $st['data']);
            $ctx->reply($ctx->t('post_pick_channel'), Keyboards::inline($rows));
            return;
        }
        self::pickChannel($ctx, (int) $channels[0]['id']);
    }

    public static function pickChannel(Ctx $ctx, int $ref): void
    {
        $st = self::bulkState($ctx);
        if ($st === null) {
            return;
        }
        if (!$ctx->app->channels->getOwned($ctx->ownerId(), $ref)) {
            self::done($ctx);
            return;
        }
        $ctx->app->states->set($ctx->userId, 'bulk_time', ['channel' => $ref] + $st['data']);
        $ctx->reply($ctx->t('bk_ask_time', ['n' => count($st['data']['items']), 'tz' => Html::e($ctx->tzName())]),
            Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    /** Birinchi post vaqti (holat bulk_time). */
    public static function timeInput(Ctx $ctx, array $state): void
    {
        $r = TimeParser::parse((string) ($ctx->message['text'] ?? ''), $ctx->tz(), $ctx->app->now());
        if (!$r['ok']) {
            $ctx->reply($ctx->t('time_' . ($r['error'] ?? 'bad'), ['tz' => Html::e($ctx->tzName())]));
            return;
        }
        $data = $state['data'];
        $data['start'] = $r['utc']->format('Y-m-d H:i:s');
        $ctx->app->states->set($ctx->userId, 'bulk_gap', $data);
        $b = static function (int $m) use ($ctx) {
            return Keyboards::btn($ctx->t('btn_bk_gap_' . $m), 'bk:g:' . $m);
        };
        $ctx->reply($ctx->t('bk_ask_gap', ['when' => TimeParser::show($data['start'], $ctx->tz())]), Keyboards::inline([
            [$b(60), $b(180), $b(360)], [$b(720), $b(1440)], [Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')],
        ]));
    }

    /** Oraliq tanlandi — postlar yaratiladi. */
    public static function gap(Ctx $ctx, int $minutes): void
    {
        $app = $ctx->app;
        $st = $ctx->state();
        if ($st === null || $st['state'] !== 'bulk_gap' || empty($st['data']['items']) || !in_array($minutes, self::GAPS, true)) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $data = $st['data'];
        $ch = $app->channels->getOwned($ctx->ownerId(), (int) ($data['channel'] ?? 0));
        if ($ch === null || !$ctx->can('create')) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $n = count($data['items']);
        $limit = $app->queueLimit($ctx->ownerId());
        if ($limit > 0 && $app->posts->pendingCount($ctx->ownerId()) + $n > $limit) {
            $ctx->reply($ctx->t('bk_queue_limit', ['max' => $limit, 'free' => max(0, $limit - $app->posts->pendingCount($ctx->ownerId())), 'n' => $n]),
                Keyboards::inline([[Keyboards::btn($ctx->t('btn_plans'), 'pl:show'), Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
            return;
        }
        if (!$app->states->take($ctx->userId, 'bulk_gap')) {
            return; // ikki marta bosish
        }
        $start = new \DateTimeImmutable((string) $data['start'], new \DateTimeZone('UTC'));
        $lines = [];
        foreach (array_values($data['items']) as $i => $d) {
            $when = $start->modify('+' . ($i * $minutes) . ' minutes')->format('Y-m-d H:i:s');
            $app->posts->create($ctx->ownerId(), (int) $ch['channel_id'], $d, $when, true, null, $ctx->userId);
            if ($i < 10) {
                $plain = trim(Html::plain((string) $d['text']));
                $lines[] = '• ' . TimeParser::show($when, $ctx->tz()) . ' — ' . ($d['type'] === 'album' ? '🖼×' . count($d['media'] ?? []) . ' ' : '')
                    . Html::e(mb_substr($plain !== '' ? $plain : ($d['type'] === 'album' ? '' : '[' . $d['type'] . ']'), 0, 40));
            }
        }
        if ($n > 10) {
            $lines[] = '…';
        }
        $r = $app->afterPostSaved($ctx->ownerId());
        if ($r !== null) {
            PlansHandler::notifyReward($app, $r, $ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId);
        }
        $ctx->replyMenu($ctx->t('bk_done', ['n' => $n, 'channel' => Html::e((string) $ch['title']), 'tz' => Html::e($ctx->tzName())]) . "\n\n" . implode("\n", $lines));
    }
}
