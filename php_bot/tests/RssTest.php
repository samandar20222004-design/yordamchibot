<?php
// 14-bosqich: RSS avtopost (FeaturesTest.php dan keyin).
declare(strict_types=1);

use PostAssist\Services\Plans;
use PostAssist\Services\Rss;
use PostAssist\Services\Scheduler;

T::section('Z. RSS avtopost');
T::eq('manzil: sxemasiz -> https', Rss::normalizeUrl('sayt.uz/feed'), 'https://sayt.uz/feed');
T::eq('manzil: ftp rad', Rss::normalizeUrl('ftp://x.uz/f'), null);
T::eq('manzil: login:parol rad', Rss::normalizeUrl('https://a:b@x.uz/f'), null);
T::eq('manzil: g\'alati port rad', Rss::normalizeUrl('https://x.uz:22/f'), null);
T::eq('IP: ichki tarmoqlar rad, ommaviy ruxsat', [Rss::publicIp('127.0.0.1'), Rss::publicIp('10.1.2.3'), Rss::publicIp('192.168.1.1'), Rss::publicIp('169.254.169.254'),
    Rss::publicIp('::1'), Rss::publicIp('100.64.0.1'), Rss::publicIp('8.8.8.8')], [false, false, false, false, false, false, true]);
$rssXml = static function (array $items, string $title = 'Texno blog'): string {
    $x = '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>' . $title . '</title>';
    foreach ($items as [$g, $t]) {
        $x .= '<item><title>' . $t . '</title><link>https://blog.example.uz/' . $g . '</link><guid>' . $g . '</guid><description><![CDATA[<p>' . $t . ' haqida <b>batafsil</b> maqola &amp; yangilik</p>]]></description></item>';
    }
    return $x . '</channel></rss>';
};
$p = Rss::parse($rssXml([['a3', 'Uchinchi'], ['a2', 'Ikkinchi'], ['a1', 'Birinchi']]));
T::check('RSS 2.0 o\'qildi: nom, 3 element, HTML tozalandi', $p['ok'] && $p['title'] === 'Texno blog' && count($p['items']) === 3 && $p['items'][0]['title'] === 'Uchinchi'
    && $p['items'][0]['summary'] === 'Uchinchi haqida batafsil maqola & yangilik');
$atom = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Video kanal</title><entry><id>yt:1</id><title>Yangi video</title>'
    . '<link rel="alternate" href="https://www.youtube.com/watch?v=1"/><summary>Qisqa</summary></entry></feed>';
$pa = Rss::parse($atom);
T::check('Atom (YouTube) o\'qildi', $pa['ok'] && $pa['title'] === 'Video kanal' && $pa['items'][0]['link'] === 'https://www.youtube.com/watch?v=1');
T::eq('DOCTYPE/ENTITY (XXE) rad', Rss::parse('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>')['error'] ?? null, 'parse');
T::eq('XML emas — parse', Rss::parse('<html>salom')['error'] ?? null, 'parse');
T::eq('javascript: havola olinmaydi', Rss::parse('<rss><channel><item><title>X</title><link>javascript:alert(1)</link></item></channel></rss>')['items'][0]['link'], '');
$ids = array_column($p['items'], 'id');
T::eq('yangilar: oxirgisidan keyingilar, eskisidan boshlab', array_column(Rss::fresh($p['items'], $ids[2]), 'title'), ['Ikkinchi', 'Uchinchi']);
T::eq('yangi yo\'q', Rss::fresh($p['items'], $ids[0]), []);
T::eq('oxirgisi topilmasa — faqat eng yangisi', array_column(Rss::fresh($p['items'], 'yoq'), 'title'), ['Uchinchi']);
$html = Rss::postHtml(['title' => 'A <b>&', 'summary' => str_repeat('s', 400), 'link' => 'https://www.blog.uz/x?a=1&b="2"']);
T::check('post: sarlavha qalin, xavfsiz, qisqa, havola', strpos($html, '<b>A &lt;b&gt;&amp;</b>') === 0 && strpos($html, '…') !== false
    && strpos($html, 'href="https://www.blog.uz/x?a=1&amp;b=&quot;2&quot;"') !== false && strpos($html, '>blog.uz</a>') !== false);

