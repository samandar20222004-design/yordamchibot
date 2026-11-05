<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\Look;

/**
 * ✨ Admin: bot ko'rinishi — premium (jonli) emoji o'rgatish va rangli tugmalar.
 * /emoji → premium emojilarni bitta yoki bir nechta xabarda yuborasiz (yoki custom emoji stikerini) → bot har birining
 * oddiy ko'rinishini (🤖, ✍️ …) aniqlab, bot matnlari va tugmalarida o'sha joyga jonli versiyasini qo'yadi.
 */
final class LookHandler
{
    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $look = $ctx->app->look;
        $map = $look->map();
        $have = [];
        $miss = [];
        foreach (Look::UI_EMOJI as $e) {
            if (isset($map[Look::norm($e)])) {
                $have[] = '<tg-emoji emoji-id="' . $map[Look::norm($e)] . '">' . $e . '</tg-emoji>';
            } else {
                $miss[] = $e;
            }
        }
        $ctx->app->states->set($ctx->userId, 'emoji_wait');
        $text = $ctx->t('look_title', [
            'n' => count($map), 'premium' => $ctx->t($look->premiumOn() ? 'ap_on' : 'ap_off'), 'styles' => $ctx->t($look->stylesOn() ? 'ap_on' : 'ap_off'),
            'have' => $have ? implode(' ', $have) : '—', 'miss' => $miss ? implode(' ', $miss) : '—',
        ]);
        $kb = Keyboards::inline([
            [Keyboards::btn($ctx->t($look->premiumOn() ? 'btn_look_prem_off' : 'btn_look_prem_on'), 'emj:tg'),
                Keyboards::btn($ctx->t($look->stylesOn() ? 'btn_look_st_off' : 'btn_look_st_on'), 'emj:st')],
            [Keyboards::btn($ctx->t('btn_look_clear'), 'emj:clr')],
            Keyboards::navRow($ctx->lang, 'a:stats'),
        ]);
        // ro'yxatning o'zi premium emoji bilan — Telegram rad etsa Telegram::call oddiy holda qayta yuboradi
        $edit ? $ctx->edit($text, $kb) : $ctx->reply($text, $kb);
    }

    /**
     * Xabardagi custom emoji'lar: oddiy ko'rinishi => custom_emoji_id.
     * @return array<string,string>
     */
    public static function extract(array $msg): array
    {
        $out = [];
        if (!empty($msg['sticker']['custom_emoji_id']) && !empty($msg['sticker']['emoji'])) {
            $out[(string) $msg['sticker']['emoji']] = (string) $msg['sticker']['custom_emoji_id'];
        }
        foreach ([['text', 'entities'], ['caption', 'caption_entities']] as [$tf, $ef]) {
            $text = (string) ($msg[$tf] ?? '');
            if ($text === '' || empty($msg[$ef]) || !is_array($msg[$ef])) {
                continue;
            }
            $u = mb_convert_encoding($text, 'UTF-16LE', 'UTF-8');
            foreach ($msg[$ef] as $en) {
                if (($en['type'] ?? '') !== 'custom_emoji' || empty($en['custom_emoji_id'])) {
                    continue;
                }
                $alt = mb_convert_encoding(substr($u, (int) $en['offset'] * 2, (int) $en['length'] * 2), 'UTF-8', 'UTF-16LE');
                if ($alt !== '') {
                    $out[$alt] = (string) $en['custom_emoji_id'];
                }
            }
        }
        return $out;
    }

    /** Holat emoji_wait: premium emojili xabar keldi. */
    public static function received(Ctx $ctx): void
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return;
        }
        $found = self::extract($ctx->message ?? []);
        if (!$found) {
            $ctx->reply($ctx->t('look_none'), Keyboards::nav($ctx->lang, 'a:stats'));
            return;
        }
        $ctx->app->look->addMap($found);
        $list = [];
        foreach ($found as $e => $id) {
            $list[] = '<tg-emoji emoji-id="' . Html::e($id) . '">' . Html::e($e) . '</tg-emoji>';
        }
        $ctx->reply($ctx->t('look_saved', ['n' => count($found), 'list' => implode(' ', $list)]));
        self::show($ctx);
    }

    public static function action(Ctx $ctx, string $act): void
    {
        if (!$ctx->app->isAdmin($ctx->userId)) {
            return;
        }
        $look = $ctx->app->look;
        if ($act === 'tg') {
            $look->set(Look::KEY_ON, $look->premiumOn() ? '0' : '1');
        } elseif ($act === 'st') {
            $look->set(Look::KEY_STYLES, $look->stylesOn() ? '0' : '1');
        } elseif ($act === 'clr') {
            $look->clearMap();
        }
        self::show($ctx, true);
    }
}
