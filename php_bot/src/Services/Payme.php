<?php
declare(strict_types=1);

namespace PostAssist\Services;

use PostAssist\App;
use PostAssist\Handlers\PlansHandler;
use PostAssist\Html;
use PostAssist\I18n;

/**
 * Payme (paycom.uz) Merchant API — JSON-RPC holat mashinasi (Python `payme_provider.py` bilan bir xil qoidalar).
 *
 *   CheckPerformTransaction — buyurtmani shu summa bilan to'lash mumkinmi
 *   CreateTransaction       — buyurtma bitta Payme tranzaksiyasiga band qilinadi
 *   PerformTransaction      — pul yechildi → tarif FAQAT BIR MARTA beriladi
 *   CancelTransaction       — bekor (1-holat) yoki qaytarish (2-holat, faqat `payme_allow_refunds`)
 *   CheckTransaction / GetStatement — holat va hisobot (Payme sinov muhiti talab qiladi)
 *
 * Takror to'lovdan himoya: (1) holat mashinasi — bajarilgan tranzaksiyaga qayta Perform natijani qaytaradi;
 * (2) har o'zgartiruvchi metod bitta DB tranzaksiyada, avval buyurtma, keyin tranzaksiya qatori FOR UPDATE;
 * (3) `payme_transactions.payme_id` UNIQUE va `payments.charge_id = payme_<id>` UNIQUE — tarif faqat yangi qator yozilganda beriladi.
 * Kalit hech qachon logga yozilmaydi.
 */
final class Payme
{
    public const STATE_CREATED = 1;
    public const STATE_PERFORMED = 2;
    public const STATE_CANCELLED = -1;
    public const STATE_CANCELLED_AFTER = -2;
    public const REASON_TIMEOUT = 4;
    public const TIMEOUT_MS = 43200000; // 12 soat
    public const MAX_ID = 64;

    public const ERR_INVALID_REQUEST = -32600;
    public const ERR_PARSE = -32700;
    public const ERR_TRANSPORT = -32300;
    public const ERR_METHOD = -32601;
    public const ERR_AUTH = -32504;
    public const ERR_SYSTEM = -32400;
    public const ERR_AMOUNT = -31001;
    public const ERR_TX_NOT_FOUND = -31003;
    public const ERR_CANNOT_CANCEL = -31007;
    public const ERR_CANNOT_PERFORM = -31008;
    public const ERR_ORDER_NOT_FOUND = -31050;
    public const ERR_ORDER_NOT_PAYABLE = -31051;
    public const ERR_ORDER_BUSY = -31052;

    private const MESSAGES = [
        -32300 => ["So'rov usuli POST emas.", 'Метод запроса не POST.', 'Request method must be POST.'],
        -32700 => ["JSON so'rovni o'qib bo'lmadi.", 'Ошибка разбора JSON.', 'Could not parse JSON.'],
        -32600 => ["So'rov maydonlari noto'g'ri.", 'Неверные поля запроса.', 'Invalid request fields.'],
        -32601 => ['Metod topilmadi.', 'Метод не найден.', 'Method not found.'],
        -32504 => ['Ruxsat yetarli emas.', 'Недостаточно привилегий.', 'Insufficient privileges.'],
        -32400 => ['Ichki tizim xatosi.', 'Внутренняя ошибка системы.', 'Internal system error.'],
        -31001 => ["To'lov summasi noto'g'ri.", 'Неверная сумма платежа.', 'Invalid amount.'],
        -31003 => ['Tranzaksiya topilmadi.', 'Транзакция не найдена.', 'Transaction not found.'],
        -31007 => ["Xizmat ko'rsatilgan, tranzaksiyani bekor qilib bo'lmaydi.", 'Услуга оказана, отмена транзакции невозможна.', 'Service already delivered; the transaction cannot be cancelled.'],
        -31008 => ["Ushbu amalni bajarib bo'lmaydi.", 'Невозможно выполнить операцию.', 'Unable to perform the operation.'],
        -31050 => ['Buyurtma topilmadi.', 'Заказ не найден.', 'Order not found.'],
        -31051 => ["Buyurtma allaqachon to'langan yoki bekor qilingan.", 'Заказ уже оплачен или отменён.', 'Order is already paid or cancelled.'],
        -31052 => ["Buyurtma bo'yicha boshqa to'lov jarayonda.", 'По заказу уже выполняется другой платёж.', 'Another payment for this order is in progress.'],
    ];

