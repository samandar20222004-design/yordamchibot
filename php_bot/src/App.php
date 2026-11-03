<?php
declare(strict_types=1);

namespace PostAssist;

use DateTimeImmutable;
use DateTimeZone;
use PostAssist\Repo\Channels;
use PostAssist\Repo\Posts;
use PostAssist\Repo\States;
use PostAssist\Repo\Users;

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

    /** Bepul tarifmi: admin va pullik tarif — nishonsiz. */
    public function isFree(int $userId): bool
    {
        return !$this->isAdmin($userId) && $this->users->isFree($userId);
    }

    public function channelLimit(int $userId): int
    {
        return $this->isAdmin($userId) ? 0 : max(1, $this->config->int('free_max_channels'));
    }

    public function queueLimit(int $userId): int
    {
        return $this->isAdmin($userId) ? 0 : max(1, $this->config->int('free_max_queued'));
    }

    public function log(string $msg): void
    {
        $dir = dirname(__DIR__) . '/storage';
        if (is_dir($dir) && is_writable($dir)) {
            @file_put_contents($dir . '/bot.log', '[' . gmdate('Y-m-d H:i:s') . '] ' . $msg . "\n", FILE_APPEND | LOCK_EX);
        }
    }
}
