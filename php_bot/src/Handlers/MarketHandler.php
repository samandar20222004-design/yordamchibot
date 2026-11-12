<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Repo\Market;
use PostAssist\Services\MarketSafety;
use PostAssist\Services\Region;
use PostAssist\Services\Countries;

/**
 * 💰 Reklama birjasi (Python `handlers/ad_market.py` qoidalari):
 *  - kanal egasi ochiq kanalini qo'yadi (bot va egasi admin — jonli tekshiruv; telefon tasdiqlangan bo'lishi shart);
 *  - reklama beruvchi katalogdan ko'radi va so'rov yozadi; yozishma BOT orqali (kontakt faqat o'zi ruxsat bersa);
 *  - pul botdan o'tmaydi; himoya: kuniga 5 yangi so'rov, karta/hamyon/havola to'siladi, ⚠️ belgilar, takror matn rad,
 *    🚩 e'longa 3 shikoyat — e'lon yopiladi, 🚩 firibgar 3 shikoyat — birjadan ban; admin /market_ban|unban|userban|userunban.
 */
final class MarketHandler
{
    public const DESC_MAX = 400;
    public const MSG_MIN = 10;
    public const MSG_MAX = 1000;

    private static function fmtNum(int $n): string
    {
        if ($n >= 1000000) {
            return round($n / 1000000, 1) . 'M';
        }
        return $n >= 10000 ? round($n / 1000, 1) . 'K' : (string) $n;
    }

    public static function price(array $l): string
    {
        return $l['currency'] === 'USD' ? '$' . number_format((int) $l['price'], 0, '', ' ') : number_format((int) $l['price'], 0, '', ' ') . ' UZS';
    }

    private static function banned(Ctx $ctx): bool
    {
        if ($ctx->app->market->isBanned($ctx->userId)) {
            $ctx->reply($ctx->t('mk_banned'), Keyboards::nav($ctx->lang));
            return true;
        }
        return false;
    }

