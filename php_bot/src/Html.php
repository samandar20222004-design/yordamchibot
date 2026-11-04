<?php
declare(strict_types=1);

namespace PostAssist;

/** HTML yordamchilari: escape, Telegram entities -> HTML, ko'rinadigan uzunlik (UTF-16). */
final class Html
{
    public static function e(?string $s): string
    {
        return htmlspecialchars((string) $s, ENT_QUOTES | ENT_SUBSTITUTE | ENT_HTML5, 'UTF-8');
    }

    /** Telegram uzunlikni UTF-16 birliklarida sanaydi (emoji = 2). */
    public static function utf16Len(string $s): int
    {
        return intdiv(strlen(mb_convert_encoding($s, 'UTF-16LE', 'UTF-8')), 2);
    }

    /** HTML teglarisiz ko'rinadigan matn. */
    public static function plain(string $html): string
    {
        return html_entity_decode(strip_tags($html), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }

    /**
     * Xabar matni + entities -> Telegram HTML (parse_mode=HTML). Formatlash saqlanadi, qolgan matn escape qilinadi.
     * @param array<int, array<string, mixed>> $entities
     */
    public static function fromEntities(string $text, array $entities): string
    {
        if ($text === '') {
            return '';
        }
        $u = mb_convert_encoding($text, 'UTF-16LE', 'UTF-8');
        $total = intdiv(strlen($u), 2);
        $opens = [];
        $closes = [];
        foreach ($entities as $i => $en) {
            $off = (int) ($en['offset'] ?? 0);
            $len = (int) ($en['length'] ?? 0);
            if ($len <= 0 || $off < 0 || $off + $len > $total) {
                continue;
            }
            $tags = self::tags($en);
            if ($tags === null) {
                continue;
            }
            $opens[$off][] = ['end' => $off + $len, 'i' => $i, 'open' => $tags[0], 'close' => $tags[1]];
        }
        $points = [0, $total];
        foreach ($opens as $off => $list) {
            $points[] = $off;
            foreach ($list as $o) {
                $points[] = $o['end'];
            }
        }
        $points = array_values(array_unique($points));
        sort($points);
        $out = '';
        $stack = [];
        $prev = 0;
        foreach ($points as $p) {
            if ($p > $prev) {
                $out .= self::e(mb_convert_encoding(substr($u, $prev * 2, ($p - $prev) * 2), 'UTF-8', 'UTF-16LE'));
            }
            // shu nuqtada tugaydiganlarni yopish (ichkaridan tashqariga); ustma-ust bo'lsa qayta ochiladi
            $reopen = [];
            while ($stack && self::hasEndingAt($stack, $p)) {
                $top = array_pop($stack);
                $out .= $top['close'];
                if ($top['end'] !== $p) {
                    $reopen[] = $top;
                }
            }
            foreach (array_reverse($reopen) as $r) {
                $out .= $r['open'];
                $stack[] = $r;
            }
            if (isset($opens[$p])) {
                $list = $opens[$p];
                usort($list, static fn ($a, $b) => $b['end'] <=> $a['end'] ?: $a['i'] <=> $b['i']);
                foreach ($list as $o) {
                    $out .= $o['open'];
                    $stack[] = $o;
                }
            }
            $prev = $p;
        }
        while ($stack) {
            $out .= array_pop($stack)['close'];
        }
        return $out;
    }

    private static function hasEndingAt(array $stack, int $p): bool
    {
        foreach ($stack as $s) {
            if ($s['end'] === $p) {
                return true;
            }
        }
        return false;
    }

    /** @return array{0:string,1:string}|null */
    private static function tags(array $en): ?array
    {
        switch ($en['type'] ?? '') {
            case 'bold': return ['<b>', '</b>'];
            case 'italic': return ['<i>', '</i>'];
            case 'underline': return ['<u>', '</u>'];
            case 'strikethrough': return ['<s>', '</s>'];
            case 'spoiler': return ['<tg-spoiler>', '</tg-spoiler>'];
            case 'code': return ['<code>', '</code>'];
            case 'blockquote': return ['<blockquote>', '</blockquote>'];
            case 'expandable_blockquote': return ['<blockquote expandable>', '</blockquote>'];
            case 'pre':
                $lang = (string) ($en['language'] ?? '');
                return $lang !== '' && preg_match('/^[A-Za-z0-9_+#.-]{1,32}$/', $lang)
                    ? ['<pre><code class="language-' . $lang . '">', '</code></pre>'] : ['<pre>', '</pre>'];
            case 'text_link':
                $url = (string) ($en['url'] ?? '');
                return $url !== '' ? ['<a href="' . self::e($url) . '">', '</a>'] : null;
            case 'text_mention':
                $id = (int) ($en['user']['id'] ?? 0);
                return $id > 0 ? ['<a href="tg://user?id=' . $id . '">', '</a>'] : null;
            case 'custom_emoji':
                $id = (string) ($en['custom_emoji_id'] ?? '');
                return preg_match('/^\d{1,30}$/', $id) ? ['<tg-emoji emoji-id="' . $id . '">', '</tg-emoji>'] : null;
        }
        return null;
    }

    /**
     * AI javobini xavfsiz Telegram HTML ga aylantiradi: faqat b/i/u/s/code/pre/blockquote/tg-spoiler va to'g'ri havolali <a>
     * qoladi, qolgan hammasi escape qilinadi; teglar juftlanadi (yopilmagani yopiladi). Markdown (**qalin**, *kursiv*, # sarlavha,
     * ``` blok) ham tushuniladi — ba'zi modellar HTML o'rniga markdown qaytaradi.
     */
    public static function sanitize(string $raw): string
    {
        $s = str_replace(["\r\n", "\r"], "\n", trim($raw));
        $s = (string) preg_replace('/^```[a-zA-Z]*\n?|\n?```$/m', '', $s);
        $s = (string) preg_replace('/^#{1,6}\s+(.+)$/mu', '**$1**', $s);
        $s = (string) preg_replace('/\*\*(.+?)\*\*/us', '<b>$1</b>', $s);
        $s = (string) preg_replace('/(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])/u', '<i>$1</i>', $s);
        $map = ['b' => 'b', 'strong' => 'b', 'i' => 'i', 'em' => 'i', 'u' => 'u', 'ins' => 'u', 's' => 's', 'strike' => 's', 'del' => 's',
            'code' => 'code', 'pre' => 'pre', 'blockquote' => 'blockquote', 'tg-spoiler' => 'tg-spoiler', 'a' => 'a'];
        $out = '';
        $stack = [];
        $pos = 0;
        $re = '#<(/?)([a-zA-Z-]+)((?:\s+[a-zA-Z-]+\s*=\s*(?:"[^"]*"|\'[^\']*\'))*)\s*/?>|<br\s*/?>#';
        if (preg_match_all($re, $s, $mm, PREG_OFFSET_CAPTURE | PREG_SET_ORDER)) {
            foreach ($mm as $m) {
                $out .= self::e(html_entity_decode(substr($s, $pos, $m[0][1] - $pos), ENT_QUOTES | ENT_HTML5, 'UTF-8'));
                $pos = $m[0][1] + strlen($m[0][0]);
                if (stripos($m[0][0], '<br') === 0) {
                    $out .= "\n";
                    continue;
                }
                $tag = $map[strtolower($m[2][0] ?? '')] ?? null;
                if ($tag === null) {
                    continue; // noma'lum teg tashlab yuboriladi (matni qoladi)
                }
                if ($m[1][0] === '/') {
                    $at = array_search($tag, $stack, true);
                    if ($at === false) {
                        continue;
                    }
                    while (count($stack) > $at) {
                        $out .= '</' . array_pop($stack) . '>';
                    }
                    continue;
                }
                if ($tag === 'a') {
                    $url = null;
                    if (preg_match('/href\s*=\s*(?:"([^"]*)"|\'([^\']*)\')/i', (string) $m[3][0], $h)) {
                        $url = Services\Links::normalize(html_entity_decode($h[1] !== '' ? $h[1] : ($h[2] ?? ''), ENT_QUOTES | ENT_HTML5, 'UTF-8'));
                    }
                    if ($url === null) {
                        continue;
                    }
                    $out .= '<a href="' . self::e($url) . '">';
                } else {
                    $out .= '<' . $tag . '>';
                }
                $stack[] = $tag;
            }
        }
        $out .= self::e(html_entity_decode(substr($s, $pos), ENT_QUOTES | ENT_HTML5, 'UTF-8'));
        while ($stack) {
            $out .= '</' . array_pop($stack) . '>';
        }
        // bo'sh teglar va ortiqcha bo'sh qatorlar
        $out = (string) preg_replace('#<(b|i|u|s|code|pre|blockquote|tg-spoiler)></\1>#', '', $out);
        return trim((string) preg_replace("/\n{3,}/", "\n\n", $out));
    }
}
