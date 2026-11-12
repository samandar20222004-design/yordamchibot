<?php
declare(strict_types=1);

namespace PostAssist\Services;

/**
 * Birja hududi: davlat (ISO-2) yoki Global («ZZ»). Foydalanuvchi davlati uning vaqt mintaqasidan aniqlanadi.
 * Katalog tartibi: o'z davlati → yaqin davlatlar (chegaradosh + bir til/madaniyat guruhi) → Global → qolganlar.
 * Python `services/channel_region.py:near_countries` bilan bir xil ro'yxat.
 */
final class Region
{
    public const GLOBAL = 'ZZ';

    private const BORDERS = [
        'UZ' => ['KZ', 'KG', 'TJ', 'TM', 'AF'], 'KZ' => ['UZ', 'KG', 'RU', 'CN', 'TM'], 'KG' => ['UZ', 'KZ', 'TJ', 'CN'],
        'TJ' => ['UZ', 'KG', 'TM', 'AF', 'CN'], 'TM' => ['UZ', 'KZ', 'TJ', 'AF', 'IR'], 'RU' => ['KZ', 'BY', 'UA', 'AZ', 'GE', 'AM', 'CN'],
        'UA' => ['PL', 'BY', 'RU', 'MD', 'RO', 'SK', 'HU'], 'BY' => ['RU', 'UA', 'PL', 'LT', 'LV'],
        'TR' => ['AZ', 'GE', 'AM', 'IR', 'IQ', 'SY', 'BG', 'GR'], 'AZ' => ['TR', 'GE', 'AM', 'RU', 'IR', 'KZ'],
        'GE' => ['TR', 'AZ', 'AM', 'RU'], 'AM' => ['TR', 'AZ', 'GE', 'IR', 'RU'], 'IN' => ['PK', 'BD', 'NP', 'LK'],
        'DE' => ['AT', 'CH', 'NL', 'PL', 'FR', 'CZ', 'BE', 'DK'], 'US' => ['CA', 'MX'], 'GB' => ['IE', 'FR'],
    ];
    private const GROUPS = [
        ['RU', 'UA', 'BY', 'KZ', 'KG', 'TJ', 'TM', 'UZ', 'AZ', 'AM', 'GE', 'MD'],
        ['TR', 'AZ', 'UZ', 'KZ', 'KG', 'TM'],
        ['SA', 'AE', 'EG', 'IQ', 'JO', 'KW', 'QA', 'OM', 'BH', 'YE', 'SY', 'LB', 'LY', 'DZ', 'MA', 'TN', 'SD'],
        ['DE', 'FR', 'IT', 'ES', 'PT', 'NL', 'BE', 'AT', 'CH', 'PL', 'CZ', 'SK', 'HU', 'RO', 'BG', 'GR', 'SE', 'NO', 'DK', 'FI', 'IE'],
        ['US', 'GB', 'CA', 'AU', 'NZ', 'IE'],
        ['IN', 'PK', 'BD', 'LK', 'NP'],
    ];

    /** @var array<string,string>|null zona => davlat */
    private static $zoneMap = null;

    /** Yaqin davlatlar (o'zi kirmaydi). Noma'lum/Global — bo'sh. @return string[] */
    public static function near(string $code): array
    {
        $c = strtoupper($code);
        if ($c === '' || $c === self::GLOBAL) {
            return [];
        }
        $out = self::BORDERS[$c] ?? [];
        foreach (self::GROUPS as $g) {
            if (in_array($c, $g, true)) {
                $out = array_merge($out, $g);
            }
        }
        $out = array_values(array_unique(array_diff($out, [$c])));
        sort($out);
        return $out;
    }

    /** Vaqt mintaqasidan davlat (Asia/Tashkent → UZ). Topilmasa — null. */
    public static function countryOfZone(string $zone): ?string
    {
        if (self::$zoneMap === null) {
            self::$zoneMap = [];
            foreach (CountryData::ALL as $code => $row) {
                foreach ((array) $row[3] as $z) {
                    if (!isset(self::$zoneMap[$z])) {
                        self::$zoneMap[$z] = $code;
                    }
                }
            }
        }
        return self::$zoneMap[$zone] ?? null;
    }

    /** Davlat kodi to'g'rimi (yoki Global). */
    public static function valid(string $code): bool
    {
        return $code === self::GLOBAL || isset(CountryData::ALL[$code]);
    }

    public static function label(string $code, string $lang): string
    {
        if ($code === '' || $code === self::GLOBAL) {
            return '🌍 Global';
        }
        return Countries::flag($code) . ' ' . Countries::name($code, $lang);
    }
}
