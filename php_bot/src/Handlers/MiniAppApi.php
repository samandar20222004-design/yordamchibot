<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Services\Ai;
use PostAssist\Services\Links;
use PostAssist\Services\Plans;
use PostAssist\Services\PostRender;
use PostAssist\Services\Recurrence;
use PostAssist\Services\Scheduler;
use PostAssist\Services\TimeParser;

/**
 * 📱 Mini App API (api.php). Har so'rov Telegram `initData` imzosi bilan tekshiriladi (HMAC-SHA256, bot tokeni bilan;
 * 24 soatdan eski imzo rad). Foydalanuvchi faqat O'Z kanali va O'Z postlari bilan ishlaydi (IDOR himoyasi).
 * Post yuborishni bot qiladi: «hozir» — darhol (Scheduler::deliver), vaqtli — cron.
 * Javob: [HTTP status, massiv]. Xato: ['ok' => false, 'error' => kod].
 */
final class MiniAppApi
{
    public const AUTH_MAX_AGE = 86400;
    public const UPLOAD_MAX = 10485760; // 10 MB

    /** @return array{0:int,1:array} */
    public static function handle(App $app, string $action, array $in, string $initData, ?array $file = null): array
    {
        $user = self::verify($initData, $app->config->str('bot_token'), $app->now()->getTimestamp());
        if ($user === null) {
            return [401, ['ok' => false, 'error' => 'auth']];
        }
        $uid = (int) $user['id'];
        $name = trim(((string) ($user['first_name'] ?? '')) . ' ' . ((string) ($user['last_name'] ?? '')));
        $saved = $app->users->upsert($uid, (string) ($user['username'] ?? ''), $name, I18n::detect($user['language_code'] ?? null));
        $ctx = new Ctx($app, $uid, $uid, I18n::norm($saved['lang']), (string) ($user['first_name'] ?? ''), null, null);
        try {
            switch ($action) {
                case 'me':
                    return [200, self::me($ctx)];
                case 'posts':
                    return [200, self::posts($ctx)];
                case 'post_create':
                    return self::create($ctx, $in);
                case 'post_update':
                    return self::update($ctx, $in);
                case 'post_cancel':
                    $ok = $ctx->can('delete') && $app->posts->cancel($ctx->ownerId(), (int) ($in['id'] ?? 0));
                    return $ok ? [200, ['ok' => true]] : [404, ['ok' => false, 'error' => 'not_found']];
                case 'settings':
                    return self::settings($ctx, $in);
                case 'ai':
                    return self::ai($ctx, $in);
                case 'upload':
                    return self::upload($ctx, $file);
                case 'draft':
                    return [200, self::draft($ctx)];
                case 'market':
                    return [200, self::market($ctx, $in)];
                case 'market_view':
                    return self::marketView($ctx, (int) ($in['id'] ?? 0));
                case 'market_threads':
                    return [200, self::marketThreads($ctx)];
                case 'market_thread':
                    return self::marketThread($ctx, (int) ($in['id'] ?? 0));
                case 'market_send':
                    return self::marketSend($ctx, $in);
            }
        } catch (\Throwable $e) {
            $app->log('miniapp ' . $action . ': ' . $e->getMessage());
            return [500, ['ok' => false, 'error' => 'server']];
        }
        return [404, ['ok' => false, 'error' => 'unknown_action']];
    }

    /** Telegram WebApp initData tekshiruvi. Natija — foydalanuvchi massivi yoki null. */
    public static function verify(string $initData, string $botToken, int $nowTs): ?array
    {
        if ($initData === '' || $botToken === '' || strlen($initData) > 8192) {
            return null;
        }
        parse_str($initData, $pairs);
        $hash = (string) ($pairs['hash'] ?? '');
        if (!preg_match('/^[a-f0-9]{64}$/', $hash)) {
            return null;
        }
        unset($pairs['hash']);
        ksort($pairs);
        $lines = [];
        foreach ($pairs as $k => $v) {
            if (!is_string($v)) {
                return null;
            }
            $lines[] = $k . '=' . $v;
        }
        $secret = hash_hmac('sha256', $botToken, 'WebAppData', true);
        if (!hash_equals(hash_hmac('sha256', implode("\n", $lines), $secret), $hash)) {
            return null;
        }
        $auth = (int) ($pairs['auth_date'] ?? 0);
        if ($auth <= 0 || $nowTs - $auth > self::AUTH_MAX_AGE || $auth - $nowTs > 300) {
            return null;
        }
        $user = json_decode((string) ($pairs['user'] ?? ''), true);
        return is_array($user) && (int) ($user['id'] ?? 0) > 0 && empty($user['is_bot']) ? $user : null;
    }

