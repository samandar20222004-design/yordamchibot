<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Team;

/**
 * 👥 Jamoa va rol. Egasi (ULTRA): yordamchi taklif qiladi (ruxsat to'plami: Hammasi / Muharrir / Faqat ko'rish), ro'yxat, olib tashlash.
 * Yordamchi: ish joyini tanlaydi (o'zi yoki egasi), jamoadan chiqadi. Taklif: /start team_<token> (bir martalik, 7 kun).
 */
final class TeamHandler
{
    public static function name(App $app, int $userId): string
    {
        $u = $app->users->get($userId);
        $n = trim((string) ($u['full_name'] ?? ''));
        return Html::e(mb_substr($n !== '' ? $n : (!empty($u['username']) ? '@' . $u['username'] : (string) $userId), 0, 40));
    }

    public static function permsText(Ctx $ctx, array $perms): string
    {
        if (!$perms) {
            return $ctx->t('team_perm_viewer');
        }
        return implode(', ', array_map(static function ($p) use ($ctx) {
            return $ctx->t('team_perm_' . $p);
        }, $perms));
    }

    public static function show(Ctx $ctx, bool $edit = true): void
    {
        $app = $ctx->app;
        $seats = $app->teamSeats($ctx->userId);
        $rows = [];
        if ($seats > 0) {
            $members = $app->team->members($ctx->userId);
            $lines = [];
            foreach ($members as $m) {
                $perms = array_values(array_filter(explode(',', (string) $m['perms'])));
                $lines[] = '• ' . self::name($app, (int) $m['member_id']) . ' — ' . self::permsText($ctx, $perms);
                $rows[] = [Keyboards::btn('🗑 ' . mb_substr(strip_tags(html_entity_decode(self::name($app, (int) $m['member_id']))), 0, 14), 'tm:rm:' . (int) $m['member_id'])];
            }
            $text = $ctx->t('team_owner', ['n' => count($members), 'seats' => $seats, 'list' => $lines ? implode("\n", $lines) : $ctx->t('team_empty')]);
            if (count($members) < $seats) {
                $rows[] = [Keyboards::btn($ctx->t('btn_team_invite'), 'tm:inv')];
            }
        } else {
            $text = $ctx->t('team_need_ultra');
            $rows[] = [Keyboards::btn($ctx->t('btn_plans'), 'pl:show')];
        }
        $owners = $app->team->ownersOf($ctx->userId);
        if ($owners) {
            $cur = $ctx->ownerId();
            $text .= "\n\n" . $ctx->t('team_member_title');
            $ws = [Keyboards::btn(($cur === $ctx->userId ? '✅ ' : '') . $ctx->t('btn_team_me'), 'tm:ws:0')];
            foreach ($owners as $o) {
                $oid = (int) $o['owner_id'];
                $perms = array_values(array_filter(explode(',', (string) $o['perms'])));
                $text .= "\n• " . self::name($app, $oid) . ' — ' . self::permsText($ctx, $perms) . ($app->teamSeats($oid) === 0 ? ' ' . $ctx->t('team_owner_paused') : '');
                $ws[] = Keyboards::btn(($cur === $oid ? '✅ ' : '') . '👥 ' . mb_substr(strip_tags(html_entity_decode(self::name($app, $oid))), 0, 12), 'tm:ws:' . $oid);
                $rows[] = [Keyboards::btn($ctx->t('btn_team_leave') . ' ' . mb_substr(strip_tags(html_entity_decode(self::name($app, $oid))), 0, 8), 'tm:lv:' . $oid)];
            }
            array_unshift($rows, array_slice($ws, 0, 3));
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'set:show');
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    public static function askPreset(Ctx $ctx): void
    {
        if ($ctx->app->teamSeats($ctx->userId) === 0) {
            self::show($ctx);
            return;
        }
        $ctx->edit($ctx->t('team_pick_preset'), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_team_all'), 'tm:ip:all')],
            [Keyboards::btn($ctx->t('btn_team_editor'), 'tm:ip:editor')],
            [Keyboards::btn($ctx->t('btn_team_viewer'), 'tm:ip:viewer')],
            Keyboards::navRow($ctx->lang, 'set:team'),
        ]));
    }

    public static function invite(Ctx $ctx, string $preset): void
    {
        $app = $ctx->app;
        $r = $app->team->createInvite($ctx->userId, $preset, $app->teamSeats($ctx->userId), $app->now());
        if (isset($r['error'])) {
            $ctx->edit($ctx->t('team_inv_' . $r['error'], ['n' => Team::INVITES_PER_DAY]), Keyboards::nav($ctx->lang, 'set:team'));
            return;
        }
        $link = 'https://t.me/' . $app->config->str('bot_username') . '?start=team_' . $r['token'];
        $share = 'https://t.me/share/url?url=' . rawurlencode($link) . '&text=' . rawurlencode($ctx->t('team_share_text'));
        $ctx->edit($ctx->t('team_invite_link', ['link' => Html::e($link), 'days' => Team::INVITE_DAYS, 'perms' => self::permsText($ctx, Team::PRESETS[$preset])]),
            Keyboards::inline([[['text' => $ctx->t('btn_share'), 'url' => $share]], Keyboards::navRow($ctx->lang, 'set:team')]));
    }

    /** /start team_<token> */
    public static function accept(Ctx $ctx, string $token): void
    {
        $app = $ctx->app;
        $r = $app->team->accept($token, $ctx->userId, static function (int $owner) use ($app): int {
            return $app->teamSeats($owner);
        }, $app->now());
        if ($r['status'] !== 'ok') {
            $ctx->replyMenu($ctx->t('team_accept_' . $r['status']));
            return;
        }
        $owner = (int) $r['owner'];
        $ctx->resetOwner();
        $ctx->replyMenu($ctx->t('team_accept_ok', ['owner' => self::name($app, $owner), 'perms' => self::permsText($ctx, $r['perms'])]));
        $ou = $app->users->get($owner);
        $app->tg->sendMessage($owner, I18n::t('team_joined_notice', I18n::norm($ou['lang'] ?? 'uz'), ['name' => self::name($app, $ctx->userId)]));
    }

    public static function askRemove(Ctx $ctx, int $memberId): void
    {
        if ($ctx->app->team->perms($ctx->userId, $memberId) === null) {
            self::show($ctx);
            return;
        }
        $ctx->edit($ctx->t('team_rm_ask', ['name' => self::name($ctx->app, $memberId)]), Keyboards::confirm($ctx->lang, 'tm:rmok:' . $memberId, 'set:team'));
    }

    public static function remove(Ctx $ctx, int $memberId): void
    {
        if ($ctx->app->team->remove($ctx->userId, $memberId)) {
            $mu = $ctx->app->users->get($memberId);
            $ctx->app->tg->sendMessage($memberId, I18n::t('team_removed_notice', I18n::norm($mu['lang'] ?? 'uz'), ['owner' => self::name($ctx->app, $ctx->userId)]));
        }
        self::show($ctx);
    }

    public static function leave(Ctx $ctx, int $ownerId): void
    {
        if ($ctx->app->team->remove($ownerId, $ctx->userId)) {
            $ou = $ctx->app->users->get($ownerId);
            $ctx->app->tg->sendMessage($ownerId, I18n::t('team_left_notice', I18n::norm($ou['lang'] ?? 'uz'), ['name' => self::name($ctx->app, $ctx->userId)]));
        }
        $ctx->resetOwner();
        self::show($ctx);
    }

    /** Ish joyini almashtirish: 0 — o'zim. */
    public static function switchTo(Ctx $ctx, int $ownerId): void
    {
        if ($ownerId !== 0 && ($ctx->app->team->perms($ownerId, $ctx->userId) === null || $ctx->app->teamSeats($ownerId) === 0)) {
            self::show($ctx);
            return;
        }
        $ctx->app->team->setWorkspace($ctx->userId, $ownerId === 0 ? null : $ownerId);
        $ctx->app->states->clear($ctx->userId);
        $ctx->resetOwner();
        self::show($ctx);
    }
}
