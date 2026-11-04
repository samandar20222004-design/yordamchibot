<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\I18n;
use PostAssist\Keyboards;
use PostAssist\Services\Plans;

final class SettingsHandler
{
    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $tier = $ctx->app->isAdmin($ctx->userId) ? Plans::ENTERPRISE : $ctx->app->tier($ctx->userId);
        $text = $ctx->t('settings_title', ['lang' => I18n::NAMES[$ctx->lang], 'tz' => Html::e($ctx->tzName()), 'plan' => Plans::NAMES[$tier]]);
        $kb = Keyboards::settings($ctx->lang);
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    /** /timezone: tezkor tugmalar yoki IANA nomini yozish (masalan Europe/Paris). */
    public static function askTimezone(Ctx $ctx): void
    {
        $now = $ctx->app->now()->setTimezone($ctx->tz())->format('H:i');
        $ctx->app->states->set($ctx->userId, 'tz_wait');
        $ctx->reply($ctx->t('tz_ask', ['tz' => Html::e($ctx->tzName()), 'now' => $now]), Keyboards::timezones($ctx->lang));
    }

    /** Matn yoki tugmadan zona: IANA nomi (katta-kichik harf farqsiz) yoki shahar nomi (Toshkent, Moskva...). */
    public static function resolveTimezone(string $input): ?string
    {
        $in = trim($input);
        if ($in === '') {
            return null;
        }
        $low = mb_strtolower($in);
        foreach (\DateTimeZone::listIdentifiers() as $id) {
            if (strtolower($id) === $low) {
                return $id;
            }
        }
        foreach (Keyboards::TIMEZONES as $id => $label) {
            $city = mb_strtolower(trim((string) preg_replace('/^\S+\s/u', '', $label)));
            if ($city === $low) {
                return $id;
            }
        }
        $alias = ['tashkent' => 'Asia/Tashkent', 'ташкент' => 'Asia/Tashkent', 'moscow' => 'Europe/Moscow', 'москва' => 'Europe/Moscow',
            'samarqand' => 'Asia/Samarkand', 'samarkand' => 'Asia/Samarkand', 'самарканд' => 'Asia/Samarkand'];
        if (isset($alias[$low])) {
            return $alias[$low];
        }
        foreach (\DateTimeZone::listIdentifiers() as $id) {
            $city = strtolower(str_replace('_', ' ', substr($id, (int) strrpos($id, '/') + (strpos($id, '/') !== false ? 1 : 0))));
            if ($city === $low) {
                return $id;
            }
        }
        return null;
    }

    public static function setTimezone(Ctx $ctx, string $input): void
    {
        $id = self::resolveTimezone($input);
        if ($id === null) {
            $ctx->reply($ctx->t('tz_bad'), Keyboards::nav($ctx->lang, 'set:show'));
            return;
        }
        $ctx->app->states->clear($ctx->userId);
        $ctx->app->users->setTimezone($ctx->userId, $id);
        $ctx->app->forgetTz($ctx->userId);
        $now = $ctx->app->now()->setTimezone($ctx->tz())->format('H:i');
        $ctx->replyMenu($ctx->t('tz_set', ['tz' => Html::e($id), 'now' => $now]));
    }

    public static function setLang(Ctx $ctx, string $lang): void
    {
        $lang = I18n::norm($lang);
        $ctx->app->users->setLang($ctx->userId, $lang);
        $ctx->lang = $lang;
        $ctx->replyMenu($ctx->t('lang_set'));
    }
}
