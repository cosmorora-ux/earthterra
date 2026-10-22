// ==================================================================
// 격자 지도 공격선 : 보스·거점이 공격하면 공격자 → 피격자로 빨간 선분을 긋고,
// 그 위로 밝은 빛줄기가 공격 방향으로 샥 지나갑니다.
// ==================================================================
// ---------- 휴대폰 격자 지도 확대 · 축소 · 맞춤 (+ 두 손가락 확대) ----------
let gridZoom = 1;
const GRID_ZOOM_MAX = 4;
function gridZoomOn() { return window.innerWidth <= 600; }
function gridZoomFrame() { return document.querySelector('#gridSection .map-frame'); }
// 화면의 (cx, cy) 지점이 확대 전후에 같은 칸을 가리키도록 스크롤을 맞춥니다.
function gridZoomTo(z, cx, cy) {
  const f = gridZoomFrame(); if (!f) return;
  z = Math.max(1, Math.min(GRID_ZOOM_MAX, z));
  if (Math.abs(z - gridZoom) < 0.01) return;
  if (cx == null) { cx = f.clientWidth / 2; cy = f.clientHeight / 2; }
  const fx = (f.scrollLeft + cx) / Math.max(1, f.scrollWidth), fy = (f.scrollTop + cy) / Math.max(1, f.scrollHeight);
  gridZoom = z;
  renderGrid(lastBattleForPanel, lastAllForCards || []);
  f.scrollLeft = fx * f.scrollWidth - cx;
  f.scrollTop = fy * f.scrollHeight - cy;
  drawAttackLines();
}
function gridZoomBy(k) { gridZoomTo(gridZoom * k); }
function gridZoomFit() {
  gridZoom = 1;
  renderGrid(lastBattleForPanel, lastAllForCards || []);
  const f = gridZoomFrame(); if (f) { f.scrollLeft = 0; f.scrollTop = 0; }
}
(function bindGridPinch() {
  const f = gridZoomFrame(); if (!f) return;
  let pinch = null, raf = 0;
  const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  f.addEventListener('touchstart', (e) => {
    if (!gridZoomOn() || e.touches.length !== 2) return;
    const r = f.getBoundingClientRect();
    pinch = { d: dist(e.touches), z: gridZoom,
      cx: (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left, cy: (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top };
  }, { passive: true });
  f.addEventListener('touchmove', (e) => {
    if (!pinch || e.touches.length !== 2) return;
    e.preventDefault();
    const z = pinch.z * dist(e.touches) / pinch.d;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => gridZoomTo(z, pinch && pinch.cx, pinch && pinch.cy));
  }, { passive: false });
  const end = (e) => { if (e.touches.length < 2) pinch = null; };
  f.addEventListener('touchend', end); f.addEventListener('touchcancel', end);
})();
window.addEventListener('resize', () => { if (!gridZoomOn() && gridZoom !== 1) gridZoomFit(); });

function gridCellCenter(frame, x, y) {
  const table = document.querySelector('#gridMap table.gmap');
  const cell = table && table.rows[y] && table.rows[y].cells[x];
  if (!cell) return null;
  const r = cell.getBoundingClientRect(), f = frame.getBoundingClientRect();
  // 확대해서 지도 틀이 스크롤된 상태여도 선이 칸에 맞도록 스크롤 양을 더합니다.
  return { x: r.left - f.left + frame.scrollLeft + r.width / 2, y: r.top - f.top + frame.scrollTop + r.height / 2 };
}
function gridCharCenter(frame, name) {
  const all = lastAllForCards || [];
  const c = all.find(k => k.name === name);
  if (!c) return null;
  // 2x2 보스는 부위 4칸의 가운데에서 선이 나갑니다.
  const parts = c.boss_group ? all.filter(k => k.boss_group === c.boss_group && k.grid_pos) : [c];
  const pts = parts.filter(k => k.grid_pos).map(k => gridCellCenter(frame, k.grid_pos[0], k.grid_pos[1])).filter(Boolean);
  if (!pts.length) return null;
  return { x: pts.reduce((a, p) => a + p.x, 0) / pts.length, y: pts.reduce((a, p) => a + p.y, 0) / pts.length };
}
// 캐릭터(보스면 그 부위) 칸의 이름 글자 상자 : 지도 틀 기준 좌표. 이름이 없으면 칸 가운데 점.
function gridNameBox(frame, name) {
  const c = (lastAllForCards || []).find(k => k.name === name);
  const table = document.querySelector('#gridMap table.gmap');
  if (!c || !c.grid_pos || !table) return null;
  const row = table.rows[c.grid_pos[1]], td = row && row.cells[c.grid_pos[0]];
  if (!td) return null;
  const el = td.querySelector('.gname') || td;
  const fr = frame.getBoundingClientRect(), r = el.getBoundingClientRect();
  const pad = 3;
  const x = r.left - fr.left + frame.scrollLeft, y = r.top - fr.top + frame.scrollTop;
  return { cx: x + r.width / 2, cy: y + r.height / 2, hw: r.width / 2 + pad, hh: r.height / 2 + pad };
}
// 상자 가운데에서 target 쪽으로 뻗은 선이 상자 가장자리를 지나는 점
function clipToBox(b, target) {
  const dx = target.x - b.cx, dy = target.y - b.cy;
  if (!dx && !dy) return { x: b.cx, y: b.cy };
  const t = Math.min(dx ? b.hw / Math.abs(dx) : Infinity, dy ? b.hh / Math.abs(dy) : Infinity);
  return t >= 1 ? { x: b.cx, y: b.cy } : { x: b.cx + dx * t, y: b.cy + dy * t };
}
function drawAttackLines() {
  const frame = document.querySelector('#gridSection .map-frame');
  if (!frame) return;
  const old = frame.querySelector('svg.atk-lines');
  if (old) old.remove();
  if (!lastAttackLines.length || !frame.offsetWidth) return;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'atk-lines');
  svg.setAttribute('width', frame.scrollWidth);
  svg.setAttribute('height', frame.scrollHeight);
  // 2x2 보스는 네 부위 이름 중 대상에 가장 가까운 글자에서 출발해 대상 이름 글자에서 끝납니다(가운데서 나오지 않게).
  // 선 끝은 글자 상자의 가장자리(서로를 향한 쪽)에 맞춰, 이름을 가리지 않고 글자에서 바로 이어져 보이게 합니다.
  atkShines = [];
  const defs = document.createElementNS(NS, 'defs');
  svg.appendChild(defs);
  lastAttackLines.forEach((l, i) => {
    const B = gridNameBox(frame, l.to);
    if (!B) return;
    const all = lastAllForCards || [];
    const atk = all.find(k => k.name === l.from);
    const names = atk && atk.boss_group ? all.filter(k => k.boss_group === atk.boss_group && k.grid_pos && k.status !== 'dead').map(k => k.name) : [l.from];
    const boxes = names.map(n => gridNameBox(frame, n)).filter(Boolean);
    if (!boxes.length) return;
    const A = boxes.reduce((best, b) => Math.hypot(b.cx - B.cx, b.cy - B.cy) < Math.hypot(best.cx - B.cx, best.cy - B.cy) ? b : best);
    const from = clipToBox(A, { x: B.cx, y: B.cy }), to = clipToBox(B, { x: A.cx, y: A.cy });
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', from.x); line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x); line.setAttribute('y2', to.y);
    line.setAttribute('class', 'atk-line');
    // 붉은 선도 양 끝으로 갈수록 투명하게 풀어져요(출발 쪽은 더 길게)
    const bg = document.createElementNS(NS, 'linearGradient');
    bg.setAttribute('id', 'atkBase' + i); bg.setAttribute('gradientUnits', 'userSpaceOnUse');
    bg.setAttribute('x1', from.x); bg.setAttribute('y1', from.y); bg.setAttribute('x2', to.x); bg.setAttribute('y2', to.y);
    [[0, 0], [.25, .7], [.85, .7], [1, .15]].forEach(([o, a]) => {
      const st = document.createElementNS(NS, 'stop');
      st.setAttribute('offset', o); st.setAttribute('stop-color', '#ff6f6f'); st.setAttribute('stop-opacity', a);
      bg.appendChild(st);
    });
    defs.appendChild(bg);
    line.setAttribute('stroke', `url(#atkBase${i})`);
    svg.appendChild(line);
    // 선 방향을 따라 움직이는 그라데이션 : 투명 → 밝은 살구빛 → 투명 창이 선 위를 미끄러져요
    const dx = to.x - from.x, dy = to.y - from.y, wx = dx * .4, wy = dy * .4, id = 'atkShine' + i;
    const g = document.createElementNS(NS, 'linearGradient');
    g.setAttribute('id', id); g.setAttribute('gradientUnits', 'userSpaceOnUse');
    g.setAttribute('x1', from.x - wx); g.setAttribute('y1', from.y - wy);
    g.setAttribute('x2', from.x); g.setAttribute('y2', from.y);
    [[0, 0], [.5, .9], [1, 0]].forEach(([o, a]) => {
      const st = document.createElementNS(NS, 'stop');
      st.setAttribute('offset', o); st.setAttribute('stop-color', '#ffe6df'); st.setAttribute('stop-opacity', a);
      g.appendChild(st);
    });
    atkShines.push({ g, x: from.x, y: from.y, dx, dy, wx, wy });
    defs.appendChild(g);
    const sh = line.cloneNode();
    sh.setAttribute('class', 'atk-shine');
    sh.setAttribute('stroke', `url(#${id})`);
    svg.appendChild(sh);
  });
  frame.appendChild(svg);
  if (atkShines.length && !atkShineRaf) atkShineRaf = requestAnimationFrame(atkShineTick);
}
// 빛 창 위치를 프레임마다 옮겨요 : 1.6초 중 앞 55%에 걸쳐 부드럽게 가속 · 감속하며 지나가고 나머지는 쉬어요.
let atkShines = [], atkShineRaf = 0;
function atkShineTick(now) {
  atkShines = atkShines.filter(s => s.g.isConnected);
  if (!atkShines.length) { atkShineRaf = 0; return; }
  const p = (now % 1600) / 1600 / .55, k = p >= 1 ? 1 : (p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
  atkShines.forEach(s => {
    const ox = (s.dx + s.wx) * k, oy = (s.dy + s.wy) * k;
    s.g.setAttribute('x1', s.x - s.wx + ox); s.g.setAttribute('y1', s.y - s.wy + oy);
    s.g.setAttribute('x2', s.x + ox); s.g.setAttribute('y2', s.y + oy);
  });
  atkShineRaf = requestAnimationFrame(atkShineTick);
}
window.addEventListener('resize', () => setTimeout(drawAttackLines, 50));
