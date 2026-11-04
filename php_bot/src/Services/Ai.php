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

    public function __construct(Config $config, ?callable $transport = null)
    {
        $this->config = $config;
        $this->transport = $transport;
    }

    /** @return array<int, array{name:string, kind:string, url:string, key:string, model:string}> */
    public function providers(): array
    {
        $c = $this->config;
        $out = [];
        if ($c->str('gemini_api_key') !== '') {
            $model = $c->str('gemini_model') ?: 'gemini-2.5-flash';
            $out[] = ['name' => 'gemini', 'kind' => 'gemini', 'key' => $c->str('gemini_api_key'), 'model' => $model,
                'url' => 'https://generativelanguage.googleapis.com/v1beta/models/' . rawurlencode($model) . ':generateContent'];
        }
        if ($c->str('groq_api_key') !== '') {
            $out[] = ['name' => 'groq', 'kind' => 'openai', 'key' => $c->str('groq_api_key'), 'model' => $c->str('groq_model') ?: 'llama-3.3-70b-versatile',
                'url' => 'https://api.groq.com/openai/v1/chat/completions'];
        }
        if ($c->str('openrouter_api_key') !== '') {
            $out[] = ['name' => 'openrouter', 'kind' => 'openai', 'key' => $c->str('openrouter_api_key'),
                'model' => $c->str('openrouter_model') ?: 'meta-llama/llama-3.3-70b-instruct:free', 'url' => 'https://openrouter.ai/api/v1/chat/completions'];
        }
        return $out;
    }

    public function enabled(): bool
    {
        return $this->providers() !== [];
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

    /** Mavzudan yangi post. */
    public static function postPrompt(string $topic, string $style): string
    {
        $how = [
            'news' => "yangilik/e'lon ko'rinishida: qisqa sarlavha (qalin), 2–3 xatboshi, oxirida bitta savol yoki chaqiriq",
            'sales' => "sotuvchi post: diqqatni tortadigan sarlavha, foydalari ro'yxat ko'rinishida (✅), aniq chaqiriq (CTA)",
            'fun' => "qiziqarli, jonli uslubda: hazil aralash, emoji ko'proq, o'quvchi bilan suhbatdek",
            'useful' => "foydali maslahatlar posti: sarlavha va 3–5 ta raqamlangan maslahat, har biri bir-ikki gap",
            'short' => "juda qisqa post: 2–4 gap, eng muhim fikr, bitta emoji",
        ][$style] ?? 'oddiy, tushunarli post';
        return "Quyidagi mavzuda Telegram kanal uchun post yoz — {$how}.\n\nMavzu:\n" . trim($topic);
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
     * @return array{ok:bool, text?:string, provider?:string, error?:string} error: disabled | failed
     */
    public function generate(string $system, string $prompt, int $maxChars): array
    {
        $providers = $this->providers();
        if (!$providers) {
            return ['ok' => false, 'error' => 'disabled'];
        }
        foreach ($providers as $p) {
            $raw = $this->callProvider($p, $system, $prompt);
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

    private function callProvider(array $p, string $system, string $prompt): ?string
    {
        if ($p['kind'] === 'gemini') {
            $gen = ['temperature' => 0.8, 'maxOutputTokens' => 2048];
            if (stripos($p['model'], 'flash') !== false) {
                // 2.5 Flash «o'ylash» tokenlari ham chegaraga kiradi — post uchun kerak emas, matn kesilib qolmasin
                $gen['thinkingConfig'] = ['thinkingBudget' => 0];
            }
            $body = json_encode([
                'systemInstruction' => ['parts' => [['text' => $system]]],
                'contents' => [['role' => 'user', 'parts' => [['text' => $prompt]]]],
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
        if ($status < 200 || $status >= 300) {
            return null;
        }
        $data = json_decode($resp, true);
        if (!is_array($data)) {
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
            return $text !== '' ? $text : null;
        }
        $text = (string) ($data['choices'][0]['message']['content'] ?? '');
        return $text !== '' ? $text : null;
    }

    /** @return array{0:int,1:string} */
    private function http(string $url, array $headers, string $body): array
    {
        if ($this->transport !== null) {
            return ($this->transport)($url, $headers, $body);
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_HTTPHEADER => $headers,
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 8, CURLOPT_TIMEOUT => 25,
        ]);
        $resp = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        return [$resp === false ? 0 : $status, $resp === false ? '' : (string) $resp];
    }
}
