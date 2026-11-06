<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Autopilots;
use PostAssist\Services\Ai;
use PostAssist\Services\PostRender;
use PostAssist\Services\Recurrence;
use PostAssist\Services\Scheduler;

/**
 * 🤖 Autopilot: har kuni belgilangan vaqtda (egasining mintaqasida) AI kanal mavzusida yangi post yozadi.
 * «Tekshirib» — post avval egasiga keladi (✅ Kanalga / ✏️ Tahrirlash / 🔄 Boshqa variant / ❌);
 * «Avtomatik» — post darhol kanalga chiqadi. Har post 1 ta AI so'rovi (kunlik limit, keyin ball); AI xato bersa qaytariladi.
 * PRO — 1, ULTRA — 3 ta autopilot; tarif tugasa autopilot to'xtaydi va egasiga aytiladi.
 */
final class AutopilotHandler
{
    public const TIMES = ['0800', '1200', '1800', '2100'];
    /** Bir cron yugurishida eng ko'pi bilan nechta AI post (har biri 5–30 soniya). */
    public const PER_RUN = 3;

    // ---------------------------------------------------------------- ro'yxat va ko'rish

    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $app = $ctx->app;
        $owner = $ctx->ownerId();
        $limit = $app->autopilotLimit($owner);
        $rows = [];
        $list = $app->autopilots->listFor($owner);
        foreach ($list as $a) {
            $rows[] = [Keyboards::btn(((int) $a['active'] === 1 ? '✅ ' : '⏸ ') . Recurrence::clock((int) $a['post_time']) . ' · '
                . mb_substr((string) ($a['channel_title'] ?? '—'), 0, 30), 'ap:v:' . (int) $a['id'])];
        }
        $btns = [];
        if ($limit === 0) {
            $btns[] = Keyboards::btn($ctx->t('btn_plans'), 'pl:show');
        } elseif (count($list) < $limit) {
            $btns[] = Keyboards::btn($ctx->t('btn_ap_add'), 'ap:new');
        }
        $btns[] = Keyboards::btn($ctx->t('btn_cp'), 'cp:show');
        $rows = array_merge($rows, Keyboards::grid($btns, Keyboards::navRow($ctx->lang)));
        $text = $ctx->t('ap_intro') . "\n\n" . ($limit === 0 ? $ctx->t('ap_paid') : ($list ? $ctx->t('ap_count', ['n' => count($list), 'max' => $limit]) : $ctx->t('ap_none')));
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    public static function view(Ctx $ctx, int $id, bool $edit = true): void
    {
        $app = $ctx->app;
        $a = $app->autopilots->getOwned($ctx->ownerId(), $id);
        if ($a === null) {
            self::show($ctx, $edit);
            return;
        }
        $ch = $app->channels->getOwned($ctx->ownerId(), (int) $a['channel_ref']);
        $on = (int) $a['active'] === 1;
        $text = $ctx->t('ap_view', [
            'channel' => Html::e((string) ($ch['title'] ?? '—')),
            'topic' => Html::e(mb_substr((string) $a['topic'], 0, 300)),
            'style' => $ctx->t('btn_ai_' . $a['style']),
            'time' => Recurrence::clock((int) $a['post_time']),
            'tz' => Html::e($ctx->tzName()),
            'mode' => $ctx->t($a['mode'] === 'auto' ? 'ap_mode_auto' : 'ap_mode_review'),
            'status' => $ctx->t($on ? 'ap_on' : 'ap_off'),
        ]);
        $kb = Keyboards::inline([
            [Keyboards::btn($ctx->t($on ? 'btn_ap_pause' : 'btn_ap_resume'), 'ap:tg:' . $id), Keyboards::btn($ctx->t('btn_ap_test'), 'ap:run:' . $id)],
            [Keyboards::btn($ctx->t('btn_ap_mode'), 'ap:mo:' . $id), Keyboards::btn($ctx->t('btn_ap_del'), 'ap:del:' . $id)],
            Keyboards::navRow($ctx->lang, 'ap:show'),
        ]);
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    private static function allowed(Ctx $ctx): bool
    {
        if (!$ctx->can('create') || !$ctx->can('ai')) {
            $ctx->reply($ctx->t('team_no_perm_ai'), Keyboards::nav($ctx->lang));
            return false;
        }
        return true;
    }

    public static function toggle(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $a = $app->autopilots->getOwned($ctx->ownerId(), $id);
        if ($a === null || !self::allowed($ctx)) {
            return;
        }
        $on = (int) $a['active'] !== 1;
        if ($on && $app->autopilotLimit($ctx->ownerId()) === 0) {
            $ctx->reply($ctx->t('ap_paid'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_plans'), 'pl:show')], Keyboards::navRow($ctx->lang, 'ap:show')]));
            return;
        }
        if ($on) {
            // yoqilganda bugungi vaqt o'tib ketgan bo'lsa — ertadan boshlanadi (darhol post chiqmaydi)
            $app->autopilots->setLastRun($id, self::startDay($ctx, (int) $a['post_time']) ?? '2000-01-01');
        }
        $app->autopilots->setActive($id, $on);
        self::view($ctx, $id);
    }

    public static function switchMode(Ctx $ctx, int $id): void
    {
        $a = $ctx->app->autopilots->getOwned($ctx->ownerId(), $id);
        if ($a === null || !self::allowed($ctx)) {
            return;
        }
        $ctx->app->db->exec('UPDATE autopilots SET mode = ? WHERE id = ?', [$a['mode'] === 'auto' ? 'review' : 'auto', $id]);
        self::view($ctx, $id);
    }

    public static function askDelete(Ctx $ctx, int $id): void
    {
        if ($ctx->app->autopilots->getOwned($ctx->ownerId(), $id) === null) {
            self::show($ctx, true);
            return;
        }
        $ctx->edit($ctx->t('ap_del_confirm'), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_ap_del'), 'ap:dok:' . $id), Keyboards::btn($ctx->t('btn_back'), 'ap:v:' . $id)],
        ]));
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        if (!self::allowed($ctx)) {
            return;
        }
        $ctx->app->autopilots->delete($ctx->ownerId(), $id);
        $ctx->edit($ctx->t('ap_deleted'), Keyboards::nav($ctx->lang, 'ap:show'));
    }

    // ---------------------------------------------------------------- yaratish: kanal → mavzu → uslub → vaqt → rejim

    public static function begin(Ctx $ctx): void
    {
        $app = $ctx->app;
        $owner = $ctx->ownerId();
        if (!self::allowed($ctx)) {
            return;
        }
        $limit = $app->autopilotLimit($owner);
        if ($limit === 0) {
            $ctx->reply($ctx->t('ap_paid'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_plans'), 'pl:show')], Keyboards::navRow($ctx->lang, 'ap:show')]));
            return;
        }
        if ($app->autopilots->countFor($owner) >= $limit) {
            $ctx->reply($ctx->t('ap_limit', ['max' => $limit]), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        $free = array_values(array_filter($app->channels->listFor($owner), static function ($c) use ($app, $owner) {
            return !$app->autopilots->hasChannel($owner, (int) $c['id']);
        }));
        if (!$free) {
            if ($app->channels->countFor($owner) === 0) {
                $ctx->replyMenu($ctx->t('ch_need_first'));
                ChannelHandler::askAdd($ctx);
                return;
            }
            $ctx->reply($ctx->t('ap_all_channels'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        if (count($free) === 1) {
            self::pickChannel($ctx, (int) $free[0]['id']);
            return;
        }
        $rows = [];
        foreach ($free as $c) {
            $rows[] = [Keyboards::btn('📢 ' . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'ap:ch:' . (int) $c['id'])];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'ap:show');
        $ctx->reply($ctx->t('ap_pick_channel'), Keyboards::inline($rows));
    }

    public static function pickChannel(Ctx $ctx, int $ref): void
    {
        $app = $ctx->app;
        $ch = $app->channels->getOwned($ctx->ownerId(), $ref);
        if ($ch === null || $app->autopilots->hasChannel($ctx->ownerId(), $ref)) {
            self::show($ctx);
            return;
        }
        $app->states->set($ctx->userId, 'ap_topic', ['ch' => $ref]);
        $ctx->reply($ctx->t('ap_ask_topic', ['channel' => Html::e((string) $ch['title'])]), Keyboards::nav($ctx->lang, 'ap:show'));
    }

    public static function topicInput(Ctx $ctx, array $state): void
    {
        $topic = trim((string) ($ctx->message['text'] ?? ''));
        $len = mb_strlen($topic);
        if ($len < AiHandler::TOPIC_MIN || $len > 500) {
            $ctx->reply($ctx->t('ai_topic_bad', ['max' => 500]), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        $data = $state['data'];
        $data['topic'] = $topic;
        $ctx->app->states->set($ctx->userId, 'ap_style', $data);
        $b = static function (string $s) use ($ctx) {
            return Keyboards::btn($ctx->t('btn_ai_' . $s), 'ap:st:' . $s);
        };
        $ctx->reply($ctx->t('ai_ask_style'), Keyboards::inline([[$b('news'), $b('sales')], [$b('fun'), $b('useful')], [$b('short')],
            Keyboards::navRow($ctx->lang, 'ap:show')]));
    }

    public static function style(Ctx $ctx, string $style): void
    {
        $st = $ctx->state();
        if ($st === null || $st['state'] !== 'ap_style' || !in_array($style, Ai::STYLES, true)) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $data = $st['data'];
        $data['style'] = $style;
        $ctx->app->states->set($ctx->userId, 'ap_time', $data);
        $btns = array_map(static function (string $t) {
            return Keyboards::btn(substr($t, 0, 2) . ':' . substr($t, 2), 'ap:t:' . $t);
        }, self::TIMES);
        $ctx->reply($ctx->t('ap_ask_time', ['tz' => Html::e($ctx->tzName())]), Keyboards::inline([$btns, Keyboards::navRow($ctx->lang, 'ap:show')]));
    }

    /** Vaqt: tugma (HHMM) yoki yozilgan «08:30». */
    public static function time(Ctx $ctx, string $raw): void
    {
        $st = $ctx->state();
        if ($st === null || $st['state'] !== 'ap_time') {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (!preg_match('/^\s*(\d{1,2})\s*[:.]?\s*(\d{2})\s*$/', $raw, $m) || (int) $m[1] > 23 || (int) $m[2] > 59) {
            $ctx->reply($ctx->t('ap_time_bad'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        $data = $st['data'];
        $data['min'] = (int) $m[1] * 60 + (int) $m[2];
        $ctx->app->states->set($ctx->userId, 'ap_mode', $data);
        $ctx->reply($ctx->t('ap_ask_mode'), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_ap_review'), 'ap:m:review'), Keyboards::btn($ctx->t('btn_ap_auto'), 'ap:m:auto')],
            Keyboards::navRow($ctx->lang, 'ap:show'),
        ]));
    }

    public static function mode(Ctx $ctx, string $mode): void
    {
        $app = $ctx->app;
        $st = $ctx->state();
        if ($st === null || $st['state'] !== 'ap_mode' || !isset($st['data']['ch'], $st['data']['topic'], $st['data']['style'], $st['data']['min'])) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $d = $st['data'];
        $owner = $ctx->ownerId();
        if (!$app->channels->getOwned($owner, (int) $d['ch']) || $app->autopilots->countFor($owner) >= $app->autopilotLimit($owner)) {
            $app->states->clear($ctx->userId);
            self::show($ctx);
            return;
        }
        $app->states->clear($ctx->userId);
        $id = $app->autopilots->create($owner, (int) $d['ch'], (string) $d['topic'], (string) $d['style'], (int) $d['min'], $mode,
            self::startDay($ctx, (int) $d['min']), $app->now());
        if ($id === null) {
            self::show($ctx);
            return;
        }
        $ctx->reply($ctx->t('ap_saved', ['time' => Recurrence::clock((int) $d['min']), 'tz' => Html::e($ctx->tzName())]));
        self::view($ctx, $id, false);
    }

    /** Bugungi vaqt o'tib ketgan bo'lsa — bugungi sana (ish ertadan boshlanadi), aks holda null. */
    private static function startDay(Ctx $ctx, int $minute): ?string
    {
        $local = $ctx->app->now()->setTimezone($ctx->app->tzFor($ctx->ownerId()));
        return (int) $local->format('G') * 60 + (int) $local->format('i') >= $minute ? $local->format('Y-m-d') : null;
    }

    // ---------------------------------------------------------------- post yozish

    /** AI so'rovi matni: mavzu, uslub, sana va oxirgi postlar (takrorlanmasin). */
    public static function prompt(array $ap, string $localDate): string
    {
        $recent = Autopilots::recent($ap);
        return "Telegram kanal uchun bugungi yangi postni yoz — " . Ai::styleHow((string) $ap['style']) . ".\n"
            . "Har kuni boshqa jihatni yorit: maslahat, qiziq fakt, savol, misol yoki hikoya. Aniq bo'lmagan narx, sana va manzillarni o'ylab topma.\n"
            . "Bugungi sana: {$localDate}.\n\nKanal mavzusi:\n" . trim((string) $ap['topic'])
            . ($recent ? "\n\nOldingi postlar (ularni takrorlama):\n- " . implode("\n- ", $recent) : '');
    }

    /** «⚡ Hozir sinash»: post yoziladi va egasiga tekshirish uchun keladi (rejimdan qat'i nazar, kunlik vaqtga ta'sir qilmaydi). */
    public static function testNow(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $a = $app->autopilots->getOwned($ctx->ownerId(), $id);
        if ($a === null || !self::allowed($ctx)) {
            return;
        }
        $ch = $app->channels->getOwned($ctx->ownerId(), (int) $a['channel_ref']);
        if ($ch === null) {
            $ctx->reply($ctx->t('ap_stopped_channel'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        $max = PostRender::TEXT_LIMIT - 200;
        $lang = I18n::norm((string) ($app->users->get($ctx->ownerId())['lang'] ?? $ctx->lang));
        $res = AiHandler::run($ctx, Ai::system($lang, $max), self::prompt($a, $app->now()->setTimezone($ctx->tz())->format('Y-m-d')), $max);
        if ($res === null) {
            return;
        }
        $app->autopilots->pushRecent($id, Html::plain($res));
        $draftId = $app->autopilots->addDraft($a, $res, $app->now());
        self::sendDraft($app, $ctx->chatId, $ctx->lang, $draftId, (string) $ch['title'], $res, (int) $a['user_id']);
    }

    private static function sendDraft(App $app, int $chatId, string $lang, int $draftId, string $channel, string $text, int $owner): void
    {
        $app->tg->sendMessage($chatId, I18n::t('ap_draft', $lang, ['channel' => Html::e($channel)]));
        $rows = [
            [Keyboards::btn(I18n::t('btn_apd_ok', $lang), 'apd:ok:' . $draftId), Keyboards::btn(I18n::t('btn_apd_edit', $lang), 'apd:ed:' . $draftId)],
            [Keyboards::btn(I18n::t('btn_ai_again', $lang), 'apd:re:' . $draftId), Keyboards::btn(I18n::t('btn_apd_no', $lang), 'apd:no:' . $draftId)],
        ];
        PostRender::send($app->tg, $chatId, ['post_type' => 'text', 'text' => $text, 'file_id' => null], $app->config->str('bot_username'), $app->isFree($owner), $rows);
    }

    /** Cron: vaqti kelgan autopilotlar. @return int yozilgan postlar */
    public static function work(App $app, Scheduler $sch, float $deadline): int
    {
        $done = 0;
        $maxDay = $app->now()->modify('+1 day')->format('Y-m-d');
        foreach ($app->autopilots->candidates($maxDay, 200) as $a) {
            if ($done >= self::PER_RUN || microtime(true) >= $deadline - 1) {
                break;
            }
            $owner = (int) $a['user_id'];
            $local = $app->now()->setTimezone($app->tzFor($owner));
            $day = $local->format('Y-m-d');
            if ($a['last_run'] !== null && (string) $a['last_run'] >= $day) {
                continue;
            }
            $late = (int) $local->format('G') * 60 + (int) $local->format('i') - (int) $a['post_time'];
            if ($late < 0) {
                continue; // hali vaqti emas
            }
            if (!$app->autopilots->claimDay((int) $a['id'], $day)) {
                continue; // boshqa jarayon oldi
            }
            if ($late > Autopilots::LATE_MINUTES) {
                continue; // cron uzoq to'xtagan: eskirgan kun o'tkazib yuboriladi
            }
            try {
                if (self::runOne($app, $sch, $a, $local)) {
                    $done++;
                }
            } catch (\Throwable $e) {
                $app->log('autopilot #' . $a['id'] . ': ' . $e->getMessage());
            }
        }
        $app->autopilots->cleanup($app->now());
        return $done;
    }

    private static function runOne(App $app, Scheduler $sch, array $a, DateTimeImmutable $local): bool
    {
        $owner = (int) $a['user_id'];
        $lang = I18n::norm((string) ($app->users->get($owner)['lang'] ?? 'uz'));
        $id = (int) $a['id'];
        if ($app->autopilotLimit($owner) === 0) {
            $app->autopilots->setActive($id, false);
            $app->tg->sendMessage($owner, I18n::t('ap_stopped_plan', $lang), Keyboards::inline([[Keyboards::btn(I18n::t('btn_plans', $lang), 'pl:show')]]));
            return false;
        }
        $ch = $app->channels->getOwned($owner, (int) $a['channel_ref']);
        if ($ch === null) {
            $app->autopilots->setActive($id, false);
            $app->tg->sendMessage($owner, I18n::t('ap_stopped_channel', $lang));
            return false;
        }
        $day = $app->today();
        $src = $app->aiUsage->reserve($owner, $app->aiLimit($owner), $day, $app->nowSql());
        if ($src === null) {
            $app->tg->sendMessage($owner, I18n::t('ap_no_quota', $lang, ['channel' => Html::e((string) $ch['title'])]));
            return false;
        }
        $max = PostRender::TEXT_LIMIT - 200;
        $res = $app->ai->generate(Ai::system($lang, $max), self::prompt($a, $local->format('Y-m-d')), $max);
        if (empty($res['ok'])) {
            $app->aiUsage->refund($owner, $src, $day, $app->nowSql());
            $app->log('autopilot AI xato: ' . ($res['error'] ?? ''));
            $app->tg->sendMessage($owner, I18n::t('ap_fail', $lang, ['channel' => Html::e((string) $ch['title'])]));
            return false;
        }
        $text = (string) $res['text'];
        $app->autopilots->pushRecent($id, Html::plain($text));
        if ($a['mode'] === 'auto') {
            $pid = $app->posts->create($owner, (int) $ch['channel_id'], ['type' => 'text', 'file_id' => null, 'text' => $text], $app->nowSql(), true);
            $app->afterPostSaved($owner);
            if ($app->posts->claim($pid)) {
                $post = $app->posts->get($pid);
                if ($post) {
                    $sch->deliver($post); // natija haqida egasiga odatdagi xabar (notify_owner)
                }
            }
            return true;
        }
        $draftId = $app->autopilots->addDraft($a, $text, $app->now());
        self::sendDraft($app, $owner, $lang, $draftId, (string) $ch['title'], $text, $owner);
        return true;
    }

    // ---------------------------------------------------------------- qoralama tugmalari (tekshirib rejimi)

    public static function draftAction(Ctx $ctx, string $act, int $id): void
    {
        $app = $ctx->app;
        $d = $app->autopilots->draft($ctx->ownerId(), $id, $app->now());
        if ($d === null) {
            $ctx->reply($ctx->t('ap_draft_gone'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        $ch = $app->channels->getOwned($ctx->ownerId(), (int) $d['channel_ref']);
        if ($ch === null) {
            $app->autopilots->takeDraft($id, 'gone');
            $ctx->reply($ctx->t('ap_stopped_channel'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        if ($act === 'no') {
            $app->autopilots->takeDraft($id, 'skip');
            $ctx->reply($ctx->t('ap_skipped'), Keyboards::nav($ctx->lang, 'ap:show'));
            return;
        }
        if ($act === 'ed') {
            if (!$app->autopilots->takeDraft($id, 'edit')) {
                return;
            }
            $data = ['draft' => ['type' => 'text', 'file_id' => null, 'text' => (string) $d['text']], 'channel' => (int) $ch['id']];
            PostHandler::preview($ctx, $data); // odatdagi preview: tugma, vaqt, reaksiya, takror
            return;
        }
        if ($act === 're') {
            $a = $app->autopilots->getOwned($ctx->ownerId(), (int) $d['autopilot_id']);
            if ($a === null || !self::allowed($ctx)) {
                $ctx->reply($ctx->t('ap_draft_gone'), Keyboards::nav($ctx->lang, 'ap:show'));
                return;
            }
            $max = PostRender::TEXT_LIMIT - 200;
            $res = AiHandler::run($ctx, Ai::system($ctx->lang, $max), self::prompt($a, $app->now()->setTimezone($ctx->tz())->format('Y-m-d')), $max);
            if ($res === null) {
                return;
            }
            $app->autopilots->updateDraft($id, $res);
            $app->autopilots->pushRecent((int) $a['id'], Html::plain($res));
            self::sendDraft($app, $ctx->chatId, $ctx->lang, $id, (string) $ch['title'], $res, $ctx->ownerId());
            return;
        }
        // ok: darhol kanalga
        if (!$ctx->can('send_now')) {
            $ctx->reply($ctx->t('team_no_perm_now'));
            return;
        }
        if (!$app->autopilots->takeDraft($id, 'sent')) {
            return; // ikkinchi bosish
        }
        $pid = $app->posts->create($ctx->ownerId(), (int) $ch['channel_id'], ['type' => 'text', 'file_id' => null, 'text' => (string) $d['text']],
            $app->nowSql(), false, null, $ctx->userId);
        $app->afterPostSaved($ctx->ownerId());
        $r = ['status' => 'retry'];
        if ($app->posts->claim($pid)) {
            $post = $app->posts->get($pid);
            $r = (new Scheduler($app))->deliver($post ?? []);
        }
        $name = Html::e((string) $ch['title']);
        if ($r['status'] === 'sent') {
            $ctx->replyMenu($ctx->t('send_ok', ['channel' => $name]));
        } elseif ($r['status'] === 'retry') {
            $ctx->replyMenu($ctx->t('send_retry'));
        } else {
            $ctx->replyMenu($ctx->t('send_fail', ['reason' => $ctx->t((string) $r['reason'])]));
        }
    }
}
