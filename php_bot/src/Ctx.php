<?php
declare(strict_types=1);

namespace PostAssist;

/** Bitta yangilanish konteksti: kim yozdi, qaysi chat, qaysi til, xabar yoki tugma. */
final class Ctx
{
    public App $app;
    public int $userId;
    public int $chatId;
    public string $lang;
    public string $firstName;
    public ?array $message;
    public ?array $callback;
    public bool $isNew = false;

    public function __construct(App $app, int $userId, int $chatId, string $lang, string $firstName, ?array $message, ?array $callback)
    {
        $this->app = $app;
        $this->userId = $userId;
        $this->chatId = $chatId;
        $this->lang = $lang;
        $this->firstName = $firstName;
        $this->message = $message;
        $this->callback = $callback;
    }

    public function t(string $key, array $params = []): string
    {
        return I18n::t($key, $this->lang, $params);
    }

    public function reply(string $text, ?array $markup = null): array
    {
        return $this->app->tg->sendMessage($this->chatId, $text, $markup);
    }

    /** Bosh menyu klaviaturasi bilan javob. */
    public function replyMenu(string $text): array
    {
        return $this->reply($text, Keyboards::main($this->lang, $this->app->isAdmin($this->userId), $this->app->ai->enabled(), $this->app->miniAppUrl()));
    }

    /** Tugma bosilgan xabarni tahrirlaydi (iloji bo'lmasa yangi xabar yuboradi). */
    public function edit(string $text, ?array $markup = null): void
    {
        $msg = $this->callback['message'] ?? null;
        if ($msg && isset($msg['message_id']) && isset($msg['text'])) {
            $res = $this->app->tg->editMessageText($this->chatId, (int) $msg['message_id'], $text, $markup);
            if (!empty($res['ok']) || strpos((string) ($res['description'] ?? ''), 'not modified') !== false) {
                return;
            }
        }
        $this->reply($text, $markup);
    }

    /** Foydalanuvchi vaqt mintaqasi (ko'rsatish va vaqtni tushunish uchun). */
    public function tz(): \DateTimeZone
    {
        return $this->app->tzFor($this->userId);
    }

    public function tzName(): string
    {
        return $this->tz()->getName();
    }

    private ?int $owner = null;

    /** Ish joyi egasi: kanal, navbat, limit va AI shu odamniki (o'z ish joyida — o'zi). */
    public function ownerId(): int
    {
        if ($this->owner === null) {
            $this->owner = $this->app->activeOwner($this->userId);
        }
        return $this->owner;
    }

    public function inTeam(): bool
    {
        return $this->ownerId() !== $this->userId;
    }

    /** Ruxsat: o'z ish joyida — hammasi; egasinikida — egasi bergan ruxsatlar (create, send_now, delete, ai). */
    public function can(string $perm): bool
    {
        if (!$this->inTeam()) {
            return true;
        }
        return in_array($perm, $this->app->team->perms($this->ownerId(), $this->userId) ?? [], true);
    }

    /** Ish joyini qayta o'qish (almashtirilgandan keyin). */
    public function resetOwner(): void
    {
        $this->owner = null;
    }

    /** «👥 Ish joyi: Ali» qatori (egasining ish joyida). */
    public function workspaceLine(): string
    {
        if (!$this->inTeam()) {
            return '';
        }
        $u = $this->app->users->get($this->ownerId());
        $name = trim((string) ($u['full_name'] ?? '')) !== '' ? (string) $u['full_name'] : (!empty($u['username']) ? '@' . $u['username'] : (string) $this->ownerId());
        return $this->t('team_ws_line', ['owner' => Html::e(mb_substr($name, 0, 40))]) . "\n\n";
    }

    public function state(): ?array
    {
        return $this->app->states->get($this->userId);
    }
}
