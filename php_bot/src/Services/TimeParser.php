<?php
declare(strict_types=1);

namespace PostAssist\Services;

use DateTimeImmutable;
use DateTimeZone;

/**
 * Foydalanuvchi yozgan vaqtni tushunadi (foydalanuvchi mintaqasida) va UTC'da qaytaradi.
 * Qo'llanadi: "14:30", "14.30", "bugun 18:00", "ertaga 09:00" (завтра/tomorrow), "25.12 18:00", "25.12.2026 18:00",
 * "+30" (30 daqiqadan keyin), "30 daqiqadan keyin", "2 soatdan keyin" (через 2 часа / in 2 hours).
 * Faqat vaqt yozilsa va u bugun o'tib ketgan bo'lsa — ertangi kun olinadi.
 */
final class TimeParser
{
    public const MIN_AHEAD_SEC = 60;
    public const MAX_AHEAD_DAYS = 366;

    /** @return array{ok:bool, utc?:DateTimeImmutable, error?:string} error: bad|past|too_far */
    public static function parse(string $input, DateTimeZone $tz, DateTimeImmutable $nowUtc): array
    {
        $s = mb_strtolower(trim(preg_replace('/\s+/u', ' ', $input) ?? ''));
        $now = $nowUtc->setTimezone($tz);
        $local = null;

        if (preg_match('/^\+\s?(\d{1,6})$/', $s, $m)) {
            $local = $now->modify('+' . (int) $m[1] . ' minutes');
        } elseif (preg_match('/^(?:через\s+|in\s+)?(\d{1,4})\s*(daqiqa|minut|min|мин\w*|minutes?|soat|час\w*|hours?|kun|дн\w*|день|days?)\w*(?:\s*(?:dan|дан)?\s*keyin|\s+later)?$/u', $s, $m)) {
            $n = (int) $m[1];
            $unit = $m[2];
            if (preg_match('/^(soat|час|hour)/u', $unit)) {
                $local = $now->modify("+{$n} hours");
            } elseif (preg_match('/^(kun|дн|день|day)/u', $unit)) {
                $local = $now->modify("+{$n} days");
            } else {
                $local = $now->modify("+{$n} minutes");
            }
        } elseif (preg_match('/^(?:(bugun|сегодня|today|ertaga|завтра|tomorrow|indinga|послезавтра)\s+)?(?:soat\s+|в\s+|at\s+)?(\d{1,2})[:.](\d{2})$/u', $s, $m)) {
            $h = (int) $m[2];
            $i = (int) $m[3];
            if ($h > 23 || $i > 59) {
                return ['ok' => false, 'error' => 'bad'];
            }
            $word = $m[1] ?? '';
            $add = 0;
            if (in_array($word, ['ertaga', 'завтра', 'tomorrow'], true)) {
                $add = 1;
            } elseif (in_array($word, ['indinga', 'послезавтра'], true)) {
                $add = 2;
            }
            $local = $now->setTime($h, $i, 0)->modify("+{$add} days");
            if ($word === '' && $local <= $now) {
                $local = $local->modify('+1 day');
            }
        } elseif (preg_match('/^(\d{1,2})[.\/-](\d{1,2})(?:[.\/-](\d{2,4}))?\s+(\d{1,2})[:.](\d{2})$/', $s, $m)) {
            $d = (int) $m[1];
            $mo = (int) $m[2];
            $y = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : (int) $now->format('Y');
            if ($y < 100) {
                $y += 2000;
            }
            $h = (int) $m[4];
            $i = (int) $m[5];
            if (!checkdate($mo, $d, $y) || $h > 23 || $i > 59) {
                return ['ok' => false, 'error' => 'bad'];
            }
            $local = (new DateTimeImmutable('now', $tz))->setDate($y, $mo, $d)->setTime($h, $i, 0);
            if ((!isset($m[3]) || $m[3] === '') && $local <= $now) {
                $local = $local->modify('+1 year'); // "05.01 10:00" dekabrda yozilsa — keyingi yil
            }
        }
        if ($local === null) {
            return ['ok' => false, 'error' => 'bad'];
        }
        $utc = $local->setTimezone(new DateTimeZone('UTC'));
        $diff = $utc->getTimestamp() - $nowUtc->getTimestamp();
        if ($diff < self::MIN_AHEAD_SEC) {
            return ['ok' => false, 'error' => 'past'];
        }
        if ($diff > self::MAX_AHEAD_DAYS * 86400) {
            return ['ok' => false, 'error' => 'too_far'];
        }
        return ['ok' => true, 'utc' => $utc];
    }

    /** Tezkor tugmalar: 1h | today18 | tom09. Bugun 18:00 o'tgan bo'lsa — ertaga 18:00. */
    public static function quick(string $code, DateTimeZone $tz, DateTimeImmutable $nowUtc): ?DateTimeImmutable
    {
        $now = $nowUtc->setTimezone($tz);
        switch ($code) {
            case '1h':
                $local = $now->modify('+1 hour');
                break;
            case 'today18':
                $local = $now->setTime(18, 0, 0);
                if ($local->getTimestamp() - $now->getTimestamp() < self::MIN_AHEAD_SEC) {
                    $local = $local->modify('+1 day');
                }
                break;
            case 'tom09':
                $local = $now->setTime(9, 0, 0)->modify('+1 day');
                break;
            default:
                return null;
        }
        return $local->setTimezone(new DateTimeZone('UTC'));
    }

    public static function show(string $utcSql, DateTimeZone $tz): string
    {
        return (new DateTimeImmutable($utcSql, new DateTimeZone('UTC')))->setTimezone($tz)->format('d.m.Y H:i');
    }
}
