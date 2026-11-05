<?php
// Integratsiya testi: haqiqiy MySQL/MariaDB + soxta Telegram (tarmoqsiz). Faqat SINOV bazasini bering — jadvallar o'chiriladi!
//   PA_TEST_DB_HOST, PA_TEST_DB_NAME, PA_TEST_DB_USER, PA_TEST_DB_PASS (standart: localhost / pa_test / pa / pa_pass)
declare(strict_types=1);

use PostAssist\App;
use PostAssist\Config;
use PostAssist\Db;
use PostAssist\Router;
use PostAssist\Services\Scheduler;
use PostAssist\Telegram;

final class FakeTg
{
    /** @var array<int, array{0:string,1:array}> */
    public array $calls = [];
    /** @var array<string|int, array> getChat javoblari: chat_id/@username => result */
    public array $chats = [];
    /** @var array<string, array> "chat|user" => getChatMember result */
    public array $members = [];
    /** @var array<string, array<int, array>> majburiy javoblar navbati: method => [javob, ...] */
    public array $forced = [];
    private int $mid = 1000;

    public function __invoke(string $method, array $params): array
    {
        $this->calls[] = [$method, $params];
        if (!empty($this->forced[$method])) {
            return array_shift($this->forced[$method]);
        }
        switch ($method) {
            case 'sendMediaGroup':
                $n = count((array) json_decode((string) ($params['media'] ?? '[]'), true));
                $out = [];
                for ($i = 0; $i < $n; $i++) {
                    $out[] = ['message_id' => ++$this->mid];
                }
                return ['ok' => true, 'result' => $out];
            case 'getChat':
                $c = $this->chats[$params['chat_id']] ?? null;
                return $c ? ['ok' => true, 'result' => $c] : ['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: chat not found'];
            case 'getChatMember':
                $m = $this->members[$params['chat_id'] . '|' . $params['user_id']] ?? null;
                return $m ? ['ok' => true, 'result' => $m] : ['ok' => false, 'error_code' => 400, 'description' => 'Bad Request: user not found'];
        }
        return ['ok' => true, 'result' => ['message_id' => ++$this->mid]];
    }

    public function reset(): void
    {
        $this->calls = [];
    }

    /** @return array<int, array> berilgan metod(lar) chaqiruvlari */
    public function of(string ...$methods): array
    {
        $out = [];
        foreach ($this->calls as $c) {
            if (in_array($c[0], $methods, true)) {
                $out[] = $c[1];
            }
        }
        return $out;
    }

    public function lastText(): string
    {
        $all = $this->of('sendMessage', 'editMessageText');
        return $all ? (string) end($all)['text'] : '';
    }

    public function texts(): string
    {
        return implode("\n---\n", array_map(static function ($p) {
            return (string) ($p['text'] ?? $p['caption'] ?? '');
        }, $this->of('sendMessage', 'editMessageText', 'sendPhoto', 'sendVideo', 'sendDocument', 'sendAnimation', 'sendAudio')));
    }
}

T::section('F. Integratsiya (MariaDB + soxta Telegram)');
$host = getenv('PA_TEST_DB_HOST') ?: 'localhost';
$name = getenv('PA_TEST_DB_NAME') ?: 'pa_test';
$user = getenv('PA_TEST_DB_USER') ?: 'pa';
$pass = getenv('PA_TEST_DB_PASS') !== false ? (string) getenv('PA_TEST_DB_PASS') : 'pa_pass';
try {
    $pdo = new PDO("mysql:host={$host};dbname={$name};charset=utf8mb4", $user, $pass);
} catch (Throwable $e) {
    T::skip('integratsiya', 'sinov bazasiga ulanib bo\'lmadi: ' . $e->getMessage());
    return;
}
$db = new Db($pdo);
$pdo->exec("SET time_zone = '+00:00'");
$ALL_TABLES = ['processed_updates', 'scheduled_posts', 'channels', 'user_states', 'users', 'payments', 'promo_codes', 'promo_redemptions',
    'promo_attempts', 'credits_ledger', 'tracked_links', 'tracked_link_visits', 'sent_messages', 'reaction_votes', 'album_items', 'album_done', 'ai_usage', 'payment_receipts', 'broadcasts', 'forced_channels', 'team_members', 'team_invites', 'market_listings', 'market_threads', 'market_messages', 'market_reports', 'content_plans', 'autopilots', 'autopilot_drafts', 'payme_orders', 'payme_transactions', 'rss_feeds', 'post_templates', 'channel_stats', 'post_comments', 'comment_bans'];
