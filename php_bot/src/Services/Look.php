<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\Db;

/**
 * ✨ Bot ko'rinishi: (1) rangli tugmalar (`style`: success / danger / primary — Telegram 2026+ ilovalarida),
 * (2) premium (jonli) emoji: oddiy belgi (🤖 ✍️ 📢 …) o'rniga admin o'rgatgan custom emoji — xabarda `<tg-emoji>`,
 * tugmada `icon_custom_emoji_id`. Telegram qoidasi: premium emoji faqat bot egasida Telegram Premium bo'lsa yoki
 * botga Fragment'da username sotib olingan bo'lsa ishlaydi; shuning uchun faqat shaxsiy chatlarda qo'llanadi va
 * Telegram rad etsa xabar oddiy holda qayta yuboriladi, xususiyat o'zi o'chadi (bot to'xtamaydi).
 * Kanal postlari (foydalanuvchi kontenti, `_raw`) o'zgartirilmaydi.
 */
final class Look
{
    public const KEY_MAP = 'premium_emoji';
    public const KEY_ON = 'premium_emoji_on';
    public const KEY_STYLES = 'button_styles_on';
    /** Bot interfeysidagi asosiy belgilar (admin ekranida qaysi biri premiumga almashganini ko'rsatish uchun). */
    public const UI_EMOJI = ['🤖', '✍️', '📢', '📅', '📊', '⚙️', '✨', '💎', '🚀', '✅', '❌', '🗑', '🔄', '⏳', '🕒', '💬', '🔒', '📌', '🔕',
        '🛡', '💰', '👥', '📰', '📝', '📤', '📦', '🎁', '🏠', '◀️', '📱', '👑', '🔥', '👍', '⭐', '💳', '🟦', '🌍', '📈', '🎯', '🧾'];

    private Db $db;
    private ?array $cache = null;
    /** Joriy yangilanish egasida Telegram Premium bormi (null — noma'lum: fon xabarlari, oddiy ko'rinish). */
    private ?bool $viewer = null;

    public function __construct(Db $db)
    {
        $this->db = $db;
    }

    private function get(string $k): ?string
    {
        if ($this->cache === null) {
            $this->cache = [];
            try {
                foreach ($this->db->all('SELECT k, v FROM bot_settings') as $r) {
                    $this->cache[(string) $r['k']] = (string) $r['v'];
                }
            } catch (\Throwable $e) {
                $this->cache = []; // jadval hali yo'q (setup.php ishlamagan) — oddiy ko'rinish
            }
        }
        return $this->cache[$k] ?? null;
    }

    public function set(string $k, string $v): void
    {
        $this->db->exec('INSERT INTO bot_settings (k, v, updated_at) VALUES (?, ?, UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE v = VALUES(v), updated_at = VALUES(updated_at)', [$k, $v]);
        $this->cache = null;
    }

    /**
     * Rangli tugmalar va jonli emoji FAQAT Telegram Premium foydalanuvchiga (shaxsiy chatda) — boshqalarga hammasi bir xil oddiy
     * ko'rinish, aralash (bir tugma ko'k, boshqasi oddiy) holat bo'lmaydi.
     */
    public function setViewer(?bool $premium): void
    {
        $this->viewer = $premium;
    }

    public function viewer(): ?bool
    {
        return $this->viewer;
    }

    public static function norm(string $e): string
    {
        return str_replace("\u{FE0F}", '', $e);
    }

    /** @return array<string,string> oddiy emoji (FE0F siz) => custom_emoji_id */
    public function map(): array
    {
        $m = json_decode((string) $this->get(self::KEY_MAP), true);
        return is_array($m) ? array_filter($m, static function ($v, $k) {
            return is_string($k) && $k !== '' && is_string($v) && preg_match('/^\d{5,25}$/', $v);
        }, ARRAY_FILTER_USE_BOTH) : [];
    }

    /** @param array<string,string> $add */
    public function addMap(array $add): array
    {
        $m = $this->map();
        foreach ($add as $e => $id) {
            if (preg_match('/^\d{5,25}$/', (string) $id) && self::norm((string) $e) !== '') {
                $m[self::norm((string) $e)] = (string) $id;
            }
        }
        $this->set(self::KEY_MAP, (string) json_encode($m, JSON_UNESCAPED_UNICODE));
        $this->set(self::KEY_ON, '1');
        return $m;
    }

    public function clearMap(): void
    {
        $this->set(self::KEY_MAP, '{}');
    }

    public function premiumOn(): bool
    {
        return $this->get(self::KEY_ON) !== '0' && $this->map() !== [];
    }

    public function stylesOn(): bool
    {
        return $this->get(self::KEY_STYLES) !== '0';
    }

