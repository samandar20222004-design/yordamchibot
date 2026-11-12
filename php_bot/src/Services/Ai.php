<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\Config;
use PostAssist\Html;

/**
 * AI matn generatsiyasi (Python botdagi kabi bepul provayderlar, navbat bilan):
 *   1) Google Gemini (gemini_api_key)   2) Groq (groq_api_key)   3) OpenRouter (openrouter_api_key).
 * Birinchisi ishlamasa (xato, bo'sh javob, vaqt tugadi) — keyingisi. Kalit qo'yilmagan provayder o'tkazib yuboriladi.
 * Natija Telegram HTML ga tozalanadi (Html::sanitize) — modeldan kelgan matn hech qachon xom holda yuborilmaydi.
 * Testlar uchun tarmoq qatlami almashtiriladi: fn(string $url, array $headers, string $body): array{0:int,1:string}.
 */
final class Ai
{
    public const STYLES = ['news', 'sales', 'fun', 'useful', 'short'];
    public const EDITS = ['improve', 'shorten', 'emoji', 'rewrite', 'tr_uz', 'tr_ru', 'tr_en'];
    private const LANG_NAMES = ['uz' => "o'zbek (lotin yozuvida)", 'ru' => 'rus', 'en' => 'ingliz'];

    private Config $config;
    /** @var callable|null */
    private $transport;
    /** @var callable|null fn(string): void — provayder xatosi logga (kalitsiz) */
    public $logger;
    /** Oxirgi so'rov natijasi har provayder bo'yicha: name => 'ok' | 'HTTP 401: ...' (setup.php tekshiruvi uchun). */
    public array $lastStatus = [];
    /** @var callable|null fn(string $key, ?string $value = null): ?string — o'zi topgan model nomini saqlash (bot_settings) */
    public $store;
    /** Oxirgi tarmoq xatosi (curl) — aniq sabab: ulanib bo'lmadi / javob kechikdi. */
    private string $netError = '';
    /** Gemini band yoki sekin bo'lganda vaqtincha ishlatilgan zaxira model: asosiy => zaxira. */
    public array $fallbackUsed = [];
    /** Shu so'rovda o'zi almashtirgan modellar: name => 'eski → yangi' (setup.php va check.php ko'rsatadi). */
    public array $healed = [];
    private array $override = [];
    private bool $healing = false;
    /** @var callable fn(int $ms): void — qayta urinishdan oldingi kutish (testda o'chiriladi) */
    public $sleeper;
    /** Testlar: haqiqiy kutishsiz (tests/run.php yoqadi). */
    public static bool $noSleep = false;

    public function __construct(Config $config, ?callable $transport = null)
    {
        $this->config = $config;
        $this->transport = $transport;
        $this->sleeper = static function (int $ms): void {
            if (!self::$noSleep) {
                usleep($ms * 1000);
            }
        };
    }

    /**
     * Har bir ulangan AI kalitini kichik so'rov bilan tekshiradi (setup.php).
     * @return array<string, string> name => 'OK (model)' yoki xato sababi
     */
    public function check(): array
    {
        $out = [];
        foreach ($this->providers() as $p) {
            $raw = $this->callProvider($p, 'Reply with one word.', 'Say: OK');
            if ($raw === null && $p['kind'] === 'gemini') {
                $first = (string) ($this->lastStatus[$p['name']] ?? '');
                $raw = $this->tryGeminiFallback($p, 'Reply with one word.', 'Say: OK', null);
                if ($raw !== null) {
                    $out[$p['name']] = 'OK (' . $this->fallbackUsed[$p['name']] . ' — zaxira; asosiy ' . $p['model'] . ': ' . $first . ')';
                    continue;
                }
            }
            if ($raw !== null) {
                $out[$p['name']] = 'OK (' . ($this->healed[$p['name']] ?? $p['model']) . ')' . (isset($this->healed[$p['name']]) ? ' — model avtomatik almashtirildi' : '');
                continue;
            }
            $msg = ($this->lastStatus[$p['name']] ?? 'xato') . ' — model: ' . $p['model'];
            $ids = stripos($msg, '404') !== false ? $this->listModels($p) : [];
            if ($ids) {
                $msg .= ' | mavjud modellar: ' . implode(', ', array_slice($ids, 0, 12)) . ' — config.php ga \'' . $p['name'] . '_model\' => \'NOM\' yozing';
            }
            $out[$p['name']] = $msg;
        }
        return $out;
    }

