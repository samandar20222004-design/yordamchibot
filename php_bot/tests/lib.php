<?php
// Oddiy test yordamchisi (PHPUnit'siz — hostingda ham, lokal ham ishlaydi).
declare(strict_types=1);

require_once dirname(__DIR__) . '/bootstrap.php';

final class T
{
    public static int $ok = 0;
    public static int $fail = 0;
    public static int $skip = 0;

    /** @param mixed $cond */
    public static function check(string $label, $cond, string $detail = ''): void
    {
        if ($cond) {
            self::$ok++;
            echo "  [OK] {$label}\n";
        } else {
            self::$fail++;
            echo "  [XATO] {$label}" . ($detail !== '' ? " — {$detail}" : '') . "\n";
        }
    }

    /** @param mixed $a @param mixed $b */
    public static function eq(string $label, $a, $b): void
    {
        self::check($label, $a === $b, 'kutilgan: ' . var_export($b, true) . ' | olindi: ' . var_export($a, true));
    }

    public static function skip(string $label, string $why): void
    {
        self::$skip++;
        echo "  [SKIP] {$label} — {$why}\n";
    }

    public static function section(string $title): void
    {
        echo "\n== {$title} ==\n";
    }

    public static function finish(): int
    {
        echo "\n" . str_repeat('=', 60) . "\n JAMI: o'tdi=" . self::$ok . ', xato=' . self::$fail . ', skip=' . self::$skip . "\n" . str_repeat('=', 60) . "\n";
        return self::$fail === 0 ? 0 : 1;
    }
}
