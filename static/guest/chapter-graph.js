// ==================================================================
// 챕터 노드 그림 : 챕터 화면 위쪽에 카드(글 · 그림)와 카드끼리 잇는 선을 그립니다.
// - 보기 : 카드를 살짝 끌어 볼 수 있고(멀리 가지 않아요), 손을 놓으면 부드럽게 제자리로 돌아가요.
// - 운영진 편집 : 카드를 끌어 자리 옮기기 · 카드 가장자리 점을 끌어 다른 카드에 놓아 선 잇기 ·
//   선을 눌러 지우기 · 카드를 눌러 내용(위 이름 · 옆 표시 · 제목 · 글 · 그림 · 너비 · 공개 챕터) 고치기.
// 공개 전 챕터에 묶인 카드는 서버가 내용을 보내지 않아요(자리만 ???로).
// ==================================================================
const cg = { edit: false, draft: null, sel: null, off: {}, raf: 0, s: 1, z: null, drag: null, open: new Set(), viewH: null };   // z : 사용자가 고른 배율(null = 화면에 맞춰 자동, 'fit' = 전체 보기)
const CG_MIN_W = 900, CG_MIN_H = 380, CG_PAD = 60, CG_SNAP = 10;
const CG_MIN_SCALE = .62;   // 좁은 화면 : 이보다 작게 줄이지 않고 옆으로 밀어서 봐요
const CG_DIR = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] };
// 카드 색(머리 점 · 은은한 빛 · 나가는 선) : 운영진이 카드마다 골라요
const CG_ACCENTS = [['point', '포인트', 'var(--point)'], ['violet', '보라', '#8b6cff'], ['blue', '파랑', '#3b8cff'], ['green', '초록', '#3ecf6e'],
  ['pink', '분홍', '#e05bd0'], ['red', '빨강', '#ef4b5f'], ['amber', '노랑', '#e9c05b'], ['gray', '회색', '#9a9aa2']];
const cgAc = (n) => (CG_ACCENTS.find(a => a[0] === (n && n.accent)) || CG_ACCENTS[0])[2];
const CG_PULL = 56;   // 보기에서 카드를 끌 수 있는 거리(이보다 멀리는 점점 덜 따라와요)
// 선은 카드 아래, 선 끝 점은 카드 위에 그려요
const CG_LAYERS = (g) => '<svg class="cg-svg"></svg>' + g.nodes.map(cgNodeHtml).join('') + '<svg class="cg-dots"></svg>';

function cgGraph() { return cg.edit ? cg.draft : ((worldData && worldData.graph) || { nodes: [], edges: [] }); }
function cgNode(id) { return cgGraph().nodes.find(n => n.id === id); }

function worldGraphHtml() {
  const g = cgGraph(), gm = worldIsGm();
  if (!g.nodes.length && !gm) return '';
  const tools = !gm ? '' : cg.edit
    ? `<button class="dorm-tbtn" onclick="cgAdd('text')"><i class="fa-solid fa-plus"></i><span class="t">글 카드</span></button>
       <button class="dorm-tbtn" onclick="cgAdd('image')"><i class="fa-solid fa-plus"></i><span class="t">그림 카드</span></button>
       <button class="dorm-tbtn" onclick="cgAdd('timeline')"><i class="fa-solid fa-plus"></i><span class="t">타임라인 카드</span></button>
       <button class="dorm-tbtn" onclick="cgCopy()" data-tip="고른 카드 복사 (Ctrl+D)"><i class="fa-regular fa-copy"></i><span class="t">복사</span></button>
       <button class="dorm-tbtn" onclick="cgDefault()" data-tip="노드 그림을 처음 스토리로 되돌려요"><i class="fa-solid fa-book"></i><span class="t">기본 스토리</span></button>
       <button class="dorm-tbtn" onclick="cgCancel()"><i class="fa-solid fa-xmark"></i><span class="t">취소</span></button>
       <button class="dorm-tbtn primary" onclick="cgSave()"><i class="fa-solid fa-floppy-disk"></i><span class="t">저장</span></button>`
    : `<button class="dorm-tbtn" onclick="cgStartEdit()"><i class="fa-solid fa-diagram-project"></i><span class="t">노드 편집</span></button>`;
  const hint = cg.edit ? '<span class="sub">카드를 끌어 옮기고, 가장자리 점을 다른 카드로 끌어 선을 이어요. 선을 누르면 지워져요.</span>' : '';
  return `<div class="wm-card cg-card${cg.edit ? ' editing' : ''}"><div class="wm-h"><span class="en">Story</span>${hint}<span class="sp"></span><span class="cg-tools">${tools}</span></div>
    <div class="cg-view"><div class="cg-wrap" id="cgWrap"><div class="cg-sizer" id="cgSizer"><div class="cg-stage" id="cgStage"></div></div>
      <div class="cg-empty">노드 편집에서 카드를 추가해 주세요.</div></div>
      <div class="zoom-ctl cg-zoom">
        <button type="button" onclick="cgZoomBy(1 / 1.25)" data-tip="축소"><i class="fa-solid fa-magnifying-glass-minus"></i></button>
        <span class="z" id="cgZoomLabel">100%</span>
        <button type="button" onclick="cgZoomBy(1.25)" data-tip="확대"><i class="fa-solid fa-magnifying-glass-plus"></i></button>
        <button type="button" class="fit" onclick="cgZoomSet('fit')" data-tip="전체가 보이게 맞춤"><i class="fa-solid fa-expand"></i></button>
        <button type="button" onclick="cgZoomSet(null)" data-tip="원래 크기로"><i class="fa-solid fa-rotate-left"></i></button>
      </div></div>
    ${cg.edit ? '<div class="cg-form" id="cgForm"></div>' : ''}</div>`;
}

