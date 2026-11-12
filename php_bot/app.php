<?php
// 📱 PostAssist Mini App (Telegram ichida ochiladi). Tashqi kutubxonasiz: bitta sahifa, ma'lumot api.php orqali.
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

use PostAssist\I18n;

$nonce = base64_encode(random_bytes(16));
header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
// Telegram ichidagi brauzer sahifani keshlab eski versiyani ko'rsatmasin
header('Cache-Control: no-cache, no-store, must-revalidate');
header('Pragma: no-cache');
header('Expires: 0');
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

.hint{margin:0 4px 12px;padding:10px 12px;border-radius:14px;background:var(--soft);font-size:13px;line-height:1.45;color:var(--text)}
.chips.seg3{grid-template-columns:repeat(3,1fr);margin-bottom:12px}.chips.seg3 .chip{font-size:12.5px;padding:8px 4px}
.errline{margin-top:6px;font-size:12px;color:var(--danger);word-break:break-word}
.auto-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;padding:14px!important;border-radius:20px!important;min-height:128px;background:var(--glass)!important;color:var(--text)!important;border:1px solid var(--line)!important;box-shadow:var(--sh1)!important}
.tile i{font-style:normal;font-size:24px;width:44px;height:44px;border-radius:14px;display:grid;place-items:center;background:var(--soft);margin-bottom:4px}
.tile b{font-size:15px}.tile span{font-size:12px;font-weight:500;color:var(--hint);line-height:1.35}
.br-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}.br-head b{font-size:17px;font-weight:800}.br-head button{width:auto}
.bscreen{padding:16px}.bscreen.old{opacity:.55}.btxt{line-height:1.55;font-size:14.5px;word-break:break-word}.btxt code{font-size:13px}
.brow{display:grid;gap:8px;margin-top:10px}.brow.n1{grid-template-columns:1fr}.brow.n2{grid-template-columns:1fr 1fr}.brow.n3{grid-template-columns:1fr 1fr 1fr}
.bbtn{display:flex;align-items:center;justify-content:center;text-align:center;min-height:44px;padding:10px 8px;border-radius:14px;font-weight:700;font-size:14px;text-decoration:none;cursor:pointer;
  border:1px solid var(--line);background:var(--glass);color:var(--text);box-shadow:var(--sh1);word-break:break-word;width:100%}
.bbtn:active{background:var(--soft)}
button.bbtn,a.bbtn{background:var(--glass)!important;color:var(--text)!important;box-shadow:var(--sh1)!important;border:1px solid var(--line)!important}
.br-input{position:sticky;bottom:96px;display:flex;gap:8px;margin-top:10px;padding:8px;border-radius:18px;background:var(--glass);border:1px solid var(--line);box-shadow:var(--sh1);backdrop-filter:blur(14px)}
.br-input input{flex:1}.br-input button{width:52px;padding:0}
.steps{margin:0 0 12px;padding-left:20px;line-height:1.9;font-size:14px;color:var(--hint)}.steps li.now{color:var(--text);font-weight:700}.steps li.done{text-decoration:line-through;opacity:.6}
.card.start{border:1px solid var(--accent)}

/* ---------- pastki panel: 4 bo'lim + «＋» (jami 5), chiziqli ikonkalar */
.dock{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(12px + env(safe-area-inset-bottom));width:min(560px,calc(100% - 24px));display:flex;align-items:center;gap:10px;z-index:9}
.dock nav#nav{position:static;transform:none;flex:1;width:auto;display:flex;gap:2px;padding:5px;border-radius:32px;background:var(--glass);
  border:1px solid var(--line);box-shadow:0 10px 34px -10px rgba(16,24,40,.35);backdrop-filter:blur(18px) saturate(170%);-webkit-backdrop-filter:blur(18px) saturate(170%)}
.dock nav#nav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 2px 7px;border-radius:26px;color:var(--hint);font-size:11px;font-weight:600;text-decoration:none;transition:background .2s,color .2s}
.dock nav#nav a::before{display:none!important}
.dock nav#nav a i{width:24px;height:24px;display:block;transform:none!important}
.dock nav#nav a i svg{width:24px;height:24px;display:block}
.dock nav#nav a.on{color:var(--text);background:rgba(128,128,128,.14)}
.dock nav#nav a.on i{color:var(--accent)}
html[data-labels=off] .dock nav#nav a span{display:none}html[data-labels=off] .dock nav#nav a{padding:12px 2px}
.fab{flex:0 0 62px;width:62px!important;height:62px;padding:0!important;border-radius:50%!important;display:grid;place-items:center;color:#fff!important;
  background:linear-gradient(135deg,var(--accent),var(--accent2))!important;box-shadow:0 12px 28px -8px var(--accent)!important}
