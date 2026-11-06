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
    . "img-src 'self' blob: data: https://t.me; media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'none'");
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

.ui-hidden{display:none!important}
#boot{display:grid;place-items:center;height:70vh;color:var(--hint)}
</style>
<style id="ui-modern">
/* ---------- zamonaviy qatlam: mavzu, rang, o'lcham, zichlik (html data-* atributlari, «🎨 Ko'rinish» sozlamalari) */
:root{--accent2:#8b5cf6;--soft:rgba(47,124,246,.12);--r:20px;--line:rgba(128,128,128,.14)}
html[data-accent=blue]{--accent:#2f7cf6;--accent2:#22b8f0;--soft:rgba(47,124,246,.13)}
html[data-accent=violet]{--accent:#7c5cff;--accent2:#c06cff;--soft:rgba(124,92,255,.14)}
html[data-accent=green]{--accent:#10b981;--accent2:#22d3a6;--soft:rgba(16,185,129,.14)}
html[data-accent=orange]{--accent:#f97316;--accent2:#fbbf24;--soft:rgba(249,115,22,.14)}
html[data-accent=pink]{--accent:#ec4899;--accent2:#f472b6;--soft:rgba(236,72,153,.14)}
html[data-accent=teal]{--accent:#0ea5a4;--accent2:#38bdf8;--soft:rgba(14,165,164,.14)}
html[data-accent=red]{--accent:#ef4444;--accent2:#fb7185;--soft:rgba(239,68,68,.14)}
html[data-accent]{--accent-text:#fff;--link:var(--accent)}
html[data-theme=light]{--bg:#f2f4fa;--card:#ffffff;--text:#11131a;--hint:#868ca0;--shadow:0 8px 28px rgba(20,30,60,.08)}
html[data-theme=dark]{--bg:#0d1016;--card:#171b25;--text:#eef1f7;--hint:#8a93a8;--shadow:0 10px 30px rgba(0,0,0,.4);--line:rgba(255,255,255,.08)}
html[data-theme=dark] input,html[data-theme=dark] select,html[data-theme=dark] textarea,html[data-theme=dark] .editor{background:#0f131b;color:var(--text)}
html[data-size=s] body{font-size:13.5px}html[data-size=l] body{font-size:17px}html[data-size=l] h1{font-size:20px}
html[data-density=compact] .card{padding:10px 12px;margin-bottom:8px}html[data-density=compact] .stats,html[data-density=compact] .actions{gap:8px;margin-bottom:8px}
html[data-density=compact] .big{padding:11px 12px}
html[data-motion=off] *{animation:none!important;transition:none!important}
body{position:relative;min-height:100vh}
body::before{content:"";position:fixed;inset:-20% -20% auto -20%;height:70vh;z-index:-1;pointer-events:none;opacity:.55;
  background:radial-gradient(40% 50% at 20% 20%,var(--soft),transparent 70%),radial-gradient(35% 45% at 85% 10%,var(--soft),transparent 70%);
  animation:aur 16s ease-in-out infinite alternate}
@keyframes aur{to{transform:translate3d(4%,3%,0) scale(1.06)}}
header{background:transparent;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.logo{background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 6px 18px var(--soft);border-radius:12px}
.card,.stat{border:1px solid var(--line);border-radius:var(--r)}
.card{transition:transform .15s ease}
.card h3{font-size:15px;letter-spacing:.1px}
button,.btn{border-radius:14px;transition:transform .1s ease,filter .15s ease,box-shadow .15s ease}
button:not(.ghost):not(.danger):not(.small){background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 8px 20px var(--soft)}
button:active{transform:scale(.97)}
button.ghost{border:1px solid var(--line);box-shadow:none}
.big{border-radius:18px}.big span{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:var(--soft);font-size:20px}
button.big:not(.ghost) span{background:rgba(255,255,255,.22)}
.stat b{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
input,select,textarea,.editor{border:1px solid var(--line);border-radius:14px;transition:border-color .15s,box-shadow .15s}
input:focus,select:focus,textarea:focus,.editor:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--soft)}
.chip{border:1px solid var(--line);transition:all .15s}.chip.on{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;box-shadow:0 4px 12px var(--soft)}
.tag{background:var(--soft);color:var(--text)}
nav{border:1px solid var(--line);border-radius:22px;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
nav a{position:relative;transition:color .15s}nav a.on::before{content:"";position:absolute;inset:4px 8px;border-radius:14px;background:var(--soft);z-index:-1}
nav a i{transition:transform .2s}nav a.on i{transform:translateY(-1px) scale(1.12)}
html[data-labels=off] nav a span{display:none}html[data-labels=off] nav a{padding:12px 4px}
.hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border:0;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-40px;top:-40px;width:160px;height:160px;border-radius:50%;background:rgba(255,255,255,.14)}
.hero .muted{color:rgba(255,255,255,.85)}.hero h3{font-size:19px;margin-bottom:4px}
.avatar{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-weight:700;background:rgba(255,255,255,.25);color:#fff;font-size:18px;float:right}
.sw{width:30px;height:30px;border-radius:50%;display:inline-block;margin:0 8px 8px 0;cursor:pointer;border:3px solid transparent;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.sw.on{border-color:var(--text)}
.set-row{margin:12px 0 4px;font-size:13px;color:var(--hint);font-weight:600}
.tzr{display:flex;justify-content:space-between;gap:8px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;margin-top:6px;cursor:pointer}
.tzr:active{background:var(--soft)}
.page.on{animation:in .28s cubic-bezier(.2,.8,.2,1)}
/* ---------- guruhlangan ro'yxat (Sozlamalar uslubi) */
.grp-t{margin:18px 6px 8px;font-size:12px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--hint)}
.list{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;margin-bottom:12px;box-shadow:var(--shadow)}
.list .li,.list summary.li{display:flex;align-items:center;gap:12px;width:100%;margin:0;padding:12px 14px;border:0;border-radius:0;
  background:transparent!important;box-shadow:none!important;color:var(--text);font-weight:500;text-align:left;cursor:pointer;list-style:none;font-size:15px}
.list summary.li::-webkit-details-marker{display:none}
.list>*+*{border-top:1px solid var(--line)}
.li i{font-style:normal;width:32px;height:32px;flex:0 0 32px;border-radius:10px;display:grid;place-items:center;background:var(--soft);font-size:17px}
.li span{flex:1;min-width:0}.li em{font-style:normal;color:var(--hint);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:45%}
.li b{color:var(--hint);font-size:20px;font-weight:400;line-height:1;transition:transform .2s}
.li:active{background:var(--soft)!important;transform:none}
details.li-d[open] summary.li b{transform:rotate(90deg)}
.li-body{padding:4px 14px 14px}
.li-sel{width:auto;max-width:48%;padding:7px 10px;border-radius:10px;font-size:14px}
.foot{text-align:center;padding:6px 18px 18px;font-size:12px}
.prof{padding:18px}.pf-top{display:flex;align-items:center;gap:12px}.pf-who{flex:1;min-width:0}.pf-who h3{margin:0;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.avatar.lg{width:56px;height:56px;font-size:24px;float:none;flex:0 0 56px;background-size:cover;background-position:center;border:2px solid rgba(255,255,255,.5)}
.prof .badge{background:rgba(255,255,255,.22);color:#fff;box-shadow:none;position:relative;z-index:1}
.pf-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px;position:relative;z-index:1}
.pf-stats div{background:rgba(255,255,255,.16);border-radius:14px;padding:10px 6px;text-align:center}
.pf-stats b{display:block;font-size:18px}.pf-stats span{font-size:11.5px;opacity:.85}
.pf-plan{margin-top:12px;font-size:13px;opacity:.9;display:flex;flex-wrap:wrap;gap:4px 10px;position:relative;z-index:1}
#bot-card .grp-t{margin-top:6px}
.toolbar{display:grid;grid-template-columns:repeat(8,1fr);gap:6px}
.toolbar button{width:100%!important;padding:8px 0!important;background:var(--bg)!important;color:var(--text)!important;border:1px solid var(--line)!important;box-shadow:none!important;border-radius:10px!important}
.toolbar button:active{background:var(--soft)!important}
.opts .li-body{padding-top:0}.opts .li-body label:first-child{margin-top:0}
.chips.seg{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:4px;border-radius:14px;background:var(--bg);border:1px solid var(--line)}
.chips.seg .chip{text-align:center;border:0;background:transparent}.chips.seg .chip.on{background:linear-gradient(135deg,var(--accent),var(--accent2))}


</style>
<style id="ui-premium">
/* ---------- premium qatlam: yangi tipografika, shisha kartalar, gradient urg'u, ixcham birja, Telegram Premium belgisi */
:root{--r:22px;--glass:rgba(255,255,255,.72);--ring:0 0 0 1px var(--line);--sh1:0 1px 2px rgba(16,24,40,.04),0 8px 24px -8px rgba(16,24,40,.12);
  --sh2:0 18px 40px -14px rgba(47,124,246,.45);--gold1:#f7c948;--gold2:#e08a1e}
html[data-theme=dark]{--glass:rgba(23,27,37,.72);--sh1:0 1px 0 rgba(255,255,255,.04) inset,0 10px 30px -10px rgba(0,0,0,.6)}
@media (prefers-color-scheme:dark){html:not([data-theme=light]){--glass:rgba(23,27,37,.72)}}
html,body{font-family:"SF Pro Text",-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased;letter-spacing:-.1px}
h1,h3,.stat b,.pf-who h3{letter-spacing:-.4px}
main{padding:0 16px;max-width:640px;margin:0 auto}
header{padding:calc(12px + var(--tg-safe-area-inset-top,0px) + var(--tg-content-safe-area-inset-top,0px)) 16px 10px;max-width:640px;margin:0 auto}
header h1{font-size:19px;font-weight:800;background:linear-gradient(90deg,var(--text),var(--accent));-webkit-background-clip:text;background-clip:text;color:transparent}
.logo{width:36px;height:36px;border-radius:12px;box-shadow:0 8px 22px -6px var(--accent)}
.badge{font-weight:800;font-size:11px;letter-spacing:.6px;padding:5px 11px;border:1px solid var(--line)}
html[data-tgp="1"] #plan::before{content:"⭐ ";}
.card,.stat,.list{background:var(--glass);backdrop-filter:blur(18px) saturate(160%);-webkit-backdrop-filter:blur(18px) saturate(160%);box-shadow:var(--sh1)}
.card{padding:16px;margin-bottom:14px}
.card h3{font-size:15.5px;font-weight:750}
.muted{line-height:1.45}
/* hero va profil */
.hero{background:radial-gradient(120% 140% at 0% 0%,var(--accent) 0%,transparent 55%),radial-gradient(120% 140% at 100% 100%,var(--accent2) 0%,transparent 60%),linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:var(--sh2);padding:20px}
.hero::before{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,.18),transparent 40%);pointer-events:none}
.hero::after{right:-50px;top:-60px;width:200px;height:200px;background:radial-gradient(circle,rgba(255,255,255,.22),transparent 70%)}
.hero h3{font-size:21px;font-weight:800}
.avatar{box-shadow:0 6px 16px rgba(0,0,0,.18)}
html[data-tgp="1"] .avatar.lg{border:0;box-shadow:0 0 0 3px var(--gold1),0 0 0 6px rgba(247,201,72,.25),0 8px 20px rgba(0,0,0,.2)}
#me-badge{background:linear-gradient(135deg,var(--gold1),var(--gold2));color:#3b2300;border:0;font-weight:800;box-shadow:0 6px 16px -4px rgba(224,138,30,.6)}
.pf-stats div{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.18);backdrop-filter:blur(6px)}
.pf-stats b{font-size:19px;font-weight:800}
/* statistika plitkalari */
.stats{gap:10px}.stat{padding:14px 8px}.stat b{font-size:24px;font-weight:800}.stat span{font-size:12px}
/* katta amal tugmalari */
.actions{gap:10px}
.big{min-height:64px;padding:14px;font-size:15px;font-weight:700;border-radius:20px;line-height:1.2}
.big b{font-weight:700}
button.big.ghost{background:var(--glass);box-shadow:var(--sh1)}
button.big:not(.ghost){box-shadow:var(--sh2)}
.big span{flex:0 0 40px;width:40px;height:40px;border-radius:13px}
/* tugmalar */
button,.btn{font-weight:700;letter-spacing:-.1px;padding:13px 16px}
button.small{padding:8px 12px;border-radius:12px}
button.ghost{background:var(--glass)}
/* ro'yxat qatorlari */
.list{border-radius:var(--r)}
.list .li,.list summary.li{padding:13px 14px;font-weight:600}
.li i{border-radius:11px;background:linear-gradient(135deg,var(--soft),transparent);box-shadow:inset 0 0 0 1px var(--line)}
.grp-t{font-size:11.5px;letter-spacing:.9px;margin:20px 8px 8px}
/* chiplar */
.chip{font-weight:600;font-size:13.5px;padding:7px 13px;background:var(--glass)}
.chips.scroll{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;margin:0 -16px 12px;padding:2px 16px 4px;-webkit-overflow-scrolling:touch;scroll-snap-type:x proximity;scroll-padding:0 16px}
.chips.scroll::-webkit-scrollbar{display:none}
.chips.scroll .chip{flex:0 0 auto;white-space:nowrap;scroll-snap-align:start}
/* birja: ixcham */
.mk-head{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:6px}
.mk-head button{width:100%;padding:10px 12px;font-size:14px}
.mk-note{font-size:12px;margin:0 4px 10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mk-item{align-items:center;padding:12px 14px;margin-bottom:8px;cursor:pointer}
.mk-av{flex:0 0 42px;width:42px;height:42px;border-radius:14px;display:grid;place-items:center;font-weight:800;color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2))}
.mk-item .tag{margin-top:6px}.chev{color:var(--hint);font-size:22px}
.empty.slim{padding:22px 10px}.empty.slim b{font-size:30px;margin-bottom:4px}
.empty{font-size:14px}
/* navbat kartasi */
.post{gap:12px}.post .body b{font-weight:700}
/* pastki panel */
nav{left:50%;right:auto;transform:translateX(-50%);width:min(560px,calc(100% - 20px));background:var(--glass);padding:4px;border-radius:24px;
  box-shadow:0 12px 40px -10px rgba(16,24,40,.35)}
nav a{padding:7px 2px 6px;border-radius:18px;font-size:10.5px;font-weight:600}
nav a.on{color:#fff}
nav a.on::before{inset:0;border-radius:18px;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 8px 18px -6px var(--accent)}
nav a i{font-size:21px;margin-bottom:1px}
/* modal va maydonlar */
.sheet{border-radius:26px 26px 0 0;background:var(--card)}
.sheet::before{content:"";display:block;width:40px;height:5px;border-radius:3px;background:var(--line);margin:-6px auto 12px}
input,select,textarea{padding:12px 13px}
.toast{border-radius:16px;box-shadow:0 12px 30px rgba(0,0,0,.25);font-weight:600}
.preview{border-radius:20px}

.ai-models{display:flex;flex-direction:column;gap:6px}.aim{display:flex;align-items:center;gap:8px;padding:9px 11px;border-radius:12px;background:var(--soft);font-size:13.5px}
.aim .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(47,179,107,.2)}.aim .muted{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.aim em{font-style:normal;font-size:11px;font-weight:800;padding:2px 7px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.pl-hero h3{margin:0 0 4px}.banner.warn{background:linear-gradient(135deg,#f59e0b,#ef4444)}
#pl-tiers{margin-bottom:12px}
.pl-feat{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px}.pf{display:flex;gap:8px;align-items:center;font-size:13.5px;font-weight:600}
.pf i{font-style:normal;width:28px;height:28px;flex:0 0 28px;border-radius:9px;display:grid;place-items:center;background:var(--soft)}
.pl-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.pp{position:relative;display:flex;flex-direction:column;align-items:flex-start;gap:3px;padding:14px!important;text-align:left;border-radius:18px!important;
  background:var(--glass)!important;color:var(--text)!important;border:2px solid var(--line)!important;box-shadow:var(--sh1)!important}
.pp.on{border-color:var(--accent)!important;box-shadow:0 0 0 4px var(--soft),var(--sh1)!important}
.pp b{font-size:15px}.pp .st{font-size:20px;font-weight:800;background:linear-gradient(135deg,var(--gold2),var(--gold1));-webkit-background-clip:text;background-clip:text;color:transparent}
.pp .muted{font-size:12px}.pp .save{font-size:11.5px;font-weight:800;color:var(--ok)}.pp .ghosty{visibility:hidden}
.pp .hot{position:absolute;top:-9px;right:10px;font-style:normal;font-size:10.5px;font-weight:800;padding:3px 8px;border-radius:10px;color:#3b2300;
  background:linear-gradient(135deg,var(--gold1),var(--gold2))}
.pl-buy{padding:16px!important;font-size:16px;margin-bottom:10px}
.pl-alt{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}.pl-alt button{width:100%}
.pl-cmp table{width:100%;border-collapse:collapse;font-size:13.5px}.pl-cmp th{font-size:12px;color:var(--hint);font-weight:800;padding:4px}
.pl-cmp td{text-align:center;padding:7px 4px;border-top:1px solid var(--line);font-weight:600}.pl-cmp td:first-child{text-align:left}
</style>
</head>
<body>
<header><div class="logo">🤖</div><h1>PostAssist</h1><span class="badge" id="plan">…</span></header>
<main>
  <div id="boot"><div><span class="spin">⏳</span></div></div>

  <section class="page" id="p-home">
    <div class="card hero" id="home-hero"><div class="avatar" id="avatar">🙂</div><h3 id="hello"></h3><div class="muted" id="tzline"></div></div>
    <div class="stats" id="home-stats">
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
    <div class="card" id="ai-card"><h3 data-t="ma_ai_title"></h3><div class="muted" id="ai-quota"></div>
      <div class="set-row" data-t="ma_ai_models"></div><div id="ai-models" class="ai-models"></div></div>
    <div class="card" id="cm-card" style="display:none"><div class="row"><b style="flex:2">💬 <span data-t="ma_cm_title"></span> <span id="cm-count"></span></b>
      <button class="small ghost" id="cm-open" data-t="ma_open"></button></div></div>
    <div class="card" id="st-card" style="display:none"><h3>📊 <span data-t="ma_st_title"></span></h3><div id="st-list"></div></div>
    <div id="bot-card"><div class="grp-t" data-t="ma_in_bot"></div>
      <div class="list">
        <button class="li" data-go="market"><i>💰</i><span data-t="ma_go_market"></span><b>›</b></button>
        <button class="li" data-bot="go_team"><i>👥</i><span data-t="ma_go_team"></span><b>›</b></button>
        <button class="li" data-go="plans"><i>💎</i><span data-t="ma_li_plans"></span><b>›</b></button>
        <button class="li" data-bot="go_channels"><i>📢</i><span data-t="ma_go_channels"></span><b>›</b></button>
      </div></div>
  </section>

  <section class="page" id="p-post">
    <div class="banner" id="draft-banner" style="display:none"><div style="flex:1" data-t="ma_draft_found"></div><button class="small" id="draft-load" data-t="ma_open"></button></div>
    <div class="card" id="no-ch" style="display:none"><div class="empty"><b>📢</b><span data-t="ma_no_channels"></span></div><button id="no-ch-bot" data-t="ma_open_bot"></button></div>
    <div id="editor-wrap">
      <div class="card" id="tpl-card" style="display:none"><div class="row"><select id="tpl-sel"><option value="" data-t="ma_tpl_pick"></option></select></div></div>
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
      <div class="list opts">
        <details class="li-d"><summary class="li"><i>🔗</i><span data-t="ma_button"></span><b>›</b></summary><div class="li-body">
          <label data-t="ma_button_text"></label><input id="b-text" maxlength="64">
          <label data-t="ma_button_url"></label><input id="b-url" placeholder="@kanal, t.me/..., sayt.uz">
        </div></details>
        <details class="li-d" id="rx-box"><summary class="li"><i>👍</i><span data-t="ma_reactions"></span><b>›</b></summary><div class="li-body"><div class="chips" id="rx-list" style="margin-top:8px"></div></div></details>
        <details class="li-d"><summary class="li"><i>🔄</i><span data-t="ma_repeat"></span><b>›</b></summary><div class="li-body">
          <select id="rep"><option value="" data-t="ma_rep_none"></option><option value="daily" data-t="ma_rep_daily"></option>
            <option value="weekly" data-t="ma_rep_weekly"></option><option value="monthly" data-t="ma_rep_monthly"></option><option value="twice" data-t="ma_rep_twice"></option>
            <option value="workdays" data-t="ma_rep_workdays"></option><option value="interval2" data-t="ma_rep_int2"></option><option value="interval3" data-t="ma_rep_int3"></option></select>
          <div id="t2-box" style="display:none"><label data-t="ma_time2"></label><input type="time" id="t2"></div>
        </div></details>
        <details class="li-d"><summary class="li"><i>⏳</i><span data-t="ma_autodel"></span><b>›</b></summary><div class="li-body"><select id="ad"></select></div></details>
        <details class="li-d"><summary class="li"><i>⚙️</i><span data-t="ma_opts"></span><b>›</b></summary><div class="li-body"><div class="chips" id="opt-list" style="margin-top:8px"></div></div></details>
        <details class="li-d"><summary class="li"><i>🔒</i><span data-t="ma_hidden"></span><b>›</b></summary><div class="li-body"><div class="muted" data-t="ma_hidden_hint"></div>
          <textarea id="hid" rows="2" maxlength="180"></textarea></div></details>
        <details class="li-d" id="mc-box"><summary class="li"><i>📢</i><span data-t="ma_more_channels"></span><b>›</b></summary><div class="li-body"><div class="chips" id="mc-list" style="margin-top:8px"></div></div></details>
      </div>
      <div class="card"><h3 data-t="ma_preview"></h3><div class="preview"><div class="bubble" id="pv"></div><div id="pv-btn"></div><div id="pv-hid"></div><div id="pv-rx"></div></div></div>
      <div class="card">
        <div class="chips seg"><span class="chip on" data-when="now" data-t="ma_now"></span><span class="chip" data-when="later" data-t="ma_later"></span></div>
        <div id="when-box" style="display:none"><label data-t="ma_when"></label><input type="datetime-local" id="when"><div class="muted" id="when-tz"></div></div>
        <div style="margin-top:12px"><button id="submit" data-t="ma_send_now"></button></div>
        <div style="margin-top:8px"><button class="ghost" id="tpl-save">💾 <span data-t="ma_tpl_save"></span></button></div>
      </div>
    </div>
  </section>

  <section class="page" id="p-queue"><div id="q-list"></div></section>

  <section class="page" id="p-market">
    <div class="mk-head"><button class="small ghost" id="mk-threads">💬 <span data-t="ma_mk_threads"></span></button>
      <button class="small" data-bot="go_market">➕ <span data-t="ma_mk_publish"></span></button></div>
    <div class="muted mk-note" id="mk-note" data-t="ma_mk_note"></div>
    <div class="chips scroll" id="mk-cats"></div>
    <div id="mk-mine"></div>
    <div id="mk-list"></div>
    <div class="row" id="mk-pager" style="margin-bottom:12px"></div>
  </section>

  <section class="page" id="p-me">
    <div class="card hero prof">
      <div class="pf-top"><div class="avatar lg" id="me-av">🙂</div>
        <div class="pf-who"><h3 id="me-name"></h3><div class="muted" id="me-sub"></div></div><span class="badge" id="me-badge"></span></div>
      <div class="pf-stats">
        <div><b id="me-st-ch">0</b><span data-t="ma_stat_channels"></span></div>
        <div><b id="me-st-q">0</b><span data-t="ma_stat_pending"></span></div>
        <div><b id="me-st-ai">—</b><span data-t="ma_me_ai_left"></span></div>
      </div>
      <div class="pf-plan"><span id="me-plan"></span><span id="me-limits" hidden></span></div>
    </div>

    <div class="grp-t" data-t="ma_grp_account"></div>
    <div class="list">
      <button class="li" id="me-plans"><i>💎</i><span data-t="ma_li_plans"></span><em id="me-plan-tag"></em><b>›</b></button>
      <button class="li" data-bot="go_team"><i>👥</i><span data-t="ma_go_team"></span><b>›</b></button>
      <button class="li" data-bot="go_channels"><i>📢</i><span data-t="ma_go_channels"></span><b>›</b></button>
      <button class="li" data-go="market"><i>💰</i><span data-t="ma_go_market"></span><b>›</b></button>
    </div>

    <div class="grp-t" data-t="ma_grp_settings"></div>
    <div class="list">
      <label class="li"><i>🌐</i><span data-t="ma_lang"></span>
        <select id="me-lang" class="li-sel"><option value="uz">🇺🇿 O'zbekcha</option><option value="ru">🇷🇺 Русский</option><option value="en">🇬🇧 English</option></select></label>
      <details class="li-d"><summary class="li"><i>🕒</i><span data-t="ma_tz"></span><em id="tz-short"></em><b>›</b></summary>
        <div class="li-body"><div class="tzr" id="tz-cur"></div><input id="tz-q" data-ph="ma_tz_search" style="margin-top:8px"><div id="tz-res"></div></div></details>
      <details class="li-d" id="ui-card"><summary class="li"><i>🎨</i><span data-t="ma_ui_title"></span><em data-t="ma_ui_hint"></em><b>›</b></summary>
        <div class="li-body">
      <div class="set-row" data-t="ma_ui_theme"></div><div class="chips" id="ui-theme"></div>
      <div class="set-row" data-t="ma_ui_accent"></div><div id="ui-accent"></div>
      <div class="set-row" data-t="ma_ui_size"></div><div class="chips" id="ui-size"></div>
      <div class="set-row" data-t="ma_ui_density"></div><div class="chips" id="ui-density"></div>
      <div class="set-row" data-t="ma_ui_motion"></div><div class="chips" id="ui-motion"></div>
      <div class="set-row" data-t="ma_ui_labels"></div><div class="chips" id="ui-labels"></div>
      <div class="set-row" data-t="ma_ui_home"></div><div class="chips" id="ui-home"></div>
      <div class="set-row" data-t="ma_ui_start"></div><div class="chips" id="ui-start"></div>
      <div style="margin-top:14px"><button class="ghost small" id="ui-reset">↺ <span data-t="ma_ui_reset"></span></button></div></div></details>
    </div>

    <div class="grp-t" data-t="ma_grp_app"></div>
    <div class="list">
      <button class="li" id="me-admin" data-go="admin" style="display:none"><i>👑</i><span data-t="ma_admin_title"></span><b>›</b></button>
      <button class="li" id="me-bot"><i>🤖</i><span data-t="ma_open_bot"></span><b>›</b></button>
    </div>
    <div class="muted foot" data-t="ma_about"></div>
  </section>

  <section class="page" id="p-plans">
    <div class="card hero pl-hero"><h3 data-t="ma_pl_title"></h3><div class="muted" id="pl-cur"></div></div>
    <div class="banner warn" id="pl-block" style="display:none"></div>
    <div class="chips seg" id="pl-tiers"><span class="chip on" data-tier="pro">💎 PRO</span><span class="chip" data-tier="ultra">🚀 ULTRA</span></div>
    <div class="card pl-feat" id="pl-feat"></div>
    <div class="pl-grid" id="pl-periods"></div>
    <button id="pl-buy" class="pl-buy"></button>
    <div class="pl-alt">
      <button class="ghost small" id="pl-uzs" data-bot="go_plans">🇺🇿 <span data-t="ma_pl_uzs"></span></button>
      <button class="ghost small" data-bot="go_plans">🎁 <span data-t="ma_pl_promo"></span></button>
    </div>
    <div class="card pl-cmp" id="pl-cmp"></div>
    <div class="muted foot" data-t="ma_pl_note"></div>
  </section>

  <section class="page" id="p-admin">
    <div class="card"><h3>👑 <span data-t="ma_admin_title"></span></h3><div id="ad-stats"><span class="spin">⏳</span></div><div id="ad-chart"></div></div>
    <div class="card"><h3>🧾 <span data-t="ma_ad_receipts"></span></h3><div id="ad-receipts"></div><div class="muted" data-t="ma_ad_receipt_hint"></div></div>
    <div class="card"><h3>🎁 <span data-t="ma_ad_grant"></span></h3>
      <div class="row"><input id="ag-id" inputmode="numeric" placeholder="ID"><select id="ag-tier"><option value="pro">PRO</option><option value="ultra">ULTRA</option></select>
      <input id="ag-days" inputmode="numeric" value="30"></div><div style="height:8px"></div><button id="ag-go" data-t="ma_ad_grant_btn"></button></div>
    <div class="card"><h3>🔍 <span data-t="ma_ad_user"></span></h3><div class="row"><input id="au-id" inputmode="numeric" placeholder="ID"><button class="small" id="au-go">🔍</button></div>
      <div id="au-out" style="margin-top:8px"></div></div>
    <div class="card"><h3>🏷 <span data-t="ma_ad_promos"></span></h3>
      <div class="row"><input id="ap-code" placeholder="KOD" maxlength="32"><select id="ap-tier"><option value="pro">PRO</option><option value="ultra">ULTRA</option></select></div>
      <div class="row" style="margin-top:6px"><input id="ap-days" inputmode="numeric" placeholder="30"><input id="ap-max" inputmode="numeric" placeholder="∞"></div>
      <div style="height:8px"></div><button class="ghost" id="ap-go" data-t="ma_ad_promo_create"></button><div id="ad-promos" style="margin-top:10px"></div></div>
    <div class="card muted" data-t="ma_ad_bot_only"></div>
  </section>
</main>

<nav>
  <a href="#" data-go="home" class="on"><i>🏠</i><span data-t="ma_tab_home"></span></a>
  <a href="#" data-go="post"><i>✍️</i><span data-t="ma_tab_post"></span></a>
  <a href="#" data-go="queue"><i>📅</i><span data-t="ma_tab_queue"></span></a>
  <a href="#" data-go="market"><i>💰</i><span data-t="ma_tab_market"></span></a>
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
  var lang = 'uz', me = null, state = {opts: [], extra: [], channel: 0, type: 'text', fileId: '', mediaUrl: '', when: 'now', reactions: '', ai: null};
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
    document.querySelectorAll('input[data-ph]').forEach(function (el) { el.placeholder = t(el.getAttribute('data-ph')); });
    if (typeof renderUi === 'function') { renderUi(); }
  }

  // ---------- navigatsiya (Telegram «Orqaga» tugmasi bilan)
  var cur = 'home';
  function go(page) {
    cur = page;
    document.querySelectorAll('.page').forEach(function (p) { p.classList.toggle('on', p.id === 'p-' + page); });
    document.querySelectorAll('nav a').forEach(function (a) { a.classList.toggle('on', a.getAttribute('data-go') === page); });
    if (tg && tg.BackButton) { page === 'home' ? tg.BackButton.hide() : tg.BackButton.show(); }
    if (page === 'queue') { loadQueue(); }
    if (page === 'home') { loadStats(); loadComments(); }
    if (page === 'post') { loadTemplates(); }
    if (page === 'market') { loadMarket(); }
    if (page === 'admin') { loadAdmin(); }
    if (page === 'plans') { loadPlans(); }
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
  $('me-plans').onclick = function () { haptic(); go('plans'); }; $('me-bot').onclick = function () { openBot(); };
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-bot]');
    if (b) { e.preventDefault(); haptic(); openBot(b.getAttribute('data-bot')); }
  });



  // ---------- 💎 tariflar va Stars to'lovi (Mini App ichida: createInvoiceLink -> tg.openInvoice)
  var pl = {data: null, tier: 'pro', key: null};
  function loadPlans() {
    $('pl-periods').innerHTML = '<div class="empty slim"><span class="spin">⏳</span></div>';
    api('plans').then(function (r) {
      if (!r.ok) { $('pl-periods').innerHTML = '<div class="empty slim">' + esc(errText(r)) + '</div>'; return; }
      pl.data = r;
      if (r.current === 'ultra') { pl.tier = 'ultra'; }
      renderPlans();
    });
  }
  function tierOf(k) { return pl.data.tiers.filter(function (x) { return x.tier === k; })[0]; }
  function renderPlans() {
    var r = pl.data, tr = tierOf(pl.tier), p = me ? me.plan : null;
    $('pl-cur').textContent = t('ma_pl_current', {plan: p ? p.name : r.current}) + (p && p.expires ? ' · ' + t('ma_until', {date: p.expires}) : '');
    $('pl-block').style.display = r.blocked ? '' : 'none';
    $('pl-block').textContent = r.blocked ? t(r.blocked === 'helper' ? 'ma_pl_helper' : 'ma_pl_enterprise') : '';
    $('pl-uzs').style.display = r.uzs ? '' : 'none';
    document.querySelectorAll('[data-tier]').forEach(function (c) { c.classList.toggle('on', c.getAttribute('data-tier') === pl.tier); });
    var f = [['📢', t('ma_pl_f_channels', {n: tr.channels})], ['📅', t('ma_pl_f_queue', {n: tr.queue})], ['✨', t('ma_pl_f_ai', {n: tr.ai})],
      ['✅', t('ma_pl_f_nobadge')]];
    if (tr.team) { f.push(['👥', t('ma_pl_f_team', {n: tr.team})]); }
    f.push(['🔄', t('ma_pl_f_more')]);
    $('pl-feat').innerHTML = f.map(function (x) { return '<div class="pf"><i>' + x[0] + '</i><span>' + esc(x[1]) + '</span></div>'; }).join('');
    if (!tr.periods.some(function (x) { return x.key === pl.key; })) { pl.key = tr.periods[tr.periods.length - 1].key; }
    var best = tr.periods[tr.periods.length - 1].key;
    $('pl-periods').innerHTML = tr.periods.map(function (x) {
      return '<button class="pp' + (x.key === pl.key ? ' on' : '') + '" data-pk="' + esc(x.key) + '">' + (x.key === best ? '<em class="hot">' + esc(t('ma_pl_best')) + '</em>' : '') +
        '<b>' + esc(x.label) + '</b><span class="st">⭐ ' + num(x.stars) + '</span><span class="muted">' + esc(t('ma_pl_per_month', {n: num(x.per_month)})) + '</span>' +
        (x.save > 0 ? '<span class="save">−' + x.save + '%</span>' : '<span class="save ghosty">&nbsp;</span>') + '</button>';
    }).join('');
    document.querySelectorAll('[data-pk]').forEach(function (b) { b.onclick = function () { haptic(); pl.key = b.getAttribute('data-pk'); renderPlans(); }; });
    var sel = tr.periods.filter(function (x) { return x.key === pl.key; })[0];
    var verb = r.current === pl.tier ? 'ma_pl_extend' : 'ma_pl_buy';
    $('pl-buy').textContent = t(verb, {plan: tr.name, stars: num(sel.stars)});
    $('pl-buy').disabled = !!r.blocked;
    $('pl-cmp').innerHTML = '<h3>' + esc(t('ma_pl_compare')) + '</h3><table><tr><th></th>' + r.tiers.map(function (x) { return '<th>' + esc(x.name) + '</th>'; }).join('') + '</tr>' +
      [['📢', 'channels'], ['📅', 'queue'], ['✨', 'ai']].map(function (row) {
        return '<tr><td>' + row[0] + '</td>' + r.tiers.map(function (x) { return '<td>' + num(x[row[1]]) + '</td>'; }).join('') + '</tr>';
      }).join('') + '<tr><td>🤖</td>' + r.tiers.map(function (x) { return '<td>' + (x.badge ? '✓' : '—') + '</td>'; }).join('') + '</tr>' +
      '<tr><td>👥</td>' + r.tiers.map(function (x) { return '<td>' + (x.team ? '+' + x.team : '—') + '</td>'; }).join('') + '</tr></table>' +
      '<div class="muted" style="margin-top:6px">📢 ' + esc(t('ma_stat_channels')) + ' · 📅 ' + esc(t('ma_stat_pending')) + ' · ✨ ' + esc(t('ma_pl_ai_day')) + ' · 🤖 ' + esc(t('ma_pl_badge')) + '</div>';
  }
  document.querySelectorAll('[data-tier]').forEach(function (c) { c.onclick = function () { haptic(); pl.tier = c.getAttribute('data-tier'); pl.key = null; renderPlans(); }; });
  $('pl-buy').onclick = function () {
    if (!pl.key || (pl.data && pl.data.blocked)) { return; }
    var btn = this; btn.disabled = true;
    api('invoice', {key: pl.key}).then(function (r) {
      btn.disabled = false;
      if (!r.ok) { toast(r.error === 'enterprise' ? t('ma_pl_enterprise') : errText(r)); return; }
      var done = function (status) {
        if (status === 'paid') { haptic('ok'); toast(t('ma_pl_paid')); setTimeout(function () { loadMe().then(function () { loadPlans(); }); }, 1500); }
        else if (status === 'failed') { toast(t('ma_pl_failed')); }
      };
      if (tg && tg.openInvoice) { tg.openInvoice(r.url, done); } else { location.href = r.url; }
    });
  };

  // ---------- 💰 birja: katalog, e'lon, suhbat (e'lon qo'yish va boshqarish — botda)
  var mk = {cat: null, page: 0};
  var num = function (n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); };
  function mkErr(r) { return r.message || errText(r); }
  function loadMarket() {
    $('mk-list').innerHTML = '<div class="empty"><span class="spin">⏳</span></div>';
    api('market', {cat: mk.cat, page: mk.page}).then(function (r) {
      if (!r.ok) { $('mk-list').innerHTML = '<div class="empty">' + esc(mkErr(r)) + '</div>'; return; }
      $('mk-cats').innerHTML = '<span class="chip' + (mk.cat ? '' : ' on') + '" data-cat="">' + esc(t('ma_mk_all')) + '</span>' +
        r.categories.map(function (c) { return '<span class="chip' + (mk.cat === c.key ? ' on' : '') + '" data-cat="' + esc(c.key) + '">' + esc(c.name) + '</span>'; }).join('');
      document.querySelectorAll('[data-cat]').forEach(function (el) { el.onclick = function () { haptic(); mk.cat = el.getAttribute('data-cat') || null; mk.page = 0; loadMarket(); }; });
      $('mk-mine').innerHTML = r.mine.length ? '<div class="card"><h3>📢 ' + esc(t('ma_mk_mine')) + '</h3>' + r.mine.map(function (l) {
        return '<div class="muted">@' + esc(l.username) + ' · ' + esc(l.price) + ' · ' + esc(l.status) + '</div>';
      }).join('') + '<div style="margin-top:8px"><button class="small ghost" data-bot="go_market">⚙️ ' + esc(t('ma_mk_manage')) + '</button></div></div>' : '';
      if (r.banned) { $('mk-list').innerHTML = '<div class="card empty"><b>🚫</b>' + esc(t('ma_mk_banned')) + '</div>'; $('mk-pager').innerHTML = ''; return; }
      if (!r.items.length) { $('mk-list').innerHTML = '<div class="empty slim"><b>📭</b>' + esc(t('ma_mk_empty')) + '</div>'; }
      else {
        $('mk-list').innerHTML = r.items.map(function (l, i) {
          return '<div class="card post mk-item" data-l="' + i + '"><div class="mk-av">' + esc(((l.title || l.username || '?').trim().charAt(0) || '?').toUpperCase()) + '</div><div class="body"><b class="t">' + esc(l.title || '@' + l.username) + '</b>' +
            '<div class="muted">@' + esc(l.username) + ' · 👥 ' + esc(num(l.subscribers)) + '</div><span class="tag">' + esc(l.category_name) + '</span>' +
            '<span class="tag">💵 ' + esc(l.price) + '</span></div><div class="chev">›</div></div>';
        }).join('');
        document.querySelectorAll('[data-l]').forEach(function (el) { el.onclick = function () { haptic(); mkView(r.items[parseInt(el.getAttribute('data-l'), 10)].id); }; });
      }
      var pg = '';
      if (r.page > 0) { pg += '<button class="ghost" id="mk-prev">◀️</button>'; }
      if (r.page + 1 < r.pages) { pg += '<button class="ghost" id="mk-next">▶️</button>'; }
      $('mk-pager').innerHTML = pg;
      if ($('mk-prev')) { $('mk-prev').onclick = function () { mk.page--; loadMarket(); }; }
      if ($('mk-next')) { $('mk-next').onclick = function () { mk.page++; loadMarket(); }; }
    });
  }
  function openChannel(u) {
    var url = 'https://t.me/' + encodeURIComponent(u);
    if (tg && tg.openTelegramLink) { tg.openTelegramLink(url); } else { window.open(url, '_blank'); }
  }
  function mkView(id) {
    api('market_view', {id: id}).then(function (r) {
      if (!r.ok) { toast(mkErr(r)); return; }
      var l = r.listing;
      var html = '<h3>' + esc(l.title || '@' + l.username) + '</h3><div class="muted">@' + esc(l.username) + ' · 👥 ' + esc(num(l.subscribers)) + ' · ' + esc(l.category_name) + '</div>' +
        '<p><b>💵 ' + esc(l.price) + '</b></p>' + (l.description ? '<p style="white-space:pre-wrap">' + esc(l.description) + '</p>' : '') +
        '<button class="ghost" id="mk-open">📢 ' + esc(t('ma_mk_open_channel')) + '</button>';
      if (!l.mine) {
        html += r.thread ? '<div style="height:8px"></div><button id="mk-chat">💬 ' + esc(t('ma_mk_chat')) + '</button>'
          : '<label>' + esc(t('ma_mk_write')) + '</label><textarea id="mk-text" rows="4" maxlength="1000" placeholder="' + esc(t('ma_mk_write_ph')) + '"></textarea>' +
            '<div class="muted">' + esc(t('ma_mk_safety')) + '</div><div style="height:8px"></div><button id="mk-send">' + esc(t('ma_mk_send')) + '</button>';
      }
      html += '<div style="height:8px"></div><button class="ghost" id="mk-close">' + esc(t('ma_back')) + '</button>';
      modal(html);
      $('mk-open').onclick = function () { openChannel(l.username); };
      $('mk-close').onclick = closeModal;
      if ($('mk-chat')) { $('mk-chat').onclick = function () { mkThread(r.thread); }; }
      if ($('mk-send')) {
        $('mk-send').onclick = function () {
          var b = $('mk-send'); b.disabled = true;
          api('market_send', {listing: l.id, text: $('mk-text').value}).then(function (x) {
            b.disabled = false;
            if (!x.ok) { toast(mkErr(x)); return; }
            haptic('ok'); toast(t('ma_mk_sent')); mkThread(x.thread);
          });
        };
      }
    });
  }
  function mkThreads() {
    api('market_threads').then(function (r) {
      if (!r.ok) { toast(mkErr(r)); return; }
      modal('<h3>💬 ' + esc(t('ma_mk_threads')) + '</h3>' + (r.threads.length ? r.threads.map(function (x, i) {
        return '<div class="card post" data-th="' + x.id + '"><div class="body"><b>' + esc(x.title || '@' + x.username) + '</b><div class="muted">' +
          esc(t(x.role === 'owner' ? 'ma_mk_buyer' : 'ma_mk_owner')) + ' · ' + esc(x.last) + (x.blocked ? ' · 🚫' : '') + '</div></div><div>›</div></div>';
      }).join('') : '<div class="empty">' + esc(t('ma_mk_no_threads')) + '</div>') + '<button class="ghost" id="mk-close">' + esc(t('ma_back')) + '</button>');
      $('mk-close').onclick = closeModal;
      document.querySelectorAll('[data-th]').forEach(function (el) { el.onclick = function () { mkThread(parseInt(el.getAttribute('data-th'), 10)); }; });
    });
  }
  function mkThread(id) {
    api('market_thread', {id: id}).then(function (r) {
      if (!r.ok) { toast(mkErr(r)); return; }
      var th = r.thread;
      var html = '<h3>💬 ' + esc(th.title || '@' + th.username) + '</h3><div class="preview" style="max-height:45vh;overflow:auto" id="mk-msgs">' +
        r.messages.map(function (m) {
          return '<div style="display:flex;justify-content:' + (m.me ? 'flex-end' : 'flex-start') + ';margin:6px 0"><div class="bubble">' + esc(m.text) +
            '<div class="muted" style="font-size:11px;text-align:right">' + esc(m.at) + '</div></div></div>';
        }).join('') + '</div>';
      if (th.blocked) { html += '<div class="empty">🚫 ' + esc(t('ma_mk_blocked')) + '</div>'; }
      else {
        html += '<label>' + esc(t('ma_mk_reply')) + '</label><textarea id="mk-text" rows="3" maxlength="1000"></textarea>' +
          '<div class="muted">' + esc(t('ma_mk_safety')) + '</div><div style="height:8px"></div><button id="mk-send">' + esc(t('ma_mk_send')) + '</button>';
      }
      html += '<div style="height:8px"></div><button class="ghost" data-bot="go_market">🤖 ' + esc(t('ma_mk_in_bot')) + '</button>' +
        '<div style="height:8px"></div><button class="ghost" id="mk-close">' + esc(t('ma_back')) + '</button>';
      modal(html);
      var box = $('mk-msgs'); box.scrollTop = box.scrollHeight;
      $('mk-close').onclick = closeModal;
      if ($('mk-send')) {
        $('mk-send').onclick = function () {
          var b = $('mk-send'); b.disabled = true;
          api('market_send', {thread: id, text: $('mk-text').value}).then(function (x) {
            b.disabled = false;
            if (!x.ok) { toast(mkErr(x)); return; }
            haptic('ok'); mkThread(id);
          });
        };
      }
    });
  }
  $('mk-threads').onclick = function () { haptic(); mkThreads(); };

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
    $('pv-hid').innerHTML = $('hid').value.trim() ? '<div class="pbtn">' + esc(t('ma_hidden_btn')) + '</div>' : '';
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
    renderExtra();
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


  // ---------- sozlamalar, yashirin matn, yana kanallar
  var OPTS = ['silent', 'nopreview', 'pin', 'protect', 'comments'];
  function renderOpts() {
    $('opt-list').innerHTML = OPTS.map(function (o) {
      return '<span class="chip' + (state.opts.indexOf(o) >= 0 ? ' on' : '') + '" data-opt="' + o + '">' + esc(t('ma_opt_' + o)) + '</span>';
    }).join('');
    document.querySelectorAll('[data-opt]').forEach(function (el) {
      el.onclick = function () {
        var o = el.getAttribute('data-opt'), i = state.opts.indexOf(o);
        if (i >= 0) { state.opts.splice(i, 1); } else { state.opts.push(o); }
        haptic(); renderOpts();
      };
    });
  }
  function renderExtra() {
    if (!me) { return; }
    var others = me.channels.filter(function (c) { return c.id !== state.channel; });
    $('mc-box').style.display = others.length ? '' : 'none';
    $('mc-list').innerHTML = others.map(function (c) {
      return '<span class="chip' + (state.extra.indexOf(c.id) >= 0 ? ' on' : '') + '" data-mc="' + c.id + '">' + esc(c.title) + '</span>';
    }).join('');
    document.querySelectorAll('[data-mc]').forEach(function (el) {
      el.onclick = function () {
        var id = parseInt(el.getAttribute('data-mc'), 10), i = state.extra.indexOf(id);
        if (i >= 0) { state.extra.splice(i, 1); } else { state.extra.push(id); }
        haptic(); renderExtra();
      };
    });
  }
  $('hid').addEventListener('input', function () { refreshPreview(); });

  // ---------- 📊 statistika (bosh sahifa)
  function signed(n) { return n === null || n === undefined ? '—' : (n > 0 ? '+' : '') + num(n); }
  function loadStats() {
    api('stats').then(function (r) {
      if (!r.ok || !r.channels.length) { $('st-card').style.display = 'none'; return; }
      $('st-card').style.display = '';
      $('st-list').innerHTML = r.channels.map(function (c) {
        var vals = c.series.map(function (x) { return x.n; }), min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
        var bars = vals.length > 1 ? '<div style="display:flex;align-items:flex-end;gap:3px;height:36px;margin:8px 0">' + vals.map(function (v) {
          var h = max === min ? 50 : Math.round(15 + (v - min) / (max - min) * 85);
          return '<div style="flex:1;height:' + h + '%;background:var(--accent);border-radius:3px;opacity:.85"></div>';
        }).join('') + '</div>' : '<div class="muted" style="margin:6px 0">' + esc(t('ma_st_soon')) + '</div>';
        return '<div style="margin-bottom:12px"><b>📢 ' + esc(c.title) + '</b><div class="muted">👥 ' + (c.subscribers === null ? '…' : num(c.subscribers)) +
          ' · 7d ' + signed(c.d7) + ' · 30d ' + signed(c.d30) + '</div>' + bars +
          '<span class="tag">📝 ' + esc(t('ma_st_posts', {n: c.posts30})) + '</span><span class="tag">👍 ' + esc(c.votes30) + '</span>' +
          (c.opens30 || c.locked30 ? '<span class="tag">🔒 ' + esc(c.opens30) + ' / ' + esc(c.locked30) + '</span>' : '') + '</div>';
      }).join('');
    });
  }

  // ---------- 📝 shablonlar (muharrir)
  function loadTemplates() {
    api('templates').then(function (r) {
      if (!r.ok) { return; }
      var sel = $('tpl-sel');
      sel.innerHTML = '<option value="">' + esc(t('ma_tpl_pick')) + '</option>' + r.templates.map(function (x) {
        return '<option value="' + x.id + '">' + esc(x.name) + '</option>';
      }).join('');
      $('tpl-card').style.display = r.templates.length ? '' : 'none';
    });
  }
  $('tpl-sel').onchange = function () {
    var id = parseInt(this.value, 10); if (!id) { return; }
    api('template', {id: id}).then(function (r) {
      $('tpl-sel').value = '';
      if (!r.ok) { toast(errText(r)); return; }
      var d = r.template;
      setEditor(d.text); $('b-text').value = d.button_text; $('b-url').value = d.button_url;
      state.reactions = d.reactions; renderReactions(); $('ad').value = String(d.delete_after || 0);
      state.opts = d.options.slice(); renderOpts(); $('hid').value = d.hidden;
      state.type = d.type; state.fileId = d.file_id; state.mediaUrl = '';
      if (d.type !== 'text') { $('media-box').style.display = 'flex'; $('media-add').style.display = 'none'; $('media-thumb').textContent = '🖼'; $('media-name').textContent = t('ma_media_attached'); }
      refreshPreview(); haptic('ok'); toast(t('ma_tpl_loaded'));
    });
  };
  $('tpl-save').onclick = function () {
    var ask = function (name) {
      if (!name) { return; }
      var body = {name: name, type: state.type, file_id: state.fileId, text: editorHtml(), button_text: $('b-text').value.trim(), button_url: $('b-url').value.trim(),
        reactions: state.reactions, delete_after: parseInt($('ad').value || '0', 10), options: state.opts, hidden: $('hid').value.trim()};
      api('template_save', body).then(function (r) {
        if (!r.ok) { toast(r.error === 'tpl_limit' ? t('ma_tpl_limit', {max: r.max}) : errText(r)); return; }
        haptic('ok'); toast(t('ma_tpl_saved')); loadTemplates();
      });
    };
    modal('<h3>💾 ' + esc(t('ma_tpl_save')) + '</h3><label>' + esc(t('ma_tpl_name')) + '</label><input id="tpl-name" maxlength="40">' +
      '<div class="row" style="margin-top:14px"><button class="ghost" id="tn-cancel">' + esc(t('ma_back')) + '</button><button id="tn-ok">' + esc(t('ma_save')) + '</button></div>');
    $('tn-cancel').onclick = closeModal;
    $('tn-ok').onclick = function () { var n = $('tpl-name').value.trim(); if (!n) { return; } closeModal(); ask(n.slice(0, 40)); };
  };

  // ---------- 💬 izohlar (egasi): ro'yxat, javob, o'chirish, bloklash
  var cmList = [];
  function loadComments() {
    api('comments').then(function (r) {
      if (!r.ok) { return; }
      cmList = r.comments;
      $('cm-card').style.display = cmList.length ? '' : 'none';
      $('cm-count').textContent = cmList.length ? '(' + cmList.length + ')' : '';
    });
  }
  function showComments() {
    var html = '<h3>💬 ' + esc(t('ma_cm_title')) + '</h3>' + (cmList.length ? cmList.map(function (c) {
      return '<div class="card"><div class="muted">📝 ' + esc(c.post) + ' · ' + esc(c.at) + '</div><b>' + (c.mine ? '⭐ ' : '') + esc(c.name) + '</b>: ' + esc(c.text) +
        '<div class="row" style="margin-top:8px"><button class="small ghost" data-cr="' + c.post_id + '">↩️ ' + esc(t('ma_cm_reply')) + '</button>' +
        (c.mine ? '' : '<button class="small ghost" data-cx="' + c.id + '">🗑</button><button class="small danger" data-cb="' + c.id + '">🚫</button>') + '</div></div>';
    }).join('') : '<div class="empty">' + esc(t('ma_cm_empty')) + '</div>') + '<button class="ghost" id="cm-close">' + esc(t('ma_back')) + '</button>';
    modal(html);
    $('cm-close').onclick = closeModal;
    var mod = function (id, act) {
      var go2 = function (yes) {
        if (!yes) { return; }
        api('comment_mod', {id: id, act: act}).then(function (r) { if (!r.ok) { toast(errText(r)); return; } haptic('ok'); loadCommentsThen(); });
      };
      if (act === 'ban' && tg && tg.showConfirm) { tg.showConfirm(t('ma_cm_ban_confirm'), go2); } else { go2(true); }
    };
    document.querySelectorAll('[data-cx]').forEach(function (b) { b.onclick = function () { mod(parseInt(b.getAttribute('data-cx'), 10), 'del'); }; });
    document.querySelectorAll('[data-cb]').forEach(function (b) { b.onclick = function () { mod(parseInt(b.getAttribute('data-cb'), 10), 'ban'); }; });
    document.querySelectorAll('[data-cr]').forEach(function (b) { b.onclick = function () { replyComment(parseInt(b.getAttribute('data-cr'), 10)); }; });
  }
  function loadCommentsThen() { api('comments').then(function (r) { if (r.ok) { cmList = r.comments; $('cm-count').textContent = '(' + cmList.length + ')'; showComments(); } }); }
  function replyComment(pid) {
    modal('<h3>↩️ ' + esc(t('ma_cm_reply')) + '</h3><textarea id="cm-text" rows="3" maxlength="500"></textarea>' +
      '<div class="row" style="margin-top:12px"><button class="ghost" id="cr-back">' + esc(t('ma_back')) + '</button><button id="cr-send">' + esc(t('ma_mk_send')) + '</button></div>');
    $('cr-back').onclick = showComments;
    $('cr-send').onclick = function () {
      api('comment_reply', {post_id: pid, text: $('cm-text').value}).then(function (r) { if (!r.ok) { toast(errText(r)); return; } haptic('ok'); toast(t('ma_saved')); loadCommentsThen(); });
    };
  }
  $('cm-open').onclick = function () { haptic(); showComments(); };

  // ---------- 👑 super admin (faqat adminlar; server ham tekshiradi)
  function loadAdmin() {
    if (!me || !me.user.is_admin) { go('me'); return; }
    api('admin_stats').then(function (r) {
      if (!r.ok) { $('ad-stats').textContent = errText(r); return; }
      var cell = function (v, k) { return '<div class="stat"><b>' + esc(v) + '</b><span class="muted">' + esc(t(k)) + '</span></div>'; };
      $('ad-stats').innerHTML = '<div class="stats">' + cell(num(r.users), 'ma_ad_users') + cell('+' + r.users_today, 'ma_ad_today') + cell(r.channels, 'ma_ad_channels') + '</div>' +
        '<div class="stats">' + cell(r.pro + ' / ' + r.ultra, 'ma_ad_paid') + cell(r.sent_today, 'ma_ad_sent') + cell(r.pending, 'ma_ad_pending') + '</div>' +
        '<div class="muted">⭐ ' + esc(r.stars_today) + ' (' + esc(r.pays_today) + ') · 💳 ' + esc(r.card_today) + ' (' + esc(r.card_count) + ') · ❌ ' + esc(r.failed_today) + '</div>';
      var max = Math.max.apply(null, r.new_users.map(function (d) { return d.n; }).concat([1]));
      $('ad-chart').innerHTML = '<div class="muted" style="margin-top:10px">' + esc(t('ma_ad_new7')) + '</div><div style="display:flex;align-items:flex-end;gap:6px;height:60px;margin-top:6px">' +
        r.new_users.map(function (d) { return '<div style="flex:1;text-align:center"><div style="height:' + Math.max(4, Math.round(d.n / max * 44)) + 'px;background:var(--accent);border-radius:4px"></div><div class="muted" style="font-size:10px">' + esc(d.day) + '</div></div>'; }).join('') + '</div>';
    });
    loadReceipts(); loadPromos();
  }
  function loadReceipts() {
    api('admin_receipts').then(function (r) {
      if (!r.ok) { return; }
      $('ad-receipts').innerHTML = r.receipts.length ? r.receipts.map(function (x) {
        return '<div class="card"><b>#' + x.id + '</b> · ' + esc(x.user || '') + ' <code>' + x.user_id + '</code><div class="muted">' + esc(x.plan) + ' · ' + x.days + ' · ' + esc(x.amount) + " · " + esc(x.at) + '</div>' +
          '<div class="row" style="margin-top:6px"><button class="small" data-rok="' + x.id + '">✅</button><button class="small danger" data-rno="' + x.id + '">❌</button></div></div>';
      }).join('') : '<div class="muted">' + esc(t('ma_ad_no_receipts')) + '</div>';
      var dec = function (id, yes) { api('admin_receipt', {id: id, approve: yes}).then(function (x) { toast(x.ok ? t('ma_saved') : errText(x)); loadReceipts(); }); };
      document.querySelectorAll('[data-rok]').forEach(function (b) { b.onclick = function () { dec(parseInt(b.getAttribute('data-rok'), 10), true); }; });
      document.querySelectorAll('[data-rno]').forEach(function (b) { b.onclick = function () { dec(parseInt(b.getAttribute('data-rno'), 10), false); }; });
    });
  }
  function loadPromos() {
    api('admin_promos').then(function (r) {
      if (!r.ok) { return; }
      $('ad-promos').innerHTML = r.promos.map(function (p) {
        return '<div class="row" style="align-items:center;margin-bottom:6px"><div style="flex:3"><b>' + esc(p.code) + '</b> <span class="muted">' + esc(p.tier.toUpperCase()) + ' · ' + p.days + 'd · ' + p.used + '/' + (p.max === null ? '∞' : p.max) + '</span></div>' +
          '<button class="small ' + (p.active ? 'ghost' : '') + '" data-pt="' + esc(p.code) + '" data-on="' + (p.active ? 0 : 1) + '">' + (p.active ? '⏸' : '▶️') + '</button></div>';
      }).join('');
      document.querySelectorAll('[data-pt]').forEach(function (b) {
        b.onclick = function () { api('admin_promo_toggle', {code: b.getAttribute('data-pt'), active: b.getAttribute('data-on') === '1'}).then(function () { loadPromos(); }); };
      });
    });
  }
  $('ag-go').onclick = function () {
    api('admin_grant', {user_id: parseInt($('ag-id').value, 10), tier: $('ag-tier').value, days: parseInt($('ag-days').value, 10)}).then(function (r) {
      toast(r.ok ? t('ma_ad_granted', {date: r.expires}) : errText(r)); if (r.ok) { haptic('ok'); }
    });
  };
  $('au-go').onclick = function () {
    var id = parseInt($('au-id').value, 10);
    api('admin_user', {id: id}).then(function (r) {
      if (!r.ok) { $('au-out').textContent = errText(r); return; }
      var u = r.user;
      $('au-out').innerHTML = '<b>' + esc(u.name) + '</b>' + (u.username ? ' @' + esc(u.username) : '') + '<div class="muted">' + esc(u.tier) + (u.expires ? ' · ' + esc(u.expires) : '') +
        ' · 📢 ' + u.channels + ' · 📅 ' + u.pending + ' · ✅ ' + u.sent + ' · 🪙 ' + u.credits + '</div><div class="muted">' + esc(t('ma_ad_joined')) + ': ' + esc(u.joined) + (u.blocked ? ' · 🚫 bot' : '') + '</div>' +
        '<div style="margin-top:8px"><button class="small ' + (u.market_banned ? '' : 'danger') + '" id="au-ban">' + esc(t(u.market_banned ? 'ma_ad_unban' : 'ma_ad_ban')) + '</button></div>';
      $('au-ban').onclick = function () { api('admin_market_ban', {id: id, ban: !u.market_banned}).then(function (x) { toast(x.ok ? t('ma_saved') : errText(x)); $('au-go').onclick(); }); };
    });
  };
  $('ap-go').onclick = function () {
    api('admin_promo_create', {code: $('ap-code').value.trim(), tier: $('ap-tier').value, days: parseInt($('ap-days').value || '30', 10), max: $('ap-max').value.trim()}).then(function (r) {
      toast(r.ok ? t('ma_ad_promo_ok', {code: r.code}) : errText(r)); if (r.ok) { $('ap-code').value = ''; loadPromos(); }
    });
  };
  // ---------- yuborish
  $('submit').onclick = function () {
    if (!state.channel) { toast(t('ma_err_channel')); return; }
    var body = {channel_id: state.channel, extra_channel_ids: state.extra.filter(function (x) { return x !== state.channel; }),
      options: state.opts, hidden: $('hid').value.trim(), type: state.type, file_id: state.fileId, text: editorHtml(),
      button_text: $('b-text').value.trim(), button_url: $('b-url').value.trim(), reactions: state.reactions,
      repeat: $('rep').value, time2: $('t2').value, delete_after: parseInt($('ad').value || '0', 10), when: 'now'};
    if (state.when === 'later') { if (!$('when').value) { toast(t('ma_err_bad_time')); return; } body.when = $('when').value; }
    var btn = this; btn.disabled = true; btn.textContent = '⏳';
    api('post_create', body).then(function (r) {
      btn.disabled = false; btn.textContent = t(state.when === 'later' ? 'ma_schedule' : 'ma_send_now');
      if (!r.ok) { toast(errText(r)); return; }
      haptic('ok');
      var msg = r.status === 'multi' ? r.results.map(function (x) {
        return (x.status === 'sent' ? '✅ ' : x.status === 'failed' ? '❌ ' : x.status === 'queued' ? '⏳ ' : '📅 ') + x.channel + (x.reason ? ' — ' + x.reason : '');
      }).join(' · ')
        : r.status === 'sent' ? t('ma_sent') : r.status === 'queued' ? t('ma_queued') : t('ma_scheduled', {when: r.when});
      if (r.next) { msg += ' ' + t('ma_next', {when: r.next}); }
      toast(msg); resetEditor(); loadMe();
    });
  };
  function resetEditor() {
    setEditor(''); $('b-text').value = ''; $('b-url').value = ''; $('rep').value = ''; $('t2-box').style.display = 'none'; $('ad').value = '0';
    state.reactions = ''; renderReactions(); $('media-del').onclick();
    state.opts = []; state.extra = []; $('hid').value = ''; renderOpts(); renderExtra(); refreshPreview();
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

  function render() {
    var p = me.plan;
    $('plan').textContent = p.name; $('plan').className = 'badge ' + (p.tier === 'ultra' ? 'ultra' : p.tier === 'free' ? '' : 'pro');
    $('hello').textContent = t('ma_hello', {name: me.user.name || ''});
    $('tzline').textContent = '🕒 ' + me.user.timezone + (me.workspace ? ' · ' + me.workspace.owner : '');
    $('s-pending').textContent = me.stats.pending; $('s-sent').textContent = me.stats.sent; $('s-channels').textContent = me.stats.channels;
    $('ai-quota').textContent = me.ai.enabled ? quotaText() : t('ma_ai_none');
    var MN = {gemini: 'Google Gemini', groq: 'Groq', openrouter: 'OpenRouter'};
    $('ai-models').innerHTML = (me.ai.models || []).map(function (m, i) {
      return '<div class="aim"><span class="dot"></span><b>' + esc(MN[m.name] || m.name) + '</b><span class="muted">' + esc(m.model) + '</span>' +
        (i === 0 ? '<em>' + esc(t('ma_ai_main')) + '</em>' : '') + '</div>';
    }).join('') + (me.ai.media ? '<div class="muted" style="margin-top:6px">📷🎙 ' + esc(t('ma_ai_media')) + '</div>' : '');
    $('ai-row').style.display = me.ai.enabled ? '' : 'none'; $('home-ai').style.display = me.ai.enabled ? '' : 'none'; $('ai-card').style.display = '';
    var initial = (me.user.name || '🙂').trim().charAt(0).toUpperCase() || '🙂';
    $('me-name').textContent = me.user.name || '';
    $('avatar').textContent = initial;
    var tu = (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) || {};
    $('me-sub').textContent = (tu.username ? '@' + tu.username + ' · ' : '') + 'ID ' + me.user.id;
    var av = $('me-av');
    if (typeof tu.photo_url === 'string' && /^https:\/\/t\.me\//.test(tu.photo_url)) {
      av.textContent = ''; av.style.backgroundImage = 'url("' + tu.photo_url.replace(/["\\]/g, '') + '")';
    } else { av.textContent = initial; av.style.backgroundImage = ''; }
    var tgp = !!tu.is_premium;
    document.documentElement.setAttribute('data-tgp', tgp ? '1' : '0');
    $('me-badge').textContent = tgp ? '⭐ Premium' : ''; $('me-badge').style.display = tgp ? '' : 'none';
    $('me-admin').style.display = me.user.is_admin ? '' : 'none';
    $('me-plan').textContent = p.expires ? '⏳ ' + t('ma_until', {date: p.expires}) : (p.tier === 'free' ? '✨ ' + t('ma_free_hint') : '♾ ' + t('ma_forever'));
    var inf = function (n) { return n === 0 ? '∞' : n; };
    $('me-limits').textContent = t('ma_limits', {ch: inf(p.channels_max), q: inf(p.queue_max)});
    $('me-st-ch').textContent = me.stats.channels + '/' + inf(p.channels_max);
    $('me-st-q').textContent = me.stats.pending + '/' + inf(p.queue_max);
    $('me-st-ai').textContent = !me.ai.enabled ? '—' : (me.ai.limit === 0 ? '∞' : me.ai.left + '/' + me.ai.limit);
    $('me-plan-tag').textContent = p.tier === 'free' ? t('ma_li_upgrade') : (p.expires ? t('ma_until', {date: p.expires.slice(0, 10)}) : p.name);
    $('me-lang').value = me.user.lang;
    renderTz();
    $('ad').innerHTML = '<option value="0">' + esc(t('ma_ad_none')) + '</option>' + me.auto_delete.map(function (m) { return '<option value="' + m + '">' + esc(t('ma_ad_hours', {h: m / 60})) + '</option>'; }).join('');
    $('when').min = me.now_local; $('when-tz').textContent = '🕒 ' + me.user.timezone;
    if (!me.channels.length) { $('no-ch').style.display = ''; $('editor-wrap').style.display = 'none'; }
    else {
      $('no-ch').style.display = 'none'; $('editor-wrap').style.display = '';
      if (!me.channels.some(function (c) { return c.id === state.channel; })) { state.channel = me.channels[0].id; }
    }
    renderChannels(); renderReactions(); renderOpts(); refreshPreview();
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


  // ---------- 🎨 Ko'rinish: mavzu, rang, o'lcham, zichlik, animatsiya, bosh sahifa bo'limlari, ochilish sahifasi
  // localStorage (darhol) + Telegram CloudStorage (boshqa qurilmada ham) — faqat shu foydalanuvchining sozlamasi.
  var UI_KEY = 'pa_ui_v1';
  var UI_DEF = {theme: 'auto', accent: 'tg', size: 'm', density: 'cozy', motion: 'on', labels: 'on', hide: [], start: 'home'};
  var ui = JSON.parse(JSON.stringify(UI_DEF));
  var ACCENTS = {tg: 'var(--tg-theme-button-color,#2f7cf6)', blue: '#2f7cf6', violet: '#7c5cff', green: '#10b981', orange: '#f97316', pink: '#ec4899', teal: '#0ea5a4', red: '#ef4444'};
  var HOME_PARTS = {stats: 'home-stats', ai: 'ai-card', comments: 'cm-card', channels: 'st-card', bot: 'bot-card'};
  function uiMerge(o) {
    if (!o || typeof o !== 'object') { return; }
    Object.keys(UI_DEF).forEach(function (k) { if (o[k] !== undefined) { ui[k] = o[k]; } });
    if (!Array.isArray(ui.hide)) { ui.hide = []; }
  }
  try { uiMerge(JSON.parse(localStorage.getItem(UI_KEY) || 'null')); } catch (e) {}
  function applyUi() {
    var h = document.documentElement;
    if (ui.theme === 'auto') { h.removeAttribute('data-theme'); } else { h.setAttribute('data-theme', ui.theme); }
    if (ui.accent === 'tg') { h.removeAttribute('data-accent'); } else { h.setAttribute('data-accent', ui.accent); }
    h.setAttribute('data-size', ui.size); h.setAttribute('data-density', ui.density);
    h.setAttribute('data-motion', ui.motion); h.setAttribute('data-labels', ui.labels);
    Object.keys(HOME_PARTS).forEach(function (k) { var el = $(HOME_PARTS[k]); if (el) { el.classList.toggle('ui-hidden', ui.hide.indexOf(k) >= 0); } });
    try { if (tg && tg.setHeaderColor && ui.theme !== 'auto') { tg.setHeaderColor(ui.theme === 'dark' ? '#0d1016' : '#f2f4fa'); } } catch (e) {}
  }
  function saveUi() {
    var j = JSON.stringify(ui);
    try { localStorage.setItem(UI_KEY, j); } catch (e) {}
    try { if (tg && tg.CloudStorage && tg.isVersionAtLeast && tg.isVersionAtLeast('6.9')) { tg.CloudStorage.setItem(UI_KEY, j); } } catch (e) {}
    applyUi(); renderUi(); haptic();
  }
  function chips(id, key, opts) {
    var box = $(id); if (!box) { return; }
    box.innerHTML = opts.map(function (o) { return '<span class="chip' + (ui[key] === o[0] ? ' on' : '') + '" data-ui="' + key + '" data-v="' + o[0] + '">' + esc(o[1]) + '</span>'; }).join('');
  }
  function renderUi() {
    if (!$('ui-card')) { return; }
    chips('ui-theme', 'theme', [['auto', '📱 ' + t('ma_ui_auto')], ['light', '☀️ ' + t('ma_ui_light')], ['dark', '🌙 ' + t('ma_ui_dark')]]);
    $('ui-accent').innerHTML = Object.keys(ACCENTS).map(function (k) {
      return '<span class="sw' + (ui.accent === k ? ' on' : '') + '" data-acc="' + k + '" title="' + k + '" style="background:' + ACCENTS[k] + '"></span>';
    }).join('');
    chips('ui-size', 'size', [['s', 'A−'], ['m', 'A'], ['l', 'A+']]);
    chips('ui-density', 'density', [['cozy', t('ma_ui_cozy')], ['compact', t('ma_ui_compact')]]);
    chips('ui-motion', 'motion', [['on', t('ma_ui_on')], ['off', t('ma_ui_off')]]);
    chips('ui-labels', 'labels', [['on', t('ma_ui_on')], ['off', t('ma_ui_off')]]);
    chips('ui-start', 'start', [['home', '🏠 ' + t('ma_tab_home')], ['post', '✍️ ' + t('ma_tab_post')], ['queue', '📅 ' + t('ma_tab_queue')], ['market', '💰 ' + t('ma_tab_market')]]);
    $('ui-home').innerHTML = Object.keys(HOME_PARTS).map(function (k) {
      return '<span class="chip' + (ui.hide.indexOf(k) < 0 ? ' on' : '') + '" data-hp="' + k + '">' + esc(t('ma_ui_part_' + k)) + '</span>';
    }).join('');
  }
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-ui]');
    if (c) { ui[c.getAttribute('data-ui')] = c.getAttribute('data-v'); saveUi(); return; }
    var a = e.target.closest('[data-acc]');
    if (a) { ui.accent = a.getAttribute('data-acc'); saveUi(); return; }
    var hp = e.target.closest('[data-hp]');
    if (hp) { var k = hp.getAttribute('data-hp'), i = ui.hide.indexOf(k); if (i >= 0) { ui.hide.splice(i, 1); } else { ui.hide.push(k); } saveUi(); }
  });
  $('ui-reset').onclick = function () { ui = JSON.parse(JSON.stringify(UI_DEF)); saveUi(); toast(t('ma_saved')); };
  applyUi();
  try {
    if (tg && tg.CloudStorage && tg.isVersionAtLeast && tg.isVersionAtLeast('6.9')) {
      tg.CloudStorage.getItem(UI_KEY, function (err, v) { if (!err && v) { try { uiMerge(JSON.parse(v)); localStorage.setItem(UI_KEY, v); } catch (e) {} applyUi(); renderUi(); } });
    }
  } catch (e) {}

  // ---------- 🌍 vaqt mintaqasi: istalgan davlat yoki shahar bo'yicha qidiruv
  function renderTz() { if (me) { $('tz-cur').innerHTML = '<span>🕒 <b>' + esc(me.user.timezone) + '</b></span><span class="muted">' + esc(me.now_local.slice(11)) + '</span>'; $('tz-short').textContent = me.user.timezone.split('/').pop().replace(/_/g, ' '); } }
  var tzTimer = null;
  $('tz-q').addEventListener('input', function () {
    var q = this.value.trim(); clearTimeout(tzTimer);
    if (q.length < 2) { $('tz-res').innerHTML = ''; return; }
    tzTimer = setTimeout(function () {
      api('tz_search', {q: q}).then(function (r) {
        if (!r.ok) { return; }
        $('tz-res').innerHTML = r.results.length ? r.results.map(function (x) {
          return '<div class="tzr" data-tz="' + esc(x.zone) + '"><span>' + esc(x.flag) + ' ' + esc(x.country || x.zone) + '</span><span class="muted">' + esc(x.label) + '</span></div>';
        }).join('') : '<div class="muted" style="margin-top:6px">' + esc(t('ma_tz_none')) + '</div>';
      });
    }, 300);
  });
  $('tz-res').addEventListener('click', function (e) {
    var el = e.target.closest('[data-tz]'); if (!el) { return; }
    api('settings', {timezone: el.getAttribute('data-tz')}).then(function (r) {
      if (!r.ok) { toast(errText(r)); return; }
      $('tz-q').value = ''; $('tz-res').innerHTML = ''; haptic('ok'); toast(t('ma_saved')); loadMe();
    });
  });
  // ---------- ishga tushirish
  if (tg) {
    tg.ready(); tg.expand();
    try { tg.setHeaderColor('secondary_bg_color'); } catch (e) {}
    // to'liq ekran (Telegram 8.0+, telefonda): yuqori tizim tugmalari ostiga kontent tushmasin — xavfsiz zona CSS'da
    try { if (tg.isVersionAtLeast && tg.isVersionAtLeast('8.0') && /android|iphone|ipad/i.test(navigator.userAgent) && tg.requestFullscreen) { tg.requestFullscreen(); } } catch (e) {}
    try { if (tg.disableVerticalSwipes) { tg.disableVerticalSwipes(); } } catch (e) {}
  }
  applyUi();
  var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user; if (u && u.language_code) { lang = ['uz', 'ru'].indexOf(u.language_code.slice(0, 2)) >= 0 ? u.language_code.slice(0, 2) : 'en'; }
  applyI18n();
  if (!initData) { $('boot').innerHTML = '<div class="empty"><b>📱</b>' + esc(t('ma_err_open_in_tg')) + '</div>'; return; }
  loadMe().then(function (ok) {
    if (!ok) { return; }
    $('boot').style.display = 'none';
    var tab = (new URLSearchParams(location.search)).get('tab');
    go(['home', 'post', 'queue', 'market', 'me', 'admin', 'plans'].indexOf(tab) >= 0 ? tab : (['home', 'post', 'queue', 'market'].indexOf(ui.start) >= 0 ? ui.start : 'home'));
    checkDraft();
  });
})();
</script>
</body>
</html>