    /** @return array<int, array{name:string, kind:string, url:string, key:string, model:string}> */
    public function providers(): array
    {
        $c = $this->config;
        $out = [];
        if ($c->str('gemini_api_key') !== '') {
            $model = $this->modelFor('gemini', $c->str('gemini_model') ?: 'gemini-3.8-flash');
            $out[] = ['name' => 'gemini', 'kind' => 'gemini', 'key' => $c->str('gemini_api_key'), 'model' => $model,
                'url' => 'https://generativelanguage.googleapis.com/v1beta/models/' . rawurlencode($model) . ':generateContent'];
        }
        if ($c->str('groq_api_key') !== '') {
            $out[] = ['name' => 'groq', 'kind' => 'openai', 'key' => $c->str('groq_api_key'), 'model' => $this->modelFor('groq', $c->str('groq_model') ?: 'llama-3.3-70b-versatile'),
                'url' => 'https://api.groq.com/openai/v1/chat/completions'];
        }
        if ($c->str('openrouter_api_key') !== '') {
            $out[] = ['name' => 'openrouter', 'kind' => 'openai', 'key' => $c->str('openrouter_api_key'),
                'model' => $this->modelFor('openrouter', $c->str('openrouter_model') ?: 'meta-llama/llama-3.3-70b-instruct:free'), 'url' => 'https://openrouter.ai/api/v1/chat/completions'];
        }
        return $out;
    }

    /** Model nomi: o'zi topib saqlagan almashtirish (faqat shu eski nom o'rniga) > sozlama/standart. */
    private function modelFor(string $name, string $configured): string
    {
        if (!isset($this->override[$name]) && $this->store !== null) {
            $raw = (string) (($this->store)('ai_model_' . $name) ?? '');
            $j = $raw !== '' ? json_decode($raw, true) : null;
            $this->override[$name] = is_array($j) && !empty($j['from']) && !empty($j['to']) ? $j : [];
        }
        $o = $this->override[$name] ?? [];
        return !empty($o) && $o['from'] === $configured ? (string) $o['to'] : $configured;
    }

    /**
     * Provayderdan mavjud modellar ro'yxatini so'raydi (kalit bilan). Gemini: generateContent'ni qo'llaydiganlar.
     * @return string[]
     */
    public function listModels(array $p): array
    {
        if ($p['name'] === 'gemini') {
            [$st, $resp] = $this->http('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200', ['x-goog-api-key: ' . $p['key']], '');
            $d = $st === 200 ? json_decode($resp, true) : null;
            $out = [];
            foreach (is_array($d['models'] ?? null) ? $d['models'] : [] as $m) {
                if (in_array('generateContent', (array) ($m['supportedGenerationMethods'] ?? []), true)) {
                    $out[] = preg_replace('#^models/#', '', (string) ($m['name'] ?? ''));
                }
            }
            return array_values(array_filter($out));
        }
        if ($p['name'] === 'groq') {
            [$st, $resp] = $this->http('https://api.groq.com/openai/v1/models', ['Authorization: Bearer ' . $p['key']], '');
            $d = $st === 200 ? json_decode($resp, true) : null;
            $out = [];
            foreach (is_array($d['data'] ?? null) ? $d['data'] : [] as $m) {
                $out[] = (string) ($m['id'] ?? '');
            }
            return array_values(array_filter($out));
        }
        return [];
    }

