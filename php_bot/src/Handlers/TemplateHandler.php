<?php
declare(strict_types=1);

namespace PostAssist\Handlers;

use PostAssist\Ctx;
use PostAssist\Html;
use PostAssist\Keyboards;
use PostAssist\Services\PostRender;

/**
 * 📝 Shablonlar: tayyor postni (matn, media, tugma, reaksiya, sozlamalar, yashirin matn) nom bilan saqlash va
 * keyin bir bosishda yangi post sifatida ochish. Bepul — 3 ta, PRO — 20, ULTRA — 50.
 */
final class TemplateHandler
{
    public const NAME_MAX = 40;

    /** «💾 Shablon qilib saqlash»: nom so'raladi (qoralama saqlanib qoladi). */
    public static function saveAsk(Ctx $ctx): void
    {
        $st = $ctx->state();
        if ($st === null || empty($st['data']['draft']) || strpos($st['state'], 'post_') !== 0) {
            $ctx->replyMenu($ctx->t('draft_expired'));
            return;
        }
        $limit = $ctx->app->templateLimit($ctx->ownerId());
        if ($ctx->app->templates->countFor($ctx->ownerId()) >= $limit) {
            $ctx->reply($ctx->t('tpl_limit', ['max' => $limit]), Keyboards::inline([
                [Keyboards::btn($ctx->t('btn_tpl_list'), 'tpl:list'), Keyboards::btn($ctx->t('btn_plans'), 'pl:show')],
                [Keyboards::btn($ctx->t('btn_back'), 'p:back')],
            ]));
            return;
        }
        $ctx->app->states->set($ctx->userId, 'post_tname', $st['data']);
        $ctx->reply($ctx->t('tpl_ask_name', ['max' => self::NAME_MAX]), Keyboards::inline([[Keyboards::btn($ctx->t('btn_back'), 'p:back')]]));
    }

    public static function nameInput(Ctx $ctx, array $state): void
    {
        $name = trim((string) preg_replace('/\s+/u', ' ', (string) ($ctx->message['text'] ?? '')));
        $len = mb_strlen($name);
        if ($len < 1 || $len > self::NAME_MAX) {
            $ctx->reply($ctx->t('tpl_name_bad', ['max' => self::NAME_MAX]));
            return;
        }
        $app = $ctx->app;
        $data = $state['data'];
        if ($app->templates->countFor($ctx->ownerId()) >= $app->templateLimit($ctx->ownerId())) {
            PostHandler::preview($ctx, $data);
            return;
        }
        $app->templates->create($ctx->ownerId(), $name, $data['draft'], $app->now());
        $ctx->reply($ctx->t('tpl_saved', ['name' => Html::e($name)]));
        PostHandler::preview($ctx, $data);
    }

    /** /templates va «📝 Shablonlar»: ro'yxat (tanlash — yangi post, 🗑 — o'chirish). */
    public static function show(Ctx $ctx, bool $edit = false): void
    {
        $list = $ctx->app->templates->listFor($ctx->ownerId());
        $rows = [];
        foreach ($list as $t) {
            $d = json_decode((string) $t['draft'], true);
            $icon = ['text' => '📄', 'photo' => '🖼', 'video' => '🎬', 'album' => '🗂', 'animation' => '🎞', 'document' => '📎', 'audio' => '🎵'][$d['type'] ?? 'text'] ?? '📄';
            $rows[] = [Keyboards::btn($icon . ' ' . mb_substr((string) $t['name'], 0, 34), 'tpl:u:' . (int) $t['id']), Keyboards::btn('🗑', 'tpl:d:' . (int) $t['id'])];
        }
        $rows[] = [Keyboards::btn($ctx->t('btn_new_post'), 'p:new'), Keyboards::btn($ctx->t('btn_home'), 'm:home')];
        $limit = $ctx->app->templateLimit($ctx->ownerId());
        $text = $list ? $ctx->t('tpl_title', ['n' => count($list), 'max' => $limit]) : $ctx->t('tpl_empty');
        $edit ? $ctx->edit($text, Keyboards::inline($rows)) : $ctx->reply($text, Keyboards::inline($rows));
    }

    /** Shablondan yangi post: hamma sozlamalari bilan preview'ga tushadi (kanal tanlanadi). */
    public static function useTemplate(Ctx $ctx, int $id): void
    {
        if (!$ctx->can('create')) {
            $ctx->replyMenu($ctx->t('team_no_perm'));
            return;
        }
        $t = $ctx->app->templates->getOwned($ctx->ownerId(), $id);
        if ($t === null) {
            $ctx->reply($ctx->t('tpl_not_found'), Keyboards::nav($ctx->lang, 'tpl:list'));
            return;
        }
        if ($ctx->app->channels->countFor($ctx->ownerId()) === 0) {
            $ctx->replyMenu($ctx->t('ch_need_first'));
            ChannelHandler::askAdd($ctx);
            return;
        }
        $ctx->app->templates->touch($id);
        $draft = $t['draft'];
        if (($draft['type'] ?? '') === 'album' && !PostRender::albumValid((array) ($draft['media'] ?? []))) {
            $ctx->reply($ctx->t('tpl_not_found'), Keyboards::nav($ctx->lang, 'tpl:list'));
            return;
        }
        // applyDraft eski qoralamadan tugma/reaksiya/sozlamalarni oladi — shuning uchun shablonning o'zi «eski» qoralama sifatida beriladi
        PostHandler::applyDraft($ctx, ['state' => 'post_content', 'data' => ['draft' => $draft]], $draft);
    }

    public static function askDelete(Ctx $ctx, int $id): void
    {
        $t = $ctx->app->templates->getOwned($ctx->ownerId(), $id);
        if ($t === null) {
            self::show($ctx, true);
            return;
        }
        $ctx->edit($ctx->t('tpl_del_confirm', ['name' => Html::e($t['name'])]), Keyboards::inline([
            [Keyboards::btn($ctx->t('btn_yes_delete'), 'tpl:dok:' . $id), Keyboards::btn($ctx->t('btn_back'), 'tpl:list')],
        ]));
    }

    public static function delete(Ctx $ctx, int $id): void
    {
        $ctx->app->templates->delete($ctx->ownerId(), $id);
        self::show($ctx, true);
    }
}