// yuklash: soxta tarmoq
$net = ['https://blog.example.uz/feed' => [200, $rssXml([['a1', 'Birinchi']]), null]];
$dns = ['blog.example.uz' => ['93.184.216.34'], 'evil.example.uz' => ['127.0.0.1'], 'redir.example.uz' => ['93.184.216.35']];
$fetches = [];
$app->rssClient = new Rss(static function (string $url, string $ip) use (&$net, &$fetches): array {
    $fetches[] = [$url, $ip];
    $r = $net[$url] ?? [404, '', null];
    return ['status' => $r[0], 'body' => $r[1], 'location' => $r[2]];
}, static function (string $host) use (&$dns): array {
    return $dns[$host] ?? [];
});
T::eq('ichki IP\'ga qaragan domen rad (SSRF)', $app->rssClient->load('https://evil.example.uz/feed')['error'] ?? null, 'blocked');
$net['https://redir.example.uz/feed'] = [302, '', 'https://evil.example.uz/x'];
T::eq('ichki manzilga yo\'naltirish rad', $app->rssClient->load('https://redir.example.uz/feed')['error'] ?? null, 'blocked');
$net['https://redir.example.uz/ok'] = [301, '', '/feed2'];
$net['https://redir.example.uz/feed2'] = [200, $rssXml([['r1', 'R']]), null];
T::eq('oddiy yo\'naltirish kuzatiladi', $app->rssClient->load('https://redir.example.uz/ok')['ok'] ?? null, true);
T::eq('DNS IP mahkamlanadi', end($fetches)[1], '93.184.216.35');
$net['https://redir.example.uz/big'] = [-1, '', null];
T::eq('katta lenta rad', $app->rssClient->load('https://redir.example.uz/big')['error'] ?? null, 'too_big');
T::eq('404 — fetch', $app->rssClient->load('https://blog.example.uz/none')['error'] ?? null, 'fetch');