// 접기 : 긴 글 카드와 타임라인 카드는 처음에 접혀 있어요(카드를 누르면 펼치기 · 접기). 편집 중에는 늘 펼쳐 둬요
function cgFoldable(n) {
  if (!n || n.locked) return false;
  if (n.kind === 'timeline') return (n.items || []).length > 1;
  return n.kind === 'text' && ((n.text || '').length > 120 || (n.text || '').split('\n').length > 5);
}
function cgIsOpen(n) { return cg.edit || !cgFoldable(n) || cg.open.has(n.id); }
function cgNodeHtml(n) {
  const fold = cgFoldable(n) && !cg.edit, open = cgIsOpen(n);
  const ic = fold ? `<i class="fa-solid fa-chevron-down cg-fold-ic"></i>` : '';
  const hd = n.label || n.tag || n.locked || fold ? `<div class="cg-hd"><i class="pip"></i>${n.label ? `<b>${worldEsc(n.label)}</b>` : ''}${n.tag ? `<span>${worldEsc(n.tag)}</span>` : ''}${ic}</div>` : '';
  let inner;
  if (n.locked) inner = '<div class="cg-lock"><i class="fa-solid fa-lock"></i>???</div>';
  else if (n.kind === 'image') inner = `<div class="cg-img"${n.image ? ` style="background-image:url('${worldEsc(n.image)}')"` : ''}>${n.image ? '' : '<i class="fa-regular fa-image"></i>'}</div>`;
  else if (n.kind === 'timeline') {
    const its = n.items || [];
    inner = `${n.title ? `<div class="cg-tt">${worldEsc(n.title)}</div>` : ''}<div class="cg-tl${open ? '' : ' fold'}">${its.map((it, i) => `<div class="cg-ti" style="--i:${i}"><i class="dot"></i>
        ${it.head ? `<div class="h">${worldEsc(it.head)}</div>` : ''}${it.text ? `<div class="t">${worldEsc(it.text)}</div>` : ''}</div>`).join('')
      || (cg.edit ? '<div class="cg-tx"><em>단계를 넣어 주세요</em></div>' : '')}</div>${!open && its.length > 1 ? `<div class="cg-more">+${its.length - 1}</div>` : ''}`;
  } else inner = `${n.title ? `<div class="cg-tt">${worldEsc(n.title)}</div>` : ''}${n.text || cg.edit || !n.title ? `<div class="cg-tx${open ? '' : ' clamp'}">${worldEsc(n.text || '') || (cg.edit ? '<em>글을 넣어 주세요</em>' : '')}</div>` : ''}`;
  const ports = cg.edit ? ['l', 'r', 't', 'b'].map(s => `<span class="cg-port p-${s}" data-s="${s}"></span>`).join('') : '';
  const gate = cg.edit && n.chapter ? `<span class="cg-gate">Ch. ${n.chapter}</span>` : '';
  return `<div class="cg-node k-${n.locked ? 'lock' : n.kind}${cg.sel === n.id ? ' sel' : ''}${fold ? ' foldable' : ''}${fold && open ? ' open' : ''}" data-id="${n.id}" style="left:${n.x}px; top:${n.y}px; width:${n.w}px; --ac:${cgAc(n)};">
    <div class="cg-box">${hd}<div class="cg-in">${inner}</div>${ports}${gate}</div></div>`;
}
// 펼치기 · 접기 : 높이가 부드럽게 바뀌는 동안 선도 따라 그려요(타임라인은 단계가 차례로 촤라락)
function cgToggle(id) {
  const n = cgNode(id), el = document.querySelector(`#cgStage .cg-node[data-id="${id}"]`);
  if (!n || !el || !cgFoldable(n)) return;
  const h0 = el.querySelector('.cg-in').offsetHeight, opening = !cg.open.has(id);
  if (opening) cg.open.add(id); else cg.open.delete(id);
  const tmp = document.createElement('div'); tmp.innerHTML = cgNodeHtml(n).trim();
  const nw = tmp.firstChild; nw.style.transform = el.style.transform;
  el.replaceWith(nw);
  const inn = nw.querySelector('.cg-in'), h1 = inn.offsetHeight;
  if (opening) { const tl = nw.querySelector('.cg-tl'); if (tl) tl.classList.add('reveal'); }
  inn.style.height = h0 + 'px'; inn.style.overflow = 'hidden'; void inn.offsetHeight;
  inn.style.transition = 'height .38s cubic-bezier(.3,.7,.2,1)'; inn.style.height = h1 + 'px';
  const t0 = performance.now();
  const tick = (now) => { cgDraw(); if (now - t0 < 420) requestAnimationFrame(tick); else { inn.style.cssText = ''; cgLayout(); cgDraw(); } };
  requestAnimationFrame(tick);
}

