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
        return $this->reply($text, Keyboards::main($this->lang, $this->app->isAdmin($this->userId)));
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

    public function state(): ?array
    {
        return $this->app->states->get($this->userId);
    }
}
