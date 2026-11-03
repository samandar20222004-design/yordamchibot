<?php
// Umumiy ishga tushirish: avtoyuklash, vaqt mintaqasi (ichki hisob UTC), konfiguratsiya.
declare(strict_types=1);

date_default_timezone_set('UTC');
mb_internal_encoding('UTF-8');

spl_autoload_register(static function (string $class): void {
    $prefix = 'PostAssist\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $file = __DIR__ . '/src/' . str_replace('\\', '/', substr($class, strlen($prefix))) . '.php';
    if (is_file($file)) {
        require $file;
    }
});

function postassist_config(): array
{
    $path = __DIR__ . '/config.php';
    if (!is_file($path)) {
        throw new RuntimeException("config.php topilmadi: config.example.php ni config.php nomi bilan nusxalang va to'ldiring.");
    }
    $cfg = require $path;
    if (!is_array($cfg)) {
        throw new RuntimeException("config.php massiv qaytarishi kerak.");
    }
    return $cfg;
}