    private App $app;
    /** @var array<int, array{user_id:int, tier:string, expires:?string, kept:bool, order:string}> commit'dan keyingi xabarlar */
    private array $paid = [];

    public function __construct(App $app)
    {
        $this->app = $app;
    }

    public static function enabled(App $app): bool
    {
        return $app->config->str('payme_merchant_id') !== '' && $app->config->str('payme_key') !== '';
    }

    public function nowMs(): int
    {
        return (int) $this->app->now()->format('U') * 1000 + (int) $this->app->now()->format('v');
    }

    /** Bir martalik, taxmin qilib bo'lmaydigan buyurtma (havola uchun). */
    public function createOrder(int $userId, string $planKey): ?array
    {
        $plan = Plans::catalog($this->app->config)[$planKey] ?? null;
        $uzs = Plans::uzs($this->app->config)[$planKey] ?? 0;
        if ($plan === null || $uzs <= 0) {
            return null;
        }
        $id = 'pm' . bin2hex(random_bytes(10));
        $this->app->db->exec('INSERT INTO payme_orders (order_id, user_id, plan_key, tier, days, amount_tiyin, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [$id, $userId, $planKey, $plan['tier'], (int) $plan['days'], $uzs * 100, 'pending', $this->app->nowSql()]);
        return ['order_id' => $id, 'amount_tiyin' => $uzs * 100, 'plan' => $plan];
    }

    /** To'lov sahifasi: `<checkout>/<base64(m=..;ac.order_id=..;a=..;l=..)>`. */
    public function checkoutUrl(string $orderId, int $amountTiyin, string $lang): string
    {
        $base = $this->app->config->str('payme_checkout_url');
        if ($base === '') {
            $base = $this->app->config->get('payme_test') ? 'https://checkout.test.paycom.uz' : 'https://checkout.paycom.uz';
        }
        $parts = ['m=' . $this->app->config->str('payme_merchant_id'), 'ac.order_id=' . $orderId, 'a=' . $amountTiyin];
        if (in_array($lang, ['uz', 'ru', 'en'], true)) {
            $parts[] = 'l=' . $lang;
        }
        return rtrim($base, '/') . '/' . base64_encode(implode(';', $parts));
    }

    /** `Authorization: Basic base64(Paycom:<kalit>)` — doimiy vaqtli taqqoslash; kalit yo'q bo'lsa rad. */
    public function authOk(?string $header): bool
    {
        $key = $this->app->config->str('payme_key');
        if ($key === '' || $header === null) {
            return false;
        }
        if (!preg_match('/^\s*Basic\s+([A-Za-z0-9+\/=]+)\s*$/i', $header, $m)) {
            return false;
        }
        $dec = base64_decode($m[1], true);
        if ($dec === false || strpos($dec, ':') === false) {
            return false;
        }
        [$login, $pass] = explode(':', $dec, 2);
        $wantLogin = $this->app->config->str('payme_login') !== '' ? $this->app->config->str('payme_login') : 'Paycom';
        $a = hash_equals($wantLogin, $login);
        $b = hash_equals($key, $pass);
        return $a && $b;
    }

    /**
     * Bitta JSON-RPC so'rov. Hech qachon istisno chiqarmaydi: har xato — JSON-RPC xato obyekti (HTTP 200).
     * @param mixed $payload
     */
    public function handle($payload, ?string $authorization): array
    {
        $rid = is_array($payload) && isset($payload['id']) && !is_array($payload['id']) ? $payload['id'] : null;
        $method = is_array($payload) && is_string($payload['method'] ?? null) ? $payload['method'] : '';
        $this->paid = [];
        try {
            if (!$this->authOk($authorization)) {
                throw new PaymeError(self::ERR_AUTH);
            }
            if (!is_array($payload) || $method === '') {
                throw new PaymeError(self::ERR_INVALID_REQUEST);
            }
            $params = $payload['params'] ?? null;
            if (!is_array($params)) {
                throw new PaymeError(self::ERR_INVALID_REQUEST, 'params');
            }
            switch ($method) {
                case 'CheckPerformTransaction':
                    $result = $this->checkPerform($params);
                    break;
                case 'CreateTransaction':
                    $result = $this->create($params);
                    break;
                case 'PerformTransaction':
                    $result = $this->perform($params);
                    break;
                case 'CancelTransaction':
                    $result = $this->cancel($params);
                    break;
                case 'CheckTransaction':
                    $result = $this->check($params);
                    break;
                case 'GetStatement':
                    $result = $this->statement($params);
                    break;
                default:
                    throw new PaymeError(self::ERR_METHOD, mb_substr($method, 0, 64));
            }
            $this->afterCommit();
            return ['jsonrpc' => '2.0', 'id' => $rid, 'result' => $result];
        } catch (PaymeError $e) {
            return self::error($rid, $e->getCode(), $e->data);
        } catch (\Throwable $e) {
            $this->app->log('Payme ichki xato (' . mb_substr($method, 0, 40) . '): ' . $e->getMessage());
            return self::error($rid, self::ERR_SYSTEM, null);
        }
    }

    /** @param mixed $id @param mixed $data */
    public static function error($id, int $code, $data): array
    {
        $m = self::MESSAGES[$code] ?? self::MESSAGES[self::ERR_SYSTEM];
        $err = ['code' => $code, 'message' => ['uz' => $m[0], 'ru' => $m[1], 'en' => $m[2]]];
        if ($data !== null) {
            $err['data'] = $data;
        }
        return ['jsonrpc' => '2.0', 'id' => $id, 'error' => $err];
    }

    // ------------------------------------------------------------------ yordamchilar

    private static function amount(array $p): int
    {
        $a = $p['amount'] ?? null;
        if (is_bool($a) || !(is_int($a) || (is_float($a) && floor($a) === $a)) || $a <= 0) {
            throw new PaymeError(self::ERR_AMOUNT, 'amount');
        }
        return (int) $a;
    }

    private static function intParam(array $p, string $k, bool $positive = false): int
    {
        $v = $p[$k] ?? null;
        if (is_bool($v) || !(is_int($v) || (is_float($v) && floor($v) === $v)) || ($positive && $v <= 0)) {
            throw new PaymeError(self::ERR_INVALID_REQUEST, $k);
        }
        return (int) $v;
    }

    private static function paymeId(array $p): string
    {
        $v = $p['id'] ?? null;
        if (!is_string($v) || trim($v) === '' || strlen($v) > self::MAX_ID) {
            throw new PaymeError(self::ERR_INVALID_REQUEST, 'id');
        }
        return trim($v);
    }

    private static function orderId(array $p): string
    {
        $acc = $p['account'] ?? null;
        if (!is_array($acc)) {
            throw new PaymeError(self::ERR_INVALID_REQUEST, 'account');
        }
        $raw = $acc['order_id'] ?? null;
        if (is_bool($raw) || !(is_string($raw) || is_int($raw)) || trim((string) $raw) === '' || strlen((string) $raw) > self::MAX_ID) {
            throw new PaymeError(self::ERR_ORDER_NOT_FOUND, 'order_id');
        }
        return trim((string) $raw);
    }

    private function order(string $id, bool $lock = false): ?array
    {
        return $this->app->db->one('SELECT * FROM payme_orders WHERE order_id = ?' . ($lock ? ' FOR UPDATE' : ''), [$id]);
    }

    private function tx(string $paymeId, bool $lock = false): ?array
    {
        return $this->app->db->one('SELECT * FROM payme_transactions WHERE payme_id = ?' . ($lock ? ' FOR UPDATE' : ''), [$paymeId]);
    }

    private static function validOrder(?array $o, int $amount): array
    {
        if ($o === null) {
            throw new PaymeError(self::ERR_ORDER_NOT_FOUND, 'order_id');
        }
        if ($o['status'] !== 'pending') {
            throw new PaymeError(self::ERR_ORDER_NOT_PAYABLE, 'order_id');
        }
        if ($amount !== (int) $o['amount_tiyin']) {
            throw new PaymeError(self::ERR_AMOUNT, 'amount');
        }
        return $o;
    }

    private function expired(array $tx, int $now): bool
    {
        $t = (int) ($this->app->config->get('payme_timeout_ms') ?? self::TIMEOUT_MS);
        return (int) $tx['state'] === self::STATE_CREATED && $now - (int) $tx['create_time'] > $t;
    }

    private function cancelCreated(array $tx, ?int $reason, int $now): array
    {
        $this->app->db->exec('UPDATE payme_transactions SET state = ?, cancel_time = ?, reason = ? WHERE id = ?', [self::STATE_CANCELLED, $now, $reason, (int) $tx['id']]);
        $tx['state'] = self::STATE_CANCELLED;
        $tx['cancel_time'] = $now;
        $tx['reason'] = $reason;
        return $tx;
    }

    /** Bitta DB tranzaksiyasida bajaradi; PaymeError'da ham `$commitOnError` bo'lsa (masalan timeout bekor) o'zgarish saqlanadi. */
    private function atomic(callable $fn)
    {
        $pdo = $this->app->db->pdo();
        $pdo->beginTransaction();
        try {
            $r = $fn();
            $pdo->commit();
            return $r;
        } catch (PaymeError $e) {
            if ($e->commit) {
                $pdo->commit();
            } else {
                $pdo->rollBack();
            }
            throw $e;
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) {
                $pdo->rollBack();
            }
            throw $e;
        }
    }

