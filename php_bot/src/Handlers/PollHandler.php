<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Keyboards;

/**
 * 📊 So'rovnoma posti: savol (≤300) va 2–10 variant (har biri ≤100). Variant oldiga «*» qo'yilsa — viktorina
 * (to'g'ri javob). Kanal so'rovnomalari doim anonim. Keyin odatdagi preview: kanal, vaqt, takror, ovozsiz, pin.
 * Saqlash: post_type='poll', text = savol, media = {"options": [...], "quiz": index|null}.
 */
final class PollHandler
{
    public const Q_MAX = 300;
    public const OPT_MAX = 100;
    public const OPTS_MIN = 2;
    public const OPTS_MAX = 10;

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
        $ctx->app->states->set($ctx->userId, 'poll_q');
        $ctx->reply($ctx->t('poll_ask_q', ['max' => self::Q_MAX]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    public static function questionInput(Ctx $ctx): void
    {
        $q = trim((string) ($ctx->message['text'] ?? ''));
        $len = mb_strlen($q);
        if ($len < 1 || $len > self::Q_MAX) {
            $ctx->reply($ctx->t('poll_q_bad', ['max' => self::Q_MAX]));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'poll_opts', ['q' => $q]);
        $ctx->reply($ctx->t('poll_ask_opts', ['min' => self::OPTS_MIN, 'max' => self::OPTS_MAX, 'len' => self::OPT_MAX]),
            Keyboards::inline([[Keyboards::btn($ctx->t('btn_cancel'), 'p:cancel')]]));
    }

    /**
     * Variantlar matnidan: ['options'=>[], 'quiz'=>?int] yoki xato kaliti.
     * @return array{options:string[], quiz:?int}|string
     */
    public static function parseOptions(string $raw)
    {
        $opts = [];
        $quiz = null;
        foreach (preg_split('/\R/u', $raw) ?: [] as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $correct = false;
            if ($line[0] === '*') {
                $correct = true;
                $line = trim(substr($line, 1));
            }
            $line = trim((string) preg_replace('/^\s*(?:\d{1,2}[.)]|[-•])\s*/u', '', $line));
            if ($line === '') {
                continue;
            }
            if (mb_strlen($line) > self::OPT_MAX) {
                return 'poll_opt_long';
            }
            if (in_array(mb_strtolower($line), array_map('mb_strtolower', $opts), true)) {
                return 'poll_opt_dup';
            }
            if ($correct) {
                if ($quiz !== null) {
                    return 'poll_two_correct';
                }
                $quiz = count($opts);
            }
            $opts[] = $line;
        }
        if (count($opts) < self::OPTS_MIN || count($opts) > self::OPTS_MAX) {
            return 'poll_opts_count';
        }
        return ['options' => $opts, 'quiz' => $quiz];
    }

    public static function optionsInput(Ctx $ctx, array $state): void
    {
        $r = self::parseOptions((string) ($ctx->message['text'] ?? ''));
        if (is_string($r)) {
            $ctx->reply($ctx->t($r, ['min' => self::OPTS_MIN, 'max' => self::OPTS_MAX, 'len' => self::OPT_MAX]));
            return;
        }
        $draft = ['type' => 'poll', 'file_id' => null, 'text' => (string) $state['data']['q'], 'media' => $r];
        PostHandler::applyDraft($ctx, ['state' => 'post_content', 'data' => []], $draft);
    }
}
