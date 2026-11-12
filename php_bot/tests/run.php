<?php
// Hamma testlar: php tests/run.php
declare(strict_types=1);

require __DIR__ . '/lib.php';
PostAssist\Services\Ai::$noSleep = true; // AI qayta urinishida haqiqiy kutish yo'q
require __DIR__ . '/UnitTest.php';
require __DIR__ . '/IntegrationTest.php';

exit(T::finish());