    /** Avval buyurtma, keyin tranzaksiya qulflanadi (doimiy tartib — deadlock yo'q). @return array{0:?array,1:array} */
    private function lockTx(string $paymeId): array
    {
        $peek = $this->tx($paymeId);
        if ($peek === null) {
            throw new PaymeError(self::ERR_TX_NOT_FOUND, 'id');
        }
        $order = $this->order((string) $peek['order_id'], true);
        $tx = $this->tx($paymeId, true);
        return [$order, $tx ?? $peek];
    }

    // ------------------------------------------------------------------ metodlar

    private function checkPerform(array $p): array
    {
        $amount = self::amount($p);
        self::validOrder($this->order(self::orderId($p)), $amount);
        return ['allow' => true];
    }

    private function create(array $p): array
    {
        $paymeId = self::paymeId($p);
        $time = self::intParam($p, 'time', true);
        $amount = self::amount($p);
        $orderId = self::orderId($p);
        $now = $this->nowMs();
        return $this->atomic(function () use ($paymeId, $time, $amount, $orderId, $now) {
            $order = $this->order($orderId, true);
            $existing = $this->tx($paymeId, true);
            if ($existing !== null) {
                if ((int) $existing['state'] !== self::STATE_CREATED) {
                    throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id');
                }
                if ($this->expired($existing, $now)) {
                    $this->cancelCreated($existing, self::REASON_TIMEOUT, $now);
                    throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id', true);
                }
                return ['create_time' => (int) $existing['create_time'], 'transaction' => (string) $existing['id'], 'state' => self::STATE_CREATED];
            }
            $order = self::validOrder($order, $amount);
            $active = $this->app->db->one('SELECT * FROM payme_transactions WHERE order_id = ? AND state IN (1, 2) ORDER BY id DESC LIMIT 1 FOR UPDATE', [$orderId]);
            if ($active !== null) {
                if ($this->expired($active, $now)) {
                    $this->cancelCreated($active, self::REASON_TIMEOUT, $now);
                } else {
                    throw new PaymeError(self::ERR_ORDER_BUSY, 'order_id');
                }
            }
            $n = $this->app->db->exec('INSERT IGNORE INTO payme_transactions (payme_id, order_id, user_id, amount, state, payme_time, create_time) VALUES (?, ?, ?, ?, ?, ?, ?)',
                [$paymeId, $orderId, (int) $order['user_id'], $amount, self::STATE_CREATED, $time, $now]);
            if ($n !== 1) {
                throw new PaymeError(self::ERR_ORDER_BUSY, 'order_id');
            }
            return ['create_time' => $now, 'transaction' => (string) $this->app->db->lastId(), 'state' => self::STATE_CREATED];
        });
    }

