<?php
declare(strict_types=1);

namespace PostAssist;

use PostAssist\Handlers\AdminHandler;
use PostAssist\Handlers\AiHandler;
use PostAssist\Handlers\AutopilotHandler;
use PostAssist\Handlers\ContentPlanHandler;
use PostAssist\Handlers\BroadcastHandler;
use PostAssist\Handlers\CardHandler;
use PostAssist\Handlers\ForceSubHandler;
use PostAssist\Handlers\HiddenHandler;
use PostAssist\Handlers\ChannelHandler;
use PostAssist\Handlers\LinksHandler;
use PostAssist\Handlers\MarketHandler;
use PostAssist\Handlers\PlansHandler;
use PostAssist\Handlers\PostHandler;
use PostAssist\Handlers\QueueHandler;
use PostAssist\Handlers\ReactionHandler;
use PostAssist\Handlers\RssHandler;
use PostAssist\Handlers\SentHandler;
use PostAssist\Handlers\SettingsHandler;
use PostAssist\Handlers\StartHandler;
use PostAssist\Handlers\TeamHandler;
use PostAssist\Repo\TrackedLinks;

/**
 * Telegram yangilanishini tegishli bo'limga yo'naltiradi. Faqat shaxsiy chatdagi xabar va tugmalar ishlanadi;
 * kanal holatining o'zgarishi (bot chiqarildi) — `my_chat_member` orqali.
 */
final class Router
{
    public const GO_TARGETS = ['go_market', 'go_team', 'go_plans', 'go_channels'];

