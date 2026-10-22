// ---------- 떠 있는 스크롤 막대(PC) : 자리를 차지하지 않는 얇은 막대를 내용 위에 그려요 ----------
(function overlayScrollbars() {
  if (window.matchMedia('(hover: none) and (pointer: coarse)').matches) return;   // 휴대폰 · 태블릿은 원래 막대가 없어요
  document.documentElement.classList.add('ovs');
  const mk = cls => { const d = document.createElement('div'); d.className = 'ovs-thumb ' + cls; document.body.appendChild(d); return d; };
  let tv, th, curY = null, curX = null, hideT = null, drag = null, raf = 0;
  // 스크롤 되는 칸인지(overflow 설정)는 요소마다 한 번만 읽어 기억해요 : 마우스를 움직일 때마다 스타일을 다시 계산하지 않게
  const ovY = new WeakMap(), ovX = new WeakMap();
  const isOv = (m, n, k) => { let v = m.get(n); if (v === undefined) { v = /(auto|scroll)/.test(getComputedStyle(n)[k]); m.set(n, v); } return v; };
  const canY = n => n.scrollHeight > n.clientHeight + 1 && isOv(ovY, n, 'overflowY');
  const canX = n => n.scrollWidth > n.clientWidth + 1 && isOv(ovX, n, 'overflowX');
  const find = (t, can) => { for (let n = t; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) if (can(n)) return n; return null; };
  function place() {
    [[tv, curY, 'y'], [th, curX, 'x']].forEach(([t, el, ax]) => {
      if (!t) return;
      if (!el || !document.body.contains(el) || !(ax === 'y' ? canY(el) : canX(el))) { t.classList.remove('on'); return; }
      const r = el.getBoundingClientRect();
      if (ax === 'y') {
        const len = Math.max(28, r.height * el.clientHeight / el.scrollHeight), max = el.scrollHeight - el.clientHeight;
        t.style.height = len + 'px'; t.style.left = (r.right - 9) + 'px';
        t.style.top = (r.top + 2 + (r.height - len - 4) * (max ? el.scrollTop / max : 0)) + 'px';
      } else {
        const len = Math.max(28, r.width * el.clientWidth / el.scrollWidth), max = el.scrollWidth - el.clientWidth;
        t.style.width = len + 'px'; t.style.top = (r.bottom - 9) + 'px';
        t.style.left = (r.left + 2 + (r.width - len - 4) * (max ? el.scrollLeft / max : 0)) + 'px';
      }
    });
  }
  function show() {
    place();
    if (curY && canY(curY)) tv.classList.add('on');
    if (curX && canX(curX)) th.classList.add('on');
    clearTimeout(hideT);
    hideT = setTimeout(() => { if (drag || tv.matches(':hover') || th.matches(':hover')) return show(); tv.classList.remove('on'); th.classList.remove('on'); }, 1100);
  }
  const ready = () => { tv = mk('v'); th = mk('h');
    [tv, th].forEach((t, k) => t.addEventListener('pointerdown', e => {
      const el = k ? curX : curY; if (!el) return;
      e.preventDefault(); t.setPointerCapture(e.pointerId); t.classList.add('drag');
      drag = { k, el, p: k ? e.clientX : e.clientY, s: k ? el.scrollLeft : el.scrollTop };
    }));
    window.addEventListener('pointermove', e => {
      if (!drag) return;
      const el = drag.el, r = el.getBoundingClientRect();
      if (drag.k) { const len = parseFloat(th.style.width) || 28; el.scrollLeft = drag.s + (e.clientX - drag.p) * (el.scrollWidth - el.clientWidth) / Math.max(1, r.width - len - 4); }
      else { const len = parseFloat(tv.style.height) || 28; el.scrollTop = drag.s + (e.clientY - drag.p) * (el.scrollHeight - el.clientHeight) / Math.max(1, r.height - len - 4); }
    });
    window.addEventListener('pointerup', () => { if (!drag) return; drag = null; tv.classList.remove('drag'); th.classList.remove('drag'); show(); });
  };
  if (document.body) ready(); else document.addEventListener('DOMContentLoaded', ready);
  // 스크롤할 때 : 그 칸의 막대를 보여요
  document.addEventListener('scroll', e => {
    const el = e.target; if (!tv || !el || el.nodeType !== 1) return;
    if (canY(el)) curY = el; if (canX(el)) curX = el;
    show();
  }, true);
  // 마우스가 스크롤 되는 칸으로 들어오면 잠깐 보여 줘요(맥처럼)
  document.addEventListener('mousemove', e => {
    if (!tv || drag || raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (e.target === tv || e.target === th) return;
      const y = find(e.target, canY), x = find(e.target, canX);
      if (y !== curY || x !== curX) { curY = y; curX = x; if (y || x) show(); else { tv.classList.remove('on'); th.classList.remove('on'); } }
    });
  }, { passive: true });
  window.addEventListener('resize', place);
})();
(function setupFloatTip() {
  const tip = document.getElementById('floatTip');
  let cur = null;
  function show(el) {
    cur = el;
    const rich = el.getAttribute('data-tip-html');
    tip.classList.toggle('rich', !!rich);
    if (rich) tip.innerHTML = rich; else tip.textContent = el.getAttribute('data-tip');
    tip.style.display = 'block';
    const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, m = 8;
    const left = Math.max(m, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - m));
    let top = r.bottom + 8;
    if (top + h > window.innerHeight - m) top = Math.max(m, r.top - h - 8);  // 아래 공간이 없으면 위로
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function hide() { cur = null; tip.style.display = 'none'; }
  document.addEventListener('mouseover', (e) => {
    let el = e.target.closest && e.target.closest('[data-tip],[data-tip-html]');
    if (el && el.closest('.sidebar')) el = null;   // 메뉴 탭(사이드바 · 하단 바)에는 툴팁을 띄우지 않아요
    if (el === cur) return;
    if (el && (el.getAttribute('data-tip') || el.getAttribute('data-tip-html'))) show(el); else hide();
  });
  document.addEventListener('mousedown', hide);
  document.addEventListener('scroll', hide, true);
  setInterval(() => { if (cur && !document.body.contains(cur)) hide(); }, 500);
})();
