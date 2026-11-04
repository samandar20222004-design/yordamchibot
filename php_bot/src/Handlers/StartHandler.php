<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;

final class StartHandler
{
    public static function start(Ctx $ctx): void
    {
        $name = Html::e($ctx->firstName !== '' ? $ctx->firstName : 'do\'st');
        $ctx->replyMenu($ctx->t($ctx->isNew ? 'start_new' : 'start_hello', ['name' => $name]));
    }

    public static function stats(Ctx $ctx): void
    {
        $s = $ctx->app->posts->userStats($ctx->userId);
        $ctx->reply($ctx->t('stats_user', [
            'channels' => $ctx->app->channels->countFor($ctx->userId),
            'pending' => $s['pending'], 'sent' => $s['sent'], 'failed' => $s['failed'],
        ]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_scheduled'), 'q:list'), Keyboards::btn($ctx->t('btn_plans'), 'pl:show')],
            [Keyboards::btn($ctx->t('btn_home'), 'm:home')]]));
    }

    /** 🏠 Menyu: holat tozalanadi, bosh menyu va qisqa yo'l-yo'riq. */
    public static function home(Ctx $ctx): void
    {
        $ctx->app->states->clear($ctx->userId);
        $name = Html::e($ctx->firstName !== '' ? $ctx->firstName : 'do\'st');
        $ctx->replyMenu($ctx->t('start_hello', ['name' => $name]));
    }
}