    private static function me(Ctx $ctx): array
    {
        $app = $ctx->app;
        $own = $ctx->ownerId();
        $tier = $app->isAdmin($own) ? Plans::ENTERPRISE : $app->tier($own);
        $plan = $app->users->plan($own);
        $lim = $app->isAdmin($own) ? ['channels' => 0, 'queue' => 0] : Plans::limits($tier, $app->config);
        $aiLimit = $app->aiLimit($own);
        $channels = array_map(static function ($c) {
            return ['id' => (int) $c['id'], 'title' => (string) ($c['title'] ?: $c['channel_id']), 'username' => $c['username']];
        }, $app->channels->listFor($own));
        $stats = $app->posts->userStats($own);
        return ['ok' => true,
            'user' => ['id' => $ctx->userId, 'name' => $ctx->firstName, 'lang' => $ctx->lang, 'timezone' => $ctx->tzName(),
                'is_admin' => $app->isAdmin($ctx->userId)],
            'plan' => ['tier' => $tier, 'name' => Plans::NAMES[$tier], 'free' => $app->isFree($own),
                'expires' => ($tier === Plans::PRO || $tier === Plans::ULTRA) && !empty($plan['subscription_expires_at'])
                    ? TimeParser::show((string) $plan['subscription_expires_at'], $ctx->tz()) : null,
                'channels_max' => $lim['channels'], 'queue_max' => $lim['queue']],
            'stats' => $stats + ['channels' => count($channels)],
            'ai' => ['enabled' => $app->ai->enabled(), 'limit' => $aiLimit,
                'left' => $aiLimit === 0 ? null : max(0, $aiLimit - $app->aiUsage->usedOn($own, $app->today())),
                'credits' => $app->credits->balance($own)],
            'channels' => $channels,
            'workspace' => $ctx->inTeam() ? ['owner_id' => $own, 'owner' => trim(strip_tags($ctx->workspaceLine())),
                'perms' => array_values(array_filter(['create', 'send_now', 'delete', 'ai'], static function ($p) use ($ctx) {
                    return $ctx->can($p);
                }))] : null,
            'bot' => $app->config->str('bot_username'),
            'now_local' => $app->now()->setTimezone($ctx->tz())->format('Y-m-d\TH:i'),
            'timezones' => array_keys(\PostAssist\Keyboards::TIMEZONES),
            'reaction_sets' => PostRender::REACTION_SETS,
            'auto_delete' => \PostAssist\Keyboards::AUTO_DELETE,
        ];
    }

    private static function postOut(Ctx $ctx, array $p): array
    {
        $rec = null;
        if (!empty($p['recurrence_type'])) {
            $rec = PostHandler::repeatLabel($ctx, ['type' => $p['recurrence_type'], 'time' => (int) $p['recurrence_time'],
                'day' => $p['recurrence_day'] !== null ? (int) $p['recurrence_day'] : null]);
        }
        return ['id' => (int) $p['id'], 'type' => (string) $p['post_type'], 'text' => (string) $p['text'],
            'channel' => (string) ($p['channel_title'] ?? $p['channel_id']),
            'when' => TimeParser::show((string) $p['scheduled_time'], $ctx->tz()),
            'when_local' => (new DateTimeImmutable((string) $p['scheduled_time'], new DateTimeZone('UTC')))->setTimezone($ctx->tz())->format('Y-m-d\TH:i'),
            'repeat' => $rec, 'sent_count' => (int) $p['sent_count'], 'button' => $p['button_text'] ? [$p['button_text'], $p['button_url']] : null,
            'reactions' => $p['reactions'], 'delete_after' => $p['delete_after'] !== null ? (int) $p['delete_after'] : null,
            'media_count' => $p['post_type'] === 'album' ? count(PostRender::albumMedia($p)) : ($p['file_id'] ? 1 : 0)];
    }

