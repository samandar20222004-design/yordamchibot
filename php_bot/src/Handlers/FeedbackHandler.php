<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Feedback;

/**
 * 💬 Fikr-mulohaza: foydalanuvchi xato / taklif / savol yozadi (matn yoki rasm + izoh), adminlarga darhol keladi,
 * admin botdan javob beradi, «hal qilindi» deb belgilaydi yoki spamchini bloklaydi. Spam himoyasi — Repo\Feedback::check.
 * Kirish: Sozlamalar va Yordam ekrani, /feedback, Mini App Profil (ko'prik orqali).
 */
final class FeedbackHandler
{
    private const ICONS = ['bug' => '🐞', 'idea' => '💡', 'q' => '❓'];

    public static function start(Ctx $ctx, bool $edit = false): void
    {
        $ctx->app->states->clear($ctx->userId);
        if ($ctx->app->feedback->isBlocked($ctx->userId)) {
            $ctx->reply($ctx->t('fb_blocked'), Keyboards::nav($ctx->lang, 'set:show'));
            return;
        }
        $kb = Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_fb_bug'), 'fb:k:bug'), Keyboards::btn($ctx->t('btn_fb_idea'), 'fb:k:idea')],
            [Keyboards::btn($ctx->t('btn_fb_q'), 'fb:k:q'), Keyboards::btn($ctx->t('btn_help'), 'set:help')],
            Keyboards::navRow($ctx->lang, 'set:show'),
        ]);
        $edit ? $ctx->edit($ctx->t('fb_title'), $kb) : $ctx->reply($ctx->t('fb_title'), $kb);
    }

    public static function kind(Ctx $ctx, string $kind): void
    {
        if (!in_array($kind, Feedback::KINDS, true)) {
            return;
        }
        if ($ctx->app->feedback->isBlocked($ctx->userId)) {
            $ctx->reply($ctx->t('fb_blocked'));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'fb_text', ['kind' => $kind]);
        $ctx->reply($ctx->t('fb_ask_' . $kind, ['min' => Feedback::MIN_LEN, 'max' => Feedback::MAX_LEN]), Keyboards::nav($ctx->lang, 'fb:start'));
    }

    /** Foydalanuvchi matni (yoki rasm + izoh) keldi. */
    public static function input(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $msg = $ctx->message ?? [];
        $kind = (string) ($state['data']['kind'] ?? 'idea');
        $body = trim((string) ($msg['text'] ?? $msg['caption'] ?? ''));
        $fileId = null;
        if (isset($msg['photo']) && is_array($msg['photo']) && $msg['photo']) {
            $last = end($msg['photo']);
            $fileId = isset($last['file_id']) ? (string) $last['file_id'] : null;
        }
        $back = Keyboards::nav($ctx->lang, 'fb:start');
        if ($body === '' && $fileId === null) {
            $ctx->reply($ctx->t('fb_need_text', ['min' => Feedback::MIN_LEN]), $back);
            return;
        }
        if (mb_strlen($body) < Feedback::MIN_LEN) {
            $ctx->reply($ctx->t('fb_short', ['min' => Feedback::MIN_LEN]), $back);
            return;
        }
        if (mb_strlen($body) > Feedback::MAX_LEN) {
            $ctx->reply($ctx->t('fb_long', ['max' => Feedback::MAX_LEN, 'n' => mb_strlen($body)]), $back);
            return;
        }
        $wait = 0;
        $why = $app->feedback->check($ctx->userId, $body, $app->now(), $wait);
        if ($why !== null) {
            $app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('fb_err_' . $why, ['s' => $wait, 'h' => Feedback::PER_HOUR, 'd' => Feedback::PER_DAY]));
            return;
        }
        if (!$app->states->take($ctx->userId, 'fb_text')) {
            return; // parallel ikkinchi nusxa
        }
        $id = $app->feedback->create($ctx->userId, $kind, $body, $fileId, $app->now());
        $ctx->replyMenu($ctx->t('fb_thanks', ['id' => $id]));
        self::notifyAdmins($ctx, $id, $kind, $body, $fileId);
    }

    private static function notifyAdmins(Ctx $ctx, int $id, string $kind, string $body, ?string $fileId): void
    {
        $app = $ctx->app;
        $u = $app->users->get($ctx->userId);
        $who = Html::e($ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId)
            . (!empty($u['username']) ? ' @' . Html::e((string) $u['username']) : '') . ' (<code>' . $ctx->userId . '</code>)';
        foreach ((array) $app->config->get('admin_ids') as $adminId) {
            $adminId = (int) $adminId;
            if ($adminId === $ctx->userId) {
                continue;
            }
            $lang = I18n::norm($app->users->get($adminId)['lang'] ?? 'uz');
            if ($fileId !== null) {
                $app->tg->call('sendPhoto', ['chat_id' => $adminId, 'photo' => $fileId, 'caption' => '💬 #' . $id]);
            }
            $app->tg->sendMessage($adminId, I18n::t('fb_admin_new', $lang, [
                'icon' => self::ICONS[$kind] ?? '💬', 'kind' => I18n::t('fb_kind_' . $kind, $lang), 'id' => $id, 'user' => $who,
                'lang' => $ctx->lang, 'body' => Html::e($body),
            ]), self::adminKb($lang, $id, $ctx->userId));
        }
    }

    private static function adminKb(string $lang, int $id, int $userId): array
    {
        return Keyboards::inline([
            [Keyboards::btn(I18n::t('btn_fb_reply', $lang), 'fb:r:' . $id), Keyboards::btn(I18n::t('btn_fb_done', $lang), 'fb:ok:' . $id)],
            [Keyboards::btn(I18n::t('btn_fb_block', $lang), 'fb:bl:' . $userId)],
        ]);
    }

    // ------------------------------------------------------------------ admin

    /** /feedback (admin): ochiq murojaatlar ro'yxati. */
    public static function adminList(Ctx $ctx): void
    {
        $rows = $ctx->app->feedback->open(15);
        if (!$rows) {
            $ctx->reply($ctx->t('fb_admin_empty'), Keyboards::nav($ctx->lang));
            return;
        }
        $kb = [];
        foreach ($rows as $r) {
            $name = trim((string) ($r['full_name'] ?? '')) !== '' ? (string) $r['full_name'] : (string) $r['user_id'];
            $kb[] = [Keyboards::btn((self::ICONS[$r['kind']] ?? '💬') . ' #' . (int) $r['id'] . ' · ' . mb_substr($name, 0, 14) . ' · '
                . mb_substr(preg_replace('/\s+/u', ' ', (string) $r['body']), 0, 24), 'fb:v:' . (int) $r['id'])];
        }
        $kb[] = Keyboards::navRow($ctx->lang);
        $ctx->reply($ctx->t('fb_admin_list', ['n' => $ctx->app->feedback->openCount()]), Keyboards::inline($kb));
    }

    public static function adminView(Ctx $ctx, int $id): void
    {
        $f = $ctx->app->feedback->get($id);
        if (!$f) {
            $ctx->reply($ctx->t('fb_not_found'));
            return;
        }
        $u = $ctx->app->users->get((int) $f['user_id']);
        $who = Html::e((string) ($u['full_name'] ?? $f['user_id'])) . (!empty($u['username']) ? ' @' . Html::e((string) $u['username']) : '')
            . ' (<code>' . (int) $f['user_id'] . '</code>)';
        $ctx->reply($ctx->t('fb_admin_new', ['icon' => self::ICONS[$f['kind']] ?? '💬', 'kind' => $ctx->t('fb_kind_' . $f['kind']), 'id' => $id,
            'user' => $who, 'lang' => (string) ($u['lang'] ?? '—'), 'body' => Html::e((string) $f['body'])]) . "\n\n" . $ctx->t('fb_status_' . $f['status']),
            self::adminKb($ctx->lang, $id, (int) $f['user_id']));
    }

    public static function admin(Ctx $ctx, string $act, int $arg): void
    {
        $app = $ctx->app;
        if (!$app->isAdmin($ctx->userId)) {
            return;
        }
        if ($act === 'v') {
            self::adminView($ctx, $arg);
            return;
        }
        if ($act === 'bl' || $act === 'ub') {
            $app->feedback->block($arg, $act === 'bl', $app->now());
            $ctx->reply($ctx->t($act === 'bl' ? 'fb_blocked_ok' : 'fb_unblocked_ok', ['id' => $arg]),
                Keyboards::inline([[Keyboards::btn($ctx->t($act === 'bl' ? 'btn_fb_unblock' : 'btn_fb_block'), ($act === 'bl' ? 'fb:ub:' : 'fb:bl:') . $arg)]]));
            return;
        }
        $f = $app->feedback->get($arg);
        if (!$f) {
            $ctx->reply($ctx->t('fb_not_found'));
            return;
        }
        if ($act === 'r') {
            $app->states->set($ctx->userId, 'fb_reply', ['id' => $arg]);
            $ctx->reply($ctx->t('fb_reply_ask', ['id' => $arg]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'fb:cx')]]));
            return;
        }
        if ($act === 'ok') {
            if ($app->feedback->setStatus($arg, 'done', $app->now())) {
                self::toUser($ctx, $f, I18n::t('fb_done_user', self::langOf($ctx, (int) $f['user_id']), ['id' => $arg]));
            }
            $ctx->reply($ctx->t('fb_done_ok', ['id' => $arg]));
        }
    }

    /** Admin javob matni. */
    public static function replyInput(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $id = (int) ($state['data']['id'] ?? 0);
        $text = trim((string) ($ctx->message['text'] ?? ''));
        $f = $app->feedback->get($id);
        if (!$app->isAdmin($ctx->userId) || !$f) {
            $app->states->clear($ctx->userId);
            return;
        }
        if ($text === '' || mb_strlen($text) > 3000) {
            $ctx->reply($ctx->t('fb_reply_ask', ['id' => $id]));
            return;
        }
        $app->states->clear($ctx->userId);
        $lang = self::langOf($ctx, (int) $f['user_id']);
        $ok = self::toUser($ctx, $f, I18n::t('fb_answer_user', $lang, ['id' => $id, 'q' => Html::e(mb_substr((string) $f['body'], 0, 200)), 'a' => Html::e($text)]));
        $app->feedback->setStatus($id, 'answered', $app->now());
        $ctx->replyMenu($ctx->t($ok ? 'fb_reply_sent' : 'fb_reply_failed', ['id' => $id]));
    }

    private static function langOf(Ctx $ctx, int $userId): string
    {
        return I18n::norm($ctx->app->users->get($userId)['lang'] ?? 'uz');
    }

    private static function toUser(Ctx $ctx, array $f, string $text): bool
    {
        $res = $ctx->app->tg->sendMessage((int) $f['user_id'], $text);
        return !empty($res['ok']);
    }
}