// 그리기 : 카드를 놓고 크기를 잰 뒤, 무대 크기 · 배율을 맞추고 선을 그려요
function cgMount() {
  const st = document.getElementById('cgStage'); if (!st) return;
  const g = cgGraph();
  st.innerHTML = CG_LAYERS(g); cg.viewH = null;
  const empty = document.querySelector('#cgWrap .cg-empty'); if (empty) empty.style.display = g.nodes.length ? 'none' : '';
  cgLayout(); cgDraw(); cgBind();
  if (cg.edit) cgForm();
}
function cgLayout() {
  const wrap = document.getElementById('cgWrap'), st = document.getElementById('cgStage'); if (!wrap || !st) return;
  let W = CG_MIN_W, H = CG_MIN_H;
  st.querySelectorAll('.cg-node').forEach(el => {
    W = Math.max(W, el.offsetLeft + el.offsetWidth + CG_PAD);
    H = Math.max(H, el.offsetTop + el.offsetHeight + CG_PAD);
  });
  const cs = getComputedStyle(wrap), avail = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  // 창(블럭) 크기는 확대 · 축소와 상관없이 늘 같아요 : 기본 배율일 때의 높이(화면 70%까지)로 고정하고, 안의 카드만 커지고 작아져요
  const autoS = Math.max(CG_MIN_SCALE, Math.min(1, avail / W));
  const viewH = cg.viewH || (cg.viewH = Math.max(120, Math.min(Math.ceil(H * autoS), Math.round(window.innerHeight * .7))));
  wrap.style.height = viewH + 'px';
  cg.s = cg.z === 'fit' ? Math.min(1.5, avail / W, viewH / H) : typeof cg.z === 'number' ? cg.z : autoS;
  const zl = document.getElementById('cgZoomLabel'); if (zl) zl.textContent = Math.round(cg.s * 100) + '%';
  st.style.width = W + 'px'; st.style.height = H + 'px';
  st.style.transform = `scale(${cg.s})`;
  const sz = document.getElementById('cgSizer');
  sz.style.width = Math.ceil(W * cg.s) + 'px'; sz.style.height = Math.ceil(H * cg.s) + 'px';
  // 작게 줄였을 때는 창 가운데에
  sz.style.marginLeft = Math.max(0, (avail - W * cg.s) / 2) + 'px'; sz.style.marginTop = Math.max(0, (viewH - H * cg.s) / 2) + 'px';
  st.querySelectorAll('svg').forEach(svg => { svg.setAttribute('width', W); svg.setAttribute('height', H); });
}
// 확대 · 축소 · 전체 맞춤 · 원래 크기 : 보고 있던 가운데가 그대로 가운데에 오게 스크롤을 맞춰요
// (cx, cy) : 노드 그림 창 안의 기준점(마우스 · 두 손가락 가운데). 그 점 아래의 내용이 그대로 그 자리에 남아요
function cgZoomApply(z, cx, cy) {
  const wrap = document.getElementById('cgWrap'); if (!wrap) return;
  const pl = parseFloat(getComputedStyle(wrap).paddingLeft) || 0;
  if (cx == null) { cx = wrap.clientWidth / 2; cy = wrap.clientHeight / 2; }
  const sz = document.getElementById('cgSizer'), m = () => [parseFloat(sz.style.marginLeft) || 0, parseFloat(sz.style.marginTop) || 0];
  let [ml, mt] = m();
  const px = (wrap.scrollLeft + cx - pl - ml) / cg.s, py = (wrap.scrollTop + cy - mt) / cg.s;
  cg.z = z; cgLayout(); cgDraw();
  [ml, mt] = m();
  wrap.scrollLeft = px * cg.s - cx + pl + ml; wrap.scrollTop = py * cg.s - cy + mt;
}
const cgClampZ = (z) => Math.max(.25, Math.min(2.5, Math.round(z * 100) / 100));
function cgZoomBy(k, cx, cy) { cgZoomApply(cgClampZ(cg.s * k), cx, cy); }
function cgZoomSet(z) { cgZoomApply(z); }
// 카드 상자(위 이름 빼고)의 무대 좌표 사각형 : 끌고 있는 만큼(off)도 더해요
function cgBoxRect(id) {
  const el = document.querySelector(`#cgStage .cg-node[data-id="${id}"]`); if (!el) return null;
  const box = el.querySelector('.cg-box'), o = cg.off[id] || { x: 0, y: 0 };
  return { x: el.offsetLeft + box.offsetLeft + o.x, y: el.offsetTop + box.offsetTop + o.y, w: box.offsetWidth, h: box.offsetHeight };
}
function cgPort(id, side, t) {
  const r = cgBoxRect(id); if (!r) return null;
  if (side === 'l') return { x: r.x, y: r.y + r.h * t };
  if (side === 'r') return { x: r.x + r.w, y: r.y + r.h * t };
  if (side === 't') return { x: r.x + r.w * t, y: r.y };
  return { x: r.x + r.w * t, y: r.y + r.h };
}
// 선 : 카드 면에서 곧게 나와 직각으로 꺾이는 길(모서리는 둥글게)
function cgPath(p1, s1, p2, s2) {
  const O = 22, n1 = CG_DIR[s1], n2 = s2 ? CG_DIR[s2] : null;
  const a = { x: p1.x + n1[0] * O, y: p1.y + n1[1] * O }, b = n2 ? { x: p2.x + n2[0] * O, y: p2.y + n2[1] * O } : p2;
  const h1 = !!n1[0], h2 = n2 ? !!n2[0] : h1;
  const pts = [p1, a];
  if (h1 && h2) { const mx = (a.x + b.x) / 2; pts.push({ x: mx, y: a.y }, { x: mx, y: b.y }); }
  else if (!h1 && !h2) { const my = (a.y + b.y) / 2; pts.push({ x: a.x, y: my }, { x: b.x, y: my }); }
  else if (h1) pts.push({ x: b.x, y: a.y });
  else pts.push({ x: a.x, y: b.y });
  pts.push(b); if (n2) pts.push(p2);
  // 겹친 점 · 한 줄 위의 점 정리
  const q = pts.filter((p, i) => !i || Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y) > .5);
  const r = q.filter((p, i) => i === 0 || i === q.length - 1 || Math.abs((p.x - q[i - 1].x) * (q[i + 1].y - p.y) - (p.y - q[i - 1].y) * (q[i + 1].x - p.x)) > .5);
  let d = `M${r[0].x},${r[0].y}`;
  for (let i = 1; i < r.length - 1; i++) {
    const A = r[i - 1], P = r[i], B = r[i + 1];
    const l1 = Math.hypot(P.x - A.x, P.y - A.y), l2 = Math.hypot(B.x - P.x, B.y - P.y), rad = Math.min(12, l1 / 2, l2 / 2);
    d += ` L${P.x - (P.x - A.x) / l1 * rad},${P.y - (P.y - A.y) / l1 * rad} Q${P.x},${P.y} ${P.x + (B.x - P.x) / l2 * rad},${P.y + (B.y - P.y) / l2 * rad}`;
  }
  const z = r[r.length - 1];
  return d + ` L${z.x},${z.y}`;
}
function cgDraw() {
  const svg = document.querySelector('#cgStage .cg-svg'), dots = document.querySelector('#cgStage .cg-dots'); if (!svg || !dots) return;
  const g = cgGraph();
  let h = '', o = '';
  const dot = (p) => `<circle class="cg-dot" cx="${p.x}" cy="${p.y}" r="4"/>`;
  g.edges.forEach((e, i) => {
    const p1 = cgPort(e.a, e.as, e.at), p2 = cgPort(e.b, e.bs, e.bt); if (!p1 || !p2) return;
    const d = cgPath(p1, e.as, p2, e.bs);
    h += `<path class="cg-line" style="--ac:${cgAc(cgNode(e.a))}" d="${d}"/>`;
    if (cg.edit) h += `<path class="cg-hit" data-i="${i}" d="${d}"/>`;
    o += dot(p1) + dot(p2);
  });
  if (cg.drag && cg.drag.type === 'link' && cg.drag.to) {
    const p1 = cgPort(cg.drag.a, cg.drag.as, .5);
    if (p1) { h += `<path class="cg-line temp" style="--ac:${cgAc(cgNode(cg.drag.a))}" d="${cgPath(p1, cg.drag.as, cg.drag.to, null)}"/>`; o += dot(p1); }
  }
  svg.innerHTML = h; dots.innerHTML = o;
}
// 화면 좌표 → 무대 좌표
function cgPt(e) {
  const st = document.getElementById('cgStage'), r = st.getBoundingClientRect();
  return { x: (e.clientX - r.left) / cg.s, y: (e.clientY - r.top) / cg.s };
}
function cgApplyOff(id) {
  const el = document.querySelector(`#cgStage .cg-node[data-id="${id}"]`), o = cg.off[id]; if (!el) return;
  if (!o || (!o.x && !o.y && !o.r)) { el.style.transform = ''; return; }
  el.style.transform = `translate(${o.x}px, ${o.y}px) rotate(${o.r || 0}deg)`;
}

