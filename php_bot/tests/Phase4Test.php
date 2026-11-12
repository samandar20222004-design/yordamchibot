<?php
// 4-bosqich integratsiya testi: navigatsiya (Orqaga / Menyu) va AI (Phase3Test.php dan keyin).
declare(strict_types=1);

use PostAssist\Config;
use PostAssist\Services\Ai;

T::section('L. Navigatsiya: har ekranda Orqaga / Menyu');
$W = $U2;
$app->states->clear($W);
$kbOf = static function () use ($fake, $mk): string {
    $all = $fake->of('sendMessage', 'editMessageText');
    return $all ? $mk(end($all)) : '';
};
$text($W, '📅 Rejalashtirilgan');
T::check('navbat ro\'yxati: «Yangi post» va «Menyu»', strpos($kbOf(), 'p:new') !== false && strpos($kbOf(), 'm:home') !== false);
$text($W, '📢 Kanallarim');
T::check('kanallar: «Menyu»', strpos($kbOf(), 'm:home') !== false);
$text($W, '⚙️ Sozlamalar / Ko\'proq');
T::check('sozlamalar: «Menyu»', strpos($kbOf(), 'm:home') !== false);
foreach (['set:lang' => 'til', 'set:help' => 'yordam', 'pl:show' => 'tariflar', 'ref:show' => 'taklif', 'set:tz' => 'vaqt mintaqasi', 'promo:ask' => 'promo'] as $cb => $name) {
    $press($W, $cb);
    T::check("{$name}: «Orqaga» sozlamalarga va «Menyu»", strpos($kbOf(), 'set:show') !== false && strpos($kbOf(), 'm:home') !== false, $kbOf());
}
T::eq('promo kutilayotgan edi', $app->states->get($W)['state'] ?? null, 'promo_wait');
$press($W, 'set:show');
T::check('«Orqaga»: holat tozalanadi, sozlamalar qaytadi', $app->states->get($W) === null && strpos($fake->lastText(), 'Sozlamalar') !== false);
$app->states->set($W, 'post_btn', ['draft' => ['type' => 'text', 'text' => 'x', 'file_id' => null]]);
$press($W, 'm:home');
T::check('«Menyu»: holat tozalanadi, bosh menyu', $app->states->get($W) === null && strpos($fake->lastText(), 'Kerakli bo\'limni') !== false
    && isset($fake->of('sendMessage')[0]['reply_markup']));
$press($W, 'p:new');
T::eq('«Yangi post» tugmasi post yaratishni boshlaydi', $app->states->get($W)['state'] ?? null, 'post_content');
$text($W, '/cancel');
$text($W, '📊 Statistika');
T::check('statistika: navbat, tariflar, menyu tugmalari', strpos($kbOf(), 'q:list') !== false && strpos($kbOf(), 'm:home') !== false);
$text($ADMIN, '/admin');
T::check('admin panel: inline tugmalar', strpos($kbOf(), 'a:promos') !== false && strpos($kbOf(), 'a:links') !== false && strpos($kbOf(), 'a:help') !== false);
$press($ADMIN, 'a:promos');
T::check('admin: promo-kodlar ro\'yxati + orqaga', strpos($fake->lastText(), 'ULT7') !== false && strpos($kbOf(), 'a:stats') !== false);
$press($ADMIN, 'a:links');
T::check('admin: havolalar', strpos($fake->lastText(), 'kanal_1') !== false);
$press($ADMIN, 'a:help');
T::check('admin: buyruqlar', strpos($fake->lastText(), '/grant_pro') !== false);
$press($W, 'a:promos');
T::eq('oddiy foydalanuvchiga admin tugmasi ishlamaydi', count($fake->of('sendMessage', 'editMessageText')), 0);
$draftText = static function (string $t) use ($text, $send, $W) {
    $text($W, '/newpost');
    $send($W, ['text' => $t]);
};
$draftText('O\'chiriladigan');
$press($W, 'p:time');
$press($W, 't:tom09');
$qid = (int) $db->value('SELECT id FROM scheduled_posts ORDER BY id DESC LIMIT 1');
$press($W, 'q:dok:' . $qid);
T::check('bekor qilingandan keyin: ro\'yxatga qaytish', strpos($kbOf(), 'q:list') !== false);
$press($W, 'q:v:' . $qid);
T::check('topilmagan post: ro\'yxatga qaytish', strpos($kbOf(), 'q:list') !== false);

