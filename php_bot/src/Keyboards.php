<?php
declare(strict_types=1);

namespace PostAssist;

/** Klaviaturalar. Callback ma'lumoti qisqa va qat'iy formatda (Router faqat shu shakllarni qabul qiladi). */
final class Keyboards
{
    public static function main(string $lang, bool $admin): array
    {
        $t = static fn (string $k) => ['text' => I18n::t($k, $lang)];
        $rows = [
            [$t('btn_create_content'), $t('btn_my_channels')],
            [$t('btn_scheduled'), $t('btn_statistics')],
            [$t('btn_settings')],
        ];
        if ($admin) {
            $rows[] = [$t('btn_admin')];
        }
        return ['keyboard' => $rows, 'resize_keyboard' => true, 'is_persistent' => true];
    }

    public static function inline(array $rows): array
    {
        return ['inline_keyboard' => array_values(array_filter($rows))];
    }

    public static function btn(string $text, string $data): array
    {
        return ['text' => $text, 'callback_data' => $data];
    }

    public static function languages(): array
    {
        $row = [];
        foreach (I18n::NAMES as $code => $name) {
            $row[] = self::btn($name, 'lang:' . $code);
        }
        return self::inline([$row]);
    }

    public static function settings(string $lang): array
    {
        return self::inline([
            [self::btn(I18n::t('btn_lang', $lang), 'set:lang')],
            [self::btn(I18n::t('btn_help', $lang), 'set:help')],
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

    /** @return array<int, array<int, array<string,string>>> preview ostidagi boshqaruv qatorlari */
    public static function previewRows(string $lang, bool $hasButton): array
    {
        return [
            [self::btn(I18n::t('btn_send_now', $lang), 'p:now'), self::btn(I18n::t('btn_set_time', $lang), 'p:time')],
            [self::btn(I18n::t($hasButton ? 'btn_remove_button' : 'btn_add_button', $lang), $hasButton ? 'p:btndel' : 'p:btn'),
                self::btn(I18n::t('btn_edit', $lang), 'p:edit')],
            [self::btn(I18n::t('btn_cancel', $lang), 'p:cancel')],
        ];
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
            $rows[] = [self::btn('📄 ' . $label, 'q:v:' . (int) $p['id'])];
        }
        return self::inline($rows);
    }

    public static function queueItem(int $id, string $lang): array
    {
        return self::inline([[self::btn(I18n::t('btn_q_del', $lang), 'q:d:' . $id), self::btn(I18n::t('btn_back', $lang), 'q:list')]]);
    }
}
