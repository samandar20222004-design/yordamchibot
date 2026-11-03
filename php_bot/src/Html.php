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
}
