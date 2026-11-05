<?php
declare(strict_types=1);

namespace PostAssist\Services;

use DateTimeImmutable;
use DateTimeZone;

/**
 * 🌍 Davlat va vaqt mintaqasini topish: 247 davlat/hudud (o'zbek, rus, ingliz nomlari, ISO kod, mashhur qisqa nomlar),
 * shahar (Toshkent, Nyu-York, Dubai…) va IANA nomi (Europe/Paris). Apostrof/tutuq belgisi va harf katta-kichikligi farqsiz.
 */
final class Countries
{
    /** Qisqa va so'zlashuvdagi nomlar. */
    private const ALIASES = [
        'aqsh' => 'US', 'amerika' => 'US', 'usa' => 'US', 'сша' => 'US', 'америка' => 'US', 'america' => 'US', 'shtatlar' => 'US',
        'angliya' => 'GB', 'britaniya' => 'GB', 'buyuk britaniya' => 'GB', 'uk' => 'GB', 'англия' => 'GB', 'британия' => 'GB', 'england' => 'GB', 'britain' => 'GB',
        'rossiya' => 'RU', 'rusiya' => 'RU', 'russia' => 'RU', 'рф' => 'RU', 'koreya' => 'KR', 'korea' => 'KR', 'корея' => 'KR', 'janubiy koreya' => 'KR',
        'bae' => 'AE', 'baa' => 'AE', 'oae' => 'AE', 'оаэ' => 'AE', 'uae' => 'AE', 'emirates' => 'AE', 'amirliklar' => 'AE', 'dubay' => 'AE', 'дубай' => 'AE',
        'gollandiya' => 'NL', 'голландия' => 'NL', 'holland' => 'NL', 'chexiya' => 'CZ', 'чехия' => 'CZ', 'czechia' => 'CZ',
        'qirgiziston' => 'KG', 'kirgiziya' => 'KG', 'киргизия' => 'KG', 'kyrgyzstan' => 'KG', 'tojikiston' => 'TJ', 'turkmaniston' => 'TM',
        'turkiya' => 'TR', 'turkey' => 'TR', 'турция' => 'TR', 'turkiye' => 'TR', 'misr' => 'EG', 'arabiston' => 'SA', 'saudiya' => 'SA', 'saudi' => 'SA',
        'xitoy' => 'CN', 'china' => 'CN', 'китай' => 'CN', 'yaponiya' => 'JP', 'hindiston' => 'IN', 'india' => 'IN', 'индия' => 'IN',
        'olmoniya' => 'DE', 'nemis' => 'DE', 'германия' => 'DE', 'фрг' => 'DE', 'polsha' => 'PL', 'польша' => 'PL', 'ukraina' => 'UA', 'украина' => 'UA',
        'belorussiya' => 'BY', 'belarus' => 'BY', 'беларусь' => 'BY', 'qozogiston' => 'KZ', 'казахстан' => 'KZ', 'kazakhstan' => 'KZ',
        'ozbekiston' => 'UZ', 'uzbekistan' => 'UZ', 'узбекистан' => 'UZ', 'italiya' => 'IT', 'ispaniya' => 'ES', 'fransiya' => 'FR', 'франция' => 'FR',
        'kanada' => 'CA', 'avstraliya' => 'AU', 'braziliya' => 'BR', 'meksika' => 'MX', 'koreya respublikasi' => 'KR', 'shimoliy koreya' => 'KP',
    ];
    /** Shaharlarning o'zbekcha/ruscha yozilishi. */
    private const CITIES = [
        'toshkent' => 'Asia/Tashkent', 'ташкент' => 'Asia/Tashkent', 'samarqand' => 'Asia/Samarkand', 'самарканд' => 'Asia/Samarkand',
        'moskva' => 'Europe/Moscow', 'москва' => 'Europe/Moscow', 'sankt-peterburg' => 'Europe/Moscow', 'piter' => 'Europe/Moscow',
        'nyu-york' => 'America/New_York', 'nyu york' => 'America/New_York', 'нью-йорк' => 'America/New_York', 'chikago' => 'America/Chicago',
        'los-anjeles' => 'America/Los_Angeles', 'лос-анджелес' => 'America/Los_Angeles', 'london' => 'Europe/London', 'лондон' => 'Europe/London',
        'seul' => 'Asia/Seoul', 'сеул' => 'Asia/Seoul', 'tokio' => 'Asia/Tokyo', 'токио' => 'Asia/Tokyo', 'pekin' => 'Asia/Shanghai', 'пекин' => 'Asia/Shanghai',
        'istanbul' => 'Europe/Istanbul', 'стамбул' => 'Europe/Istanbul', 'dubay' => 'Asia/Dubai', 'дубай' => 'Asia/Dubai', 'olmaota' => 'Asia/Almaty',
        'алматы' => 'Asia/Almaty', 'astana' => 'Asia/Almaty', 'астана' => 'Asia/Almaty', 'bishkek' => 'Asia/Bishkek', 'бишкек' => 'Asia/Bishkek',
        'dushanbe' => 'Asia/Dushanbe', 'душанбе' => 'Asia/Dushanbe', 'ashxobod' => 'Asia/Ashgabat', 'ашхабад' => 'Asia/Ashgabat',
        'novosibirsk' => 'Asia/Novosibirsk', 'yekaterinburg' => 'Asia/Yekaterinburg', 'ekaterinburg' => 'Asia/Yekaterinburg', 'екатеринбург' => 'Asia/Yekaterinburg',
        'vladivostok' => 'Asia/Vladivostok', 'parij' => 'Europe/Paris', 'париж' => 'Europe/Paris', 'berlin' => 'Europe/Berlin', 'берлин' => 'Europe/Berlin',
    ];