    /** Ro'yxatdan matn (chat) uchun eng mosini tanlaydi (eng yangi barqaror Flash / eng katta Llama). null — topilmadi. */
    public static function pickModel(string $provider, array $ids): ?string
    {
        if ($provider === 'gemini') {
            $best = null;
            $bestV = '0';
            foreach (['#^gemini-(\d+(?:\.\d+)?)-flash$#', '#^gemini-(\d+(?:\.\d+)?)-flash-lite$#'] as $re) {
                foreach ($ids as $id) {
                    if (preg_match($re, $id, $m) && version_compare($m[1], $bestV, '>')) {
                        $best = $id;
                        $bestV = $m[1];
                    }
                }
                if ($best !== null) {
                    return $best;
                }
            }
            return null;
        }
        if ($provider === 'groq') {
            $chat = array_values(array_filter($ids, static function ($id) {
                return preg_match('#whisper|guard|tts|orpheus|playai|prompt|safeguard|embed#i', $id) !== 1;
            }));
            foreach (['#versatile#i', '#70b#i', '#120b#i', '#llama#i'] as $re) {
                foreach ($chat as $id) {
                    if (preg_match($re, $id)) {
                        return $id;
                    }
                }
            }
            return $chat[0] ?? null;
        }
        return null;
    }

    /**
     * Gemini modeli band (429/5xx) yoki javob bermadi (vaqt tugadi): boshqa Gemini modeli bilan bir marta urinish
     * (masalan yengilroq «flash-lite»). Kalit xatosi (400/401/403) bo'lsa — urinilmaydi. Saqlanmaydi (vaqtinchalik).
     */
    private function tryGeminiFallback(array $p, string $system, string $prompt, ?array $media): ?string
    {
        $st = (string) ($this->lastStatus[$p['name']] ?? '');
        if (!preg_match('/^(HTTP (429|5\d\d)|tarmoq|bo\'sh javob)/', $st)) {
            return null;
        }
        $alt = self::pickAlternate($this->listModels($p), $p['model']);
        if ($alt === null) {
            return null;
        }
        $q = $p;
        $q['model'] = $alt;
        $q['url'] = 'https://generativelanguage.googleapis.com/v1beta/models/' . rawurlencode($alt) . ':generateContent';
        $raw = $this->callProvider($q, $system, $prompt, $media);
        if ($raw !== null) {
            $this->fallbackUsed[$p['name']] = $alt;
            if ($this->logger !== null) {
                ($this->logger)('AI ' . $p['name'] . ': ' . $p['model'] . ' band/sekin — zaxira model ishladi: ' . $alt);
            }
        }
        return $raw;
    }

    /** Joriydan boshqa Gemini modeli: avval eng yangi barqaror flash, keyin flash-lite (preview/exp/image/tts emas). */
    public static function pickAlternate(array $ids, string $current): ?string
    {
        $ids = array_values(array_filter($ids, static function ($id) use ($current) {
            return $id !== $current;
        }));
        return self::pickModel('gemini', $ids);
    }

    /** Model topilmadi (404): mavjud ro'yxatdan mosini topib, saqlaydi. Yangi nom yoki null. */
    private function heal(array $p): ?string
    {
        if ($this->healing) {
            return null;
        }
        $this->healing = true;
        try {
            $new = self::pickModel($p['name'], $this->listModels($p));
        } finally {
            $this->healing = false;
        }
        if ($new === null || $new === $p['model']) {
            return null;
        }
        $from = $this->config->str($p['name'] . '_model') ?: ($p['name'] === 'gemini' ? 'gemini-3.8-flash' : 'llama-3.3-70b-versatile');
        $this->override[$p['name']] = ['from' => $from, 'to' => $new];
        $this->healed[$p['name']] = $p['model'] . ' → ' . $new;
        if ($this->store !== null) {
            ($this->store)('ai_model_' . $p['name'], json_encode(['from' => $from, 'to' => $new]));
        }
        if ($this->logger !== null) {
            ($this->logger)('AI ' . $p['name'] . ': model topilmadi (' . $p['model'] . '), avtomatik almashtirildi: ' . $new);
        }
        return $new;
    }

    public function enabled(): bool
    {
        return $this->providers() !== [];
    }

    /** Rasm va ovozni faqat Gemini tushunadi (inlineData). */
    public function mediaEnabled(): bool
    {
        return $this->config->str('gemini_api_key') !== '';
    }

