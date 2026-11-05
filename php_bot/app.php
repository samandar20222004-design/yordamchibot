<?php
// 📱 PostAssist Mini App (Telegram ichida ochiladi). Tashqi kutubxonasiz: bitta sahifa, ma'lumot api.php orqali.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\I18n;

$nonce = base64_encode(random_bytes(16));
header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-{$nonce}' https://telegram.org; style-src 'self' 'unsafe-inline'; "
    . "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'none'");
$i18n = [];
foreach (I18n::LANGS as $l) {
    $i18n[$l] = array_filter(I18n::table($l), static function ($k) {
        return strpos((string) $k, 'ma_') === 0;
    }, ARRAY_FILTER_USE_KEY);
}
$json = json_encode($i18n, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT);
?><!doctype html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<title>PostAssist</title>
<script src="https://telegram.org/js/telegram-web-app.js" nonce="<?= $nonce ?>"></script>
<style>
:root{--bg:var(--tg-theme-bg-color,#f4f6fb);--card:var(--tg-theme-secondary-bg-color,#fff);--text:var(--tg-theme-text-color,#14161c);
--hint:var(--tg-theme-hint-color,#8a8f9c);--accent:var(--tg-theme-button-color,#2f7cf6);--accent-text:var(--tg-theme-button-text-color,#fff);
--link:var(--tg-theme-link-color,#2f7cf6);--danger:#e5484d;--ok:#2fb36b;--radius:16px;--shadow:0 6px 24px rgba(20,30,60,.08)}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
body{padding:0 0 calc(84px + env(safe-area-inset-bottom))}
header{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;padding:14px 16px;background:var(--bg)}
.logo{width:34px;height:34px;border-radius:11px;background:linear-gradient(135deg,#2f7cf6,#8b5cf6);display:grid;place-items:center;color:#fff;font-size:18px}
h1{font-size:18px;margin:0;flex:1}.badge{font-size:12px;font-weight:600;padding:4px 10px;border-radius:20px;background:var(--card);box-shadow:var(--shadow)}
.badge.pro{background:linear-gradient(135deg,#2f7cf6,#8b5cf6);color:#fff}.badge.ultra{background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff}
main{padding:0 14px}.page{display:none;animation:in .25s ease}.page.on{display:block}@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1}}
.card{background:var(--card);border-radius:var(--radius);padding:14px;margin:0 0 12px;box-shadow:var(--shadow)}
.card h3{margin:0 0 10px;font-size:15px}.muted{color:var(--hint);font-size:13px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.stat{background:var(--card);border-radius:var(--radius);padding:12px;text-align:center;box-shadow:var(--shadow)}.stat b{display:block;font-size:22px}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
button,.btn{font:inherit;border:0;border-radius:12px;padding:12px 14px;background:var(--accent);color:var(--accent-text);font-weight:600;cursor:pointer;width:100%}
button.ghost{background:var(--card);color:var(--text);box-shadow:var(--shadow)}button.small{padding:7px 10px;font-size:13px;width:auto}
button.danger{background:var(--danger);color:#fff}button:disabled{opacity:.5}
.big{padding:16px;font-size:16px;text-align:left;display:flex;gap:10px;align-items:center}.big span{font-size:22px}
label{display:block;font-size:13px;color:var(--hint);margin:10px 0 6px}
input,select,textarea{font:inherit;width:100%;padding:11px 12px;border-radius:12px;border:1px solid rgba(128,128,128,.25);background:var(--bg);color:var(--text)}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{padding:8px 12px;border-radius:20px;background:var(--bg);border:1px solid rgba(128,128,128,.25);font-size:14px;cursor:pointer}
.chip.on{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
.toolbar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.toolbar button{width:auto;padding:7px 11px;background:var(--bg);color:var(--text);border:1px solid rgba(128,128,128,.25)}
.editor{min-height:140px;padding:12px;border-radius:12px;border:1px solid rgba(128,128,128,.25);background:var(--bg);outline:none;white-space:pre-wrap;word-break:break-word}
.editor:empty:before{content:attr(data-ph);color:var(--hint)}.editor blockquote,.bubble blockquote{border-left:3px solid var(--accent);margin:4px 0;padding:2px 8px}
.editor code,.bubble code{background:rgba(128,128,128,.15);padding:1px 4px;border-radius:4px}
.counter{text-align:right;font-size:12px;color:var(--hint);margin-top:4px}.counter.bad{color:var(--danger)}
.row{display:flex;gap:8px}.row>*{flex:1}
.media{display:flex;align-items:center;gap:10px}.media img,.media video{width:72px;height:72px;object-fit:cover;border-radius:10px}
.preview{background:linear-gradient(160deg,#cfe3f7,#e8d9f5);border-radius:var(--radius);padding:14px}
.bubble{background:#fff;color:#111;border-radius:14px 14px 14px 4px;padding:8px 10px;max-width:92%;box-shadow:0 1px 2px rgba(0,0,0,.15);white-space:pre-wrap;word-break:break-word}
.bubble img,.bubble video{width:100%;border-radius:10px;margin-bottom:6px;display:block}.bubble a{color:#2f7cf6}
.pbtn{margin-top:6px;background:rgba(255,255,255,.7);color:#2f7cf6;text-align:center;border-radius:10px;padding:7px;font-size:14px;max-width:92%}
.rx{display:flex;gap:6px;margin-top:6px;max-width:92%}.rx span{flex:1;text-align:center;background:rgba(255,255,255,.7);border-radius:10px;padding:6px;font-size:14px}
.post{display:flex;gap:10px;align-items:flex-start}.post .body{flex:1;min-width:0}.post .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;background:var(--bg);margin:4px 4px 0 0}
nav{position:fixed;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));display:flex;background:var(--card);border-radius:20px;box-shadow:0 8px 30px rgba(0,0,0,.15);z-index:9}
nav a{flex:1;text-align:center;padding:9px 4px 8px;font-size:11px;color:var(--hint);text-decoration:none}nav a i{display:block;font-style:normal;font-size:20px}
nav a.on{color:var(--accent);font-weight:600}
.toast{position:fixed;left:50%;bottom:100px;transform:translateX(-50%);background:#14161c;color:#fff;padding:10px 16px;border-radius:12px;font-size:14px;z-index:20;max-width:90%;display:none}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:15;display:none;align-items:flex-end}.modal.on{display:flex}
.sheet{background:var(--card);width:100%;border-radius:20px 20px 0 0;padding:16px 16px calc(16px + env(safe-area-inset-bottom));max-height:85vh;overflow:auto}
.empty{text-align:center;padding:30px 10px;color:var(--hint)}.empty b{display:block;font-size:40px}
.banner{background:linear-gradient(135deg,#2f7cf6,#8b5cf6);color:#fff;border-radius:var(--radius);padding:12px 14px;margin-bottom:12px;display:flex;gap:10px;align-items:center}
.banner button{background:#fff;color:#2f7cf6;width:auto}
details summary{cursor:pointer;font-weight:600;padding:4px 0}.spin{display:inline-block;animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
#boot{display:grid;place-items:center;height:70vh;color:var(--hint)}
</style>
</head>
<body>
<header><div class="logo">🤖</div><h1>PostAssist</h1><span class="badge" id="plan">…</span></header>
<main>
  <div id="boot"><div><span class="spin">⏳</span></div></div>

  <section class="page" id="p-home">
    <div class="card"><h3 id="hello"></h3><div class="muted" id="tzline"></div></div>
    <div class="stats">
      <div class="stat"><b id="s-pending">0</b><span class="muted" data-t="ma_stat_pending"></span></div>
      <div class="stat"><b id="s-sent">0</b><span class="muted" data-t="ma_stat_sent"></span></div>
      <div class="stat"><b id="s-channels">0</b><span class="muted" data-t="ma_stat_channels"></span></div>
    </div>
    <div class="actions">
      <button class="big" data-go="post"><span>✍️</span><b data-t="ma_new_post"></b></button>
      <button class="big ghost" id="home-ai"><span>✨</span><b data-t="ma_ai_post"></b></button>
      <button class="big ghost" data-go="queue"><span>📅</span><b data-t="ma_tab_queue"></b></button>
      <button class="big ghost" id="open-bot"><span>🤖</span><b data-t="ma_open_bot"></b></button>
    </div>
    <div class="card" id="ai-card"><h3 data-t="ma_ai_title"></h3><div class="muted" id="ai-quota"></div></div>
    <div class="card"><h3 data-t="ma_in_bot"></h3>
      <div class="actions">
        <button class="big ghost" data-bot="go_market"><span>💰</span><b data-t="ma_go_market"></b></button>
        <button class="big ghost" data-bot="go_team"><span>👥</span><b data-t="ma_go_team"></b></button>
        <button class="big ghost" data-bot="go_plans"><span>💎</span><b data-t="ma_plans"></b></button>
        <button class="big ghost" data-bot="go_channels"><span>📢</span><b data-t="ma_go_channels"></b></button>
      </div></div>
  </section>

  <section class="page" id="p-post">
    <div class="banner" id="draft-banner" style="display:none"><div style="flex:1" data-t="ma_draft_found"></div><button class="small" id="draft-load" data-t="ma_open"></button></div>
    <div class="card" id="no-ch" style="display:none"><div class="empty"><b>📢</b><span data-t="ma_no_channels"></span></div><button id="no-ch-bot" data-t="ma_open_bot"></button></div>
    <div id="editor-wrap">
      <div class="card"><h3 data-t="ma_channel"></h3><div class="chips" id="ch-list"></div></div>
      <div class="card">
        <div class="media" id="media-box" style="display:none"><span id="media-thumb"></span><div style="flex:1" class="muted" id="media-name"></div><button class="small ghost" id="media-del">✕</button></div>
        <button class="ghost" id="media-add" data-t="ma_add_media"></button>
        <input type="file" id="media-file" accept="image/jpeg,image/png,image/webp,video/mp4" hidden>
      </div>
      <div class="card">
        <div class="toolbar">
          <button data-cmd="bold"><b>B</b></button><button data-cmd="italic"><i>I</i></button><button data-cmd="underline"><u>U</u></button>
          <button data-cmd="strikeThrough"><s>S</s></button><button data-cmd="link">🔗</button><button data-cmd="code">&lt;/&gt;</button>
          <button data-cmd="quote">❝</button><button data-cmd="clear">⌫</button>
        </div>
        <div class="editor" id="ed" contenteditable="true"></div>
        <div class="counter" id="cnt"></div>
        <div class="row" id="ai-row" style="margin-top:10px">
          <button class="ghost small" id="ai-write">✨ <span data-t="ma_ai_write"></span></button>
          <select id="ai-edit"><option value="" data-t="ma_ai_edit"></option>
            <option value="improve" data-t="ma_aie_improve"></option><option value="shorten" data-t="ma_aie_shorten"></option>
            <option value="emoji" data-t="ma_aie_emoji"></option><option value="rewrite" data-t="ma_aie_rewrite"></option>
            <option value="tr_uz">🇺🇿 UZ</option><option value="tr_ru">🇷🇺 RU</option><option value="tr_en">🇬🇧 EN</option></select>
        </div>
      </div>
      <div class="card">
        <details><summary>🔗 <span data-t="ma_button"></span></summary>
          <label data-t="ma_button_text"></label><input id="b-text" maxlength="64">
          <label data-t="ma_button_url"></label><input id="b-url" placeholder="@kanal, t.me/..., sayt.uz">
        </details>
        <details id="rx-box"><summary>👍 <span data-t="ma_reactions"></span></summary><div class="chips" id="rx-list" style="margin-top:8px"></div></details>
        <details><summary>🔄 <span data-t="ma_repeat"></span></summary>
          <select id="rep"><option value="" data-t="ma_rep_none"></option><option value="daily" data-t="ma_rep_daily"></option>
            <option value="weekly" data-t="ma_rep_weekly"></option><option value="monthly" data-t="ma_rep_monthly"></option><option value="twice" data-t="ma_rep_twice"></option></select>
          <div id="t2-box" style="display:none"><label data-t="ma_time2"></label><input type="time" id="t2"></div>
        </details>
        <details><summary>⏳ <span data-t="ma_autodel"></span></summary><select id="ad"></select></details>
      </div>
      <div class="card"><h3 data-t="ma_preview"></h3><div class="preview"><div class="bubble" id="pv"></div><div id="pv-btn"></div><div id="pv-rx"></div></div></div>
      <div class="card">
        <div class="chips"><span class="chip on" data-when="now" data-t="ma_now"></span><span class="chip" data-when="later" data-t="ma_later"></span></div>
        <div id="when-box" style="display:none"><label data-t="ma_when"></label><input type="datetime-local" id="when"><div class="muted" id="when-tz"></div></div>
        <div style="margin-top:12px"><button id="submit" data-t="ma_send_now"></button></div>
      </div>
    </div>
  </section>

  <section class="page" id="p-queue"><div id="q-list"></div></section>

  <section class="page" id="p-me">
    <div class="card"><h3 id="me-name"></h3><div class="muted" id="me-plan"></div><div class="muted" id="me-limits"></div>
      <div style="margin-top:10px"><button id="me-plans" data-t="ma_plans"></button></div></div>
    <div class="card"><label data-t="ma_lang"></label><select id="me-lang"><option value="uz">🇺🇿 O'zbekcha</option><option value="ru">🇷🇺 Русский</option><option value="en">🇬🇧 English</option></select>
      <label data-t="ma_tz"></label><select id="me-tz"></select></div>
    <div class="card muted" data-t="ma_about"></div>
  </section>
</main>

<nav>
  <a href="#" data-go="home" class="on"><i>🏠</i><span data-t="ma_tab_home"></span></a>
  <a href="#" data-go="post"><i>✍️</i><span data-t="ma_tab_post"></span></a>
  <a href="#" data-go="queue"><i>📅</i><span data-t="ma_tab_queue"></span></a>
  <a href="#" data-go="me"><i>👤</i><span data-t="ma_tab_me"></span></a>
</nav>

<div class="modal" id="modal"><div class="sheet" id="sheet"></div></div>
<div class="toast" id="toast"></div>

<script nonce="<?= $nonce ?>">
(function () {
  'use strict';
  var I18N = <?= $json ?>;
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  var initData = tg ? tg.initData : '';
  var lang = 'uz', me = null, state = {channel: 0, type: 'text', fileId: '', mediaUrl: '', when: 'now', reactions: '', ai: null};
  var $ = function (id) { return document.getElementById(id); };
  var t = function (k, p) {
    var s = (I18N[lang] && I18N[lang][k]) || I18N.uz[k] || k;
    if (p) { Object.keys(p).forEach(function (x) { s = s.split('{' + x + '}').join(String(p[x])); }); }
    return s;
  };
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); };
  var haptic = function (k) { try { tg && tg.HapticFeedback && (k === 'ok' ? tg.HapticFeedback.notificationOccurred('success') : tg.HapticFeedback.impactOccurred('light')); } catch (e) {} };
  function toast(msg) { var el = $('toast'); el.textContent = msg; el.style.display = 'block'; clearTimeout(toast.t); toast.t = setTimeout(function () { el.style.display = 'none'; }, 2800); }

  function api(action, body, isForm) {
    var opt = {method: 'POST', headers: {'X-Telegram-Init-Data': initData}};
    if (isForm) { opt.body = body; } else { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body || {}); }
    return fetch('api.php?a=' + action, opt).then(function (r) {
      return r.json().catch(function () { return {ok: false, error: 'server'}; }).then(function (j) { j._status = r.status; return j; });
    }).catch(function () { return {ok: false, error: 'network'}; });
  }
  function errText(r) {
    var key = 'ma_err_' + (r.error || 'server');
    var s = t(key, {max: r.max || '', len: r.len || '', max_mb: r.max_mb || ''});
    if (s === key) { s = t('ma_err_server'); }
    return r.reason ? s + ' ' + r.reason : s;
  }

  function applyI18n() {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-t]').forEach(function (el) { el.textContent = t(el.getAttribute('data-t')); });
    $('ed').setAttribute('data-ph', t('ma_text_ph'));
  }

  // ---------- navigatsiya (Telegram «Orqaga» tugmasi bilan)
  var cur = 'home';
  function go(page) {
    cur = page;
    document.querySelectorAll('.page').forEach(function (p) { p.classList.toggle('on', p.id === 'p-' + page); });
    document.querySelectorAll('nav a').forEach(function (a) { a.classList.toggle('on', a.getAttribute('data-go') === page); });
    if (tg && tg.BackButton) { page === 'home' ? tg.BackButton.hide() : tg.BackButton.show(); }
    if (page === 'queue') { loadQueue(); }
    if (page === 'post') { refreshPreview(); }
    window.scrollTo(0, 0);
  }
  document.addEventListener('click', function (e) {
    var g = e.target.closest('[data-go]');
    if (g) { e.preventDefault(); haptic(); go(g.getAttribute('data-go')); }
  });
  if (tg && tg.BackButton) { tg.BackButton.onClick(function () { if ($('modal').classList.contains('on')) { closeModal(); } else { go('home'); } }); }

  var BOT_SECTIONS = ['go_market', 'go_team', 'go_plans', 'go_channels'];
  function openBot(section) {
    if (!me) { return; }
    var url = 'https://t.me/' + me.bot;
    if (typeof section === 'string' && BOT_SECTIONS.indexOf(section) >= 0) { url += '?start=' + section; }
    if (tg && tg.openTelegramLink) { tg.openTelegramLink(url); setTimeout(function () { tg.close(); }, 300); } else { location.href = url; }
  }
  $('open-bot').onclick = function () { openBot(); }; $('no-ch-bot').onclick = function () { openBot('go_channels'); };
  $('me-plans').onclick = function () { openBot('go_plans'); };
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-bot]');
    if (b) { e.preventDefault(); haptic(); openBot(b.getAttribute('data-bot')); }
  });

  function modal(html) { $('sheet').innerHTML = html; $('modal').classList.add('on'); }
  function closeModal() { $('modal').classList.remove('on'); }
  $('modal').addEventListener('click', function (e) { if (e.target.id === 'modal') { closeModal(); } });

  // ---------- muharrir: DOM -> Telegram HTML
  function toHtml(node) {
    var out = '';
    node.childNodes.forEach(function (n) {
      if (n.nodeType === 3) { out += esc(n.nodeValue); return; }
      if (n.nodeType !== 1) { return; }
      var tag = n.tagName.toLowerCase(), inner = toHtml(n);
      var map = {b: 'b', strong: 'b', i: 'i', em: 'i', u: 'u', s: 's', strike: 's', del: 's', code: 'code', blockquote: 'blockquote'};
      if (tag === 'br') { out += '\n'; } else if (map[tag]) { out += inner ? '<' + map[tag] + '>' + inner + '</' + map[tag] + '>' : ''; }
      else if (tag === 'a' && n.getAttribute('href')) { out += '<a href="' + esc(n.getAttribute('href')) + '">' + inner + '</a>'; }
      else if (tag === 'div' || tag === 'p') { out += (out && !/\n$/.test(out) ? '\n' : '') + inner + '\n'; }
      else if (tag === 'span' && /font-weight:\s*(bold|[6-9]00)/.test(n.getAttribute('style') || '')) { out += '<b>' + inner + '</b>'; }
      else { out += inner; }
    });
    return out;
  }
  function editorHtml() { return toHtml($('ed')).replace(/\n+$/, ''); }
  function setEditor(html) { $('ed').innerHTML = String(html || '').replace(/\n/g, '<br>'); refreshPreview(); }
  function plainLen(html) { var d = document.createElement('div'); d.innerHTML = html; var s = d.textContent || ''; var n = 0; for (var ch of s) { n += ch.codePointAt(0) > 0xffff ? 2 : 1; } return n; }

  document.querySelectorAll('.toolbar button').forEach(function (b) {
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });
    b.onclick = function () {
      var c = b.getAttribute('data-cmd'); $('ed').focus(); haptic();
      if (c === 'link') { var u = prompt(t('ma_link_ph'), 'https://'); if (u) { document.execCommand('createLink', false, u); } }
      else if (c === 'code' || c === 'quote') { wrap(c === 'code' ? 'code' : 'blockquote'); }
      else if (c === 'clear') { document.execCommand('removeFormat'); document.execCommand('unlink'); }
      else { document.execCommand(c); }
      refreshPreview();
    };
  });
  function wrap(tag) {
    var sel = window.getSelection(); if (!sel.rangeCount || sel.isCollapsed) { return; }
    var r = sel.getRangeAt(0), el = document.createElement(tag);
    try { el.appendChild(r.extractContents()); r.insertNode(el); } catch (e) {}
  }
  $('ed').addEventListener('input', refreshPreview);
  $('ed').addEventListener('paste', function (e) {
    e.preventDefault(); var txt = (e.clipboardData || window.clipboardData).getData('text/plain'); document.execCommand('insertText', false, txt);
  });

  // ---------- jonli ko'rinish (kanalda qanday chiqadi)
  function refreshPreview() {
    var html = editorHtml(), max = state.type === 'text' ? 4096 : 1024, len = plainLen(html);
    var c = $('cnt'); c.textContent = len + ' / ' + max; c.classList.toggle('bad', len > max);
    var media = '';
    if (state.mediaUrl) { media = state.type === 'video' ? '<video src="' + state.mediaUrl + '" muted playsinline></video>' : '<img src="' + state.mediaUrl + '">'; }
    else if (state.fileId) { media = '<div class="muted">🖼 ' + esc(t('ma_media_attached')) + '</div>'; }
    var mark = me && me.plan.free ? '🤖 @' + esc(me.bot) + '\n\n' : '';
    $('pv').innerHTML = media + mark + (html || '<span class="muted">' + esc(t('ma_text_ph')) + '</span>');
    var bt = $('b-text').value.trim();
    $('pv-btn').innerHTML = bt ? '<div class="pbtn">' + esc(bt) + '</div>' : '';
    $('pv-rx').innerHTML = state.reactions ? '<div class="rx">' + state.reactions.split(',').map(function (e) { return '<span>' + esc(e) + '</span>'; }).join('') + '</div>' : '';
  }
  ['b-text', 'b-url'].forEach(function (id) { $(id).addEventListener('input', refreshPreview); });

  // ---------- media
  $('media-add').onclick = function () { $('media-file').click(); };
  $('media-file').onchange = function () {
    var f = this.files[0]; if (!f) { return; }
    if (f.size > 10 * 1024 * 1024) { toast(t('ma_err_too_big', {max_mb: 10})); return; }
    $('media-add').disabled = true; $('media-add').textContent = '⏳ ' + t('ma_uploading');
    var fd = new FormData(); fd.append('file', f);
    api('upload', fd, true).then(function (r) {
      $('media-add').disabled = false; $('media-add').textContent = t('ma_add_media');
      if (!r.ok) { toast(errText(r)); return; }
      state.type = r.type; state.fileId = r.file_id; state.mediaUrl = URL.createObjectURL(f);
      $('media-box').style.display = 'flex'; $('media-add').style.display = 'none';
      $('media-thumb').innerHTML = r.type === 'video' ? '<video src="' + state.mediaUrl + '" muted></video>' : '<img src="' + state.mediaUrl + '">';
      $('media-name').textContent = f.name; haptic('ok'); refreshPreview();
    });
  };
  $('media-del').onclick = function () {
    state.type = 'text'; state.fileId = ''; state.mediaUrl = ''; $('media-file').value = '';
    $('media-box').style.display = 'none'; $('media-add').style.display = ''; refreshPreview();
  };

  // ---------- kanal, reaksiya, takror, avto-o'chirish, vaqt
  function renderChannels() {
    var box = $('ch-list'); box.innerHTML = '';
    me.channels.forEach(function (c) {
      var el = document.createElement('span'); el.className = 'chip' + (c.id === state.channel ? ' on' : ''); el.textContent = '📢 ' + c.title;
      el.onclick = function () { state.channel = c.id; renderChannels(); haptic(); }; box.appendChild(el);
    });
  }
  function renderReactions() {
    var box = $('rx-list'); box.innerHTML = '';
    [''].concat(me.reaction_sets).forEach(function (set) {
      var el = document.createElement('span'); el.className = 'chip' + (set === state.reactions ? ' on' : '');
      el.textContent = set ? set.split(',').join(' ') : t('ma_rx_none');
      el.onclick = function () { state.reactions = set; renderReactions(); refreshPreview(); }; box.appendChild(el);
    });
  }
  $('rep').onchange = function () { $('t2-box').style.display = this.value === 'twice' ? '' : 'none'; };
  document.querySelectorAll('[data-when]').forEach(function (c) {
    c.onclick = function () {
      state.when = c.getAttribute('data-when');
      document.querySelectorAll('[data-when]').forEach(function (x) { x.classList.toggle('on', x === c); });
      $('when-box').style.display = state.when === 'later' ? '' : 'none';
      $('submit').textContent = t(state.when === 'later' ? 'ma_schedule' : 'ma_send_now');
    };
  });

  // ---------- yuborish
  $('submit').onclick = function () {
    if (!state.channel) { toast(t('ma_err_channel')); return; }
    var body = {channel_id: state.channel, type: state.type, file_id: state.fileId, text: editorHtml(),
      button_text: $('b-text').value.trim(), button_url: $('b-url').value.trim(), reactions: state.reactions,
      repeat: $('rep').value, time2: $('t2').value, delete_after: parseInt($('ad').value || '0', 10), when: 'now'};
    if (state.when === 'later') { if (!$('when').value) { toast(t('ma_err_bad_time')); return; } body.when = $('when').value; }
    var btn = this; btn.disabled = true; btn.textContent = '⏳';
    api('post_create', body).then(function (r) {
      btn.disabled = false; btn.textContent = t(state.when === 'later' ? 'ma_schedule' : 'ma_send_now');
      if (!r.ok) { toast(errText(r)); return; }
      haptic('ok');
      var msg = r.status === 'sent' ? t('ma_sent') : r.status === 'queued' ? t('ma_queued') : t('ma_scheduled', {when: r.when});
      if (r.next) { msg += ' ' + t('ma_next', {when: r.next}); }
      toast(msg); resetEditor(); loadMe();
    });
  };
  function resetEditor() {
    setEditor(''); $('b-text').value = ''; $('b-url').value = ''; $('rep').value = ''; $('t2-box').style.display = 'none'; $('ad').value = '0';
    state.reactions = ''; renderReactions(); $('media-del').onclick();
  }

  // ---------- AI
  function aiOff() { if (!me.ai.enabled) { toast(t('ma_err_ai_disabled')); return true; } return false; }
  function aiStart() {
    if (aiOff()) { return; }
    var styles = ['news', 'sales', 'fun', 'useful', 'short'];
    modal('<h3>✨ ' + esc(t('ma_ai_post')) + '</h3><textarea id="ai-topic" rows="4" placeholder="' + esc(t('ma_ai_topic_ph')) + '"></textarea>' +
      '<label>' + esc(t('ma_ai_style')) + '</label><div class="chips" id="ai-styles">' +
      styles.map(function (s, i) { return '<span class="chip' + (i === 0 ? ' on' : '') + '" data-st="' + s + '">' + esc(t('ma_style_' + s)) + '</span>'; }).join('') +
      '</div><div style="margin-top:14px"><button id="ai-go">' + esc(t('ma_ai_generate')) + '</button></div><div class="muted" style="margin-top:8px">' + esc(quotaText()) + '</div>');
    var style = 'news';
    document.querySelectorAll('#ai-styles .chip').forEach(function (c) {
      c.onclick = function () { style = c.getAttribute('data-st'); document.querySelectorAll('#ai-styles .chip').forEach(function (x) { x.classList.toggle('on', x === c); }); };
    });
    $('ai-go').onclick = function () {
      var topic = $('ai-topic').value.trim(); if (topic.length < 3) { toast(t('ma_err_bad_input')); return; }
      var b = this; b.disabled = true; b.textContent = '⏳ ' + t('ma_ai_working');
      api('ai', {mode: 'post', topic: topic, style: style}).then(function (r) {
        b.disabled = false; b.textContent = t('ma_ai_generate');
        if (!r.ok) { toast(errText(r)); return; }
        closeModal(); go('post'); setEditor(r.text); haptic('ok'); loadMe();
      });
    };
  }
  $('home-ai').onclick = aiStart; $('ai-write').onclick = aiStart;
  $('ai-edit').onchange = function () {
    var action = this.value; this.value = ''; if (!action || aiOff()) { return; }
    var text = editorHtml(); if (!text.trim()) { toast(t('ma_err_bad_input')); return; }
    toast('⏳ ' + t('ma_ai_working'));
    api('ai', {mode: 'edit', text: text, action: action, max: state.type === 'text' ? 4096 : 1024}).then(function (r) {
      if (!r.ok) { toast(errText(r)); return; } setEditor(r.text); haptic('ok'); loadMe();
    });
  };
  function quotaText() {
    if (!me.ai.enabled) { return t('ma_err_ai_disabled'); }
    return me.ai.limit === 0 ? t('ma_ai_unlimited') : t('ma_ai_quota', {left: me.ai.left, limit: me.ai.limit, credits: me.ai.credits});
  }

  // ---------- navbat
  function loadQueue() {
    $('q-list').innerHTML = '<div class="empty"><span class="spin">⏳</span></div>';
    api('posts').then(function (r) {
      if (!r.ok) { $('q-list').innerHTML = '<div class="empty">' + esc(errText(r)) + '</div>'; return; }
      if (!r.posts.length) {
        $('q-list').innerHTML = '<div class="card empty"><b>📭</b>' + esc(t('ma_q_empty')) + '<div style="margin-top:12px"><button data-go="post">' + esc(t('ma_new_post')) + '</button></div></div>';
        return;
      }
      $('q-list').innerHTML = r.posts.map(function (p, i) {
        var d = document.createElement('div'); d.innerHTML = p.text; var plain = (d.textContent || '').trim() || '[' + p.type + ']';
        return '<div class="card post"><div class="body"><b>🕒 ' + esc(p.when) + '</b><div class="muted">📢 ' + esc(p.channel) + '</div>' +
          '<div class="t">' + (p.type !== 'text' ? '🖼 ' : '') + esc(plain) + '</div>' +
          (p.repeat ? '<span class="tag">🔄 ' + esc(p.repeat) + '</span>' : '') + (p.delete_after ? '<span class="tag">⏳ ' + (p.delete_after / 60) + 'h</span>' : '') +
          (p.reactions ? '<span class="tag">' + esc(p.reactions.split(',').join(' ')) + '</span>' : '') +
          '</div><div><button class="small ghost" data-edit="' + i + '">✏️</button><div style="height:6px"></div><button class="small danger" data-del="' + p.id + '">🗑</button></div></div>';
      }).join('');
      document.querySelectorAll('[data-del]').forEach(function (b) { b.onclick = function () { askCancel(parseInt(b.getAttribute('data-del'), 10)); }; });
      document.querySelectorAll('[data-edit]').forEach(function (b) { b.onclick = function () { editPost(r.posts[parseInt(b.getAttribute('data-edit'), 10)]); }; });
    });
  }
  function askCancel(id) {
    var done = function (yes) {
      if (!yes) { return; }
      api('post_cancel', {id: id}).then(function (r) { toast(r.ok ? t('ma_cancelled') : errText(r)); if (r.ok) { haptic('ok'); loadQueue(); loadMe(); } });
    };
    if (tg && tg.showConfirm) { tg.showConfirm(t('ma_confirm_cancel'), done); } else { done(confirm(t('ma_confirm_cancel'))); }
  }
  function editPost(p) {
    modal('<h3>✏️ ' + esc(t('ma_edit_post')) + '</h3><div class="editor" id="ed2" contenteditable="true"></div>' +
      '<label>' + esc(t('ma_when')) + '</label><input type="datetime-local" id="when2" value="' + esc(p.when_local) + '">' +
      '<div class="row" style="margin-top:14px"><button class="ghost" id="e-cancel">' + esc(t('ma_back')) + '</button><button id="e-save">' + esc(t('ma_save')) + '</button></div>');
    $('ed2').innerHTML = String(p.text || '').replace(/\n/g, '<br>');
    $('e-cancel').onclick = closeModal;
    $('e-save').onclick = function () {
      var body = {id: p.id, text: toHtml($('ed2')).replace(/\n+$/, '')};
      if ($('when2').value && $('when2').value !== p.when_local) { body.when = $('when2').value; }
      api('post_update', body).then(function (r) { if (!r.ok) { toast(errText(r)); return; } closeModal(); toast(t('ma_saved')); haptic('ok'); loadQueue(); });
    };
  }

  // ---------- profil
  $('me-lang').onchange = function () {
    var l = this.value; api('settings', {lang: l}).then(function (r) { if (r.ok) { lang = l; applyI18n(); render(); toast(t('ma_saved')); } else { toast(errText(r)); } });
  };
  $('me-tz').onchange = function () {
    api('settings', {timezone: this.value}).then(function (r) { if (r.ok) { toast(t('ma_saved')); loadMe(); } else { toast(errText(r)); } });
  };

  function render() {
    var p = me.plan;
    $('plan').textContent = p.name; $('plan').className = 'badge ' + (p.tier === 'ultra' ? 'ultra' : p.tier === 'free' ? '' : 'pro');
    $('hello').textContent = t('ma_hello', {name: me.user.name || ''});
    $('tzline').textContent = '🕒 ' + me.user.timezone + (me.workspace ? ' · ' + me.workspace.owner : '');
    $('s-pending').textContent = me.stats.pending; $('s-sent').textContent = me.stats.sent; $('s-channels').textContent = me.stats.channels;
    $('ai-quota').textContent = quotaText();
    $('ai-row').style.display = me.ai.enabled ? '' : 'none'; $('home-ai').style.display = me.ai.enabled ? '' : 'none'; $('ai-card').style.display = me.ai.enabled ? '' : 'none';
    $('me-name').textContent = '👤 ' + (me.user.name || '');
    $('me-plan').textContent = t('ma_plan_line', {plan: p.name}) + (p.expires ? ' · ' + t('ma_until', {date: p.expires}) : '');
    var inf = function (n) { return n === 0 ? '∞' : n; };
    $('me-limits').textContent = t('ma_limits', {ch: inf(p.channels_max), q: inf(p.queue_max)});
    $('me-lang').value = me.user.lang;
    var tzs = me.timezones.slice(); if (tzs.indexOf(me.user.timezone) < 0) { tzs.unshift(me.user.timezone); }
    $('me-tz').innerHTML = tzs.map(function (z) { return '<option' + (z === me.user.timezone ? ' selected' : '') + '>' + esc(z) + '</option>'; }).join('');
    $('ad').innerHTML = '<option value="0">' + esc(t('ma_ad_none')) + '</option>' + me.auto_delete.map(function (m) { return '<option value="' + m + '">' + esc(t('ma_ad_hours', {h: m / 60})) + '</option>'; }).join('');
    $('when').min = me.now_local; $('when-tz').textContent = '🕒 ' + me.user.timezone;
    if (!me.channels.length) { $('no-ch').style.display = ''; $('editor-wrap').style.display = 'none'; }
    else {
      $('no-ch').style.display = 'none'; $('editor-wrap').style.display = '';
      if (!me.channels.some(function (c) { return c.id === state.channel; })) { state.channel = me.channels[0].id; }
    }
    renderChannels(); renderReactions(); refreshPreview();
  }
  function loadMe() {
    return api('me').then(function (r) {
      if (!r.ok) {
        $('boot').innerHTML = '<div class="empty"><b>🔒</b>' + esc(r.error === 'auth' ? t('ma_err_auth') : errText(r)) + '</div>';
        return false;
      }
      me = r; lang = r.user.lang || lang; applyI18n(); render(); return true;
    });
  }
  function checkDraft() {
    api('draft').then(function (r) {
      if (!r.ok || !r.draft) { return; }
      $('draft-banner').style.display = 'flex';
      $('draft-load').onclick = function () {
        var d = r.draft; resetEditor(); setEditor(d.text); $('draft-banner').style.display = 'none';
        if (d.type !== 'text' && d.file_id) { state.type = d.type; state.fileId = d.file_id; $('media-box').style.display = 'flex'; $('media-add').style.display = 'none';
          $('media-thumb').textContent = '🖼'; $('media-name').textContent = t('ma_media_attached'); }
        if (d.button_text) { $('b-text').value = d.button_text; $('b-url').value = d.button_url || ''; }
        if (d.reactions) { state.reactions = d.reactions; renderReactions(); }
        if (d.delete_after) { $('ad').value = String(d.delete_after); }
        if (d.channel_id && me.channels.some(function (c) { return c.id === d.channel_id; })) { state.channel = d.channel_id; renderChannels(); }
        refreshPreview(); go('post');
      };
    });
  }

  // ---------- ishga tushirish
  if (tg) { tg.ready(); tg.expand(); try { tg.setHeaderColor('secondary_bg_color'); } catch (e) {} }
  var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user; if (u && u.language_code) { lang = ['uz', 'ru'].indexOf(u.language_code.slice(0, 2)) >= 0 ? u.language_code.slice(0, 2) : 'en'; }
  applyI18n();
  if (!initData) { $('boot').innerHTML = '<div class="empty"><b>📱</b>' + esc(t('ma_err_open_in_tg')) + '</div>'; return; }
  loadMe().then(function (ok) {
    if (!ok) { return; }
    $('boot').style.display = 'none';
    var tab = (new URLSearchParams(location.search)).get('tab');
    go(['home', 'post', 'queue', 'me'].indexOf(tab) >= 0 ? tab : 'home');
    checkDraft();
  });
})();
</script>
</body>
</html>
