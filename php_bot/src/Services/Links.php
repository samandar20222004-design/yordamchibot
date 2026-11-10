<?php
declare(strict_types=1);

namespace PostAssist\Services;

/** Tugma havolasini to'g'rilash: @kanal, t.me/..., sayt.uz, https://... (Python `normalize` qoidasi bilan bir xil). */
final class Links
{
    public static function normalize(string $raw): ?string
    {
        $s = trim($raw);
        if ($s === '' || preg_match('/\s/u', $s)) {
            return null;
        }
        if (preg_match('/^@([A-Za-z][A-Za-z0-9_]{3,31})$/', $s, $m)) {
            return 'https://t.me/' . $m[1];
        }
        if (preg_match('#^(?:https?://)?(?:www\.)?(t\.me|telegram\.me)/([A-Za-z0-9_+/?=&%.-]+)$#i', $s, $m)) {
            return 'https://t.me/' . $m[2];
        }
        if (preg_match('#^https?://#i', $s)) {
            $ok = filter_var($s, FILTER_VALIDATE_URL);
            return $ok && preg_match('#^https?://[^/]+\.[^/]+#i', $s) ? $s : null;
        }
        if (preg_match('#^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}(/\S*)?$#', $s)) {
            return 'https://' . $s;
        }
        return null;
    }

    public const MAX_ROWS = 8;
    public const MAX_PER_ROW = 3;

    /**
     * Bir nechta tugma: har qator — yangi qator tugmalar; bir qatorda bir nechta tugma « | » bilan:
     *   Sayt - sayt.uz | Kanal - @kanal
     *   Batafsil - t.me/xabar
     * Eski «Matn | havola» (bitta tugma) shakli ham ishlaydi. Natija: [[[matn, url], ...], ...] yoki null.
     * @return array<int, array<int, array{0:string,1:string}>>|null
     */
    public static function parseButtons(string $input): ?array
    {
        $rows = [];
        foreach (preg_split('/\R/u', trim($input)) ?: [] as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $one = self::parseButton($line);
            $parts = preg_split('/\s*\|\s*/u', $line) ?: [];
            $row = [];
            // bir nechta «matn - havola» bo'lsa — bir qatorda bir nechta tugma, aks holda bitta tugma
            if (count($parts) > 1 && count(array_filter($parts, static function ($x) {
                return preg_match('/\s[-—–]\s/u', $x) === 1;
            })) === count($parts)) {
                foreach ($parts as $part) {
                    $b = self::parseButton($part);
                    if ($b === null) {
                        return null;
                    }
                    $row[] = $b;
                }
            } elseif ($one !== null) {
                $row[] = $one;
            } else {
                return null;
            }
            if (count($row) > self::MAX_PER_ROW) {
                return null;
            }
            $rows[] = $row;
        }
        return $rows && count($rows) <= self::MAX_ROWS ? $rows : null;
    }

    /**
     * Tashqaridan (Mini App) kelgan tugmalar: [[{t,u}|[t,u], ...], ...] -> tekshirilgan [[[matn, url]]] yoki null (xato) / [] (bo'sh).
     * @return array<int, array<int, array{0:string,1:string}>>|null
     */
    public static function cleanButtons($raw): ?array
    {
        if (!is_array($raw)) {
            return [];
        }
        $rows = [];
        foreach (array_slice($raw, 0, self::MAX_ROWS + 1) as $r) {
            if (!is_array($r)) {
                return null;
            }
            $row = [];
            foreach ($r as $b) {
                $t = is_array($b) ? trim((string) ($b['t'] ?? $b[0] ?? '')) : '';
                $u = is_array($b) ? trim((string) ($b['u'] ?? $b[1] ?? '')) : '';
                if ($t === '' && $u === '') {
                    continue;
                }
                $url = self::normalize($u);
                if ($t === '' || mb_strlen($t) > 64 || $url === null) {
                    return null;
                }
                $row[] = [$t, $url];
            }
            if (count($row) > self::MAX_PER_ROW) {
                return null;
            }
            if ($row) {
                $rows[] = $row;
            }
        }
        return count($rows) <= self::MAX_ROWS ? $rows : null;
    }

    /** "Matn - havola" yoki "Matn | havola" -> [matn, url]. */
    public static function parseButton(string $input): ?array
    {
        $parts = preg_split('/\s+[-|—–]\s+|\s*\|\s*/u', trim($input), 2);
        if (!$parts || count($parts) !== 2) {
            return null;
        }
        $text = trim($parts[0]);
        $url = self::normalize($parts[1]);
        if ($text === '' || mb_strlen($text) > 64 || $url === null) {
            return null;
        }
        return [$text, $url];
    }
}
