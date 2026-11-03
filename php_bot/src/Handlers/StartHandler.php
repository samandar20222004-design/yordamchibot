<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;

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
        $ctx->replyMenu($ctx->t('stats_user', [
            'channels' => $ctx->app->channels->countFor($ctx->userId),
            'pending' => $s['pending'], 'sent' => $s['sent'], 'failed' => $s['failed'],
        ]));
    }
}
