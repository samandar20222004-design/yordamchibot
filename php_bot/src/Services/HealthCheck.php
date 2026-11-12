<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\App;
use PostAssist\Config;

/**
 * Botning umumiy sog'ligi (check.php): sozlama, baza, token, webhook, cron, AI, oxirgi xatolar.
 * Har qator: ['ok'|'warn'|'fail', sarlavha, tafsilot]. Maxfiy qiymat (token, parol, kalit) HECH QACHON chiqmaydi.
 */
final class HealthCheck
{
    private App $app;
    private array $cfg;
    private string $root;

    public function __construct(App $app, array $cfg, string $root)
    {
        $this->app = $app;
        $this->cfg = $cfg;
        $this->root = rtrim($root, '/');
    }

    /** @return array<int, array{0:string,1:string,2:string}> */
    public function run(bool $checkAi = true): array
    {
        $r = [];
        $r[] = version_compare(PHP_VERSION, '7.4.0', '>=') ? ['ok', 'PHP', PHP_VERSION] : ['fail', 'PHP', 'PHP 7.4 yoki yangi kerak, sizda ' . PHP_VERSION];
        foreach (['pdo_mysql', 'curl', 'mbstring', 'json'] as $ext) {
            $r[] = extension_loaded($ext) ? ['ok', 'Kengaytma ' . $ext, 'bor'] : ['fail', 'Kengaytma ' . $ext, 'YO\'Q — hosting panelida yoqing'];
        }
        $r[] = extension_loaded('simplexml') ? ['ok', 'Kengaytma simplexml', 'bor'] : ['warn', 'Kengaytma simplexml', 'yo\'q — faqat 📰 RSS ishlamaydi'];

        $problems = (new Config($this->cfg))->problems();
        $r[] = $problems ? ['fail', 'config.php', 'to\'ldirilmagan: ' . implode(', ', $problems)] : ['ok', 'config.php', 'asosiy sozlamalar to\'liq'];
        $admins = array_filter((array) ($this->cfg['admin_ids'] ?? []), static function ($v) {
            return (int) $v > 0;
        });
        $r[] = $admins ? ['ok', 'Adminlar', count($admins) . ' ta'] : ['warn', 'Adminlar', 'admin_ids bo\'sh — admin paneli va karta cheklari ishlamaydi'];

        // Baza va jadvallar
        $db = $this->app->db;
        try {
            $db->value('SELECT 1');
            $r[] = ['ok', 'Baza', 'ulandi'];
            $have = array_map('strval', array_map('current', $db->all('SHOW TABLES')));
            preg_match_all('/CREATE TABLE IF NOT EXISTS (\w+)/', (string) @file_get_contents($this->root . '/sql/schema.sql'), $m);
            $missing = array_values(array_diff($m[1], $have));
            $r[] = $missing ? ['fail', 'Jadvallar', 'yo\'q: ' . implode(', ', array_slice($missing, 0, 8)) . ' — setup.php ni ishga tushiring']
                : ['ok', 'Jadvallar', count($m[1]) . ' ta, hammasi bor'];
        } catch (\Throwable $e) {
            $r[] = ['fail', 'Baza', 'ulanib bo\'lmadi — db_* sozlamalarini tekshiring'];
            return $r; // baza yo'q bo'lsa qolgan tekshiruvlar ma'nosiz
        }

        // Token va webhook
        $me = $this->app->tg->call('getMe', []);
        if (empty($me['ok'])) {
            $d = (string) ($me['description'] ?? '');
            $r[] = ['fail', 'Bot tokeni', stripos($d, 'network') === 0 ? 'Telegram\'ga ulanib bo\'lmadi (' . $d . ')' : 'ishlamayapti: ' . $d];
        } else {
            $real = (string) ($me['result']['username'] ?? '');
            $same = strcasecmp($real, ltrim((string) ($this->cfg['bot_username'] ?? ''), '@')) === 0;
            $r[] = $same ? ['ok', 'Bot', '@' . $real] : ['fail', 'Bot', 'bot_username noto\'g\'ri: token @' . $real . ' botiniki'];
            $wh = $this->app->tg->call('getWebhookInfo', []);
            $info = is_array($wh['result'] ?? null) ? $wh['result'] : [];
            $url = (string) ($info['url'] ?? '');
            $want = (string) ($this->cfg['webhook_url'] ?? '');
            if ($url === '') {
                $r[] = ['fail', 'Webhook', 'o\'rnatilmagan — setup.php ni oching'];
            } elseif ($want !== '' && $url !== $want) {
                $r[] = ['fail', 'Webhook', 'boshqa manzilga qaragan (config bilan mos emas) — setup.php ni qayta oching'];
            } else {
                $r[] = ['ok', 'Webhook', 'o\'rnatilgan'];
            }
            $pending = (int) ($info['pending_update_count'] ?? 0);
            $r[] = $pending > 20 ? ['warn', 'Kutilayotgan yangilanishlar', $pending . ' ta — webhook xato bermoqda bo\'lishi mumkin'] : ['ok', 'Kutilayotgan yangilanishlar', (string) $pending];
            $err = (string) ($info['last_error_message'] ?? '');
            $errAt = (int) ($info['last_error_date'] ?? 0);
            if ($err !== '' && $errAt > time() - 3600) {
                $r[] = ['fail', 'Telegram webhook xatosi (oxirgi soat)', mb_substr($err, 0, 160)];
            } else {
                $r[] = ['ok', 'Telegram webhook xatosi', 'oxirgi soatda yo\'q'];
            }
        }

        // Cron
        $last = '';
        try {
            $last = (string) $db->value("SELECT v FROM bot_settings WHERE k = 'cron_last'");
        } catch (\Throwable $e) {
        }
        if ($last === '') {
            $r[] = ['fail', 'Cron', 'hali bir marta ham ishlamagan — hostingda cron.php ni HAR DAQIQA ishga tushiring (rejalangan postlar chiqmaydi)'];
        } else {
            $ago = time() - (int) strtotime($last . ' UTC');
            $r[] = $ago <= 180 ? ['ok', 'Cron', 'ishlayapti (oxirgisi ' . max(0, $ago) . ' soniya oldin)']
                : ['fail', 'Cron', 'to\'xtagan: oxirgisi ' . (int) ($ago / 60) . ' daqiqa oldin — har daqiqa ishlashi kerak'];
        }

        // Navbat
        try {
            $q = $db->one("SELECT SUM(status = 'pending') AS p, SUM(status = 'failed') AS f, SUM(status = 'pending' AND scheduled_time < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE)) AS late FROM scheduled_posts") ?? [];
            $late = (int) ($q['late'] ?? 0);
            $r[] = $late > 0 ? ['warn', 'Navbat', $late . ' ta post vaqtidan 10+ daqiqa kechikkan (cron yoki bot admin huquqini tekshiring)']
                : ['ok', 'Navbat', 'navbatda ' . (int) ($q['p'] ?? 0) . ', chiqmagan ' . (int) ($q['f'] ?? 0)];
            $r[] = ['ok', 'Foydalanuvchilar / kanallar', (int) $db->value('SELECT COUNT(*) FROM users') . ' / ' . (int) $db->value('SELECT COUNT(*) FROM channels WHERE is_active = 1')];
        } catch (\Throwable $e) {
        }

        // AI
        if (!$this->app->ai->enabled()) {
            $r[] = ['warn', 'AI', 'kalit yo\'q — AI tugmalari ko\'rinmaydi (bot qolgan hamma ishni qiladi)'];
        } elseif ($checkAi) {
            foreach ($this->app->ai->check() as $name => $res) {
                $r[] = strpos($res, 'OK') === 0 ? ['ok', 'AI ' . $name, $res] : ['fail', 'AI ' . $name, $res];
            }
            $r[] = $this->app->ai->mediaEnabled() ? ['ok', 'Rasm/ovozdan post', 'yoqilgan (Gemini)'] : ['warn', 'Rasm/ovozdan post', 'o\'chiq — gemini_api_key kerak'];
        }

        // To'lov sozlamalari
        $card = trim((string) ($this->cfg['card_number'] ?? ''));
        $r[] = $card === '' ? ['warn', 'Karta to\'lovi', 'o\'chiq (faqat Telegram Stars)'] : ['ok', 'Karta to\'lovi', 'yoqilgan'];
        $r[] = trim((string) ($this->cfg['payme_merchant_id'] ?? '')) === '' ? ['warn', 'Payme', 'o\'chiq'] : ['ok', 'Payme', 'yoqilgan'];

        // Fayl tizimi
        $st = $this->root . '/storage';
        $r[] = is_dir($st) && is_writable($st) ? ['ok', 'storage/ papkasi', 'yoziladi'] : ['fail', 'storage/ papkasi', 'yozib bo\'lmaydi — papkaga yozish huquqi (chmod 755/775) bering'];

        // Oxirgi log xatolari
        $log = $st . '/bot.log';
        if (is_file($log)) {
            $lines = array_slice(array_filter(explode("\n", (string) @file_get_contents($log, false, null, max(0, (int) filesize($log) - 20000)))), -5);
            $bad = [];
            foreach ($lines as $ln) {
                if (stripos($ln, 'xato') !== false || stripos($ln, 'ishlamadi') !== false) {
                    $bad[] = $this->scrub($ln);
                }
            }
            $r[] = $bad ? ['warn', 'Oxirgi xatolar (bot.log)', implode("\n", $bad)] : ['ok', 'bot.log', 'oxirgi yozuvlarda xato yo\'q'];
        } else {
            $r[] = ['ok', 'bot.log', 'hali xato yozilmagan'];
        }
        return $r;
    }

    /** Logdan token/kalit bo'lishi mumkin bo'lgan qismlarni yashiradi. */
    private function scrub(string $s): string
    {
        foreach (['bot_token', 'gemini_api_key', 'groq_api_key', 'openrouter_api_key', 'db_pass', 'webhook_secret', 'cron_key', 'payme_key'] as $k) {
            $v = (string) ($this->cfg[$k] ?? '');
            if (strlen($v) >= 6) {
                $s = str_replace($v, '***', $s);
            }
        }
        return mb_substr($s, 0, 220);
    }

    /** @param array<int, array{0:string,1:string,2:string}> $rows */
    public static function summary(array $rows): string
    {
        $f = count(array_filter($rows, static function ($x) {
            return $x[0] === 'fail';
        }));
        $w = count(array_filter($rows, static function ($x) {
            return $x[0] === 'warn';
        }));
        return $f > 0 ? "❌ MUAMMO BOR: {$f} ta xato, {$w} ta ogohlantirish" : ($w > 0 ? "⚠️ Ishlayapti, {$w} ta ogohlantirish" : '✅ HAMMASI YAXSHI');
    }
}
