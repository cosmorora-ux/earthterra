// ==================================================================
// 피해/회복 연출 : 카드가 다시 그려질 때마다 이전 HP와 비교해서, 바뀐 카드에만
// HP 막대 잔상 · 숫자 카운트 · 떠오르는 숫자 · 흔들림/빛남을 줍니다.
// ==================================================================
var fxHpMemory = {};
var fxLastRound = null;
const FX_REDUCED = false;  // 윈도우 '애니메이션 효과' 설정과 상관없이 연출은 항상 보여줍니다.
function runHpFx(root) {
  (root || document).querySelectorAll('[data-fx]').forEach(el => {
    const key = el.dataset.fx;
    const hp = parseInt(el.dataset.hp, 10);
    if (isNaN(hp)) return;
    const prev = fxHpMemory[key];
    fxHpMemory[key] = hp;
    if (prev == null || prev === hp || FX_REDUCED) return;
    playHpFx(el, prev, hp);
  });
}
function playHpFx(el, prev, hp) {
  const delta = hp - prev;
  const fill = el.querySelector('.hpbar-fill, .hpbar-fill-sm');
  if (fill) {
    const newW = fill.style.width;
    const max = parseInt(el.dataset.max, 10) || 0;
    const oldW = max > 0 ? Math.max(0, Math.min(100, prev / max * 100)) + '%' : newW;
    if (delta < 0) {
      // 피해 : 막대는 바로 줄고, 밝은 잔상이 잠깐 남았다가 따라 줄어듭니다.
      const ghost = document.createElement('div');
      ghost.className = 'fx-hp-ghost';
      ghost.style.width = oldW;
      fill.parentNode.insertBefore(ghost, fill);
      requestAnimationFrame(() => requestAnimationFrame(() => { ghost.style.width = newW; ghost.style.opacity = '0'; }));
      setTimeout(() => ghost.remove(), 1600);
    } else {
      // 회복 : 막대가 이전 길이에서 부드럽게 차오릅니다.
      fill.style.width = oldW;
      fill.classList.add('fx-hp-grow');
      requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = newW; }));
    }
  }
  const num = el.querySelector('.hpnum, .chp-sm, .site-hp');
  if (num) countHpText(num, prev, hp);
  // 흔들림 · 숫자는 연출 순서표(fxSchedule)에서 차례가 오면 함께 나옵니다.
  // 서버가 이미 이 캐릭터에 수치(공격·회복·방어·피해 정산)를 띄웠으면 숫자는 다시 띄우지 않습니다.
  const name = (el.dataset.fx || '').replace(/^group:/, '');
  if (Date.now() - (fxRecentNumbers[name] || 0) > 2500) {
    spawnFxNumber(el, delta < 0 ? 'atk' : 'heal', delta, name);
  }
}
// 카드 위에 떠오르는 수치 + 테두리 빛 (kind : atk 빨강 / heal 노랑 / def 파랑)
// 한 캐릭터에 수치가 여러 개(누적 피해 · 방어 + 피해 등) 생기면, 옆으로 늘어놓지 않고 같은 자리에서 차례대로 하나씩 떠오릅니다.
var fxRecentNumbers = {};
const FX_NUM_GAP = 420;       // 숫자 사이 간격(ms) : 캐릭터가 달라도 하나씩 차례로
function spawnFxNumber(el, kind, value, who) {
  fxSchedule(() => {
    // 기다리는 사이 카드가 다시 그려졌으면 새 카드를 찾아 그 위에 띄웁니다.
    let target = el;
    if (!target.isConnected && el.dataset.fx) {
      const esc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
      target = [...document.querySelectorAll(`[data-fx="${esc(el.dataset.fx)}"]`)].find(e => e.getBoundingClientRect().width > 0) || el;
    }
    const flash = document.createElement('div');
    flash.className = 'fx-flash ' + kind;
    target.appendChild(flash);
    setTimeout(() => flash.remove(), 1200);
    // 맞은 순간에 맞춰 살짝 흔들림
    if (value < 0 && target.classList) { target.classList.remove('fx-hit'); void target.offsetWidth; target.classList.add('fx-hit'); setTimeout(() => target.classList.remove('fx-hit'), 400); }
    const r = target.getBoundingClientRect();
    if (!r.width || r.bottom < 0 || r.top > window.innerHeight) return;
    const f = document.createElement('div');
    f.className = 'fx-float ' + kind;
    f.textContent = (value < 0 ? '−' : '+') + Math.abs(value);
    f.style.left = (r.left + r.width / 2) + 'px';
    f.style.top = (r.top + Math.min(r.height * 0.35, 60)) + 'px';
    document.body.appendChild(f);
    setTimeout(() => f.remove(), 1300);
  }, FX_NUM_GAP, 'num');
}
// 서버가 로그에서 뽑아 보내는 수치 : [{target, kind, value}]
function fxElementFor(name) {
  const esc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s;
  // 화면에 보이는 것만(격자 전투에서는 숨겨진 작은 카드 대신 지도 칸 위에 띄웁니다)
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  let el = [...document.querySelectorAll(`[data-fx="${esc(name)}"]`)].find(shown) || null;
  if (!el) {
    const c = (lastAllForCards || []).find(k => k.name === name);
    if (c && c.boss_group) el = document.querySelector(`[data-fx="${esc('group:' + c.name.split(/[ -]/)[0])}"]`)
      || [...document.querySelectorAll('[data-fx]')].find(e => (lastAllForCards || []).some(k => k.name === e.dataset.fx && k.boss_group === c.boss_group));
    if (!el && c && c.grid_pos) {
      const cell = document.querySelector('#gridMap table.gmap') && document.querySelector('#gridMap table.gmap').rows[c.grid_pos[1]];
      el = cell && cell.cells[c.grid_pos[0]] && cell.cells[c.grid_pos[0]].querySelector('.gcell');
    }
  }
  return el;
}
socket.on('fx_numbers', (list) => {
  (list || []).forEach(n => {
    const el = fxElementFor(n.target);
    fxRecentNumbers[n.target] = Date.now();
    if (!el) return;
    spawnFxNumber(el, n.kind, n.value, n.target);  // 연출 순서표(fxSchedule)에서 하나씩 차례로
  });
});
function countHpText(node, from, to) {
  // 카드 체력처럼 <b>현재</b><span>/최대</span>로 나뉘어 있으면 굵은 숫자만 셉니다.
  if (node.querySelector('b')) node = node.querySelector('b');
  const m = node.textContent.match(/^(\d+)(\/.*)?$/);
  if (!m) return;
  const rest = m[2], t0 = performance.now(), dur = 600;
  function step(t) {
    if (!node.isConnected) return;
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    node.textContent = Math.round(from + (to - from) * e) + (rest || '');
    if (k < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
// 라운드나 선공 · 후공 차례가 바뀌면 화면 가운데에 짧게 "ROUND n" 띠가 지나갑니다(처음 접속했을 때는 띄우지 않음).
function maybeShowRoundBanner(battle) {
  const r = battle.finished ? null : battle.round_no;
  if (r == null) { fxLastRound = null; return; }
  // 라운드뿐 아니라 같은 라운드 안에서 선공 → 후공으로 넘어갈 때도 띄워요
  const key = `${r}|${battle.current_turn_team}`;
  const prev = fxLastRound;
  fxLastRound = key;
  if (prev == null || prev === key || FX_REDUCED) return;
  const sub = `${battle.round_first_team === battle.current_turn_team ? '선공' : '후공'} · ${battle.current_turn_team}`;
  // 앞 연출(컷인 · 숫자)이 다 끝난 뒤에 라운드 띠
  fxSchedule(() => {
    const snd = (lastSfxDefaults || {}).round;
    if (snd && snd.url && sfxVolume > 0) playSfx(snd.url, ((snd.volume != null ? snd.volume : 100) / 100) * (sfxVolume / 100));
    const el = document.createElement('div');
    el.className = 'fx-round';
    el.innerHTML = `<b>ROUND ${r}</b><span>${sub}</span>`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2000);
  }, 2100, 'round');
}
