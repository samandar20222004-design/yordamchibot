<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use DateTimeImmutable;
use PostAssist\App;
use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Services\Links;
use PostAssist\Services\PostRender;
use PostAssist\Services\Recurrence;
use PostAssist\Services\Scheduler;
use PostAssist\Services\TimeParser;

/**
 * Oddiy post: kontent -> (kanal tanlash) -> ko'rinish (preview) -> hozir yuborish | vaqt belgilash.
 * Holat `user_states` da: post_content | post_pick | post_preview | post_btn | post_edit | post_time | post_rx | post_time2,
 * ma'lumot: ['draft' => [type, file_id, text, media, button_text, button_url, reactions, delete_after], 'channel' => channels.id,
 *            'repeat' => ['type' => daily|weekly|monthly|twice, 'second' => kechki vaqt (daqiqa)]].
 * «⚙️ Qo'shimcha»: havolali tugma, reaksiya, takrorlash, avto-o'chirish. Albom (2–10 fayl) — tugma va reaksiyasiz (Telegram cheklovi).
 */
final class PostHandler
{
    public static function begin(Ctx $ctx): void
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
        $ctx->app->states->set($ctx->userId, 'post_content');
        $rows = [];
        if ($ctx->app->templates->countFor($ctx->ownerId()) > 0) {
            $rows[] = [Keyboards::btn($ctx->t('btn_tpl_list'), 'tpl:list')];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')];
        $ctx->reply($ctx->workspaceLine() . $ctx->t('post_ask_content'), Keyboards::inline($rows));
    }

    /** Post kontenti keldi (yangi yoki tahrir). */
    public static function content(Ctx $ctx, array $state): void
    {
        $msg = $ctx->message ?? [];
        if (!empty($msg['media_group_id'])) {
            self::albumItem($ctx, (string) $msg['media_group_id']);
            return;
        }
        $draft = PostRender::draftFromMessage($msg);
        if ($draft === null) {
            $ctx->reply($ctx->t('post_unsupported'));
            return;
        }
        if ($draft['type'] === 'text' && trim(Html::plain($draft['text'])) === '') {
            $ctx->reply($ctx->t('post_unsupported'));
            return;
        }
        self::applyDraft($ctx, $state, $draft);
    }

