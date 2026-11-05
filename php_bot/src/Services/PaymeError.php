<?php
declare(strict_types=1);

namespace PostAssist\Services;

/** Payme JSON-RPC xatosi (doim HTTP 200 bilan javob beriladi). */
final class PaymeError extends \Exception
{
    /** @var mixed */
    public $data;
    /** Timeout bilan bekor qilish saqlansin (xato baribir qaytadi). */
    public bool $commit;

    /** @param mixed $data */
    public function __construct(int $code, $data = null, bool $commit = false)
    {
        parent::__construct('Payme ' . $code, $code);
        $this->data = $data;
        $this->commit = $commit;
    }
}