    /** Umumiy qoidalar (Python `[QUALITY]` bloki ma'nosida). */
    public static function system(string $lang, int $maxChars): string
    {
        $l = self::LANG_NAMES[$lang] ?? self::LANG_NAMES['uz'];
        return "Sen Telegram kanallari uchun professional SMM kopirayterisan.\n"
            . "Qoidalar:\n"
            . "- Faqat tayyor post matnini yoz: kirish so'zlari («Mana post», «Albatta») va izohlarsiz.\n"
            . "- Aynan so'ralganini bajar. Faktlar, raqamlar, narx, sana, manzil va havolalarni o'ylab topma va o'zgartirma.\n"
            . "- Formatlash uchun FAQAT Telegram HTML teglari: <b>, <i>, <u>, <s>, <code>, <blockquote>. Markdown ishlatma.\n"
            . "- Qisqa xatboshilar, o'qishga qulay; emoji me'yorida.\n"
            . "- Javob tili: {$l}.\n"
            . "- Uzunligi {$maxChars} belgidan oshmasin.";
    }

    /** Uslub ta'rifi (mavzu, rasm va ovozdan post uchun umumiy). */
    public static function styleHow(string $style): string
    {
        return [
            'news' => "yangilik/e'lon ko'rinishida: qisqa sarlavha (qalin), 2–3 xatboshi, oxirida bitta savol yoki chaqiriq",
            'sales' => "sotuvchi post: diqqatni tortadigan sarlavha, foydalari ro'yxat ko'rinishida (✅), aniq chaqiriq (CTA)",
            'fun' => "qiziqarli, jonli uslubda: hazil aralash, emoji ko'proq, o'quvchi bilan suhbatdek",
            'useful' => "foydali maslahatlar posti: sarlavha va 3–5 ta raqamlangan maslahat, har biri bir-ikki gap",
            'short' => "juda qisqa post: 2–4 gap, eng muhim fikr, bitta emoji",
        ][$style] ?? 'oddiy, tushunarli post';
    }

    /** Mavzudan yangi post. */
    public static function postPrompt(string $topic, string $style): string
    {
        return "Quyidagi mavzuda Telegram kanal uchun post yoz — " . self::styleHow($style) . ".\n\nMavzu:\n" . trim($topic);
    }

    /** Rasmdan post: faqat ko'ringan narsaga tayanadi (narx, manzil, nom kabi ko'rinmagan faktlarni o'ylab topmaydi). */
    public static function imagePrompt(string $hint, string $style): string
    {
        return "Rasmga qarab Telegram kanal uchun post yoz — " . self::styleHow($style) . ".\n"
            . "Faqat rasmda ko'ringan narsa va quyidagi izohga tayan; ko'rinmagan faktlarni (narx, manzil, nom, sana) o'ylab topma."
            . (trim($hint) !== '' ? "\n\nMuallif izohi:\n" . trim($hint) : '');
    }

    /** Ovozli xabardan post: aytilgan fikr va faktlar saqlanadi, to'xtash va takrorlar tashlanadi. */
    public static function voicePrompt(string $style): string
    {
        return "Ovozli xabarni diqqat bilan tingla va undan Telegram kanal uchun post yoz — " . self::styleHow($style) . ".\n"
            . "Gapirilgan fikr va faktlarni (raqam, narx, sana, manzil) aynan saqla, ortiqcha so'zlar, to'xtash va takrorlarni tashla; o'zingdan fakt qo'shma.";
    }

    /** Mavjud matnni tahrirlash. */
    public static function editPrompt(string $text, string $action): string
    {
        $what = [
            'improve' => "Matnni yaxshila: imlo va uslubni tuzat, o'qishga qulay qil, ma'nosini va faktlarni saqla.",
            'shorten' => "Matnni taxminan ikki baravar qisqartir, asosiy fikrlar va barcha faktlar qolsin.",
            'emoji' => "Matnga mos joylarda me'yorida emoji qo'sh, so'zlarini o'zgartirma.",
            'rewrite' => "Matnni butunlay boshqacha so'zlar bilan qayta yoz, ma'nosi va faktlari bir xil qolsin.",
            'tr_uz' => "Matnni o'zbek tiliga (lotin yozuvida) tarjima qil, formatlash va emoji saqlansin.",
            'tr_ru' => "Matnni rus tiliga tarjima qil, formatlash va emoji saqlansin.",
            'tr_en' => "Matnni ingliz tiliga tarjima qil, formatlash va emoji saqlansin.",
        ][$action] ?? "Matnni yaxshila.";
        return $what . "\n\nMatn:\n" . trim($text);
    }