    private const MENU_KEYS = ['btn_create_content', 'btn_ai_post', 'btn_my_channels', 'btn_scheduled', 'btn_statistics', 'btn_settings', 'btn_admin'];

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
        if (isset($update['pre_checkout_query'])) {
            PlansHandler::preCheckout($this->app, $update['pre_checkout_query']);
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
        $link = null;
        if (preg_match('/^\/start(?:@\w+)?(?:\s+(\S+))?$/u', $text, $m)) {
            $startArg = $m[1] ?? '';
            $code = TrackedLinks::codeFromPayload($startArg);
            if (preg_match('/^ref_(\d{1,20})$/', $startArg, $r)) {
                $referrer = (int) $r[1];
            } elseif ($code !== null) {
                $link = $this->app->links->active($code);
                if ($link && $link['owner_id'] !== null) {
                    $referrer = (int) $link['owner_id']; // hamkor havolasi = uning taklifi (faqat yangi foydalanuvchiga)
                }
            }
        }
        $ctx = $this->ctxFor($msg['from'], (int) $msg['chat']['id'], $msg, null, $referrer);
        if ($ctx === null) {
            return;
        }
        if ($link) {
            $this->app->links->recordVisit((int) $link['id'], $ctx->userId, $ctx->isNew, $this->app->now());
        }
        if (isset($msg['successful_payment']) && is_array($msg['successful_payment'])) {
            PlansHandler::paid($ctx, $msg['successful_payment']);
            return;
        }
        if (!ForceSubHandler::gate($ctx)) {
            return; // majburiy obuna: avval kanallarga a'zo bo'ling
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
        if (isset($msg['voice']) && is_array($msg['voice']) && ($state === null || in_array($state['state'], ['post_content', 'post_edit', 'post_preview', 'intake', 'ai_topic', 'ai_style'], true))) {
            AiHandler::voice($ctx); // 🎤 ovozdan post
            return;
        }
        $group = isset($msg['media_group_id']) ? (string) $msg['media_group_id'] : '';
        if ($group !== '' && $state !== null && ($state['data']['draft']['group'] ?? null) === $group
            && in_array($state['state'], ['post_preview', 'post_pick'], true)) {
            PostHandler::albumLate($ctx, $state); // shu albomning kechikib kelgan qismi — qoralamaga qo'shiladi
            return;
        }
        if ($group !== '' && ($state === null || !in_array($state['state'], ['post_content', 'post_edit'], true))) {
            // albom post kutilmagan joyda keldi: har qismga emas, faqat bir marta javob
            if ($this->app->albums->claim($ctx->userId, $group)) {
                $ctx->replyMenu($ctx->t('unknown'));
            }
            return;
        }
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
                case 'post_time2':
                    PostHandler::secondTimeInput($ctx, $state);
                    return;
                case 'post_rx':
                    PostHandler::reactionsInput($ctx, $state);
                    return;
                case 'rss_url':
                    RssHandler::urlInput($ctx, $state);
                    return;
                case 'sent_edit':
                    SentHandler::editInput($ctx, $state);
                    return;
                case 'post_hidden':
                    PostHandler::hiddenInput($ctx, $state);
                    return;
                case 'tz_wait':
                    SettingsHandler::setTimezone($ctx, $text);
                    return;
                case 'mk_phone':
                    MarketHandler::phone($ctx);
                    return;
                case 'mk_price':
                    MarketHandler::priceInput($ctx, $state);
                    return;
                case 'mk_desc':
                    MarketHandler::descInput($ctx, $state);
                    return;
                case 'mk_msg':
                    MarketHandler::message($ctx, $state);
                    return;
                case 'receipt_wait':
                    CardHandler::receipt($ctx, $state);
                    return;
                case 'uz_verify':
                    CardHandler::contact($ctx);
                    return;
                case 'bc_wait':
                    if ($this->app->isAdmin($ctx->userId)) {
                        BroadcastHandler::received($ctx);
                    }
                    return;
                case 'cp_topic':
                    ContentPlanHandler::topicInput($ctx);
                    return;
                case 'ap_topic':
                    AutopilotHandler::topicInput($ctx, $state);
                    return;
                case 'ap_time':
                    AutopilotHandler::time($ctx, $text);
                    return;
                case 'ai_topic':
                case 'ai_style':
                    AiHandler::topicInput($ctx); // uslub o'rniga yana matn yozsa — yangi mavzu
                    return;
                case 'intake':
                    if (AiHandler::intake($ctx)) {
                        return;
                    }
                    break;
                case 'promo_wait':
                    if ($text !== '') {
                        PlansHandler::redeem($ctx, $text);
                    } else {
                        $ctx->reply($ctx->t('promo_ask'));
                    }
                    return;
            }
        }
        // Holatsiz: kanaldan forward qilingan post — kanal ulash urinishi
        if (isset($msg['forward_origin']['chat']) || isset($msg['forward_from_chat'])) {
            ChannelHandler::receive($ctx);
            return;
        }
        if (AiHandler::intake($ctx)) {
            return; // matn/rasm: «Bu bilan nima qilamiz?»
        }
        $ctx->replyMenu($ctx->t('unknown'));
    }

    private function command(Ctx $ctx, string $text): bool
    {
        $parts = preg_split('/\s+/u', trim($text)) ?: [];
        $cmd = strtolower((string) preg_replace('/@\w+$/', '', (string) array_shift($parts)));
        $args = array_values(array_filter($parts, static function ($a) {
            return $a !== '';
        }));
        switch ($cmd) {
            case '/start':
                $this->app->states->clear($ctx->userId);
                if (isset($args[0]) && preg_match('/^team_([a-f0-9]{24})$/', $args[0], $tm)) {
                    TeamHandler::accept($ctx, $tm[1]); // jamoa taklifi
                    return true;
                }
                // Mini App -> bot: faqat ruxsat etilgan bo'limlar (app.php BOT_SECTIONS bilan bir xil).
                if (isset($args[0]) && in_array($args[0], self::GO_TARGETS, true)) {
                    $go = $args[0];
                    if ($go === 'go_market') {
                        MarketHandler::home($ctx);
                    } elseif ($go === 'go_team') {
                        TeamHandler::show($ctx, false);
                    } elseif ($go === 'go_plans') {
                        PlansHandler::show($ctx);
                    } else {
                        ChannelHandler::show($ctx);
                    }
                    return true;
                }
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
            case '/timezone':
                SettingsHandler::askTimezone($ctx);
                return true;
            case '/lang':
                $ctx->reply($ctx->t('lang_choose'), Keyboards::languages());
                return true;
            case '/stats':
                StartHandler::stats($ctx);
                return true;
            case '/app':
            case '/miniapp':
                $url = $this->app->miniAppUrl();
                if ($url === null) {
                    $ctx->replyMenu($ctx->t('miniapp_off'));
                } else {
                    $ctx->reply($ctx->t('miniapp_open'), Keyboards::inline([[['text' => $ctx->t('btn_miniapp'), 'web_app' => ['url' => $url]]], Keyboards::navRow($ctx->lang)]));
                }
                return true;
            case '/ai':
                $this->app->states->clear($ctx->userId);
                AiHandler::start($ctx);
                return true;
            case '/market':
                MarketHandler::home($ctx);
                return true;
            case '/rss':
                $this->app->states->clear($ctx->userId);
                RssHandler::show($ctx, false);
                return true;
            case '/sent':
                $this->app->states->clear($ctx->userId);
                SentHandler::show($ctx, false);
                return true;
            case '/contentplan':
                $this->app->states->clear($ctx->userId);
                ContentPlanHandler::show($ctx);
                return true;
            case '/autopilot':
                $this->app->states->clear($ctx->userId);
                AutopilotHandler::show($ctx);
                return true;
            case '/team':
                TeamHandler::show($ctx, false);
                return true;
            case '/plans':
                $this->app->states->clear($ctx->userId);
                PlansHandler::show($ctx);
                return true;
            case '/invite':
                PlansHandler::referral($ctx);
                return true;
            case '/mylinks':
                LinksHandler::mine($ctx);
                return true;
            case '/admin':
                if ($this->app->isAdmin($ctx->userId)) {
                    AdminHandler::show($ctx);
                    return true;
                }
                return false;
        }
        if (AdminHandler::command($ctx, $cmd, $args)) {
            return true;
        }
        if ($cmd === '/promo') {
            // oddiy foydalanuvchi: /promo KOD — darhol, /promo — so'raydi
            $args ? PlansHandler::redeem($ctx, $args[0]) : PlansHandler::askPromo($ctx);
            return true;
        }
        return false;
    }

    private function menu(Ctx $ctx, string $key): void
    {
        switch ($key) {
            case 'btn_create_content':
                PostHandler::begin($ctx);
                return;
            case 'btn_ai_post':
                AiHandler::start($ctx);
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
        if (isset($cq['from']) && is_array($chat) && ($cq['data'] ?? '') === 'hd') {
            HiddenHandler::press($this->app, $cq); // 🔒 yashirin matn (kanalda yoki preview'da)
            return;
        }
        if (isset($cq['from']) && is_array($chat) && preg_match('/^rx:([0-5])$/', (string) ($cq['data'] ?? ''), $rm)) {
            ReactionHandler::press($this->app, $cq, (int) $rm[1]); // kanal postidagi reaksiya tugmasi
            return;
        }
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
        if ($data === 'fs:check') {
            ForceSubHandler::check($ctx);
            return;
        }
        if (!ForceSubHandler::gate($ctx)) {
            return;
        }
        if (preg_match('/^lang:(uz|ru|en)$/', $data, $m)) {
            SettingsHandler::setLang($ctx, $m[1]);
        } elseif ($data === 'm:home') {
            StartHandler::home($ctx);
        } elseif ($data === 'set:show') {
            $this->app->states->clear($ctx->userId);
            SettingsHandler::show($ctx, true);
        } elseif ($data === 'set:lang') {
            $ctx->edit($ctx->t('lang_choose'), Keyboards::languages($ctx->lang));
        } elseif ($data === 'pl:show') {
            PlansHandler::show($ctx, true);
        } elseif (preg_match('/^pl:t:(pro|ultra)$/', $data, $m)) {
            PlansHandler::periods($ctx, $m[1]);
        } elseif (preg_match('/^pl:b:(u?(?:1m|3m|6m|1y))$/', $data, $m)) {
            PlansHandler::invoice($ctx, $m[1]);
        } elseif ($data === 'ref:show') {
            PlansHandler::referral($ctx);
        } elseif ($data === 'promo:ask') {
            PlansHandler::askPromo($ctx);
        } elseif ($data === 'set:help') {
            $ctx->edit($ctx->t('help'), Keyboards::nav($ctx->lang, 'set:show'));
        } elseif ($data === 'p:new') {
            $this->app->states->clear($ctx->userId);
            PostHandler::begin($ctx);
        } elseif ($data === 'p:ai') {
            AiHandler::editMenu($ctx);
        } elseif ($data === 'cp:show') {
            $this->app->states->clear($ctx->userId);
            ContentPlanHandler::show($ctx);
        } elseif ($data === 'cp:new') {
            ContentPlanHandler::ask($ctx);
        } elseif (preg_match('/^cp:w:(\d{1,10}):(\d)$/', $data, $m)) {
            ContentPlanHandler::write($ctx, (int) $m[1], (int) $m[2]);
        } elseif ($data === 'ap:show') {
            $this->app->states->clear($ctx->userId);
            AutopilotHandler::show($ctx, true);
        } elseif ($data === 'ap:new') {
            AutopilotHandler::begin($ctx);
        } elseif (preg_match('/^ap:st:(news|sales|fun|useful|short)$/', $data, $m)) {
            AutopilotHandler::style($ctx, $m[1]);
        } elseif (preg_match('/^ap:t:(\d{4})$/', $data, $m)) {
            AutopilotHandler::time($ctx, $m[1]);
        } elseif (preg_match('/^ap:m:(review|auto)$/', $data, $m)) {
            AutopilotHandler::mode($ctx, $m[1]);
        } elseif (preg_match('/^ap:(ch|v|tg|mo|del|dok|run):(\d{1,10})$/', $data, $m)) {
            $id = (int) $m[2];
            if ($m[1] === 'ch') {
                AutopilotHandler::pickChannel($ctx, $id);
            } elseif ($m[1] === 'v') {
                AutopilotHandler::view($ctx, $id);
            } elseif ($m[1] === 'tg') {
                AutopilotHandler::toggle($ctx, $id);
            } elseif ($m[1] === 'mo') {
                AutopilotHandler::switchMode($ctx, $id);
            } elseif ($m[1] === 'del') {
                AutopilotHandler::askDelete($ctx, $id);
            } elseif ($m[1] === 'dok') {
                AutopilotHandler::delete($ctx, $id);
            } else {
                AutopilotHandler::testNow($ctx, $id);
            }
        } elseif (preg_match('/^apd:(ok|ed|re|no):(\d{1,10})$/', $data, $m)) {
            AutopilotHandler::draftAction($ctx, $m[1], (int) $m[2]);
        } elseif ($data === 'ai:again') {
            AiHandler::again($ctx);
        } elseif (preg_match('/^ai:s:(news|sales|fun|useful|short)$/', $data, $m)) {
            AiHandler::style($ctx, $m[1]);
        } elseif (preg_match('/^ai:e:(improve|shorten|emoji|rewrite|tr_uz|tr_ru|tr_en)$/', $data, $m)) {
            AiHandler::edit($ctx, $m[1]);
        } elseif (preg_match('/^in:(post|ai|close)$/', $data, $m)) {
            AiHandler::intakeChoice($ctx, $m[1]);
        } elseif ($data === 'mk:home') {
            MarketHandler::home($ctx, true);
        } elseif ($data === 'mk:cat') {
            MarketHandler::categories($ctx);
        } elseif (preg_match('/^mk:l:([a-z]{2,14}):(\d{1,4})$/', $data, $m)) {
            MarketHandler::listing($ctx, in_array($m[1], \PostAssist\Repo\Market::CATEGORIES, true) ? $m[1] : 'all', (int) $m[2]);
        } elseif (preg_match('/^mk:(v|ask|rep|hide|del|upd|pc|re|ct|bl|fr|t):(\d{1,10})$/', $data, $m)) {
            $id = (int) $m[2];
            $map = ['v' => 'view', 'ask' => 'ask', 'rep' => 'report', 'hide' => 'toggle', 'del' => 'delete', 'upd' => 'refresh', 'pc' => 'pickChannel',
                're' => 'reply', 'ct' => 'contact', 'bl' => 'block', 'fr' => 'fraud', 't' => 'thread'];
            $fn = $map[$m[1]];
            MarketHandler::$fn($ctx, $id);
        } elseif ($data === 'mk:pub') {
            MarketHandler::publish($ctx);
        } elseif ($data === 'mk:my') {
            MarketHandler::mine($ctx);
        } elseif ($data === 'mk:th') {
            MarketHandler::threads($ctx);
        } elseif (preg_match('/^mk:cs:([a-z]{2,14})$/', $data, $m) && in_array($m[1], \PostAssist\Repo\Market::CATEGORIES, true)) {
            MarketHandler::saveCategory($ctx, $m[1]);
        } elseif ($data === 'set:team') {
            TeamHandler::show($ctx);
        } elseif ($data === 'tm:inv') {
            TeamHandler::askPreset($ctx);
        } elseif (preg_match('/^tm:ip:(all|editor|viewer)$/', $data, $m)) {
            TeamHandler::invite($ctx, $m[1]);
        } elseif (preg_match('/^tm:rm:(\d{1,20})$/', $data, $m)) {
            TeamHandler::askRemove($ctx, (int) $m[1]);
        } elseif (preg_match('/^tm:rmok:(\d{1,20})$/', $data, $m)) {
            TeamHandler::remove($ctx, (int) $m[1]);
        } elseif (preg_match('/^tm:lv:(\d{1,20})$/', $data, $m)) {
            TeamHandler::leave($ctx, (int) $m[1]);
        } elseif (preg_match('/^tm:ws:(\d{1,20})$/', $data, $m)) {
            TeamHandler::switchTo($ctx, (int) $m[1]);
        } elseif ($data === 'pl:card') {
            CardHandler::start($ctx);
        } elseif (preg_match('/^pl:ct:(pro|ultra)$/', $data, $m)) {
            CardHandler::periods($ctx, $m[1]);
        } elseif (preg_match('/^pl:pm:(u?(?:1m|3m|6m|1y))$/', $data, $m)) {
            CardHandler::payme($ctx, $m[1]);
        } elseif (preg_match('/^pl:cb:(u?(?:1m|3m|6m|1y))$/', $data, $m)) {
            CardHandler::details($ctx, $m[1]);
        } elseif (preg_match('/^rc:(ok|no):(\d{1,10})$/', $data, $m)) {
            CardHandler::decide($ctx, $m[1], (int) $m[2]);
        } elseif (preg_match('/^bc:(go|no)$/', $data, $m)) {
            BroadcastHandler::confirm($ctx, $m[1] === 'go');
        } elseif (preg_match('/^a:(stats|promos|links|help|bc|fs)$/', $data, $m)) {
            if ($this->app->isAdmin($ctx->userId)) {
                $map = ['promos' => '/promos', 'links' => '/links', 'help' => '/admin_help', 'bc' => '/broadcast', 'fs' => '/force_list'];
                $m[1] === 'stats' ? AdminHandler::show($ctx) : AdminHandler::command($ctx, $map[$m[1]], []);
            }
        } elseif ($data === 'ch:add') {
            ChannelHandler::askAdd($ctx);
        } elseif ($data === 'ch:list') {
            ChannelHandler::show($ctx, true);
        } elseif (preg_match('/^ch:del:(\d{1,10})$/', $data, $m)) {
            ChannelHandler::askDelete($ctx, (int) $m[1]);
        } elseif (preg_match('/^ch:delok:(\d{1,10})$/', $data, $m)) {
            ChannelHandler::delete($ctx, (int) $m[1]);
        } elseif (preg_match('/^pm:(\d{1,10})$/', $data, $m)) {
            PostHandler::extraChannels($ctx, (int) $m[1]);
        } elseif (preg_match('/^p:ch:(\d{1,10})$/', $data, $m)) {
            PostHandler::pickChannel($ctx, (int) $m[1]);
        } elseif (preg_match('/^p:(now|time|more|btn|btndel|rep|rx|ad|edit|cancel|back|hidden|hddel|o_silent|o_nopreview|o_pin|o_protect|mc)$/', $data, $m)) {
            PostHandler::action($ctx, $m[1]);
        } elseif (preg_match('/^pr:(none|daily|weekly|monthly|twice)$/', $data, $m)) {
            PostHandler::setRepeat($ctx, $m[1]);
        } elseif (preg_match('/^px:([0-3]|c|none)$/', $data, $m)) {
            PostHandler::setReactions($ctx, $m[1]);
        } elseif (preg_match('/^pa:(\d{1,4})$/', $data, $m)) {
            PostHandler::setAutoDelete($ctx, (int) $m[1]);
        } elseif ($data === 'set:tz') {
            SettingsHandler::askTimezone($ctx);
        } elseif (preg_match('/^tz:([A-Za-z_\/]{2,40})$/', $data, $m)) {
            SettingsHandler::setTimezone($ctx, $m[1]);
        } elseif (preg_match('/^t:(1h|today18|tom09)$/', $data, $m)) {
            PostHandler::quickTime($ctx, $m[1]);
        } elseif ($data === 'rss:show') {
            $this->app->states->clear($ctx->userId);
            RssHandler::show($ctx);
        } elseif ($data === 'rss:new') {
            RssHandler::begin($ctx);
        } elseif (preg_match('/^rss:(ch|v|tg|del|dok|last):(\d{1,10})$/', $data, $m)) {
            $rid = (int) $m[2];
            if ($m[1] === 'ch') {
                RssHandler::pickChannel($ctx, $rid);
            } elseif ($m[1] === 'v') {
                RssHandler::view($ctx, $rid);
            } elseif ($m[1] === 'tg') {
                RssHandler::toggle($ctx, $rid);
            } elseif ($m[1] === 'del') {
                RssHandler::askDelete($ctx, $rid);
            } elseif ($m[1] === 'dok') {
                RssHandler::delete($ctx, $rid);
            } else {
                RssHandler::postLatest($ctx, $rid);
            }
        } elseif ($data === 's:list') {
            $this->app->states->clear($ctx->userId);
            SentHandler::show($ctx);
        } elseif (preg_match('/^s:(v|e|d|dok):(\d{1,10})$/', $data, $m)) {
            $sid = (int) $m[2];
            if ($m[1] === 'v') {
                $this->app->states->clear($ctx->userId);
                SentHandler::view($ctx, $sid);
            } elseif ($m[1] === 'e') {
                SentHandler::askEdit($ctx, $sid);
            } elseif ($m[1] === 'd') {
                SentHandler::askDelete($ctx, $sid);
            } else {
                SentHandler::delete($ctx, $sid);
            }
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
