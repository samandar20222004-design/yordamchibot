<?php
// 6-bosqich: rasmdan va ovozdan post (Phase5Test.php dan keyin).
declare(strict_types=1);

use PostAssist\Config;
use PostAssist\Services\Ai;
use PostAssist\Telegram;

T::section('Q. Rasmdan va ovozdan post (AI Vision / audio)');
$clock = new DateTimeImmutable('2026-12-05 10:00:00', new DateTimeZone('UTC'));
$app->sleeper = static function (int $ms): void {
};
$V = 9300;
$fake->chats[-1009300] = ['id' => -1009300, 'type' => 'channel', 'title' => 'Ovoz kanali'];
$fake->members["-1009300|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["-1009300|{$V}"] = ['status' => 'creator'];
$app->users->upsert($V, 'v', 'Vali', 'uz');
$app->channels->connect($V, -1009300, 'Ovoz kanali', null, 0);
$aiCalls = [];
$aiQueue = [];
$aiT = static function (string $url, array $h, string $body) use (&$aiCalls, &$aiQueue): array {
    $aiCalls[] = [$url, $h, json_decode($body, true)];
    return $aiQueue ? array_shift($aiQueue) : [500, ''];
};
$gem = static function (string $t): array {
    return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => $t]]]]]])];
};
$parts = static function (int $i) use (&$aiCalls): array {
    return $aiCalls[$i][2]['contents'][0]['parts'] ?? [];
};
$downloads = [];
$app->tg->setDownloader(static function (string $url) use (&$downloads): ?string {
    $downloads[] = $url;
    return strpos($url, '.oga') !== false ? 'OggS-fake-audio-bytes' : "\xFF\xD8\xFF\xE0fake-jpeg";
});
$fileOk = static function (string $path, int $size = 1000) use ($fake): void {
    $fake->forced['getFile'] = [['ok' => true, 'result' => ['file_path' => $path, 'file_size' => $size]]];
};

// --- Telegram::fetchFile
$tgF = new Telegram('111:TOKEN', 'https://api.test', $fake);
$tgF->setDownloader(static function (string $u): string {
    return 'DATA:' . $u;
});
$fileOk('photos/a.jpg');
$r = $tgF->fetchFile('FID', 5000);
T::check('fetchFile: baytlar va manzil (token ichida, yo\'l tekshirilgan)', $r !== null && $r[1] === 'photos/a.jpg' && $r[0] === 'DATA:https://api.test/file/bot111:TOKEN/photos/a.jpg');
$fileOk('photos/a.jpg', 9999999);
T::eq('juda katta fayl (getFile hajmi) rad', $tgF->fetchFile('FID', 5000), null);
$fileOk('../../etc/passwd');
T::eq('xavfli yo\'l rad', $tgF->fetchFile('FID', 5000), null);
$fake->forced['getFile'] = [['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: wrong file_id']];
T::eq('getFile xato: null', $tgF->fetchFile('FID', 5000), null);

// --- Ai: media faqat Gemini
$aiG = new Ai(new Config(['gemini_api_key' => 'GK', 'groq_api_key' => 'QK']), $aiT);
$aiQueue = [$gem('Rasm izohi')];
$r = $aiG->generate('S', 'P', 900, ['mime' => 'image/jpeg', 'data' => 'RAWBYTES']);
$pt = $parts(0);
T::check('media: faqat Gemini, inlineData (base64) va matn', $r['ok'] && $r['provider'] === 'gemini' && count($aiCalls) === 1 && ($pt[0]['inlineData']['mimeType'] ?? '') === 'image/jpeg'
    && ($pt[0]['inlineData']['data'] ?? '') === base64_encode('RAWBYTES') && ($pt[1]['text'] ?? '') === 'P');
$aiCalls = [];
$aiQueue = [[500, '']];
T::check('Gemini yiqilsa media uchun Groq ishlatilmaydi', ($aiG->generate('S', 'P', 900, ['mime' => 'image/jpeg', 'data' => 'x'])['error'] ?? '') === 'failed' && count($aiCalls) === 1);
$aiQ = new Ai(new Config(['groq_api_key' => 'QK']), $aiT);
T::eq('faqat Groq: media uchun provayder yo\'q', [$aiQ->mediaEnabled(), $aiQ->generate('S', 'P', 900, ['mime' => 'a', 'data' => 'b'])['error'] ?? ''], [false, 'disabled']);
T::check('promptlar: rasm (faktlarni o\'ylab topma), ovoz', strpos(Ai::imagePrompt('Yangi mahsulot', 'sales'), 'Yangi mahsulot') !== false && strpos(Ai::imagePrompt('', 'fun'), 'ko\'rinmagan') !== false
    && strpos(Ai::imagePrompt('', 'fun'), 'Muallif izohi') === false && strpos(Ai::voicePrompt('news'), 'Ovozli xabarni') !== false);