    /** Tahrirdan keyin javob tili: tarjima bo'lsa — o'sha til. */
    public static function editLang(string $action, string $uiLang): string
    {
        return strpos($action, 'tr_') === 0 ? substr($action, 3) : $uiLang;
    }

    /**
     * @param array{mime:string, data:string}|null $media rasm yoki ovoz baytlari (faqat Gemini)
     * @return array{ok:bool, text?:string, provider?:string, error?:string} error: disabled | failed
     */
    public function generate(string $system, string $prompt, int $maxChars, ?array $media = null): array
    {
        $providers = array_values(array_filter($this->providers(), static function ($p) use ($media) {
            return $media === null || $p['kind'] === 'gemini'; // rasm/ovoz — faqat Gemini
        }));
        if (!$providers) {
            return ['ok' => false, 'error' => 'disabled'];
        }
        foreach ($providers as $i => $p) {
            $raw = $this->callProvider($p, $system, $prompt, $media);
            // zaxira Gemini modeli faqat boshqa yo'l qolmaganda (rasm/ovoz yoki oxirgi provayder) — matnda Groq tezroq
            if ($raw === null && $p['kind'] === 'gemini' && ($media !== null || $i === count($providers) - 1)) {
                $raw = $this->tryGeminiFallback($p, $system, $prompt, $media);
            }
            if ($raw === null) {
                continue;
            }
            $html = Html::sanitize($raw);
            if (trim(Html::plain($html)) === '') {
                continue;
            }
            if (Html::utf16Len(Html::plain($html)) > $maxChars) {
                $html = self::cut($html, $maxChars);
            }
            return ['ok' => true, 'text' => $html, 'provider' => $p['name']];
        }
        return ['ok' => false, 'error' => 'failed'];
    }

    /** Juda uzun javobni oxirgi to'liq xatboshi/gapgacha qisqartiradi (formatlashsiz, xavfsiz). */
    public static function cut(string $html, int $maxChars): string
    {
        $plain = Html::plain($html);
        $part = mb_substr($plain, 0, max(1, $maxChars - 1));
        $p = max((int) mb_strrpos($part, "\n"), (int) mb_strrpos($part, '. '));
        if ($p > $maxChars / 2) {
            $part = mb_substr($part, 0, $p + 1);
        }
        while (Html::utf16Len($part) > $maxChars - 1) {
            $part = mb_substr($part, 0, mb_strlen($part) - 1);
        }
        return Html::e(rtrim($part)) . '…';
    }