// bot
$clock = new DateTimeImmutable('2027-04-01 10:00:00', new DateTimeZone('UTC'));
$RU = 9950;
$RC = -1009950;
$text($RU, '/start');
$fake->chats[$RC] = ['id' => $RC, 'type' => 'channel', 'title' => 'Blog kanali'];
$fake->members["{$RC}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$app->channels->connect($RU, $RC, 'Blog kanali', null, 0);
$kbR = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$toChan = static function () use ($fake, $RC): array {
    return array_values(array_filter($fake->of('sendMessage'), function ($p) use ($RC) { return (int) $p['chat_id'] === $RC; }));
};
$text($RU, '📢 Kanallarim');
T::check('kanallar ekranida «📰 RSS avtopost»', strpos($kbR(), 'rss:show') !== false);
$text($RU, '/rss');
T::check('bepul: PRO/ULTRA kerak', strpos($fake->lastText(), 'PRO') !== false && strpos($kbR(), 'rss:new') === false && strpos($kbR(), 'pl:show') !== false);
Plans::grant($db, $RU, 'pro', 30, $clock);
$press($RU, 'rss:show');
$press($RU, 'rss:new');
T::eq('bitta kanal: darhol manzil so\'raladi', $app->states->get($RU)['state'] ?? null, 'rss_url');
$text($RU, 'evil.example.uz/feed');
T::check('ichki tarmoq: rad, sabab aytiladi', strpos($fake->lastText(), 'ichki tarmoq') !== false && (int) $db->value('SELECT COUNT(*) FROM rss_feeds WHERE user_id = ?', [$RU]) === 0);
$text($RU, 'blog.example.uz/none');
T::check('ochilmaydigan lenta: rad', strpos($fake->lastText(), 'yuklab bo\'lmadi') !== false);
$text($RU, 'blog.example.uz/feed');
$FID = (int) $db->value('SELECT id FROM rss_feeds WHERE user_id = ?', [$RU]);
T::check('lenta ulandi, eski maqola yuborilmadi', $FID > 0 && strpos($fake->texts(), 'Lenta ulandi') !== false && strpos($fake->texts(), 'Texno blog') !== false && count($toChan()) === 0
    && $app->states->get($RU) === null);
$press($RU, 'rss:new');
$text($RU, 'https://blog.example.uz/feed');
T::check('takror ulash rad', strpos($fake->lastText(), 'allaqachon') !== false);
$sched = new Scheduler($app, static function (int $us): void {
});
$fake->reset();
$sched->run(5);
T::eq('15 daqiqa o\'tmaguncha tekshirilmaydi', count($toChan()), 0);
$net['https://blog.example.uz/feed'] = [200, $rssXml([['a3', 'Uchinchi'], ['a2', 'Ikkinchi'], ['a1', 'Birinchi']]), null];
$clock = $clock->modify('+16 minutes');
$fake->reset();
$sched->run(5);
$posts = $toChan();
T::check('cron: 2 ta yangi maqola, eskisidan boshlab', count($posts) === 2 && strpos((string) $posts[0]['text'], 'Ikkinchi') !== false && strpos((string) $posts[1]['text'], 'Uchinchi') !== false
    && strpos((string) $posts[0]['text'], 'blog.example.uz') !== false);
T::eq('PRO: nishonsiz', strpos((string) $posts[0]['text'], '@PostAssistrobot'), false);
$fake->reset();
$sched->run(5);
T::eq('o\'sha daqiqada qayta yuborilmaydi', count($toChan()), 0);
$clock = $clock->modify('+16 minutes');
$fake->reset();
$sched->run(5);
T::eq('yangi maqola yo\'q — post yo\'q', count($toChan()), 0);
$many = [];
for ($i = 9; $i >= 1; $i--) {
    $many[] = ['b' . $i, 'Yangi ' . $i];
}
$many[] = ['a3', 'Uchinchi'];
$net['https://blog.example.uz/feed'] = [200, $rssXml($many), null];
$clock = $clock->modify('+16 minutes');
$fake->reset();
$sched->run(5);
$posts = $toChan();
T::check('ko\'p yangi: bir tekshiruvda 3 ta (eng yangilari), qolgani tashlanadi', count($posts) === 3 && strpos((string) $posts[2]['text'], 'Yangi 9') !== false);
T::eq('hisoblagich', (int) $db->value('SELECT posted FROM rss_feeds WHERE id = ?', [$FID]), 5);
// xatolar
$net['https://blog.example.uz/feed'] = [500, '', null];
for ($i = 0; $i < 10; $i++) {
    $clock = $clock->modify('+16 minutes');
    $fake->reset();
    $sched->run(5);
}
T::check('10 marta xato: lenta to\'xtadi, egasiga xabar', (int) $db->value('SELECT active FROM rss_feeds WHERE id = ?', [$FID]) === 0 && strpos($fake->texts(), 'to\'xtatildi') !== false);
$net['https://blog.example.uz/feed'] = [200, $rssXml([['c1', 'Tiklandi']]), null];
$press($RU, 'rss:tg:' . $FID);
T::eq('qayta yoqildi', (int) $db->value('SELECT active FROM rss_feeds WHERE id = ?', [$FID]), 1);
$press($RU, 'rss:last:' . $FID);
T::check('«📤 Oxirgisini hozir»: eng yangisi kanalga', count($toChan()) === 1 && strpos((string) $toChan()[0]['text'], 'Tiklandi') !== false && strpos($fake->lastText(), 'Yuborildi') !== false);
$press($ADMIN, 'rss:v:' . $FID);
T::check('begona lenta ko\'rinmaydi', strpos($fake->lastText(), 'blog.example.uz') === false);
$press($ADMIN, 'rss:dok:' . $FID);
T::eq('begona odam o\'chira olmaydi', (int) $db->value('SELECT COUNT(*) FROM rss_feeds WHERE id = ?', [$FID]), 1);
$db->exec("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL WHERE user_id = ?", [$RU]);
$clock = $clock->modify('+20 minutes');
$fake->reset();
$sched->run(5);
T::check('tarif tugadi: lenta to\'xtadi', (int) $db->value('SELECT active FROM rss_feeds WHERE id = ?', [$FID]) === 0 && count($toChan()) === 0);
$press($RU, 'rss:del:' . $FID);
$press($RU, 'rss:dok:' . $FID);
T::eq('o\'chirildi', (int) $db->value('SELECT COUNT(*) FROM rss_feeds WHERE id = ?', [$FID]), 0);
T::eq('limitlar: free 0, pro 3, ultra 10, admin 20', [$app->rssLimit($AX), $app->rssLimit($ADMIN)], [0, 20]);
$app->rssClient = new Rss();