    private static function posts(Ctx $ctx): array
    {
        return ['ok' => true, 'posts' => array_map(static function ($p) use ($ctx) {
            return self::postOut($ctx, $p);
        }, $ctx->app->posts->listPending($ctx->ownerId(), 50))];
    }

    /** Mahalliy «YYYY-MM-DDTHH:MM» -> UTC (kelajakda, 1 yil ichida) yoki xato kodi. @return DateTimeImmutable|string */
    private static function parseWhen(Ctx $ctx, string $when)
    {
        if (!preg_match('/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/', $when, $m) || !checkdate((int) $m[2], (int) $m[3], (int) $m[1])
            || (int) $m[4] > 23 || (int) $m[5] > 59) {
            return 'bad_time';
        }
        $utc = (new DateTimeImmutable('now', $ctx->tz()))->setDate((int) $m[1], (int) $m[2], (int) $m[3])->setTime((int) $m[4], (int) $m[5], 0)
            ->setTimezone(new DateTimeZone('UTC'));
        $diff = $utc->getTimestamp() - $ctx->app->now()->getTimestamp();
        if ($diff < TimeParser::MIN_AHEAD_SEC) {
            return 'past';
        }
        if ($diff > TimeParser::MAX_AHEAD_DAYS * 86400) {
            return 'too_far';
        }
        return $utc;
    }

    /** Mini App muharriridan kelgan HTML: tozalanadi va uzunligi tekshiriladi. @return string|array */
    private static function cleanText(string $html, string $type)
    {
        $clean = Html::sanitize($html);
        $max = PostRender::limitFor($type === 'album' ? 'photo' : $type);
        $len = Html::utf16Len(Html::plain($clean));
        return $len > $max ? ['too_long', $len, $max] : $clean;
    }

    /** @return array{0:int,1:array} */
    private static function create(Ctx $ctx, array $in): array
    {
        $app = $ctx->app;
        if (!$ctx->can('create') || (($in['when'] ?? 'now') === 'now' && !$ctx->can('send_now'))) {
            return [403, ['ok' => false, 'error' => 'no_perm']];
        }
        $channel = $app->channels->getOwned($ctx->ownerId(), (int) ($in['channel_id'] ?? 0));
        if (!$channel) {
            return [400, ['ok' => false, 'error' => 'channel']];
        }
        $draft = self::draftFromInput($ctx, $in);
        if (is_string($draft)) {
            return [400, ['ok' => false, 'error' => $draft]];
        }
        if (isset($draft['error'])) {
            return [400, ['ok' => false] + $draft];
        }
        $limit = $app->queueLimit($ctx->ownerId());
        if ($limit > 0 && $app->posts->pendingCount($ctx->ownerId()) >= $limit) {
            return [400, ['ok' => false, 'error' => 'queue_limit', 'max' => $limit]];
        }
        $now = ($in['when'] ?? 'now') === 'now';
        $utc = $now ? $app->now() : self::parseWhen($ctx, (string) $in['when']);
        if (is_string($utc)) {
            return [400, ['ok' => false, 'error' => $utc]];
        }
        $rec = null;
        $repeat = (string) ($in['repeat'] ?? '');
        if ($repeat !== '') {
            $second = isset($in['time2']) && $in['time2'] !== '' ? Recurrence::parseClock((string) $in['time2']) : null;
            $rec = Recurrence::fromFirst($repeat, $utc, $ctx->tz(), $second);
            if ($rec === null) {
                return [400, ['ok' => false, 'error' => 'repeat']];
            }
        }
        $id = $app->posts->create($ctx->ownerId(), (int) $channel['channel_id'], $draft, $utc->format('Y-m-d H:i:s'), !$now, $rec, $ctx->userId);
        $reward = $app->afterPostSaved($ctx->ownerId());
        if ($reward !== null) {
            PlansHandler::notifyReward($app, $reward, $ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId);
        }
        if (!$now) {
            return [200, ['ok' => true, 'id' => $id, 'status' => 'scheduled', 'when' => TimeParser::show($utc->format('Y-m-d H:i:s'), $ctx->tz())]];
        }
        if (!$app->posts->claim($id)) {
            return [200, ['ok' => true, 'id' => $id, 'status' => 'queued']];
        }
        $r = (new Scheduler($app))->deliver($app->posts->get($id) ?? []);
        if ($r['status'] === 'sent') {
            $next = $r['next'] ?? null;
            return [200, ['ok' => true, 'id' => $id, 'status' => 'sent', 'next' => $next ? TimeParser::show($next->format('Y-m-d H:i:s'), $ctx->tz()) : null]];
        }
        if ($r['status'] === 'retry') {
            return [200, ['ok' => true, 'id' => $id, 'status' => 'queued']];
        }
        return [200, ['ok' => false, 'id' => $id, 'status' => 'failed', 'error' => 'send_failed', 'reason' => $ctx->t($r['reason'])]];
    }

