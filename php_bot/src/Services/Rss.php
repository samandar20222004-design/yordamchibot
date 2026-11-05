<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\Html;

/**
 * 📰 RSS/Atom lentasini xavfsiz yuklab olish va o'qish.
 *  - faqat http/https; manzil ichki tarmoqqa (127.0.0.1, 10.x, 192.168.x, 169.254.x, ::1 …) qarasa — rad (SSRF);
 *  - DNS javobi curl'ga mahkamlanadi (CURLOPT_RESOLVE) — so'rov paytida boshqa IP'ga almashtirib bo'lmaydi;
 *  - yo'naltirish (redirect) qo'lda, ko'pi bilan 3 marta, har birida qayta tekshiriladi;
 *  - hajm 2 MB, vaqt 10 s; XML'da DOCTYPE/ENTITY bo'lsa rad (XXE va «billion laughs»).
 */
final class Rss
{
    public const MAX_BYTES = 2097152;
    public const TIMEOUT = 10;
    public const MAX_REDIRECTS = 3;

    /** @var callable|null (string $url, string $ip): array{status:int, body:string, location:?string} — testlar uchun */
    private $fetcher;
    /** @var callable|null (string $host): string[] — testlar uchun DNS */
    private $resolver;

    public function __construct(?callable $fetcher = null, ?callable $resolver = null)
    {
        $this->fetcher = $fetcher;
        $this->resolver = $resolver;
    }

    /** Foydalanuvchi yozgan manzilni tozalash: «sayt.uz/feed» -> «https://sayt.uz/feed». null — yaroqsiz. */
    public static function normalizeUrl(string $raw): ?string
    {
        $u = trim($raw);
        if ($u === '' || strlen($u) > 500 || preg_match('/\s/', $u)) {
            return null;
        }
        if (!preg_match('#^https?://#i', $u)) {
            if (preg_match('#^[a-z][a-z0-9+.-]*:#i', $u) && !preg_match('#^[^/:]+:\d+(/|$)#', $u)) {
                return null; // ftp:, file:, javascript: va h.k.
            }
            $u = 'https://' . $u;
        }
        $p = parse_url($u);
        if (!is_array($p) || empty($p['host']) || !in_array(strtolower((string) ($p['scheme'] ?? '')), ['http', 'https'], true)
            || isset($p['user']) || isset($p['pass'])) {
            return null;
        }
        if (isset($p['port']) && !in_array((int) $p['port'], [80, 443, 8080, 8443], true)) {
            return null;
        }
        return $u;
    }