function cgBind() {
  const st = document.getElementById('cgStage'); if (!st || st._cg) return; st._cg = true;
  cgBindPan();
  st.addEventListener('pointerdown', (e) => {
    if (e.button && e.button !== 0) return;
    const port = e.target.closest('.cg-port'), node = e.target.closest('.cg-node'), hit = e.target.closest('.cg-hit');
    if (cg.edit && hit) { cg.draft.edges.splice(+hit.dataset.i, 1); cgDraw(); return; }
    if (!node) return;
    e.preventDefault();
    const id = node.dataset.id, p = cgPt(e);
    if (cg.edit && port) cg.drag = { type: 'link', a: id, as: port.dataset.s, to: p };
    else if (cg.edit) { const n = cgNode(id); cg.drag = { type: 'move', id, p, x0: n.x, y0: n.y, moved: false }; }
    else { const o = cg.off[id] || (cg.off[id] = { x: 0, y: 0, vx: 0, vy: 0, r: 0 }); cg.drag = { type: 'play', id, p, last: p, t: performance.now(), far: 0 }; o.vx = o.vy = 0; node.classList.add('held'); }
    try { st.setPointerCapture(e.pointerId); } catch (err) {}
  });
  st.addEventListener('pointermove', (e) => {
    const d = cg.drag; if (!d) return;
    const p = cgPt(e);
    if (d.type === 'link') { d.to = p; cgDraw(); return; }
    if (d.type === 'move') {
      const dx = p.x - d.p.x, dy = p.y - d.p.y;
      if (!d.moved && Math.hypot(dx, dy) < 4) return;
      d.moved = true;
      const n = cgNode(d.id);
      n.x = Math.max(0, Math.round((d.x0 + dx) / CG_SNAP) * CG_SNAP); n.y = Math.max(0, Math.round((d.y0 + dy) / CG_SNAP) * CG_SNAP);
      const el = st.querySelector(`.cg-node[data-id="${d.id}"]`); el.style.left = n.x + 'px'; el.style.top = n.y + 'px';
      cgDraw(); return;
    }
    // 보기 : 살짝만 따라와요(멀리 끌수록 덜 따라오는 고무줄), 기울기도 아주 조금
    const o = cg.off[d.id], now = performance.now(), dt = Math.max(1, now - d.t) / 1000;
    const rub = (v) => CG_PULL * Math.tanh(v * .6 / CG_PULL);
    d.far = Math.max(d.far, Math.hypot(p.x - d.p.x, p.y - d.p.y));
    const nx = rub(p.x - d.p.x), ny = rub(p.y - d.p.y);
    o.vx = (nx - o.x) / dt; o.vy = (ny - o.y) / dt;
    o.x = nx; o.y = ny;
    o.r = Math.max(-1.5, Math.min(1.5, o.vx * .002));
    d.last = p; d.t = now;
    cgApplyOff(d.id); cgDraw();
  });
  const end = (e) => {
    const d = cg.drag; if (!d) return; cg.drag = null;
    if (d.type === 'link') {
      const el = document.elementFromPoint(e.clientX, e.clientY), tn = el && el.closest('#cgStage .cg-node');
      if (tn && tn.dataset.id !== d.a) {
        const r = cgBoxRect(tn.dataset.id), p = cgPt(e);
        // 놓은 자리에서 가장 가까운 면, 그 면 위의 위치
        const dist = { l: Math.abs(p.x - r.x), r: Math.abs(p.x - r.x - r.w), t: Math.abs(p.y - r.y), b: Math.abs(p.y - r.y - r.h) };
        const bs = Object.keys(dist).sort((a, b) => dist[a] - dist[b])[0];
        const bt = bs === 'l' || bs === 'r' ? (p.y - r.y) / r.h : (p.x - r.x) / r.w;
        cg.draft.edges.push({ a: d.a, as: d.as, at: .5, b: tn.dataset.id, bs, bt: Math.round(Math.max(.08, Math.min(.92, bt)) * 100) / 100 });
      }
      cgDraw(); return;
    }
    if (d.type === 'move') {
      if (!d.moved) { cg.sel = d.id; document.querySelectorAll('#cgStage .cg-node').forEach(n => n.classList.toggle('sel', n.dataset.id === d.id)); cgForm(); }
      else { cgLayout(); cgDraw(); }
      return;
    }
    const el = st.querySelector(`.cg-node[data-id="${d.id}"]`); if (el) el.classList.remove('held');
    cgSpring();
    if (d.far < 5) cgToggle(d.id);
  };
  st.addEventListener('pointerup', end); st.addEventListener('pointercancel', end);
}
// 빈 곳을 끌어서 둘러보기(마우스) · 휠로 확대/축소(마우스 위치 기준) · 두 손가락 벌리고 오므리기(휴대폰)
function cgBindPan() {
  const wrap = document.getElementById('cgWrap'); if (!wrap || wrap._pan) return; wrap._pan = true;
  let pan = null;
  wrap.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'mouse' || e.button !== 0 || e.target.closest('.cg-node, .cg-hit')) return;
    pan = { x: e.clientX, y: e.clientY, l: wrap.scrollLeft, t: wrap.scrollTop };
    wrap.classList.add('panning');
    try { wrap.setPointerCapture(e.pointerId); } catch (err) {}
  });
  wrap.addEventListener('pointermove', (e) => {
    if (!pan) return;
    wrap.scrollLeft = pan.l - (e.clientX - pan.x); wrap.scrollTop = pan.t - (e.clientY - pan.y);
  });
  const stop = () => { pan = null; wrap.classList.remove('panning'); };
  wrap.addEventListener('pointerup', stop); wrap.addEventListener('pointercancel', stop);
  wrap.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = wrap.getBoundingClientRect();
    cgZoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0015)), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  let pinch = null;
  const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  wrap.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 2) return;
    const r = wrap.getBoundingClientRect();
    pinch = { d: dist(e.touches), s: cg.s, cx: (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left, cy: (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top };
    if (cg.drag && cg.drag.type === 'play') { const id = cg.drag.id; cg.drag = null; cgSpring(); const el = document.querySelector(`#cgStage .cg-node[data-id="${id}"]`); if (el) el.classList.remove('held'); }
  }, { passive: true });
  wrap.addEventListener('touchmove', (e) => {
    if (!pinch || e.touches.length !== 2) return;
    e.preventDefault();
    cgZoomApply(cgClampZ(pinch.s * dist(e.touches) / pinch.d), pinch.cx, pinch.cy);
  }, { passive: false });
  const end = (e) => { if (e.touches.length < 2) pinch = null; };
  wrap.addEventListener('touchend', end); wrap.addEventListener('touchcancel', end);
}
// 손을 놓으면 부드럽게 제자리로(거의 튀지 않게)
function cgSpring() {
  if (cg.raf) return;
  let prev = performance.now();
  const K = 210, C = 25;   // 거의 튀지 않고 부드럽게 돌아와요
  const step = (now) => {
    const dt = Math.min(.032, (now - prev) / 1000); prev = now;
    let busy = false;
    Object.keys(cg.off).forEach(id => {
      if (cg.drag && cg.drag.id === id) { busy = true; return; }
      const o = cg.off[id];
      o.vx += (-K * o.x - C * o.vx) * dt; o.vy += (-K * o.y - C * o.vy) * dt;
      o.x += o.vx * dt; o.y += o.vy * dt;
      o.r = Math.max(-1.5, Math.min(1.5, o.vx * .002));
      if (Math.abs(o.x) < .3 && Math.abs(o.y) < .3 && Math.abs(o.vx) < 4 && Math.abs(o.vy) < 4) { delete cg.off[id]; cgApplyOff(id); return; }
      busy = true; cgApplyOff(id);
    });
    cgDraw();
    cg.raf = busy ? requestAnimationFrame(step) : 0;
  };
  cg.raf = requestAnimationFrame(step);
}