    /** @return array|string qoralama yoki xato kodi */
    private static function draftFromInput(Ctx $ctx, array $in)
    {
        $type = (string) ($in['type'] ?? 'text');
        $fileId = (string) ($in['file_id'] ?? '');
        if (!in_array($type, ['text', 'photo', 'video', 'animation', 'document', 'audio'], true)) {
            return 'type';
        }
        if ($type !== 'text' && !preg_match('/^[A-Za-z0-9_-]{10,255}$/', $fileId)) {
            return 'file';
        }
        $text = self::cleanText((string) ($in['text'] ?? ''), $type);
        if (is_array($text)) {
            return ['error' => 'too_long', 'len' => $text[1], 'max' => $text[2]];
        }
        if ($type === 'text' && trim(Html::plain($text)) === '') {
            return 'empty';
        }
        $draft = ['type' => $type, 'file_id' => $type === 'text' ? null : $fileId, 'text' => $text, 'button_text' => null, 'button_url' => null,
            'reactions' => null, 'delete_after' => null];
        $bt = trim((string) ($in['button_text'] ?? ''));
        $bu = trim((string) ($in['button_url'] ?? ''));
        if ($bt !== '' || $bu !== '') {
            $url = Links::normalize($bu);
            if ($bt === '' || mb_strlen($bt) > 64 || $url === null) {
                return 'button';
            }
            $draft['button_text'] = $bt;
            $draft['button_url'] = $url;
        }
        if (!empty($in['reactions'])) {
            $r = PostRender::parseReactions((string) $in['reactions']);
            if ($r === null) {
                return 'reactions';
            }
            $draft['reactions'] = $r;
        }
        $ad = (int) ($in['delete_after'] ?? 0);
        if ($ad > 0) {
            if (!in_array($ad, \PostAssist\Keyboards::AUTO_DELETE, true)) {
                return 'delete_after';
            }
            $draft['delete_after'] = $ad;
        }
        return $draft;
    }

    /** @return array{0:int,1:array} */
    private static function update(Ctx $ctx, array $in): array
    {
        if (!$ctx->can('create')) {
            return [403, ['ok' => false, 'error' => 'no_perm']];
        }
        $p = $ctx->app->posts->getOwnedPending($ctx->ownerId(), (int) ($in['id'] ?? 0));
        if (!$p) {
            return [404, ['ok' => false, 'error' => 'not_found']];
        }
        $text = null;
        if (array_key_exists('text', $in)) {
            $text = self::cleanText((string) $in['text'], (string) $p['post_type']);
            if (is_array($text)) {
                return [400, ['ok' => false, 'error' => 'too_long', 'len' => $text[1], 'max' => $text[2]]];
            }
            if ($p['post_type'] === 'text' && trim(Html::plain($text)) === '') {
                return [400, ['ok' => false, 'error' => 'empty']];
            }
        }
        $utcSql = null;
        if (!empty($in['when'])) {
            $utc = self::parseWhen($ctx, (string) $in['when']);
            if (is_string($utc)) {
                return [400, ['ok' => false, 'error' => $utc]];
            }
            $utcSql = $utc->format('Y-m-d H:i:s');
        }
        $ctx->app->posts->updatePending($ctx->ownerId(), (int) $p['id'], $text, $utcSql);
        return [200, ['ok' => true, 'post' => self::postOut($ctx, $ctx->app->posts->getOwnedPending($ctx->ownerId(), (int) $p['id']) ?? $p)]];
    }