    /** Tugma rangi callback_data bo'yicha: asosiy amal — yashil, o'chirish/bekor — qizil, muhim yo'l — ko'k. */
    public static function styleFor(string $data): ?string
    {
        if ($data === '') {
            return null;
        }
        if (preg_match('/(^p:cancel$|:dok(:|$)|^cm:[xb]:|^apd:no:|^rc:no|^bc:no$|^p:(btndel|hddel)$|^q:d:|^s:d:)/', $data)) {
            return 'danger';
        }
        if (preg_match('/(^p:now$|^apd:ok:|^bk:done$|^rc:ok|^bc:go$|^pl:b:|^pl:pm:|^pl:cb:|^cm:w:|^ap:m:|^bk:g:|^tpl:u:|^p:ch:|^pm:)/', $data)) {
            return 'success';
        }
        if (preg_match('/(^p:time$|^p:new$|^bk:start$|^poll:start$|^pl:show$|^ap:new$|^rss:new$|^cp:new$)/', $data)) {
            return 'primary';
        }
        return null;
    }

    /** Matn boshidagi xaritadagi emoji: [emoji (asl), id] yoki null. */
    private function leading(string $text, array $map): ?array
    {
        if (!preg_match('/^(\X)\s*/u', $text, $m)) {
            return null;
        }
        $k = self::norm($m[1]);
        return isset($map[$k]) ? [$m[0], $map[$k]] : null;
    }

    /**
     * Telegram so'rovini bezash. $premium/$styles — qaysi qatlam qo'llansin (Telegram rad etsa navbat bilan o'chiriladi).
     * @param array<string,mixed> $p
     * @return array<string,mixed>
     */
    public function decorate(string $method, array $p, bool $premium = true, bool $styles = true): array
    {
        if (!empty($p['_raw'])) {
            $premium = false; // post (kanalda yoki preview'da) — foydalanuvchi matni va tugmalari o'zgarmaydi, faqat boshqaruv tugmalari rangi
        }
        unset($p['_raw']);
        $private = isset($p['chat_id']) && is_numeric($p['chat_id']) && (int) $p['chat_id'] > 0;
        $vip = $private && $this->viewer === true;
        $map = $premium && $vip && $this->premiumOn() ? $this->map() : [];
        $styles = $styles && $vip && $this->stylesOn();
        if (isset($p['reply_markup']) && is_array($p['reply_markup'])) {
            foreach (['inline_keyboard', 'keyboard'] as $kind) {
                if (!isset($p['reply_markup'][$kind]) || !is_array($p['reply_markup'][$kind])) {
                    continue;
                }
                foreach ($p['reply_markup'][$kind] as $r => $row) {
                    foreach ((array) $row as $c => $btn) {
                        if (!is_array($btn) || !isset($btn['text'])) {
                            continue;
                        }
                        if ($styles && !isset($btn['style'])) {
                            // premium: hamma tugma rangli — asosiy amal yashil, o'chirish qizil, qolgani ko'k (bir xil uslub)
                            $st = self::styleFor((string) ($btn['callback_data'] ?? ''));
                            if ($st === null && $kind === 'inline_keyboard') {
                                $st = 'primary';
                            }
                            if ($st !== null) {
                                $btn['style'] = $st;
                            }
                        }
                        if ($map && !isset($btn['icon_custom_emoji_id']) && ($lead = $this->leading((string) $btn['text'], $map)) !== null) {
                            $rest = trim(substr((string) $btn['text'], strlen($lead[0])));
                            if ($rest !== '') {
                                $btn['icon_custom_emoji_id'] = $lead[1];
                                $btn['text'] = $rest;
                            }
                        }
                        $p['reply_markup'][$kind][$r][$c] = $btn;
                    }
                }
            }
        }
        if ($map && ($p['parse_mode'] ?? '') === 'HTML') {
            foreach (['text', 'caption'] as $f) {
                if (isset($p[$f]) && is_string($p[$f]) && strpos($p[$f], '<tg-emoji') === false) {
                    $p[$f] = $this->emojify($p[$f], $map);
                }
            }
        }
        return $p;
    }

    /** HTML matndagi (teglardan tashqari) xaritadagi emojilar → <tg-emoji>. */
    private function emojify(string $html, array $map): string
    {
        $parts = preg_split('/(<[^>]*>)/u', $html, -1, PREG_SPLIT_DELIM_CAPTURE) ?: [$html];
        $inCode = 0;
        foreach ($parts as $i => $part) {
            if ($part !== '' && $part[0] === '<') {
                if (preg_match('#^<(code|pre)\b#i', $part)) {
                    $inCode++;
                } elseif (preg_match('#^</(code|pre)>#i', $part)) {
                    $inCode = max(0, $inCode - 1);
                }
                continue;
            }
            if ($inCode > 0 || $part === '') {
                continue;
            }
            $parts[$i] = (string) preg_replace_callback('/\X/u', static function ($m) use ($map) {
                $k = self::norm($m[0]);
                return isset($map[$k]) ? '<tg-emoji emoji-id="' . $map[$k] . '">' . $m[0] . '</tg-emoji>' : $m[0];
            }, $part);
        }
        return implode('', $parts);
    }
}