    public static function home(Ctx $ctx, bool $edit = false): void
    {
        $ctx->app->states->clear($ctx->userId);
        $kb = Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_mk_catalog'), 'mk:cat'), Keyboards::btn($ctx->t('btn_mk_publish'), 'mk:pub')],
            [Keyboards::btn($ctx->t('btn_mk_threads'), 'mk:th'), Keyboards::btn($ctx->t('btn_mk_mine'), 'mk:my')],
            Keyboards::navRow($ctx->lang),
        ]);
        $edit ? $ctx->edit($ctx->t('mk_home'), $kb) : $ctx->reply($ctx->t('mk_home'), $kb);
    }

    public static function categories(Ctx $ctx): void
    {
        $rows = [];
        $row = [];
        foreach (Market::CATEGORIES as $c) {
            $row[] = Keyboards::btn($ctx->t('mkc_' . $c), 'mk:l:' . $c . ':0');
            if (count($row) === 2) {
                $rows[] = $row;
                $row = [];
            }
        }
        if ($row) {
            $rows[] = $row;
        }
        array_unshift($rows, [Keyboards::btn($ctx->t('btn_mk_all'), 'mk:l:all:0')]);
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:home');
        $ctx->edit($ctx->t('mk_pick_cat'), Keyboards::inline($rows));
    }

    public static function listing(Ctx $ctx, string $cat, int $page): void
    {
        // o'z davlati birinchi, keyin yaqin davlatlar, Global va boshqalar
        $r = $ctx->app->market->catalog($cat === 'all' ? null : $cat, $page, $ctx->app->userCountry($ctx->userId));
        $rows = [];
        foreach ($r['rows'] as $l) {
            $rows[] = [Keyboards::btn(self::flagOf($l) . ' ' . mb_substr((string) $l['title'], 0, 20) . ' · ' . self::fmtNum((int) $l['subscribers']) . ' · ' . self::price($l), 'mk:v:' . (int) $l['id'])];
        }
        $nav = [];
        if ($page > 0) {
            $nav[] = Keyboards::btn('◀️', 'mk:l:' . $cat . ':' . ($page - 1));
        }
        if (($page + 1) * Market::PAGE < $r['total']) {
            $nav[] = Keyboards::btn('▶️', 'mk:l:' . $cat . ':' . ($page + 1));
        }
        if ($nav) {
            $rows[] = $nav;
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:cat');
        $title = $cat === 'all' ? $ctx->t('btn_mk_all') : $ctx->t('mkc_' . $cat);
        $ctx->edit($r['total'] > 0 ? $ctx->t('mk_list', ['cat' => $title, 'n' => $r['total']]) : $ctx->t('mk_list_empty', ['cat' => $title]), Keyboards::inline($rows));
    }

    /** E'lon davlati bayrog'i (Global — 🌍). */
    public static function flagOf(array $l): string
    {
        $c = (string) ($l['country'] ?? '');
        return $c === '' || $c === Region::GLOBAL ? '🌍' : Countries::flag($c);
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $l = $ctx->app->market->get($id);
        if (!$l || $l['status'] !== 'active') {
            $ctx->edit($ctx->t('mk_not_found'), Keyboards::nav($ctx->lang, 'mk:cat'));
            return;
        }
        $rows = [[['text' => '📢 @' . $l['username'], 'url' => 'https://t.me/' . $l['username']]]];
        if ((int) $l['owner_id'] !== $ctx->userId) {
            $rows[] = [Keyboards::btn($ctx->t('btn_mk_ask'), 'mk:ask:' . $id), Keyboards::btn($ctx->t('btn_mk_report'), 'mk:rep:' . $id)];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:l:' . $l['category'] . ':0');
        $ctx->edit($ctx->t('mk_card', [
            'title' => Html::e((string) $l['title']), 'username' => Html::e((string) $l['username']), 'subs' => number_format((int) $l['subscribers'], 0, '', ' '),
            'cat' => $ctx->t('mkc_' . $l['category']), 'price' => self::price($l),
            'desc' => trim((string) $l['description']) !== '' ? Html::e((string) $l['description']) : '—',
        ]) . "\n" . $ctx->t('mk_region_line', ['region' => Html::e(Region::label((string) ($l['country'] ?? ''), $ctx->lang))]), Keyboards::inline($rows));
    }

    // ------------------------------------------------------------------ e'lon qo'yish

    public static function publish(Ctx $ctx): void
    {
        if (self::banned($ctx)) {
            return;
        }
        if (!$ctx->app->users->isPhoneVerified($ctx->userId)) {
            $ctx->app->states->set($ctx->userId, 'mk_phone');
            $ctx->reply($ctx->t('mk_phone_ask'), [
                'keyboard' => [[['text' => $ctx->t('btn_share_phone'), 'request_contact' => true]], [['text' => $ctx->t('btn_cancel')]]],
                'resize_keyboard' => true, 'one_time_keyboard' => true,
            ]);
            return;
        }
        $chs = array_values(array_filter($ctx->app->channels->listFor($ctx->userId), static function ($c) {
            return !empty($c['username']);
        }));
        if (!$chs) {
            $ctx->reply($ctx->t('mk_need_public'), Keyboards::nav($ctx->lang, 'mk:home'));
            return;
        }
        $rows = [];
        foreach ($chs as $c) {
            $rows[] = [Keyboards::btn('📢 ' . mb_substr((string) $c['title'], 0, 30), 'mk:pc:' . (int) $c['id'])];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:home');
        $ctx->reply($ctx->t('mk_pick_channel'), Keyboards::inline($rows));
    }

    /** Telefon (o'z kontakti) — birjada e'lon qo'yish uchun. Raqam saqlanmaydi. */
    public static function phone(Ctx $ctx): void
    {
        $c = $ctx->message['contact'] ?? null;
        if (!is_array($c)) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cancelled'));
            return;
        }
        if ((int) ($c['user_id'] ?? 0) !== $ctx->userId) {
            $ctx->reply($ctx->t('uz_verify_not_own'));
            return;
        }
        $ctx->app->states->clear($ctx->userId);
        $digits = (string) preg_replace('/\D+/', '', (string) ($c['phone_number'] ?? ''));
        preg_match('/^998\d{9}$/', $digits) ? $ctx->app->users->markUzVerified($ctx->userId) : $ctx->app->users->markPhoneVerified($ctx->userId);
        $ctx->replyMenu($ctx->t('mk_phone_ok'));
        self::publish($ctx);
    }

    /** Kanal tanlandi: jonli tekshiruv (ochiq, bot va egasi admin), obunachilar soni. */
    public static function pickChannel(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $ch = $app->channels->getOwned($ctx->userId, $id);
        if (!$ch || self::banned($ctx)) {
            return;
        }
        $info = $app->tg->call('getChat', ['chat_id' => (int) $ch['channel_id']]);
        $username = (string) ($info['result']['username'] ?? '');
        if (empty($info['ok']) || $username === '') {
            $ctx->reply($ctx->t('mk_need_public'), Keyboards::nav($ctx->lang, 'mk:home'));
            return;
        }
        $bot = $app->tg->call('getChatMember', ['chat_id' => (int) $ch['channel_id'], 'user_id' => ChannelHandler::botId($app)]);
        $me = $app->tg->call('getChatMember', ['chat_id' => (int) $ch['channel_id'], 'user_id' => $ctx->userId]);
        if (!in_array($bot['result']['status'] ?? '', ['administrator', 'creator'], true) || !in_array($me['result']['status'] ?? '', ['administrator', 'creator'], true)) {
            $ctx->reply($ctx->t('mk_need_admin'), Keyboards::nav($ctx->lang, 'mk:home'));
            return;
        }
        $cnt = $app->tg->call('getChatMemberCount', ['chat_id' => (int) $ch['channel_id']]);
        $data = ['ch' => ['channel_id' => (int) $ch['channel_id'], 'title' => (string) ($info['result']['title'] ?? $ch['title']), 'username' => $username],
            'subs' => !empty($cnt['ok']) && is_int($cnt['result'] ?? null) ? (int) $cnt['result'] : 0,
            'currency' => $app->users->isUzVerified($ctx->userId) ? 'UZS' : 'USD'];
        $app->states->set($ctx->userId, 'mk_price', $data);
        $ctx->reply($ctx->t($data['currency'] === 'UZS' ? 'mk_price_ask_uzs' : 'mk_price_ask_usd'), Keyboards::nav($ctx->lang, 'mk:home'));
    }

    public static function priceInput(Ctx $ctx, array $state): void
    {
        $data = $state['data'];
        $digits = (string) preg_replace('/[\s.,]/u', '', (string) ($ctx->message['text'] ?? ''));
        $usd = ($data['currency'] ?? 'UZS') === 'USD';
        [$min, $max] = $usd ? [1, 100000] : [1000, 1000000000];
        if (!ctype_digit($digits) || (int) $digits < $min || (int) $digits > $max) {
            $ctx->reply($ctx->t('mk_price_bad', ['min' => number_format($min, 0, '', ' '), 'max' => number_format($max, 0, '', ' ')]));
            return;
        }
        $data['price'] = (int) $digits;
        $ctx->app->states->set($ctx->userId, 'mk_desc', $data);
        $ctx->reply($ctx->t('mk_desc_ask', ['max' => self::DESC_MAX]), Keyboards::nav($ctx->lang, 'mk:home'));
    }

    public static function descInput(Ctx $ctx, array $state): void
    {
        $desc = trim((string) ($ctx->message['text'] ?? ''));
        if ($desc === '-') {
            $desc = '';
        }
        if (mb_strlen($desc) > self::DESC_MAX) {
            $ctx->reply($ctx->t('mk_desc_long', ['max' => self::DESC_MAX]));
            return;
        }
        $safe = MarketSafety::assess($desc);
        if (in_array($safe['reason'], ['card', 'wallet'], true)) {
            $ctx->reply($ctx->t('mk_blocked_' . $safe['reason']));
            return;
        }
        $data = $state['data'];
        $data['desc'] = $desc;
        $ctx->app->states->set($ctx->userId, 'mk_cat', $data);
        $rows = [];
        $row = [];
        foreach (Market::CATEGORIES as $c) {
            $row[] = Keyboards::btn($ctx->t('mkc_' . $c), 'mk:cs:' . $c);
            if (count($row) === 2) {
                $rows[] = $row;
                $row = [];
            }
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:home');
        $ctx->reply($ctx->t('mk_cat_ask'), Keyboards::inline($rows));
    }

    public static function saveCategory(Ctx $ctx, string $cat): void
    {
        $st = $ctx->state();
        if ($st === null || $st['state'] !== 'mk_cat' || !$ctx->app->states->take($ctx->userId, 'mk_cat')) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $d = $st['data'];
        $id = $ctx->app->market->upsert($ctx->userId, $d['ch'], (int) $d['price'], (string) $d['currency'], (string) $d['desc'], $cat, (int) $d['subs'], $ctx->app->now(),
            $ctx->app->userCountry($ctx->userId)); // standart — egasining davlati; «Mening e'lonlarim»da Global'ga o'zgartiriladi
        $l = $ctx->app->market->get($id);
        $ctx->reply($ctx->t($l && $l['status'] === 'banned' ? 'mk_saved_banned' : 'mk_saved', ['title' => Html::e((string) $d['ch']['title'])]),
            Keyboards::inline([[Keyboards::btn($ctx->t('btn_mk_mine'), 'mk:my')], Keyboards::navRow($ctx->lang, 'mk:home')]));
    }

    public static function mine(Ctx $ctx): void
    {
        $rows = [];
        $lines = [];
        foreach ($ctx->app->market->mine($ctx->userId) as $l) {
            $id = (int) $l['id'];
            $lines[] = '• ' . self::flagOf($l) . ' <b>' . Html::e((string) $l['title']) . '</b> — ' . self::price($l) . ' · ' . $ctx->t('mk_st_' . $l['status']);
            if ($l['status'] !== 'banned') {
                $rows[] = [Keyboards::btn(($l['status'] === 'active' ? '🙈 ' : '👁 ') . mb_substr((string) $l['title'], 0, 12), 'mk:hide:' . $id),
                    Keyboards::btn(self::flagOf($l), 'mk:rg:' . $id), Keyboards::btn('🔄', 'mk:upd:' . $id), Keyboards::btn('🗑', 'mk:del:' . $id)];
            }
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_mk_publish'), 'mk:pub')];
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:home');
        $ctx->edit($lines ? $ctx->t('mk_mine', ['list' => implode("\n", $lines)]) : $ctx->t('mk_mine_empty'), Keyboards::inline($rows));
    }

    /** Hudud: o'z davlatim ↔ 🌍 Global (boshqa davlatlarga ham reklama qabul qilaman). */
    public static function region(Ctx $ctx, int $id): void
    {
        $l = $ctx->app->market->get($id);
        if ($l && (int) $l['owner_id'] === $ctx->userId) {
            $own = $ctx->app->userCountry($ctx->userId);
            $cur = (string) ($l['country'] ?? '');
            $ctx->app->market->setCountry($id, $ctx->userId, $cur === Region::GLOBAL || $cur === '' ? $own : Region::GLOBAL);
        }
        self::mine($ctx);
    }

    public static function toggle(Ctx $ctx, int $id): void
    {
        $l = $ctx->app->market->get($id);
        if ($l && (int) $l['owner_id'] === $ctx->userId && $l['status'] !== 'banned') {
            $ctx->app->market->setStatus($id, $l['status'] === 'active' ? 'hidden' : 'active');
        }
        self::mine($ctx);
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        $ctx->app->market->delete($ctx->userId, $id);
        self::mine($ctx);
    }

    public static function refresh(Ctx $ctx, int $id): void
    {
        $l = $ctx->app->market->get($id);
        if ($l && (int) $l['owner_id'] === $ctx->userId) {
            $cnt = $ctx->app->tg->call('getChatMemberCount', ['chat_id' => (int) $l['channel_id']]);
            if (!empty($cnt['ok']) && is_int($cnt['result'] ?? null)) {
                $ctx->app->market->setSubscribers($id, (int) $cnt['result']);
            }
        }
        self::mine($ctx);
    }

    // ------------------------------------------------------------------ yozishma

    public static function ask(Ctx $ctx, int $listingId): void
    {
        $app = $ctx->app;
        if (self::banned($ctx)) {
            return;
        }
        $l = $app->market->get($listingId);
        if (!$l || $l['status'] !== 'active' || (int) $l['owner_id'] === $ctx->userId) {
            $ctx->reply($ctx->t('mk_not_found'), Keyboards::nav($ctx->lang, 'mk:cat'));
            return;
        }
        $t = $app->market->threadFor($listingId, $ctx->userId);
        if ($t && $t['status'] === 'blocked') {
            $ctx->reply($ctx->t('mk_thread_blocked'), Keyboards::nav($ctx->lang, 'mk:cat'));
            return;
        }
        if (!$t && $app->market->newThreadsToday($ctx->userId, $app->now()->modify('-1 day')->format('Y-m-d H:i:s')) >= Market::REQUESTS_PER_DAY) {
            $ctx->reply($ctx->t('mk_limit', ['n' => Market::REQUESTS_PER_DAY]), Keyboards::nav($ctx->lang, 'mk:cat'));
            return;
        }
        $app->states->set($ctx->userId, 'mk_msg', ['listing' => $listingId]);
        $ctx->reply($ctx->t('mk_ask', ['title' => Html::e((string) $l['title']), 'min' => self::MSG_MIN]), Keyboards::nav($ctx->lang, 'mk:v:' . $listingId));
    }

    public static function reply(Ctx $ctx, int $threadId): void
    {
        $t = $ctx->app->market->thread($threadId);
        if (!$t || ((int) $t['buyer_id'] !== $ctx->userId && (int) $t['owner_id'] !== $ctx->userId)) {
            return;
        }
        if ($t['status'] === 'blocked' || self::banned($ctx)) {
            $ctx->reply($ctx->t('mk_thread_blocked'), Keyboards::nav($ctx->lang, 'mk:th'));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'mk_msg', ['thread' => $threadId]);
        $ctx->reply($ctx->t('mk_reply_ask'), Keyboards::nav($ctx->lang, 'mk:t:' . $threadId));
    }

    /** Matn keldi (holat mk_msg): xavfsizlik, yozish, ikkinchi tomonga yetkazish. */
    public static function message(Ctx $ctx, array $state): void
    {
        $app = $ctx->app;
        $text = trim((string) ($ctx->message['text'] ?? ''));
        $r = self::send($app, $ctx->userId, $state['data'], $text);
        switch ($r['code']) {
            case 'len':
                $ctx->reply($ctx->t('mk_msg_len', ['min' => self::MSG_MIN, 'max' => self::MSG_MAX]));
                return;
            case 'not_found':
                $app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('mk_not_found'));
                return;
            case 'blocked':
            case 'banned':
                $app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t($r['code'] === 'banned' ? 'mk_banned' : 'mk_thread_blocked'));
                return;
            case 'limit':
                $app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('mk_limit', ['n' => Market::REQUESTS_PER_DAY]));
                return;
            case 'unsafe':
                $ctx->reply($ctx->t('mk_blocked_' . $r['reason']));
                return;
            case 'full':
            case 'dup':
                $ctx->reply($ctx->t('mk_msg_' . $r['code'], ['n' => Market::MAX_MESSAGES]));
                return;
        }
        $app->states->clear($ctx->userId);
        $ctx->reply($ctx->t('mk_sent'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_mk_threads'), 'mk:th')], Keyboards::navRow($ctx->lang)]));
    }

    /**
     * Birja xabari (bot va Mini App uchun umumiy): uzunlik, ban, blok, kunlik so'rov limiti, firibgarlik skaneri,
     * yozish va ikkinchi tomonga bot orqali yetkazish.
     * @param array{thread?:int, listing?:int} $target
     * @return array{code:string, reason?:string, thread?:int} code: ok|len|not_found|blocked|banned|limit|unsafe|full|dup
     */
    public static function send(App $app, int $uid, array $target, string $text): array
    {
        $text = trim($text);
        $len = mb_strlen($text);
        if ($len < self::MSG_MIN || $len > self::MSG_MAX) {
            return ['code' => 'len'];
        }
        if ($app->market->isBanned($uid)) {
            return ['code' => 'banned'];
        }
        $l = null;
        if (!empty($target['thread'])) {
            $t = $app->market->thread((int) $target['thread']);
            if (!$t) {
                return ['code' => 'not_found'];
            }
        } else {
            $l = $app->market->get((int) ($target['listing'] ?? 0));
            if (!$l || $l['status'] !== 'active' || (int) $l['owner_id'] === $uid) {
                return ['code' => 'not_found'];
            }
            $t = $app->market->threadFor((int) $l['id'], $uid);
            if (!$t && $app->market->newThreadsToday($uid, $app->now()->modify('-1 day')->format('Y-m-d H:i:s')) >= Market::REQUESTS_PER_DAY) {
                return ['code' => 'limit'];
            }
        }
        if ($t && ((int) $t['buyer_id'] !== $uid && (int) $t['owner_id'] !== $uid)) {
            return ['code' => 'not_found'];
        }
        if ($t && $t['status'] === 'blocked') {
            return ['code' => 'blocked'];
        }
        $isOwner = $t && (int) $t['owner_id'] === $uid;
        $u = $app->users->get($uid);
        $age = $u ? ($app->now()->getTimestamp() - (new DateTimeImmutable((string) $u['created_at'], new DateTimeZone('UTC')))->getTimestamp()) / 86400 : null;
        $safe = MarketSafety::assess($text, !$t || (int) $t['messages'] === 0, $age, $isOwner);
        if (!$safe['ok']) {
            return ['code' => 'unsafe', 'reason' => (string) $safe['reason']];
        }
        if (!$t && $l !== null) {
            $t = $app->market->thread($app->market->openThread($l, $uid, $app->now()));
        }
        if (!$t) {
            return ['code' => 'not_found'];
        }
        $res = $app->market->addMessage((int) $t['id'], $uid, $text, MarketSafety::dupHash($text), $app->now());
        if ($res !== 'ok') {
            return ['code' => $res];
        }
        $to = $isOwner ? (int) $t['buyer_id'] : (int) $t['owner_id'];
        $tu = $app->users->get($to);
        $lang = I18n::norm($tu['lang'] ?? 'uz');
        $warn = '';
        foreach ($safe['flags'] as $f) {
            $warn .= "\n" . I18n::t('mk_flag_' . $f, $lang);
        }
        $app->tg->sendMessage($to, I18n::t($isOwner ? 'mk_in_from_owner' : 'mk_in_from_buyer', $lang, ['title' => Html::e((string) $t['title']), 'id' => (int) $t['id'],
            'text' => Html::e($text)]) . ($warn !== '' ? "\n" . $warn : ''), Keyboards::inline([
            [Keyboards::btn(I18n::t('btn_mk_reply', $lang), 'mk:re:' . (int) $t['id']), Keyboards::btn(I18n::t('btn_mk_contact', $lang), 'mk:ct:' . (int) $t['id'])],
            [Keyboards::btn(I18n::t('btn_mk_fraud', $lang), 'mk:fr:' . (int) $t['id']), Keyboards::btn(I18n::t('btn_mk_block', $lang), 'mk:bl:' . (int) $t['id'])],
        ]));
        return ['code' => 'ok', 'thread' => (int) $t['id']];
    }

    /** Suhbatdagi ikkinchi tomon va uning xavfsizligi. */
    private static function party(Ctx $ctx, int $threadId): ?array
    {
        $t = $ctx->app->market->thread($threadId);
        if (!$t || ((int) $t['buyer_id'] !== $ctx->userId && (int) $t['owner_id'] !== $ctx->userId)) {
            return null;
        }
        $t['other'] = (int) $t['buyer_id'] === $ctx->userId ? (int) $t['owner_id'] : (int) $t['buyer_id'];
        return $t;
    }

    public static function contact(Ctx $ctx, int $threadId): void
    {
        $t = self::party($ctx, $threadId);
        if (!$t || $t['status'] === 'blocked') {
            return;
        }
        $u = $ctx->app->users->get($ctx->userId);
        $who = !empty($u['username']) ? '@' . Html::e((string) $u['username']) : '<a href="tg://user?id=' . $ctx->userId . '">' . Html::e((string) ($u['full_name'] ?: $ctx->userId)) . '</a>';
        $ou = $ctx->app->users->get($t['other']);
        $ctx->app->tg->sendMessage($t['other'], I18n::t('mk_contact_shared', I18n::norm($ou['lang'] ?? 'uz'), ['who' => $who, 'title' => Html::e((string) $t['title'])]));
        $ctx->reply($ctx->t('mk_contact_done'));
    }

    public static function block(Ctx $ctx, int $threadId): void
    {
        $t = self::party($ctx, $threadId);
        if ($t) {
            $ctx->app->market->blockThread($threadId);
            $ctx->reply($ctx->t('mk_blocked_done'), Keyboards::nav($ctx->lang, 'mk:th'));
        }
    }

    /** 🚩 Firibgar: 3 xil odamdan shikoyat — birjadan ban. */
    public static function fraud(Ctx $ctx, int $threadId): void
    {
        $app = $ctx->app;
        $t = self::party($ctx, $threadId);
        if (!$t) {
            return;
        }
        $app->market->blockThread($threadId);
        $app->market->report('user', $t['other'], $ctx->userId, $app->now());
        // Takroriy bosishda ham jami sanaladi (boshqa yo'ldan kelgan shikoyatlar bilan birga).
        $n = $app->market->reportCount('user', $t['other']);
        if ($n >= Market::REPORTS_LIMIT && !$app->market->isBanned($t['other'])) {
            $app->market->banUser($t['other'], true);
            PlansHandler::notifyAdmins($app, 'mk_admin_user_banned', ['id' => $t['other'], 'n' => $n]);
        }
        $ctx->reply($ctx->t('mk_fraud_done'), Keyboards::nav($ctx->lang, 'mk:th'));
    }

    /** 🚩 E'longa shikoyat: 3 ta — e'lon yopiladi. */
    public static function report(Ctx $ctx, int $id): void
    {
        $app = $ctx->app;
        $l = $app->market->get($id);
        if (!$l || (int) $l['owner_id'] === $ctx->userId) {
            return;
        }
        $n = $app->market->report('listing', $id, $ctx->userId, $app->now());
        if ($n !== null && $n >= Market::REPORTS_LIMIT && $l['status'] === 'active') {
            $app->market->setStatus($id, 'banned');
            PlansHandler::notifyAdmins($app, 'mk_admin_listing_banned', ['id' => $id, 'title' => Html::e((string) $l['title']), 'n' => $n]);
        }
        $ctx->reply($ctx->t($n === null ? 'mk_report_again' : 'mk_report_done'), Keyboards::nav($ctx->lang, 'mk:cat'));
    }

    public static function threads(Ctx $ctx): void
    {
        $rows = [];
        foreach ($ctx->app->market->threadsOf($ctx->userId) as $t) {
            $role = (int) $t['owner_id'] === $ctx->userId ? '📥' : '📤';
            $rows[] = [Keyboards::btn($role . ' ' . mb_substr((string) $t['title'], 0, 24) . ' #' . (int) $t['id'] . ($t['status'] === 'blocked' ? ' 🚫' : ''), 'mk:t:' . (int) $t['id'])];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:home');
        $ctx->edit($rows && count($rows) > 1 ? $ctx->t('mk_threads') : $ctx->t('mk_threads_empty'), Keyboards::inline($rows));
    }

    public static function thread(Ctx $ctx, int $threadId): void
    {
        $t = self::party($ctx, $threadId);
        if (!$t) {
            return;
        }
        $lines = [];
        foreach ($ctx->app->market->messages($threadId, 10) as $m) {
            $lines[] = ((int) $m['sender_id'] === $ctx->userId ? '🟦 ' . $ctx->t('mk_you') : '⬜ ' . $ctx->t('mk_them')) . ': ' . Html::e(mb_substr((string) $m['body'], 0, 300));
        }
        $rows = [];
        if ($t['status'] !== 'blocked') {
            $rows[] = [Keyboards::btn($ctx->t('btn_mk_reply'), 'mk:re:' . $threadId), Keyboards::btn($ctx->t('btn_mk_contact'), 'mk:ct:' . $threadId)];
            $rows[] = [Keyboards::btn($ctx->t('btn_mk_fraud'), 'mk:fr:' . $threadId), Keyboards::btn($ctx->t('btn_mk_block'), 'mk:bl:' . $threadId)];
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'mk:th');
        $ctx->edit($ctx->t('mk_thread', ['title' => Html::e((string) $t['title']), 'id' => $threadId, 'list' => $lines ? implode("\n\n", $lines) : '—']), Keyboards::inline($rows));
    }

    // ------------------------------------------------------------------ admin

    public static function admin(Ctx $ctx, string $cmd, array $args): bool
    {
        $map = ['/market_ban' => ['listing', 'banned'], '/market_unban' => ['listing', 'active'], '/market_userban' => ['user', true], '/market_userunban' => ['user', false]];
        if (!isset($map[$cmd])) {
            return false;
        }
        if (!$args || !ctype_digit($args[0])) {
            $ctx->reply($ctx->t('admin_usage', ['usage' => $cmd . ' ID']));
            return true;
        }
        [$kind, $val] = $map[$cmd];
        $ok = $kind === 'listing' ? $ctx->app->market->setStatus((int) $args[0], (string) $val) : $ctx->app->market->banUser((int) $args[0], (bool) $val);
        $ctx->reply($ctx->t($ok ? 'mk_admin_ok' : 'mk_not_found'));
        return true;
    }
}