    /** @return array{0:int,1:array} */
    private static function settings(Ctx $ctx, array $in): array
    {
        if (isset($in['lang'])) {
            if (!in_array($in['lang'], I18n::LANGS, true)) {
                return [400, ['ok' => false, 'error' => 'lang']];
            }
            $ctx->app->users->setLang($ctx->userId, (string) $in['lang']);
        }
        if (isset($in['timezone'])) {
            $tz = SettingsHandler::resolveTimezone((string) $in['timezone']);
            if ($tz === null) {
                return [400, ['ok' => false, 'error' => 'timezone']];
            }
            $ctx->app->users->setTimezone($ctx->userId, $tz);
            $ctx->app->forgetTz($ctx->userId);
        }
        return [200, ['ok' => true]];
    }

    /** AI: {mode: post, topic, style} yoki {mode: edit, text, action}. @return array{0:int,1:array} */
    private static function ai(Ctx $ctx, array $in): array
    {
        $app = $ctx->app;
        if (!$app->ai->enabled()) {
            return [400, ['ok' => false, 'error' => 'ai_disabled']];
        }
        if (!$ctx->can('ai')) {
            return [403, ['ok' => false, 'error' => 'no_perm']];
        }
        $mode = (string) ($in['mode'] ?? '');
        if ($mode === 'post') {
            $topic = trim((string) ($in['topic'] ?? ''));
            $style = (string) ($in['style'] ?? 'news');
            if (mb_strlen($topic) < AiHandler::TOPIC_MIN || mb_strlen($topic) > AiHandler::TOPIC_MAX || !in_array($style, Ai::STYLES, true)) {
                return [400, ['ok' => false, 'error' => 'bad_input']];
            }
            $max = PostRender::TEXT_LIMIT - 200;
            $system = Ai::system($ctx->lang, $max);
            $prompt = Ai::postPrompt($topic, $style);
        } elseif ($mode === 'edit') {
            $text = (string) ($in['text'] ?? '');
            $action = (string) ($in['action'] ?? '');
            $max = (int) ($in['max'] ?? PostRender::TEXT_LIMIT) === PostRender::CAPTION_LIMIT ? PostRender::CAPTION_LIMIT - 40 : PostRender::TEXT_LIMIT - 40;
            if (trim(Html::plain(Html::sanitize($text))) === '' || !in_array($action, Ai::EDITS, true)) {
                return [400, ['ok' => false, 'error' => 'bad_input']];
            }
            $system = Ai::system(Ai::editLang($action, $ctx->lang), $max);
            $prompt = Ai::editPrompt(Html::sanitize($text), $action);
        } else {
            return [400, ['ok' => false, 'error' => 'bad_input']];
        }
        $day = $app->today();
        $src = $app->aiUsage->reserve($ctx->ownerId(), $app->aiLimit($ctx->ownerId()), $day, $app->nowSql());
        if ($src === null) {
            return [429, ['ok' => false, 'error' => 'ai_limit']];
        }
        @set_time_limit(120);
        $res = $app->ai->generate($system, $prompt, $max);
        if (!$res['ok']) {
            $app->aiUsage->refund($ctx->ownerId(), $src, $day, $app->nowSql());
            return [502, ['ok' => false, 'error' => 'ai_failed']];
        }
        return [200, ['ok' => true, 'text' => $res['text']]];
    }

