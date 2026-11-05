<?php
declare(strict_types=1);

namespace PostAssist;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\Repo\AiUsage;
use PostAssist\Repo\Autopilots;
use PostAssist\Repo\ContentPlans;
use PostAssist\Repo\RssFeeds;
use PostAssist\Repo\Albums;
use PostAssist\Repo\Broadcasts;
use PostAssist\Repo\ForcedChannels;
use PostAssist\Repo\Receipts;
use PostAssist\Repo\Team;
use PostAssist\Repo\Channels;
use PostAssist\Repo\Credits;
use PostAssist\Repo\Market;
use PostAssist\Repo\Messages;
use PostAssist\Repo\Payments;
use PostAssist\Repo\Posts;
use PostAssist\Repo\Promos;
use PostAssist\Repo\States;
use PostAssist\Repo\TrackedLinks;
use PostAssist\Repo\Users;
use PostAssist\Services\Ai;
use PostAssist\Services\Plans;

/** Bitta so'rov davomida kerak bo'ladigan hamma narsa (konfiguratsiya, baza, Telegram, repozitoriylar, soat). */
final class App
{
    public Config $config;
    public Db $db;
    public Telegram $tg;
    public Users $users;
    public States $states;
    public Channels $channels;
    public Posts $posts;
    public Payments $payments;
    public Promos $promos;
    public Credits $credits;
    public TrackedLinks $links;
    public Messages $messages;
    public Albums $albums;
    public AiUsage $aiUsage;
    public Receipts $receipts;
    public Broadcasts $broadcasts;
    public ForcedChannels $forced;
    public Team $team;
    public Market $market;
    public ContentPlans $plans;
    public Autopilots $autopilots;
    public RssFeeds $rss;
    /** @var \PostAssist\Services\Rss */
    public $rssClient;
    public Ai $ai;
    /** @var callable|null webhook.php: Telegram'ga javobni darhol qaytarib, ulanishni yopadi (albom kutish uchun) */
    public $releaseClient = null;
    /** @var callable testlar uchun: fn(int $ms): void */
    public $sleeper;
    /** @var array<int, DateTimeZone> */
    private array $tzCache = [];
    /** @var callable|null testlar uchun soat: fn(): DateTimeImmutable (UTC) */
    private $clock;

    public function __construct(Config $config, Db $db, Telegram $tg, ?callable $clock = null)
    {
        $this->config = $config;
        $this->db = $db;
        $this->tg = $tg;
        $this->clock = $clock;
        $this->users = new Users($db);
        $this->states = new States($db);
        $this->channels = new Channels($db);
        $this->posts = new Posts($db);
        $this->payments = new Payments($db);
        $this->promos = new Promos($db);
        $this->credits = new Credits($db);
        $this->links = new TrackedLinks($db);
        $this->messages = new Messages($db);
        $this->albums = new Albums($db);
        $this->aiUsage = new AiUsage($db, $this->credits);
        $this->receipts = new Receipts($db);
        $this->broadcasts = new Broadcasts($db);
        $this->forced = new ForcedChannels($db);
        $this->team = new Team($db);
        $this->market = new Market($db);
        $this->plans = new ContentPlans($db);
        $this->autopilots = new Autopilots($db);
        $this->rss = new RssFeeds($db);
        $this->rssClient = new \PostAssist\Services\Rss();
        $this->ai = new Ai($config);
        $this->sleeper = static function (int $ms): void {
            usleep($ms * 1000);
        };
    }

    public static function fromConfig(array $cfg): self
    {
        $config = new Config($cfg);
        return new self($config, Db::connect($config), new Telegram($config->str('bot_token'), $config->str('api_base')));
    }

    public function now(): DateTimeImmutable
    {
        return $this->clock !== null ? ($this->clock)() : new DateTimeImmutable('now', new DateTimeZone('UTC'));
    }

    public function nowSql(): string
    {
        return $this->now()->format('Y-m-d H:i:s');
    }

    /** Bot (admin statistikasi) mintaqasi — config.php `timezone`. */
    public function tz(): DateTimeZone
    {
        return $this->config->tz();
    }

    /** Foydalanuvchi mintaqasi: o'zi tanlagan (`/timezone`) yoki botniki. */
    public function tzFor(int $userId): DateTimeZone
    {
        if (!isset($this->tzCache[$userId])) {
            $name = (string) $this->db->value('SELECT timezone FROM users WHERE user_id = ?', [$userId]);
            $tz = $this->tz();
            if ($name !== '' && in_array($name, DateTimeZone::listIdentifiers(), true)) {
                $tz = new DateTimeZone($name);
            }
            $this->tzCache[$userId] = $tz;
        }
        return $this->tzCache[$userId];
    }

    public function forgetTz(int $userId): void
    {
        unset($this->tzCache[$userId]);
    }

    public function nowMs(): int
    {
        return (int) round((float) $this->now()->format('U.u') * 1000);
    }

    public function sleepMs(int $ms): void
    {
        ($this->sleeper)($ms);
    }

    /** Telegram'ga «ok» ni darhol qaytarish (webhook ichida bo'lsa). */
    public function releaseClient(): void
    {
        if ($this->releaseClient !== null) {
            $fn = $this->releaseClient;
            $this->releaseClient = null;
            $fn();
        }
    }

    public function tzName(): string
    {
        return $this->tz()->getName();
    }

    public function isAdmin(int $userId): bool
    {
        return $this->config->isAdmin($userId);
    }

