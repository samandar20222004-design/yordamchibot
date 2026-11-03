<?php
declare(strict_types=1);

namespace PostAssist;

/** uz / ru / en matnlari. Kalit topilmasa o'zbekcha, u ham bo'lmasa kalitning o'zi qaytadi. */
final class I18n
{
    public const LANGS = ['uz', 'ru', 'en'];
    public const NAMES = ['uz' => "🇺🇿 O'zbekcha", 'ru' => '🇷🇺 Русский', 'en' => '🇬🇧 English'];

    /** @var array<string, array<string, string>> */
    private static array $cache = [];

    public static function norm(?string $lang): string
    {
        $l = strtolower(substr((string) $lang, 0, 2));
        return in_array($l, self::LANGS, true) ? $l : 'uz';
    }

    /** Telegram `language_code` dan boshlang'ich til. */
    public static function detect(?string $code): string
    {
        $c = strtolower(substr((string) $code, 0, 2));
        if ($c === 'ru' || $c === 'uk' || $c === 'be' || $c === 'kk') {
            return 'ru';
        }
        if ($c === 'uz' || $c === '') {
            return 'uz';
        }
        return 'en';
    }

    /** @return array<string, string> */
    public static function table(string $lang): array
    {
        $lang = self::norm($lang);
        if (!isset(self::$cache[$lang])) {
            self::$cache[$lang] = require __DIR__ . '/Lang/' . $lang . '.php';
        }
        return self::$cache[$lang];
    }

    /**
     * @param array<string, string|int> $params qiymatlar o'zgarishsiz qo'yiladi — HTML-escape chaqiruvchida.
     */
    public static function t(string $key, string $lang, array $params = []): string
    {
        $text = self::table($lang)[$key] ?? self::table('uz')[$key] ?? $key;
        if ($params) {
            $map = [];
            foreach ($params as $k => $v) {
                $map['{' . $k . '}'] = (string) $v;
            }
            $text = strtr($text, $map);
        }
        return $text;
    }

    /** Berilgan matn qaysi tildagi qaysi kalitga teng (eski klaviatura boshqa tilda qolgan bo'lsa ham ishlaydi). */
    public static function keyOf(string $text, array $keys): ?string
    {
        foreach (self::LANGS as $l) {
            $tbl = self::table($l);
            foreach ($keys as $k) {
                if (isset($tbl[$k]) && $tbl[$k] === $text) {
                    return $k;
                }
            }
        }
        return null;
    }
}