T::eq('imageMime', [PostAssist\Handlers\AiHandler::imageMime("\x89PNG\r\n"), PostAssist\Handlers\AiHandler::imageMime('RIFF1234WEBP'), PostAssist\Handlers\AiHandler::imageMime("\xFF\xD8")], ['image/png', 'image/webp', 'image/jpeg']);
$aiCalls = [];

// --- rasm: aqlli qabul -> Vision
$app->ai = new Ai(new Config(['groq_api_key' => 'QK']), $aiT);
$send($V, ['photo' => [['file_id' => 'P_small'], ['file_id' => 'P_BIG', 'file_unique_id' => 'x']]]);
T::check('faqat Groq kaliti (Gemini yo\'q): rasmda «AI bilan» tugmasi yo\'q', strpos($mk($fake->of('sendMessage')[0] ?? []), 'in:ai') === false && strpos($mk($fake->of('sendMessage')[0] ?? []), 'in:post') !== false);
$app->states->clear($V);
$app->ai = new Ai(new Config(['gemini_api_key' => 'GK']), $aiT);
$send($V, ['photo' => [['file_id' => 'P_small'], ['file_id' => 'P_BIG', 'file_unique_id' => 'x']]]);
T::check('Gemini bor: izohsiz rasmda ham «✨ AI bilan» (faqat bosilganda ishlaydi)', strpos($mk($fake->of('sendMessage')[0] ?? []), 'in:ai') !== false && count($aiCalls) === 0);
$press($V, 'in:ai');
T::check('uslub so\'raladi, AI hali chaqirilmadi', strpos($mk($fake->of('sendMessage')[0] ?? []), 'ai:s:sales') !== false && ($app->states->get($V)['data']['photo'] ?? '') === 'P_BIG' && count($aiCalls) === 0);
$used0 = $app->aiUsage->usedOn($V, $app->today());
$fileOk('photos/file_5.jpg');
$aiQueue = [$gem('**Yangi kolleksiya!** 👗 Bahor ruhi.')];
$press($V, 'ai:s:sales');
$ph = $fake->of('sendPhoto')[0] ?? [];
T::check('Vision: rasm yuklandi, Gemini rasm bilan chaqirildi (image/jpeg), preview — rasm + yozilgan izoh', count($downloads) === 1 && strpos($downloads[0], 'photos/file_5.jpg') !== false
    && ($parts(0)[0]['inlineData']['mimeType'] ?? '') === 'image/jpeg' && strpos((string) ($parts(0)[1]['text'] ?? ''), 'rasmga qarab') !== false || strpos((string) ($parts(0)[1]['text'] ?? ''), 'Rasmga qarab') !== false);
T::check('preview: sendPhoto (o\'sha file_id) va <b> izoh, «Boshqa variant»', ($ph['photo'] ?? '') === 'P_BIG' && strpos((string) ($ph['caption'] ?? ''), '<b>Yangi kolleksiya!</b>') !== false && strpos($mk($ph), 'ai:again') !== false);
T::eq('hisob: 1 ta ishlatildi', $app->aiUsage->usedOn($V, $app->today()), $used0 + 1);
$fileOk('photos/file_5.jpg');
$aiQueue = [$gem('Ikkinchi variant (rasm)')];
$press($V, 'ai:again');
T::check('«Boshqa variant»: rasm qayta yuboriladi, izoh almashadi', count($aiCalls) === 2 && count($downloads) === 2 && strpos($fake->texts(), 'Ikkinchi variant') !== false
    && ($app->states->get($V)['data']['draft']['file_id'] ?? '') === 'P_BIG');
// yuklash muvaffaqiyatsiz
$usedBefore = $app->aiUsage->usedOn($V, $app->today());
$calls0 = count($aiCalls);
$fake->forced['getFile'] = [['ok' => false, 'error_code' => 400, 'description' => 'file is too big']];
$press($V, 'ai:again');
T::check('fayl yuklanmasa: AI chaqirilmaydi, limit sarflanmaydi', strpos($fake->lastText(), 'yuklab bo\'lmadi') !== false && count($aiCalls) === $calls0
    && $app->aiUsage->usedOn($V, $app->today()) === $usedBefore);
// AI xatosi -> limit qaytadi
$fileOk('photos/file_5.jpg');
$aiQueue = [[500, '']];
$press($V, 'ai:again');
T::check('AI xatosi: limit qaytadi', strpos($fake->lastText(), 'javob bermadi') !== false && $app->aiUsage->usedOn($V, $app->today()) === $usedBefore);
$press($V, 'p:now');
T::check('AI rasm posti kanalga: rasm + izoh', ($fake->of('sendPhoto')[0]['photo'] ?? '') === 'P_BIG' && strpos((string) ($fake->of('sendPhoto')[0]['caption'] ?? ''), 'Ikkinchi variant') !== false
    && (int) ($fake->of('sendPhoto')[0]['chat_id'] ?? 0) === -1009300);
