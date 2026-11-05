<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\App;
use PostAssist\I18n;
use PostAssist\Services\PostRender;

/**
 * 🔒 «Faqat obunachilar uchun» yashirin matn: kanal postidagi tugma bosilganda bot bosgan odam kanalga obuna
 * ekanini tekshiradi (getChatMember) va matnni faqat obunachiga ogohlantirish oynasida ko'rsatadi.
 * Qolganlarga — «avval obuna bo'ling». Tekshirib bo'lmasa (bot admin emas, tarmoq) — matn ko'rsatilmaydi.
 */
final class HiddenHandler
{
    private const MEMBER = ['creator', 'administrator', 'member'];

    public static function press(App $app, array $cq): void
    {
        $id = (string) ($cq['id'] ?? '');
        $chat = $cq['message']['chat'] ?? [];
        $chatId = (int) ($chat['id'] ?? 0);
        $uid = (int) ($cq['from']['id'] ?? 0);
        $lang = I18n::norm(I18n::detect($cq['from']['language_code'] ?? null));
        if ($uid <= 0 || $chatId === 0) {
            $app->tg->answerCallback($id);
            return;
        }
        if (($chat['type'] ?? '') === 'private') {
            // preview: egasi matnni o'zi ko'radi
            $st = $app->states->get($uid);
            $h = PostRender::hidden($st['data']['draft']['hidden'] ?? null);
            $app->tg->answerCallback($id, $h !== null ? '👁 ' . $h['t'] : '', $h !== null);
            return;
        }
        $row = $app->messages->find($chatId, (int) ($cq['message']['message_id'] ?? 0));
        $h = $row ? PostRender::hidden($row['hidden_text'] ?? null) : null;
        if ($h === null) {
            $app->tg->answerCallback($id);
            return;
        }
        $m = $app->tg->call('getChatMember', ['chat_id' => $chatId, 'user_id' => $uid]);
        $status = (string) ($m['result']['status'] ?? '');
        $member = !empty($m['ok']) && (in_array($status, self::MEMBER, true) || ($status === 'restricted' && !empty($m['result']['is_member'])));
        $app->tg->answerCallback($id, $member ? $h['t'] : I18n::t('hidden_need_sub', $lang), true);
    }
}
