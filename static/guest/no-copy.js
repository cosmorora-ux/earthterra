// ==================================================================
// 복사 막기 : 사이트 글 · 그림을 복사 · 잘라내기 · 오른쪽 클릭 메뉴 · 그림 끌어 저장 ·
// 페이지 저장(Ctrl+S) · 소스 보기(Ctrl+U)로 가져가지 못하게 해요. 입력칸 안에서는 평소처럼 써요.
// 글 쓰는 화면(공지 · 편지 · 마이페이지 · 방명록 · 챕터 편집 · 운영 페이지 · LOOP 편집) 안에서는 막지 않아요.
// (화면 캡처나 개발자 도구까지 완전히 막을 수는 없어요)
// ==================================================================
const NO_COPY_FREE = '#noticeEditor, .mail-form, #myPageModal, .dorm-gb-write, #cgForm, #opsPage, #loopAdminPage';   // guest.css에도 같은 목록
(function () {
  const elOf = (n) => (n && n.nodeType === 3 ? n.parentElement : n);   // 글자(텍스트 노드)면 그 칸으로
  const free = (n) => { const el = elOf(n); return !!(el && el.closest && el.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""], ' + NO_COPY_FREE)); };
  const writing = () => free(document.activeElement) || free((getSelection() || {}).anchorNode);
  ['copy', 'cut'].forEach(type => document.addEventListener(type, (e) => {
    if (writing() || free(e.target)) return;
    e.preventDefault();
  }, true));
  document.addEventListener('selectstart', (e) => { if (!free(e.target)) e.preventDefault(); }, true);
  document.addEventListener('contextmenu', (e) => { if (!free(e.target)) e.preventDefault(); });
  document.addEventListener('dragstart', (e) => { if (free(e.target)) return; if (e.target && (e.target.tagName === 'IMG' || e.target.tagName === 'A')) e.preventDefault(); }, true);
  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = (e.key || '').toLowerCase();
    if (k === 's' || k === 'u') { e.preventDefault(); return; }
    if ((k === 'c' || k === 'x' || k === 'a') && !writing()) e.preventDefault();
  }, true);
})();
