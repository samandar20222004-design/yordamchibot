<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\App;

/**
 * «/» buyruqlar menyusi. setup.php umumiy ro'yxatni Telegram tiliga qarab o'rnatadi; foydalanuvchi botda yoki Mini App'da
 * tilni o'zgartirsa — o'sha chat uchun ham tanlangan tildagi ro'yxat qo'yiladi (Telegram ilovasi tili boshqa bo'lsa ham).
 */
final class BotCommands
{
    public const LIST = [
    'uz' => ['start' => 'Bosh menyu', 'newpost' => 'Yangi post', 'app' => 'Mini App', 'ai' => 'AI bilan post', 'contentplan' => 'AI kontent-reja', 'autopilot' => 'Autopilot (har kuni AI post)', 'market' => 'Reklama birjasi', 'rss' => 'RSS avtopost', 'templates' => 'Shablonlar', 'report' => 'Haftalik hisobot', 'stats' => 'Statistika', 'sent' => 'Yuborilgan postlar', 'queue' => 'Rejalashtirilgan postlar', 'channels' => 'Kanallarim', 'settings' => 'Sozlamalar', 'plans' => 'Tariflar', 'invite' => 'Do\'stlarni taklif qilish', 'help' => 'Yordam', 'feedback' => 'Taklif va xatolar'],
    'ru' => ['start' => 'Главное меню', 'newpost' => 'Новый пост', 'app' => 'Mini App', 'ai' => 'Пост с AI', 'contentplan' => 'AI контент-план', 'autopilot' => 'Автопилот (AI-пост каждый день)', 'market' => 'Биржа рекламы', 'rss' => 'RSS-автопостинг', 'templates' => 'Шаблоны', 'report' => 'Недельный отчёт', 'stats' => 'Статистика', 'sent' => 'Отправленные посты', 'queue' => 'Запланированные посты', 'channels' => 'Мои каналы', 'settings' => 'Настройки', 'plans' => 'Тарифы', 'invite' => 'Пригласить друзей', 'help' => 'Помощь', 'feedback' => 'Предложения и ошибки'],
    'en' => ['start' => 'Main menu', 'newpost' => 'New post', 'app' => 'Mini App', 'ai' => 'Post with AI', 'contentplan' => 'AI content plan', 'autopilot' => 'Autopilot (daily AI post)', 'market' => 'Ad market', 'rss' => 'RSS autopost', 'templates' => 'Templates', 'report' => 'Weekly report', 'stats' => 'Statistics', 'sent' => 'Sent posts', 'queue' => 'Scheduled posts', 'channels' => 'My channels', 'settings' => 'Settings', 'plans' => 'Plans', 'invite' => 'Invite friends', 'help' => 'Help', 'feedback' => 'Feedback and bugs'],
];

    /** @return array<int, array{command:string, description:string}> */
    public static function forLang(string $lang): array
    {
        $out = [];
        foreach (self::LIST[$lang] ?? self::LIST['uz'] as $c => $d) {
            $out[] = ['command' => $c, 'description' => $d];
        }
        return $out;
    }

    /** Bitta chat uchun buyruqlar tilini o'rnatadi (xato botni to'xtatmaydi). */
    public static function applyForChat(App $app, int $chatId, string $lang): void
    {
        $app->tg->call('setMyCommands', ['commands' => self::forLang($lang), 'scope' => ['type' => 'chat', 'chat_id' => $chatId]]);
    }
}