.fab svg{width:28px;height:28px}
.fab.on{box-shadow:0 0 0 4px var(--soft),0 12px 28px -8px var(--accent)!important}
body{padding-bottom:calc(100px + env(safe-area-inset-bottom))}
.li i.ic{color:#fff;box-shadow:none;font-size:16px}
.g-orange{background:linear-gradient(135deg,#f7a54a,#f07c2b)!important}.g-green{background:linear-gradient(135deg,#9be15d,#3fbf5f)!important}
.g-teal{background:linear-gradient(135deg,#34d399,#0ea5a4)!important}.g-violet{background:linear-gradient(135deg,#8b7cf6,#6d5cf0)!important}
.g-pink{background:linear-gradient(135deg,#f472b6,#e5486e)!important}.g-blue{background:linear-gradient(135deg,#60a5fa,#3b6cf6)!important}
.list.hl-gold{background:linear-gradient(135deg,rgba(247,165,74,.20),rgba(247,165,74,.08))}.list.hl-green{background:linear-gradient(135deg,rgba(155,225,93,.24),rgba(63,191,95,.08))}

/* ---------- o'z uslubimiz: markazda ko'tarilgan «＋», faol bo'lim nuqta bilan, banner va plitkalar */
.dock{gap:0}
.dock nav#nav{align-items:flex-end;padding:6px 6px 5px;border-radius:26px;overflow:visible}
.dock nav#nav a{border-radius:16px;padding:7px 2px 6px;position:relative}
.dock nav#nav a.on{background:transparent;color:var(--accent)}
.dock nav#nav a.on::after{content:"";position:absolute;bottom:1px;left:50%;width:5px;height:5px;margin-left:-2.5px;border-radius:50%;background:var(--accent)}
.dock nav#nav a.on i svg{stroke-width:2.3}
.dock .fab{flex:0 0 58px;width:58px!important;height:58px;margin:-26px 6px 2px;border:4px solid var(--bg)!important;border-radius:20px!important;transform:rotate(0);transition:transform .25s}
.dock .fab:active{transform:scale(.94)}
.logo svg{width:20px;height:20px}
.prem{display:flex;align-items:center;gap:12px;width:100%;text-align:left;margin:0 0 6px;padding:14px 16px!important;border-radius:22px!important;color:#2b1700!important;
  background:linear-gradient(120deg,#ffd76a,#ffb547 55%,#ff8f3d)!important;box-shadow:0 12px 26px -12px rgba(255,143,61,.7)!important;border:0!important}
.prem-ic{font-size:26px;width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:rgba(255,255,255,.4)}
.prem-tx{flex:1;display:flex;flex-direction:column;min-width:0}.prem-tx b{font-size:16px}.prem-sub{font-size:12.5px;opacity:.8;font-weight:600}
.prem-cta{background:#2b1700;color:#ffd76a;font-size:12.5px;font-weight:800;padding:8px 12px;border-radius:12px;white-space:nowrap}
.mini-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:6px}
.mini-tiles button{display:flex;flex-direction:column;align-items:center;gap:6px;padding:12px 4px!important;border-radius:18px!important;background:var(--glass)!important;
  color:var(--text)!important;border:1px solid var(--line)!important;box-shadow:var(--sh1)!important;font-size:11.5px;font-weight:700}
.mini-tiles i{font-style:normal;font-size:20px;width:40px;height:40px;border-radius:13px;display:grid;place-items:center;background:var(--soft)}
.qa{display:grid;grid-template-columns:1fr;gap:8px}
.qa-i{display:grid;grid-template-columns:44px 1fr;grid-template-rows:auto auto;column-gap:12px;text-align:left;padding:12px!important;border-radius:16px!important;
  background:var(--bg)!important;color:var(--text)!important;border:1px solid var(--line)!important;box-shadow:none!important}
.qa-i i{grid-row:1/3;font-style:normal;font-size:22px;width:44px;height:44px;border-radius:14px;display:grid;place-items:center;background:var(--soft)}
.qa-i b{font-size:15px}.qa-i span{font-size:12px;color:var(--hint);font-weight:500}
.up-list{display:flex;flex-direction:column;gap:8px;margin-top:10px}
.up{display:flex;gap:12px;align-items:center;padding:10px;border-radius:14px;background:var(--soft)}
.up-t{flex:0 0 58px;text-align:center;font-weight:800;font-size:16px;line-height:1.1}.up-t small{display:block;font-size:11px;color:var(--hint);font-weight:600}
.up-b{flex:1;min-width:0;display:flex;flex-direction:column}.up-b b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:14px}

.q-search{margin-bottom:10px;border-radius:14px}
.days{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;margin:0 -16px 12px;padding:2px 16px 4px}.days::-webkit-scrollbar{display:none}
.day{flex:0 0 52px;width:52px!important;display:flex;flex-direction:column;align-items:center;gap:1px;padding:7px 0 6px!important;border-radius:16px!important;
  background:var(--glass)!important;color:var(--text)!important;border:1px solid var(--line)!important;box-shadow:none!important;font-weight:700}
.day small{font-size:10.5px;color:var(--hint);font-weight:600;text-transform:capitalize}.day b{font-size:17px}.day i{font-style:normal;font-size:10px;height:13px;color:var(--accent)}
.day.has i::before{content:"● "}
.day.on{background:linear-gradient(135deg,var(--accent),var(--accent2))!important;color:#fff!important;border-color:transparent!important}.day.on small,.day.on i{color:rgba(255,255,255,.9)}
.qp .body{width:100%}.pacts{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}.pacts button{width:auto!important;padding:7px 10px!important;font-size:12.5px}
.danger-t{color:var(--danger)!important}
.when-q{margin:10px 0 2px}
.chip.on{color:#fff!important}

.bed{display:flex;flex-direction:column;gap:8px}.bed-row{display:flex;flex-wrap:wrap;gap:6px;padding:8px;border-radius:14px;background:var(--bg);border:1px dashed var(--line)}
.bed-btn{flex:1 1 140px;display:grid;grid-template-columns:1fr auto;gap:4px;min-width:0}.bed-btn .bt{grid-column:1}.bed-btn .bu{grid-column:1;font-size:13px}
.bed-btn .bx{grid-column:2;grid-row:1/3;width:auto!important;padding:4px 8px!important;align-self:center}.badd{width:auto!important;align-self:flex-start}
.st-sub{margin-top:12px;padding-top:10px;border-top:1px solid var(--line,rgba(127,127,127,.18))}.st-top{display:flex;gap:10px;margin-top:8px;align-items:flex-start}.st-n{flex:0 0 22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:12px;display:flex;align-items:center;justify-content:center}
.pbrow{display:flex;gap:4px;max-width:92%}.pbrow .pbtn{flex:1;max-width:none}
</style>
</head>
<body>
<header><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 3 10 14"/><path d="M21 3 14.5 21l-4.5-7-7-4.5z"/></svg></div><h1>PostAssist</h1><span class="badge" id="plan">…</span></header>
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
      <button class="big ghost" data-go="queue"><span>📅</span><b data-t="ma_tab_posts"></b></button>
      <button class="big ghost" data-go="auto"><span>🤖</span><b data-t="ma_tab_auto"></b></button>
    </div>
    <div class="card start" id="start-card" style="display:none"><h3 data-t="ma_start_title"></h3>
      <ol class="steps"><li id="stp1" data-t="ma_start_1"></li><li id="stp2" data-t="ma_start_2"></li><li id="stp3" data-t="ma_start_3"></li></ol>
      <button class="small" id="start-go"></button></div>
    <div class="card" id="up-card" style="display:none"><div class="row" style="align-items:center"><h3 style="flex:2;margin:0" data-t="ma_up_title"></h3>
      <button class="small ghost" data-go="queue" style="flex:0 0 auto" data-t="ma_all"></button></div><div id="up-list" class="up-list"></div></div>
    <div class="card" id="ai-card"><h3 data-t="ma_ai_title"></h3><div class="muted" id="ai-quota"></div>
      <div class="set-row" data-t="ma_ai_models"></div><div id="ai-models" class="ai-models"></div></div>
    <div class="card" id="cm-card" style="display:none"><div class="row"><b style="flex:2">💬 <span data-t="ma_cm_title"></span> <span id="cm-count"></span></b>
      <button class="small ghost" id="cm-open" data-t="ma_open"></button></div></div>
    <div class="card" id="st-card" style="display:none"><h3>📊 <span data-t="ma_st_title"></span></h3><div id="st-list"></div></div>
    <div id="bot-card"><div class="grp-t" data-t="ma_in_bot"></div>
      <div class="list">
        <button class="li" data-go="stats"><i class="ic g-teal">📊</i><span data-t="ma_tab_stats"></span><b>›</b></button>
        <button class="li" data-go="market"><i class="ic g-violet">💰</i><span data-t="ma_go_market"></span><b>›</b></button>
        <button class="li" data-br="set:team" data-bt="ma_go_team"><i class="ic g-blue">👥</i><span data-t="ma_go_team"></span><b>›</b></button>
        <button class="li" data-go="plans"><i class="ic g-orange">👑</i><span data-t="ma_li_premium"></span><b>›</b></button>
      </div></div>
  </section>

  <section class="page" id="p-post">
    <div class="banner" id="draft-banner" style="display:none"><div style="flex:1" data-t="ma_draft_found"></div><button class="small" id="draft-load" data-t="ma_open"></button></div>
    <div class="card" id="no-ch" style="display:none"><div class="empty"><b>📢</b><span data-t="ma_no_channels"></span></div><button id="no-ch-bot" data-t="ma_add_channel"></button></div>
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
          <div class="muted" data-t="ma_btns_hint" style="margin-bottom:6px"></div><div class="bed" id="b-rows"></div>
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
        <div id="when-box" style="display:none"><div class="chips when-q" id="when-quick"></div><label data-t="ma_when"></label><input type="datetime-local" id="when"><div class="muted" id="when-tz"></div></div>
        <div style="margin-top:12px"><button id="submit" data-t="ma_send_now"></button></div>
        <div style="margin-top:8px"><button class="ghost" id="tpl-save">💾 <span data-t="ma_tpl_save"></span></button></div>
      </div>
    </div>
  </section>

  <section class="page" id="p-queue">
    <div class="hint" data-t="ma_hint_queue"></div>
    <div class="chips seg seg3" id="q-seg"><span class="chip on" data-seg="sched" data-t="ma_q_sched"></span><span class="chip" data-seg="sent" data-t="ma_q_sent"></span><span class="chip" data-seg="failed" data-t="ma_q_failed"></span></div>
    <input id="q-search" class="q-search" data-ph="ma_q_search" type="search">
    <div class="days" id="q-days"></div>
    <div id="q-list"></div>
  </section>

  <section class="page" id="p-auto">
    <div class="hint" data-t="ma_hint_auto"></div>
    <div class="auto-grid">
      <button class="tile" data-br="cp:show" data-bt="ma_au_plan"><i>📅</i><b data-t="ma_au_plan"></b><span data-t="ma_au_plan_d"></span></button>
      <button class="tile" data-br="ap:show" data-bt="ma_au_ap"><i>🤖</i><b data-t="ma_au_ap"></b><span data-t="ma_au_ap_d"></span></button>
      <button class="tile" data-br="rss:show" data-bt="ma_au_rss"><i>📰</i><b data-t="ma_au_rss"></b><span data-t="ma_au_rss_d"></span></button>
      <button class="tile" data-br="bk:start" data-bt="ma_au_bulk"><i>📦</i><b data-t="ma_au_bulk"></b><span data-t="ma_au_bulk_d"></span></button>
      <button class="tile" data-br="poll:start" data-bt="ma_au_poll"><i>📊</i><b data-t="ma_au_poll"></b><span data-t="ma_au_poll_d"></span></button>
      <button class="tile" data-br="tpl:list" data-bt="ma_au_tpl"><i>💾</i><b data-t="ma_au_tpl"></b><span data-t="ma_au_tpl_d"></span></button>
    </div>
  </section>

  <section class="page" id="p-bot">
    <div class="br-head"><button class="ghost small" id="br-back">‹ <span data-t="ma_back"></span></button><b id="br-title"></b></div>
    <div id="br-body"></div>
    <div class="br-input" id="br-input" style="display:none"><input id="br-text" data-ph="ma_br_type" maxlength="4000"><button id="br-send">➤</button></div>
  </section>

  <section class="page" id="p-market">
    <div class="mk-head"><button class="small ghost" id="mk-threads">💬 <span data-t="ma_mk_threads"></span></button>
      <button class="small" data-br="mk:pub" data-bt="ma_mk_publish">➕ <span data-t="ma_mk_publish"></span></button></div>
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

    <button class="prem" data-go="plans"><span class="prem-ic">👑</span><span class="prem-tx"><b data-t="ma_prem_title"></b><span id="me-prem-tag" class="prem-sub"></span></span><span class="prem-cta" data-t="ma_prem_cta"></span></button>
    <div class="grp-t" data-t="ma_li_ai_studio"></div>
    <div class="mini-tiles">
      <button data-br="cp:show" data-bt="ma_au_plan"><i>📅</i><span data-t="ma_au_plan"></span></button>
      <button data-br="ap:show" data-bt="ma_au_ap"><i>🤖</i><span data-t="ma_au_ap"></span></button>
      <button data-br="rss:show" data-bt="ma_au_rss"><i>📰</i><span data-t="ma_au_rss"></span></button>
      <button data-go="auto"><i>⋯</i><span data-t="ma_more"></span></button>
    </div>
    <div class="list">
      <button class="li" data-go="stats"><i class="ic g-teal">📊</i><span data-t="ma_tab_stats"></span><b>›</b></button>
      <button class="li" data-go="market"><i class="ic g-violet">💰</i><span data-t="ma_go_market"></span><b>›</b></button>
      <button class="li" data-br="ref:show" data-bt="ma_li_invite"><i class="ic g-pink">🤝</i><span data-t="ma_li_invite"></span><b>›</b></button>
    </div>

    <div class="grp-t" data-t="ma_grp_account"></div>
    <div class="list">
      <button class="li" id="me-plans"><i>💎</i><span data-t="ma_li_plans"></span><em id="me-plan-tag"></em><b>›</b></button>
      <button class="li" data-br="set:team" data-bt="ma_go_team"><i>👥</i><span data-t="ma_go_team"></span><b>›</b></button>
      <button class="li" data-br="promo:ask" data-bt="ma_li_promo"><i>🎁</i><span data-t="ma_li_promo"></span><b>›</b></button>
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
      <button class="li" data-br="set:help" data-bt="ma_li_help"><i>❓</i><span data-t="ma_li_help"></span><b>›</b></button>
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
      <button class="ghost small" id="pl-uzs" data-br="pl:card" data-bt="ma_pl_uzs">🇺🇿 <span data-t="ma_pl_uzs"></span></button>
      <button class="ghost small" data-br="promo:ask" data-bt="ma_pl_promo">🎁 <span data-t="ma_pl_promo"></span></button>
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
      <div class="row"><input id="ap-code" data-ph="ma_ad_code_ph" maxlength="32"><select id="ap-tier"><option value="pro">PRO</option><option value="ultra">ULTRA</option></select></div>
      <div class="row" style="margin-top:6px"><input id="ap-days" inputmode="numeric" placeholder="30"><input id="ap-max" inputmode="numeric" placeholder="∞"></div>
      <div style="height:8px"></div><button class="ghost" id="ap-go" data-t="ma_ad_promo_create"></button><div id="ad-promos" style="margin-top:10px"></div></div>
    <div class="card muted" data-t="ma_ad_bot_only"></div>
  </section>
</main>

<div class="dock">
<nav id="nav">
<a href="#" data-go="home" class="on"><i><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/></svg></i><span data-t="ma_tab_home"></span></a>
  <a href="#" data-go="channels"><i><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg></i><span data-t="ma_tab_channels"></span></a>
  <button class="fab" id="fab"  aria-label="+"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></button>
  <a href="#" data-go="queue"><i><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2.5"/><path d="M8 8h8M8 12h8M8 16h5"/></svg></i><span data-t="ma_tab_posts"></span></a>
  <a href="#" data-go="me"><i><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg></i><span data-t="ma_tab_me"></span></a>
</nav>
</div>

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
    var s = t(key, {max: r.max || '', len: r.len || '', max_mb: r.max_mb || '', n: r.n || '', s: r.s || ''});
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
  var cur = 'home', qseg = 'sched';
  var BR_PAGES = {channels: {d: 'ch:list', t: 'ma_tab_channels'}, stats: {d: 'st:show', t: 'ma_tab_stats', nav: 'me'}};
  var NAV_OF = {plans: 'me', admin: 'me', auto: 'home', market: 'me', post: null, bot: null};
  function centerNav(name) {
    var nav = $('nav'), a = nav.querySelector('a[data-go="' + name + '"]');
    nav.querySelectorAll('a').forEach(function (x) { x.classList.toggle('on', x === a); });
    var fab = $('fab'); if (fab) { fab.classList.toggle('on', cur === 'post'); }
    if (a) { try { nav.scrollTo({left: a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2, behavior: 'smooth'}); } catch (e) { nav.scrollLeft = a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2; } }
  }
  // joriy sahifani yangi til/ma'lumot bilan qayta chizish
  function refreshPage() {
    if (cur === 'bot') { if (br.stack.length) { var last = br.lastArg; $('br-title').textContent = t(br.title); if (last && last.d) { br.stack.pop(); brCall(last); } } return; }
    go(cur);
  }
  function go(page, opts) {
    var leaving = cur === 'bot' && page !== 'bot';
    if (leaving) { brLeave(); }
    var navName = page;
    if (BR_PAGES[page]) { brOpen(BR_PAGES[page].d, BR_PAGES[page].t, BR_PAGES[page].nav || page); return; }
    cur = page;
    document.querySelectorAll('.page').forEach(function (p) { p.classList.toggle('on', p.id === 'p-' + page); });
    if (page === 'bot') { navName = br.nav; } else if (NAV_OF.hasOwnProperty(page)) { navName = NAV_OF[page]; }
    centerNav(navName);
    if (tg && tg.BackButton) { page === 'home' ? tg.BackButton.hide() : tg.BackButton.show(); }
    if (page === 'queue') { if (opts && opts.seg) { qseg = opts.seg; } loadQueue(); }
    if (page === 'home') { loadStats(); loadComments(); loadUpcoming(); }
    if (page === 'post') { loadTemplates(); restoreLocalDraft(); }
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
  if (tg && tg.BackButton) { tg.BackButton.onClick(function () {
    if ($('modal').classList.contains('on')) { closeModal(); }
    else if (cur === 'bot' && br.stack.length > 1) { brBack(); }
    else { go('home'); }
  }); }

  var BOT_SECTIONS = ['go_market', 'go_team', 'go_plans', 'go_channels'];
  function openBot(section) {
    if (!me) { return; }
    var url = 'https://t.me/' + me.bot;
    if (typeof section === 'string' && BOT_SECTIONS.indexOf(section) >= 0) { url += '?start=' + section; }
    if (tg && tg.openTelegramLink) { tg.openTelegramLink(url); setTimeout(function () { tg.close(); }, 300); } else { location.href = url; }
  }
  $('no-ch-bot').onclick = function () { brOpen('ch:add', 'ma_tab_channels', 'channels'); };
  $('me-plans').onclick = function () { haptic(); go('plans'); }; $('me-bot').onclick = function () { openBot(); };
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-bot]');
    if (b) { e.preventDefault(); haptic(); openBot(b.getAttribute('data-bot')); }
  });




  // ---------- 🌉 bot ekranlari Mini App ichida (kanallar, avtopilot, kontent-reja, RSS, shablonlar, jamoa, taklif, promo …)
  var br = {stack: [], nav: 'home', title: '', busy: false, state: null};
  function tgHtml(src) {
    var doc = new DOMParser().parseFromString('<body>' + String(src).replace(/<\/?tg-emoji[^>]*>/g, '') + '</body>', 'text/html');
    var ok = {B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, STRIKE: 1, CODE: 1, PRE: 1, BLOCKQUOTE: 1};
    function walk(n) {
      var out = '';
      n.childNodes.forEach(function (c) {
        if (c.nodeType === 3) { out += esc(c.nodeValue); }
        else if (c.nodeType === 1) {
          var inner = walk(c), tag = c.tagName;
          if (tag === 'A') {
            var h = c.getAttribute('href') || '';
            out += /^https?:\/\/|^tg:\/\//.test(h) ? '<a href="' + esc(h) + '" target="_blank" rel="noopener">' + inner + '</a>' : inner;
          } else if (ok[tag]) { var lt = tag.toLowerCase(); out += '<' + lt + '>' + inner + '</' + lt + '>'; }
          else { out += inner; }
        }
      });
      return out;
    }
    return walk(doc.body).replace(/\n/g, '<br>');
  }
  function brRows(rows) {
    return rows.map(function (r) {
      var cls = 'brow n' + Math.min(r.length, 3);
      return '<div class="' + cls + '">' + r.map(function (b) {
        if (b.u) { return '<a class="bbtn" href="' + esc(b.u) + '" target="_blank" rel="noopener">' + esc(b.t) + '</a>'; }
        return '<button class="bbtn" data-bd="' + esc(b.d) + '">' + esc(b.t) + '</button>';
      }).join('') + '</div>';
    }).join('');
  }
  function brRender(r) {
    var html = '';
    (r.screens || []).forEach(function (sc, i) {
      var last = i === r.screens.length - 1;
      html += '<div class="card bscreen' + (last ? '' : ' old') + '">' + (sc.text ? '<div class="btxt">' + tgHtml(sc.text) + '</div>' : '') + (last ? brRows(sc.rows || []) : '') + '</div>';
    });
    if (!r.screens || !r.screens.length) { html = '<div class="card bscreen"><div class="btxt">' + esc(t('ma_br_done')) + '</div></div>'; }
    if (r.menu && (!r.screens || !r.screens.some(function (x) { return x.rows && x.rows.length; }))) {
      html += '<div class="row" style="margin-top:6px"><button data-go="home">🏠 ' + esc(t('ma_tab_home')) + '</button></div>';
    }
    if (r.bot_link) { html += '<button class="ghost" id="br-bot">🤖 ' + esc(t('ma_br_in_bot')) + '</button>'; }
    $('br-body').innerHTML = html;
    br.state = r.state || null;
    $('br-input').style.display = br.state ? '' : 'none';
    $('br-text').value = '';
    if ($('br-bot')) { $('br-bot').onclick = function () { openBot(); }; }
    window.scrollTo(0, 0);
  }
  function brCall(arg, push) {
    if (br.busy) { return; }
    if (arg && arg.d) { br.lastArg = arg; }
    br.busy = true;
    $('br-body').insertAdjacentHTML('afterbegin', '<div class="empty slim" id="br-spin"><span class="spin">⏳</span></div>');
    api('bridge', arg).then(function (r) {
      br.busy = false;
      var sp = $('br-spin'); if (sp) { sp.remove(); }
      if (!r.ok) { toast(errText(r)); return; }
      if (push !== false) { br.stack.push(r); }
      brRender(r);
      if (arg && arg.d && /^lang:/.test(arg.d)) { loadMe(); } // botdagi til tanlovi — Mini App ham darhol o'sha tilga
      haptic();
    });
  }
  function brOpen(d, titleKey, navName) {
    br.stack = []; br.nav = navName || 'home'; br.title = titleKey;
    if (cur === 'bot') { brLeave(); }
    cur = 'bot';
    document.querySelectorAll('.page').forEach(function (p) { p.classList.toggle('on', p.id === 'p-bot'); });
    $('br-title').textContent = t(titleKey);
    $('br-body').innerHTML = '';
    centerNav(br.nav);
    if (tg && tg.BackButton) { tg.BackButton.show(); }
    brCall({d: d});
  }
  function brBack() { br.stack.pop(); brRender(br.stack[br.stack.length - 1]); }
  function brLeave() { if (br.state) { api('bridge_reset', {}); br.state = null; } br.stack = []; loadMe(); } // bot ekranida o'zgargan narsa (yangi kanal, tarif, til) Mini App'ga ham tushsin
  $('br-back').onclick = function () { haptic(); if (br.stack.length > 1) { brBack(); } else { go('home'); } };
  $('br-send').onclick = function () { var v = $('br-text').value.trim(); if (v) { brCall({t: v}); } };
  $('br-text').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); $('br-send').click(); } });
  // bot tugmalari: Mini App'ning o'z bo'limiga yo'naltiriladiganlar
  var BR_MAP = {'m:home': 'home', 'p:new': 'post', 'q:list': 'queue', 'pl:show': 'plans', 'mk:market': 'market', 'set:show': 'me'};
  function brNavigate(d) {
    if (BR_MAP[d]) { go(BR_MAP[d]); return true; }
    if (d === 's:list') { go('queue', {seg: 'sent'}); return true; }
    if (/^p:/.test(d)) { go('post'); return true; }
    return false;
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-bd]');
    if (b) { e.preventDefault(); var d = b.getAttribute('data-bd'); if (!brNavigate(d)) { brCall({d: d}); } return; }
    var o = e.target.closest('[data-br]');
    if (o) { e.preventDefault(); haptic(); brOpen(o.getAttribute('data-br'), o.getAttribute('data-bt') || 'ma_tab_auto', BR_NAV[o.getAttribute('data-br')] || (cur === 'me' ? 'me' : cur === 'auto' ? 'auto' : 'home')); }
  });
  var BR_NAV = {'ch:list': 'channels', 'ch:add': 'channels', 'st:show': 'me'};


  // ---------- «＋»: tezkor amallar oynasi
  $('fab').onclick = function (e) {
    e.preventDefault(); haptic();
    var acts = [['post', '✍️', 'ma_qa_post', 'ma_qa_post_d'], ['ai', '✨', 'ma_qa_ai', 'ma_qa_ai_d'], ['poll:start', '📊', 'ma_au_poll', 'ma_au_poll_d'],
      ['bk:start', '📦', 'ma_au_bulk', 'ma_au_bulk_d'], ['tpl:list', '💾', 'ma_au_tpl', 'ma_au_tpl_d']];
    modal('<h3>' + esc(t('ma_qa_title')) + '</h3><div class="qa">' + acts.map(function (a) {
      return '<button class="qa-i" data-qa="' + a[0] + '" data-qt="' + a[2] + '"><i>' + a[1] + '</i><b>' + esc(t(a[2])) + '</b><span>' + esc(t(a[3])) + '</span></button>';
    }).join('') + '</div>');
    document.querySelectorAll('[data-qa]').forEach(function (b) { b.onclick = function () {
      var q = b.getAttribute('data-qa'); closeModal();
      if (q === 'post') { go('post'); } else if (q === 'ai') { go('post'); if (me && me.ai.enabled) { aiStart(); } }
      else { brOpen(q, b.getAttribute('data-qt'), 'home'); }
    }; });
  };
  // ---------- bosh sahifa: yaqin 3 ta post
  function loadUpcoming() {
    api('posts').then(function (r) {
      if (!r.ok || !r.posts.length) { $('up-card').style.display = 'none'; return; }
      $('up-card').style.display = '';
      $('up-list').innerHTML = r.posts.slice(0, 3).map(function (p) {
        var d = document.createElement('div'); d.innerHTML = p.text;
        return '<div class="up"><span class="up-t">' + esc(p.when.slice(-5)) + '<small>' + esc(p.when.slice(0, 5)) + '</small></span><span class="up-b"><b>' +
          esc((d.textContent || '').trim().slice(0, 60) || '[' + p.type + ']') + '</b><span class="muted">📢 ' + esc(p.channel) + (p.repeat ? ' · 🔄' : '') + '</span></span></div>';
      }).join('');
    });
  }
  // ---------- muharrir: yozilgan matn yo'qolmaydi (qurilmada saqlanadi)
  var DKEY = 'pa_draft_text_v1';
  function saveLocalDraft() { try { var h = $('ed').innerHTML; if (plainOf(h)) { localStorage.setItem(DKEY, h); } else { localStorage.removeItem(DKEY); } } catch (e) {} }
  $('ed').addEventListener('input', function () { clearTimeout(saveLocalDraft.t); saveLocalDraft.t = setTimeout(saveLocalDraft, 600); });
  function restoreLocalDraft() {
    try { var h = localStorage.getItem(DKEY); if (h && !plainOf($('ed').innerHTML)) { $('ed').innerHTML = h; refreshPreview(); toast(t('ma_draft_restored')); } } catch (e) {}
  }

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
      }).join('') + '<div style="margin-top:8px"><button class="small ghost" data-br="mk:my" data-bt="ma_mk_manage">⚙️ ' + esc(t('ma_mk_manage')) + '</button></div></div>' : '';
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
      html += '<div style="height:8px"></div><button class="ghost" data-br="mk:home" data-bt="ma_go_market">🤖 ' + esc(t('ma_mk_in_bot')) + '</button>' +
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

  document.addEventListener('mousedown', function (e) { if (e.target.closest('.toolbar button')) { e.preventDefault(); } });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.toolbar button'); if (!b) { return; }
    var box = b.closest('.card, .sheet'), edEl = (box && box.querySelector('.editor')) || $('ed');
    var c = b.getAttribute('data-cmd'); edEl.focus(); haptic();
    if (c === 'link') { var u = prompt(t('ma_link_ph'), 'https://'); if (u) { document.execCommand('createLink', false, u); } }
    else if (c === 'code' || c === 'quote') { wrap(c === 'code' ? 'code' : 'blockquote'); }
    else if (c === 'clear') { document.execCommand('removeFormat'); document.execCommand('unlink'); }
    else { document.execCommand(c); }
    if (edEl === $('ed')) { refreshPreview(); }
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
    $('pv-btn').innerHTML = btnRead('b-rows').map(function (r) {
      return '<div class="pbrow">' + r.map(function (b) { return '<div class="pbtn">' + esc(b.t || '…') + '</div>'; }).join('') + '</div>';
    }).join('');
    $('pv-hid').innerHTML = $('hid').value.trim() ? '<div class="pbtn">' + esc(t('ma_hidden_btn')) + '</div>' : '';
    $('pv-rx').innerHTML = state.reactions ? '<div class="rx">' + state.reactions.split(',').map(function (e) { return '<span>' + esc(e) + '</span>'; }).join('') + '</div>' : '';
  }
  // ---------- bir nechta havolali tugma: qatorlar (8 tagacha), qatorda 3 tagacha
  function btnRead(boxId) {
    var box = $(boxId); if (!box) { return []; }
    var rows = [];
    box.querySelectorAll('.bed-row').forEach(function (r) {
      var row = [];
      r.querySelectorAll('.bed-btn').forEach(function (b) {
        var t2 = b.querySelector('.bt').value.trim(), u = b.querySelector('.bu').value.trim();
        if (t2 || u) { row.push({t: t2, u: u}); }
      });
      if (row.length) { rows.push(row); }
    });
    return rows;
  }
  function btnEditor(boxId, rows, onChange) {
    var box = $(boxId); if (!box) { return; }
    rows = (rows || []).map(function (r) { return r.map(function (b) { return Array.isArray(b) ? {t: b[0], u: b[1]} : b; }); });
    var draw = function () {
      box.innerHTML = rows.map(function (r, i) {
        return '<div class="bed-row">' + r.map(function (b, j) {
          return '<div class="bed-btn"><input class="bt" maxlength="64" placeholder="' + esc(t('ma_button_text')) + '" value="' + esc(b.t || '') + '">' +
            '<input class="bu" placeholder="' + esc(t('ma_url_ph')) + '" value="' + esc(b.u || '') + '"><button class="small ghost bx" data-bx="' + i + ':' + j + '">✕</button></div>';
        }).join('') + (r.length < 3 ? '<button class="small ghost badd" data-bside="' + i + '">＋ ' + esc(t('ma_btn_side')) + '</button>' : '') + '</div>';
      }).join('') + (rows.length < 8 ? '<button class="small ghost badd" data-brow="1">＋ ' + esc(t(rows.length ? 'ma_btn_row' : 'ma_btn_add')) + '</button>' : '');
      box.querySelectorAll('input').forEach(function (inp) { inp.addEventListener('input', function () { if (onChange) { onChange(); } }); });
      box.querySelectorAll('[data-bx]').forEach(function (b) { b.onclick = function () { rows = readRaw(); var k = b.getAttribute('data-bx').split(':');
        rows[+k[0]].splice(+k[1], 1); rows = rows.filter(function (r) { return r.length; }); draw(); if (onChange) { onChange(); } }; });
      box.querySelectorAll('[data-bside]').forEach(function (b) { b.onclick = function () { rows = readRaw(); rows[+b.getAttribute('data-bside')].push({t: '', u: ''}); draw(); }; });
      box.querySelectorAll('[data-brow]').forEach(function (b) { b.onclick = function () { rows = readRaw(); rows.push([{t: '', u: ''}]); draw(); }; });
    };
    // ekrandagi (bo'sh qatorlarni ham saqlagan holda) qiymatlar
    var readRaw = function () {
      var out = [];
      box.querySelectorAll('.bed-row').forEach(function (r) {
        var row = [];
        r.querySelectorAll('.bed-btn').forEach(function (b) { row.push({t: b.querySelector('.bt').value, u: b.querySelector('.bu').value}); });
        out.push(row);
      });
      return out;
    };
    draw();
  }
  btnEditor('b-rows', [], refreshPreview);

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

  // tezkor vaqt: bir bosishda (foydalanuvchi mintaqasidagi hozirgi vaqtdan)
  function quickWhen() {
    if (!me) { return; }
    var now = new Date(me.now_local + ':00');
    var pad = function (n) { return ('0' + n).slice(-2); };
    var fmt = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()); };
    var at = function (days, h) { var d = new Date(now.getTime()); d.setDate(d.getDate() + days); d.setHours(h, 0, 0, 0); return d; };
    var opts = [['ma_q_1h', new Date(now.getTime() + 3600000)], ['ma_q_today18', at(0, 18)], ['ma_q_tom09', at(1, 9)], ['ma_q_tom18', at(1, 18)]]
      .filter(function (o) { return o[1].getTime() > now.getTime() + 60000; });
    var html = opts.map(function (o) { return '<span class="chip" data-wq="' + fmt(o[1]) + '">' + esc(t(o[0])) + '</span>'; }).join('');
    // ⭐ eng yaxshi soat (faqat o'z postlari bo'yicha aniq ma'lumot bo'lsa)
    if (bestTimeCache && bestTimeCache.data && bestTimeCache.hours.length) {
      var h0 = bestTimeCache.hours[0], bd = at(0, h0);
      if (bd.getTime() <= now.getTime() + 60000) { bd = at(1, h0); }
      html = '<span class="chip" data-wq="' + fmt(bd) + '">' + esc(t('ma_q_best', {t: ('0' + h0).slice(-2) + ':00'})) + '</span>' + html;
    } else if (bestTimeCache === null) {
      bestTimeCache = false;
      api('best_time').then(function (r) { if (r && r.ok) { bestTimeCache = r; if (r.data && $('when-box').style.display !== 'none') { quickWhen(); } } });
    }
    $('when-quick').innerHTML = html;
    document.querySelectorAll('[data-wq]').forEach(function (c) { c.onclick = function () {
      $('when').value = c.getAttribute('data-wq'); haptic();
      document.querySelectorAll('[data-wq]').forEach(function (x) { x.classList.toggle('on', x === c); });
    }; });
  }
  document.querySelectorAll('[data-when]').forEach(function (c) {
    c.onclick = function () {
      state.when = c.getAttribute('data-when');
      document.querySelectorAll('[data-when]').forEach(function (x) { x.classList.toggle('on', x === c); });
      $('when-box').style.display = state.when === 'later' ? '' : 'none';
      if (state.when === 'later') { quickWhen(); }
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
      }).join('') + bestHtml(r.best) + topHtml(r.top || []);
      if (r.best) { bestTimeCache = r.best; }
    });
  }
  // ⏰ eng yaxshi vaqt va 🏆 eng yaxshi postlar (statistika kartasida)
  var bestTimeCache = null;
  function bestHtml(b) {
    if (!b) { return ''; }
    return '<div class="st-sub"><b>⏰ ' + esc(t('ma_st_best')) + '</b><div class="chips" style="margin:6px 0">' + b.hours.map(function (h) {
      return '<span class="tag">' + ('0' + h).slice(-2) + ':00</span>';
    }).join('') + '</div><div class="muted">' + esc(b.data ? t('ma_st_best_own', {n: b.posts}) : t('ma_st_best_gen')) + '</div></div>';
  }
  function topHtml(list) {
    return '<div class="st-sub"><b>🏆 ' + esc(t('ma_st_top')) + '</b>' + (list.length ? list.map(function (p, i) {
      return '<div class="st-top"><span class="st-n">' + (i + 1) + '</span><div><div>' + esc(p.text) + '</div><div class="muted">👍 ' + p.votes + ' · 💬 ' + p.comments +
        ' · 🔒 ' + p.opens + ' — ' + esc(p.channel) + ', ' + esc(p.at) + '</div></div></div>';
    }).join('') : '<div class="muted">' + esc(t('ma_st_top_empty')) + '</div>') + '</div>';
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
  // shablon yoki «Nusxa» — muharrirni to'ldirish (bitta joy)
  function applyToEditor(d) {
    setEditor(d.text); btnEditor('b-rows', d.buttons && d.buttons.length ? d.buttons : (d.button_text ? [[[d.button_text, d.button_url || '']]] : []), refreshPreview);
    state.reactions = d.reactions || ''; renderReactions(); $('ad').value = String(d.delete_after || 0);
    state.opts = (d.options || []).slice(); renderOpts(); $('hid').value = d.hidden || '';
    state.type = d.type; state.fileId = d.file_id || ''; state.mediaUrl = '';
    if (d.type !== 'text') { $('media-box').style.display = 'flex'; $('media-add').style.display = 'none'; $('media-thumb').textContent = '🖼'; $('media-name').textContent = t('ma_media_attached'); }
    if (d.channel_ref && me && me.channels.some(function (c) { return c.id === d.channel_ref; })) { state.channel = d.channel_ref; renderChannels(); }
    refreshPreview();
  }
  $('tpl-sel').onchange = function () {
    var id = parseInt(this.value, 10); if (!id) { return; }
    api('template', {id: id}).then(function (r) {
      $('tpl-sel').value = '';
      if (!r.ok) { toast(errText(r)); return; }
      applyToEditor(r.template); haptic('ok'); toast(t('ma_tpl_loaded'));
    });
  };
  $('tpl-save').onclick = function () {
    var ask = function (name) {
      if (!name) { return; }
      var body = {name: name, type: state.type, file_id: state.fileId, text: editorHtml(), buttons: btnRead('b-rows'),
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
      buttons: btnRead('b-rows'), reactions: state.reactions,
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
      toast(msg); resetEditor(); try { localStorage.removeItem(DKEY); } catch (e) {} loadMe();
    });
  };
  function resetEditor() {
    setEditor(''); btnEditor('b-rows', [], refreshPreview); $('rep').value = ''; $('t2-box').style.display = 'none'; $('ad').value = '0';
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
  var qposts = [], qday = '';
  function loadSched() {
    $('q-list').innerHTML = '<div class="empty"><span class="spin">⏳</span></div>';
    api('posts').then(function (r) {
      if (!r.ok) { $('q-list').innerHTML = '<div class="empty">' + esc(errText(r)) + '</div>'; return; }
      qposts = r.posts; renderDays(); renderSched();
    });
  }
  // 14 kunlik lenta: har kunda nechta post borligi — bosilsa o'sha kun postlari
  function renderDays() {
    if (qseg !== 'sched') { $('q-days').innerHTML = ''; return; }
    var base = new Date((me ? me.now_local : new Date().toISOString().slice(0, 16)) + ':00'), html = '', fmt;
    var wd = t('ma_wd').split(','); // brauzerlarda o'zbekcha sana nomlari yo'q — o'zimizning 3 tilli ro'yxat
    fmt = {format: function (d) { return wd[d.getDay()] || ''; }};
    var all = '<button class="day' + (qday === '' ? ' on' : '') + '" data-day=""><small>' + esc(t('ma_all')) + '</small><b>' + qposts.length + '</b></button>';
    for (var i = 0; i < 14; i++) {
      var d = new Date(base.getTime() + i * 86400000), key = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
      var n = qposts.filter(function (p) { return p.when_local.slice(0, 10) === key; }).length;
      html += '<button class="day' + (qday === key ? ' on' : '') + (n ? ' has' : '') + '" data-day="' + key + '"><small>' + esc(i === 0 ? t('ma_today') : (fmt ? fmt.format(d) : key.slice(5))) + '</small><b>' + d.getDate() + '</b><i>' + (n ? n : '') + '</i></button>';
    }
    $('q-days').innerHTML = all + html;
    document.querySelectorAll('[data-day]').forEach(function (b) { b.onclick = function () { haptic(); qday = b.getAttribute('data-day'); renderDays(); renderSched(); }; });
  }
  function renderSched() {
    var list = qposts.filter(function (p) { return !qday || p.when_local.slice(0, 10) === qday; });
    if (!list.length) {
      $('q-list').innerHTML = '<div class="card empty"><b>📭</b>' + esc(t(qposts.length ? 'ma_q_day_empty' : 'ma_q_empty')) + '<div style="margin-top:12px"><button data-go="post">' + esc(t('ma_new_post')) + '</button></div></div>';
      return;
    }
    $('q-list').innerHTML = list.map(function (p) {
      var i = qposts.indexOf(p), d = document.createElement('div'); d.innerHTML = p.text; var plain = (d.textContent || '').trim() || '[' + p.type + ']';
      var canCopy = p.type !== 'album' && p.type !== 'poll';
      return '<div class="card post qp"><div class="body"><b>🕒 ' + esc(p.when) + '</b><div class="muted">📢 ' + esc(p.channel) + '</div>' +
        '<div class="t">' + (p.type !== 'text' ? '🖼 ' : '') + esc(plain) + '</div>' +
        (p.repeat ? '<span class="tag">🔄 ' + esc(p.repeat) + '</span>' : '') + (p.delete_after ? '<span class="tag">⏳ ' + (p.delete_after / 60) + 'h</span>' : '') +
        (p.reactions ? '<span class="tag">' + esc(p.reactions.split(',').join(' ')) + '</span>' : '') +
        '<div class="pacts"><button class="small ghost" data-edit="' + i + '">✏️ ' + esc(t('ma_edit')) + '</button>' +
        '<button class="small ghost" data-now="' + p.id + '">🚀 ' + esc(t('ma_now')) + '</button>' +
        (canCopy ? '<button class="small ghost" data-copy="' + i + '">📋</button>' : '') +
        '<button class="small ghost danger-t" data-del="' + p.id + '">🗑</button></div></div></div>';
    }).join('');
    document.querySelectorAll('[data-del]').forEach(function (b) { b.onclick = function () { askCancel(parseInt(b.getAttribute('data-del'), 10)); }; });
    document.querySelectorAll('[data-edit]').forEach(function (b) { b.onclick = function () { editPost(qposts[parseInt(b.getAttribute('data-edit'), 10)]); }; });
    document.querySelectorAll('[data-copy]').forEach(function (b) { b.onclick = function () {
      var p = qposts[parseInt(b.getAttribute('data-copy'), 10)];
      go('post'); applyToEditor({type: p.type, file_id: p.file_id, text: p.text, buttons: p.buttons || [],
        reactions: p.reactions || '', delete_after: p.delete_after || 0, options: p.options || [], hidden: p.hidden || '', channel_ref: p.channel_ref});
      haptic('ok'); toast(t('ma_copied'));
    }; });
    document.querySelectorAll('[data-now]').forEach(function (b) { b.onclick = function () {
      var id = parseInt(b.getAttribute('data-now'), 10);
      var run = function (yes) { if (!yes) { return; } b.disabled = true;
        api('post_now', {id: id}).then(function (x) { b.disabled = false; toast(x.ok ? t(x.status === 'sent' ? 'ma_sent' : 'ma_queued') : errText(x)); if (x.ok) { haptic('ok'); loadSched(); loadMe(); } }); };
      if (tg && tg.showConfirm) { tg.showConfirm(t('ma_confirm_now'), run); } else { run(confirm(t('ma_confirm_now'))); }
    }; });
    filterSearch();
  }
  // qidiruv: ko'rinib turgan ro'yxatdagi postlarni matn/kanal bo'yicha saralaydi
  function filterSearch() {
    var q = ($('q-search').value || '').trim().toLowerCase();
    document.querySelectorAll('#q-list .card.post').forEach(function (c) { c.style.display = !q || c.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none'; });
  }
  $('q-search').addEventListener('input', filterSearch);

  function askCancel(id) {
    var done = function (yes) {
      if (!yes) { return; }
      api('post_cancel', {id: id}).then(function (r) { toast(r.ok ? t('ma_cancelled') : errText(r)); if (r.ok) { haptic('ok'); loadQueue(); loadMe(); } });
    };
    if (tg && tg.showConfirm) { tg.showConfirm(t('ma_confirm_cancel'), done); } else { done(confirm(t('ma_confirm_cancel'))); }
  }
  var TOOLBAR = '<div class="toolbar"><button data-cmd="bold"><b>B</b></button><button data-cmd="italic"><i>I</i></button><button data-cmd="underline"><u>U</u></button>' +
    '<button data-cmd="strikeThrough"><s>S</s></button><button data-cmd="link">🔗</button><button data-cmd="code">&lt;/&gt;</button><button data-cmd="quote">❝</button><button data-cmd="clear">⌫</button></div>';
  var REPEATS = ['', 'daily', 'weekly', 'monthly', 'twice', 'workdays', 'interval2', 'interval3'];
  var REP_KEY = {'': 'ma_rep_none', daily: 'ma_rep_daily', weekly: 'ma_rep_weekly', monthly: 'ma_rep_monthly', twice: 'ma_rep_twice', workdays: 'ma_rep_workdays', interval2: 'ma_rep_int2', interval3: 'ma_rep_int3'};
  function plainOf(html) { var d = document.createElement('div'); d.innerHTML = String(html || ''); return (d.textContent || '').trim(); }
  function qseg_update() { document.querySelectorAll('[data-seg]').forEach(function (c) { c.classList.toggle('on', c.getAttribute('data-seg') === qseg); }); }
  function loadQueue() {
    qseg_update(); $('q-search').value = '';
    if (qseg !== 'sched') { $('q-days').innerHTML = ''; }
    if (qseg === 'sent') { return loadSent(); }
    if (qseg === 'failed') { return loadFailed(); }
    return loadSched();
  }
  document.querySelectorAll('[data-seg]').forEach(function (c) { c.onclick = function () { haptic(); qseg = c.getAttribute('data-seg'); loadQueue(); }; });
  function loadSent() {
    $('q-list').innerHTML = '<div class="empty slim"><span class="spin">⏳</span></div>';
    api('sent_list').then(function (r) {
      if (!r.ok) { $('q-list').innerHTML = '<div class="empty">' + esc(errText(r)) + '</div>'; return; }
      if (!r.items.length) { $('q-list').innerHTML = '<div class="empty slim"><b>📭</b>' + esc(t('ma_sent_empty')) + '</div>'; return; }
      $('q-list').innerHTML = r.items.map(function (m, i) {
        var pl = plainOf(m.text);
        return '<div class="card post"><div class="body"><b>✅ ' + esc(m.when) + '</b><div class="muted">📢 ' + esc(m.channel) + '</div>' +
          '<div class="t">' + (m.type !== 'text' ? '🖼 ' : '') + esc(pl || '[' + m.type + ']') + '</div>' + (m.edited ? '<span class="tag">✏️ ' + esc(t('ma_edited')) + '</span>' : '') +
          '</div><div>' + (m.editable ? '<button class="small ghost" data-se="' + i + '">✏️</button><div style="height:6px"></div>' : '') +
          '<button class="small danger" data-sd="' + m.id + '">🗑</button></div></div>';
      }).join('');
      document.querySelectorAll('[data-se]').forEach(function (b) { b.onclick = function () { editSent(r.items[parseInt(b.getAttribute('data-se'), 10)]); }; });
      document.querySelectorAll('[data-sd]').forEach(function (b) { b.onclick = function () {
        var id = parseInt(b.getAttribute('data-sd'), 10);
        var done = function (yes) { if (yes) { api('sent_delete', {id: id}).then(function (x) { toast(x.ok ? t('ma_deleted') : errText(x)); if (x.ok) { haptic('ok'); loadSent(); } }); } };
        if (tg && tg.showConfirm) { tg.showConfirm(t('ma_confirm_sent_del'), done); } else { done(confirm(t('ma_confirm_sent_del'))); }
      }; });
    });
  }
  function editSent(m) {
    modal('<h3>✏️ ' + esc(t('ma_edit_sent')) + '</h3><div class="muted" style="margin-bottom:8px">' + esc(t('ma_edit_sent_hint')) + '</div>' + TOOLBAR +
      '<div class="editor" id="ed3" contenteditable="true"></div><div class="row" style="margin-top:14px"><button class="ghost" id="e-cancel">' + esc(t('ma_back')) + '</button><button id="e-save">' + esc(t('ma_save')) + '</button></div>');
    $('ed3').innerHTML = String(m.text || '').replace(/\n/g, '<br>');
    $('e-cancel').onclick = closeModal;
    $('e-save').onclick = function () {
      var btn = this; btn.disabled = true;
      api('sent_edit', {id: m.id, text: toHtml($('ed3')).replace(/\n+$/, '')}).then(function (r) {
        btn.disabled = false;
        if (!r.ok) { toast(errText(r)); return; }
        closeModal(); toast(t('ma_saved')); haptic('ok'); loadSent();
      });
    };
  }
  function loadFailed() {
    $('q-list').innerHTML = '<div class="empty slim"><span class="spin">⏳</span></div>';
    api('failed_list').then(function (r) {
      if (!r.ok) { $('q-list').innerHTML = '<div class="empty">' + esc(errText(r)) + '</div>'; return; }
      if (!r.items.length) { $('q-list').innerHTML = '<div class="empty slim"><b>🎉</b>' + esc(t('ma_failed_empty')) + '</div>'; return; }
      $('q-list').innerHTML = r.items.map(function (p) {
        return '<div class="card post"><div class="body"><b>⚠️ ' + esc(p.when) + '</b><div class="muted">📢 ' + esc(p.channel) + '</div>' +
          '<div class="t">' + esc(plainOf(p.text) || '[' + p.type + ']') + '</div><div class="errline">' + esc(p.error || '') + '</div></div>' +
          '<div><button class="small" data-rt="' + p.id + '">↻ ' + esc(t('ma_retry')) + '</button></div></div>';
      }).join('');
      document.querySelectorAll('[data-rt]').forEach(function (b) { b.onclick = function () {
        api('post_retry', {id: parseInt(b.getAttribute('data-rt'), 10)}).then(function (x) { toast(x.ok ? t('ma_retry_ok') : errText(x)); if (x.ok) { haptic('ok'); loadFailed(); loadMe(); } });
      }; });
    });
  }
  // to'liq tahrirlash: matn va format, kanal, vaqt, takror, tugma, reaksiya, yashirin matn, sozlamalar, avto-o'chirish
  function editPost(p) {
    var ed = {opts: (p.options || []).slice(), rx: p.reactions || ''};
    var chOpts = me.channels.map(function (c) { return '<option value="' + c.id + '"' + (c.id === p.channel_ref ? ' selected' : '') + '>' + esc(c.title) + '</option>'; }).join('');
    var repOpts = REPEATS.map(function (k) { return '<option value="' + k + '"' + (k === p.repeat_key ? ' selected' : '') + '>' + esc(t(REP_KEY[k])) + '</option>'; }).join('');
    var adOpts = '<option value="0">' + esc(t('ma_ad_none')) + '</option>' + me.auto_delete.map(function (m) { return '<option value="' + m + '"' + (m === p.delete_after ? ' selected' : '') + '>' + esc(t('ma_ad_hours', {h: m / 60})) + '</option>'; }).join('');
    modal('<h3>✏️ ' + esc(t('ma_edit_post')) + '</h3>' + (p.type !== 'poll' ? TOOLBAR + '<div class="editor" id="ed2" contenteditable="true"></div>' : '<div class="muted">' + esc(t('ma_poll_text_bot')) + '</div>') +
      '<label>' + esc(t('ma_channel')) + '</label><select id="e-ch">' + chOpts + '</select>' +
      '<label>' + esc(t('ma_when')) + '</label><input type="datetime-local" id="when2" value="' + esc(p.when_local) + '">' +
      '<label>' + esc(t('ma_repeat')) + '</label><select id="e-rep">' + repOpts + '</select>' +
      '<div id="e-t2" style="display:' + (p.repeat_key === 'twice' ? '' : 'none') + '"><label>' + esc(t('ma_time2')) + '</label><input type="time" id="e-time2" value="' + esc(p.time2 || '') + '"></div>' +
      (p.type !== 'album' && p.type !== 'poll' ? '<label>🔗 ' + esc(t('ma_button')) + '</label><div class="bed" id="e-rows"></div>' : '') +
      '<label>👍 ' + esc(t('ma_reactions')) + '</label><div class="chips" id="e-rx"></div>' +
      '<label>⏳ ' + esc(t('ma_autodel')) + '</label><select id="e-ad">' + adOpts + '</select>' +
      (p.type !== 'album' ? '<label>🔒 ' + esc(t('ma_hidden')) + '</label><textarea id="e-hid" rows="2" maxlength="180">' + esc(p.hidden || '') + '</textarea>' : '') +
      '<label>⚙️ ' + esc(t('ma_opts')) + '</label><div class="chips" id="e-opts"></div>' +
      '<div class="row" style="margin-top:16px"><button class="ghost" id="e-cancel">' + esc(t('ma_back')) + '</button><button id="e-save">' + esc(t('ma_save')) + '</button></div>');
    if ($('ed2')) { $('ed2').innerHTML = String(p.text || '').replace(/\n/g, '<br>'); }
    function drawRx() {
      $('e-rx').innerHTML = [''].concat(me.reaction_sets).map(function (set) {
        return '<span class="chip' + (ed.rx === set ? ' on' : '') + '" data-erx="' + esc(set) + '">' + (set ? esc(set.split(',').join(' ')) : esc(t('ma_rx_none'))) + '</span>';
      }).join('');
      document.querySelectorAll('[data-erx]').forEach(function (c) { c.onclick = function () { ed.rx = c.getAttribute('data-erx'); drawRx(); }; });
    }
    function drawOpts() {
      $('e-opts').innerHTML = OPTS.map(function (o) { return '<span class="chip' + (ed.opts.indexOf(o) >= 0 ? ' on' : '') + '" data-eo="' + o + '">' + esc(t('ma_opt_' + o)) + '</span>'; }).join('');
      document.querySelectorAll('[data-eo]').forEach(function (c) { c.onclick = function () { var o = c.getAttribute('data-eo'), i = ed.opts.indexOf(o); if (i >= 0) { ed.opts.splice(i, 1); } else { ed.opts.push(o); } drawOpts(); }; });
    }
    drawRx(); drawOpts();
    btnEditor('e-rows', p.buttons || [], null);
    $('e-rep').onchange = function () { $('e-t2').style.display = this.value === 'twice' ? '' : 'none'; };
    $('e-cancel').onclick = closeModal;
    $('e-save').onclick = function () {
      var btn = this, body = {id: p.id, channel_id: parseInt($('e-ch').value, 10), 
        reactions: ed.rx, delete_after: parseInt($('e-ad').value, 10) || 0, options: ed.opts.join(','), repeat: $('e-rep').value};
      if ($('ed2')) { body.text = toHtml($('ed2')).replace(/\n+$/, ''); }
      if ($('e-rows')) { body.buttons = btnRead('e-rows'); }
      if ($('e-hid')) { body.hidden = $('e-hid').value.trim(); }
      if (body.repeat === 'twice') { body.time2 = $('e-time2').value; }
      if ($('when2').value && $('when2').value !== p.when_local) { body.when = $('when2').value; }
      btn.disabled = true;
      api('post_update', body).then(function (r) { btn.disabled = false; if (!r.ok) { toast(errText(r)); return; } closeModal(); toast(t('ma_saved')); haptic('ok'); loadQueue(); });
    };
  }

  // ---------- profil
  $('me-lang').onchange = function () {
    var sel = this, l = sel.value, prev = me ? me.user.lang : lang;
    sel.disabled = true;
    api('settings', {lang: l}).then(function (r) {
      sel.disabled = false;
      if (!r.ok) { sel.value = prev; toast(errText(r)); return; }
      lang = l; if (me) { me.user.lang = l; }
      // server tarjima qilgan matnlar (takror, sana, tarif) ham yangi tilda bo'lsin — hammasi qayta yuklanadi
      loadMe().then(function () { applyI18n(); refreshPage(); toast(t('ma_saved')); });
    });
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
    if ($('me-prem-tag')) { $('me-prem-tag').textContent = p.tier === 'free' ? t('ma_prem_free') : p.name + (p.expires ? ' · ' + t('ma_until', {date: p.expires.slice(0, 10)}) : ''); }
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
    // yangi foydalanuvchi uchun 3 qadamli ko'rsatma
    var step = !me.channels.length ? 1 : (me.stats.sent + me.stats.pending === 0 ? 2 : 0);
    $('start-card').style.display = step ? '' : 'none';
    ['stp1', 'stp2', 'stp3'].forEach(function (id, i) { $(id).className = i + 1 < step ? 'done' : (i + 1 === step ? 'now' : ''); });
    $('start-go').textContent = t(step === 1 ? 'ma_start_add' : 'ma_start_post');
    $('start-go').onclick = function () { if (step === 1) { brOpen('ch:add', 'ma_tab_channels', 'channels'); } else { go('post'); } };
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
        if (d.button_text) { btnEditor('b-rows', [[[d.button_text, d.button_url || '']]], refreshPreview); }
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
    go(['home', 'post', 'queue', 'auto', 'channels', 'stats', 'market', 'me', 'admin', 'plans'].indexOf(tab) >= 0 ? tab : (['home', 'post', 'queue', 'market'].indexOf(ui.start) >= 0 ? ui.start : 'home'));
    checkDraft();
  });
})();
</script>
</body>
</html>