// ---- 운영진 편집 ----
function cgStartEdit() {
  if (!worldIsGm()) return;
  cg.draft = JSON.parse(JSON.stringify((worldData && worldData.graph) || { nodes: [], edges: [] }));
  cg.edit = true; cg.sel = null; cg.off = {}; renderWorld();
}
function cgDefault() {
  uiConfirm('지금 노드를 모두 지우고 기본 스토리(1차 · 2차 기간 · 세계 연표)로 되돌릴까요?', { title: '기본 스토리', okText: '되돌리기', danger: true }).then(ok => {
    if (!ok) return;
    socket.emit('world_graph_default');
    cg.edit = false; cg.draft = null; cg.sel = null;
  });
}
function cgCancel() { cg.edit = false; cg.draft = null; cg.sel = null; renderWorld(); }
function cgSave() {
  socket.emit('world_graph_save', cg.draft);
  cg.edit = false; cg.draft = null; cg.sel = null;
}
function cgAdd(kind) {
  const ns = cg.draft.nodes, k = ns.length;
  const n = { id: Math.random().toString(16).slice(2, 10), kind, label: kind === 'image' ? 'Image' : '', tag: '', title: '', text: '',
    image: null, x: 40 + (k % 6) * 40, y: 40 + (k % 6) * 30, w: kind === 'image' ? 240 : 300, chapter: 0, items: kind === 'timeline' ? [{ head: '01', text: '' }] : [] };
  ns.push(n); cg.sel = n.id; cgMount();
}
function cgSet(key, v) {
  const n = cgNode(cg.sel); if (!n) return;
  n[key] = v;
  if (key === 'kind' && v === 'timeline' && !(n.items || []).length) n.items = [{ head: '01', text: '' }];
  const keep = document.activeElement && document.activeElement.id;
  const st = document.getElementById('cgStage');
  st.innerHTML = CG_LAYERS(cg.draft);
  cgLayout(); cgDraw();
  if (key === 'kind') cgForm();
  else if (keep) { const el = document.getElementById(keep); if (el) el.focus(); }
}
// 고른 카드 복사 : 내용 그대로 옆 아래에 하나 더(선은 복사하지 않아요)
function cgCopy() {
  const n = cg.edit && cg.sel && cgNode(cg.sel);
  if (!n) { if (typeof uiToast === 'function') uiToast('복사할 카드를 먼저 눌러 고르세요.'); return; }
  const c = Object.assign(JSON.parse(JSON.stringify(n)), { id: Math.random().toString(16).slice(2, 10), x: n.x + 30, y: n.y + 30 });
  cg.draft.nodes.push(c); cg.sel = c.id; cgMount();
}
document.addEventListener('keydown', (e) => {
  if (!cg.edit || /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '')) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); cgCopy(); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && cg.sel) { e.preventDefault(); cgDel(); }
});
// 타임라인 단계 고치기
function cgItem(i, k, v) { const n = cgNode(cg.sel); if (!n || !n.items[i]) return; n.items[i][k] = v; cgSet('items', n.items); }
function cgItemAdd() { const n = cgNode(cg.sel); if (!n) return; n.items = n.items || []; n.items.push({ head: String(n.items.length + 1).padStart(2, '0'), text: '' }); cgSet('items', n.items); cgForm(); }
function cgItemDel(i) { const n = cgNode(cg.sel); if (!n) return; n.items.splice(i, 1); cgSet('items', n.items); cgForm(); }
function cgItemMove(i, d) { const n = cgNode(cg.sel); if (!n || !n.items[i + d]) return; [n.items[i], n.items[i + d]] = [n.items[i + d], n.items[i]]; cgSet('items', n.items); cgForm(); }
function cgDel() {
  cg.draft.nodes = cg.draft.nodes.filter(n => n.id !== cg.sel);
  cg.draft.edges = cg.draft.edges.filter(e => e.a !== cg.sel && e.b !== cg.sel);
  cg.sel = null; cgMount();
}
function cgPickImage(input) {
  const f = input.files && input.files[0]; if (!f || !cg.sel) return;
  f.arrayBuffer().then(buf => socket.emit('world_image', { filename: f.name, data: buf, for: 'node:' + cg.sel }));
  input.value = '';
}
socket.on('world_image_result', (d) => {
  if (!d.ok || !cg.edit || !String(d.for || '').startsWith('node:')) return;
  const n = cgNode(String(d.for).slice(5)); if (!n) return;
  n.image = d.url; if (n.id === cg.sel) cgSet('image', d.url); else cgMount();
});
function cgForm() {
  const box = document.getElementById('cgForm'); if (!box) return;
  const n = cg.sel && cgNode(cg.sel);
  if (!n) { box.innerHTML = '<div class="ops-hint">카드를 누르면 여기서 내용을 고칠 수 있어요.</div>'; return; }
  const chs = (worldData && worldData.chapters) || [];
  const chOpts = `<option value="0"${!n.chapter ? ' selected' : ''}>처음부터</option>` + chs.map((c, i) => `<option value="${i + 1}"${n.chapter === i + 1 ? ' selected' : ''}>Chapter ${i + 1} · ${worldEsc(c.title || '')}</option>`).join('');
  box.innerHTML = `<div class="cg-fgrid">
    <div class="ops-field"><span class="lb">종류</span><select class="ops-in" onchange="cgSet('kind', this.value)"><option value="text"${n.kind === 'text' ? ' selected' : ''}>글</option><option value="image"${n.kind === 'image' ? ' selected' : ''}>그림</option><option value="timeline"${n.kind === 'timeline' ? ' selected' : ''}>타임라인</option></select></div>
    <div class="ops-field"><span class="lb">이름</span><input class="ops-in" id="cgfLabel" maxlength="30" value="${worldEsc(n.label)}" oninput="cgSet('label', this.value)"></div>
    <div class="ops-field"><span class="lb">오른쪽 표시</span><input class="ops-in" id="cgfTag" maxlength="30" value="${worldEsc(n.tag)}" oninput="cgSet('tag', this.value)"></div>
    <div class="ops-field"><span class="lb">색</span><select class="ops-in" onchange="cgSet('accent', this.value)">${CG_ACCENTS.map(a => `<option value="${a[0]}"${(n.accent || 'point') === a[0] ? ' selected' : ''}>${a[1]}</option>`).join('')}</select></div>
    <div class="ops-field"><span class="lb">공개</span><select class="ops-in" onchange="cgSet('chapter', +this.value)">${chOpts}</select></div>
    ${n.kind === 'text' ? `<div class="ops-field"><span class="lb">제목</span><input class="ops-in" id="cgfTitle" maxlength="40" value="${worldEsc(n.title)}" oninput="cgSet('title', this.value)"></div>
      <div class="ops-field wide"><span class="lb">글</span><textarea class="ops-in" id="cgfText" maxlength="600" oninput="cgSet('text', this.value)">${worldEsc(n.text)}</textarea></div>`
    : n.kind === 'timeline' ? `<div class="ops-field"><span class="lb">제목</span><input class="ops-in" id="cgfTitle" maxlength="40" value="${worldEsc(n.title)}" oninput="cgSet('title', this.value)"></div>
      <div class="ops-field wide"><span class="lb">단계 (위에서부터 차례로)</span><div class="cg-items">${(n.items || []).map((it, i) => `<div class="cg-item">
        <input class="ops-in" id="cgfIh${i}" maxlength="40" placeholder="머리 (예: 공력 514년)" value="${worldEsc(it.head)}" oninput="cgItem(${i}, 'head', this.value)">
        <textarea class="ops-in" id="cgfIt${i}" maxlength="600" placeholder="내용" oninput="cgItem(${i}, 'text', this.value)">${worldEsc(it.text)}</textarea>
        <span class="cg-item-tools"><button class="ops-btn icon" onclick="cgItemMove(${i}, -1)" data-tip="위로"><i class="fa-solid fa-angle-up"></i></button><button class="ops-btn icon" onclick="cgItemMove(${i}, 1)" data-tip="아래로"><i class="fa-solid fa-angle-down"></i></button><button class="ops-btn icon" onclick="cgItemDel(${i})" data-tip="지우기"><i class="fa-solid fa-trash-can"></i></button></span></div>`).join('')}
        <button class="ops-btn" onclick="cgItemAdd()"><i class="fa-solid fa-plus"></i> 단계 추가</button></div></div>`
    : `<div class="ops-field"><span class="lb">그림</span><label class="ops-btn"><i class="fa-solid fa-image"></i> 그림 올리기<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display:none" onchange="cgPickImage(this)"></label></div>`}
    <div class="ops-field"><span class="lb">너비 ${n.w}px</span><input type="range" id="cgfW" min="140" max="520" step="10" value="${n.w}" oninput="this.previousElementSibling.textContent='너비 '+this.value+'px'; cgSet('w', +this.value)"></div>
    </div><div class="ops-foot"><button class="ops-btn" onclick="cgCopy()"><i class="fa-regular fa-copy"></i> 복사</button><button class="ops-btn danger" onclick="cgDel()"><i class="fa-solid fa-trash-can"></i> 이 카드 지우기</button></div>`;
}
window.addEventListener('resize', () => { if (document.getElementById('cgStage')) { cg.viewH = null; cgLayout(); cgDraw(); } });