    /** Amaldagi tarif: free | pro | ultra | enterprise (muddati o'tgan pro/ultra = free). */
    public function tier(int $userId): string
    {
        $row = $this->users->plan($userId);
        return $row ? Plans::effective($row['plan_type'], $row['subscription_expires_at'], $this->now()) : Plans::FREE;
    }

    /** Bepul tarifmi: admin va pullik tarif — nishonsiz. */
    public function isFree(int $userId): bool
    {
        return !$this->isAdmin($userId) && $this->tier($userId) === Plans::FREE;
    }

    /** 0 = cheksiz (admin, enterprise). */
    public function channelLimit(int $userId): int
    {
        return $this->isAdmin($userId) ? 0 : max(0, Plans::limits($this->tier($userId), $this->config)['channels']);
    }

    public function queueLimit(int $userId): int
    {
        return $this->isAdmin($userId) ? 0 : max(0, Plans::limits($this->tier($userId), $this->config)['queue']);
    }

    /**
     * Mini App manzili: config `miniapp_url`, bo'lmasa webhook manzilidan (…/webhook.php -> …/app.php). Faqat HTTPS.
     * `miniapp_enabled => false` bo'lsa yoki manzil yo'q bo'lsa — null (bot tugmalari ko'rinmaydi).
     */
    public function miniAppUrl(string $query = ''): ?string
    {
        if ($this->config->get('miniapp_enabled') === false) {
            return null;
        }
        $url = $this->config->str('miniapp_url');
        if ($url === '') {
            $hook = $this->config->str('webhook_url');
            if (!preg_match('#^https://.+/webhook\.php$#', $hook)) {
                return null;
            }
            $url = substr($hook, 0, -strlen('webhook.php')) . 'app.php';
        }
        if (strpos($url, 'https://') !== 0) {
            return null;
        }
        return $query !== '' ? $url . (strpos($url, '?') === false ? '?' : '&') . $query : $url;
    }

    /** Jamoadagi yordamchi o'rinlari: ULTRA va muddatsiz tarif (hamda admin) — 2, qolganlar — 0 (config `team_seats`). */
    public function teamSeats(int $ownerId): int
    {
        $tier = $this->isAdmin($ownerId) ? Plans::ENTERPRISE : $this->tier($ownerId);
        if ($tier !== Plans::ULTRA && $tier !== Plans::ENTERPRISE) {
            return 0;
        }
        $n = $this->config->get('team_seats');
        return $n !== null ? max(0, (int) $n) : 2;
    }

    /**
     * Foydalanuvchi hozir kimning ish joyida: o'zi yoki egasi (a'zolik bor va egasining tarifi hali jamoaga ruxsat beradi).
     * Shart bajarilmasa ish joyi o'ziga qaytariladi.
     */
    public function activeOwner(int $userId): int
    {
        $owner = $this->team->workspace($userId);
        if ($owner === null || $owner === $userId) {
            return $userId;
        }
        if ($this->team->perms($owner, $userId) === null || $this->teamSeats($owner) === 0) {
            $this->team->setWorkspace($userId, null);
            return $userId;
        }
        return $owner;
    }

    /** Autopilotlar soni: FREE — 0, PRO — 1, ULTRA — 3, muddatsiz/admin — 10 (config `autopilot_limits`). */
    public function autopilotLimit(int $userId): int
    {
        $tier = $this->isAdmin($userId) ? Plans::ENTERPRISE : $this->tier($userId);
        $map = (array) ($this->config->get('autopilot_limits') ?? []) + ['free' => 0, 'pro' => 1, 'ultra' => 3, 'enterprise' => 10];
        return max(0, (int) ($map[$tier] ?? 0));
    }

    /** RSS lentalari soni: FREE — 0, PRO — 3, ULTRA — 10, muddatsiz/admin — 20 (config `rss_limits`). */
    public function rssLimit(int $userId): int
    {
        $tier = $this->isAdmin($userId) ? Plans::ENTERPRISE : $this->tier($userId);
        $map = (array) ($this->config->get('rss_limits') ?? []) + ['free' => 0, 'pro' => 3, 'ultra' => 10, 'enterprise' => 20];
        return max(0, (int) ($map[$tier] ?? 0));
    }

    /** Kunlik AI limiti (admin va enterprise — cheksiz = 0). */
    public function aiLimit(int $userId): int
    {
        return $this->isAdmin($userId) ? 0 : Plans::aiDaily($this->tier($userId), $this->config);
    }

    /** Bot mintaqasidagi bugungi sana (AI kunlik hisobi uchun). */
    public function today(): string
    {
        return $this->now()->setTimezone($this->tz())->format('Y-m-d');
    }

    /** Foydalanuvchining birinchi posti saqlandi: referal mukofoti va manba havolasi belgisi (xatosi postga ta'sir qilmaydi). */
    public function afterPostSaved(int $userId): ?array
    {
        try {
            $this->links->markFirstPost($userId, $this->now());
            return $this->credits->rewardReferral($userId, $this->now());
        } catch (\Throwable $e) {
            $this->log('afterPostSaved: ' . $e->getMessage());
            return null;
        }
    }

    public function log(string $msg): void
    {
        $dir = dirname(__DIR__) . '/storage';
        if (is_dir($dir) && is_writable($dir)) {
            @file_put_contents($dir . '/bot.log', '[' . gmdate('Y-m-d H:i:s') . '] ' . $msg . "\n", FILE_APPEND | LOCK_EX);
        }
    }
}
