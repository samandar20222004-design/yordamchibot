<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\Ai;
use PostAssist\Services\PostRender;

/**
 * ✨ AI: mavzudan post (uslub tanlab), tayyor postni tahrirlash (yaxshilash, qisqartirish, emoji, qayta yozish, tarjima)
 * va aqlli qabul — dialogdan tashqari yuborilgan matn/media uchun «Bu bilan nima qilamiz?» (AI o'zi ishga tushmaydi).
 * Har AI so'rovi oldidan joy band qilinadi (kunlik limit, keyin ball); AI javob bermasa qaytariladi.
 * Natija oddiy post qoralamasiga tushadi — keyin hamma narsa odatdagidek: kanal, preview, tugma, vaqt, takror.
 */
final class AiHandler
{
    public const TOPIC_MIN = 3;
    public const TOPIC_MAX = 2000;
    /** Rasm va ovoz uchun yuklab olinadigan fayl chegarasi (Gemini so'rovi hajmi ham shunga mos). */
    public const MEDIA_MAX_BYTES = 5242880;
    public const VOICE_MAX_SECONDS = 180;

    private static function disabled(Ctx $ctx): bool
    {
        if ($ctx->app->ai->enabled()) {
            return false;
        }
        $ctx->reply($ctx->t($ctx->app->isAdmin($ctx->userId) ? 'ai_disabled_admin' : 'ai_disabled'), Keyboards::nav($ctx->lang));
        return true;
    }

    /** Qolgan so'rovlar: «Bugun: 3/5 · Ball: 7» yoki «cheksiz». */
    public static function quotaLine(Ctx $ctx): string
    {
        $limit = $ctx->app->aiLimit($ctx->userId);
        if ($limit === 0) {
            return $ctx->t('ai_quota_unlimited');
        }
        $left = max(0, $limit - $ctx->app->aiUsage->usedOn($ctx->userId, $ctx->app->today()));
        return $ctx->t('ai_quota', ['left' => $left, 'limit' => $limit, 'credits' => $ctx->app->credits->balance($ctx->userId)]);
    }

    /** «✨ AI post»: mavzu so'raladi. */
    public static function start(Ctx $ctx): void
    {
        if (self::disabled($ctx)) {
            return;
        }
        if ($ctx->app->channels->countFor($ctx->userId) === 0) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        $ctx->app->states->set($ctx->userId, 'ai_topic');
        $ctx->reply($ctx->t('ai_ask_topic') . "\n\n" . self::quotaLine($ctx), Keyboards::nav($ctx->lang));
    }

    public static function topicInput(Ctx $ctx): void
    {
        $topic = trim((string) ($ctx->message['text'] ?? $ctx->message['caption'] ?? ''));
        $len = mb_strlen($topic);
        if ($len < self::TOPIC_MIN || $len > self::TOPIC_MAX) {
            $ctx->reply($ctx->t('ai_topic_bad', ['max' => self::TOPIC_MAX]), Keyboards::nav($ctx->lang));
            return;
        }
        $st = $ctx->state();
        self::askStyle($ctx, $topic, !empty($st['data']['photo']) ? (string) $st['data']['photo'] : null); // rasm bo'lsa — yangi izoh
    }

    /** Uslub so'rash. $photo — rasmdan post (mavzu — ixtiyoriy izoh). */
    public static function askStyle(Ctx $ctx, string $topic, ?string $photo = null): void
    {
        $data = ['topic' => $topic];
        if ($photo !== null) {
            $data['photo'] = $photo;
        }
        $ctx->app->states->set($ctx->userId, 'ai_style', $data);
        $ctx->reply($ctx->t('ai_ask_style'), Keyboards::aiStyles($ctx->lang));
    }

    /** Uslub tanlandi — post yoziladi (mavzudan yoki rasmdan). */
    public static function style(Ctx $ctx, string $style): void
    {
        $st = $ctx->state();
        $topic = (string) ($st['data']['topic'] ?? '');
        $photo = (string) ($st['data']['photo'] ?? '');
        if ($st === null || $st['state'] !== 'ai_style' || ($topic === '' && $photo === '')) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $ai = ['topic' => $topic, 'style' => $style] + ($photo !== '' ? ['photo' => $photo] : []);
        $res = self::generateFrom($ctx, $ai);
        if ($res === null) {
            return;
        }
        $draft = $photo !== '' ? ['type' => 'photo', 'file_id' => $photo, 'text' => $res] : ['type' => 'text', 'file_id' => null, 'text' => $res];
        PostHandler::applyDraft($ctx, ['state' => 'ai_style', 'data' => ['ai' => $ai]], $draft);
    }

