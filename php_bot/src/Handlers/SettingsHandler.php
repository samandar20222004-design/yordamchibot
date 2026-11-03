<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;

final class SettingsHandler
{
    public static function show(Ctx $ctx): void
    {
        $ctx->reply($ctx->t('settings_title', ['lang' => I18n::NAMES[$ctx->lang], 'tz' => Html::e($ctx->app->tzName())]),
            Keyboards::settings($ctx->lang));
    }

    public static function setLang(Ctx $ctx, string $lang): void
    {
        $lang = I18n::norm($lang);
        $ctx->app->users->setLang($ctx->userId, $lang);
        $ctx->lang = $lang;
        $ctx->replyMenu($ctx->t('lang_set'));
    }
}
