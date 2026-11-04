<?php
declare(strict_types=1);

namespace PostAssist\Services;

use DateTimeImmutable;
use DateTimeZone;

/**
 * Takroriy post qoidalari (Python `services/recurrence.py` bilan bir xil ma'no):
 *  - daily   — har kuni `time` (kun boshidan daqiqa) da;
 *  - weekly  — har hafta `day` (1=dushanba … 7=yakshanba) kuni `time` da;
 *  - monthly — har oyning `day`-kuni `time` da (oyda bunday kun bo'lmasa — oyning oxirgi kuni);
 *  - twice   — har kuni ikki marta: `time` (ertalab) va `day` (kechqurun, daqiqa) da.
 * Vaqt egasining mintaqasida hisoblanadi (yozgi vaqt o'tishi PHP DateTime orqali to'g'ri). Keyingi vaqt doim «hozir»dan
 * KEYIN olinadi — cron bir necha kun ishlamay qolsa ham o'tib ketgan nusxalar ketma-ket yuborilmaydi.
 */
final class Recurrence
{
    public const TYPES = ['daily', 'weekly', 'monthly', 'twice'];

    /** Tanlangan birinchi vaqtdan qoida parametrlari. @return array{type:string,time:int,day:?int}|null */
    public static function fromFirst(string $type, DateTimeImmutable $firstUtc, DateTimeZone $tz, ?int $secondMinutes = null): ?array
    {
        if (!in_array($type, self::TYPES, true)) {
            return null;
        }
        $l = $firstUtc->setTimezone($tz);
        $time = (int) $l->format('G') * 60 + (int) $l->format('i');
        switch ($type) {
            case 'weekly':
                return ['type' => $type, 'time' => $time, 'day' => (int) $l->format('N')];
            case 'monthly':
                return ['type' => $type, 'time' => $time, 'day' => (int) $l->format('j')];
            case 'twice':
                if ($secondMinutes === null || $secondMinutes < 0 || $secondMinutes >= 1440 || $secondMinutes === $time) {
                    return null;
                }
                return ['type' => $type, 'time' => min($time, $secondMinutes), 'day' => max($time, $secondMinutes)];
        }
        return ['type' => $type, 'time' => $time, 'day' => null];
    }

    /** «HH:MM» -> daqiqa yoki null. */
    public static function parseClock(string $s): ?int
    {
        if (!preg_match('/^\s*(\d{1,2})[:.](\d{2})\s*$/', $s, $m) || (int) $m[1] > 23 || (int) $m[2] > 59) {
            return null;
        }
        return (int) $m[1] * 60 + (int) $m[2];
    }

    private static function at(DateTimeImmutable $localDay, int $minutes): DateTimeImmutable
    {
        return $localDay->setTime(intdiv($minutes, 60), $minutes % 60, 0);
    }

    /** Hozirdan keyingi chiqish vaqti (UTC) yoki null (noto'g'ri qoida). */
    public static function next(string $type, int $time, ?int $day, DateTimeImmutable $nowUtc, DateTimeZone $tz): ?DateTimeImmutable
    {
        if ($time < 0 || $time >= 1440) {
            return null;
        }
        $now = $nowUtc->setTimezone($tz);
        $today = $now->setTime(0, 0, 0);
        $best = null;
        switch ($type) {
            case 'daily':
            case 'twice':
                $times = [$time];
                if ($type === 'twice') {
                    if ($day === null || $day < 0 || $day >= 1440) {
                        return null;
                    }
                    $times[] = $day;
                }
                for ($d = 0; $d <= 2 && $best === null; $d++) {
                    foreach ($times as $t) {
                        $c = self::at($today->modify("+{$d} days"), $t);
                        if ($c > $now && ($best === null || $c < $best)) {
                            $best = $c;
                        }
                    }
                }
                break;
            case 'weekly':
                if ($day === null || $day < 1 || $day > 7) {
                    return null;
                }
                for ($d = 0; $d <= 7; $d++) {
                    $dayDt = $today->modify("+{$d} days");
                    $c = self::at($dayDt, $time);
                    if ((int) $dayDt->format('N') === $day && $c > $now) {
                        $best = $c;
                        break;
                    }
                }
                break;
            case 'monthly':
                if ($day === null || $day < 1 || $day > 31) {
                    return null;
                }
                $first = $now->setDate((int) $now->format('Y'), (int) $now->format('n'), 1)->setTime(0, 0, 0);
                for ($k = 0; $k <= 2; $k++) {
                    $month = $first->modify("+{$k} months");
                    $dom = min($day, (int) $month->format('t'));
                    $c = self::at($month->setDate((int) $month->format('Y'), (int) $month->format('n'), $dom), $time);
                    if ($c > $now) {
                        $best = $c;
                        break;
                    }
                }
                break;
            default:
                return null;
        }
        return $best !== null ? $best->setTimezone(new DateTimeZone('UTC')) : null;
    }

    public static function clock(int $minutes): string
    {
        return sprintf('%02d:%02d', intdiv($minutes, 60), $minutes % 60);
    }
}
