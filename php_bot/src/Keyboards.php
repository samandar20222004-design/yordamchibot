<?php
declare(strict_types=1);

namespace PostAssist;

use PostAssist\Services\PostRender;

/** Klaviaturalar. Callback ma'lumoti qisqa va qat'iy formatda (Router faqat shu shakllarni qabul qiladi). */
final class Keyboards
{
    public static function main(string $lang, bool $admin, bool $ai = false, ?string $miniApp = null): array
    {
        $t = static fn (string $k) => ['text' => I18n::t($k, $lang)];
        $rows = $ai ? [
            [$t('btn_create_content'), $t('btn_ai_post')],
            [$t('btn_my_channels'), $t('btn_scheduled')],
            [$t('btn_statistics'), $t('btn_settings')],
        ] : [
            [$t('btn_create_content'), $t('btn_my_channels')],
            [$t('btn_scheduled'), $t('btn_statistics')],
            [$t('btn_settings')],
        ];
        $last = [];
        if ($miniApp !== null) {
            $last[] = ['text' => I18n::t('btn_miniapp', $lang), 'web_app' => ['url' => $miniApp]];
        }
        if ($admin) {
            $last[] = $t('btn_admin');
        }
        if ($last) {
            $rows[] = $last;
        }
        return ['keyboard' => $rows, 'resize_keyboard' => true, 'is_persistent' => true];
    }

    /** Pastki navigatsiya qatori: [◀️ Orqaga] [🏠 Menyu] (orqaga bo'lmasa faqat menyu). */
    public static function navRow(string $lang, ?string $back = null): array
    {
        $row = [];
        if ($back !== null) {
            $row[] = self::btn(I18n::t('btn_back', $lang), $back);
        }
        $row[] = self::btn(I18n::t('btn_home', $lang), 'm:home');
        return $row;
    }

    public static function nav(string $lang, ?string $back = null): array
    {
        return self::inline([self::navRow($lang, $back)]);
    }

    public static function aiStyles(string $lang): array
    {
        $b = static fn (string $s) => self::btn(I18n::t('btn_ai_' . $s, $lang), 'ai:s:' . $s);
        return self::inline([[$b('news'), $b('sales')], [$b('fun'), $b('useful')], [$b('short')], self::navRow($lang)]);
    }

    public static function aiEdits(string $lang): array
    {
        $b = static fn (string $a) => self::btn(I18n::t('btn_aie_' . $a, $lang), 'ai:e:' . $a);
        return self::inline([[$b('improve'), $b('shorten')], [$b('emoji'), $b('rewrite')], [$b('tr_uz'), $b('tr_ru'), $b('tr_en')],
            [self::btn(I18n::t('btn_back', $lang), 'p:back')]]);
    }

    public static function inline(array $rows): array
    {
        return ['inline_keyboard' => array_values(array_filter($rows))];
    }

    public static function btn(string $text, string $data): array
    {
        return ['text' => $text, 'callback_data' => $data];
    }

    public static function languages(?string $lang = null): array
    {
        $row = [];
        foreach (I18n::NAMES as $code => $name) {
            $row[] = self::btn($name, 'lang:' . $code);
        }
        return self::inline($lang !== null ? [$row, self::navRow($lang, 'set:show')] : [$row]);
    }

    public static function settings(string $lang): array
    {
        return self::inline([
            [self::btn(I18n::t('btn_lang', $lang), 'set:lang'), self::btn(I18n::t('btn_plans', $lang), 'pl:show')],
            [self::btn(I18n::t('btn_invite', $lang), 'ref:show'), self::btn(I18n::t('btn_promo', $lang), 'promo:ask')],
            [self::btn(I18n::t('btn_timezone', $lang), 'set:tz'), self::btn(I18n::t('btn_team', $lang), 'set:team')],
            [self::btn(I18n::t('btn_help', $lang), 'set:help')],
            self::navRow($lang),
        ]);
    }

    public static function channels(array $channels, string $lang, bool $canAdd): array
    {
        $rows = [];
        foreach ($channels as $c) {
            $rows[] = [self::btn('🗑 ' . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'ch:del:' . (int) $c['id'])];
        }
        if ($canAdd) {
            $rows[] = [self::btn(I18n::t('btn_ch_add', $lang), 'ch:add')];
        }
        $rows[] = [self::btn(I18n::t('btn_mk_market', $lang), 'mk:home')];
        $rows[] = self::navRow($lang);
        return self::inline($rows);
    }