T::section('M. AI o\'chiq bo\'lsa va aqlli qabul');
$text($W, '/ai');
T::check('AI kalitsiz: tushunarli xabar (oddiy foydalanuvchi)', strpos($fake->lastText(), 'yoqilmagan') !== false && strpos($fake->lastText(), 'config.php') === false);
$text($ADMIN, '/ai');
T::check('AI kalitsiz: adminga qayerga kalit yozish', strpos($fake->lastText(), 'gemini_api_key') !== false);
$text($W, 'Ertaga do\'konimizda katta chegirma boshlanadi');
$kb = $kbOf();
T::check('matn (dialogsiz): «Bu bilan nima qilamiz?», AI tugmasi yo\'q (o\'chiq)', strpos($fake->lastText(), 'nima qilamiz') !== false
    && strpos($kb, 'in:post') !== false && strpos($kb, 'in:ai') === false);
$press($W, 'in:post');
$prev = $fake->of('sendMessage')[0] ?? [];
T::check('«Post qilish»: o\'zgarishsiz preview', strpos((string) ($prev['text'] ?? ''), 'katta chegirma') !== false
    && ($app->states->get($W)['state'] ?? null) === 'post_preview');
$app->states->clear($W);
$send($W, ['photo' => [['file_id' => 'IN1']]]);
T::check('rasm (dialogsiz): post qilish taklifi', strpos($kbOf(), 'in:post') !== false);
$press($W, 'in:close');
T::check('«Yopish»', $app->states->get($W) === null && strpos($fake->lastText(), 'Bekor') !== false);
$text($W, 'ha');
T::check('qisqa javob: oddiy «tushunmadim»', strpos($fake->lastText(), 'Tushunmadim') !== false);

T::section('N. AI: post yozish, boshqa variant, tahrir, tarjima, limit, zaxira provayder');
$aiCalls = [];
$aiQueue = [];
$aiT = static function (string $url, array $h, string $body) use (&$aiCalls, &$aiQueue): array {
    $aiCalls[] = [$url, $h, json_decode($body, true)];
    return $aiQueue ? array_shift($aiQueue) : [500, ''];
};
$gem = static function (string $t): array {
    return [200, json_encode(['candidates' => [['content' => ['parts' => [['text' => $t]]]]]])];
};
$app->ai = new Ai(new Config(['gemini_api_key' => 'GK', 'groq_api_key' => 'QK']), $aiT);
$prompt = static function (int $i) use (&$aiCalls): string {
    $b = $aiCalls[$i][2] ?? [];
    return (string) ($b['contents'][0]['parts'][0]['text'] ?? $b['messages'][1]['content'] ?? '');
};
$system = static function (int $i) use (&$aiCalls): string {
    $b = $aiCalls[$i][2] ?? [];
    return (string) ($b['systemInstruction']['parts'][0]['text'] ?? $b['messages'][0]['content'] ?? '');
};
$text($W, '/start');
T::check('AI yoqilgach menyuda «✨ AI post»', strpos($kbOf(), 'AI post') !== false);
$text($W, '✨ AI post');
T::check('mavzu so\'raladi, PRO limiti 40/40', ($app->states->get($W)['state'] ?? null) === 'ai_topic' && strpos($fake->lastText(), '40/40') !== false);
$text($W, 'ab');
T::check('juda qisqa mavzu rad', strpos($fake->lastText(), '3–') !== false);
$text($W, 'Chilonzorda yangi filial ochildi, birinchi haftada 20% chegirma');
T::check('uslub tanlash', strpos($kbOf(), 'ai:s:sales') !== false && ($app->states->get($W)['state'] ?? null) === 'ai_style');
$aiQueue = [$gem("**Yangi filial!** 🎉\nChilonzorda ochildik — 20% chegirma.<script>x</script>")];
$press($W, 'ai:s:sales');
$prev = $fake->of('sendMessage');
$postMsg = null;
foreach ($prev as $m) {
    if (strpos((string) $m['text'], 'Yangi filial') !== false) {
        $postMsg = $m;
    }
}
T::check('AI chaqirildi: mavzu va uslub promptda, til o\'zbek', count($aiCalls) === 1 && strpos($prompt(0), 'Chilonzorda') !== false
    && strpos($prompt(0), 'CTA') !== false && strpos($system(0), "o'zbek") !== false);