    /** Yangi kontent: uzunlik tekshiruvi, eski sozlamalar (tugma, reaksiya, avto-o'chirish) saqlanadi, kanal tanlash, preview. */
    public static function applyDraft(Ctx $ctx, array $state, array $draft): void
    {
        $len = Html::utf16Len(Html::plain((string) $draft['text']));
        $max = PostRender::limitFor($draft['type'] === 'album' ? 'photo' : $draft['type']);
        if ($len > $max) {
            $ctx->reply($ctx->t($draft['type'] === 'text' ? 'post_too_long_text' : 'post_too_long_caption', ['len' => $len, 'max' => $max]));
            return;
        }
        $data = $state['data'];
        $old = $data['draft'] ?? [];
        foreach (['button_text', 'button_url', 'reactions', 'delete_after', 'options', 'hidden'] as $k) {
            $draft[$k] = $old[$k] ?? null;
        }
        if ($draft['type'] === 'album') {
            $draft['button_text'] = $draft['button_url'] = $draft['reactions'] = $draft['hidden'] = null; // albomga tugma qo'yib bo'lmaydi
        }
        $data['draft'] = $draft;
        if (empty($data['channel']) || !$ctx->app->channels->getOwned($ctx->ownerId(), (int) $data['channel'])) {
            $channels = $ctx->app->channels->listFor($ctx->ownerId());
            if (!$channels) {
                $ctx->app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('ch_need_first'));
                return;
            }
            if (count($channels) > 1) {
                $ctx->app->states->set($ctx->userId, 'post_pick', $data);
                $ctx->reply($ctx->t('post_pick_channel'), Keyboards::pickChannel($channels, $ctx->lang));
                return;
            }
            $data['channel'] = (int) $channels[0]['id'];
        }
        self::preview($ctx, $data);
    }

    // ------------------------------------------------------------------ albom

    /** Albom qismi: yoziladi; ~2 soniya yangi qism kelmasa — shu so'rov albomni yig'adi. */
    private static function albumItem(Ctx $ctx, string $group): void
    {
        $app = $ctx->app;
        $msg = $ctx->message ?? [];
        $d = PostRender::draftFromMessage($msg);
        if ($d === null || !in_array($d['type'], ['photo', 'video', 'document', 'audio'], true) || $app->albums->isDone($ctx->userId, $group)) {
            return; // GIF/stiker albomda bo'lmaydi; kech kelgan qism e'tiborsiz
        }
        $app->albums->add($ctx->userId, $group, (int) ($msg['message_id'] ?? 0), $d['type'], (string) $d['file_id'], (string) $d['text'], $app->nowMs());
        $app->releaseClient(); // Telegram keyingi qismni yubora olsin
        $app->sleepMs(2000);
        if ($app->albums->hasNewer($ctx->userId, $group, (int) ($msg['message_id'] ?? 0))) {
            return; // oxirgi qism emas — yig'ishni oxirgisi qiladi
        }
        self::finishAlbum($app, $ctx->userId, $group, $ctx);
    }

    /** Albomni bitta postga yig'adi (faqat bir marta). Cron ham chaqiradi (jarayon uzilgan bo'lsa). */
    public static function finishAlbum(App $app, int $userId, string $group, ?Ctx $ctx = null): bool
    {
        if (!$app->albums->claim($userId, $group)) {
            return false;
        }
        $items = $app->albums->items($userId, $group);
        $app->albums->drop($userId, $group);
        if ($ctx === null) {
            $u = $app->users->get($userId);
            if (!$u) {
                return true;
            }
            $ctx = new Ctx($app, $userId, $userId, I18n::norm($u['lang'] ?? 'uz'), (string) ($u['full_name'] ?? ''), null, null);
        }
        $state = $ctx->state();
        if ($state === null || !in_array($state['state'], ['post_content', 'post_edit'], true)) {
            return true; // foydalanuvchi boshqa ishga o'tib ketgan
        }
        $media = [];
        $caption = '';
        foreach ($items as $it) {
            $media[] = [(string) $it['item_type'], (string) $it['file_id']];
            if ($caption === '' && trim((string) $it['caption']) !== '') {
                $caption = (string) $it['caption'];
            }
        }
        if (count($media) === 1) {
            $one = ['type' => $media[0][0], 'file_id' => $media[0][1], 'text' => $caption];
            self::applyDraft($ctx, $state, $one);
            return true;
        }
        if (count($media) > PostRender::ALBUM_MAX) {
            $media = array_slice($media, 0, PostRender::ALBUM_MAX);
            $ctx->reply($ctx->t('album_trimmed', ['max' => PostRender::ALBUM_MAX]));
        }
        if (!PostRender::albumValid($media)) {
            $ctx->reply($ctx->t('album_mixed'));
            return true;
        }
        self::applyDraft($ctx, $state, ['type' => 'album', 'file_id' => null, 'text' => $caption, 'media' => $media, 'group' => $group]);
        return true;
    }

    /** Albom yig'ilgandan keyin kelgan qism (server band bo'lib kechikkan): qoralamaga qo'shiladi, preview yangilanadi. */
    public static function albumLate(Ctx $ctx, array $state): void
    {
        $d = PostRender::draftFromMessage($ctx->message ?? []);
        $data = $state['data'];
        $media = $data['draft']['media'] ?? [];
        if ($d === null || !in_array($d['type'], ['photo', 'video', 'document', 'audio'], true) || count($media) >= PostRender::ALBUM_MAX) {
            return;
        }
        foreach ($media as $m) {
            if ($m[1] === $d['file_id']) {
                return;
            }
        }
        $next = array_merge($media, [[$d['type'], (string) $d['file_id']]]);
        if (!PostRender::albumValid($next)) {
            $ctx->reply($ctx->t('album_mixed'));
            return;
        }
        $data['draft']['media'] = $next;
        if (trim((string) $data['draft']['text']) === '' && trim((string) $d['text']) !== '') {
            $data['draft']['text'] = $d['text'];
        }
        if ($state['state'] === 'post_pick') {
            $ctx->app->states->set($ctx->userId, 'post_pick', $data); // kanal tanlangach to'liq albom ko'rinadi
            return;
        }
        self::preview($ctx, $data);
    }

    public static function pickChannel(Ctx $ctx, int $id): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        if (!$ctx->app->channels->getOwned($ctx->ownerId(), $id)) {
            $ctx->reply($ctx->t('post_pick_channel'), Keyboards::pickChannel($ctx->app->channels->listFor($ctx->ownerId()), $ctx->lang));
            return;
        }
        $data = $st['data'];
        $data['channel'] = $id;
        self::preview($ctx, $data);
    }

    /** Postni foydalanuvchiga xuddi kanaldagidek ko'rsatadi (nishon bilan) va boshqaruv tugmalari. */
    public static function preview(Ctx $ctx, array $data): void
    {
        $ctx->app->states->set($ctx->userId, 'post_preview', $data);
        $d = $data['draft'];
        $post = ['post_type' => $d['type'], 'text' => $d['text'], 'file_id' => $d['file_id'], 'media' => $d['media'] ?? null,
            'button_text' => $d['button_text'] ?? null, 'button_url' => $d['button_url'] ?? null, 'reactions' => $d['reactions'] ?? null,
            'options' => $d['options'] ?? null, 'hidden_text' => $d['hidden'] ?? null,
            'comments_label' => in_array('comments', PostRender::options($d['options'] ?? null), true) && $d['type'] !== 'album' ? $ctx->t('cm_btn') : null];
        $rows = Keyboards::previewRows($ctx->lang, (!empty($data['ai']['topic']) || !empty($data['ai']['photo']) || !empty($data['ai']['voice'])) && $ctx->app->ai->enabled(),
            $d['type'] !== 'album' ? $ctx->app->miniAppUrl('tab=post') : null);
        $free = $ctx->app->isFree($ctx->ownerId());
        $bot = $ctx->app->config->str('bot_username');
        $hint = $ctx->t('post_preview_hint') . self::extrasText($ctx, $data);
        if ($d['type'] === 'album') {
            $res = PostRender::send($ctx->app->tg, $ctx->chatId, $post, $bot, $free);
            if (empty($res['ok'])) {
                $ctx->reply($ctx->t('send_fail', ['reason' => $ctx->t(PostRender::reasonKey($res))]), Keyboards::inline($rows));
                return;
            }
            $ctx->reply($hint, Keyboards::inline($rows)); // albomga tugma ulanmaydi — boshqaruv alohida xabarda
            return;
        }
        $res = PostRender::send($ctx->app->tg, $ctx->chatId, $post, $bot, $free, $rows);
        if (empty($res['ok'])) {
            $ctx->reply($ctx->t('send_fail', ['reason' => $ctx->t(PostRender::reasonKey($res))]), Keyboards::inline($rows));
            return;
        }
        $ctx->reply($hint);
    }

    /** Preview ostidagi qo'shimcha sozlamalar ro'yxati (takror, avto-o'chirish, reaksiya). */
    private static function extrasText(Ctx $ctx, array $data): string
    {
        $lines = [];
        $rep = $data['repeat']['type'] ?? null;
        if ($rep !== null) {
            $lines[] = '🔄 ' . $ctx->t('rep_' . $rep, ['n' => (int) ($data['repeat']['n'] ?? 0)]) . ($rep === 'twice' && isset($data['repeat']['second'])
                ? ' (+' . Recurrence::clock((int) $data['repeat']['second']) . ')' : '');
        }
        $ad = (int) ($data['draft']['delete_after'] ?? 0);
        if ($ad > 0) {
            $lines[] = '⏳ ' . $ctx->t('ad_after', ['h' => intdiv($ad, 60)]);
        }
        if (!empty($data['draft']['reactions'])) {
            $lines[] = '👍 ' . Html::e(str_replace(',', ' ', (string) $data['draft']['reactions']));
        }
        $opts = PostRender::options($data['draft']['options'] ?? null);
        if ($opts) {
            $lines[] = implode(' · ', array_map(static function ($o) use ($ctx) {
                return $ctx->t('btn_o_' . $o);
            }, $opts));
        }
        if (!empty($data['extra'])) {
            $names = [];
            foreach (self::targets($ctx, $data) as $i => $c) {
                if ($i > 0) {
                    $names[] = Html::e((string) $c['title']);
                }
            }
            if ($names) {
                $lines[] = '📢 + ' . implode(', ', $names);
            }
        }
        $h = PostRender::hidden($data['draft']['hidden'] ?? null);
        if ($h !== null) {
            $lines[] = $ctx->t('hidden_line', ['text' => Html::e(mb_substr($h['t'], 0, 60))]);
        }
        return $lines ? "\n\n" . implode("\n", $lines) : '';
    }

    /** Preview tugmalari. */
    public static function action(Ctx $ctx, string $act): void
    {
        if ($act === 'cancel') {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('cancelled'));
            return;
        }
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        $album = ($data['draft']['type'] ?? '') === 'album';
        switch ($act) {
            case 'now':
                self::sendNow($ctx, $data, $st['state']);
                return;
            case 'time':
                $ctx->app->states->set($ctx->userId, 'post_time', $data);
                $ctx->reply($ctx->t('time_ask', ['tz' => Html::e($ctx->tzName())]), Keyboards::times($ctx->lang));
                return;
            case 'more':
                $ctx->app->states->set($ctx->userId, 'post_preview', $data);
                $ctx->reply($ctx->t('more_title') . self::extrasText($ctx, $data) . ($album ? "\n\n" . $ctx->t('album_no_buttons') : ''),
                    Keyboards::more($ctx->lang, $data['draft'], $album, $ctx->app->ai->enabled(), self::extraInfo($ctx, $data)));
                return;
            case 'btn':
                if ($album) {
                    $ctx->reply($ctx->t('album_no_buttons'));
                    return;
                }
                $ctx->app->states->set($ctx->userId, 'post_btn', $data);
                $ctx->reply($ctx->t('post_btn_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
                return;
            case 'btndel':
                $data['draft']['button_text'] = null;
                $data['draft']['button_url'] = null;
                self::preview($ctx, $data);
                return;
            case 'rep':
                $ctx->app->states->set($ctx->userId, 'post_preview', $data);
                $ctx->reply($ctx->t('rep_ask'), Keyboards::repeat($ctx->lang));
                return;
            case 'rx':
                if ($album) {
                    $ctx->reply($ctx->t('album_no_buttons'));
                    return;
                }
                $ctx->app->states->set($ctx->userId, 'post_preview', $data);
                $ctx->reply($ctx->t('rx_ask'), Keyboards::reactions($ctx->lang));
                return;
            case 'ad':
                $ctx->app->states->set($ctx->userId, 'post_preview', $data);
                $ctx->reply($ctx->t('ad_ask'), Keyboards::autoDelete($ctx->lang));
                return;
            case 'edit':
                $ctx->app->states->set($ctx->userId, 'post_edit', $data);
                $ctx->reply($ctx->t('post_edit_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
                return;
            case 'back':
                self::preview($ctx, $data);
                return;
            case 'hidden':
                if ($album) {
                    $ctx->reply($ctx->t('album_no_buttons'));
                    return;
                }
                $ctx->app->states->set($ctx->userId, 'post_hidden', $data);
                $ctx->reply($ctx->t('hidden_ask', ['max' => self::HIDDEN_MAX]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
                return;
            case 'mc':
                self::extraChannels($ctx);
                return;
            case 'tsave':
                TemplateHandler::saveAsk($ctx);
                return;
            case 'hddel':
                $data['draft']['hidden'] = null;
                self::preview($ctx, $data);
                return;
        }
        if (strpos($act, 'o_') === 0) {
            // sozlama yoqish/o'chirish: ovozsiz, havola ko'rinishisiz, pin, nusxa himoyasi
            $opt = substr($act, 2);
            $cur = PostRender::options($data['draft']['options'] ?? null);
            $cur = in_array($opt, $cur, true) ? array_values(array_diff($cur, [$opt])) : array_merge($cur, [$opt]);
            $data['draft']['options'] = PostRender::optionsString($cur);
            $ctx->app->states->set($ctx->userId, $st['state'], $data);
            $ctx->edit($ctx->t('more_title') . self::extrasText($ctx, $data) . ($album ? "\n\n" . $ctx->t('album_no_buttons') : ''),
                Keyboards::more($ctx->lang, $data['draft'], $album, $ctx->app->ai->enabled(), self::extraInfo($ctx, $data)));
        }
    }

    public const HIDDEN_MAX = 180;

    /** 🔒 Yashirin matn kiritildi (holat post_hidden). Telegram ogohlantirish oynasi 200 belgigacha. */
    public static function hiddenInput(Ctx $ctx, array $state): void
    {
        $text = trim((string) ($ctx->message['text'] ?? ''));
        $len = mb_strlen($text);
        if ($len < 1 || $len > self::HIDDEN_MAX) {
            $ctx->reply($ctx->t('hidden_bad', ['max' => self::HIDDEN_MAX]));
            return;
        }
        $data = $state['data'];
        $data['draft']['hidden'] = PostRender::hiddenJson($ctx->t('hidden_btn_label'), $text);
        self::preview($ctx, $data);
    }

    /** Takrorlash tanlandi: none|daily|weekly|monthly|twice (twice — kechki vaqt so'raladi). */
    public static function setRepeat(Ctx $ctx, string $type): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        if ($type === 'none') {
            unset($data['repeat']);
            self::preview($ctx, $data);
            return;
        }
        if ($type === 'twice') {
            $ctx->app->states->set($ctx->userId, 'post_time2', $data);
            $ctx->reply($ctx->t('rep_twice_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
            return;
        }
        if (preg_match('/^int(\d+)$/', $type, $im) && in_array((int) $im[1], Recurrence::INTERVALS, true)) {
            $data['repeat'] = ['type' => 'interval', 'n' => (int) $im[1]];
        } else {
            $data['repeat'] = ['type' => $type];
        }
        self::preview($ctx, $data);
    }

    /** «Kuniga 2 marta»: ikkinchi (kechki) vaqt yozildi. */
    public static function secondTimeInput(Ctx $ctx, array $state): void
    {
        $min = Recurrence::parseClock((string) ($ctx->message['text'] ?? ''));
        if ($min === null) {
            $ctx->reply($ctx->t('rep_twice_bad'));
            return;
        }
        $data = $state['data'];
        $data['repeat'] = ['type' => 'twice', 'second' => $min];
        self::preview($ctx, $data);
    }

    /** Reaksiya to'plami: 0..3 (tayyor), none, c (o'zi yozadi). */
    public static function setReactions(Ctx $ctx, string $choice): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        if ($choice === 'c') {
            $ctx->app->states->set($ctx->userId, 'post_rx', $data);
            $ctx->reply($ctx->t('rx_custom_ask'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
            return;
        }
        $data['draft']['reactions'] = $choice === 'none' ? null : (PostRender::REACTION_SETS[(int) $choice] ?? null);
        self::preview($ctx, $data);
    }

    public static function reactionsInput(Ctx $ctx, array $state): void
    {
        $r = PostRender::parseReactions((string) ($ctx->message['text'] ?? ''));
        if ($r === null) {
            $ctx->reply($ctx->t('rx_bad'));
            return;
        }
        $data = $state['data'];
        $data['draft']['reactions'] = $r;
        self::preview($ctx, $data);
    }

    /** Avto-o'chirish: daqiqalar (0 = o'chirmaslik). */
    public static function setAutoDelete(Ctx $ctx, int $minutes): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        $data['draft']['delete_after'] = in_array($minutes, Keyboards::AUTO_DELETE, true) ? $minutes : null;
        self::preview($ctx, $data);
    }

    public static function buttonInput(Ctx $ctx, array $state): void
    {
        $parsed = Links::parseButton((string) ($ctx->message['text'] ?? ''));
        if ($parsed === null) {
            $ctx->reply($ctx->t('post_btn_bad'));
            return;
        }
        $data = $state['data'];
        $data['draft']['button_text'] = $parsed[0];
        $data['draft']['button_url'] = $parsed[1];
        self::preview($ctx, $data);
    }

    public static function timeInput(Ctx $ctx, array $state): void
    {
        $r = TimeParser::parse((string) ($ctx->message['text'] ?? ''), $ctx->tz(), $ctx->app->now());
        if (!$r['ok']) {
            $key = ['past' => 'time_past', 'too_far' => 'time_too_far'][$r['error']] ?? 'time_bad';
            $ctx->reply($ctx->t($key));
            return;
        }
        self::schedule($ctx, $state['data'], $r['utc'], $state['state']);
    }

    public static function quickTime(Ctx $ctx, string $code): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $utc = TimeParser::quick($code, $ctx->tz(), $ctx->app->now());
        if ($utc !== null) {
            self::schedule($ctx, $st['data'], $utc, $st['state']);
        }
    }

    private static function schedule(Ctx $ctx, array $data, DateTimeImmutable $utc, string $stateName): void
    {
        $channels = self::targets($ctx, $data);
        if (!$channels) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (!$ctx->can('create')) {
            $ctx->replyMenu($ctx->t('team_no_perm'));
            return;
        }
        if (!self::queueHasRoom($ctx, count($channels))) {
            return;
        }
        $rec = self::recurrenceFor($ctx, $data, $utc);
        if ($rec === false) {
            return;
        }
        if (!$ctx->app->states->take($ctx->userId, $stateName)) {
            return; // ikkinchi parallel bosish — post allaqachon yaratildi
        }
        $utcSql = $utc->format('Y-m-d H:i:s');
        foreach ($channels as $channel) {
            $ctx->app->posts->create($ctx->ownerId(), (int) $channel['channel_id'], $data['draft'], $utcSql, true, $rec, $ctx->userId);
        }
        self::afterSaved($ctx);
        $ctx->replyMenu($ctx->t('post_scheduled', [
            'channel' => implode(', ', array_map(static function ($c) {
                return Html::e((string) $c['title']);
            }, $channels)),
            'when' => TimeParser::show($utcSql, $ctx->tz()),
            'tz' => Html::e($ctx->tzName()),
        ]) . ($rec !== null ? "\n🔄 " . self::repeatLabel($ctx, $rec) : ''));
    }

    /** Post chiqadigan kanallar: asosiy + «📢 Yana kanallar» (faqat egasiniki, takrorsiz). */
    private static function targets(Ctx $ctx, array $data): array
    {
        $out = [];
        foreach (array_merge([(int) ($data['channel'] ?? 0)], array_map('intval', (array) ($data['extra'] ?? []))) as $id) {
            if (isset($out[$id])) {
                continue;
            }
            $c = $ctx->app->channels->getOwned($ctx->ownerId(), $id);
            if ($c !== null) {
                $out[$id] = $c;
            } elseif ($id === (int) ($data['channel'] ?? 0)) {
                return []; // asosiy kanal yo'q — qoralama eskirgan
            }
        }
        return array_values($out);
    }

    /** «⚙️ Qo'shimcha» uchun: [boshqa kanallar soni, tanlangan qo'shimchalar soni]. */
    private static function extraInfo(Ctx $ctx, array $data): array
    {
        $all = $ctx->app->channels->countFor($ctx->ownerId());
        return [max(0, $all - 1), count(self::targets($ctx, $data)) - 1];
    }

    /** «📢 Yana kanallar»: boshqa kanallarni belgilash. */
    public static function extraChannels(Ctx $ctx, ?int $toggle = null): void
    {
        $st = self::draftState($ctx);
        if ($st === null) {
            return;
        }
        $data = $st['data'];
        $main = (int) ($data['channel'] ?? 0);
        $extra = array_values(array_unique(array_map('intval', (array) ($data['extra'] ?? []))));
        if ($toggle !== null && $toggle !== $main && $ctx->app->channels->getOwned($ctx->ownerId(), $toggle)) {
            $extra = in_array($toggle, $extra, true) ? array_values(array_diff($extra, [$toggle])) : array_merge($extra, [$toggle]);
            $data['extra'] = $extra;
            $ctx->app->states->set($ctx->userId, $st['state'], $data);
        }
        $rows = [];
        foreach ($ctx->app->channels->listFor($ctx->ownerId()) as $c) {
            $id = (int) $c['id'];
            if ($id === $main) {
                continue;
            }
            $rows[] = [Keyboards::btn((in_array($id, $extra, true) ? '✅ ' : '▫️ ') . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'pm:' . $id)];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_done'), 'p:more')];
        $mainCh = $ctx->app->channels->getOwned($ctx->ownerId(), $main);
        $text = $ctx->t('mc_ask', ['main' => Html::e((string) ($mainCh['title'] ?? ''))]);
        $toggle === null ? $ctx->reply($text, Keyboards::inline($rows)) : $ctx->edit($text, Keyboards::inline($rows));
    }

    /** «Hozir yuborish»: navbatga qo'yiladi va darhol yuboriladi; natija rostdan aytiladi (har kanal uchun). */
    private static function sendNow(Ctx $ctx, array $data, string $stateName): void
    {
        $channels = self::targets($ctx, $data);
        if (!$channels) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (!$ctx->can('send_now')) {
            $ctx->reply($ctx->t('team_no_perm_now'));
            return;
        }
        if (!self::queueHasRoom($ctx, count($channels))) {
            return;
        }
        $rec = self::recurrenceFor($ctx, $data, $ctx->app->now());
        if ($rec === false) {
            return;
        }
        if (!$ctx->app->states->take($ctx->userId, $stateName)) {
            return; // ikkinchi parallel bosish — post allaqachon yuborilmoqda
        }
        $results = [];
        foreach ($channels as $channel) {
            $id = $ctx->app->posts->create($ctx->ownerId(), (int) $channel['channel_id'], $data['draft'], $ctx->app->nowSql(), false, $rec, $ctx->userId);
            $r = ['status' => 'retry', 'reason' => ''];
            if ($ctx->app->posts->claim($id)) {
                $post = $ctx->app->posts->get($id);
                $r = (new Scheduler($ctx->app))->deliver($post ?? []);
            }
            $results[] = [$channel, $r];
        }
        self::afterSaved($ctx);
        if (count($results) === 1) {
            [$channel, $r] = $results[0];
            $name = Html::e((string) $channel['title']);
            if ($r['status'] === 'sent') {
                $next = $r['next'] ?? null;
                $ctx->replyMenu($ctx->t('send_ok', ['channel' => $name]) . ($next !== null
                    ? "\n🔄 " . $ctx->t('rep_next', ['when' => TimeParser::show($next->format('Y-m-d H:i:s'), $ctx->tz())]) : ''));
            } elseif ($r['status'] === 'retry') {
                $ctx->replyMenu($ctx->t('send_retry'));
            } else {
                $ctx->replyMenu($ctx->t('send_fail', ['reason' => $ctx->t($r['reason'])]));
            }
            return;
        }
        $lines = [];
        foreach ($results as [$channel, $r]) {
            $name = Html::e((string) $channel['title']);
            $lines[] = $r['status'] === 'sent' ? '✅ ' . $name : ($r['status'] === 'retry' ? '⏳ ' . $name . ' — ' . $ctx->t('mc_queued')
                : '❌ ' . $name . ' — ' . $ctx->t((string) $r['reason']));
        }
        $ctx->replyMenu($ctx->t('mc_result') . "\n\n" . implode("\n", $lines));
    }

    /**
     * Takrorlash qoidasi (birinchi chiqish vaqtidan): null — takrorsiz, false — xato (foydalanuvchiga aytildi).
     * @return array{type:string,time:int,day:?int}|null|false
     */
    private static function recurrenceFor(Ctx $ctx, array $data, DateTimeImmutable $firstUtc)
    {
        $type = $data['repeat']['type'] ?? null;
        if ($type === null) {
            return null;
        }
        $rec = Recurrence::fromFirst((string) $type, $firstUtc, $ctx->tz(), isset($data['repeat']['second']) ? (int) $data['repeat']['second'] : null,
            isset($data['repeat']['n']) ? (int) $data['repeat']['n'] : null);
        if ($rec === null) {
            $ctx->reply($ctx->t('rep_twice_same'));
            return false;
        }
        return $rec;
    }

    /** «Har kuni 09:00», «Har hafta (Du) 09:00», «Har oy 15-kuni 09:00», «Kuniga 2 marta: 09:00 va 18:30». */
    public static function repeatLabel(Ctx $ctx, array $rec): string
    {
        $t = Recurrence::clock((int) $rec['time']);
        switch ($rec['type']) {
            case 'weekly':
                return $ctx->t('rep_weekly_at', ['day' => $ctx->t('wd_' . (int) $rec['day']), 'time' => $t]);
            case 'monthly':
                return $ctx->t('rep_monthly_at', ['day' => (int) $rec['day'], 'time' => $t]);
            case 'twice':
                return $ctx->t('rep_twice_at', ['time' => $t, 'time2' => Recurrence::clock((int) $rec['day'])]);
            case 'workdays':
                return $ctx->t('rep_workdays_at', ['time' => $t]);
            case 'interval':
                return $ctx->t('rep_interval_at', ['n' => (int) $rec['day'], 'time' => $t]);
        }
        return $ctx->t('rep_daily_at', ['time' => $t]);
    }

    /** Post saqlandi: referal mukofoti (birinchi post) va manba havolasi belgisi. */
    private static function afterSaved(Ctx $ctx): void
    {
        $r = $ctx->app->afterPostSaved($ctx->ownerId());
        if ($r !== null) {
            PlansHandler::notifyReward($ctx->app, $r, $ctx->firstName !== '' ? $ctx->firstName : (string) $ctx->userId);
        }
    }

    private static function queueHasRoom(Ctx $ctx, int $n = 1): bool
    {
        $limit = $ctx->app->queueLimit($ctx->ownerId());
        if ($limit > 0 && $ctx->app->posts->pendingCount($ctx->ownerId()) + $n > $limit) {
            $ctx->reply($ctx->t('queue_limit', ['max' => $limit]));
            return false;
        }
        return true;
    }

    /** Qoralamali holat (bo'lmasa foydalanuvchiga aytiladi va null). */
    private static function draftState(Ctx $ctx): ?array
    {
        $st = $ctx->state();
        if ($st === null || empty($st['data']['draft']) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return null;
        }
        return $st;
    }
}