    /** Bir xil vaqtli mintaqalardan qaysi shahar ko'rsatilsin (yirik shaharlar birinchi). */
    private const PREFERRED = [
        'Europe/Moscow', 'Europe/Kaliningrad', 'Europe/Samara', 'Asia/Yekaterinburg', 'Asia/Omsk', 'Asia/Novosibirsk', 'Asia/Krasnoyarsk', 'Asia/Irkutsk',
        'Asia/Yakutsk', 'Asia/Vladivostok', 'Asia/Magadan', 'Asia/Kamchatka',
        'America/New_York', 'America/Chicago', 'America/Denver', 'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu',
        'America/Toronto', 'America/Vancouver', 'America/Edmonton', 'America/Winnipeg', 'America/Halifax', 'America/St_Johns', 'America/Regina',
        'Australia/Sydney', 'Australia/Brisbane', 'Australia/Adelaide', 'Australia/Darwin', 'Australia/Perth',
        'America/Sao_Paulo', 'America/Manaus', 'America/Mexico_City', 'America/Cancun', 'America/Tijuana', 'Asia/Jakarta', 'Asia/Makassar', 'Asia/Jayapura',
        'Asia/Shanghai', 'Asia/Almaty', 'Asia/Tashkent', 'Europe/Kyiv', 'Europe/Madrid', 'Atlantic/Canary', 'Europe/Lisbon',
    ];

    /** Qidiruv uchun tozalash: kichik harf, apostrof/tutuq belgilari olinadi, ё=е, bo'shliqlar bitta. */
    public static function norm(string $s): string
    {
        $s = mb_strtolower(trim($s));
        $s = str_replace(['ʻ', 'ʼ', "'", '‘', '’', '`', '´', 'ʹ'], '', $s);
        $s = str_replace('ё', 'е', $s);
        return trim((string) preg_replace('/\s+/u', ' ', $s));
    }

    public static function flag(string $code): string
    {
        if (!preg_match('/^[A-Z]{2}$/', $code)) {
            return '🌐';
        }
        $out = '';
        foreach (str_split($code) as $ch) {
            $out .= mb_chr(0x1F1E6 + ord($ch) - 65, 'UTF-8');
        }
        return $out;
    }

    public static function name(string $code, string $lang): string
    {
        $row = CountryData::ALL[$code] ?? null;
        if ($row === null) {
            return $code;
        }
        return (string) $row[['uz' => 0, 'ru' => 1, 'en' => 2][$lang] ?? 0];
    }

    /** Yangi nomli mintaqalarning eski nomi (eski tzdata'li hosting, masalan PHP 7.4). */
    private const OLD_NAMES = ['Europe/Kyiv' => 'Europe/Kiev', 'America/Nuuk' => 'America/Godthab', 'Pacific/Kanton' => 'Pacific/Enderbury',
        'Asia/Yangon' => 'Asia/Rangoon', 'America/Ciudad_Juarez' => 'America/Ojinaga', 'America/Coyhaique' => 'America/Punta_Arenas'];
    /** @var array<string,bool>|null */
    private static ?array $known = null;

    /** Davlat mintaqalari — faqat shu serverdagi PHP biladiganlari (yangi nom bo'lmasa eskisi). @return string[] */
    public static function zones(string $code): array
    {
        if (self::$known === null) {
            self::$known = array_fill_keys(DateTimeZone::listIdentifiers(), true);
        }
        $out = [];
        foreach (CountryData::ALL[$code][3] ?? [] as $z) {
            if (!isset(self::$known[$z]) && isset(self::OLD_NAMES[$z])) {
                $z = self::OLD_NAMES[$z];
            }
            if (isset(self::$known[$z]) && !in_array($z, $out, true)) {
                $out[] = $z;
            }
        }
        return $out;
    }