    /** IP ommaviy internetdami (xususiy, lokal, zaxira diapazonlar rad). */
    public static function publicIp(string $ip): bool
    {
        return filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE) !== false
            && strpos($ip, '100.64.') !== 0 && $ip !== '0.0.0.0';
    }

    /** @return string[] */
    private function resolve(string $host): array
    {
        if ($this->resolver !== null) {
            return (array) ($this->resolver)($host);
        }
        if (filter_var($host, FILTER_VALIDATE_IP)) {
            return [$host];
        }
        $ips = [];
        foreach ((array) @dns_get_record($host, DNS_A | DNS_AAAA) as $r) {
            if (!empty($r['ip'])) {
                $ips[] = (string) $r['ip'];
            }
            if (!empty($r['ipv6'])) {
                $ips[] = (string) $r['ipv6'];
            }
        }
        if (!$ips) {
            $v4 = @gethostbynamel($host);
            $ips = is_array($v4) ? $v4 : [];
        }
        return $ips;
    }

    /**
     * Lentani yuklab, o'qiydi.
     * @return array{ok:bool, error?:string, title?:string, items?:array<int, array{id:string,title:string,link:string,summary:string}>}
     *   error: bad_url | blocked | fetch | too_big | parse | empty
     */
    public function load(string $url): array
    {
        $url = self::normalizeUrl($url);
        if ($url === null) {
            return ['ok' => false, 'error' => 'bad_url'];
        }
        for ($i = 0; $i <= self::MAX_REDIRECTS; $i++) {
            $p = parse_url($url);
            $host = strtolower(trim((string) ($p['host'] ?? ''), '[]'));
            $ips = $this->resolve($host);
            if (!$ips) {
                return ['ok' => false, 'error' => 'fetch'];
            }
            foreach ($ips as $ip) {
                if (!self::publicIp($ip)) {
                    return ['ok' => false, 'error' => 'blocked'];
                }
            }
            $r = $this->fetch($url, $ips[0]);
            if ($r['status'] >= 300 && $r['status'] < 400 && !empty($r['location'])) {
                $next = self::absolute((string) $r['location'], $url);
                if ($next === null) {
                    return ['ok' => false, 'error' => 'fetch'];
                }
                $url = $next;
                continue;
            }
            if ($r['status'] === -1) {
                return ['ok' => false, 'error' => 'too_big'];
            }
            if ($r['status'] !== 200 || $r['body'] === '') {
                return ['ok' => false, 'error' => 'fetch'];
            }
            return self::parse($r['body']);
        }
        return ['ok' => false, 'error' => 'fetch'];
    }

    private static function absolute(string $loc, string $base): ?string
    {
        if (preg_match('#^https?://#i', $loc)) {
            return self::normalizeUrl($loc);
        }
        $b = parse_url($base);
        if (!is_array($b) || strpos($loc, '//') === 0) {
            return null;
        }
        $root = $b['scheme'] . '://' . $b['host'] . (isset($b['port']) ? ':' . $b['port'] : '');
        return self::normalizeUrl($loc !== '' && $loc[0] === '/' ? $root . $loc : $root . '/' . ltrim($loc, '/'));
    }

    /** @return array{status:int, body:string, location:?string} status -1 — hajm katta */
    private function fetch(string $url, string $ip): array
    {
        if ($this->fetcher !== null) {
            return ($this->fetcher)($url, $ip);
        }
        $p = parse_url($url);
        $port = (int) ($p['port'] ?? (strtolower((string) $p['scheme']) === 'https' ? 443 : 80));
        $body = '';
        $tooBig = false;
        $location = null;
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => false,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_TIMEOUT => self::TIMEOUT,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_RESOLVE => [$p['host'] . ':' . $port . ':' . (strpos($ip, ':') !== false ? '[' . $ip . ']' : $ip)],
            CURLOPT_USERAGENT => 'PostAssistBot/1.0 (+RSS)',
            CURLOPT_HTTPHEADER => ['Accept: application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5'],
            CURLOPT_ENCODING => '',
            CURLOPT_HEADERFUNCTION => static function ($c, string $h) use (&$location): int {
                if (stripos($h, 'Location:') === 0) {
                    $location = trim(substr($h, 9));
                }
                return strlen($h);
            },
            CURLOPT_WRITEFUNCTION => static function ($c, string $chunk) use (&$body, &$tooBig): int {
                if (strlen($body) + strlen($chunk) > self::MAX_BYTES) {
                    $tooBig = true;
                    return 0; // uzib qo'yish
                }
                $body .= $chunk;
                return strlen($chunk);
            },
        ]);
        curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return ['status' => $tooBig ? -1 : $status, 'body' => $body, 'location' => $location];
    }

    /** RSS 2.0 / RSS 1.0 / Atom. Elementlar lentadagi tartibda (odatda yangisi birinchi). */
    public static function parse(string $xml): array
    {
        if (stripos($xml, '<!DOCTYPE') !== false || stripos($xml, '<!ENTITY') !== false) {
            return ['ok' => false, 'error' => 'parse'];
        }
        $prev = libxml_use_internal_errors(true);
        $doc = simplexml_load_string($xml, 'SimpleXMLElement', LIBXML_NONET | LIBXML_NOCDATA);
        libxml_clear_errors();
        libxml_use_internal_errors($prev);
        if ($doc === false) {
            return ['ok' => false, 'error' => 'parse'];
        }
        $items = [];
        $title = '';
        $root = strtolower($doc->getName());
        if ($root === 'feed') { // Atom
            $title = (string) $doc->title;
            foreach ($doc->entry as $e) {
                $link = '';
                foreach ($e->link as $l) {
                    $rel = (string) ($l['rel'] ?? 'alternate');
                    if ($rel === 'alternate' || $link === '') {
                        $link = (string) $l['href'];
                    }
                }
                $items[] = self::item((string) $e->id, (string) $e->title, $link, (string) ($e->summary !== null && (string) $e->summary !== '' ? $e->summary : $e->content));
            }
        } else { // RSS 2.0 (rss/channel/item) yoki RSS 1.0 (rdf:RDF/item)
            $chan = isset($doc->channel) ? $doc->channel : $doc;
            $title = (string) $chan->title;
            $list = isset($chan->item) && count($chan->item) > 0 ? $chan->item : $doc->item;
            foreach ($list as $it) {
                $items[] = self::item((string) $it->guid, (string) $it->title, (string) $it->link, (string) $it->description);
            }
        }
        $items = array_values(array_filter($items, static function ($it) {
            return $it['title'] !== '' || $it['link'] !== '';
        }));
        if (!$items) {
            return ['ok' => false, 'error' => 'empty'];
        }
        return ['ok' => true, 'title' => mb_substr(trim(Html::plain($title)), 0, 120), 'items' => array_slice($items, 0, 50)];
    }

    private static function item(string $id, string $title, string $link, string $summary): array
    {
        $link = trim($link);
        if ($link !== '' && !preg_match('#^https?://#i', $link)) {
            $link = '';
        }
        $plainTitle = trim((string) preg_replace('/\s+/u', ' ', html_entity_decode(strip_tags($title), ENT_QUOTES | ENT_HTML5, 'UTF-8')));
        $plainSum = trim((string) preg_replace('/\s+/u', ' ', html_entity_decode(strip_tags($summary), ENT_QUOTES | ENT_HTML5, 'UTF-8')));
        $key = trim($id) !== '' ? trim($id) : ($link !== '' ? $link : $plainTitle);
        return ['id' => sha1($key), 'title' => mb_substr($plainTitle, 0, 250), 'link' => mb_substr($link, 0, 1000), 'summary' => $plainSum];
    }

    /** Kanal posti (HTML): qalin sarlavha, qisqa mazmun, havola. */
    public static function postHtml(array $it, int $summaryMax = 300): string
    {
        $s = $it['summary'];
        if (mb_strlen($s) > $summaryMax) {
            $s = rtrim(mb_substr($s, 0, $summaryMax - 1)) . '…';
        }
        $out = $it['title'] !== '' ? '<b>' . Html::e($it['title']) . '</b>' : '';
        if ($s !== '' && $s !== $it['title']) {
            $out .= ($out !== '' ? "\n\n" : '') . Html::e($s);
        }
        if ($it['link'] !== '') {
            $out .= ($out !== '' ? "\n\n" : '') . '🔗 <a href="' . Html::e($it['link']) . '">' . Html::e(self::shortLink($it['link'])) . '</a>';
        }
        return $out;
    }

    private static function shortLink(string $url): string
    {
        $h = (string) parse_url($url, PHP_URL_HOST);
        return $h !== '' ? preg_replace('/^www\./', '', $h) : $url;
    }

    /**
     * Yangi elementlar: oxirgi ko'rilgandan keyingilari (eskisidan yangisiga), ko'pi bilan $max.
     * Oxirgisi lentada topilmasa (lenta almashgan) — faqat eng yangisi (eskilar bilan kanal to'lmaydi).
     * @return array<int, array>
     */
    public static function fresh(array $items, ?string $lastId, int $max = 3): array
    {
        if ($lastId === null || $lastId === '') {
            return [];
        }
        $new = [];
        foreach ($items as $it) {
            if ($it['id'] === $lastId) {
                return array_reverse(array_slice($new, 0, $max));
            }
            $new[] = $it;
        }
        return $items ? [$items[0]] : [];
    }
}
