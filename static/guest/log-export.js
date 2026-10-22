// ---- 로그 내려받기 : 채팅창 · 로그창을 그리는 바로 그 코드(fmtChat · formatLogHtml)와 이 화면의 스타일로 파일을 만듭니다 ----
// 서버는 원본 기록만 보내므로, 채팅창 · 로그창을 고치면 내려받은 파일도 자동으로 같은 모양이 됩니다.
function downloadLogs() { socket.emit('export_log', {}); }
socket.on('export_log_data', async (d) => {
  try {
    const html = await buildExportHtml(d);
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = d.filename || 'log.html';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
  } catch (e) {
    console.error(e);
    if (typeof showShopToast === 'function') showShopToast('로그 파일을 만들지 못했어요. 다시 시도해 주세요.');
  }
});
// 파일만 열어도(인터넷 없이) 보이도록 그림 · 글꼴을 파일 안에 넣습니다.
async function exportToDataUrl(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('fetch ' + url);
  const blob = await r.blob();
  return await new Promise((res, rej) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsDataURL(blob); });
}
const EXPORT_FRAME_CSS = `
  html, body { height:auto !important; overflow:auto !important; }
  body { background: var(--bg); }
  .xwrap { max-width:780px; margin:0 auto; padding:40px 20px 80px; }
  .xhero { position:relative; overflow:hidden; border-radius:16px; border:1px solid rgba(255,255,255,.07); padding:24px 24px 20px; margin-bottom:16px;
    background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.012)), #121215; }
  .xhero::after { content:""; position:absolute; left:24px; right:24px; top:0; height:1px; background: linear-gradient(90deg, transparent, var(--point), transparent); opacity:.85; }
  .xhero .k { font-family: var(--font-title); font-size:22px; line-height:1; color:#fff; }
  .xhero h1 { font-size:24px; font-weight:800; letter-spacing:-0.02em; margin:12px 0 12px; line-height:1.25; }
  .xchips { display:flex; flex-wrap:wrap; gap:6px; }
  .xchip { display:inline-flex; align-items:center; gap:6px; padding:5px 11px; border-radius:10px; background:rgba(255,255,255,.06); color:#c9c9ce; font-size:12.5px; }
  .xtabs { position:sticky; top:0; z-index:5; display:flex; gap:4px; padding:6px; margin:0 0 16px; border-radius:16px;
    background:rgba(18,18,21,.92); border:1px solid rgba(255,255,255,.07); -webkit-backdrop-filter:blur(8px); backdrop-filter:blur(8px); }
  .xtabs a { flex:1; text-align:center; color: var(--muted); text-decoration:none; padding:9px 10px; font-size:14px; font-weight:600; border-radius:10px; white-space:nowrap; }
  .xtabs a .n { font-size:11.5px; opacity:.6; margin-left:4px; font-variant-numeric:tabular-nums; }
  .xtabs a.on { color:#fff; background:rgba(255,255,255,.09); }
  .xsec { display:none; } .xsec.on { display:block; }
  .xpanel { background:#141416; border:1px solid rgba(255,255,255,.07); border-radius:16px; padding:16px 18px; }
  .xpanel #chatLog, .xpanel #pubLog { overflow:visible !important; padding:0 !important; flex:none !important; min-height:0; }
  .xbattle { font-size:13px; color: var(--muted); font-weight:700; margin:28px 0 10px; padding-bottom:8px; border-bottom:1px solid rgba(255,255,255,.08); }
  .xbattle:first-child { margin-top:0; }
  .xempty { color: var(--muted); font-size:14px; }
  .xfoot { text-align:center; color:#55555c; font-size:12px; margin-top:28px; }
`;
const EXPORT_TAB_JS = `(function(){var t=document.querySelectorAll('.xtabs a'),s=document.querySelectorAll('.xsec');
function show(id){var f=false;s.forEach(function(x){var on=x.id===id;x.classList.toggle('on',on);if(on)f=true;});
if(!f&&s[0]){id=s[0].id;s[0].classList.add('on');}t.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+id);});}
t.forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();var id=a.getAttribute('href').slice(1);show(id);history.replaceState(null,'','#'+id);window.scrollTo({top:0});});});
show((location.hash||'').slice(1));})();`;
async function buildExportHtml(d) {
  const esc = shopEsc;
  // 1) 채팅 : 채팅창과 같은 fmtChat + 이어 쓴 글 묶기. 파일에는 삭제 · 다시 보기 버튼과 클릭 동작을 뺍니다.
  const chat = (d.chat || []).filter(e => e.category !== 'presence' && !/님이 (입장|퇴장)했습니다/.test(e.text || ''));
  const chatBox = document.createElement('div');
  chatBox.innerHTML = chat.map(fmtChat).join('');
  markChatContinuations(chatBox);
  chatBox.querySelectorAll('.chat-del, .sr-play').forEach(el => el.remove());
  chatBox.querySelectorAll('[onclick]').forEach(el => el.removeAttribute('onclick'));
  const chatCount = chat.filter(e => !['round', 'system'].includes(e.category)).length;

  // 2) 전투 로그 : 로그창과 같은 formatLogHtml. 지난 전투는 지금 화면에 없는 캐릭터가 있으므로,
  //    그 전투의 팀 정보로 잠깐 바꿔 끼워 그린 뒤 되돌립니다(라운드 결과 표의 팀 나누기 등).
  const battles = (d.battles || []).slice().reverse();
  const renderBattles = key => {
    if (!battles.length) return '<div class="xempty">기록이 없어요.</div>';
    const keep = lastAllForCards;
    try {
      return battles.map(b => {
        const teams = b.teams || {};
        const known = new Map((keep || []).map(c => [c.name, c]));
        lastAllForCards = Object.keys(teams).map(n => known.get(n) || { name: n, teamLabel: teams[n] === 'B' ? 'B' : 'A' });
        return `<div class="xbattle">${esc(b.label)}</div><div id="pubLog">${formatLogHtml(b[key] || [])}</div>`;
      }).join('');
    } finally { lastAllForCards = keep; }
  };
  const sections = [['chat', '채팅', `<div id="chatLog">${chatBox.innerHTML}</div>`, chatCount], ['battle', '전투 로그', renderBattles('public_log'), null]];
  if (d.include_operator) sections.push(['operator', '운영진 로그', renderBattles('operator_log'), null]);

  // 3) 스타일 : 이 화면의 스타일 그대로 + 파일 틀. 제목 글꼴과 프로필 그림은 파일 안에 넣습니다.
  // 화면 스타일은 static/guest/guest.css 파일이라 그 내용을 받아 와서 넣어요
  let css = '';
  try { const l = document.getElementById('guestCss'); if (l) css = await (await fetch(l.href)).text(); } catch (e) {}
  try { css = css.replace(/url\(["']?\/static\/fonts\/Baunk\.ttf["']?\)/g, `url("${await exportToDataUrl('/static/fonts/Baunk.ttf')}")`); } catch (e) {}
  css = css.replace(/url\((["']?)\/static\//g, `url($1${location.origin}/static/`);
  let body = sections.map(([k, t, h]) => `<section class="xsec" id="${k}"><div class="xpanel">${h}</div></section>`).join('');
  const urls = [...new Set([...body.matchAll(/url\(&quot;([^&]+)&quot;\)|url\('([^']+)'\)/g)].map(m => m[1] || m[2]).filter(u => u && !u.startsWith('data:')))];
  for (const u of urls) {
    try { const du = await exportToDataUrl(u); body = body.split(u).join(du); } catch (e) {}
  }
  const tabs = sections.map(([k, t, , n]) => `<a href="#${k}">${t}${n ? `<span class="n">${n}</span>` : ''}</a>`).join('');
  const point = document.documentElement.getAttribute('data-point') || '';
  return `<!doctype html><html lang="ko" data-point="${esc(point)}"><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(d.room_name || '')} 로그</title>`
    + `<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">`
    + `<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.7.2/css/all.min.css">`
    + `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=42dot+Sans:wght@300..800&display=swap">`
    + `<style>${css}${EXPORT_FRAME_CSS}</style></head><body><div class="xwrap">`
    + `<header class="xhero"><div class="k">Battle Log</div><h1>${esc(d.room_name || '')}</h1><div class="xchips">`
    + `<span class="xchip">${esc(d.battle_type_label || '')}</span><span class="xchip">${esc(d.saved_at || '')} 저장</span><span class="xchip">채팅 ${chatCount}개</span></div></header>`
    + `<nav class="xtabs">${tabs}</nav>${body}<div class="xfoot">earthterra · ${esc(d.saved_at || '')}</div></div>`
    + `<script>${EXPORT_TAB_JS}<\/script></body></html>`;
}
