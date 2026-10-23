// ==================================================================
// 챕터 노드 그림 : 챕터 화면 위쪽에 카드(글 · 그림)와 카드끼리 잇는 선을 그립니다.
// - 보기 : 카드를 끌어서 가지고 놀 수 있고, 손을 놓으면 용수철처럼 튕기며 제자리로 돌아가요.
// - 운영진 편집 : 카드를 끌어 자리 옮기기 · 카드 가장자리 점을 끌어 다른 카드에 놓아 선 잇기 ·
//   선을 눌러 지우기 · 카드를 눌러 내용(위 이름 · 옆 표시 · 제목 · 글 · 그림 · 너비 · 공개 챕터) 고치기.
// 공개 전 챕터에 묶인 카드는 서버가 내용을 보내지 않아요(자리만 ???로).
// ==================================================================
const cg = { edit: false, draft: null, sel: null, off: {}, raf: 0, s: 1, drag: null };
const CG_MIN_W = 900, CG_MIN_H = 380, CG_PAD = 60, CG_SNAP = 10;
const CG_MIN_SCALE = .62;   // 좁은 화면 : 이보다 작게 줄이지 않고 옆으로 밀어서 봐요
const CG_DIR = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] };
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
       <button class="dorm-tbtn" onclick="cgCancel()"><i class="fa-solid fa-xmark"></i><span class="t">취소</span></button>
       <button class="dorm-tbtn primary" onclick="cgSave()"><i class="fa-solid fa-floppy-disk"></i><span class="t">저장</span></button>`
    : `<button class="dorm-tbtn" onclick="cgStartEdit()"><i class="fa-solid fa-diagram-project"></i><span class="t">노드 편집</span></button>`;
  const hint = cg.edit ? '<span class="sub">카드를 끌어 옮기고, 가장자리 점을 다른 카드로 끌어 선을 이어요. 선을 누르면 지워져요.</span>' : '';
  return `<div class="wm-card cg-card${cg.edit ? ' editing' : ''}"><div class="wm-h"><span class="en">Story</span>${hint}<span class="sp"></span><span class="cg-tools">${tools}</span></div>
    <div class="cg-wrap" id="cgWrap"><div class="cg-sizer" id="cgSizer"><div class="cg-stage" id="cgStage"></div></div>
      <div class="cg-empty">노드 편집에서 카드를 추가해 주세요.</div></div>
    ${cg.edit ? '<div class="cg-form" id="cgForm"></div>' : ''}</div>`;
}

function cgNodeHtml(n) {
  const lb = n.label || n.tag ? `<div class="cg-lb">${n.label ? `<b>${worldEsc(n.label)}</b>` : ''}${n.tag ? `<span>${worldEsc(n.tag)}</span>` : ''}</div>` : '';
  let box;
  if (n.locked) box = '<div class="cg-lock"><i class="fa-solid fa-lock"></i>???</div>';
  else if (n.kind === 'image') box = `<div class="cg-img"${n.image ? ` style="background-image:url('${worldEsc(n.image)}')"` : ''}>${n.image ? '' : '<i class="fa-regular fa-image"></i>'}</div>`;
  else box = `${n.title ? `<div class="cg-tt">${worldEsc(n.title)}</div>` : ''}<div class="cg-tx">${worldEsc(n.text || '') || (cg.edit ? '<em>글을 넣어 주세요</em>' : '')}</div>`;
  const ports = cg.edit ? ['l', 'r', 't', 'b'].map(s => `<span class="cg-port p-${s}" data-s="${s}"></span>`).join('') : '';
  const gate = cg.edit && n.chapter ? `<span class="cg-gate">Ch. ${n.chapter}</span>` : '';
  return `<div class="cg-node k-${n.locked ? 'lock' : n.kind}${cg.sel === n.id ? ' sel' : ''}" data-id="${n.id}" style="left:${n.x}px; top:${n.y}px; width:${n.w}px;">
    ${lb}<div class="cg-box">${box}${ports}${gate}</div></div>`;
}

// 그리기 : 카드를 놓고 크기를 잰 뒤, 무대 크기 · 배율을 맞추고 선을 그려요
function cgMount() {
  const st = document.getElementById('cgStage'); if (!st) return;
  const g = cgGraph();
  st.innerHTML = CG_LAYERS(g);
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
  cg.s = Math.max(CG_MIN_SCALE, Math.min(1, wrap.clientWidth / W));
  st.style.width = W + 'px'; st.style.height = H + 'px';
  st.style.transform = `scale(${cg.s})`;
  const sz = document.getElementById('cgSizer');
  sz.style.width = Math.ceil(W * cg.s) + 'px'; sz.style.height = Math.ceil(H * cg.s) + 'px';
  st.querySelectorAll('svg').forEach(svg => { svg.setAttribute('width', W); svg.setAttribute('height', H); });
}
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
function cgPath(p1, s1, p2, s2) {
  const d = Math.max(40, Math.hypot(p2.x - p1.x, p2.y - p1.y) * .45);
  const [ax, ay] = CG_DIR[s1], [bx, by] = s2 ? CG_DIR[s2] : [0, 0];
  return `M${p1.x},${p1.y} C${p1.x + ax * d},${p1.y + ay * d} ${p2.x + bx * d},${p2.y + by * d} ${p2.x},${p2.y}`;
}
function cgDraw() {
  const svg = document.querySelector('#cgStage .cg-svg'), dots = document.querySelector('#cgStage .cg-dots'); if (!svg || !dots) return;
  const g = cgGraph();
  let h = '', o = '';
  const dot = (p) => `<circle class="cg-dot" cx="${p.x}" cy="${p.y}" r="6"/>`;
  g.edges.forEach((e, i) => {
    const p1 = cgPort(e.a, e.as, e.at), p2 = cgPort(e.b, e.bs, e.bt); if (!p1 || !p2) return;
    const d = cgPath(p1, e.as, p2, e.bs);
    h += `<path class="cg-line" d="${d}"/>`;
    if (cg.edit) h += `<path class="cg-hit" data-i="${i}" d="${d}"/>`;
    o += dot(p1) + dot(p2);
  });
  if (cg.drag && cg.drag.type === 'link' && cg.drag.to) {
    const p1 = cgPort(cg.drag.a, cg.drag.as, .5);
    if (p1) { h += `<path class="cg-line temp" d="${cgPath(p1, cg.drag.as, cg.drag.to, null)}"/>`; o += dot(p1); }
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
  st.addEventListener('pointerdown', (e) => {
    if (e.button && e.button !== 0) return;
    const port = e.target.closest('.cg-port'), node = e.target.closest('.cg-node'), hit = e.target.closest('.cg-hit');
    if (cg.edit && hit) { cg.draft.edges.splice(+hit.dataset.i, 1); cgDraw(); return; }
    if (!node) return;
    e.preventDefault();
    const id = node.dataset.id, p = cgPt(e);
    if (cg.edit && port) cg.drag = { type: 'link', a: id, as: port.dataset.s, to: p };
    else if (cg.edit) { const n = cgNode(id); cg.drag = { type: 'move', id, p, x0: n.x, y0: n.y, moved: false }; }
    else { const o = cg.off[id] || (cg.off[id] = { x: 0, y: 0, vx: 0, vy: 0, r: 0 }); cg.drag = { type: 'play', id, p, x0: o.x, y0: o.y, last: p, t: performance.now() }; node.classList.add('held'); }
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
    // 보기 : 끌린 만큼 따라오며, 움직이는 방향으로 살짝 기울어요
    const o = cg.off[d.id], now = performance.now(), dt = Math.max(1, now - d.t) / 1000;
    o.vx = (p.x - d.last.x) / dt; o.vy = (p.y - d.last.y) / dt;
    o.x = d.x0 + p.x - d.p.x; o.y = d.y0 + p.y - d.p.y;
    o.r = Math.max(-8, Math.min(8, o.vx * .006));
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
  };
  st.addEventListener('pointerup', end); st.addEventListener('pointercancel', end);
}
// 손을 놓으면 용수철처럼 제자리로 : 살짝 지나쳤다가 돌아오는 텐션
function cgSpring() {
  if (cg.raf) return;
  let prev = performance.now();
  const K = 170, C = 11;
  const step = (now) => {
    const dt = Math.min(.032, (now - prev) / 1000); prev = now;
    let busy = false;
    Object.keys(cg.off).forEach(id => {
      if (cg.drag && cg.drag.id === id) { busy = true; return; }
      const o = cg.off[id];
      o.vx += (-K * o.x - C * o.vx) * dt; o.vy += (-K * o.y - C * o.vy) * dt;
      o.x += o.vx * dt; o.y += o.vy * dt;
      o.r = Math.max(-8, Math.min(8, o.vx * .006));
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
function cgCancel() { cg.edit = false; cg.draft = null; cg.sel = null; renderWorld(); }
function cgSave() {
  socket.emit('world_graph_save', cg.draft);
  cg.edit = false; cg.draft = null; cg.sel = null;
}
function cgAdd(kind) {
  const ns = cg.draft.nodes, k = ns.length;
  const n = { id: Math.random().toString(16).slice(2, 10), kind, label: kind === 'image' ? 'IMAGE' : '', tag: '', title: '', text: '',
    image: null, x: 40 + (k % 6) * 40, y: 40 + (k % 6) * 30, w: kind === 'image' ? 240 : 280, chapter: 0 };
  ns.push(n); cg.sel = n.id; cgMount();
}
function cgSet(key, v) {
  const n = cgNode(cg.sel); if (!n) return;
  n[key] = v;
  const keep = document.activeElement && document.activeElement.id;
  const st = document.getElementById('cgStage');
  st.innerHTML = CG_LAYERS(cg.draft);
  cgLayout(); cgDraw();
  if (key === 'kind') cgForm();
  else if (keep) { const el = document.getElementById(keep); if (el) el.focus(); }
}
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
    <div class="ops-field"><span class="lb">종류</span><select class="ops-in" onchange="cgSet('kind', this.value)"><option value="text"${n.kind === 'text' ? ' selected' : ''}>글</option><option value="image"${n.kind === 'image' ? ' selected' : ''}>그림</option></select></div>
    <div class="ops-field"><span class="lb">위 이름</span><input class="ops-in" id="cgfLabel" maxlength="30" value="${worldEsc(n.label)}" oninput="cgSet('label', this.value)"></div>
    <div class="ops-field"><span class="lb">옆 표시</span><input class="ops-in" id="cgfTag" maxlength="30" value="${worldEsc(n.tag)}" oninput="cgSet('tag', this.value)"></div>
    <div class="ops-field"><span class="lb">공개</span><select class="ops-in" onchange="cgSet('chapter', +this.value)">${chOpts}</select></div>
    ${n.kind === 'text' ? `<div class="ops-field"><span class="lb">제목</span><input class="ops-in" id="cgfTitle" maxlength="40" value="${worldEsc(n.title)}" oninput="cgSet('title', this.value)"></div>
      <div class="ops-field wide"><span class="lb">글</span><textarea class="ops-in" id="cgfText" maxlength="600" oninput="cgSet('text', this.value)">${worldEsc(n.text)}</textarea></div>`
    : `<div class="ops-field"><span class="lb">그림</span><label class="ops-btn"><i class="fa-solid fa-image"></i> 그림 올리기<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display:none" onchange="cgPickImage(this)"></label></div>`}
    <div class="ops-field"><span class="lb">너비 ${n.w}px</span><input type="range" id="cgfW" min="140" max="520" step="10" value="${n.w}" oninput="this.previousElementSibling.textContent='너비 '+this.value+'px'; cgSet('w', +this.value)"></div>
    </div><div class="ops-foot"><button class="ops-btn danger" onclick="cgDel()"><i class="fa-solid fa-trash-can"></i> 이 카드 지우기</button></div>`;
}
window.addEventListener('resize', () => { if (document.getElementById('cgStage')) { cgLayout(); cgDraw(); } });