    /**
     * Manba bo'yicha matn yozadi: rasm / ovoz / mavzu. Fayl avval yuklanadi (yuklanmasa limit sarflanmaydi).
     * @param array{topic?:string, style?:string, photo?:string, voice?:string} $ai
     */
    private static function generateFrom(Ctx $ctx, array $ai): ?string
    {
        $style = (string) ($ai['style'] ?? 'news');
        if (!empty($ai['photo']) || !empty($ai['voice'])) {
            if (!$ctx->app->ai->mediaEnabled()) {
                $ctx->reply($ctx->t('ai_media_off'), Keyboards::nav($ctx->lang));
                return null;
            }
            $isPhoto = !empty($ai['photo']);
            $file = $ctx->app->tg->fetchFile((string) ($isPhoto ? $ai['photo'] : $ai['voice']), self::MEDIA_MAX_BYTES);
            if ($file === null) {
                $ctx->reply($ctx->t('ai_media_failed'), Keyboards::nav($ctx->lang));
                return null;
            }
            $media = ['mime' => $isPhoto ? self::imageMime($file[0]) : 'audio/ogg', 'data' => $file[0]];
            $max = $isPhoto ? PostRender::CAPTION_LIMIT - 120 : PostRender::TEXT_LIMIT - 200;
            return self::run($ctx, Ai::system($ctx->lang, $max), $isPhoto ? Ai::imagePrompt((string) ($ai['topic'] ?? ''), $style) : Ai::voicePrompt($style), $max, $media);
        }
        $max = PostRender::TEXT_LIMIT - 200;
        return self::run($ctx, Ai::system($ctx->lang, $max), Ai::postPrompt((string) ($ai['topic'] ?? ''), $style), $max);
    }

    /** Baytlardan rasm turi (Telegram rasmlari JPEG; boshqa turlar ham tekshiriladi). */
    public static function imageMime(string $bytes): string
    {
        if (strncmp($bytes, "\x89PNG", 4) === 0) {
            return 'image/png';
        }
        if (strncmp($bytes, 'RIFF', 4) === 0 && substr($bytes, 8, 4) === 'WEBP') {
            return 'image/webp';
        }
        return 'image/jpeg';
    }