    public static function confirm(string $lang, string $yesData, string $backData): array
    {
        return self::inline([[self::btn(I18n::t('btn_yes_delete', $lang), $yesData), self::btn(I18n::t('btn_back', $lang), $backData)]]);
    }

    public static function pickChannel(array $channels, string $lang): array
    {
        $rows = [];
        foreach ($channels as $c) {
            $rows[] = [self::btn('📢 ' . mb_substr((string) ($c['title'] ?: $c['channel_id']), 0, 40), 'p:ch:' . (int) $c['id'])];
        }
        $rows[] = [self::btn(I18n::t('btn_cancel', $lang), 'p:cancel')];
        return self::inline($rows);
    }

    /** Avto-o'chirish variantlari (daqiqa). */
    public const AUTO_DELETE = [60, 360, 720, 1440, 2880];
    /** /timezone tezkor tugmalari: IANA nomi => yorliq. */
    public const TIMEZONES = [
        'Asia/Tashkent' => '🇺🇿 Toshkent', 'Asia/Almaty' => '🇰🇿 Almaty', 'Asia/Bishkek' => '🇰🇬 Bishkek',
        'Asia/Dushanbe' => '🇹🇯 Dushanbe', 'Europe/Moscow' => '🇷🇺 Moskva', 'Europe/Istanbul' => '🇹🇷 Istanbul',
        'Asia/Dubai' => '🇦🇪 Dubai', 'Asia/Seoul' => '🇰🇷 Seul', 'Europe/Berlin' => '🇩🇪 Berlin',
        'Europe/London' => '🇬🇧 London', 'America/New_York' => '🇺🇸 New York', 'UTC' => '🌐 UTC',
    ];

    /** @return array<int, array<int, array<string,string>>> preview ostidagi boshqaruv qatorlari (ixcham, 5 tugma) */
    public static function previewRows(string $lang, bool $aiAgain = false, ?string $miniApp = null): array
    {
        $rows = [
            [self::btn(I18n::t('btn_send_now', $lang), 'p:now'), self::btn(I18n::t('btn_set_time', $lang), 'p:time')],
            [self::btn(I18n::t('btn_more', $lang), 'p:more'), self::btn(I18n::t('btn_edit', $lang), 'p:edit')],
        ];
        if ($aiAgain) {
            $rows[] = [self::btn(I18n::t('btn_ai_again', $lang), 'ai:again')];
        }
        if ($miniApp !== null) {
            $rows[] = [['text' => I18n::t('btn_miniapp_continue', $lang), 'web_app' => ['url' => $miniApp]]];
        }
        $rows[] = [self::btn(I18n::t('btn_cancel', $lang), 'p:cancel')];
        return $rows;
    }

    /** «⚙️ Qo'shimcha»: tugma, reaksiya (albomda yo'q), takror, avto-o'chirish. */
    public static function more(string $lang, array $draft, bool $album, bool $ai = false): array
    {
        $rows = [];
        if ($ai && trim(Html::plain((string) ($draft['text'] ?? ''))) !== '') {
            $rows[] = [self::btn(I18n::t('btn_ai_edit', $lang), 'p:ai')];
        }
        if (!$album) {
            $has = !empty($draft['button_url']);
            $rows[] = [self::btn(I18n::t($has ? 'btn_remove_button' : 'btn_add_button', $lang), $has ? 'p:btndel' : 'p:btn'),
                self::btn((!empty($draft['reactions']) ? '✅ ' : '') . I18n::t('btn_reactions', $lang), 'p:rx')];
        }
        $rows[] = [self::btn(I18n::t('btn_repeat', $lang), 'p:rep'),
            self::btn((!empty($draft['delete_after']) ? '✅ ' : '') . I18n::t('btn_autodelete', $lang), 'p:ad')];
        $rows[] = [self::btn(I18n::t('btn_back', $lang), 'p:back')];
        return self::inline($rows);
    }

