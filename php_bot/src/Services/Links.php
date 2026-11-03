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
