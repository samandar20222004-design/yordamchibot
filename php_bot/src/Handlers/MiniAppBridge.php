<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\I18n;
use PostAssist\Router;
use PostAssist\Telegram;

/**
 * 🌉 Mini App ↔ bot ko'prigi: botdagi HAR BIR ekran (autopilot, kontent-reja, RSS, shablonlar, ko'p post, so'rovnoma, jamoa,
 * taklif, promo, hisobot, kanallar…) Mini App ichida ham ishlaydi — bot mantiqi bitta, ikki marta yozilmaydi.
 * Tugma bosilishi (`d`) yoki matn (`t`) odatdagi yangilanish sifatida Router'dan o'tkaziladi; foydalanuvchi chatiga ketadigan
 * xabarlar yuborilmaydi — ushlanib, Mini App'ga ekran sifatida qaytariladi. Kanalga yuborish, getChat va hokazo — haqiqiy.
 */
final class MiniAppBridge
{
    /** @return array{0:int,1:array} */
    public static function run(App $app, array $user, array $in): array
    {
        $uid = (int) $user['id'];
        $data = isset($in['d']) ? (string) $in['d'] : null;
        $text = isset($in['t']) ? (string) $in['t'] : null;
        if (($data === null || $data === '' || strlen($data) > 64) && ($text === null || trim($text) === '' || strlen($text) > 6000)) {
            return [400, ['ok' => false, 'error' => 'bad_input']];
        }
        $from = ['id' => $uid, 'is_bot' => false, 'first_name' => (string) ($user['first_name'] ?? ''), 'last_name' => (string) ($user['last_name'] ?? ''),
            'username' => (string) ($user['username'] ?? ''), 'language_code' => (string) ($user['language_code'] ?? ''), 'is_premium' => !empty($user['is_premium'])];
        $chat = ['id' => $uid, 'type' => 'private'];
        if ($data !== null && $data !== '') {
            $update = ['update_id' => 0, 'callback_query' => ['id' => 'mini', 'from' => $from, 'data' => $data,
                'message' => ['message_id' => 1, 'chat' => $chat, 'text' => 'x']]];
        } else {
            $update = ['update_id' => 0, 'message' => ['message_id' => 1, 'from' => $from, 'chat' => $chat, 'date' => time(), 'text' => (string) $text]];
        }

        // «◀️ Orqaga» va «🏠 Menyu» faqat botda: Mini App'da tepada Telegram «orqaga» tugmasi, pastda bosh sahifa bor
        $nav = [];
        foreach (I18n::LANGS as $l) {
            $nav[I18n::bare(I18n::t('btn_back', $l))] = true;
            $nav[I18n::bare(I18n::t('btn_home', $l))] = true;
        }
        $screens = [];
        $menu = false;
        $botLink = false;
        $real = $app->tg;
        $transport = static function (string $method, array $p) use (&$screens, &$menu, &$botLink, $real, $uid, $nav): array {
            $private = isset($p['chat_id']) && (int) $p['chat_id'] === $uid;
            if ($method === 'answerCallbackQuery') {
                return ['ok' => true, 'result' => true];
            }
            if (!$private) {
                return $real->call($method, $p); // kanal, getChat, getChatMember, deleteMessage (kanalda) … — haqiqiy
            }
            if (in_array($method, ['sendMessage', 'editMessageText', 'sendPhoto', 'sendVideo', 'sendDocument', 'sendAnimation', 'sendAudio', 'copyMessage', 'sendInvoice'], true)) {
                $kb = $p['reply_markup'] ?? null;
                $kb = is_string($kb) ? json_decode($kb, true) : $kb;
                $rows = [];
                if (is_array($kb) && isset($kb['inline_keyboard'])) {
                    foreach ($kb['inline_keyboard'] as $row) {
                        $r = [];
                        foreach ((array) $row as $b) {
                            if (!isset($b['text'])) {
                                continue;
                            }
                            if (($b['callback_data'] ?? '') === 'm:home' || isset($nav[I18n::bare((string) $b['text'])])) {
                                continue;
                            }
                            $item = ['t' => (string) $b['text']];
                            if (isset($b['callback_data'])) {
                                $item['d'] = (string) $b['callback_data'];
                            } elseif (isset($b['url'])) {
                                $item['u'] = (string) $b['url'];
                            } elseif (isset($b['web_app'])) {
                                continue; // Mini App ichida web_app tugmasi kerak emas
                            } else {
                                continue;
                            }
                            $r[] = $item;
                        }
                        if ($r) {
                            $rows[] = $r;
                        }
                    }
                } elseif (is_array($kb) && isset($kb['keyboard'])) {
                    if (strpos(json_encode($kb), 'request_contact') !== false) {
                        $botLink = true; // kontakt so'rash faqat bot chatida ishlaydi
                    } else {
                        $menu = true; // bosh menyu klaviaturasi = oqim tugadi
                    }
                }
                $txt = (string) ($p['text'] ?? $p['caption'] ?? '');
                if ($method === 'sendInvoice') {
                    $botLink = true;
                    $txt = (string) ($p['title'] ?? '');
                }
                if ($txt !== '' || $rows) {
                    $screens[] = ['text' => $txt, 'rows' => $rows, 'edit' => $method === 'editMessageText'];
                }
            }
            return ['ok' => true, 'result' => ['message_id' => 1]];
        };

        $app->tg = new Telegram('x', 'https://x', $transport);
        try {
            (new Router($app))->handle($update);
        } catch (\Throwable $e) {
            $app->tg = $real;
            $app->log('miniapp bridge: ' . $e->getMessage());
            return [500, ['ok' => false, 'error' => 'server']];
        }
        $app->tg = $real;
        $state = $app->states->get($uid);
        // tahrirlar va xabarlar ichidan oxirgisi asosiy ekran (oldingilari — bildirishnoma kabi)
        return [200, ['ok' => true, 'screens' => $screens, 'menu' => $menu, 'bot_link' => $botLink, 'state' => $state['state'] ?? null]];
    }
}