    public static function repeat(string $lang): array
    {
        return self::inline([
            [self::btn(I18n::t('btn_rep_daily', $lang), 'pr:daily'), self::btn(I18n::t('btn_rep_weekly', $lang), 'pr:weekly')],
            [self::btn(I18n::t('btn_rep_monthly', $lang), 'pr:monthly'), self::btn(I18n::t('btn_rep_twice', $lang), 'pr:twice')],
            [self::btn(I18n::t('btn_rep_none', $lang), 'pr:none'), self::btn(I18n::t('btn_back', $lang), 'p:back')],
        ]);
    }

    public static function reactions(string $lang): array
    {
        $rows = [];
        foreach (PostRender::REACTION_SETS as $i => $set) {
            $rows[] = [self::btn(str_replace(',', ' ', $set), 'px:' . $i)];
        }
        $rows[] = [self::btn(I18n::t('btn_rx_custom', $lang), 'px:c'), self::btn(I18n::t('btn_rx_none', $lang), 'px:none')];
        $rows[] = [self::btn(I18n::t('btn_back', $lang), 'p:back')];
        return self::inline($rows);
    }

    public static function autoDelete(string $lang): array
    {
        $b = static function (int $min) use ($lang): array {
            return self::btn(I18n::t('ad_hours', $lang, ['h' => intdiv($min, 60)]), 'pa:' . $min);
        };
        return self::inline([
            [$b(60), $b(360), $b(720)],
            [$b(1440), $b(2880)],
            [self::btn(I18n::t('btn_ad_none', $lang), 'pa:0'), self::btn(I18n::t('btn_back', $lang), 'p:back')],
        ]);
    }

    public static function timezones(string $lang): array
    {
        $rows = [];
        $row = [];
        foreach (self::TIMEZONES as $id => $label) {
            $row[] = self::btn($label, 'tz:' . $id);
            if (count($row) === 3) {
                $rows[] = $row;
                $row = [];
            }
        }
        if ($row) {
            $rows[] = $row;
        }
        $rows[] = self::navRow($lang, 'set:show');
        return self::inline($rows);
    }

    /** Admin paneli tugmalari. */
    public static function admin(string $lang): array
    {
        return self::inline([
            [self::btn(I18n::t('btn_adm_promos', $lang), 'a:promos'), self::btn(I18n::t('btn_adm_links', $lang), 'a:links')],
            [self::btn(I18n::t('btn_adm_bc', $lang), 'a:bc'), self::btn(I18n::t('btn_adm_fs', $lang), 'a:fs')],
            [self::btn(I18n::t('btn_adm_help', $lang), 'a:help'), self::btn(I18n::t('btn_refresh', $lang), 'a:stats')],
            self::navRow($lang),
        ]);
    }

    public static function times(string $lang): array
    {
        return self::inline([
            [self::btn(I18n::t('btn_t_1h', $lang), 't:1h')],
            [self::btn(I18n::t('btn_t_today18', $lang), 't:today18'), self::btn(I18n::t('btn_t_tom09', $lang), 't:tom09')],
            [self::btn(I18n::t('btn_back', $lang), 'p:back')],
        ]);
    }

    public static function queue(array $posts, string $lang, \DateTimeZone $tz): array
    {
        $rows = [];
        foreach ($posts as $p) {
            $when = (new \DateTimeImmutable((string) $p['scheduled_time'], new \DateTimeZone('UTC')))->setTimezone($tz)->format('d.m H:i');
            $label = $when . ' · ' . mb_substr((string) ($p['channel_title'] ?? ''), 0, 24);
            $icon = !empty($p['recurrence_type']) ? '🔄 ' : ($p['post_type'] === 'album' ? '🖼 ' : '📄 ');
            $rows[] = [self::btn($icon . $label, 'q:v:' . (int) $p['id'])];
        }
        $rows[] = [self::btn(I18n::t('btn_new_post', $lang), 'p:new'), self::btn(I18n::t('btn_home', $lang), 'm:home')];
        return self::inline($rows);
    }

    public static function queueItem(int $id, string $lang): array
    {
        return self::inline([[self::btn(I18n::t('btn_q_del', $lang), 'q:d:' . $id), self::btn(I18n::t('btn_back', $lang), 'q:list')]]);
    }
}
