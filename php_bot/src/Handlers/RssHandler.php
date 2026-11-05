<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\RssFeeds;
use PostAssist\Services\Rss;
use PostAssist\Services\Scheduler;
use PostAssist\Services\TimeParser;

/**
 * 📰 RSS avtopost: sayt/blog lentasidagi YANGI maqolalar kanalga avtomatik chiqadi (sarlavha, qisqa mazmun, havola).
 * Ulanganda eski maqolalar yuborilmaydi; har tekshiruvda ko'pi bilan 3 ta. PRO — 3, ULTRA — 10 lenta.
 * 10 marta ketma-ket xato — lenta to'xtatiladi va egasiga aytiladi.
 */
final class RssHandler
{
    public const INTERVAL_MIN = 15;
    public const PER_RUN = 5;
    public const PER_CHECK = 3;

    private static function allowed(Ctx $ctx): bool
    {
        if (!$ctx->can('create')) {
            $ctx->reply($ctx->t('team_no_perm'), Keyboards::nav($ctx->lang, 'rss:show'));
            return false;
        }
        return true;
    }

    public static function show(Ctx $ctx, bool $edit = true): void
    {
        $app = $ctx->app;
        $own = $ctx->ownerId();
        $limit = $app->rssLimit($own);
        $list = $app->rss->listFor($own);
        $rows = [];
        foreach ($list as $f) {
            $rows[] = [Keyboards::btn(((int) $f['active'] === 1 ? '✅ ' : '⏸ ') . mb_substr((string) ($f['title'] ?: parse_url((string) $f['url'], PHP_URL_HOST)), 0, 24)
                . ' → ' . mb_substr((string) ($f['channel_title'] ?? '—'), 0, 16), 'rss:v:' . (int) $f['id'])];
        }
        if ($limit === 0) {
            $rows[] = [Keyboards::btn($ctx->t('btn_plans'), 'pl:show')];
        } elseif (count($list) < $limit) {
            $rows[] = [Keyboards::btn($ctx->t('btn_rss_add'), 'rss:new')];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'ch:list');
        $text = $ctx->t('rss_intro') . "\n\n" . ($limit === 0 ? $ctx->t('rss_paid') : ($list ? $ctx->t('rss_count', ['n' => count($list), 'max' => $limit]) : $ctx->t('rss_none')));
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    public static function begin(Ctx $ctx): void
    {
        $app = $ctx->app;
        $own = $ctx->ownerId();
        if (!self::allowed($ctx)) {
            return;
        }
        $limit = $app->rssLimit($own);
        if ($limit === 0 || $app->rss->countFor($own) >= $limit) {
            $ctx->reply($limit === 0 ? $ctx->t('rss_paid') : $ctx->t('rss_limit', ['max' => $limit]),
                Keyboards::inline([[Keyboards::btn($ctx->t('btn_plans'), 'pl:show')], Keyboards::navRow($ctx->lang, 'rss:show')]));
            return;
        }
        $channels = $app->channels->listFor($own);
        if (!$channels) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        if (count($channels) === 1) {
            self::pickChannel($ctx, (int) $channels[0]['id']);
            return;
        }
        $rows = [];
        foreach ($channels as $c) {
            $rows[] = [Keyboards::btn('📢 ' . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'rss:ch:' . (int) $c['id'])];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'rss:show');
        $ctx->reply($ctx->t('rss_pick_channel'), Keyboards::inline($rows));
    }

    public static function pickChannel(Ctx $ctx, int $ref): void
    {
        $ch = $ctx->app->channels->getOwned($ctx->ownerId(), $ref);
        if ($ch === null) {
            self::show($ctx, false);
            return;
        }
        $ctx->app->states->set($ctx->userId, 'rss_url', ['ch' => $ref]);
        $ctx->reply($ctx->t('rss_ask_url', ['channel' => Html::e((string) $ch['title'])]), Keyboards::nav($ctx->lang, 'rss:show'));
    }

    /** Manzil keldi (holat rss_url): lenta tekshiriladi va ulanadi (eski maqolalar yuborilmaydi). */
    public static function urlInput(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $own = $ctx->ownerId();
        $ref = (int) ($state['data']['ch'] ?? 0);
        $ch = $app->channels->getOwned($own, $ref);
        $limit = $app->rssLimit($own);
        if ($ch === null || $limit === 0 || $app->rss->countFor($own) >= $limit) {
            $app->states->clear($ctx->userId);
            self::show($ctx, false);
            return;
        }
        $url = Rss::normalizeUrl((string) ($ctx->message['text'] ?? ''));
        if ($url === null) {
            $ctx->reply($ctx->t('rss_err_bad_url'), Keyboards::nav($ctx->lang, 'rss:show'));
            return;
        }
        $wait = $ctx->reply($ctx->t('rss_checking'));
        $app->releaseClient();
        $res = $app->rssClient->load($url);
        if (!empty($wait['result']['message_id'])) {
            $app->tg->call('deleteMessage', ['chat_id' => $ctx->chatId, 'message_id' => (int) $wait['result']['message_id']]);
        }
        if (empty($res['ok'])) {
            $ctx->reply($ctx->t('rss_err_' . ($res['error'] ?? 'fetch')), Keyboards::nav($ctx->lang, 'rss:show'));
            return;
        }
        $id = $app->rss->create($own, $ref, $url, (string) ($res['title'] ?? ''), $res['items'][0]['id'], $app->now(),
            $app->now()->modify('+' . self::INTERVAL_MIN . ' minutes'));
        $app->states->clear($ctx->userId);
        if ($id === null) {
            $ctx->reply($ctx->t('rss_dup'), Keyboards::nav($ctx->lang, 'rss:show'));
            return;
        }
        $ctx->reply($ctx->t('rss_added', ['title' => Html::e((string) ($res['title'] ?: parse_url($url, PHP_URL_HOST))), 'n' => count($res['items']),
            'channel' => Html::e((string) $ch['title']), 'min' => self::INTERVAL_MIN]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_rss_last'), 'rss:last:' . $id)],
            [Keyboards::btn($ctx->t('btn_rss_list'), 'rss:show'), Keyboards::btn($ctx->t('btn_home'), 'm:home')],
        ]));
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $f = $ctx->app->rss->getOwned($ctx->ownerId(), $id);
        if ($f === null) {
            self::show($ctx);
            return;
        }
        $on = (int) $f['active'] === 1;
        $ctx->edit($ctx->t('rss_view', [
            'title' => Html::e((string) ($f['title'] ?: '—')), 'url' => Html::e((string) $f['url']), 'channel' => Html::e((string) ($f['channel_title'] ?? '—')),
            'checked' => $f['last_check'] ? TimeParser::show((string) $f['last_check'], $ctx->tz()) : '—', 'posted' => (int) $f['posted'],
            'status' => $ctx->t($on ? 'ap_on' : 'ap_off') . ((int) $f['fails'] > 0 ? ' · ⚠️ ' . (int) $f['fails'] : ''),
        ]), Keyboards::inline([
            [Keyboards::btn($ctx->t($on ? 'btn_ap_pause' : 'btn_ap_resume'), 'rss:tg:' . $id), Keyboards::btn($ctx->t('btn_rss_last'), 'rss:last:' . $id)],
            [Keyboards::btn($ctx->t('btn_ap_del'), 'rss:del:' . $id)],
            Keyboards::navRow($ctx->lang, 'rss:show'),
        ]));
    }