T::check('preview: tozalangan HTML (<b>, <script> yo\'q), «Boshqa variant» tugmasi', $postMsg !== null
    && strpos((string) $postMsg['text'], '<b>Yangi filial!</b>') !== false && strpos((string) $postMsg['text'], '<script>') === false
    && strpos($mk($postMsg), 'ai:again') !== false);
T::check('«⏳ AI yozmoqda» xabari o\'chirildi', count($fake->of('deleteMessage')) === 1);
T::eq('AI hisob: 1 ta ishlatildi', $app->aiUsage->usedOn($W, $app->today()), 1);
$aiQueue = [$gem('Ikkinchi variant matni')];
$press($W, 'ai:again');
T::check('«Boshqa variant»: o\'sha mavzu, yangi matn preview\'da', strpos($prompt(1), 'Chilonzorda') !== false && strpos($fake->texts(), 'Ikkinchi variant') !== false
    && ($app->states->get($W)['data']['draft']['text'] ?? '') === 'Ikkinchi variant matni');
$press($W, 'p:more');
T::check('«Qo\'shimcha» ichida «✨ AI tahrir»', strpos($kbOf(), 'p:ai') !== false);
$press($W, 'p:ai');
T::check('AI tahrir menyusi: tarjima tugmalari va qolgan so\'rovlar', strpos($kbOf(), 'ai:e:tr_ru') !== false && strpos($fake->lastText(), 'Bugun qoldi') !== false);
$aiQueue = [$gem('Второй вариант текста')];
$press($W, 'ai:e:tr_ru');
T::check('tarjima: rus tilida, matn almashdi', strpos($system(2), 'rus') !== false && strpos($prompt(2), 'Ikkinchi variant') !== false
    && ($app->states->get($W)['data']['draft']['text'] ?? '') === 'Второй вариант текста');
$aiQueue = [[503, ''], [503, ''], [200, json_encode(['choices' => [['message' => ['content' => 'Groq javobi']]]])]]; // 503 — bir marta qayta urinadi
$press($W, 'ai:e:improve');
T::check('Gemini ishlamasa (qayta urinishdan keyin ham) — Groq javob beradi', strpos($fake->texts(), 'Groq javobi') !== false && strpos($aiCalls[4][0], 'googleapis') !== false
    && strpos($aiCalls[5][0], 'groq.com') !== false);
$usedBefore = $app->aiUsage->usedOn($W, $app->today());
$aiQueue = [[500, ''], [500, '']];
$press($W, 'ai:e:shorten');
T::check('ikkalasi ham ishlamasa: xabar va limit qaytadi', strpos($fake->lastText(), 'javob bermadi') !== false
    && $app->aiUsage->usedOn($W, $app->today()) === $usedBefore && ($app->states->get($W)['data']['draft']['text'] ?? '') === 'Groq javobi');
$press($W, 'p:now');
T::check('AI posti kanalga ketdi', strpos((string) ($fake->of('sendMessage')[0]['text'] ?? ''), 'Groq javobi') !== false
    && (int) ($fake->of('sendMessage')[0]['chat_id'] ?? 0) === $CH);

