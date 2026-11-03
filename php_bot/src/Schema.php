<?php
declare(strict_types=1);

namespace PostAssist;

/**
 * Baza sxemasi: yangi o'rnatishda sql/schema.sql; oldingi bosqichdan yangilashda yetishmayotgan ustun/indekslar qo'shiladi
 * (MySQL 5.7/8.0 da `ADD COLUMN IF NOT EXISTS` yo'q — information_schema orqali tekshiriladi). Qayta ishga tushirish xavfsiz.
 */
final class Schema
{
    /** @var array<int, array{0:string,1:string,2:string}> [jadval, ustun, ta'rif] */
    private const COLUMNS = [
        ['users', 'subscription_expires_at', 'DATETIME NULL'],
        ['users', 'plan_reminder_for', 'DATETIME NULL'],
        ['users', 'ai_credits', 'INT NOT NULL DEFAULT 5'],
        ['users', 'referral_rewarded_at', 'DATETIME NULL'],
    ];
    /** @var array<int, array{0:string,1:string,2:string}> [jadval, indeks, ustunlar] */
    private const INDEXES = [
        ['users', 'idx_users_referrer', 'referrer_id'],
        ['users', 'idx_users_plan', 'plan_type, subscription_expires_at'],
    ];

    /** @return array<int, string> qilingan o'zgarishlar ro'yxati */
    public static function apply(Db $db, string $schemaSql): array
    {
        $db->execScript($schemaSql);
        $done = [];
        foreach (self::COLUMNS as [$table, $column, $def]) {
            $has = (int) $db->value(
                'SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?',
                [$table, $column]
            );
            if ($has === 0) {
                $db->pdo()->exec("ALTER TABLE `{$table}` ADD COLUMN `{$column}` {$def}");
                $done[] = "{$table}.{$column}";
            }
        }
        foreach (self::INDEXES as [$table, $index, $cols]) {
            $has = (int) $db->value(
                'SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ?',
                [$table, $index]
            );
            if ($has === 0) {
                $db->pdo()->exec("ALTER TABLE `{$table}` ADD KEY `{$index}` ({$cols})");
                $done[] = "{$table}.{$index}";
            }
        }
        return $done;
    }
}