    public static function toggle(Ctx $ctx, int $id): void
    {
        $f = $ctx->app->rss->getOwned($ctx->ownerId(), $id);
        if ($f === null || !self::allowed($ctx)) {
            return;
        }
        $on = (int) $f['active'] !== 1;
        if ($on && $ctx->app->rssLimit($ctx->ownerId()) === 0) {
            $ctx->reply($ctx->t('rss_paid'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_plans'), 'pl:show')], Keyboards::navRow($ctx->lang, 'rss:show')]));
            return;
        }
        $ctx->app->rss->setActive($id, $on, $ctx->app->now());
        self::view($ctx, $id);
    }

    public static function askDelete(Ctx $ctx, int $id): void
    {
        if ($ctx->app->rss->getOwned($ctx->ownerId(), $id) === null) {
            self::show($ctx);
            return;
        }
        $ctx->edit($ctx->t('rss_del_confirm'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_ap_del'), 'rss:dok:' . $id), Keyboards::btn($ctx->t('btn_back'), 'rss:v:' . $id)]]));
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        if (!self::allowed($ctx)) {
            return;
        }
        $ctx->app->rss->delete($ctx->ownerId(), $id);
        $ctx->edit($ctx->t('rss_deleted'), Keyboards::nav($ctx->lang, 'rss:show'));
    }

    /** «📤 Oxirgisini hozir»: lentadagi eng yangi maqola kanalga darhol (tekshirish uchun). */
    public static function postLatest(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $f = $app->rss->getOwned($ctx->ownerId(), $id);
        if ($f === null || !$ctx->can('send_now')) {
            $ctx->reply($ctx->t($f === null ? 'rss_not_found' : 'team_no_perm_now'), Keyboards::nav($ctx->lang, 'rss:show'));
            return;
        }
        $app->releaseClient();
        $res = $app->rssClient->load((string) $f['url']);
        if (empty($res['ok'])) {
            $ctx->reply($ctx->t('rss_err_' . ($res['error'] ?? 'fetch')), Keyboards::nav($ctx->lang, 'rss:v:' . $id));
            return;
        }
        $r = self::publish($app, new Scheduler($app), $f, $res['items'][0]);
        $ctx->reply($r === 'sent' ? $ctx->t('send_ok', ['channel' => Html::e((string) ($f['channel_title'] ?? ''))])
            : ($r === 'retry' ? $ctx->t('send_retry') : $ctx->t('send_fail', ['reason' => $ctx->t($r)])), Keyboards::nav($ctx->lang, 'rss:v:' . $id));
    }

    /** @return string sent | retry | sabab kaliti */
    private static function publish(App $app, Scheduler $sch, array $f, array $item): string
    {
        $owner = (int) $f['user_id'];
        $ch = $app->channels->getOwned($owner, (int) $f['channel_ref']);
        if ($ch === null) {
            return 'reason_chat_not_found';
        }
        $pid = $app->posts->create($owner, (int) $ch['channel_id'], ['type' => 'text', 'file_id' => null, 'text' => Rss::postHtml($item)], $app->nowSql(), false);
        $app->afterPostSaved($owner);
        if (!$app->posts->claim($pid)) {
            return 'retry';
        }
        $post = $app->posts->get($pid);
        $r = $sch->deliver($post ?? []);
        return $r['status'] === 'sent' ? 'sent' : ($r['status'] === 'retry' ? 'retry' : (string) $r['reason']);
    }

    /** Cron: vaqti kelgan lentalar. @return int kanalga chiqqan maqolalar */
    public static function work(App $app, Scheduler $sch, float $deadline): int
    {
        $sent = 0;
        $n = 0;
        foreach ($app->rss->due($app->now(), 20) as $f) {
            if ($n >= self::PER_RUN || microtime(true) >= $deadline - 1) {
                break;
            }
            $interval = max(5, (int) ($app->config->get('rss_interval_min') ?? self::INTERVAL_MIN));
            if (!$app->rss->claim($f, $app->now()->modify('+' . $interval . ' minutes'))) {
                continue;
            }
            $n++;
            $owner = (int) $f['user_id'];
            $lang = I18n::norm((string) ($app->users->get($owner)['lang'] ?? 'uz'));
            try {
                if ($app->rssLimit($owner) === 0 || $app->channels->getOwned($owner, (int) $f['channel_ref']) === null) {
                    $app->rss->setActive((int) $f['id'], false, $app->now());
                    $app->tg->sendMessage($owner, I18n::t('rss_stopped', $lang, ['url' => Html::e((string) $f['url'])]));
                    continue;
                }
                $res = $app->rssClient->load((string) $f['url']);
                if (empty($res['ok'])) {
                    if ($app->rss->failed((int) $f['id'], $app->now()) >= RssFeeds::FAILS_LIMIT) {
                        $app->rss->setActive((int) $f['id'], false, $app->now());
                        $app->tg->sendMessage($owner, I18n::t('rss_stopped_fails', $lang, ['url' => Html::e((string) $f['url']), 'n' => RssFeeds::FAILS_LIMIT]));
                    }
                    continue;
                }
                $new = Rss::fresh($res['items'], $f['last_item'] !== null ? (string) $f['last_item'] : null, self::PER_CHECK);
                $posted = 0;
                foreach ($new as $it) {
                    if (self::publish($app, $sch, $f, $it) === 'sent') {
                        $posted++;
                    }
                }
                $app->rss->checked((int) $f['id'], $res['items'][0]['id'], $posted, $app->now());
                $sent += $posted;
            } catch (\Throwable $e) {
                $app->log('rss #' . $f['id'] . ': ' . $e->getMessage());
            }
        }
        return $sent;
    }
}