// limit tugadi, ballar ham yo'q
$db->exec('UPDATE ai_usage SET used = 40 WHERE user_id = ? AND day = ?', [$W, $app->today()]);
$db->exec('UPDATE users SET ai_credits = 1 WHERE user_id = ?', [$W]);
$text($W, '✨ AI post');
$text($W, 'Seminar ertaga soat 10 da');
$aiQueue = [$gem('Seminar posti')];
$calls0 = count($aiCalls);
$press($W, 'ai:s:short');
T::check('kunlik limit tugasa — ball ishlatiladi (1 -> 0)', count($aiCalls) === $calls0 + 1 && $app->credits->balance($W) === 0
    && (int) $db->value("SELECT COUNT(*) FROM credits_ledger WHERE user_id = ? AND operation_type = 'ai'", [$W]) === 1);
$app->states->clear($W);
$text($W, '✨ AI post');
$text($W, 'Yana bir mavzu haqida post');
$press($W, 'ai:s:short');
T::check('limit va ball tugadi: AI chaqirilmaydi, tariflar va taklif tugmalari', count($aiCalls) === $calls0 + 1
    && strpos($fake->lastText(), 'tugadi') !== false && strpos($kbOf(), 'pl:show') !== false && strpos($kbOf(), 'ref:show') !== false);
$db->exec('UPDATE ai_usage SET used = 0 WHERE user_id = ? AND day = ?', [$W, $app->today()]);
$aiQueue = [[500, ''], [500, '']];
$db->exec('UPDATE ai_usage SET used = 40 WHERE user_id = ? AND day = ?', [$W, $app->today()]);
$db->exec('UPDATE users SET ai_credits = 3 WHERE user_id = ?', [$W]);
$app->states->set($W, 'ai_style', ['topic' => 'Mavzu matni']);
$press($W, 'ai:s:news');
T::eq('ball bilan so\'rov muvaffaqiyatsiz bo\'lsa — ball qaytadi', $app->credits->balance($W), 3);
$db->exec('UPDATE ai_usage SET used = 0 WHERE user_id = ? AND day = ?', [$W, $app->today()]);

// aqlli qabul AI bilan
$app->states->clear($W);
$text($W, 'Ertaga soat 10 da bepul seminar boshlanadi, joylar soni cheklangan');
T::check('matn: «✨ AI bilan» tugmasi ham bor', strpos($kbOf(), 'in:ai') !== false);
$press($W, 'in:ai');
T::check('AI bilan: uslub so\'raladi', strpos($kbOf(), 'ai:s:news') !== false && ($app->states->get($W)['data']['topic'] ?? '') !== '');
$text($W, 'Boshqa mavzu: yangi kurs ochilmoqda');
T::eq('uslub o\'rniga matn yozsa — yangi mavzu', $app->states->get($W)['data']['topic'] ?? null, 'Boshqa mavzu: yangi kurs ochilmoqda');
$aiQueue = [$gem('Kurs posti')];
$press($W, 'ai:s:useful');
T::check('aqlli qabul -> AI post preview', ($app->states->get($W)['state'] ?? null) === 'post_preview' && strpos($fake->texts(), 'Kurs posti') !== false);
// matnsiz rasm: AI tahrir matn so'raydi
$app->states->clear($W);
$text($W, '/newpost');
$send($W, ['photo' => [['file_id' => 'NOCAP']]]);
$press($W, 'p:more');
T::check('matnsiz rasmda «AI tahrir» tugmasi yo\'q', strpos($kbOf(), 'p:ai') === false);
$press($W, 'p:ai');
T::check('to\'g\'ridan-to\'g\'ri bosilsa: avval matn qo\'shing', strpos($fake->lastText(), 'matn yo\'q') !== false);
$press($W, 'ai:again');
T::check('AI bo\'lmagan qoralamada «Boshqa variant»: qoralama topilmadi', strpos($fake->lastText(), 'Qoralama topilmadi') !== false);
$app->states->clear($W);
$app->ai = new Ai(new Config([]));
