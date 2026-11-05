<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Repo\ContentPlans;

/**
 * 📅 Kontent-reja: kanal mavzusi bo'yicha AI 7 ta post g'oyasini beradi (1 ta AI so'rovi).
 * G'oya raqami bosilsa — oddiy «✨ AI post» oqimi (uslub → post → preview) shu g'oya bilan boshlanadi.
 */
final class ContentPlanHandler
{
    public static function show(Ctx $ctx): void
    {
        $plan = $ctx->app->plans->latest($ctx->ownerId());
        if ($plan === null || !$plan['items']) {
            self::ask($ctx);
            return;
        }
        self::render($ctx, $plan, false);
    }

    public static function ask(Ctx $ctx): void
    {
        if (!$ctx->can('ai')) {
            $ctx->reply($ctx->t('team_no_perm_ai'), Keyboards::nav($ctx->lang));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'cp_topic');
        $ctx->reply($ctx->t('cp_ask_topic') . "\n\n" . AiHandler::quotaLine($ctx), Keyboards::nav($ctx->lang));
    }

    public static function topicInput(Ctx $ctx): void
    {
        $topic = trim((string) ($ctx->message['text'] ?? ''));
        $len = mb_strlen($topic);
        if ($len < AiHandler::TOPIC_MIN || $len > 500) {
            $ctx->reply($ctx->t('ai_topic_bad', ['max' => 500]), Keyboards::nav($ctx->lang));
            return;
        }
        $prompt = "Telegram kanal uchun " . ContentPlans::ITEMS . " ta turli post g'oyasini yoz.\n"
            . "Har g'oya alohida qatorda, raqamsiz va belgisiz, 4–15 so'z; faqat g'oyalar ro'yxati, kirish va izohsiz.\n"
            . "G'oyalar xilma-xil bo'lsin: foydali maslahat, savol-javob, yangilik, hikoya, so'rovnoma, taqqoslash, sotuv.\n\n"
            . "Kanal mavzusi:\n" . $topic;
        $res = AiHandler::run($ctx, \PostAssist\Services\Ai::system($ctx->lang, 1500), $prompt, 1500);
        if ($res === null) {
            return;
        }
        $ideas = ContentPlans::parseIdeas(Html::plain($res));
        if (count($ideas) < 3) {
            $ctx->app->states->clear($ctx->userId);
            $ctx->reply($ctx->t('cp_failed'), Keyboards::inline([[Keyboards::btn($ctx->t('btn_cp_new'), 'cp:new')], Keyboards::navRow($ctx->lang)]));
            return;
        }
        $ctx->app->states->clear($ctx->userId);
        $id = $ctx->app->plans->create($ctx->ownerId(), $topic, $ideas, $ctx->app->now());
        $plan = $ctx->app->plans->get($ctx->ownerId(), $id);
        if ($plan !== null) {
            self::render($ctx, $plan, false);
        }
    }

    public static function view(Ctx $ctx, int $id): void
    {
        $plan = $ctx->app->plans->get($ctx->ownerId(), $id);
        if ($plan === null) {
            self::show($ctx);
            return;
        }
        self::render($ctx, $plan, true);
    }

    /** G'oya tanlandi: belgilanadi va AI post oqimi (uslub tanlash) boshlanadi. */
    public static function write(Ctx $ctx, int $id, int $n): void
    {
        $plan = $ctx->app->plans->get($ctx->ownerId(), $id);
        if ($plan === null || !isset($plan['items'][$n])) {
            $ctx->reply($ctx->t('cp_not_found'), Keyboards::nav($ctx->lang));
            return;
        }
        if (!$ctx->can('ai')) {
            $ctx->reply($ctx->t('team_no_perm_ai'), Keyboards::nav($ctx->lang));
            return;
        }
        $ctx->app->plans->markDone($ctx->ownerId(), $id, $n);
        $idea = (string) $plan['items'][$n]['t'];
        AiHandler::askStyle($ctx, $plan['topic'] . "\n\nPost g'oyasi: " . $idea);
    }

    private static function render(Ctx $ctx, array $plan, bool $edit): void
    {
        $lines = [];
        $btns = [];
        foreach ($plan['items'] as $i => $it) {
            $mark = !empty($it['done']) ? '✅' : '▫️';
            $lines[] = $mark . ' <b>' . ($i + 1) . '.</b> ' . Html::e((string) $it['t']);
            $btns[] = Keyboards::btn('✍️ ' . ($i + 1), 'cp:w:' . $plan['id'] . ':' . $i);
        }
        $rows = array_chunk($btns, 4);
        $rows[] = [Keyboards::btn($ctx->t('btn_cp_new'), 'cp:new'), Keyboards::btn($ctx->t('btn_ap'), 'ap:show')];
        $rows[] = Keyboards::navRow($ctx->lang);
        $text = $ctx->t('cp_title', ['topic' => Html::e(mb_substr($plan['topic'], 0, 120)), 'items' => implode("\n", $lines)]);
        if ($edit) {
            $ctx->edit($text, Keyboards::inline($rows));
        } else {
            $ctx->reply($text, Keyboards::inline($rows));
        }
    }
}