    /**
     * Foydalanuvchiga tanlash uchun mintaqalar: hozirgi vaqti bir xil bo'lganlardan faqat birinchisi (asosiysi) qoladi.
     * Masalan Germaniya (Berlin, Busingen) — bitta; AQSH — 6–7 xil vaqt.
     * @return string[]
     */
    public static function distinctZones(string $code, ?DateTimeImmutable $nowUtc = null): array
    {
        $now = $nowUtc ?? new DateTimeImmutable('now', new DateTimeZone('UTC'));
        $all = self::zones($code);
        $main = $all[0] ?? null;
        // asosiy mintaqa, keyin yirik shaharlar, keyin qolganlari — har vaqt farqidan birinchisi tanlanadi
        usort($all, static function (string $a, string $b) use ($main): int {
            $ra = $a === $main ? -1 : (($i = array_search($a, self::PREFERRED, true)) === false ? 999 : $i);
            $rb = $b === $main ? -1 : (($i = array_search($b, self::PREFERRED, true)) === false ? 999 : $i);
            return $ra === $rb ? strcmp($a, $b) : $ra <=> $rb;
        });
        $picked = [];
        foreach ($all as $z) {
            try {
                $off = (new DateTimeZone($z))->getOffset($now);
            } catch (\Throwable $e) {
                continue;
            }
            if (!isset($picked[$off])) {
                $picked[$off] = $z;
            }
        }
        // ko'rsatish: asosiysi birinchi, qolgani UTC farqi bo'yicha
        $first = $main !== null && in_array($main, $picked, true) ? [$main] : [];
        $rest = array_diff_key($picked, array_flip(array_keys($picked, $main, true)));
        ksort($rest);
        return array_values(array_merge($first, array_values($rest)));
    }

    /** Mintaqa yorlig'i: «New York (UTC−5)». */
    public static function zoneLabel(string $zone, ?DateTimeImmutable $nowUtc = null): string
    {
        $city = str_replace('_', ' ', substr($zone, (int) strrpos($zone, '/') + (strpos($zone, '/') !== false ? 1 : 0)));
        try {
            $off = (new DateTimeZone($zone))->getOffset($nowUtc ?? new DateTimeImmutable('now', new DateTimeZone('UTC')));
        } catch (\Throwable $e) {
            return $city;
        }
        $h = intdiv(abs($off), 3600);
        $m = intdiv(abs($off) % 3600, 60);
        return $city . ' (UTC' . ($off < 0 ? '−' : '+') . $h . ($m ? ':' . sprintf('%02d', $m) : '') . ')';
    }

    /** Aniq mintaqa (IANA nomi yoki shahar) — topilmasa null. */
    public static function zoneFor(string $input): ?string
    {
        $q = self::norm($input);
        if ($q === '') {
            return null;
        }
        foreach (DateTimeZone::listIdentifiers() as $id) {
            if (strtolower($id) === $q) {
                return $id;
            }
        }
        if (isset(self::CITIES[$q])) {
            return self::CITIES[$q];
        }
        $qq = str_replace(['-', ' '], '_', $q);
        foreach (DateTimeZone::listIdentifiers() as $id) {
            $city = strtolower(substr($id, (int) strrpos($id, '/') + (strpos($id, '/') !== false ? 1 : 0)));
            if ($city === $qq) {
                return $id;
            }
        }
        return null;
    }

    /**
     * Davlat qidiruvi: aniq mos (nom, kod, qisqa nom) birinchi, keyin boshlanishi, keyin ichida (≥3 harf).
     * @return string[] ISO kodlar (ko'pi bilan $limit)
     */
    public static function search(string $input, int $limit = 8): array
    {
        $q = self::norm($input);
        if ($q === '') {
            return [];
        }
        $exact = [];
        $starts = [];
        $contains = [];
        if (isset(self::ALIASES[$q])) {
            $exact[] = self::ALIASES[$q];
        }
        if (preg_match('/^[a-z]{2}$/', $q) && isset(CountryData::ALL[strtoupper($q)])) {
            $exact[] = strtoupper($q);
        }
        foreach (CountryData::ALL as $code => $row) {
            foreach ([0, 1, 2] as $i) {
                $n = self::norm((string) $row[$i]);
                if ($n === $q) {
                    $exact[] = $code;
                } elseif (strpos($n, $q) === 0) {
                    $starts[] = $code;
                } elseif (mb_strlen($q) >= 3 && strpos($n, $q) !== false) {
                    $contains[] = $code;
                }
            }
        }
        return array_slice(array_values(array_unique(array_merge($exact, $starts, $contains))), 0, $limit);
    }
}
