<?php
declare(strict_types=1);

namespace PostAssist\Services;

/**
 * 🛡 Reklama birjasi: firibgarlikdan himoya (Python `services/market_safety.py` bilan bir xil qoidalar).
 *  - TO'SISH (xabar umuman yuborilmaydi): karta raqami, kripto hamyon; birinchi xabarda yoki yangi hisobdan (2 kundan yosh) havola;
 *  - BELGI (yuboriladi, oluvchiga ⚠️): oldindan to'lov, shoshiltirish, «kafolatlangan daromad», havola.
 * Ataylab ehtiyotkor: yolg'on ogohlantirish — kichik zarar, o'tkazib yuborilgan firibgarlik — katta.
 */
final class MarketSafety
{
    public const NEW_ACCOUNT_DAYS = 2;
    private const CARD = '/(?<!\d)(?:\d[ \-]?){15,19}(?!\d)/u';
    private const WALLET = '/\b(?:T[1-9A-HJ-NP-Za-km-z]{33}|0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,60}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b/';
    private const LINK = '/(?:https?:\/\/|www\.|t\.me\/|telegram\.me\/|bit\.ly|tinyurl|\b[a-z0-9-]{2,}\.(?:com|ru|uz|org|net|io|me|xyz|top|cc|ly|site|online|link)\b)/u';
    private const PREPAY = ["oldindan to'lov", 'oldindan tolov', 'oldindan pul', 'avans', 'garov', 'zaklad', 'kafolat puli', "pul o'tkazing",
        'pul tashlang', 'kartaga tashlang', 'kartamga', "to'lov qiling", 'predoplat', 'предоплат', 'залог', 'переведите',
        'скиньте на карту', 'перевод на карту', 'prepay', 'advance payment', 'deposit', 'send money', 'wire transfer', 'transfer to my card'];
    private const PRESSURE = ['shoshiling', 'hoziroq', "tezroq to'lang", 'oxirgi imkoniyat', 'faqat bugun', 'срочно', 'прямо сейчас', 'последний шанс',
        'только сегодня', 'urgent', 'right now', 'last chance', 'act now'];
    private const SCAM = ['100% kafolat', 'kafolatlangan daromad', 'kafolatlangan foyda', 'pul ishlash', 'tez boyish', 'investitsiya', 'kripto',
        'usdt', 'crypto', 'bitcoin', 'гарантированный доход', 'гарантия дохода', 'инвестиц', 'быстрый заработок', 'криптовалют',
        'guaranteed income', 'guaranteed profit', 'get rich', 'free money', 'like bosish', 'лайки'];

    public static function normalize(string $text): string
    {
        $t = str_replace(["\u{200B}", "\u{200C}", "\u{200D}", "\u{2060}", "\u{FEFF}"], '', $text);
        $t = str_replace(['ʻ', 'ʼ', '‘', '’', '`', '´'], "'", $t);
        return mb_strtolower($t);
    }

    /** Bir xil matn spamini aniqlash uchun xesh. */
    public static function dupHash(string $text): string
    {
        return sha1(trim((string) preg_replace('/\s+/u', ' ', self::normalize($text))));
    }

    /**
     * @return array{ok:bool, reason:?string, flags:array<int,string>} reason: card | wallet | link
     */
    public static function assess(string $text, bool $firstMessage = false, ?float $accountAgeDays = null, bool $ownerSender = false): array
    {
        $norm = self::normalize($text);
        $flags = [];
        $reason = null;
        if (preg_match(self::CARD, $norm)) {
            $reason = 'card';
        } elseif (preg_match(self::WALLET, $text)) {
            $reason = 'wallet';
        }
        if (preg_match(self::LINK, $norm)) {
            $newAccount = $accountAgeDays !== null && $accountAgeDays < self::NEW_ACCOUNT_DAYS;
            if ($reason === null && !$ownerSender && ($firstMessage || $newAccount)) {
                $reason = 'link';
            } else {
                $flags[] = 'link';
            }
        }
        foreach (['prepay' => self::PREPAY, 'pressure' => self::PRESSURE, 'scam' => self::SCAM] as $flag => $words) {
            foreach ($words as $w) {
                if (mb_strpos($norm, $w) !== false) {
                    $flags[] = $flag;
                    break;
                }
            }
        }
        return ['ok' => $reason === null, 'reason' => $reason, 'flags' => array_values(array_unique($flags))];
    }
}