    /** Preview'dagi «🔄 Boshqa variant» — o'sha manba (mavzu / rasm / ovoz) va uslubda qayta yozish; kanal va sozlamalar saqlanadi. */
    public static function again(Ctx $ctx): void
    {
        $st = $ctx->state();
        $ai = $st['data']['ai'] ?? null;
        if ($st === null || !is_array($ai) || (empty($ai['topic']) && empty($ai['photo']) && empty($ai['voice'])) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $res = self::generateFrom($ctx, $ai);
        if ($res === null) {
            return;
        }
        $data = $st['data'];
        $data['draft']['text'] = $res;
        PostHandler::preview($ctx, $data);
    }

    /** «⚙️ Qo'shimcha» → «✨ AI tahrir»: amal tanlash. */
    public static function editMenu(Ctx $ctx): void
    {
        if (self::disabled($ctx)) {
            return;
        }
        $st = $ctx->state();
        if ($st === null || empty($st['data']['draft']) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        if (trim(Html::plain((string) ($st['data']['draft']['text'] ?? ''))) === '') {
            $ctx->reply($ctx->t('ai_need_text'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
            return;
        }
        $ctx->reply($ctx->t('ai_edit_ask') . "\n\n" . self::quotaLine($ctx), Keyboards::aiEdits($ctx->lang));
    }

    public static function edit(Ctx $ctx, string $action): void
    {
        $st = $ctx->state();
        if ($st === null || empty($st['data']['draft']) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $data = $st['data'];
        $text = (string) ($data['draft']['text'] ?? '');
        if (trim(Html::plain($text)) === '') {
            $ctx->reply($ctx->t('ai_need_text'));
            return;
        }
        $type = (string) $data['draft']['type'];
        $max = PostRender::limitFor($type === 'album' ? 'photo' : $type) - 40; // bepul nishon uchun joy
        $res = self::run($ctx, Ai::system(Ai::editLang($action, $ctx->lang), $max), Ai::editPrompt($text, $action), $max);
        if ($res === null) {
            return;
        }
        $data['draft']['text'] = $res;
        PostHandler::preview($ctx, $data);
    }

    /**
     * AI chaqiruvi: limit band qilinadi, «⏳ yozmoqda» ko'rsatiladi, xatoda limit qaytadi.
     * @return string|null tayyor HTML yoki null (foydalanuvchiga sabab aytildi)
     */
    private static function run(Ctx $ctx, string $system, string $prompt, int $maxChars, ?array $media = null): ?string
    {
        $app = $ctx->app;
        if (self::disabled($ctx)) {
            return null;
        }
        $day = $app->today();
        $src = $app->aiUsage->reserve($ctx->userId, $app->aiLimit($ctx->userId), $day, $app->nowSql());
        if ($src === null) {
            $ctx->reply($ctx->t('ai_limit'), Keyboards::inline([
                [Keyboards::btn($ctx->t('btn_plans'), 'pl:show'), Keyboards::btn($ctx->t('btn_invite'), 'ref:show')],
                [Keyboards::btn($ctx->t('btn_home'), 'm:home')],
            ]));
            return null;
        }
        $wait = $ctx->reply($ctx->t('ai_working'));
        $app->releaseClient(); // AI 5–30 soniya: Telegram kutib qolmasin
        @set_time_limit(120);
        $res = $app->ai->generate($system, $prompt, $maxChars, $media);
        if (!empty($wait['result']['message_id'])) {
            $app->tg->call('deleteMessage', ['chat_id' => $ctx->chatId, 'message_id' => (int) $wait['result']['message_id']]);
        }
        if (!$res['ok']) {
            $app->aiUsage->refund($ctx->userId, $src, $day, $app->nowSql());
            $app->log('AI xato: ' . ($res['error'] ?? ''));
            $ctx->reply($ctx->t('ai_failed'), Keyboards::nav($ctx->lang));
            return null;
        }
        return (string) $res['text'];
    }

    // ------------------------------------------------------------------ aqlli qabul

    /** Dialogdan tashqari kelgan matn/media: AI o'zi ishga tushmaydi — foydalanuvchi tanlaydi. */
    public static function intake(Ctx $ctx): bool
    {
        $msg = $ctx->message ?? [];
        $draft = PostRender::draftFromMessage($msg);
        if ($draft === null) {
            return false;
        }
        if ($draft['type'] === 'text') {
            $plain = trim(Html::plain((string) $draft['text']));
            if (mb_strlen($plain) < 8 || count(preg_split('/\s+/u', $plain) ?: []) < 2) {
                return false; // «ha», «???» — oddiy javob
            }
        }
        $ctx->app->states->set($ctx->userId, 'intake', ['draft' => $draft]);
        $row = [Keyboards::btn($ctx->t('btn_in_post'), 'in:post')];
        $hasText = trim(Html::plain((string) $draft['text'])) !== '';
        if (($draft['type'] === 'text' && $hasText && $ctx->app->ai->enabled()) || ($draft['type'] === 'photo' && $ctx->app->ai->mediaEnabled())) {
            $row[] = Keyboards::btn($ctx->t('btn_in_ai'), 'in:ai'); // rasm — Vision (faqat bosilganda)
        }
        $ctx->reply($ctx->t('in_ask'), Keyboards::inline([$row, [Keyboards::btn($ctx->t('btn_in_close'), 'in:close')]]));
        return true;
    }

    public static function intakeChoice(Ctx $ctx, string $choice): void
    {
        $st = $ctx->state();
        if ($choice === 'close' || $st === null || $st['state'] !== 'intake' || empty($st['data']['draft'])) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t($choice === 'close' ? 'cancelled' : 'draft_expired'));
            return;
        }
        $draft = $st['data']['draft'];
        if ($ctx->app->channels->countFor($ctx->userId) === 0) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        if ($choice === 'ai') {
            if (self::disabled($ctx)) {
                return;
            }
            if (($draft['type'] ?? '') === 'photo') {
                if (!$ctx->app->ai->mediaEnabled()) {
                    $ctx->reply($ctx->t('ai_media_off'), Keyboards::nav($ctx->lang));
                    return;
                }
                self::askStyle($ctx, mb_substr(trim(Html::plain((string) $draft['text'])), 0, self::TOPIC_MAX), (string) $draft['file_id']);
                return;
            }
            self::askStyle($ctx, mb_substr(trim(Html::plain((string) $draft['text'])), 0, self::TOPIC_MAX));
            return;
        }
        PostHandler::applyDraft($ctx, ['state' => 'intake', 'data' => []], $draft);
    }

    // ------------------------------------------------------------------ ovozdan post

    /** 🎤 Ovozli xabar: tinglanadi va tayyor post yoziladi (uslub: yangilik; «Boshqa variant» bilan o'zgartiriladi). */
    public static function voice(Ctx $ctx): void
    {
        $v = $ctx->message['voice'] ?? [];
        if (!$ctx->app->ai->enabled()) {
            $ctx->reply($ctx->t('ai_disabled'), Keyboards::nav($ctx->lang));
            return;
        }
        if (!$ctx->app->ai->mediaEnabled()) {
            $ctx->reply($ctx->t('ai_media_off'), Keyboards::nav($ctx->lang));
            return;
        }
        if ($ctx->app->channels->countFor($ctx->userId) === 0) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        if ((int) ($v['duration'] ?? 0) > self::VOICE_MAX_SECONDS || empty($v['file_id'])) {
            $ctx->reply($ctx->t('ai_voice_long', ['sec' => self::VOICE_MAX_SECONDS]), Keyboards::nav($ctx->lang));
            return;
        }
        $ai = ['voice' => (string) $v['file_id'], 'style' => 'news'];
        $res = self::generateFrom($ctx, $ai);
        if ($res === null) {
            return;
        }
        $st = $ctx->state();
        $data = ($st !== null && strpos($st['state'], 'post_') === 0) ? $st['data'] : [];
        $data['ai'] = $ai;
        PostHandler::applyDraft($ctx, ['state' => 'voice', 'data' => $data], ['type' => 'text', 'file_id' => null, 'text' => $res]);
    }
}