    /**
     * Rasm/video yuklash: fayl botning foydalanuvchi bilan chatiga yuboriladi (Telegram file_id olish uchun) va darhol o'chiriladi.
     * @return array{0:int,1:array}
     */
    private static function upload(Ctx $ctx, ?array $file): array
    {
        // api.php faqat is_uploaded_file() dan o'tgan faylni beradi
        if ($file === null || ($file['error'] ?? 1) !== UPLOAD_ERR_OK || !is_file((string) ($file['tmp_name'] ?? ''))) {
            return [400, ['ok' => false, 'error' => 'upload']];
        }
        $size = (int) ($file['size'] ?? 0);
        if ($size <= 0 || $size > self::UPLOAD_MAX) {
            return [400, ['ok' => false, 'error' => 'too_big', 'max_mb' => intdiv(self::UPLOAD_MAX, 1048576)]];
        }
        $path = (string) $file['tmp_name'];
        $mime = self::sniff($path);
        if ($mime === null) {
            return [400, ['ok' => false, 'error' => 'file_type']];
        }
        $kind = strpos($mime, 'video/') === 0 ? 'video' : 'photo';
        $method = $kind === 'video' ? 'sendVideo' : 'sendPhoto';
        $res = $ctx->app->tg->call($method, ['chat_id' => $ctx->userId, $kind => new \CURLFile($path, $mime, 'upload'), 'disable_notification' => true]);
        if (empty($res['ok'])) {
            return [502, ['ok' => false, 'error' => 'telegram']];
        }
        $msg = $res['result'];
        $fid = $kind === 'video' ? (string) ($msg['video']['file_id'] ?? '') : (string) (is_array($msg['photo'] ?? null) ? (end($msg['photo'])['file_id'] ?? '') : '');
        if (!empty($msg['message_id'])) {
            $ctx->app->tg->call('deleteMessage', ['chat_id' => $ctx->userId, 'message_id' => (int) $msg['message_id']]);
        }
        return $fid !== '' ? [200, ['ok' => true, 'type' => $kind, 'file_id' => $fid]] : [502, ['ok' => false, 'error' => 'telegram']];
    }

    /** Fayl turini baytlardan aniqlash (kengaytmaga ishonilmaydi). */
    public static function sniff(string $path): ?string
    {
        $h = (string) @file_get_contents($path, false, null, 0, 16);
        if (strncmp($h, "\xFF\xD8\xFF", 3) === 0) {
            return 'image/jpeg';
        }
        if (strncmp($h, "\x89PNG\r\n\x1a\n", 8) === 0) {
            return 'image/png';
        }
        if (strncmp($h, 'RIFF', 4) === 0 && substr($h, 8, 4) === 'WEBP') {
            return 'image/webp';
        }
        if (substr($h, 4, 4) === 'ftyp') {
            return 'video/mp4';
        }
        return null;
    }

    /** Botdagi tayyor qoralama (preview bosqichida) — Mini App'da davom ettirish uchun. */
    private static function draft(Ctx $ctx): array
    {
        $st = $ctx->state();
        $d = $st['data']['draft'] ?? null;
        if ($st === null || !is_array($d) || strpos($st['state'], 'post_') !== 0 || ($d['type'] ?? '') === 'album') {
            return ['ok' => true, 'draft' => null];
        }
        return ['ok' => true, 'draft' => ['type' => $d['type'], 'file_id' => $d['file_id'], 'text' => (string) $d['text'],
            'button_text' => $d['button_text'] ?? null, 'button_url' => $d['button_url'] ?? null, 'reactions' => $d['reactions'] ?? null,
            'delete_after' => $d['delete_after'] ?? null, 'channel_id' => (int) ($st['data']['channel'] ?? 0)]];
    }

    // ------------------------------------------------------------------ 💰 birja (katalog, e'lon, suhbat; e'lon qo'yish — botda)

    private static function listingOut(Ctx $ctx, array $l): array
    {
        return ['id' => (int) $l['id'], 'title' => (string) ($l['title'] ?? ''), 'username' => (string) $l['username'],
            'subscribers' => (int) $l['subscribers'], 'price' => MarketHandler::price($l), 'category' => (string) $l['category'],
            'category_name' => I18n::t('mkc_' . $l['category'], $ctx->lang), 'description' => (string) ($l['description'] ?? ''),
            'mine' => (int) $l['owner_id'] === $ctx->userId];
    }

    private static function market(Ctx $ctx, array $in): array
    {
        $app = $ctx->app;
        $cat = isset($in['cat']) && in_array($in['cat'], \PostAssist\Repo\Market::CATEGORIES, true) ? (string) $in['cat'] : null;
        $page = max(0, min(500, (int) ($in['page'] ?? 0)));
        $res = $app->market->catalog($cat, $page);
        $cats = [];
        foreach (\PostAssist\Repo\Market::CATEGORIES as $c) {
            $cats[] = ['key' => $c, 'name' => I18n::t('mkc_' . $c, $ctx->lang)];
        }
        return ['ok' => true, 'items' => array_map(static function ($l) use ($ctx) {
            return self::listingOut($ctx, $l);
        }, $res['rows']), 'total' => $res['total'], 'page' => $page, 'pages' => (int) ceil($res['total'] / \PostAssist\Repo\Market::PAGE),
            'categories' => $cats, 'cat' => $cat, 'banned' => $app->market->isBanned($ctx->userId),
            'mine' => array_map(static function ($l) use ($ctx) {
                return self::listingOut($ctx, $l) + ['status' => (string) $l['status']];
            }, $app->market->mine($ctx->userId))];
    }

