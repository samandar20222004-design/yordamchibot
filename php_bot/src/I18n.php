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
    /** Eski tugma yorliqlari (foydalanuvchida eski klaviatura qolgan bo'lsa ham taniladi). */
    /** Eski (Python bot) pastki menyu yorliqlari — Telegram eski klaviaturani saqlab qoladi, bosilsa ham ishlasin. */
    public const ALIASES = [
        'btn_settings' => ["Sozlamalar / Ko'proq", 'Настройки / Ещё', 'Settings / More', "Qo'shimcha funksiyalar", 'Дополнительные функции', 'Extra features'],
        'btn_admin' => ['Admin Panel', 'Admin panel', 'Панель администратора', 'Админ панель', 'Админ-панель'],
        'btn_create_content' => ['Yangi post', 'Новый пост', 'New post'],
        'btn_ai_post' => ['AI Yordamchi', 'AI Помощник', 'AI-помощник', 'AI Assistant', 'AI Post Yordamchi', 'Magic Post'],
        'btn_my_channels' => ['Kanal/Guruhlar', 'Каналы/Группы', 'Channels/Groups'],
        'btn_scheduled' => ['Kutilayotgan postlar', 'Ожидающие посты', 'Pending posts'],
        'menu_home' => ['Asosiy menyu', 'Главное меню', 'Main menu', "To'liq menyuni ochish", 'Открыть полное меню', 'Open full menu'],
    ];

    /** Matn eski (hozirgi menyuda yo'q) yorliqmi — klaviaturani yangilash kerak. */
    public static function isAlias(string $text): bool
    {
        $bare = self::bare($text);
        foreach (self::LANGS as $l) {
            foreach (self::table($l) as $k => $v) {
                if (strpos((string) $k, 'btn_') === 0 && is_string($v) && self::bare($v) === $bare) {
                    return false; // hozirgi yorliq (masalan «👑 Admin panel») — eski emas
                }
            }
        }
        foreach (self::ALIASES as $list) {
            if ($bare !== '' && in_array($bare, $list, true)) {
                return true;
            }
        }
        return false;
    }

    public static function keyOf(string $text, array $keys): ?string
    {
        // premium belgi qo'yilgan tugmada emoji matndan olinadi — belgisiz matn ham taniladi
        $bare = self::bare($text);
        foreach ($keys as $k) {
            if ($bare !== '' && in_array($bare, self::ALIASES[$k] ?? [], true)) {
                return $k;
            }
        }
        foreach (self::LANGS as $l) {
            $tbl = self::table($l);
            foreach ($keys as $k) {
                if (isset($tbl[$k]) && ($tbl[$k] === $text || ($bare !== '' && self::bare($tbl[$k]) === $bare))) {
                    return $k;
                }
            }
        }
        return null;
    }

    /** Boshidagi emoji/belgilarsiz matn. */
    public static function bare(string $s): string
    {
        return trim((string) preg_replace('/^[^\p{L}\p{N}]+/u', '', $s));
    }
}