    private function perform(array $p): array
    {
        $paymeId = self::paymeId($p);
        $now = $this->nowMs();
        return $this->atomic(function () use ($paymeId, $now) {
            [$order, $tx] = $this->lockTx($paymeId);
            $state = (int) $tx['state'];
            if ($state === self::STATE_PERFORMED) {
                return ['transaction' => (string) $tx['id'], 'perform_time' => (int) $tx['perform_time'], 'state' => self::STATE_PERFORMED]; // takror
            }
            if ($state !== self::STATE_CREATED) {
                throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id');
            }
            if ($this->expired($tx, $now)) {
                $this->cancelCreated($tx, self::REASON_TIMEOUT, $now);
                throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id', true);
            }
            if ($order === null || $order['status'] !== 'pending') {
                throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id');
            }
            $uid = (int) $order['user_id'];
            $nowUtc = $this->app->now();
            $new = $this->app->db->exec("INSERT IGNORE INTO payments (user_id, provider, amount, currency, payload, charge_id, plan_key, tier, days, created_at)
                VALUES (?, 'payme', ?, 'UZS', ?, ?, ?, ?, ?, ?)", [$uid, intdiv((int) $order['amount_tiyin'], 100), 'payme:' . $order['order_id'],
                'payme_' . $paymeId, $order['plan_key'], $order['tier'], (int) $order['days'], $nowUtc->format('Y-m-d H:i:s')]);
            if ($new === 1) {
                if (!$this->app->users->get($uid)) {
                    throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id'); // foydalanuvchi yo'q — pul yechilmaydi
                }
                $g = Plans::grantInTx($this->app->db, $uid, (string) $order['tier'], (int) $order['days'], $nowUtc);
                if (empty($g['ok'])) {
                    throw new PaymeError(self::ERR_CANNOT_PERFORM, 'id');
                }
                $this->paid[] = ['user_id' => $uid, 'tier' => (string) $g['tier'], 'expires' => $g['expires'] ?? null, 'kept' => !empty($g['kept']),
                    'order' => (string) $order['order_id'], 'amount' => intdiv((int) $order['amount_tiyin'], 100), 'plan_key' => (string) $order['plan_key']];
            } else {
                $this->app->log('Payme: payments qatori allaqachon bor — tarif qayta berilmadi (tx ' . $tx['id'] . ')');
            }
            $this->app->db->exec('UPDATE payme_transactions SET state = ?, perform_time = ? WHERE id = ?', [self::STATE_PERFORMED, $now, (int) $tx['id']]);
            $this->app->db->exec("UPDATE payme_orders SET status = 'paid' WHERE order_id = ?", [$order['order_id']]);
            return ['transaction' => (string) $tx['id'], 'perform_time' => $now, 'state' => self::STATE_PERFORMED];
        });
    }

    private function cancel(array $p): array
    {
        $paymeId = self::paymeId($p);
        $reason = self::intParam($p, 'reason');
        $now = $this->nowMs();
        return $this->atomic(function () use ($paymeId, $reason, $now) {
            [$order, $tx] = $this->lockTx($paymeId);
            $state = (int) $tx['state'];
            if ($state === self::STATE_CANCELLED || $state === self::STATE_CANCELLED_AFTER) {
                return ['transaction' => (string) $tx['id'], 'cancel_time' => (int) $tx['cancel_time'], 'state' => $state];
            }
            if ($state === self::STATE_CREATED) {
                $c = $this->cancelCreated($tx, $reason, $now); // buyurtma ochiq qoladi — qayta to'lash mumkin
                return ['transaction' => (string) $c['id'], 'cancel_time' => $now, 'state' => self::STATE_CANCELLED];
            }
            // bajarilgan — qaytarish faqat ruxsat bo'lsa (tarif — ko'rsatilgan xizmat)
            if (!$this->app->config->get('payme_allow_refunds')) {
                throw new PaymeError(self::ERR_CANNOT_CANCEL, 'id');
            }
            $this->app->db->exec('UPDATE payme_transactions SET state = ?, cancel_time = ?, reason = ? WHERE id = ?', [self::STATE_CANCELLED_AFTER, $now, $reason, (int) $tx['id']]);
            $this->app->db->exec("UPDATE payments SET provider = 'payme_refund' WHERE charge_id = ?", ['payme_' . $paymeId]);
            if ($order !== null) {
                $this->app->db->exec("UPDATE payme_orders SET status = 'cancelled' WHERE order_id = ?", [$order['order_id']]);
                $this->app->db->exec("UPDATE users SET subscription_expires_at = DATE_SUB(subscription_expires_at, INTERVAL ? DAY) WHERE user_id = ? AND subscription_expires_at IS NOT NULL",
                    [(int) $order['days'], (int) $order['user_id']]);
            }
            return ['transaction' => (string) $tx['id'], 'cancel_time' => $now, 'state' => self::STATE_CANCELLED_AFTER];
        });
    }

    private function check(array $p): array
    {
        $tx = $this->tx(self::paymeId($p));
        if ($tx === null) {
            throw new PaymeError(self::ERR_TX_NOT_FOUND, 'id');
        }
        return ['create_time' => (int) $tx['create_time'], 'perform_time' => (int) $tx['perform_time'], 'cancel_time' => (int) $tx['cancel_time'],
            'transaction' => (string) $tx['id'], 'state' => (int) $tx['state'], 'reason' => $tx['reason'] !== null ? (int) $tx['reason'] : null];
    }

    private function statement(array $p): array
    {
        $from = self::intParam($p, 'from');
        $to = self::intParam($p, 'to');
        if ($to < $from) {
            throw new PaymeError(self::ERR_INVALID_REQUEST, 'to');
        }
        $out = [];
        foreach ($this->app->db->all('SELECT * FROM payme_transactions WHERE payme_time BETWEEN ? AND ? ORDER BY payme_time', [$from, $to]) as $tx) {
            $out[] = ['id' => (string) $tx['payme_id'], 'time' => (int) $tx['payme_time'], 'amount' => (int) $tx['amount'], 'account' => ['order_id' => (string) $tx['order_id']],
                'create_time' => (int) $tx['create_time'], 'perform_time' => (int) $tx['perform_time'], 'cancel_time' => (int) $tx['cancel_time'],
                'transaction' => (string) $tx['id'], 'state' => (int) $tx['state'], 'reason' => $tx['reason'] !== null ? (int) $tx['reason'] : null];
        }
        return ['transactions' => $out];
    }

    /** Commit'dan keyin: foydalanuvchi va adminlarga xabar (xato to'lovga ta'sir qilmaydi). */
    private function afterCommit(): void
    {
        foreach ($this->paid as $e) {
            try {
                $uid = $e['user_id'];
                $lang = I18n::norm((string) ($this->app->users->get($uid)['lang'] ?? 'uz'));
                $tz = $this->app->tzFor($uid);
                $date = $e['tier'] === Plans::ENTERPRISE || $e['expires'] === null ? '♾' : TimeParser::show((string) $e['expires'], $tz);
                $this->app->tg->sendMessage($uid, I18n::t($e['kept'] ? 'pay_kept' : 'pay_ok', $lang, ['plan' => Plans::NAMES[$e['tier']] ?? $e['tier'],
                    'date' => $date, 'tz' => Html::e($tz->getName())]) . PlansHandler::perks($this->app, (string) $e['tier'], $lang),
                    \PostAssist\Keyboards::afterPay($lang));
                PlansHandler::notifyAdmins($this->app, 'payme_admin_paid', ['id' => $uid, 'amount' => Plans::fmtUzs((int) $e['amount']), 'plan' => $e['plan_key']]);
            } catch (\Throwable $ex) {
                $this->app->log('Payme xabar: ' . $ex->getMessage());
            }
        }
        $this->paid = [];
    }
}
