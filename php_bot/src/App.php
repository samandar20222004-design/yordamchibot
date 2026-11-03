<?php
declare(strict_types=1);

namespace PostAssist;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\Repo\Channels;
use PostAssist\Repo\Credits;
use PostAssist\Repo\Payments;
use PostAssist\Repo\Posts;
use PostAssist\Repo\Promos;
use PostAssist\Repo\States;
use PostAssist\Repo\TrackedLinks;
use PostAssist\Repo\Users;
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

    public function tz(): DateTimeZone
    {
        return $this->config->tz();
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