    private static function marketView(Ctx $ctx, int $id): array
    {
        $l = $ctx->app->market->get($id);
        if (!$l || ($l['status'] !== 'active' && (int) $l['owner_id'] !== $ctx->userId)) {
            return [404, ['ok' => false, 'error' => 'not_found']];
        }
        $t = $ctx->app->market->threadFor($id, $ctx->userId);
        return [200, ['ok' => true, 'listing' => self::listingOut($ctx, $l), 'thread' => $t ? (int) $t['id'] : null]];
    }

    private static function marketThreads(Ctx $ctx): array
    {
        $uid = $ctx->userId;
        return ['ok' => true, 'threads' => array_map(static function ($t) use ($uid, $ctx) {
            return ['id' => (int) $t['id'], 'title' => (string) ($t['title'] ?? ''), 'username' => (string) $t['username'],
                'role' => (int) $t['owner_id'] === $uid ? 'owner' : 'buyer', 'messages' => (int) $t['messages'],
                'blocked' => $t['status'] === 'blocked', 'last' => TimeParser::show((string) $t['last_at'], $ctx->tz())];
        }, $ctx->app->market->threadsOf($uid, 30))];
    }

    /** Suhbat xabarlari — faqat ishtirokchi ko'radi (IDOR). */
    private static function marketThread(Ctx $ctx, int $id): array
    {
        $t = $ctx->app->market->thread($id);
        if (!$t || ((int) $t['buyer_id'] !== $ctx->userId && (int) $t['owner_id'] !== $ctx->userId)) {
            return [404, ['ok' => false, 'error' => 'not_found']];
        }
        $uid = $ctx->userId;
        return [200, ['ok' => true, 'thread' => ['id' => (int) $t['id'], 'title' => (string) ($t['title'] ?? ''), 'username' => (string) $t['username'],
            'blocked' => $t['status'] === 'blocked', 'role' => (int) $t['owner_id'] === $uid ? 'owner' : 'buyer'],
            'messages' => array_map(static function ($m) use ($uid, $ctx) {
                return ['me' => (int) $m['sender_id'] === $uid, 'text' => (string) $m['body'], 'at' => TimeParser::show((string) $m['created_at'], $ctx->tz())];
            }, $ctx->app->market->messages($id, 40))]];
    }

    /** Yangi so'rov (listing) yoki suhbatga javob (thread) — bot bilan bir xil himoya (MarketHandler::send). */
    private static function marketSend(Ctx $ctx, array $in): array
    {
        $target = !empty($in['thread']) ? ['thread' => (int) $in['thread']] : ['listing' => (int) ($in['listing'] ?? 0)];
        $r = MarketHandler::send($ctx->app, $ctx->userId, $target, (string) ($in['text'] ?? ''));
        if ($r['code'] === 'ok') {
            return [200, ['ok' => true, 'thread' => $r['thread']]];
        }
        $key = [
            'len' => ['mk_msg_len', ['min' => MarketHandler::MSG_MIN, 'max' => MarketHandler::MSG_MAX]],
            'not_found' => ['mk_not_found', []], 'blocked' => ['mk_thread_blocked', []], 'banned' => ['mk_banned', []],
            'limit' => ['mk_limit', ['n' => \PostAssist\Repo\Market::REQUESTS_PER_DAY]],
            'full' => ['mk_msg_full', ['n' => \PostAssist\Repo\Market::MAX_MESSAGES]], 'dup' => ['mk_msg_dup', []],
            'unsafe' => ['mk_blocked_' . ($r['reason'] ?? 'link'), []],
        ][$r['code']] ?? ['mk_not_found', []];
        return [$r['code'] === 'not_found' ? 404 : 400, ['ok' => false, 'error' => $r['code'], 'message' => strip_tags(I18n::t($key[0], $ctx->lang, $key[1]))]];
    }
}
