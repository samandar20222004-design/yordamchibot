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

    /** Matn yoki tugmadan aniq zona: IANA nomi, shahar (Toshkent, Moskva, Nyu-York…) yoki tugmadagi shahar. */
    public static function resolveTimezone(string $input): ?string
    {
        $z = \PostAssist\Services\Countries::zoneFor($input);
        if ($z !== null) {
            return $z;
        }
        $low = \PostAssist\Services\Countries::norm($input);
        foreach (Keyboards::TIMEZONES as $id => $label) {
            if (\PostAssist\Services\Countries::norm((string) preg_replace('/^\S+\s/u', '', $label)) === $low) {
                return $id;
            }
        }
        return null;
    }

    /** Zona, shahar yoki DAVLAT nomi (uch tilda). Bir nechta mintaqali davlatda shahar tanlanadi. */
    public static function setTimezone(Ctx $ctx, string $input): void
    {
        $id = self::resolveTimezone($input);
        if ($id !== null) {
            self::applyTimezone($ctx, $id);
            return;
        }
        $found = \PostAssist\Services\Countries::search($input);
        if (count($found) === 1 && count(\PostAssist\Services\Countries::distinctZones($found[0], $ctx->app->now())) === 1) {
            self::applyTimezone($ctx, \PostAssist\Services\Countries::zones($found[0])[0]);
            return;
        }
        if (count($found) === 1) {
            self::countryZones($ctx, $found[0]);
            return;
        }
        if ($found) {
            $rows = [];
            foreach ($found as $code) {
                $rows[] = [Keyboards::btn(\PostAssist\Services\Countries::flag($code) . ' ' . mb_substr(\PostAssist\Services\Countries::name($code, $ctx->lang), 0, 40), 'tzc:' . $code)];
            }
            $rows[] = Keyboards::navRow($ctx->lang, 'set:tz');
            $ctx->reply($ctx->t('tz_pick_country'), Keyboards::inline($rows));
            return;
        }
        $ctx->reply($ctx->t('tz_bad'), Keyboards::nav($ctx->lang, 'set:show'));
    }

    /** Davlatning mintaqalari (shahar + UTC farqi). */
    public static function countryZones(Ctx $ctx, string $code): void
    {
        $zones = \PostAssist\Services\Countries::distinctZones($code, $ctx->app->now());
        if (!$zones) {
            self::askTimezone($ctx);
            return;
        }
        if (count($zones) === 1) {
            self::applyTimezone($ctx, $zones[0]);
            return;
        }
        $rows = [];
        $row = [];
        foreach (array_slice($zones, 0, 40) as $z) {
            $row[] = Keyboards::btn(\PostAssist\Services\Countries::zoneLabel($z, $ctx->app->now()), 'tz:' . $z);
            if (count($row) === 2) {
                $rows[] = $row;
                $row = [];
            }
        }
        if ($row) {
            $rows[] = $row;
        }
        $rows[] = Keyboards::navRow($ctx->lang, 'set:tz');
        $ctx->reply($ctx->t('tz_pick_zone', ['country' => \PostAssist\Services\Countries::flag($code) . ' ' . Html::e(\PostAssist\Services\Countries::name($code, $ctx->lang))]),
            Keyboards::inline($rows));
    }

    private static function applyTimezone(Ctx $ctx, string $id): void
    {
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
