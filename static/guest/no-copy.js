// ==================================================================
// 복사 막기 : 사이트 글 · 그림을 복사 · 잘라내기 · 오른쪽 클릭 메뉴 · 그림 끌어 저장 ·
// 페이지 저장(Ctrl+S) · 소스 보기(Ctrl+U)로 가져가지 못하게 해요. 입력칸 안에서는 평소처럼 써요.
// (화면 캡처나 개발자 도구까지 완전히 막을 수는 없어요)
// ==================================================================
(function () {
  const editable = (el) => !!(el && el.closest && el.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]'));
  const inField = () => editable(document.activeElement);
  ['copy', 'cut'].forEach(type => document.addEventListener(type, (e) => {
    if (inField() && editable(e.target)) return;   // 내가 쓰는 입력칸 안의 글은 그대로
    e.preventDefault();
  }, true));
  document.addEventListener('selectstart', (e) => { if (!editable(e.target)) e.preventDefault(); }, true);
  document.addEventListener('contextmenu', (e) => { if (!editable(e.target)) e.preventDefault(); });
  document.addEventListener('dragstart', (e) => { if (e.target && (e.target.tagName === 'IMG' || e.target.tagName === 'A')) e.preventDefault(); }, true);
  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = (e.key || '').toLowerCase();
    if (k === 's' || k === 'u') { e.preventDefault(); return; }
    if ((k === 'c' || k === 'x' || k === 'a') && !inField()) e.preventDefault();
  }, true);
})();
