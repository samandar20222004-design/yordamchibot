<?php
declare(strict_types=1);

namespace PostAssist;

use PDO;

/** PDO (MySQL/MariaDB) o'rami: har so'rov tayyorlangan (prepared) — SQL injection yo'q. */
final class Db
{
    private PDO $pdo;

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
        $this->pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $this->pdo->setAttribute(PDO::ATTR_EMULATE_PREPARES, false);
    }

    public static function connect(Config $c): self
    {
        $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $c->str('db_host'), $c->int('db_port') ?: 3306, $c->str('db_name'));
        $pdo = new PDO($dsn, $c->str('db_user'), $c->str('db_pass'), [PDO::ATTR_TIMEOUT => 10]);
        $pdo->exec("SET time_zone = '+00:00'");
        return new self($pdo);
    }

    public function pdo(): PDO
    {
        return $this->pdo;
    }

    /** @param array<int|string, mixed> $params */
    public function run(string $sql, array $params = []): \PDOStatement
    {
        $st = $this->pdo->prepare($sql);
        $st->execute($params);
        return $st;
    }

    /** @param array<int|string, mixed> $params */
    public function one(string $sql, array $params = []): ?array
    {
        $row = $this->run($sql, $params)->fetch();
        return $row === false ? null : $row;
    }

    /** @param array<int|string, mixed> $params */
    public function all(string $sql, array $params = []): array
    {
        return $this->run($sql, $params)->fetchAll();
    }

    /** @param array<int|string, mixed> $params */
    public function value(string $sql, array $params = [])
    {
        $v = $this->run($sql, $params)->fetchColumn();
        return $v === false ? null : $v;
    }

    /** @param array<int|string, mixed> $params */
    public function exec(string $sql, array $params = []): int
    {
        return $this->run($sql, $params)->rowCount();
    }

    public function lastId(): int
    {
        return (int) $this->pdo->lastInsertId();
    }

    /** Bir nechta SQL buyruqni (schema.sql) ketma-ket bajaradi; izohlar va bo'sh satrlar tashlanadi. */
    public function execScript(string $sql): void
    {
        $sql = preg_replace('/^\s*--.*$/m', '', $sql) ?? $sql;
        foreach (array_filter(array_map('trim', explode(';', $sql))) as $stmt) {
            $this->pdo->exec($stmt);
        }
    }

    /** MySQL nomlangan qulfi (cron bir vaqtda ikki marta ishlamasin). */
    public function lock(string $name, int $timeout = 0): bool
    {
        return (int) $this->value('SELECT GET_LOCK(?, ?)', [$name, $timeout]) === 1;
    }

    public function unlock(string $name): void
    {
        $this->value('SELECT RELEASE_LOCK(?)', [$name]);
    }
}