// rasm + izoh matni
$app->states->clear($V);
$send($V, ['photo' => [['file_id' => 'P_C']], 'caption' => 'Yangi krossovka 2026 kolleksiyasi']);
$press($V, 'in:ai');
T::eq('rasm izohi — AI uchun ko\'rsatma', $app->states->get($V)['data']['topic'] ?? '', 'Yangi krossovka 2026 kolleksiyasi');
$text($V, 'Faqat arzon narxni ta\'kidla va yoshlarga qarat');
T::check('uslub o\'rniga yangi izoh yozilsa — rasm saqlanadi', ($app->states->get($V)['data']['photo'] ?? '') === 'P_C' && ($app->states->get($V)['data']['topic'] ?? '') !== 'Yangi krossovka 2026 kolleksiyasi');
$fileOk('photos/c.jpg');
$aiQueue = [$gem('Arzon krossovka')];
$press($V, 'ai:s:short');
T::check('izoh promptga kirdi', strpos((string) ($parts(count($aiCalls) - 1)[1]['text'] ?? ''), 'arzon narxni') !== false);
$app->states->clear($V);

// --- ovozdan post
$vc = static function (int $uid, int $dur = 20, string $fid = 'VOICE1') use ($send): void {
    $send($uid, ['voice' => ['file_id' => $fid, 'duration' => $dur, 'mime_type' => 'audio/ogg', 'file_size' => 40000]]);
};
$aiCalls = [];
$fileOk('voice/file_9.oga');
$aiQueue = [$gem("<b>Aksiya!</b> Ertaga 10:00 da 20% chegirma.")];
$vc($V);
$prev = $fake->of('sendMessage');
$postMsg = null;
foreach ($prev as $m) {
    if (strpos((string) $m['text'], 'Aksiya!') !== false) {
        $postMsg = $m;
    }
}
T::check('ovoz: yuklandi, audio/ogg bilan Gemini, tayyor post preview\'da', count($aiCalls) === 1 && ($parts(0)[0]['inlineData']['mimeType'] ?? '') === 'audio/ogg'
    && strpos((string) ($parts(0)[1]['text'] ?? ''), 'Ovozli xabarni') !== false && $postMsg !== null && strpos((string) $postMsg['text'], '<b>Aksiya!</b>') !== false);
T::check('ovoz posti: «Boshqa variant» bor, holat post_preview', strpos($mk($postMsg), 'ai:again') !== false && ($app->states->get($V)['state'] ?? '') === 'post_preview'
    && ($app->states->get($V)['data']['ai']['voice'] ?? '') === 'VOICE1');
$fileOk('voice/file_9.oga');
$aiQueue = [$gem('Ovozdan ikkinchi variant')];
$press($V, 'ai:again');
T::check('ovoz: «Boshqa variant»', strpos($fake->texts(), 'Ovozdan ikkinchi variant') !== false && count($aiCalls) === 2);
$app->states->clear($V);
$aiCalls = [];
$vc($V, 400);
T::check('juda uzun ovoz rad (180 s)', strpos($fake->lastText(), '180') !== false && count($aiCalls) === 0);
$fake->forced['getFile'] = [['ok' => true, 'result' => ['file_path' => 'voice/big.oga', 'file_size' => 9999999]]];
$vc($V, 30);
T::check('hajmi katta ovoz: yuklanmaydi, AI chaqirilmaydi', strpos($fake->lastText(), 'yuklab bo\'lmadi') !== false && count($aiCalls) === 0);
// kanalsiz foydalanuvchi
$N = 9301;
$text($N, '/start');
$vc($N);
T::check('kanalsiz foydalanuvchi: avval kanal ulash', strpos($fake->texts(), 'Avval kanal ulang') !== false && count($aiCalls) === 0);
$app->states->clear($N);
// post yaratish holatida ovoz
$text($V, '/newpost');
$fileOk('voice/file_10.oga');
$aiQueue = [$gem('Holatdagi ovoz posti')];
$vc($V, 15, 'VOICE2');
T::check('«Post yaratish» holatida ham ovoz — post', strpos($fake->texts(), 'Holatdagi ovoz posti') !== false && ($app->states->get($V)['state'] ?? '') === 'post_preview');
$app->states->clear($V);
// AI o'chiq / Gemini yo'q
$app->ai = new Ai(new Config([]));
$vc($V);
T::check('AI o\'chiq: ovozga tushunarli javob', strpos($fake->lastText(), 'yoqilmagan') !== false);
$app->ai = new Ai(new Config(['groq_api_key' => 'Q']), $aiT);
$vc($V);
T::check('Gemini yo\'q: ovoz uchun kalit kerakligi aytiladi', strpos($fake->lastText(), 'gemini_api_key') !== false);
$text($V, '/start');
$app->ai = new Ai(new Config([]));
$app->states->clear($V);
$app->tg->setDownloader(null);