    private function callProvider(array $p, string $system, string $prompt, ?array $media = null): ?string
    {
        if ($p['kind'] === 'gemini') {
            $gen = ['temperature' => 0.8, 'maxOutputTokens' => 2048];
            if (stripos($p['model'], 'flash') !== false) {
                // 2.5 Flash «o'ylash» tokenlari ham chegaraga kiradi — post uchun kerak emas, matn kesilib qolmasin
                $gen['thinkingConfig'] = ['thinkingBudget' => 0];
            }
            $body = json_encode([
                'systemInstruction' => ['parts' => [['text' => $system]]],
                'contents' => [['role' => 'user', 'parts' => array_merge(
                    $media !== null ? [['inlineData' => ['mimeType' => $media['mime'], 'data' => base64_encode($media['data'])]]] : [],
                    [['text' => $prompt]]
                )]],
                'generationConfig' => $gen,
            ], JSON_UNESCAPED_UNICODE);
            $headers = ['Content-Type: application/json', 'x-goog-api-key: ' . $p['key']];
        } else {
            $body = json_encode([
                'model' => $p['model'],
                'messages' => [['role' => 'system', 'content' => $system], ['role' => 'user', 'content' => $prompt]],
                'temperature' => 0.8, 'max_tokens' => 2048,
            ], JSON_UNESCAPED_UNICODE);
            $headers = ['Content-Type: application/json', 'Authorization: Bearer ' . $p['key']];
        }
        [$status, $resp] = $this->http($p['url'], $headers, (string) $body);
        if (in_array($status, [429, 500, 502, 503, 504], true)) {
            // provayder vaqtincha band (ko'p talab / kvota soniyasi) — 2 soniyadan keyin bir marta qayta
            ($this->sleeper)(2000);
            [$status, $resp] = $this->http($p['url'], $headers, (string) $body);
        }
        if (($status === 404 || $status === 400) && $p['name'] !== 'openrouter' && !$this->healing && preg_match('#model|no longer available|not found|not exist#i', $resp)) {
            $new = $this->heal($p);
            if ($new !== null) {
                $p['model'] = $new;
                if ($p['kind'] === 'gemini') {
                    $p['url'] = 'https://generativelanguage.googleapis.com/v1beta/models/' . rawurlencode($new) . ':generateContent';
                } else {
                    $body = (string) preg_replace('#"model":"[^"]*"#', '"model":' . json_encode($new), (string) $body, 1);
                }
                [$status, $resp] = $this->http($p['url'], $headers, (string) $body);
            }
        }
        if ($status < 200 || $status >= 300) {
            $data = json_decode($resp, true);
            $err = is_array($data) ? ($data['error'] ?? '') : '';
            $why = is_array($err) ? (string) ($err['message'] ?? '') : (is_string($err) ? $err : '');
            $net = $this->netError !== '' ? $this->netError : '';
            $this->netError = '';
            $msg = ($status === 0 ? 'tarmoq/vaqt tugadi' . ($net !== '' ? ' (' . mb_substr($net, 0, 120) . ')' : '') : 'HTTP ' . $status) . ($why !== '' ? ': ' . mb_substr(str_replace($p['key'], '***', $why), 0, 160) : '');
            $this->fail($p['name'], $msg);
            return null;
        }
        $data = json_decode($resp, true);
        if (!is_array($data)) {
            $this->fail($p['name'], "javob JSON emas");
            return null;
        }
        if ($p['kind'] === 'gemini') {
            $parts = $data['candidates'][0]['content']['parts'] ?? [];
            $text = '';
            foreach (is_array($parts) ? $parts : [] as $part) {
                if (empty($part['thought'])) {
                    $text .= (string) ($part['text'] ?? '');
                }
            }
            if ($text === '') {
                $this->fail($p['name'], "bo'sh javob (" . (string) ($data['candidates'][0]['finishReason'] ?? $data['promptFeedback']['blockReason'] ?? '?') . ')');
                return null;
            }
            $this->lastStatus[$p['name']] = 'ok';
            return $text;
        }
        $text = (string) ($data['choices'][0]['message']['content'] ?? '');
        if ($text === '') {
            $this->fail($p['name'], "bo'sh javob");
            return null;
        }
        $this->lastStatus[$p['name']] = 'ok';
        return $text;
    }

    private function fail(string $name, string $msg): void
    {
        $this->lastStatus[$name] = $msg;
        if ($this->logger !== null) {
            ($this->logger)('AI ' . $name . ' ishlamadi: ' . $msg);
        }
    }

    /** @return array{0:int,1:string} */
    private function http(string $url, array $headers, string $body): array
    {
        if ($this->transport !== null) {
            return ($this->transport)($url, $headers, $body);
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 8, CURLOPT_TIMEOUT => 25,
        ]);
        if ($body !== '') { // bo'sh tana — GET (modellar ro'yxati)
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        }
        $resp = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $this->netError = $resp === false ? (string) curl_error($ch) : '';
        curl_close($ch);
        return [$resp === false ? 0 : $status, $resp === false ? '' : (string) $resp];
    }
}
