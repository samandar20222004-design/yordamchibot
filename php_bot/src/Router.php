<?php
declare(strict_types=1);

namespace PostAssist;

use PostAssist\Handlers\AdminHandler;
use PostAssist\Handlers\ChannelHandler;
use PostAssist\Handlers\PostHandler;
use PostAssist\Handlers\QueueHandler;
use PostAssist\Handlers\SettingsHandler;
use PostAssist\Handlers\StartHandler;

/**
 * Telegram yangilanishini tegishli bo'limga yo'naltiradi. Faqat shaxsiy chatdagi xabar va tugmalar ishlanadi;
 * kanal holatining o'zgarishi (bot chiqarildi) — `my_chat_member` orqali.
 */
final class Router
{
    private const MENU_KEYS = ['btn_create_content', 'btn_my_channels', 'btn_scheduled', 'btn_statistics', 'btn_settings', 'btn_admin'];

    private App $app;

    public function __construct(App $app)
    {
        $this->app = $app;
    }

    public function handle(array $update): void
    {
        $uid = (int) ($update['update_id'] ?? 0);
        if ($uid > 0 && $this->app->db->exec('INSERT IGNORE INTO processed_updates (update_id, created_at) VALUES (?, UTC_TIMESTAMP())', [$uid]) === 0) {
            return; // Telegram qayta yubordi — allaqachon ishlangan
        }
        if (isset($update['my_chat_member'])) {
            ChannelHandler::memberChanged($this->app, $update['my_chat_member']);
            return;
        }
        if (isset($update['callback_query'])) {
            $this->callback($update['callback_query']);
            return;
        }
        if (isset($update['message'])) {
            $this->message($update['message']);
        }
    }

    private function ctxFor(array $from, int $chatId, ?array $message, ?array $callback, ?int $referrer = null): ?Ctx
    {
        $userId = (int) ($from['id'] ?? 0);
        if ($userId <= 0 || !empty($from['is_bot'])) {
            return null;
        }
        $name = trim(((string) ($from['first_name'] ?? '')) . ' ' . ((string) ($from['last_name'] ?? '')));
        $saved = $this->app->users->upsert($userId, (string) ($from['username'] ?? ''), $name, I18n::detect($from['language_code'] ?? null), $referrer);
        $ctx = new Ctx($this->app, $userId, $chatId, I18n::norm($saved['lang']), (string) ($from['first_name'] ?? ''), $message, $callback);
        $ctx->isNew = $saved['is_new'];
        return $ctx;
    }

    private function message(array $msg): void
    {
        if (($msg['chat']['type'] ?? '') !== 'private' || !isset($msg['from'])) {
            return;
        }
        $text = isset($msg['text']) ? trim((string) $msg['text']) : '';
        $referrer = null;
        $startArg = '';
        if (preg_match('/^\/start(?:@\w+)?(?:\s+(\S+))?$/u', $text, $m)) {
            $startArg = $m[1] ?? '';
            if (preg_match('/^ref_(\d{1,20})$/', $startArg, $r)) {
                $referrer = (int) $r[1];
            }
        }
        $ctx = $this->ctxFor($msg['from'], (int) $msg['chat']['id'], $msg, null, $referrer);
        if ($ctx === null) {
            return;
        }
        $user = $this->app->users->get($ctx->userId);
        if ($user && (int) $user['is_blocked'] === 1) {
            $this->app->users->markBlocked($ctx->userId, false); // foydalanuvchi botni qayta ochdi
        }

        if ($text !== '' && $text[0] === '/') {
            if (!$this->command($ctx, $text)) {
                $ctx->replyMenu($ctx->t('unknown')); // noma'lum buyruq post matni bo'lib qolmasin
            }
            return;
        }
        $menu = $text !== '' ? I18n::keyOf($text, self::MENU_KEYS) : null;
        if ($menu !== null) {
            $this->app->states->clear($ctx->userId);
            $this->menu($ctx, $menu);
            return;
        }
        $state = $ctx->state();
        if ($state !== null) {
            switch ($state['state']) {
                case 'ch_wait':
                    ChannelHandler::receive($ctx);
                    return;
                case 'post_content':
                case 'post_edit':
                    PostHandler::content($ctx, $state);
                    return;
                case 'post_btn':
                    PostHandler::buttonInput($ctx, $state);
                    return;
                case 'post_time':
                    PostHandler::timeInput($ctx, $state);
                    return;
            }
        }
        // Holatsiz: kanaldan forward qilingan post — kanal ulash urinishi
        if (isset($msg['forward_origin']['chat']) || isset($msg['forward_from_chat'])) {
            ChannelHandler::receive($ctx);
            return;
        }
        $ctx->replyMenu($ctx->t('unknown'));
    }