foreach ($ALL_TABLES as $t) {
    $pdo->exec("DROP TABLE IF EXISTS {$t}");
}
$schema = (string) file_get_contents(dirname(__DIR__) . '/sql/schema.sql');
// 1-bosqichdan yangilash: eski users jadvali (yangi ustunlarsiz) bo'lsa ham Schema::apply ularni qo'shadi
$pdo->exec("CREATE TABLE users (user_id BIGINT NOT NULL PRIMARY KEY, username VARCHAR(64) NULL, full_name VARCHAR(255) NULL,
    lang VARCHAR(5) NOT NULL DEFAULT 'uz', lang_chosen TINYINT(1) NOT NULL DEFAULT 0, referrer_id BIGINT NULL,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'free', is_blocked TINYINT(1) NOT NULL DEFAULT 0, created_at DATETIME NOT NULL,
    last_active_at DATETIME NULL, KEY idx_users_created (created_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
$changes = PostAssist\Schema::apply($db, $schema);
T::eq('eski bazani yangilash: 10 ustun (2-bosqich 4 ta, timezone, uz_verified, sub_ok_until, workspace_owner, phone_verified, market_banned) + 2 indeks qo\'shildi', count($changes), 12);
T::eq('qayta ishga tushirish: o\'zgarish yo\'q (idempotent)', PostAssist\Schema::apply($db, $schema), []);
T::eq('hamma jadvallar bor', (int) $db->value('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN (' . implode(',', array_fill(0, count($ALL_TABLES), '?')) . ')', $ALL_TABLES), count($ALL_TABLES));

$BOT = 111111;
$ADMIN = 999;
$U = 5001;       // oddiy foydalanuvchi
$U2 = 5002;      // boshqa foydalanuvchi
$CH = -1001000000001;
$CH2 = -1001000000002;
$fake = new FakeTg();
$clock = new DateTimeImmutable('2026-11-03 10:00:00', new DateTimeZone('UTC'));
$config = new Config([
    'bot_token' => $BOT . ':' . str_repeat('A', 35), 'bot_username' => 'PostAssistrobot', 'admin_ids' => [$ADMIN],
    'webhook_secret' => str_repeat('s', 20), 'cron_key' => str_repeat('k', 20), 'timezone' => 'Asia/Tashkent',
    'free_max_channels' => 2, 'free_max_queued' => 3,
]);
$app = new App($config, $db, new Telegram('x', 'https://x', $fake), static function () use (&$clock) {
    return $clock;
});
$router = new Router($app);
$upd = 1;
// Telegram::call massivlarni JSON satrga aylantiradi — testlar shu satrni o'qiydi
$mk = static function (array $p): string {
    $m = $p['reply_markup'] ?? '';
    return is_string($m) ? $m : (string) json_encode($m);
};
$from = static function (int $id, string $lang = 'uz') {
    return ['id' => $id, 'is_bot' => false, 'first_name' => 'Ali<script>', 'username' => 'ali' . $id, 'language_code' => $lang];
};
$send = static function (int $uid, array $msgExtra, string $lang = 'uz') use (&$upd, $router, $from, $fake) {
    $fake->reset();
    $router->handle(['update_id' => $upd++, 'message' => array_merge(['message_id' => $upd, 'from' => $from($uid, $lang), 'chat' => ['id' => $uid, 'type' => 'private'], 'date' => 0], $msgExtra)]);
};
$text = static function (int $uid, string $t, string $lang = 'uz') use ($send) {
    $send($uid, ['text' => $t], $lang);
};
$press = static function (int $uid, string $data) use (&$upd, $router, $from, $fake) {
    $fake->reset();
    $router->handle(['update_id' => $upd++, 'callback_query' => ['id' => 'cb' . $upd, 'from' => $from($uid), 'data' => $data,
        'message' => ['message_id' => 77, 'chat' => ['id' => $uid, 'type' => 'private'], 'text' => 'eski']]]);
};

// --- /start
$text($U, '/start');
T::check('/start: yangi foydalanuvchi salomlashuvi va bosh menyu', strpos($fake->lastText(), 'PostAssist') !== false
    && isset($fake->of('sendMessage')[0]['reply_markup']));
T::check('/start: ism HTML-escape qilingan', strpos($fake->lastText(), 'Ali&lt;script&gt;') !== false && strpos($fake->lastText(), '<script>') === false);
T::eq('foydalanuvchi bazada (til uz)', $app->users->get($U)['lang'] ?? null, 'uz');
$text($U, '/start');
T::check('qayta /start: oddiy salom', strpos($fake->lastText(), 'Kerakli bo\'limni') !== false);
$text($U2, '/start ref_' . $U, 'ru');
T::eq('referal: yangi foydalanuvchiga taklif qiluvchi yozildi', (int) ($app->users->get($U2)['referrer_id'] ?? 0), $U);
T::eq('til Telegram tilidan: ru', $app->users->get($U2)['lang'] ?? null, 'ru');
$text(5003, '/start ref_5003');
T::eq('o\'zini taklif qilish rad', $app->users->get(5003)['referrer_id'] ?? null, null);
$text(5004, '/start ref_424242');
T::eq('noma\'lum taklif qiluvchi rad', $app->users->get(5004)['referrer_id'] ?? null, null);

// --- dublikat yangilanish
$fake->reset();
$router->handle(['update_id' => 1, 'message' => ['message_id' => 1, 'from' => $from($U), 'chat' => ['id' => $U, 'type' => 'private'], 'text' => '/start']]);
T::eq('bir xil update_id qayta ishlanmaydi', count($fake->calls), 0);
// --- guruh xabari e'tiborsiz
$fake->reset();
$router->handle(['update_id' => $upd++, 'message' => ['message_id' => 2, 'from' => $from($U), 'chat' => ['id' => -500, 'type' => 'group'], 'text' => '/start']]);
T::eq('guruhdagi xabar e\'tiborsiz', count($fake->calls), 0);

// --- til
$press($U, 'lang:en');
T::eq('til o\'zgardi: en', $app->users->get($U)['lang'], 'en');
T::check('javob inglizcha', strpos($fake->lastText(), 'English') !== false);
$text($U, '📢 Kanallarim');
T::check('eski (uz) menyu tugmasi boshqa tilda ham ishlaydi', strpos($fake->lastText(), 'My channels') !== false);
$press($U, 'lang:uz');

// --- kanal yo'q bo'lsa post
$text($U, '✍️ Post yaratish');
T::check('kanalsiz post: avval kanal ulash so\'raladi', strpos($fake->texts(), 'Avval kanal ulang') !== false);
T::eq('holat: kanal kutilmoqda', $app->states->get($U)['state'] ?? null, 'ch_wait');

// --- kanal ulash
$fake->chats[$CH] = ['id' => $CH, 'type' => 'channel', 'title' => 'Mening <kanalim>', 'username' => 'mykanal'];
$fake->chats['@mykanal'] = $fake->chats[$CH];
$fake->chats[$CH2] = ['id' => $CH2, 'type' => 'channel', 'title' => 'Ikkinchi'];
$fake->chats['@guruh'] = ['id' => -100777, 'type' => 'supergroup', 'title' => 'G'];
$send($U, ['forward_origin' => ['type' => 'channel', 'chat' => ['id' => $CH, 'type' => 'channel', 'title' => 'x']]]);
T::check('bot admin emas -> rad', strpos($fake->lastText(), 'admin emas') !== false);
$fake->members["{$CH}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => false];
$send($U, ['forward_origin' => ['type' => 'channel', 'chat' => ['id' => $CH, 'type' => 'channel', 'title' => 'x']]]);
T::check('botda xabar joylash huquqi yo\'q -> rad', strpos($fake->lastText(), 'joylash huquqi yo\'q') !== false);
$fake->members["{$CH}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["{$CH}|{$U}"] = ['status' => 'member'];
$text($U, '@mykanal');
T::check('foydalanuvchi kanal admini emas -> rad (begona kanal ulanmaydi)', strpos($fake->lastText(), 'admini emassiz') !== false);
$text($U, '@guruh');
T::check('guruh kanal emas -> rad', strpos($fake->lastText(), 'kanal emas') !== false);
$text($U, 'salom qalesan');
T::check('noto\'g\'ri matn -> kanal topilmadi', strpos($fake->lastText(), 'topilmadi') !== false);
$fake->members["{$CH}|{$U}"] = ['status' => 'creator'];
$text($U, 'https://t.me/mykanal');
T::check('kanal ulandi (t.me havola bilan), nom escape', strpos($fake->lastText(), 'Kanal ulandi') !== false && strpos($fake->lastText(), 'Mening &lt;kanalim&gt;') !== false);
T::eq('kanal bazada', $app->channels->countFor($U), 1);
T::eq('holat tozalandi', $app->states->get($U), null);
$fake->members["{$CH}|{$U2}"] = ['status' => 'administrator'];
$press($U2, 'ch:add');
$text($U2, '@mykanal');
T::check('boshqa foydalanuvchiga ulangan kanal -> rad', strpos($fake->lastText(), 'boshqa foydalanuvchiga') !== false || strpos($fake->lastText(), 'другому') !== false);
$fake->members["{$CH2}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["{$CH2}|{$U}"] = ['status' => 'administrator'];
$press($U, 'ch:add');
$text($U, (string) $CH2);
T::eq('ikkinchi kanal (-100 ID bilan)', $app->channels->countFor($U), 2);
$fake->chats[-1003] = ['id' => -1003, 'type' => 'channel', 'title' => 'Uch'];
$fake->members["-1003|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$fake->members["-1003|{$U}"] = ['status' => 'creator'];
$press($U, 'ch:add');
$send($U, ['forward_from_chat' => ['id' => -1003, 'type' => 'channel', 'title' => 'Uch']]);
T::check('kanal limiti (2) -> rad', strpos($fake->lastText(), 'chegarasiga') !== false);
$fake->members["-1003|{$ADMIN}"] = ['status' => 'creator'];
$text($ADMIN, '/start');
$press($ADMIN, 'ch:add');
$send($ADMIN, ['forward_from_chat' => ['id' => -1003, 'type' => 'channel', 'title' => 'Uch']]);
T::eq('admin uchun kanal limiti yo\'q', $app->channels->countFor($ADMIN), 1);

// --- post: ko'p kanal -> tanlash -> preview
$text($U, '✍️ Post yaratish');
T::eq('post holati', $app->states->get($U)['state'] ?? null, 'post_content');
$send($U, ['sticker' => ['file_id' => 'stk']]);
T::check('stiker post qilinmaydi', strpos($fake->lastText(), 'post qilib bo\'lmaydi') !== false);
$send($U, ['photo' => [['file_id' => 'p1']], 'caption' => str_repeat('x', 1100)]);
T::check('uzun izoh rad (1024)', strpos($fake->lastText(), 'juda uzun') !== false);
$send($U, ['text' => 'Yangi aksiya! 20% chegirma', 'entities' => [['type' => 'bold', 'offset' => 0, 'length' => 13]]]);
T::eq('ikki kanal: kanal tanlash so\'raladi', $app->states->get($U)['state'] ?? null, 'post_pick');
$ch1 = $app->channels->listFor($U)[0];
$chB = $app->channels->listFor($ADMIN)[0];
$press($U, 'p:ch:' . $chB['id']);
T::eq('begona kanalni tanlab bo\'lmaydi', $app->states->get($U)['state'] ?? null, 'post_pick');
$press($U, 'p:ch:' . $ch1['id']);
$prev = $fake->of('sendMessage')[0] ?? [];
T::check('preview: formatlash saqlangan, bepul nishon bor', strpos((string) ($prev['text'] ?? ''), "🤖 @PostAssistrobot\n\n<b>Yangi aksiya!</b> 20% chegirma") === 0, (string) ($prev['text'] ?? ''));
T::check('preview: boshqaruv tugmalari', strpos($mk($prev), 'p:now') !== false);
T::eq('holat: preview', $app->states->get($U)['state'] ?? null, 'post_preview');

// --- tugma qo'shish
$press($U, 'p:btn');
$text($U, 'yomon format');
T::check('tugma: noto\'g\'ri format rad', strpos($fake->lastText(), 'Format noto\'g\'ri') !== false);
$text($U, 'Batafsil - sayt.uz');
$prev = $fake->of('sendMessage')[0] ?? [];
T::check('tugma qo\'shildi (preview\'da url tugma + ixcham panel: Qo\'shimcha)', strpos($mk($prev), 'https:\/\/sayt.uz') !== false
    && strpos($mk($prev), 'p:more') !== false, $mk($prev));
$press($U, 'p:more');
T::check('«Qo\'shimcha» ichida: tugmani o\'chirish, reaksiya, takror, avto-o\'chirish', strpos($mk($fake->of('sendMessage')[0] ?? []), 'p:btndel') !== false
    && strpos($mk($fake->of('sendMessage')[0] ?? []), 'p:rep') !== false && strpos($mk($fake->of('sendMessage')[0] ?? []), 'p:ad') !== false);

// --- hozir yuborish
$press($U, 'p:now');
$sent = $fake->of('sendMessage');
T::eq('hozir yuborish: kanalga ketdi', (int) ($sent[0]['chat_id'] ?? 0), $CH);
T::check('kanal postida nishon va tugma', strpos((string) $sent[0]['text'], '🤖 @PostAssistrobot') === 0 && strpos($mk($sent[0]), 'https:\/\/sayt.uz') !== false);
T::check('foydalanuvchiga «Yuborildi»', strpos($fake->lastText(), 'Yuborildi') !== false);
T::eq('post bazada: sent', $db->value("SELECT status FROM scheduled_posts ORDER BY id DESC LIMIT 1"), 'sent');
$press($U, 'p:now');
T::eq('ikkinchi bosish: qayta yuborilmaydi', count($fake->of('sendPhoto', 'sendMessage')) === 1 && strpos($fake->lastText(), 'Qoralama topilmadi') !== false, true);

// --- admin: nishonsiz
$text($ADMIN, '/newpost');
$send($ADMIN, ['text' => 'Admin posti']);
$press($ADMIN, 'p:now');
T::eq('admin posti nishonsiz', (string) ($fake->of('sendMessage')[0]['text'] ?? ''), 'Admin posti');

// --- vaqt belgilash
$text($U, '/newpost');
$send($U, ['photo' => [['file_id' => 'small'], ['file_id' => 'BIG']], 'caption' => 'Rasm izohi', 'caption_entities' => [['type' => 'italic', 'offset' => 0, 'length' => 4]]]);
$press($U, 'p:ch:' . $ch1['id']);
T::eq('rasm preview (eng katta o\'lcham)', (string) ($fake->of('sendPhoto')[0]['photo'] ?? ''), 'BIG');
$press($U, 'p:time');
T::check('vaqt so\'raladi (Toshkent)', strpos($fake->lastText(), 'Asia/Tashkent') !== false);
$text($U, 'bugun 14:00');
T::check('o\'tgan vaqt rad', strpos($fake->lastText(), 'o\'tib ketgan') !== false);
$text($U, 'ertaga 09:00');
T::check('rejalashtirildi: 04.11.2026 09:00', strpos($fake->lastText(), '04.11.2026 09:00') !== false);
$row = $db->one("SELECT * FROM scheduled_posts WHERE post_type = 'photo' ORDER BY id DESC LIMIT 1");
T::eq('bazada UTC vaqt', $row['scheduled_time'] ?? null, '2026-11-04 04:00:00');
T::eq('bazada izoh formatlangan', $row['text'] ?? null, '<i>Rasm</i> izohi');

// --- navbat limiti (3) va tezkor tugma
$text($U, '/newpost');
$send($U, ['text' => 'Ikkinchi']);
$press($U, 'p:ch:' . $ch1['id']);
$press($U, 'p:time');
$press($U, 't:tom09');
T::eq('tezkor tugma: ertaga 09:00', $db->value("SELECT scheduled_time FROM scheduled_posts WHERE text = 'Ikkinchi'"), '2026-11-04 04:00:00');
$text($U, '/newpost');
$send($U, ['text' => 'Uchinchi']);
$press($U, 'p:ch:' . $ch1['id']);
$press($U, 'p:time');
$press($U, 't:1h');
$text($U, '/newpost');
$send($U, ['text' => 'To\'rtinchi']);
$press($U, 'p:ch:' . $ch1['id']);
$press($U, 'p:time');
$press($U, 't:1h');
T::check('navbat limiti (3) -> rad', strpos($fake->lastText(), 'chegarasiga') !== false);
T::eq('limitdan oshgan post yaratilmadi', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE text = 'To''rtinchi'"), 0);

// --- navbat ro'yxati / ko'rish / bekor
$text($U, '📅 Rejalashtirilgan');
$kb = $mk($fake->of('sendMessage')[0] ?? []);
T::check('navbat ro\'yxati: 3 ta post', substr_count($kb, 'q:v:') === 3);
$pid = (int) $db->value("SELECT id FROM scheduled_posts WHERE text = 'Uchinchi'");
$press($U, 'q:v:' . $pid);
T::check('postni ko\'rish', strpos($fake->lastText(), 'Uchinchi') !== false && strpos($fake->lastText(), '#' . $pid) !== false);
$press($U2, 'q:v:' . $pid);
T::check('begona post ko\'rinmaydi (IDOR)', strpos($fake->lastText(), 'Uchinchi') === false);
$press($U2, 'q:dok:' . $pid);
T::eq('begona post bekor qilinmaydi', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$pid]), 'pending');
$press($U, 'q:d:' . $pid);
T::check('bekor qilish tasdiq so\'raydi', strpos($fake->lastText(), 'bekor qilinsinmi') !== false);
$press($U, 'q:dok:' . $pid);
T::eq('post bekor qilindi', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$pid]), 'cancelled');

// --- cron: vaqti kelmagan / kelgan
$sched = new Scheduler($app, static function (int $us): void {
});
$fake->reset();
$r = $sched->run(5);
T::eq('cron: vaqti kelmagan post yuborilmaydi', $r['sent'], 0);
$clock = new DateTimeImmutable('2026-11-04 04:00:30', new DateTimeZone('UTC'));
$fake->reset();
$r = $sched->run(5);
T::eq('cron: vaqti kelgan 2 ta post yuborildi', $r['sent'], 2);
T::check('egasiga «post chiqdi» xabari', strpos($fake->texts(), 'Rejalashtirilgan post chiqdi') !== false);
T::eq('rasm kanalga sendPhoto bilan, nishonli izoh', (string) ($fake->of('sendPhoto')[0]['caption'] ?? ''), "🤖 @PostAssistrobot\n\n<i>Rasm</i> izohi");
$fake->reset();
T::eq('cron qayta: hech narsa ikki marta ketmaydi', $sched->run(5)['sent'], 0);

// --- cron: vaqtinchalik xato -> qayta urinish, doimiy xato -> failed + xabar
$text($U, '/newpost');
$send($U, ['text' => 'Xatoli']);
$press($U, 'p:ch:' . $ch1['id']);
$press($U, 'p:time');
$text($U, '+5');
$xid = (int) $db->value("SELECT id FROM scheduled_posts WHERE text = 'Xatoli'");
$clock = $clock->modify('+10 minutes');
$fake->reset();
$fake->forced['sendMessage'] = [['ok' => false, 'error_code' => 429, 'description' => 'Too Many Requests', 'parameters' => ['retry_after' => 30]]];
$r = $sched->run(5);
T::eq('429: qayta urinishga qoldi', [$r['retry'], $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$xid])], [1, 'pending']);
$db->exec('UPDATE scheduled_posts SET scheduled_time = ? WHERE id = ?', [$clock->format('Y-m-d H:i:s'), $xid]);
$fake->forced['sendMessage'] = [['ok' => false, 'error_code' => 403, 'description' => 'Forbidden: bot was kicked from the channel chat']];
$r = $sched->run(5);
T::eq('403: failed', $db->value('SELECT status FROM scheduled_posts WHERE id = ?', [$xid]), 'failed');
T::check('egasiga sabab bilan xabar', strpos($fake->texts(), 'admin emas') !== false);

// --- processing da qolib ketgan post tiklanadi
$db->exec("INSERT INTO scheduled_posts (user_id, channel_id, post_type, text, scheduled_time, status, processing_started_at, created_at)
    VALUES (?, ?, 'text', 'Qotgan', ?, 'processing', ?, ?)", [$U, $CH, $clock->format('Y-m-d H:i:s'), '2000-01-01 00:00:00', $clock->format('Y-m-d H:i:s')]);
$db->exec("UPDATE scheduled_posts SET processing_started_at = UTC_TIMESTAMP() - INTERVAL 20 MINUTE WHERE text = 'Qotgan'");
$fake->reset();
$sched->run(5);
T::eq('qotgan post qayta yuborildi', $db->value("SELECT status FROM scheduled_posts WHERE text = 'Qotgan'"), 'sent');

// --- cron qulfi: ikkinchi jarayon kutmaydi
$db2 = new Db(new PDO("mysql:host={$host};dbname={$name};charset=utf8mb4", $user, $pass));
$db2->lock(Scheduler::LOCK, 0);
T::eq('boshqa cron ishlayotganda: qulf band', $sched->run(5)['locked'], true);
$db2->unlock(Scheduler::LOCK);

// --- bot kanaldan chiqarildi
$text($U, '/newpost');
$send($U, ['text' => 'Kanal ketadi']);
$press($U, 'p:ch:' . $ch1['id']);
$press($U, 'p:time');
$press($U, 't:tom09');
$fake->reset();
$router->handle(['update_id' => $upd++, 'my_chat_member' => ['chat' => ['id' => $CH, 'type' => 'channel'], 'from' => $from($U),
    'new_chat_member' => ['status' => 'left', 'user' => ['id' => $BOT]]]]);
T::eq('bot chiqarilganda kanal o\'chadi', (int) $db->value('SELECT is_active FROM channels WHERE channel_id = ?', [$CH]), 0);
T::eq('o\'sha kanalning navbatdagi postlari bekor', (int) $db->value("SELECT COUNT(*) FROM scheduled_posts WHERE channel_id = ? AND status = 'pending'", [$CH]), 0);
T::check('egasiga ogohlantirish', strpos($fake->lastText(), 'chiqarildi') !== false);

// --- kanal o'chirish (tasdiq bilan) va IDOR
$ch2row = $db->one('SELECT * FROM channels WHERE channel_id = ?', [$CH2]);
$press($U2, 'ch:delok:' . $ch2row['id']);
T::eq('begona kanalni o\'chirib bo\'lmaydi', (int) $db->value('SELECT is_active FROM channels WHERE id = ?', [$ch2row['id']]), 1);
$press($U, 'ch:del:' . $ch2row['id']);
T::check('o\'chirish tasdiq so\'raydi', strpos($fake->lastText(), 'o\'chiraymi') !== false);
$press($U, 'ch:delok:' . $ch2row['id']);
T::eq('kanal o\'chirildi', (int) $db->value('SELECT is_active FROM channels WHERE id = ?', [$ch2row['id']]), 0);
$fake->members["{$CH}|{$U2}"] = ['status' => 'administrator'];
$fake->members["{$CH}|{$BOT}"] = ['status' => 'administrator', 'can_post_messages' => true];
$press($U2, 'ch:add');
$text($U2, '@mykanal');
T::eq('o\'chirilgan kanalni boshqa admin ulay oladi', (int) $db->value('SELECT user_id FROM channels WHERE channel_id = ?', [$CH]), $U2);

// --- statistika, admin, eskirgan tugmalar
$text($U, '📊 Statistika');
T::check('statistika: yuborilgan/chiqmagan', strpos($fake->lastText(), 'Yuborilgan') !== false);
$text($U, '/admin');
T::check('oddiy foydalanuvchiga admin panel yo\'q', strpos($fake->lastText(), 'Admin panel') === false);
$text($ADMIN, '👑 Admin panel');
T::check('admin panel: foydalanuvchilar soni', strpos($fake->lastText(), 'Foydalanuvchilar') !== false);
$app->states->clear($U);
$press($U, 'p:now');
T::check('eskirgan preview tugmasi: qoralama topilmadi', strpos($fake->lastText(), 'Qoralama topilmadi') !== false);
$press($U, 'q:v:abc');
T::eq('noto\'g\'ri callback e\'tiborsiz (faqat javob)', count($fake->of('sendMessage', 'editMessageText')), 0);
$text($U, 'nimadir');
T::check('holatsiz matn: tushunmadim + menyu', strpos($fake->lastText(), 'Tushunmadim') !== false);
$text($ADMIN, '/newpost');
$text($ADMIN, '/nomalum');
T::check('post kutilayotganda noma\'lum buyruq post bo\'lmaydi', strpos($fake->lastText(), 'Tushunmadim') !== false
    && ($app->states->get($ADMIN)['state'] ?? null) === 'post_content');
$text($U, '/cancel');
T::check('/cancel', strpos($fake->lastText(), 'Bekor qilindi') !== false);

require __DIR__ . '/Phase2Test.php';
require __DIR__ . '/Phase3Test.php';
require __DIR__ . '/Phase4Test.php';
require __DIR__ . '/MiniAppTest.php';
require __DIR__ . '/Phase5Test.php';
require __DIR__ . '/Phase6Test.php';
require __DIR__ . '/TeamTest.php';
require __DIR__ . '/MarketTest.php';
require __DIR__ . '/AutopilotTest.php';
require __DIR__ . '/PaymeTest.php';
require __DIR__ . '/MiniAppMarketTest.php';
require __DIR__ . '/FeaturesTest.php';
require __DIR__ . '/RssTest.php';
require __DIR__ . '/TemplatesTest.php';
require __DIR__ . '/StatsTest.php';
require __DIR__ . '/CommentsTest.php';
require __DIR__ . '/ExtrasTest.php';