    private function command(Ctx $ctx, string $text): bool
    {
        $cmd = strtolower((string) preg_replace('/@\w+$/', '', explode(' ', $text, 2)[0]));
        switch ($cmd) {
            case '/start':
                $this->app->states->clear($ctx->userId);
                StartHandler::start($ctx);
                return true;
            case '/help':
                $ctx->replyMenu($ctx->t('help'));
                return true;
            case '/cancel':
                $this->app->states->clear($ctx->userId);
                $ctx->replyMenu($ctx->t('cancelled'));
                return true;
            case '/newpost':
                $this->app->states->clear($ctx->userId);
                PostHandler::begin($ctx);
                return true;
            case '/queue':
                QueueHandler::show($ctx);
                return true;
            case '/channels':
                ChannelHandler::show($ctx);
                return true;
            case '/settings':
                SettingsHandler::show($ctx);
                return true;
            case '/lang':
                $ctx->reply($ctx->t('lang_choose'), Keyboards::languages());
                return true;
            case '/stats':
                StartHandler::stats($ctx);
                return true;
            case '/admin':
                if ($this->app->isAdmin($ctx->userId)) {
                    AdminHandler::show($ctx);
                    return true;
                }
                return false;
        }
        return false;
    }

    private function menu(Ctx $ctx, string $key): void
    {
        switch ($key) {
            case 'btn_create_content':
                PostHandler::begin($ctx);
                return;
            case 'btn_my_channels':
                ChannelHandler::show($ctx);
                return;
            case 'btn_scheduled':
                QueueHandler::show($ctx);
                return;
            case 'btn_statistics':
                StartHandler::stats($ctx);
                return;
            case 'btn_settings':
                SettingsHandler::show($ctx);
                return;
            case 'btn_admin':
                if ($this->app->isAdmin($ctx->userId)) {
                    AdminHandler::show($ctx);
                } else {
                    $ctx->replyMenu($ctx->t('unknown'));
                }
                return;
        }
    }

    private function callback(array $cq): void
    {
        $chat = $cq['message']['chat'] ?? null;
        if (!isset($cq['from']) || !is_array($chat) || ($chat['type'] ?? '') !== 'private') {
            if (isset($cq['id'])) {
                $this->app->tg->answerCallback((string) $cq['id']);
            }
            return;
        }
        $ctx = $this->ctxFor($cq['from'], (int) $chat['id'], null, $cq);
        $this->app->tg->answerCallback((string) $cq['id']);
        if ($ctx === null) {
            return;
        }
        $data = (string) ($cq['data'] ?? '');
        if (preg_match('/^lang:(uz|ru|en)$/', $data, $m)) {
            SettingsHandler::setLang($ctx, $m[1]);
        } elseif ($data === 'set:lang') {
            $ctx->edit($ctx->t('lang_choose'), Keyboards::languages());
        } elseif ($data === 'set:help') {
            $ctx->reply($ctx->t('help'));
        } elseif ($data === 'ch:add') {
            ChannelHandler::askAdd($ctx);
        } elseif ($data === 'ch:list') {
            ChannelHandler::show($ctx, true);
        } elseif (preg_match('/^ch:del:(\d{1,10})$/', $data, $m)) {
            ChannelHandler::askDelete($ctx, (int) $m[1]);
        } elseif (preg_match('/^ch:delok:(\d{1,10})$/', $data, $m)) {
            ChannelHandler::delete($ctx, (int) $m[1]);
        } elseif (preg_match('/^p:ch:(\d{1,10})$/', $data, $m)) {
            PostHandler::pickChannel($ctx, (int) $m[1]);
        } elseif (preg_match('/^p:(now|time|btn|btndel|edit|cancel|back)$/', $data, $m)) {
            PostHandler::action($ctx, $m[1]);
        } elseif (preg_match('/^t:(1h|today18|tom09)$/', $data, $m)) {
            PostHandler::quickTime($ctx, $m[1]);
        } elseif ($data === 'q:list') {
            QueueHandler::show($ctx, true);
        } elseif (preg_match('/^q:v:(\d{1,10})$/', $data, $m)) {
            QueueHandler::view($ctx, (int) $m[1]);
        } elseif (preg_match('/^q:d:(\d{1,10})$/', $data, $m)) {
            QueueHandler::askCancel($ctx, (int) $m[1]);
        } elseif (preg_match('/^q:dok:(\d{1,10})$/', $data, $m)) {
            QueueHandler::cancel($ctx, (int) $m[1]);
        }
    }
}
