// 마우스 클릭 물결 효과
document.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  const r = document.createElement('span');
  r.className = 'click-ripple';
  r.style.left = e.clientX + 'px';
  r.style.top = e.clientY + 'px';
  document.body.appendChild(r);
  setTimeout(() => r.remove(), 600);
}, true);

// ==================================================================
// 운영 페이지 (GM 전용) : 예전 운영진 화면의 전투 준비 · 캐릭터 등록 · 음악 · 방 설정
// - 보이는지 여부는 화면 편의일 뿐이고, 실제 권한은 서버가 GM 인증 소켓인지로 검사합니다.
// - 스탯·수식·운영진 로그는 gm_state(GM 채널)로만 오므로 러너에게는 데이터 자체가 없습니다.
// ==================================================================
const OPS_SKILLS = { "가디언": ["차폐", "편광"], "스트라이커": ["붕괴", "방출"], "메딕": ["환류", "복원"] };
const OPS_ROLES = ['가디언', '스트라이커', '메딕'];
const IS_LOUNGE = BATTLE_TYPE === 'lounge';
// 일반 룸은 전투가 없으므로 전투 준비 탭을 뺍니다.
// PLAY 룸은 전투 준비 대신 LOOP 편집(사건 · 규칙 · 문장)이 첫 탭이에요.
// PLAY 룸은 전투가 없어서 전투 준비 탭을 빼요(LOOP 편집은 사이드바의 따로 된 페이지).
// 운영 페이지는 두 가지 : 전투 관리(전투 방 · 사이드 슬라이더 / 룸 목록 연필) · 방 설정(모든 방 · 사이드 톱니바퀴)
const OPS_BATTLE_ROOM = ['pvp', 'siege', 'mass_raid'].includes(BATTLE_TYPE);
const OPS_TAB_SETS = {
  battle: [['battle', '전투 준비'], ['music', '음악'], ['bset', '전투 설정'], ['anal', '성능 분석']],
  general: [['chars', '캐릭터']].concat(OPS_BATTLE_ROOM ? [] : [['music', '음악']], [['room', '방 설정']]),
};
let opsMode = OPS_BATTLE_ROOM ? 'battle' : 'general';
let OPS_TABS = OPS_TAB_SETS[opsMode];
let opsTab = OPS_TABS[0][0];
let opsTeamA = [], opsTeamB = [];
let opsLastPublic = null;
let opsQuick = { role: '스트라이커', stats: {} };
let opsRegMode = 'quick';
let opsEditName = null;
let opsResultHtml = '';
// ==================================================================
// 전투 일정(일반 룸 '전투' 메뉴) : 운영진이 만든 전투 방을 골라 들어가요.
// 입장 가능 시간 = 시작 3시간 전 ~ 끝난 뒤 3시간. 운영진은 여기서 방 만들기 · 날짜/시간 · 배정을 해요.
// ==================================================================
let battleHub = null, battleHubT = null, battleEdit = {};
// 전투 화면(룸 목록) : 일반 룸의 '전투' 탭을 누르면 본문이 룸 목록으로 바뀌어요(형식별로 묶어서). 룸을 고르면 그 룸의 전투 화면으로.
function battleHubOpen() { return document.body.classList.contains('view-battles'); }
function openBattleHub() {
  if (document.getElementById('dormModal').style.display === 'flex') closeDorm();
  if (document.getElementById('dormModal').style.display === 'flex') return;
  closeWorldMap(true);
  if (typeof opsOpen === 'function' && opsOpen()) { document.body.classList.remove('view-ops'); document.getElementById('sidebarOpsBtn').classList.remove('active'); document.getElementById('sidebarSettingsBtn').classList.remove('active'); }
  document.body.classList.add('view-battles');
  ['sidebarBattleBtn', 'sidebarDormBtn', 'sidebarMapBtn', 'sidebarChapterBtn'].forEach(id => { const b = document.getElementById(id); if (b) b.classList.remove('active'); });
  document.getElementById('sidebarBattlesBtn').classList.add('active');
  socket.emit('battle_list'); renderBattleHub();
  clearInterval(battleHubT); battleHubT = setInterval(() => { if (battleHubOpen()) renderBattleHub(true); else clearInterval(battleHubT); }, 30000);
}
function closeBattleHub() {
  if (!battleHubOpen()) return;
  document.body.classList.remove('view-battles'); clearInterval(battleHubT);
  document.getElementById('sidebarBattlesBtn').classList.remove('active');
}
socket.on('battle_list', d => {
  battleHub = d; battleHub.offset = (d.now || Date.now() / 1000) - Date.now() / 1000;
  const dot = document.getElementById('battlesDot'); if (dot) dot.classList.toggle('on', (d.battles || []).some(b => b.mine && b.live));
  if (battleHubOpen()) renderBattleHub();
});
socket.on('joined', (d) => {
  if (IS_LOUNGE) socket.emit('battle_list');
  if (d && d.lobby_url) { window.BT_LOBBY_URL = d.lobby_url; const b = document.getElementById('btBackLobby'); if (b) b.style.display = ''; document.body.classList.add('has-lobby'); }
});
// 룸 목록의 연필 버튼(?view=ops) : 운영진 로그인이 확인되면 이 방의 운영 페이지(전투 준비)를 열어요
if (!IS_LOUNGE && new URLSearchParams(location.search).get('view') === 'ops') {
  const t0 = Date.now();
  const tryOps = () => { if (typeof opsIsGm === 'function' && opsIsGm()) { opsTab = 'battle'; openOps('battle'); } else if (Date.now() - t0 < 12000) setTimeout(tryOps, 200); };
  setTimeout(tryOps, 300);
}
// 전투 방의 메뉴 : 일반 룸과 같은 아이콘. 마이룸 · 우체통 · 지도는 일반 룸의 그 화면으로 이동해요.
function goLounge(view) { if (window.BT_LOBBY_URL) location.href = BT_LOBBY_URL.replace(/view=battles/, 'view=' + view); }
function sidebarBattleClick() {
  const busy = (typeof opsOpen === 'function' && opsOpen()) || document.body.classList.contains('view-loopadmin') || document.body.classList.contains('view-dorm')
    || document.body.classList.contains('view-map') || document.body.classList.contains('m-chat-open');
  if (document.body.classList.contains('m-chat-open')) toggleMobileChat(false);
  closeDorm(); closeOps(); if (typeof closeLoopAdmin === 'function') closeLoopAdmin(); if (!IS_LOUNGE) closeWorldMap(true);
  // 이미 전투 화면이면 룸 목록으로(일반 룸의 배틀 탭과 같은 자리)
  if (!busy && !IS_LOUNGE && BATTLE_TYPE !== 'play' && window.BT_LOBBY_URL) location.href = BT_LOBBY_URL;
}
if (!IS_LOUNGE && BATTLE_TYPE !== 'play') document.addEventListener('DOMContentLoaded', () => {
  const on = (id, fn) => { const b = document.getElementById(id); if (b) b.onclick = fn; };
  on('sidebarMapBtn', () => goLounge('map'));
  on('sidebarChapterBtn', () => goLounge('chapter'));
  on('sidebarMailBtn', () => goLounge('mail'));
  on('sidebarShopBtn', () => goLounge('shop'));
  on('newsMailRow', () => goLounge('mail'));
});
if (IS_LOUNGE && ['map', 'chapter', 'mail', 'shop', 'mydorm', 'dormmanage'].includes(new URLSearchParams(location.search).get('view'))) {
  const v = new URLSearchParams(location.search).get('view');
  const t0 = Date.now();
  const tryV = () => {
    if (!(document.getElementById('dormModal') && typeof openWorldMap === 'function')) { setTimeout(tryV, 100); return; }
    if (v === 'map' || v === 'chapter') openWorldMap(v); else if (v === 'shop') openShop(); else if (v === 'mail') openMail();
    // 내 방 · 관리는 로그인 · 마이룸 정보가 온 뒤에 열어요
    else if (dormData && (v === 'mydorm' ? dormMe() : dormIsGm())) openDormView(v === 'mydorm' ? 'mine' : 'manage');
    else if (Date.now() - t0 < 10000) setTimeout(tryV, 200);
  };
  setTimeout(tryV, 500);
}
// 전투 방에서 '룸 목록'으로 돌아오면(?view=battles) 바로 룸 목록 화면을 열어요
if (IS_LOUNGE && new URLSearchParams(location.search).get('view') === 'battles') {
  const tryOpen = () => { if (document.getElementById('dormModal')) openBattleHub(); else setTimeout(tryOpen, 100); };
  setTimeout(tryOpen, 300);
}
socket.on('battle_enter', r => {
  if (!r || !r.ok) { uiToast((r && r.message) || '들어갈 수 없어요.', 'error'); return; }
  // 지금 로그인한 캐릭터 그대로 전투 방에 들어가요
  // 배정된 방은 지금 캐릭터 그대로, 관전으로 들어가는 방은 로그인 없이 관전으로
  const n = myLoggedInName(); if (n && !r.watch) { try { localStorage.setItem('joinedName_' + r.room_id, n); } catch (e) {} }
  location.href = r.url;
});
socket.on('battle_saved', r => { if (r && r.ok) { uiToast('저장했어요.'); if (!IS_LOUNGE) socket.emit('battle_list'); } });
function btFmt(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} (${'일월화수목금토'[d.getDay()]}) ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function btLeft(sec) {
  sec = Math.max(0, Math.round(sec)); const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m}분` : `${m}분`;
}
function btLocalInput(ts) { if (!ts) return ''; const d = new Date(ts * 1000), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; }
function renderBattleHub(tickOnly) {
  const body = document.getElementById('battleHubBody'); if (!body) return;
  if (!battleHub) { body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '전투 일정을 불러오는 중이에요'); return; }
  if (tickOnly && body.querySelector(':focus')) return;   // 운영진이 입력 중이면 다시 그리지 않아요
  const now = Date.now() / 1000 + (battleHub.offset || 0), gm = battleHub.is_gm, me = myLoggedInName();
  const card = b => {
    // 일정 · 배정 없이 : 상태는 진행 중 / 종료만, 들어갈 수 있는 건 참여자(와 관전 허용 방의 관전자)
    const st = b.live ? 'open' : b.state === 'done' ? 'closed' : 'ready';
    const typeChip = `<span class="bt-chip"><i class="fa-solid ${(BT_TYPES.find(t => t[0] === b.type) || [])[2] || 'fa-shield-halved'}"></i>${mailEsc(b.type_label || '')}</span>`;
    const stChip = typeChip + (b.hidden ? '<span class="bt-chip hid"><i class="fa-solid fa-eye-slash"></i>비공개</span>' : '') + (b.live ? '<span class="bt-chip st-live"><i class="fa-solid fa-circle"></i>진행 중</span>' : st === 'closed' ? '<span class="bt-chip">종료</span>' : '');
    const can = !!b.can_enter;
    const ic = (BT_TYPES.find(t => t[0] === b.type) || [])[2] || 'fa-shield-halved';
    // 남은 시간 · 마감 · 입장 조건 문구는 표시하지 않아요(날짜 · 시간과 상태 표시만)
    // 참여자 : 동그란 프로필 사진을 겹쳐 몇 개만, 나머지는 +n. 오른쪽에 팀 인원(n:n)
    const sides = b.sides || [0, 0];
    const faces = (b.faces || []).map(f => `<span class="bt-face" data-tip="${mailEsc(f.name)}">${f.avatar ? `<img src="${mailEsc(f.avatar)}" alt="" loading="lazy" onerror="this.remove()">` : ''}</span>`).join('')
      + (b.faces_more ? `<span class="more">+${b.faces_more}</span>` : '');
    const when = (faces ? `<span class="bt-faces">${faces}</span>` : '') + (sides[0] || sides[1] ? `<span class="bt-vs">${sides[0]} : ${sides[1]}</span>` : '');
    const thumbStyle = b.thumb ? ` style="background-image:url('${mailEsc(b.thumb)}')"` : '';
    const drag = gm ? ` draggable="true" data-id="${b.id}" ondragstart="btDragStart(event)" ondragend="btDragEnd(event)" ondragover="btDragOver(event)" ondrop="btDrop(event)"` : '';
    return `<div class="bt-card ${st}${can ? ' can' : ''}${b.hidden ? ' hid' : ''}"${drag}${can ? ` onclick="socket.emit('battle_enter', {room_id:'${b.id}'})"` : ''}>
      <div class="bt-thumb${b.thumb ? ' has-img' : ''}"${thumbStyle}>${b.thumb ? '' : `<i class="fa-solid ${ic} ic"></i>`}
        <div class="bt-tags">${stChip}</div>
        ${can ? `<div class="bt-go"><i class="fa-solid ${b.watch ? 'fa-eye' : 'fa-right-to-bracket'}"></i>${b.watch ? '관전하기' : '입장하기'}</div>` : ''}</div>
      <div class="bt-foot"><div class="bt-info"><div class="bt-name">${mailEsc(b.name)}</div>${when ? `<div class="bt-when">${when}</div>` : ''}</div>
        ${gm ? `<div class="bt-icons" onclick="event.stopPropagation()"><button class="ops-btn icon" onclick="location.href = '${b.url || ''}' + '&view=ops'" data-tip="방 설정 · 일정 · 배정"><i class="fa-solid fa-pen"></i></button>
          <button class="ops-btn icon danger" onclick="battleDelete('${b.id}')" data-tip="전투 방 지우기"><i class="fa-regular fa-trash-can"></i></button></div>` : ''}</div>
      </div>`;
  };
  const list = battleHub.battles || [];
  const tools = document.getElementById('btTools'); if (tools) tools.innerHTML = '';
  const shop = btShopHtml();
  const fab = document.getElementById('btFab'); if (fab) { fab.classList.toggle('gm', !!gm); fab.classList.toggle('on', !!battleAddOpen); }
  const add = gm && battleAddOpen ? `<div class="bt-add"><select id="btNewType">${BT_TYPES.map(t => `<option value="${t[0]}">${t[1]}</option>`).join('')}</select>
      <input type="text" id="btNewName" placeholder="새 전투 이름" onkeydown="if (event.key === 'Enter') battleCreate()"><button class="btn" onclick="battleCreate()"><i class="fa-solid fa-plus"></i>전투 추가</button></div>` : '';
  // 유형별 소제목 없이 순서대로 쭉(유형은 카드의 뱃지 · 아이콘으로 구분)
  body.innerHTML = `<div class="bt-list">${shop}${add}${list.length ? `<div class="bt-grid">${list.map(card).join('')}</div>`
    : emptyHtml('fa-shield-halved', '예정된 전투가 없어요', gm ? '오른쪽 아래 + 로 전투를 추가하고, 연필에서 팀을 편성해 주세요.' : '운영진이 전투를 등록하면 여기에 보여요.')}</div>`;
}
function btShopHtml() {
  const gm = !!(battleHub && battleHub.is_gm), me = myLoggedInName();
  // 상점 바로가기 : 내 P · 소지품 개수(운영진은 처리 요청 수)
  const sd = shopCharData(me), pts = sd ? (sd.points || 0) : 0;
  const own = sd ? Object.values(sd.items || {}).reduce((a, n) => a + (n > 0 ? n : 0), 0) : 0;
  const req = gm ? (lastShopRequests || []).filter(r => !r.done).length : 0;
  const shopStats = gm ? `<span class="${req ? 'req' : ''}"><i class="fa-solid fa-inbox"></i>처리 요청 <b>${req}</b></span>`
    : me ? `<span class="pt"><i class="fa-solid fa-coins"></i><b>${pts}</b>P</span><span><i class="fa-solid fa-briefcase"></i>소지품 <b>${own}</b></span>` : '';
  return `<button type="button" class="bt-shop" id="btShop" onclick="openShop('shop')"><span class="ico"><i class="fa-solid fa-store"></i></span>
      <span class="tx"><b>Shop</b><span>${gm ? '상품 관리 · 재화 · 처리 요청' : '전투 전에 필요한 아이템을 준비하세요'}</span></span>
      ${shopStats ? `<span class="st">${shopStats}</span>` : ''}<i class="fa-solid fa-chevron-right go"></i></button>`;
}
// 운영진 : 룸 목록 카드를 끌어서 순서 바꾸기
let btDragId = null;
function btDragStart(e) { btDragId = e.currentTarget.dataset.id; e.currentTarget.classList.add('dragging'); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', btDragId); } catch (x) {} }
function btDragEnd(e) { e.currentTarget.classList.remove('dragging'); document.querySelectorAll('.bt-card.drop-l, .bt-card.drop-r').forEach(x => x.classList.remove('drop-l', 'drop-r')); btDragId = null; }
function btDragOver(e) {
  if (!btDragId) return; e.preventDefault();
  const c = e.currentTarget, r = c.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
  document.querySelectorAll('.bt-card.drop-l, .bt-card.drop-r').forEach(x => x !== c && x.classList.remove('drop-l', 'drop-r'));
  c.classList.toggle('drop-r', after); c.classList.toggle('drop-l', !after);
}
function btDrop(e) {
  e.preventDefault(); e.stopPropagation();
  const c = e.currentTarget, to = c.dataset.id, from = btDragId;
  const after = c.classList.contains('drop-r');
  c.classList.remove('drop-l', 'drop-r');
  if (!from || from === to || !battleHub) return;
  const ids = (battleHub.battles || []).map(b => b.id).filter(id => id !== from);
  ids.splice(ids.indexOf(to) + (after ? 1 : 0), 0, from);
  battleHub.battles.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));   // 바로 반영 후 서버에 저장
  renderBattleHub();
  socket.emit('battle_reorder', { ids });
}
const BT_TYPES = [['pvp', 'PVP', 'fa-user-group'], ['siege', '공성전', 'fa-chess-rook'], ['mass_raid', '마스 레이드', 'fa-dragon']];
let battleAddOpen = false;
function battleCreate() {
  const t = document.getElementById('btNewType'), n = document.getElementById('btNewName');
  if (!t || !n) return;
  socket.emit('battle_room_create', { type: t.value, name: n.value }); battleAddOpen = false;
}
function battleToggle(id, name) { const e = battleEdit[id]; const i = e.assigned.indexOf(name); if (i < 0) e.assigned.push(name); else e.assigned.splice(i, 1); if (opsOpen()) opsRenderSchedule(true); else renderBattleHub(); }
function battleSave(id) {
  const e = battleEdit[id]; const t = e.start ? new Date(e.start).getTime() / 1000 : '';
  socket.emit('battle_schedule_set', { room_id: id, name: e.name, start: t, assigned: e.assigned });
}
function battleDelete(id) {
  uiConfirm('이 전투 방을 지울까요? 진행 기록도 함께 사라져요.', { title: '전투 지우기', okText: '지우기', danger: true }).then(ok => { if (ok) { delete battleEdit[id]; socket.emit('battle_room_delete', { room_id: id }); } });
}
function opsIsGm() { return myControlInfo(lastBattleForPanel).scope === 'all'; }
function opsOpen() { return document.body.classList.contains('view-ops'); }
function opsTeamLabels() { return BATTLE_TYPE === 'pvp' ? ['Team 1', 'Team 2'] : ['Runner', 'Enemy']; }
function opsRosterDetail() { return (lastRosterDetail || []).slice(); }

function syncOpsBtn() {
  const btn = document.getElementById('sidebarOpsBtn');
  if (!btn) return;
  const gm = opsIsGm();
  btn.style.display = gm && OPS_BATTLE_ROOM ? '' : 'none';   // 전투 관리는 전투 방에서만
  const gb = document.getElementById('sidebarSettingsBtn'); if (gb) gb.style.display = gm ? '' : 'none';   // 방 설정(톱니바퀴)
  if (!gm && opsOpen()) closeOps();
  // 상점 : 메뉴의 '전투' 묶음 안에 모두에게 보여요(LOOP 방은 운영진만)
  const sb = document.getElementById('sidebarShopBtn'); if (sb) sb.style.display = (gm || BATTLE_TYPE !== 'play') ? '' : 'none';   // 상점 : 모두(LOOP 방은 운영진만)
  const dm = document.getElementById('sidebarDormManageBtn'); if (dm) dm.style.display = gm ? '' : 'none';   // 마이룸 관리 : 운영진만
  const myd = document.getElementById('sidebarMyDormBtn'); if (myd) myd.style.display = myLoggedInName() ? '' : 'none';   // 내 방 : 캐릭터로 로그인했을 때만
  const lb = document.getElementById('sidebarLoopEditBtn');
  if (lb) { lb.style.display = gm ? '' : 'none'; if (!gm && typeof closeLoopAdmin === 'function') closeLoopAdmin(); }
}
function openOps(mode) {
  if (!opsIsGm()) return;
  mode = mode === 'battle' && OPS_BATTLE_ROOM ? 'battle' : mode === 'general' || !OPS_BATTLE_ROOM ? 'general' : opsMode;
  if (mode !== opsMode || !OPS_TAB_SETS[mode].some(t => t[0] === opsTab)) { opsMode = mode; OPS_TABS = OPS_TAB_SETS[mode]; opsTab = OPS_TABS[0][0]; }
  if (typeof closeLoopAdmin === 'function') closeLoopAdmin();
  closeWorldMap(true);
  if (document.getElementById('dormModal').style.display === 'flex') closeDorm();
  if (document.getElementById('dormModal').style.display === 'flex') return;  // 꾸미기 저장 확인 중
  if (typeof closeBattleHub === 'function') closeBattleHub();
  document.body.classList.add('view-ops');
  document.getElementById('sidebarOpsBtn').classList.toggle('active', opsMode === 'battle');
  document.getElementById('sidebarSettingsBtn').classList.toggle('active', opsMode === 'general');
  const brand = document.querySelector('#opsPage .ops-brand'); if (brand) brand.textContent = opsMode === 'battle' ? 'Admin' : 'Settings';
  document.getElementById('sidebarBattleBtn').classList.remove('active');
  renderOps();
}
function closeOps() {
  if (!opsOpen()) return;
  document.getElementById('sidebarSettingsBtn').classList.remove('active');
  if (IS_LOUNGE) { document.body.classList.remove('view-ops'); document.getElementById('sidebarOpsBtn').classList.remove('active'); openDorm(); return; }
  document.body.classList.remove('view-ops');
  document.getElementById('sidebarOpsBtn').classList.remove('active');
  document.getElementById('sidebarBattleBtn').classList.toggle('active', !document.body.classList.contains('view-dorm'));
  setTimeout(() => window.dispatchEvent(new Event('resize')), 30);
}
// 일반 룸은 기숙사가 첫 화면입니다(전투 화면이 없음).
if (IS_LOUNGE) document.addEventListener('DOMContentLoaded', () => openDorm());
function setOpsTab(t) { opsTab = t; opsEditName = null; renderOps(); }

function renderOps() {
  document.getElementById('opsTabs').innerHTML = OPS_TABS.map(([k, t]) =>
    `<button class="${k === opsTab ? 'active' : ''}" onclick="setOpsTab('${k}')">${t}</button>`).join('');
  document.getElementById('opsTopSeg').textContent = (OPS_TABS.find(t => t[0] === opsTab) || [])[1] || '';
  const body = document.getElementById('opsBody');
  if (opsTab === 'battle') body.innerHTML = opsBattleHtml();
  else if (opsTab === 'chars') body.innerHTML = opsCharsHtml();
  else if (opsTab === 'music') body.innerHTML = opsMusicHtml();
  else if (opsTab === 'anal') body.innerHTML = opsAnalHtml();
  else body.innerHTML = opsRoomHtml(opsTab === 'bset' ? 'battle' : 'general');
  renderOpsData();
}
// 서버 상태가 바뀔 때는 입력칸을 건드리지 않고 목록 부분만 다시 그립니다(입력 중 포커스가 날아가지 않게).
function renderOpsData() {
  if (!opsOpen()) return;
  if (opsTab === 'battle') { opsRenderTeams(); opsRenderPool(); opsRenderLive(); }
  else if (opsTab === 'chars') { opsRenderRoster(); opsQuickRefresh(); }
  else if (opsTab === 'music') opsRenderMusicNow();
  else if (opsTab === 'room' || opsTab === 'bset') opsRenderRoomInfo();
  else if (opsTab === 'anal') opsRenderAnal();
}

// ---------- 전투 준비 ----------
function opsBattleHtml() {
  const [la, lb] = opsTeamLabels();
  return `<div id="opsLive"></div>
  <div class="ops-grid wide-left">
    <div class="ops-card">
      <h3><i class="fa-solid fa-users"></i> 팀 편성<span class="sub">${BATTLE_TYPE_LABEL} · 편성을 바꾸면 러너 화면에 미리보기로 보여요</span></h3>
      <div class="ops-teams" id="opsTeams"></div>
      <div class="ops-bar">
        <span class="ops-hint">무작위</span>
        <span class="ops-num"><em>${la}</em><input class="ops-in num" id="opsCountA" type="number" min="1" max="30" value="${OPS_DEFAULT_A}"></span>
        <span class="ops-num"><em>${lb}</em><input class="ops-in num" id="opsCountB" type="number" min="1" max="30" value="${OPS_DEFAULT_B}"></span>
        <button class="ops-btn" onclick="opsRandomAssign()"><i class="fa-solid fa-shuffle"></i> 섞어서 배치</button>
        <span style="flex:1"></span>
        <button class="ops-btn" onclick="opsClearTeams()"><i class="fa-solid fa-eraser"></i> 비우기</button>
        <button class="ops-btn primary" onclick="opsStartBattle()"><i class="fa-solid fa-flag"></i> 전투 시작</button>
      </div>
    </div>
    <div class="ops-card fit">
      <h3><i class="fa-solid fa-id-card"></i> 명단<span class="sub" id="opsPoolCount"></span></h3>
      <input class="ops-in" id="opsPoolQ" placeholder="이름 검색" autocomplete="off" oninput="opsRenderPool()">
      <div class="ops-pool" id="opsPool"></div>
    </div>
  </div>`;
}
function opsRoleColor(role) { return roleColorVar(role); }
function opsRoleOf(name) { const c = opsRosterDetail().find(r => r.name === name); return c ? c.role : ''; }
function opsChip(name, team) {
  // PVP : 한 차례 행동 횟수(NPC를 여러 번 행동하게)
  const n = ((opsLastPublic && opsLastPublic.action_counts) || {})[name] || 1;
  const acts = BATTLE_TYPE === 'pvp' ? `<select class="ops-acts ${n > 1 ? 'on' : ''}" data-tip="한 차례 행동 횟수" onchange='socket.emit("set_action_count", {name: ${JSON.stringify(name)}, count: +this.value})'>${[1, 2, 3, 4, 5].map(k => `<option value="${k}" ${k === n ? 'selected' : ''}>${k}회</option>`).join('')}</select>` : '';
  return `<span class="ops-chip" style="--rc:${opsRoleColor(opsRoleOf(name))}"><span class="dot"></span>${mailEsc(name)}${acts}
    <button onclick='opsSetTeam(${JSON.stringify(name)}, null)' data-tip="빼기"><i class="fa-solid fa-xmark"></i></button></span>`;
}
// 이미 편성해 둔 팀(미리보기) 또는 진행 중인 전투의 팀을 불러와요 : 전투 관리에 다시 들어와도 새로 짜는 것처럼 비어 보이지 않게
function opsSeedTeams() {
  if (opsTeamA.length || opsTeamB.length) return;
  const b = lastBattleForPanel, pt = lastPreviewTeams;
  if (b && !b.finished && (b.team_a || []).length) { opsTeamA = b.team_a.map(c => c.name); opsTeamB = (b.team_b || []).map(c => c.name); }
  else if (pt && ((pt.team_a || []).length || (pt.team_b || []).length)) { opsTeamA = (pt.team_a || []).slice(); opsTeamB = (pt.team_b || []).slice(); }
}
function opsRenderTeams() {
  const el = document.getElementById('opsTeams'); if (!el) return;
  opsSeedTeams();
  const known = new Set(opsRosterDetail().map(c => c.name));
  opsTeamA = opsTeamA.filter(n => known.has(n)); opsTeamB = opsTeamB.filter(n => known.has(n));
  const [la, lb] = opsTeamLabels();
  const col = (label, list) => `<div class="ops-team"><div class="ops-team-h"><span class="en">${label}</span><span class="cnt">${list.length}명</span></div>
    <div class="ops-chips">${list.length ? list.map(n => opsChip(n)).join('') : '<div class="ops-empty">명단에서 1 · 2를 눌러 골라 주세요.</div>'}</div></div>`;
  el.innerHTML = col(la, opsTeamA) + col(lb, opsTeamB);
}
function opsRenderPool() {
  const el = document.getElementById('opsPool'); if (!el) return;
  const list = opsRosterDetail();
  const q = ((document.getElementById('opsPoolQ') || {}).value || '').trim().toLowerCase();
  const shown = list.filter(c => !q || c.name.toLowerCase().includes(q))
    .sort((a, b) => (OPS_ROLES.indexOf(a.role) - OPS_ROLES.indexOf(b.role)) || a.name.localeCompare(b.name, 'ko'));
  document.getElementById('opsPoolCount').textContent = `${list.length}명`;
  if (!shown.length) { el.innerHTML = `<div class="ops-empty">${list.length ? '검색 결과가 없어요.' : '등록된 캐릭터가 없어요. 캐릭터 탭에서 등록해 주세요.'}</div>`; return; }
  el.innerHTML = shown.map(c => {
    const n = JSON.stringify(c.name);
    const inA = opsTeamA.includes(c.name), inB = opsTeamB.includes(c.name);
    return `<div class="ops-prow"><span class="nm">${mailEsc(c.name)}</span><span class="rl" style="color:${opsRoleColor(c.role)}">${mailEsc(c.role || '')}</span>
      ${c.skill ? `<span class="sk">${mailEsc(c.skill)}</span>` : ''}<span class="sp"></span>
      <button class="ops-pick ${inA ? 'on' : ''}" onclick='opsSetTeam(${n}, ${inA ? 'null' : '"a"'})' data-tip="${opsTeamLabels()[0]}">1</button>
      <button class="ops-pick ${inB ? 'on' : ''}" onclick='opsSetTeam(${n}, ${inB ? 'null' : '"b"'})' data-tip="${opsTeamLabels()[1]}">2</button></div>`;
  }).join('');
}
function opsRenderLive() {
  const el = document.getElementById('opsLive'); if (!el) return;
  const b = lastBattleForPanel;
  el.innerHTML = b && !b.finished ? `<div class="ops-live"><i class="fa-solid fa-circle-play"></i>지금 전투가 진행 중이에요 (Round ${b.round_no || '-'}). 새로 시작하면 진행 중인 전투는 끝나요.</div>` : '';
}
function opsSetTeam(name, team) {
  opsTeamA = opsTeamA.filter(n => n !== name); opsTeamB = opsTeamB.filter(n => n !== name);
  if (team === 'a') opsTeamA.push(name); else if (team === 'b') opsTeamB.push(name);
  opsSendPreview(); opsRenderTeams(); opsRenderPool();
}
function opsClearTeams() { opsTeamA = []; opsTeamB = []; opsSendPreview(); opsRenderTeams(); opsRenderPool(); }
function opsSendPreview() { socket.emit('preview_teams', { team_a: opsTeamA, team_b: opsTeamB }); }
function opsRandomAssign() {
  const na = parseInt(document.getElementById('opsCountA').value, 10) || 1;
  const nb = parseInt(document.getElementById('opsCountB').value, 10) || 1;
  const names = opsRosterDetail().map(c => c.name);
  if (names.length < na + nb) { showError(`등록된 캐릭터가 부족해요 (필요 ${na + nb}명, 지금 ${names.length}명)`); return; }
  for (let i = names.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [names[i], names[j]] = [names[j], names[i]]; }
  opsTeamA = names.slice(0, na); opsTeamB = names.slice(na, na + nb);
  opsSendPreview(); opsRenderTeams(); opsRenderPool();
}
function opsStartBattle() {
  if (!opsTeamA.length || !opsTeamB.length) { showError('양쪽 팀에 한 명 이상 있어야 해요.'); return; }
  const live = lastBattleForPanel && !lastBattleForPanel.finished;
  const go = () => { socket.emit('start_battle', { team_a: opsTeamA, team_b: opsTeamB }); closeOps(); };
  if (live) uiConfirm('진행 중인 전투를 끝내고 새 전투를 시작할까요?', { title: '전투 시작', okText: '새로 시작', danger: true }).then(ok => ok && go());
  else go();
}

// ---------- 캐릭터 ----------
function opsCharsHtml() {
  return `<div class="ops-grid">
    <div class="ops-card">
      <h3><i class="fa-solid fa-user-plus"></i> 캐릭터 등록
        <span class="sub"><span class="ops-seg"><button class="${opsRegMode === 'quick' ? 'on' : ''}" onclick="opsSetReg('quick')">간편</button><button class="${opsRegMode === 'paste' ? 'on' : ''}" onclick="opsSetReg('paste')">붙여넣기</button></span></span></h3>
      ${opsRegMode === 'quick' ? `
      <div class="ops-field"><span class="lb">이름</span><input class="ops-in" id="opsQName" maxlength="20" placeholder="캐릭터 이름" autocomplete="off" oninput="opsQuickRefresh()">
        <div class="ops-hint" id="opsQWarn" style="display:none; margin-top:6px;">이미 있는 이름이에요. 등록하면 기존 정보를 덮어써요.</div></div>
      <div class="ops-field"><span class="lb">포지션</span><div class="ops-roles" id="opsQRoles"></div></div>
      <div class="ops-row" style="margin-top:10px;">
        <div class="ops-field" style="flex:1; margin:0;"><span class="lb">스킬</span><select class="ops-in" id="opsQSkill"></select></div>
        <div class="ops-field" style="flex:1; margin:0;"><span class="lb">2차 진영</span><select class="ops-in" id="opsQNation"><option value="">(미정)</option>${FACTION_CHOICES.map(n => `<option>${n}</option>`).join('')}</select></div>
      </div>
      <div class="ops-steppers" id="opsQStats"></div>
      <div class="ops-start"><span class="ops-hint">합계 <b id="opsQTotal" style="color:var(--text)">0</b></span>
        <button class="ops-btn" onclick="opsQuickReset()">초기화</button>
        <button class="ops-btn primary" onclick="opsQuickSubmit()"><i class="fa-solid fa-plus"></i> 등록</button></div>`
      : `
      <textarea class="ops-in" id="opsRegText" placeholder="메이&#10;체력 2&#10;공격 3&#10;방어 1&#10;이능 3&#10;정신 2&#10;민첩 3&#10;행운 2&#10;역할 스트라이커&#10;스킬 붕괴&#10;진영 使徒 또는 Void (2차, 선택)&#10;나이 13~16 (1차 기준, 선택 · 기본 13)"></textarea>
      <div class="ops-start"><span class="ops-hint">여러 명은 빈 줄로 나눠 한 번에 붙여 넣어요.</span>
        <button class="ops-btn primary" onclick="opsPasteSubmit()">일괄 등록</button></div>
      <div class="ops-row" style="margin-top:14px;"><span class="ops-hint" style="flex:1;">테스트용 더미 캐릭터</span>
        <input class="ops-in num" id="opsDummyN" type="number" min="1" max="100" value="6"><button class="ops-btn" onclick="opsDummies()">더미 생성</button></div>`}
      <div class="ops-result" id="opsRegResult">${opsResultHtml}</div>
    </div>
    <div class="ops-card fit">
      <h3><i class="fa-solid fa-address-book"></i> 등록된 캐릭터<span class="sub" id="opsRosterCount"></span></h3>
      <input class="ops-in" id="opsRosterQ" placeholder="이름 검색" autocomplete="off" oninput="opsRenderRoster()">
      <div id="opsRoster" class="ops-roster"></div>
    </div>
  </div>`;
}
function opsSetReg(m) { opsRegMode = m; renderOps(); }
function opsQuickRefresh() {
  const roles = document.getElementById('opsQRoles'); if (!roles) return;
  roles.innerHTML = OPS_ROLES.map(r => `<button class="${r === opsQuick.role ? 'on' : ''}" style="--rc:${opsRoleColor(r)}" onclick="opsQuickRole('${r}')">${r}</button>`).join('');
  const sel = document.getElementById('opsQSkill');
  const keep = sel.value;
  sel.innerHTML = '<option value="">(없음)</option>' + (OPS_SKILLS[opsQuick.role] || []).map(k => `<option value="${k}">${k}</option>`).join('');
  if ((OPS_SKILLS[opsQuick.role] || []).includes(keep)) sel.value = keep;
  document.getElementById('opsQStats').innerHTML = STAT_KEYS.map(k => { const v = opsQuick.stats[k] || 0; return `<div class="ops-step"><span class="k">${k}</span>
    <button onclick="opsQuickStep('${k}', -1)" ${v <= 0 ? 'disabled' : ''}><i class="fa-solid fa-minus"></i></button><span class="v">${v}</span>
    <button onclick="opsQuickStep('${k}', 1)"><i class="fa-solid fa-plus"></i></button></div>`; }).join('');
  document.getElementById('opsQTotal').textContent = STAT_KEYS.reduce((a, k) => a + (opsQuick.stats[k] || 0), 0);
  const name = document.getElementById('opsQName').value.trim();
  document.getElementById('opsQWarn').style.display = name && opsRosterDetail().some(c => c.name === name) ? '' : 'none';
}
function opsQuickRole(r) { opsQuick.role = r; opsQuickRefresh(); }
function opsQuickStep(k, d) { opsQuick.stats[k] = Math.max(0, (opsQuick.stats[k] || 0) + d); opsQuickRefresh(); }
function opsQuickReset() { opsQuick.stats = {}; document.getElementById('opsQName').value = ''; document.getElementById('opsQNation').value = ''; opsQuickRefresh(); }
function opsQuickSubmit() {
  const name = document.getElementById('opsQName').value.trim();
  if (!name) { showError('이름을 입력해 주세요.'); return; }
  if (/^(체력|공격|방어|이능|정신|민첩|행운|역할|스킬|색상|국가|진영|나이)/.test(name)) { showError('이름이 스탯/역할 이름으로 시작하면 등록할 수 없어요.'); return; }
  const lines = [name, ...STAT_KEYS.map(k => `${k} ${opsQuick.stats[k] || 0}`), `역할 ${opsQuick.role}`];
  const skill = document.getElementById('opsQSkill').value; if (skill) lines.push(`스킬 ${skill}`);
  const nation = document.getElementById('opsQNation').value.trim(); if (nation) lines.push(`진영 ${nation}`);
  socket.emit('register_characters', { text: lines.join('\n') });
  document.getElementById('opsQName').value = '';
  opsQuickRefresh();
}
function opsPasteSubmit() {
  const t = document.getElementById('opsRegText').value;
  if (!t.trim()) { showError('등록할 내용을 붙여 넣어 주세요.'); return; }
  socket.emit('register_characters', { text: t });
}
function opsDummies() { socket.emit('generate_dummies', { count: parseInt(document.getElementById('opsDummyN').value, 10) || 6 }); }
socket.on('register_result', (d) => {
  const ok = (d.registered || []), bad = (d.errors || []);
  opsResultHtml = (ok.length ? `<div class="ok"><i class="fa-solid fa-check"></i> ${ok.length}명 등록 : ${ok.map(mailEsc).join(', ')}</div>` : '')
    + bad.map(e => `<div class="bad"><i class="fa-solid fa-triangle-exclamation"></i> ${mailEsc(e)}</div>`).join('');
  const el = document.getElementById('opsRegResult'); if (el) el.innerHTML = opsResultHtml;
  if (ok.length && opsRegMode === 'paste') { const ta = document.getElementById('opsRegText'); if (ta && !bad.length) ta.value = ''; }
});
function opsRenderRoster() {
  const el = document.getElementById('opsRoster'); if (!el) return;
  const list = opsRosterDetail();
  document.getElementById('opsRosterCount').textContent = `${list.length}명`;
  const q = ((document.getElementById('opsRosterQ') || {}).value || '').trim().toLowerCase();
  const shown = list.filter(c => !q || c.name.toLowerCase().includes(q));
  if (!shown.length) { el.innerHTML = `<div class="ops-empty">${list.length ? '검색 결과가 없어요.' : '등록된 캐릭터가 없어요.'}</div>`; return; }
  const roles = [...OPS_ROLES, ...[...new Set(shown.map(c => c.role))].filter(r => !OPS_ROLES.includes(r))];
  el.innerHTML = roles.map(role => {
    const g = shown.filter(c => c.role === role).sort((a, b) => a.name.localeCompare(b.name, 'ko'));
    if (!g.length) return '';
    return `<div class="ops-rgroup"><div class="ops-rgroup-h" style="color:${opsRoleColor(role)}">${mailEsc(role)}<span>${g.length}</span></div>
      ${g.map(c => { const n = JSON.stringify(c.name); return `<div class="ops-prow"><span class="nm">${mailEsc(c.name)}</span>
        ${c.mob ? '<span class="sk mob">몹</span>' : ''}${c.skill ? `<span class="sk">${mailEsc(c.skill)}</span>` : ''}${FACTION_CHOICES.includes(c.nation) ? `<span class="sk">${mailEsc(c.nation)}</span>` : ''}<span class="sp"></span>
        <button class="ops-btn icon" onclick='opsEdit(${n})' data-tip="수정"><i class="fa-solid fa-pen"></i></button>
        <button class="ops-btn icon" onclick='opsDelete(${n})' data-tip="삭제"><i class="fa-solid fa-trash-can"></i></button></div>
        ${opsEditName === c.name ? opsEditHtml(c) : ''}`; }).join('')}</div>`;
  }).join('');
}
function opsEditHtml(c) {
  const skills = OPS_SKILLS[c.role] || [];
  return `<div class="ops-edit">
    <div class="ops-row"><div class="ops-field" style="flex:1; margin:0;"><span class="lb">역할</span>
      <select class="ops-in" id="opsERole" onchange="opsEditRole()">${OPS_ROLES.map(r => `<option ${r === c.role ? 'selected' : ''}>${r}</option>`).join('')}</select></div>
      <div class="ops-field" style="flex:1; margin:0;"><span class="lb">스킬</span><select class="ops-in" id="opsESkill"><option value="">(없음)</option>${skills.map(k => `<option ${k === c.skill ? 'selected' : ''}>${k}</option>`).join('')}</select></div></div>
    <div class="ops-field" style="margin-top:10px;"><span class="lb">나이 (1차 · 空歷 514年 기준, 13~16세)</span><input class="ops-in" type="number" id="opsEAge" min="13" max="16" placeholder="비우면 기본 13세" value="${c.age ?? ''}"></div>
    <label class="ops-check" style="margin-top:12px;"><input type="checkbox" id="opsEMob" ${c.mob ? 'checked' : ''}><span>몹 <em>참가자 화면에 정확한 체력을 숨겨요(막대만 보여요)</em></span></label>
    <div class="ops-field" style="margin-top:10px;"><span class="lb">2차 진영</span><select class="ops-in" id="opsENation"><option value="">(미정)</option>${FACTION_CHOICES.map(n => `<option ${n === c.nation ? 'selected' : ''}>${mailEsc(n)}</option>`).join('')}</select></div>
    <div class="ops-stat-grid">${STAT_KEYS.map(k => `<label>${k}<input class="ops-in" type="number" id="opsEStat_${k}" value="${(c.stats || {})[k] ?? 0}" oninput="opsEditTotal()"></label>`).join('')}</div>
    <div class="ops-start"><span class="ops-hint">합계 <b id="opsETotal" style="color:var(--text)">${STAT_KEYS.reduce((a, k) => a + (parseInt((c.stats || {})[k], 10) || 0), 0)}</b></span>
      <button class="ops-btn" onclick="opsEditName=null; opsRenderRoster()">취소</button>
      <button class="ops-btn primary" onclick="opsEditSave()">저장</button></div></div>`;
}
function opsEdit(name) { opsEditName = opsEditName === name ? null : name; opsRenderRoster(); }
function opsEditRole() {
  const role = document.getElementById('opsERole').value;
  document.getElementById('opsESkill').innerHTML = '<option value="">(없음)</option>' + (OPS_SKILLS[role] || []).map(k => `<option>${k}</option>`).join('');
}
function opsEditTotal() { document.getElementById('opsETotal').textContent = STAT_KEYS.reduce((a, k) => a + (parseInt(document.getElementById('opsEStat_' + k).value, 10) || 0), 0); }
function opsEditSave() {
  if (!opsEditName) return;
  const stats = {}; STAT_KEYS.forEach(k => { stats[k] = document.getElementById('opsEStat_' + k).value; });
  socket.emit('update_character', { name: opsEditName, role: document.getElementById('opsERole').value, stats,
    skill: document.getElementById('opsESkill').value || null, nation: document.getElementById('opsENation').value,
    mob: document.getElementById('opsEMob').checked,
    age: document.getElementById('opsEAge').value === '' ? null : document.getElementById('opsEAge').value });
  opsEditName = null;
}
function opsDelete(name) {
  uiConfirm(`${name} 캐릭터를 삭제할까요?`, { title: '캐릭터 삭제', okText: '삭제', danger: true }).then(ok => {
    if (!ok) return;
    if (opsEditName === name) opsEditName = null;
    socket.emit('delete_character', { name });
  });
}

// ---------- 음악 ----------
function opsMusicHtml() {
  return `<div class="ops-grid">
    <div class="ops-card">
      <h3><i class="fa-solid fa-compact-disc"></i> 지금 재생<span class="sub">모두에게 같은 위치로 재생</span></h3>
      <div class="ops-now"><span class="ic"><i class="fa-solid fa-music"></i></span><span class="t" id="opsMusicNow">재생 없음</span></div>
      <div class="ops-field"><span class="lb">표시 이름 (비우면 '배경음악')</span>
        <div class="ops-row"><input class="ops-in" id="opsMusicTitle" maxlength="40" placeholder="러너 화면에 보일 곡 이름">
        <button class="ops-btn" onclick="socket.emit('set_music_title', { title: opsMusicTitle() })" data-tip="재생 위치는 그대로">이름 변경</button></div></div>
      <div class="ops-foot"><button class="ops-btn danger" onclick="socket.emit('stop_music', {})"><i class="fa-solid fa-stop"></i> 정지</button></div>
    </div>
    <div class="ops-card">
      <h3><i class="fa-solid fa-play"></i> 새 곡 재생</h3>
      <div class="ops-field"><span class="lb">유튜브 링크</span>
        <div class="ops-row"><input class="ops-in" id="opsMusicYt" placeholder="https://www.youtube.com/watch?v=...">
        <button class="ops-btn primary" onclick="opsPlayYoutube()"><i class="fa-solid fa-play"></i> 재생</button></div></div>
      <div class="ops-field"><span class="lb">mp3 파일</span>
        <div class="ops-row"><label class="ops-file"><input type="file" id="opsMusicFile" accept=".mp3" onchange="document.getElementById('opsMusicFileName').textContent = this.files[0] ? this.files[0].name : '파일을 골라 주세요'">
          <i class="fa-solid fa-file-audio"></i><span id="opsMusicFileName">파일을 골라 주세요</span></label>
        <button class="ops-btn primary" onclick="opsPlayMp3()"><i class="fa-solid fa-upload"></i> 올려서 재생</button></div></div>
    </div>
  </div>`;
}
function opsMusicTitle() { return ((document.getElementById('opsMusicTitle') || {}).value || '').trim(); }
function opsRenderMusicNow() {
  const el = document.getElementById('opsMusicNow'); if (!el) return;
  const m = opsLastPublic && opsLastPublic.music;
  el.textContent = m && m.src ? `${m.title || '배경음악'} · ${m.type === 'youtube' ? '유튜브' : 'mp3'}` : '재생 없음';
}
function opsPlayYoutube() {
  const url = document.getElementById('opsMusicYt').value.trim();
  if (!url) { showError('유튜브 링크를 입력해 주세요.'); return; }
  socket.emit('set_music', { type: 'youtube', src: url, title: opsMusicTitle() });
}
function opsPlayMp3() {
  const file = document.getElementById('opsMusicFile').files[0];
  if (!file) { showError('mp3 파일을 골라 주세요.'); return; }
  if (file.size > UPLOAD_AUDIO_BYTES) { showError(`파일이 너무 커요 (최대 ${UPLOAD_AUDIO_MB}MB).`); return; }
  const fd = new FormData();
  fd.append('room_id', ROOM_ID); fd.append('key', KEY); fd.append('sid', socket.id); fd.append('file', file);
  fetch('/upload_music', { method: 'POST', body: fd }).then(r => r.json()).then(d => {
    if (d.error) { showError(d.error); return; }
    socket.emit('set_music', { type: 'mp3', src: d.url, title: opsMusicTitle() });
  }).catch(() => showError('업로드에 실패했어요.'));
}

// ---------- 방 설정 ----------
// 방 설정(일반 · 톱니바퀴) / 전투 설정(전투 방 · 전투 관리)
// ---------- 성능 분석 : 캐릭터마다 다이스 값이 보통 얼마나 나오는지(이 방 전투 유형의 수식으로 여러 번 굴려 본 값) ----------
// 큰 숫자 = 보통(가운데 값), 막대 = 낮게(10%)~높게(90%), 흰 선 = 보통. 설명 글 없이 배치로 읽히게.
let opsAnal = null, opsAnalSel = null, opsAnalSort = 'atk', opsAnalKind = 'all', opsAnalVs = null, opsAnalMatch = null;
socket.on('dice_analysis', (d) => { opsAnal = d; if (!opsAnalSel && d.chars.length) opsAnalSel = d.chars[0].name; if (opsOpen() && opsTab === 'anal') opsRenderAnal(); });
socket.on('dice_matchup', (d) => { opsAnalMatch = d; if (opsOpen() && opsTab === 'anal') opsRenderAnalDetail(); });
const ANAL_STATS = [['atk', '공격'], ['def', '방어'], ['heal', '회복']];
function opsAnalHtml() {
  if (!opsAnal) socket.emit('dice_analysis');
  const seg = (id, items, cur, fn) => `<div class="anal-seg" id="${id}">${items.map(k => `<button type="button" data-k="${k[0]}" class="${cur === k[0] ? 'on' : ''}" onclick="${fn}('${k[0]}')">${k[1]}</button>`).join('')}</div>`;
  return `<div class="ops-card anal-card">
    <div class="anal-top">
      ${seg('opsAnalKind', [['all', '전체'], ['runner', '러너'], ['mob', '몹']], opsAnalKind, 'opsAnalSetKind')}
      <input class="ops-in" id="opsAnalQ" placeholder="검색" autocomplete="off" oninput="opsRenderAnal()">
      <button class="ops-btn icon" onclick="opsAnal = null; opsAnalMatch = null; socket.emit('dice_analysis'); opsRenderAnal()" data-tip="다시 계산"><i class="fa-solid fa-rotate"></i></button>
    </div>
    <div class="anal-wrap"><div class="anal-list" id="opsAnalTable"></div><div class="anal-detail" id="opsAnalDetail"></div></div>
  </div>`;
}
function opsAnalSetKind(k) { opsAnalKind = k; document.querySelectorAll('#opsAnalKind button').forEach(b => b.classList.toggle('on', b.dataset.k === k)); opsRenderAnal(); }
// 정렬 : 머리글을 눌러요
function opsAnalSetSort(k) { opsAnalSort = k; opsRenderAnal(); }
function opsAnalCell(o, scale) {
  const at = (v) => Math.max(0, Math.min(100, (v - scale.lo) / Math.max(1, scale.hi - scale.lo) * 100));
  return `<span class="anal-cell" data-tip="${o.p10} ~ ${o.p90}"><b>${o.p50}</b>
    <i class="rng"><i style="left:${at(o.p10)}%; width:${Math.max(2, at(o.p90) - at(o.p10))}%"></i><i class="m" style="left:${at(o.p50)}%"></i></i></span>`;
}
function opsRenderAnal() {
  const box = document.getElementById('opsAnalTable'); if (!box) return;
  if (!opsAnal) { box.innerHTML = emptyHtml('fa-circle-notch fa-spin', '계산하는 중'); document.getElementById('opsAnalDetail').innerHTML = ''; return; }
  const kindOf = (c, k) => k === 'all' || (k === 'mob' ? c.mob : !c.mob);
  const q = ((document.getElementById('opsAnalQ') || {}).value || '').trim().toLowerCase();
  const key = { atk: c => c.atk.p50, def: c => c.def.p50, heal: c => c.heal.p50, hp: c => c.hp }[opsAnalSort];
  const list = opsAnal.chars.filter(c => kindOf(c, opsAnalKind) && (!q || c.name.toLowerCase().includes(q))).sort((a, b) => key(b) - key(a));
  const scale = {}; ANAL_STATS.forEach(([k]) => { scale[k] = { lo: Math.min(...opsAnal.chars.map(c => c[k].p10)), hi: Math.max(...opsAnal.chars.map(c => c[k].p90)) }; });
  const th = (k, t) => `<button type="button" class="${opsAnalSort === k ? 'on' : ''}" onclick="opsAnalSetSort('${k}')">${t}</button>`;
  box.innerHTML = `<div class="anal-row head"><span></span>${th('hp', '체력')}${ANAL_STATS.map(([k, t]) => th(k, t)).join('')}</div>`
    + (list.length ? list.map(c => `<button type="button" class="anal-row${c.name === opsAnalSel ? ' on' : ''}" onclick='opsAnalPick(${JSON.stringify(c.name)})'>
      <span class="nm"><i class="dot" style="background:${roleColorVar(c.role)}"></i><b>${mailEsc(c.name)}</b></span>
      <span class="hp">${c.hp}</span>${ANAL_STATS.map(([k]) => opsAnalCell(c[k], scale[k])).join('')}</button>`).join('')
      : emptyHtml(opsAnalKind === 'mob' ? 'fa-dragon' : 'fa-magnifying-glass', '없음'));
  if (!list.some(c => c.name === opsAnalSel) && list.length) opsAnalSel = list[0].name;
  opsRenderAnalDetail();
}
function opsAnalPick(name) { opsAnalSel = name; opsAnalMatch = null; opsRenderAnal(); }
function opsAnalBars(h, o) {
  const max = Math.max(...h.bars, 1), at = (v) => h.hi > h.lo ? ((v - h.lo) / (h.hi - h.lo) * 100).toFixed(1) : 50;
  return `<div class="anal-hist">${h.bars.map(b => `<i style="height:${Math.max(2, b / max * 100)}%"></i>`).join('')}<b class="mk" style="left:${at(o.p50)}%"></b></div>
    <div class="anal-axis"><span>${o.p10}</span><span>${o.p90}</span></div>`;
}
function opsRenderAnalDetail() {
  const box = document.getElementById('opsAnalDetail'); if (!box || !opsAnal) return;
  const c = opsAnal.chars.find(x => x.name === opsAnalSel); if (!c) { box.innerHTML = ''; return; }
  const st = c.stats || {}, rr = c.reroll, d = c.dice;
  const chip = (t) => `<span class="chip">${t}</span>`;
  const card = (title, o, chips) => `<div class="anal-blk"><div class="h"><b>${title}</b>${chips}<strong>${o.p50}</strong></div>${opsAnalBars(o.hist, o)}</div>`;
  const others = opsAnal.chars.filter(x => x.name !== c.name);
  if (!opsAnalVs || opsAnalVs === c.name || !others.some(x => x.name === opsAnalVs)) opsAnalVs = others.length ? others[0].name : null;
  const m = opsAnalMatch && opsAnalMatch.a === c.name && opsAnalMatch.b === opsAnalVs ? opsAnalMatch : null;
  box.innerHTML = `<div class="anal-who"><i class="dot" style="background:${roleColorVar(c.role)}"></i><b>${mailEsc(c.name)}</b>
      <span class="facts"><span data-tip="체력"><i class="fa-solid fa-heart"></i>${c.hp}</span><span data-tip="이동"><i class="fa-solid fa-shoe-prints"></i>${c.move}</span><span data-tip="회피"><i class="fa-solid fa-wind"></i>${c.dodge}%</span></span></div>
    <div class="anal-stats">${['체력', '공격', '방어', '이능', '정신', '민첩', '행운'].map(k => `<span><em>${k}</em><b>${st[k] || 0}</b></span>`).join('')}</div>
    ${card('공격', c.atk, c.atk.crit_on ? chip(`치명 ${c.atk.crit}% ×${c.atk.crit_mult}`) : '')}
    ${card('방어', c.def, chip(`무방비 ${c.def.passive}`))}
    ${card('회복', c.heal, c.heal.crit_on ? chip(`치명 ${c.heal.crit}%`) : '')}
    ${rr.threshold > 0 ? `<div class="anal-blk"><div class="h"><b>정신</b>${chip(`${rr.threshold} 이하 ${rr.chance}%`)}${chip(`공격 +${Math.round(rr.gain * d.atk_count * 10) / 10}`)}
      <strong class="arrow"><em>${rr.plain_median}</em><i class="fa-solid fa-arrow-right"></i>${rr.median}</strong></div></div>` : ''}
    <div class="anal-blk"><div class="h"><b>vs</b>
      <select class="ops-in" onchange="opsAnalVs = this.value; opsAnalMatch = null; opsRenderAnalDetail()">${others.map(x => `<option value="${mailEsc(x.name)}"${x.name === opsAnalVs ? ' selected' : ''}>${mailEsc(x.name)}</option>`).join('')}</select></div>
      ${!opsAnalVs ? '' : m ? `<div class="anal-vs">
          <div><span>무방비</span><b>${m.passive.p50}</b>${m.passive.hits ? `<em>${m.passive.hits}타</em>` : ''}</div>
          <div><span>방어</span><b>${m.active.p50}</b>${m.active.hits ? `<em>${m.active.hits}타</em>` : ''}</div></div>`
        : (socket.emit('dice_matchup', { a: c.name, b: opsAnalVs }), '<div class="anal-vs"><div><b>…</b></div><div><b>…</b></div></div>')}</div>`;
}
function opsRoomHtml(kind) {
  const C = {
    room: `    <div class="ops-card">
      <h3><i class="fa-solid fa-door-open"></i> 방</h3>
      <div class="ops-field"><span class="lb">방 이름</span>
        <div class="ops-row"><input class="ops-in" id="opsRoomName" maxlength="40" autocomplete="off" onkeydown="if(event.key==='Enter') opsSaveRoomName()">
        <button class="ops-btn primary" onclick="opsSaveRoomName()">저장</button></div></div>
      <div class="ops-field"><span class="lb">참가자 링크</span>
        <div class="ops-row"><input class="ops-in" id="opsGuestLink" readonly onclick="this.select()">
        <button class="ops-btn" onclick="opsCopyLink()"><i class="fa-regular fa-copy"></i> 복사</button></div></div>
    </div>
`,
    point: `    <div class="ops-card">
      <h3><i class="fa-solid fa-palette"></i> 포인트 컬러</h3>
      <div class="ops-swatches" id="opsSwatches"></div>
      <div class="ops-hint" style="margin-top:12px;">진영 색(Resonans · 使徒 · Void)은 바뀌지 않아요.</div>
    </div>
`,
    mail: `    <div class="ops-card">
      <h3><i class="fa-solid fa-envelope"></i> 편지 시기<span class="sub">러너는 이 기간 안에서 연도만 골라요</span></h3>
      <div class="mail-eras" id="opsMailEras"></div>
      <div class="ops-hint" style="margin-top:12px;">캐릭터 나이는 1차 입학(空歷 514年) 기준 13~16세(기본 13세)이고, 운영진이 마이페이지나 캐릭터 수정에서 바꿀 수 있어요.</div>
    </div>
`,
    remind: `    <div class="ops-card">
      <h3><i class="fa-solid fa-hourglass-half"></i> 미행동자 안내<span class="sub">라운드 제한시간이 이만큼 남으면 커맨드 창에 한 번 안내</span></h3>
      <div class="mail-eras" id="opsRemind"></div>
      <div class="ops-hint" style="margin-top:12px;">예) 제한시간 1분 남았습니다. 미행동자 하루, 노아, 세린 · 모두 행동했으면 안내하지 않아요.</div>
    </div>
`,
    chat: `    <div class="ops-card">
      <h3><i class="fa-solid fa-comment-slash"></i> 채팅 도배 방지<span class="sub">이 시간 안에 이 횟수를 넘게 보내면 잠시 막아요 · 운영진은 제한 없음</span></h3>
      <div class="mail-eras" id="opsChatLimit"></div>
    </div>
`,
    scene: `    <div class="ops-card">
      <h3><i class="fa-solid fa-cloud-sun"></i> 배경 · 날씨</h3>
      <div class="ops-scene" id="opsScene"></div>
      <div class="ops-foot"><button class="ops-btn" onclick="openSceneModal()"><i class="fa-solid fa-sliders"></i> 배경 · 날씨 설정</button></div>
    </div>
`,
    thumb: `    <div class="ops-card">
      <h3><i class="fa-regular fa-image"></i> 썸네일<span class="sub">룸 목록 카드에 보여요 · 없으면 배경이나 맵 이미지를 써요</span></h3>
      <div class="ops-thumb" id="opsThumb"></div>
      <div class="ops-foot"><input type="file" id="opsThumbFile" accept="image/png,image/jpeg,image/webp,image/gif,.apng" style="display:none" onchange="opsThumbUpload(this)">
        <button class="ops-btn" id="opsThumbClear" onclick="socket.emit('set_battle_thumb', {clear: true})"><i class="fa-solid fa-trash-can"></i> 지우기</button>
        <button class="ops-btn primary" onclick="document.getElementById('opsThumbFile').click()"><i class="fa-solid fa-upload"></i> 이미지 올리기</button></div>
    </div>
`,
    mapbg: `    <div class="ops-card">
      <h3><i class="fa-solid fa-map"></i> 지도 배경 · 몹 이미지<span class="sub">격자 지도에 깔리는 배경과 몹(2x2) 이미지</span></h3>
      <div class="ops-thumb" id="opsMapBg"></div>
      <div class="ops-foot"><button class="ops-btn primary" onclick="openMapBgModal()"><i class="fa-solid fa-sliders"></i> 지도 배경 · 몹 이미지 설정</button></div>
    </div>
`,
    chattabs: `    <div class="ops-card">
      <h3><i class="fa-solid fa-comments"></i> 채팅 탭<span class="sub">전투 관전 · 아군 회의 탭을 켜고 끄거나 이름을 바꿔요</span></h3>
      <div class="ops-hint" id="opsChatTabsNow"></div>
      <div class="ops-foot"><button class="ops-btn" onclick="toggleChatTabSettings()"><i class="fa-solid fa-sliders"></i> 채팅 탭 설정</button></div>
    </div>
`,
    backup: `    <div class="ops-card">
      <h3><i class="fa-solid fa-box-archive"></i> 백업<span class="sub">서버 컴퓨터 backups 폴더에 자동으로 묶어 보관해요</span></h3>
      <div id="opsBackup" class="ops-bk"><span class="ops-hint">불러오는 중…</span></div>
      <div class="ops-foot"><button class="ops-btn" onclick="socket.emit('backup_now')"><i class="fa-solid fa-floppy-disk"></i> 지금 백업</button></div>
    </div>
`,
    errors: `    <div class="ops-card">
      <h3><i class="fa-solid fa-triangle-exclamation"></i> 최근 오류<span class="sub">지난 24시간 · 서버와 참가자 화면에서 난 오류(서버 컴퓨터 logs 폴더에 날짜별로 남아요)</span></h3>
      <div id="opsErrors" class="ops-errs"><span class="ops-hint">불러오는 중…</span></div>
      <div class="ops-foot"><button class="ops-btn" onclick="socket.emit('error_summary')"><i class="fa-solid fa-rotate"></i> 새로고침</button></div>
    </div>
`,
    hidden: `    <div class="ops-card">
      <h3><i class="fa-solid fa-eye-slash"></i> 공개<span class="sub">비공개면 룸 목록에 운영진에게만 보이고 아무도 들어올 수 없어요 · 새 전투는 비공개로 만들어져요</span></h3>
      <label class="ops-check"><input type="checkbox" id="opsHidden" onchange="socket.emit('battle_set_hidden', {hidden: this.checked})"> 비공개 (준비 중)</label>
    </div>
`,
    obstacle: `    <div class="ops-card">
      <h3><i class="fa-solid fa-cubes-stacked"></i> 장애물<span class="sub">전조 선택에서 오른쪽 클릭으로 놓아요 · 몇 번 맞으면 부서지는지(크리티컬이면 한 번에)</span></h3>
      <div class="ops-seg" id="opsObsHits"></div>
      <div class="ops-hint" style="margin-top:8px;">장애물 칸과 그 너머 십자 줄로는 이동할 수 없어요. 바꾼 횟수는 새로 놓는 장애물부터 적용돼요.</div>
    </div>
`,
    watch: `    <div class="ops-card">
      <h3><i class="fa-solid fa-eye"></i> 관전<span class="sub">룸 목록에는 모든 전투가 보이고, 들어올 수 있는 건 이 전투의 참여자(팀 편성)예요</span></h3>
      <label class="ops-check"><input type="checkbox" id="opsWatchOk" onchange="socket.emit('set_chat_tabs', {tabs: {spectator: this.checked}})"> 관전자도 들어올 수 있게(전투 관전 탭)</label>
    </div>
`,
    formula: `    <div class="ops-card">
      <h3><i class="fa-solid fa-lock"></i> 전투 수식</h3>
      <div class="ops-hint">수식과 운영진 로그는 GM으로 로그인한 화면에만 서버가 보내요. 러너 화면에는 데이터가 가지 않아요.</div>
      <div class="ops-foot"><button class="ops-btn" onclick="toggleFormulaPanel()"><i class="fa-solid fa-square-root-variable"></i> 전투 수식 설정</button></div>
    </div>
`,
  };
  // 전투 방 : 방 이름 · 링크 · 배경은 전투 설정으로, 일반 방 설정에는 사이트 공통 설정만
  // 격자 지도를 쓰는 전투(마스 레이드)만 지도 배경 · 몹 이미지
  const grid = !!document.getElementById('mapBgBtn');
  const keys = kind === 'battle' ? ['room', 'hidden', 'thumb', ...(grid ? ['mapbg'] : []), ...(BATTLE_TYPE === 'mass_raid' ? ['obstacle'] : []), 'watch', 'chattabs', 'remind', 'scene', 'formula']
    : OPS_BATTLE_ROOM ? ['point', 'mail', 'chat', 'backup', 'errors'] : ['room', 'point', 'mail', 'chat', 'scene', 'backup', 'errors'];
  return `<div class="ops-grid">${keys.map(k => C[k]).join('')}</div>`;
}
function opsRenderObsHits() {
  const el = document.getElementById('opsObsHits'); if (!el) return;
  const cur = (opsLastPublic && opsLastPublic.obstacle_hits) || 3;
  el.innerHTML = [1, 2, 3, 4, 5, 6].map(n => `<button class="${n === cur ? 'on' : ''}" onclick="socket.emit('set_obstacle_hits', {hits:${n}})">${n}회</button>`).join('');
}
function opsRenderScene() {
  const el = document.getElementById('opsScene'); if (!el) return;
  const cfg = sceneCfg();
  const wb = document.querySelector(`#sceneModal button[data-v="${cfg.weather}"]`);
  const wname = cfg.weather && cfg.weather !== 'none' && wb ? wb.textContent.trim() : '없음';
  el.innerHTML = `<div class="thumb" style="${cfg.url ? `background-image:url('${cfg.url}')` : ''}">${cfg.url ? '' : '<i class="fa-regular fa-image"></i>'}</div>
    <div class="kv"><div><span class="k">배경</span><span>${cfg.url ? `이미지 · 어둡게 ${cfg.dim}%` : '없음'}</span></div>
    <div><span class="k">날씨</span><span>${mailEsc(wname)}</span></div></div>`;
}
const OPS_POINTS = [['purple', '보라', '#a48dff'], ['blue', '파랑', '#6f93ff'], ['yellow', '노랑', '#f0c862']];
function opsRenderSwatches() {
  const el = document.getElementById('opsSwatches'); if (!el) return;
  const cur = (opsLastPublic && opsLastPublic.point_theme) || 'blue';
  el.innerHTML = OPS_POINTS.map(([k, t, c]) => `<button class="ops-swatch ${k === cur ? 'on' : ''}" style="--sw:${c}" onclick="socket.emit('set_point_theme', {theme:'${k}'})">
    <span class="sw"></span>${t}${k === cur ? '<i class="fa-solid fa-check"></i>' : ''}</button>`).join('');
}
function opsRenderMailEras() {
  const el = document.getElementById('opsMailEras'); if (!el) return;
  if (!mailData || !mailData.eras) { socket.emit('mail_list'); return; }
  const cur = mailData.era_now;
  el.innerHTML = mailData.eras.map(e => `<button class="${e.id === cur ? 'on' : ''}" onclick="socket.emit('mail_era_set', {era:'${e.id}'})">${mailEsc(e.name)} · ${e.from}~${e.to}年</button>`).join('');
}
const OPS_REMIND = [[0, '끄기'], [30, '30초'], [60, '1분'], [120, '2분'], [180, '3분'], [300, '5분']];
function opsRenderRemind() {
  const el = document.getElementById('opsRemind'); if (!el) return;
  const cur = opsLastPublic && opsLastPublic.remind_seconds != null ? opsLastPublic.remind_seconds : 60;
  el.innerHTML = OPS_REMIND.map(([v, t]) => `<button class="${v === cur ? 'on' : ''}" onclick="socket.emit('set_remind_seconds', {seconds:${v}})">${v ? `${t} 남았을 때` : t}</button>`).join('');
}
const OPS_CHAT_LIMIT = [['off', '끄기'], ['3/5', '5초에 3번'], ['5/10', '10초에 5번'], ['8/10', '10초에 8번'], ['15/30', '30초에 15번']];
function opsRenderChatLimit() {
  const el = document.getElementById('opsChatLimit'); if (!el) return;
  const cur = (opsLastPublic && opsLastPublic.chat_limit) || 'off';
  el.innerHTML = OPS_CHAT_LIMIT.map(([v, t]) => `<button class="${v === cur ? 'on' : ''}" onclick="socket.emit('set_chat_limit', {limit:'${v}'})">${t}</button>`).join('');
}
function opsThumbUpload(inp) {
  const f = inp.files && inp.files[0]; inp.value = ''; if (!f) return;
  f.arrayBuffer().then(buf => socket.emit('set_battle_thumb', { filename: f.name, data: buf }));
}
function opsRenderThumb() {
  const el = document.getElementById('opsThumb'); if (!el) return;
  const st = opsLastPublic || {}, own = st.battle_thumb;
  const fb = own || (st.scene && st.scene.url) || (st.map_bg && st.map_bg.url) || '';
  el.style.backgroundImage = fb ? `url('${fb}')` : '';
  el.classList.toggle('fallback', !own && !!fb);
  el.innerHTML = own ? '' : fb ? '<span class="tag">배경 · 맵 이미지 사용 중</span>' : '<i class="fa-regular fa-image"></i><span>썸네일 없음</span>';
  const c = document.getElementById('opsThumbClear'); if (c) c.disabled = !own;
}
function opsRenderMapBg() {
  const el = document.getElementById('opsMapBg'); if (!el) return;
  const mb = (opsLastPublic && opsLastPublic.map_bg) || {};
  el.style.backgroundImage = mb.url ? `url('${mb.url}')` : '';
  el.innerHTML = mb.url ? '' : '<i class="fa-regular fa-image"></i><span>배경 없음</span>';
}
socket.on('error_summary', d => {
  const el = document.getElementById('opsErrors'); if (!el || !d) return;
  if (!d.count) { el.innerHTML = '<div class="ops-errs-ok"><i class="fa-solid fa-circle-check"></i> 지난 24시간 동안 오류가 없어요.</div>'; return; }
  const t = at => { const x = new Date(at * 1000), p = n => String(n).padStart(2, '0'); return `${p(x.getMonth() + 1)}.${p(x.getDate())} ${p(x.getHours())}:${p(x.getMinutes())}`; };
  el.innerHTML = `<div class="ops-errs-n"><b>${d.count}건</b><span>서버 ${d.server} · 화면 ${d.client}</span></div>`
    + d.recent.map(x => `<div class="ops-err"><span class="k ${x.kind}">${x.kind === 'server' ? '서버' : '화면'}</span><span class="m">${mailEsc(x.message)}</span><span class="t">${t(x.at)}</span><span class="w">${mailEsc(x.where || '')}</span></div>`).join('');
});
socket.on('backup_status', d => {
  const el = document.getElementById('opsBackup'); if (!el || !d) return;
  const ago = at => { if (!at) return '아직 없음'; const m = Math.round((Date.now() / 1000 - at) / 60); return m < 1 ? '방금' : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`; };
  const mb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
  const stale = !d.last_at || (Date.now() / 1000 - d.last_at) > (d.hours * 2 + 1) * 3600;
  el.innerHTML = `<div class="r"><span class="k">마지막 백업</span><span class="v ${stale ? 'bad' : ''}">${ago(d.last_at)}${d.last_at ? ` · ${mb(d.last_size)}` : ''}</span></div>
    <div class="r"><span class="k">보관</span><span class="v">${d.count}개 · ${d.hours}시간마다 · 최근 ${d.keep}개</span></div>
    <div class="r"><span class="k">다른 곳 복사</span><span class="v ${d.extra_dir ? (d.extra_ok === false ? 'bad' : 'ok') : 'warn'}">${d.extra_dir
      ? (d.extra_ok === false ? `<i class="fa-solid fa-xmark"></i> 실패 · ${mailEsc(d.extra_err || '폴더를 찾을 수 없어요')}` : `<i class="fa-solid fa-check"></i> ${mailEsc(d.extra_dir)}`)
      : '설정 안 됨 — 컴퓨터가 고장 나면 백업도 같이 잃어요'}</span></div>
    ${d.extra_dir ? '' : '<div class="ops-hint" style="margin-top:6px">서버 폴더에 <b>backup_dir.txt</b> 파일을 만들고 첫 줄에 구글 드라이브 · OneDrive 폴더 경로를 적으면 백업마다 그곳에도 복사돼요.</div>'}`;
});
function opsRenderRoomInfo() {
  if (document.getElementById('opsBackup') && !opsRenderRoomInfo._bk) { opsRenderRoomInfo._bk = true; socket.emit('backup_status'); setTimeout(() => { opsRenderRoomInfo._bk = false; }, 30000); }
  if (document.getElementById('opsErrors') && !opsRenderRoomInfo._asked) { opsRenderRoomInfo._asked = true; socket.emit('error_summary'); setTimeout(() => { opsRenderRoomInfo._asked = false; }, 30000); }
  opsRenderThumb(); opsRenderMapBg();
  const hd = document.getElementById('opsHidden'); if (hd) hd.checked = !!(opsLastPublic && opsLastPublic.battle_hidden);
  const ct = document.getElementById('opsChatTabsNow');
  if (ct) ct.textContent = `${chatTabLabels.spectator} ${chatTabsEnabled.spectator ? '켜짐' : '꺼짐'} · ${chatTabLabels.team} ${chatTabsEnabled.team ? '켜짐' : '꺼짐'}`;
  const w = document.getElementById('opsWatchOk'); if (w) w.checked = !!((opsLastPublic && opsLastPublic.chat_tabs) || {}).spectator;
  opsRenderSwatches(); opsRenderObsHits(); opsRenderScene(); opsRenderMailEras(); opsRenderRemind(); opsRenderChatLimit();
  const n = document.getElementById('opsRoomName');
  if (n && document.activeElement !== n) n.value = (opsLastPublic && opsLastPublic.room_name) || ROOM_ID;
  const l = document.getElementById('opsGuestLink');
  if (l) l.value = `${location.origin}${location.pathname}?key=${encodeURIComponent(KEY)}`;
}
function opsSaveRoomName() { socket.emit('set_room_name', { name: document.getElementById('opsRoomName').value }); showShopToast('방 이름을 저장했어요.'); }
function opsCopyLink() {
  const l = document.getElementById('opsGuestLink');
  (navigator.clipboard ? navigator.clipboard.writeText(l.value) : Promise.reject()).then(() => showShopToast('참가자 링크를 복사했어요.'))
    .catch(() => { l.select(); document.execCommand('copy'); showShopToast('참가자 링크를 복사했어요.'); });
}

// 상태 갱신 연결
socket.on('public_state', (state) => {
  opsLastPublic = state;
  if (state.point_theme) { sitePointTheme = state.point_theme; applyPointTheme(); }
  syncOpsBtn(); renderOpsData();
});
socket.on('gm_state', (state) => {
  renderOpsData();
  const btn = document.getElementById('pendingRevealBtn');
  if (btn) btn.style.display = state.pending_reveal ? '' : 'none';
});

// ==================================================================
// 맵 (일반 룸) : 장소 지도(월드맵)와 챕터 해금 트랙(챕터)을 지도 메뉴에서 따로 엽니다. 운영진은 '편집'으로 장소·챕터를 고치고 해금 챕터를 정합니다.
// 잠긴 장소·챕터 내용은 서버가 러너에게 보내지 않습니다(??? 로만 보임).
// ==================================================================
let worldData = null, worldSel = null, worldView = 'map', worldEditMode = false, worldDraft = null, worldEditIdx = 0;
const worldEsc = (t) => mailEsc(t == null ? '' : String(t));
function worldOpen() { return document.body.classList.contains('view-map'); }
function worldIsGm() { return !!(worldData && worldData.gm) && myControlInfo(lastBattleForPanel).scope === 'all'; }
// 지도 메뉴 : 월드맵(장소 · 구역)과 챕터(해금 트랙)를 따로 열어요
function openWorldMap(view) {
  worldView = view === 'chapter' ? 'chapter' : 'map';
  // 기록 · 채팅 창이 열려 있으면 같은 순간에 닫고 지도로(중간 화면 없이)
  if (document.body.classList.contains('m-chat-open')) { viewSwap(); document.body.classList.add('view-map'); toggleMobileChat(false); }
  if (document.getElementById('dormModal').style.display === 'flex') closeDorm();
  if (document.getElementById('dormModal').style.display === 'flex') return;  // 꾸미기 저장 확인 중
  if (typeof closeOps === 'function' && opsOpen()) { document.body.classList.remove('view-ops'); document.getElementById('sidebarOpsBtn').classList.remove('active'); document.getElementById('sidebarSettingsBtn').classList.remove('active'); }
  if (typeof closeBattleHub === 'function') closeBattleHub();
  document.body.classList.add('view-map');
  if (typeof closeLoopAdmin === 'function' && document.body.classList.contains('view-loopadmin')) closeLoopAdmin();
  ['sidebarBattleBtn', 'sidebarDormBtn'].forEach(id => document.getElementById(id).classList.remove('active'));
  document.getElementById('sidebarMapBtn').classList.toggle('active', worldView === 'map');
  document.getElementById('sidebarChapterBtn').classList.toggle('active', worldView === 'chapter');
  socket.emit('world_get');
  renderWorld();
}
function closeWorldMap(silent) {
  if (!worldOpen()) return;
  document.body.classList.remove('view-map');
  document.getElementById('sidebarMapBtn').classList.remove('active');
  document.getElementById('sidebarChapterBtn').classList.remove('active');
  worldEditMode = false; worldDraft = null;
  if (typeof cg !== 'undefined') { cg.edit = false; cg.draft = null; cg.sel = null; }
  if (!silent && IS_LOUNGE) openDorm();
  if (!IS_LOUNGE) document.getElementById('sidebarBattleBtn').classList.add('active');
}
socket.on('world_data', (d) => {
  worldData = d;
  if (!d.gm) { worldEditMode = false; worldDraft = null; }
  if (worldOpen() && !worldEditMode) renderWorld();
  if (typeof renderMyPage === 'function') renderMyPage();
});
socket.on('world_result', (d) => showShopToast(d.message));
socket.on('joined', () => { if (worldOpen()) socket.emit('world_get'); });
socket.on('world_image_result', (d) => {
  if (!d.ok || !worldDraft || String(d.for || '').startsWith('node:')) return;
  const [pid, zi] = String(d.for || '').split(':z');
  const p = worldDraft.places.find(x => x.id === pid); if (!p) return;
  if (zi != null && zi !== '') { (p.zones = p.zones || [])[+zi] = Object.assign(p.zones[+zi] || {}, { image: d.url }); }
  else p.image = d.url;
  renderWorld();
});

function renderWorld() {
  const body = document.getElementById('worldBody'), tools = document.getElementById('worldTools');
  if (!body) return;
  const gm = worldIsGm();
  tools.innerHTML = !gm ? '' : worldEditMode
    ? `<button class="dorm-tbtn" onclick="worldEditMode=false; worldDraft=null; renderWorld()" data-tip="취소"><i class="fa-solid fa-xmark"></i><span class="t">취소</span></button>
       <button class="dorm-tbtn primary" onclick="saveWorld()" data-tip="저장"><i class="fa-solid fa-floppy-disk"></i><span class="t">저장</span></button>`
    : `<button class="dorm-tbtn" onclick="startWorldEdit()" data-tip="맵 편집"><i class="fa-solid fa-pen-ruler"></i><span class="t">편집</span></button>`;
  if (!worldData) { body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '맵을 불러오는 중입니다'); return; }
  if (worldEditMode) { worldDrawer(null); document.getElementById('worldTopSeg').textContent = '편집'; body.innerHTML = worldEditHtml(); return; }
  if (worldView === 'chapter') {
    document.getElementById('worldTopSeg').textContent = '챕터';
    // 챕터 화면 : 노드 그림이 위, 챕터는 아래 서랍(위 화살표를 누르면 올라와 덮고, 다시 누르면 내려가 노드가 보여요)
    body.innerHTML = worldGraphHtml();
    worldDrawer(worldChaptersHtml() || emptyHtml('fa-book-open', '아직 챕터가 없어요', gm ? '편집에서 챕터를 추가해 주세요.' : ''));
    cgMount();
    return;
  }
  worldDrawer(null);
  const places = worldData.places || [];
  if (!worldSel || !places.some(p => p.id === worldSel)) worldSel = (places.find(p => !p.locked) || places[0] || {}).id || null;
  const sel = places.find(p => p.id === worldSel);
  document.getElementById('worldTopSeg').textContent = sel && !sel.locked ? sel.name : '맵';
  body.innerHTML = worldMapHtml(places, sel);
  // 고른 장소가 화면 가운데 오도록 지도를 가로로 옮깁니다(좁은 화면).
  const st = body.querySelector('.wm-stage'), el = body.querySelector('.wm-node.sel');
  if (st && el && st.scrollWidth > st.clientWidth) st.scrollLeft = el.offsetLeft - st.clientWidth / 2 + el.offsetWidth / 2;
  worldPlaceFill(true);
  bindWorldFx();
}
let worldTrackShown = false, worldFillPrev = null;
// 지도 선 : 왼쪽 끝에서 고른 장소까지 포인트 컬러로 이어집니다(장소를 바꾸면 따라 움직임).
function worldPlaceFill(instant) {
  const row = document.querySelector('.wm-row'), el = row && row.querySelector('.wm-node.sel'), fill = row && row.querySelector('.wm-fill');
  if (!fill) return;
  const first = row.querySelector('.wm-node');
  const x0 = first ? first.offsetLeft + first.offsetWidth / 2 : 0;
  fill.style.left = x0 + 'px';
  const x = el ? el.offsetLeft + el.offsetWidth / 2 - x0 : 0;
  if (instant && worldFillPrev != null) { fill.style.transition = 'none'; fill.style.width = worldFillPrev + 'px'; void fill.offsetWidth; fill.style.transition = ''; }
  requestAnimationFrame(() => { fill.style.width = Math.max(0, x) + 'px'; });
  worldFillPrev = Math.max(0, x);
}
// 장소 고르기 : 지도는 그대로 두고 아래 설명·구역 카드만 새로 띄웁니다.
function worldPick(id) {
  const places = (worldData && worldData.places) || [], sel = places.find(p => p.id === id);
  if (!sel || worldSel === id) return;
  worldSel = id;
  document.querySelectorAll('.wm-node').forEach(n => n.classList.toggle('sel', n.dataset.id === id));
  const node = document.querySelector(`.wm-node[data-id="${id}"]`);
  if (node) { node.classList.remove('pulse'); void node.offsetWidth; node.classList.add('pulse'); }
  document.getElementById('worldTopSeg').textContent = sel.locked ? '맵' : sel.name;
  const box = document.getElementById('wmDetail');
  if (box) { box.innerHTML = worldDetailInner(sel); }
  const st = document.querySelector('.wm-stage');
  if (st && node && st.scrollWidth > st.clientWidth) st.scrollTo({ left: node.offsetLeft - st.clientWidth / 2 + node.offsetWidth / 2, behavior: 'smooth' });
  worldPlaceFill(false);
}
// 마우스 효과 : 지도 동심원이 살짝 따라 움직이고(패럴랙스), 구역 카드는 커서 쪽으로 기울며 빛이 비칩니다.
function bindWorldFx() {
  const body = document.getElementById('worldBody');
  if (!body || body._fx) return; body._fx = true;
  body.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    const st = e.target.closest('.wm-stage');
    if (st) { const r = st.getBoundingClientRect(); st.style.setProperty('--px', ((e.clientX - r.left) / r.width - .5).toFixed(3)); st.style.setProperty('--py', ((e.clientY - r.top) / r.height - .5).toFixed(3)); }
    const card = e.target.closest('.wm-zone');
    body.querySelectorAll('.wm-zone.tilt').forEach(c => { if (c !== card) { c.classList.remove('tilt'); c.style.removeProperty('--rx'); c.style.removeProperty('--ry'); } });
    if (card) {
      const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      card.classList.add('tilt');
      card.style.setProperty('--ry', ((x - .5) * 7).toFixed(2) + 'deg'); card.style.setProperty('--rx', ((.5 - y) * 6).toFixed(2) + 'deg');
      card.style.setProperty('--mx', (x * 100).toFixed(1) + '%'); card.style.setProperty('--my', (y * 100).toFixed(1) + '%');
    }
  });
  body.addEventListener('pointerleave', () => body.querySelectorAll('.wm-zone.tilt').forEach(c => c.classList.remove('tilt')));
  // 구역 카드 줄(옆으로 넘기는 화면) : 마우스 휠을 옆으로 바꿔 주고, 마우스로 끌어서도 넘겨요
  const canSide = (z) => z && z.scrollWidth > z.clientWidth + 2;
  body.addEventListener('wheel', (e) => {
    const z = e.target.closest('.wm-zones');
    if (!canSide(z) || Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
    const max = z.scrollWidth - z.clientWidth;
    if ((e.deltaY < 0 && z.scrollLeft <= 0) || (e.deltaY > 0 && z.scrollLeft >= max - 1)) return;   // 끝에 닿으면 페이지가 내려가요
    e.preventDefault();
    // 카드가 한 장씩 맞물려 있어서(scroll-snap) 휠 한 번에 카드 한 장씩 넘겨요
    const now = Date.now(); if (now - (z._wheelAt || 0) < 280) return; z._wheelAt = now;
    const card = z.querySelector('.wm-zone'), step = card ? card.offsetWidth + 14 : z.clientWidth * .8;
    z.scrollBy({ left: Math.sign(e.deltaY) * step, behavior: 'smooth' });
  }, { passive: false });
  let drag = null;
  body.addEventListener('pointerdown', (e) => {
    const z = e.target.closest('.wm-zones');
    if (e.pointerType !== 'mouse' || e.button !== 0 || !canSide(z)) return;
    drag = { z, x: e.clientX, left: z.scrollLeft, moved: false };
  });
  window.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) > 5) { drag.moved = true; drag.z.classList.add('dragging'); }
    if (drag.moved) drag.z.scrollLeft = drag.left - dx;
  });
  window.addEventListener('pointerup', () => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.moved) {
      d.z.classList.remove('dragging');
      // 끌고 난 뒤의 클릭(구역 안내)은 한 번 무시해요
      const eat = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      d.z.addEventListener('click', eat, { capture: true, once: true });
      setTimeout(() => d.z.removeEventListener('click', eat, { capture: true }), 0);
    }
  });
}
// 키보드 ← → 로 장소 넘기기
document.addEventListener('keydown', (e) => {
  if (!worldOpen() || worldEditMode || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  const ps = (worldData && worldData.places) || [], i = ps.findIndex(p => p.id === worldSel);
  const n = ps[i + (e.key === 'ArrowRight' ? 1 : -1)];
  if (n) { e.preventDefault(); worldPick(n.id); }
});

function worldChaptersHtml() {
  const chs = worldData.chapters || [], n = worldData.unlocked || 0, gm = worldIsGm();
  if (!chs.length) return gm ? '' : '';
  const fill = chs.length > 1 ? Math.max(0, (n - 1) / (chs.length - 1)) : (n ? 1 : 0);
  const nodes = chs.map((c, i) => {
    const open = i < n, now = i === n - 1;
    const title = c.locked ? '???' : worldEsc(c.title);
    return `<div class="wm-cnode ${open ? 'open' : ''} ${now ? 'now' : ''} ${gm ? 'gm' : ''}" ${gm ? `onclick="setWorldUnlocked(${i + 1})" data-tip="여기까지 해금"` : ''}>
      <span class="dot">${open ? i + 1 : '<i class="fa-solid fa-lock" style="font-size:10px"></i>'}</span><span class="t">${title}</span></div>`;
  }).join('');
  const rows = chs.map((c, i) => {
    const open = i < n, now = i === n - 1, locked = !!c.locked || !open;
    const st = now ? '<span class="st now">진행 중</span>' : open ? '<span class="st open">해금</span>' : '<span class="st lock"><i class="fa-solid fa-lock"></i> 잠김</span>';
    return `<div class="wm-chrow ${locked && !gm ? 'locked' : ''}"><span class="no">Ch. ${i + 1}</span>
      <span class="tt">${c.locked ? '아직 공개되지 않은 챕터입니다.' : worldEsc(c.title)}</span>${st}
      ${!c.locked && (open || gm) && c.summary ? `<span class="sm">${worldEsc(c.summary)}</span>` : ''}</div>`;
  }).join('');
  return `<div class="wm-card"><div class="wm-h"><span class="en">Chapter</span><span class="sub">${n} / ${chs.length} 해금</span><span class="sp"></span>
    ${gm ? '<span class="sub">점을 누르면 그 챕터까지 해금돼요</span>' : ''}</div>
    <div class="wm-track" style="--fill:${fill}">${nodes}</div><div class="wm-chlist">${rows}</div></div>`;
}
let worldDrawerOpen = false;
function worldDrawer(html) {
  const d = document.getElementById('cgDrawer'); if (!d) return;
  document.getElementById('worldBody').classList.toggle('has-drawer', html != null);
  if (html == null) { d.hidden = true; d.innerHTML = ''; return; }
  const chs = (worldData && worldData.chapters) || [], n = (worldData && worldData.unlocked) || 0;
  d.hidden = false; d.classList.toggle('open', worldDrawerOpen);
  d.innerHTML = `<button type="button" class="cg-drawer-bar" onclick="worldDrawerToggle()" aria-expanded="${worldDrawerOpen}">
      <span class="en">Chapter</span><span class="sub">${n} / ${chs.length} 해금</span><span class="sp"></span><i class="fa-solid fa-chevron-up"></i></button>
    <div class="cg-drawer-body">${html}</div>`;
}
function worldDrawerToggle() {
  worldDrawerOpen = !worldDrawerOpen;
  const d = document.getElementById('cgDrawer'); if (!d) return;
  d.classList.toggle('open', worldDrawerOpen);
  d.querySelector('.cg-drawer-bar').setAttribute('aria-expanded', worldDrawerOpen);
  // 처음 열 때 챕터 진행선이 왼쪽부터 차오르게
  const tr = d.querySelector('.wm-track');
  if (worldDrawerOpen && tr) { const f = tr.style.getPropertyValue('--fill'); tr.style.setProperty('--fill', 0); requestAnimationFrame(() => requestAnimationFrame(() => tr.style.setProperty('--fill', f))); }
}
function setWorldUnlocked(k) {
  if (!worldIsGm()) return;
  const n = worldData.unlocked === k ? k - 1 : k;
  socket.emit('world_save', { ...worldData, unlocked: n });
}

function worldMapHtml(places, sel) {
  const gm = worldIsGm(), n = worldData.unlocked || 0;
  if (!places.length) return `<div class="wm-card">${emptyHtml('fa-map', '아직 등록된 장소가 없습니다', gm ? '오른쪽 위 편집에서 장소를 추가해 주세요.' : '장소가 공개되면 여기에 보입니다.')}</div>`;
  const nodes = places.map((p, idx) => {
    // sealed : 아이콘 · 이름은 보이고 장소 안만 잠긴 곳(LOOP 방의 학교)
    const sealed = !!p.sealed, locked = !!p.locked && !sealed, gmlock = gm && p.chapter > n;
    const label = locked ? '???' : (p.en || p.name || '');
    return `<div class="wm-node ${p.id === worldSel ? 'sel' : ''} ${locked ? 'locked' : ''} ${sealed ? 'sealed' : ''} ${gmlock ? 'gmlock' : ''}" data-id="${p.id}" style="--i:${idx}" onclick="worldPick('${p.id}')">
      <span class="nm ${!locked && !p.en ? 'ko' : ''} ${label.length > 12 ? 'long' : ''}">${worldEsc(label)}</span>
      <span class="ic" style="${!locked && p.image ? `background-image:url('${worldEsc(p.image)}')` : ''}">${locked ? '<i class="fa-solid fa-lock"></i>' : (p.image ? '' : '<i class="fa-solid fa-location-dot"></i>')}</span>
      <span class="sb">${locked ? '' : worldEsc(p.sub || '')}</span></div>`;
  }).join('');
  return `<div class="wm-card"><div class="wm-sky"><span class="gx-orbit o2" aria-hidden="true"></span><span class="gx-orbit o1" aria-hidden="true"></span><div class="wm-stage"><div class="wm-row">${nodes}<span class="wm-fill"></span></div></div></div><div id="wmDetail">${worldDetailInner(sel)}</div></div>`;
}
function worldDetailInner(sel) {
  const gm = worldIsGm(), n = worldData.unlocked || 0;
  let detail = '';
  if (sel && sel.locked) {
    detail = emptyHtml('fa-lock', '아직 해금되지 않은 장소입니다', sel.chapter ? `Chapter ${sel.chapter}에서 공개됩니다.` : '', null, true);
  } else if (sel) {
    const tags = [sel.sub ? `<span class="tag pt">${worldEsc(sel.sub)}</span>` : '',
      sel.chapter ? `<span class="tag">Chapter ${sel.chapter}부터${gm && sel.chapter > n ? ' · 미공개' : ''}</span>` : ''].join('');
    const info = (sel.info || []).filter(i => i.k || i.v);
    detail = `<div class="wm-detail"><div><div class="name">${worldEsc(sel.name)}</div>${sel.en ? `<div class="en">${worldEsc(sel.en)}</div>` : ''}
      <div class="tags">${tags}</div><div class="desc">${worldEsc(sel.desc || '')}</div></div>
      ${info.length ? `<div class="wm-info">${info.map(i => `<div><div class="k">${worldEsc(i.k)}</div><div class="v">${worldEsc(i.v)}</div></div>`).join('')}</div>` : '<div></div>'}</div>`;
  }
  const zones = sel && !sel.locked ? worldZonesHtml(sel) : '';
  return detail + zones;
}

// ---------- 구역 카드 (장소마다 1~4구역) : 이미지 · 구역 이름 · 설명 · 정보 칸. 이미지가 없으면 No Signal ----------
const WM_NOSIGNAL = `<svg class="ns" viewBox="0 0 120 120" aria-hidden="true">${[0, 45, 90, 135, 180, 225, 270, 315].map(r =>
  `<rect x="57" y="8" width="6" height="26" fill="currentColor" transform="rotate(${r} 60 60)"/>`).join('')}</svg>`;
function worldZonesHtml(p) {
  const zs = p.zones || [];
  if (!zs.length) return '';
  return `<div class="wm-zones">${zs.map((z, i) => {
    const info = (z.info || []).filter(r => r.k || r.v);
    return `<article class="wm-zone" style="--i:${i}" onclick="worldZoneToast('${p.id}',${i})">
      <div class="cap"><span>${worldEsc(z.title || `${i + 1}구역`)}</span></div>
      <div class="img ${z.image ? '' : 'empty'}" style="${z.image ? `background-image:url('${worldEsc(z.image)}')` : ''}">${z.image ? '' : `${WM_NOSIGNAL}<span>No Signal</span>`}</div>
      <div class="ttl"><b>${i + 1}구역</b>${z.desc ? `<button class="wm-go" onclick="event.stopPropagation(); openWorldZone('${p.id}',${i})" aria-label="자세히 보기" data-tip="자세히 보기"><i class="fa-solid fa-arrow-right"></i></button>` : ''}</div>
      <div class="foot">${z.desc ? `<p class="clamp">${worldEsc(z.desc)}</p>` : '<p class="muted">구역 설명이 아직 없습니다.</p>'}
        ${info.length ? `<dl>${info.map(r => `<div><dt>${worldEsc(r.k)}</dt><dd>${worldEsc(r.v)}</dd></div>`).join('')}</dl>` : ''}
        ${z.ref ? `<div class="wm-ref"><i class="fa-solid fa-circle-info"></i>${worldEsc(z.ref)}</div>` : ''}</div>
    </article>`;
  }).join('')}</div>`;
}

// ---------- 구역 카드 : 누르면 한 줄 문구 토스트 / 자세히 보기 ----------
function worldZoneOf(pid, i) { const p = ((worldData && worldData.places) || []).find(x => x.id === pid); return p && p.zones ? [p, p.zones[i]] : [null, null]; }
// 출신지 : 마이페이지에서 고른 '장소id:구역번호'
function worldHomeNames(pid, i) {
  if (BATTLE_TYPE === 'play') return [];   // LOOP 방 : 맵에 누구의 출신지인지 보이지 않게
  const key = `${pid}:${i}`;
  return Object.entries(lastRosterMypage || {}).filter(([, d]) => d && d.hometown === key).map(([n]) => n).sort((a, b) => a.localeCompare(b, 'ko'));
}
let wmToastTimer = null, wmToastLast = {};
function worldZoneToast(pid, i) {
  const [p, z] = worldZoneOf(pid, i); if (!z) return;
  const names = worldHomeNames(pid, i), lines = z.lines || [];
  // 같은 문구가 연달아 나오지 않게 합니다.
  let line = '';
  if (lines.length) {
    const key = `${pid}:${i}`; let k = Math.floor(Math.random() * lines.length);
    if (lines.length > 1 && k === wmToastLast[key]) k = (k + 1) % lines.length;
    wmToastLast[key] = k; line = lines[k];
  }
  const t = document.getElementById('wmToast');
  const head = names.length ? `<b>${names.map(worldEsc).join(', ')}</b>의 출신지.` : `${i + 1}구역 · ${worldEsc(z.title || p.name)}`;
  t.innerHTML = `<div class="l1">${head}</div>${line ? `<div class="l2">${worldEsc(line)}</div>` : ''}`;
  t.classList.remove('on'); void t.offsetWidth; t.classList.add('on');
  clearTimeout(wmToastTimer); wmToastTimer = setTimeout(() => t.classList.remove('on'), 3600);
}
function openWorldZone(pid, i) {
  const [p, z] = worldZoneOf(pid, i); if (!z) return;
  const info = (z.info || []).filter(r => r.k || r.v), names = worldHomeNames(pid, i);
  document.getElementById('wmReaderBody').innerHTML = `
    <div class="wr-cap">${i + 1}구역 — ${worldEsc(p.name)}</div>
    <div class="wr-title">${worldEsc(z.title || `${i + 1}구역`)}</div>
    ${info.length ? `<div class="wr-info">${info.map(r => `<span><em>${worldEsc(r.k)}</em>${worldEsc(r.v)}</span>`).join('')}</div>` : ''}
    ${z.image ? `<div class="wr-img" style="background-image:url('${worldEsc(z.image)}')"></div>` : ''}
    <div class="wr-desc">${(z.desc || '').split(/\n+/).filter(Boolean).map(t => `<p>${worldEsc(t)}</p>`).join('')}</div>
    ${z.ref ? `<div class="wm-ref"><i class="fa-solid fa-circle-info"></i>${worldEsc(z.ref)}</div>` : ''}
    ${names.length ? `<div class="wr-home"><i class="fa-solid fa-location-dot"></i>${names.map(worldEsc).join(', ')}의 출신지</div>` : ''}`;
  document.getElementById('wmReader').style.display = 'flex';
  document.getElementById('wmReaderBody').scrollTop = 0;
}

// ---------- 운영진 편집 ----------
function startWorldEdit() {
  if (!worldIsGm()) return;
  worldDraft = JSON.parse(JSON.stringify({ chapters: worldData.chapters || [], places: worldData.places || [], unlocked: worldData.unlocked || 0 }));
  worldEditIdx = Math.max(0, worldDraft.places.findIndex(p => p.id === worldSel));
  worldEditMode = true; renderWorld();
}
function saveWorld() {
  if (!worldDraft) return;
  socket.emit('world_save', worldDraft);
  worldEditMode = false; worldDraft = null;
}
function worldMove(list, i, d) { const a = worldDraft[list], j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; if (list === 'places' && worldEditIdx === i) worldEditIdx = j; renderWorld(); }
function worldDel(list, i) {
  uiConfirm(list === 'places' ? '이 장소를 삭제할까요?' : '이 챕터를 삭제할까요?', { title: '삭제', okText: '삭제', danger: true }).then(ok => {
    if (!ok) return; worldDraft[list].splice(i, 1);
    if (list === 'chapters') { worldDraft.unlocked = Math.min(worldDraft.unlocked, worldDraft.chapters.length); worldDraft.places.forEach(p => { if (p.chapter > worldDraft.chapters.length) p.chapter = worldDraft.chapters.length; }); }
    if (list === 'places') worldEditIdx = Math.max(0, Math.min(worldEditIdx, worldDraft.places.length - 1));
    renderWorld();
  });
}
function worldAddChapter() { worldDraft.chapters.push({ id: Math.random().toString(16).slice(2, 10), title: `Chapter ${worldDraft.chapters.length + 1}`, summary: '' }); renderWorld(); }
function worldAddPlace() {
  worldDraft.places.push({ id: Math.random().toString(16).slice(2, 10), name: '새 장소', en: '', sub: '', desc: '', info: [], image: null, chapter: 0,
    zones: [0, 1, 2, 3].map(() => ({ title: '', image: null, desc: '', info: [], ref: '', lines: [] })) });
  worldEditIdx = worldDraft.places.length - 1; renderWorld();
}
function worldPlaceImage(ev, id) {
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_IMG_BYTES) { showShopToast(`${UPLOAD_IMG_MB}MB 이하의 이미지만 등록할 수 있습니다.`); return; }
  f.arrayBuffer().then(buf => socket.emit('world_image', { filename: f.name, data: buf, for: id }));
}
function worldZoneEditHtml(p) {
  const pi = worldEditIdx;
  if (!p.zones || p.zones.length !== 4) p.zones = [0, 1, 2, 3].map(i => (p.zones || [])[i] || { title: '', image: null, desc: '', info: [] });
  return `<div class="wm-zedit">${p.zones.map((z, i) => `<div class="wm-zed">
    <div class="ops-row"><span class="wm-zno">${i + 1}구역</span>
      <span class="pv" style="${z.image ? `background-image:url('${worldEsc(z.image)}')` : ''}"></span>
      <label class="ops-btn"><i class="fa-solid fa-image"></i> 이미지 삽입<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display:none" onchange="worldPlaceImage(event,'${p.id}:z${i}')"></label>
      ${z.image ? `<button class="ops-btn icon" onclick="worldDraft.places[${pi}].zones[${i}].image=null; renderWorld()" data-tip="이미지 삭제"><i class="fa-solid fa-xmark"></i></button>` : ''}</div>
    <input class="ops-in" style="margin-top:8px;" maxlength="30" placeholder="구역 이름" value="${worldEsc(z.title)}" oninput="worldDraft.places[${pi}].zones[${i}].title=this.value">
    <textarea class="ops-in" style="min-height:140px; margin-top:8px;" maxlength="4000" placeholder="구역 설명을 입력해 주세요. (줄을 바꾸면 문단이 나뉩니다.)" oninput="worldDraft.places[${pi}].zones[${i}].desc=this.value">${worldEsc(z.desc)}</textarea>
    <input class="ops-in" style="margin-top:8px;" maxlength="200" placeholder="참고 (ⓘ 표시와 함께 카드 아래에 나옵니다.)" value="${worldEsc(z.ref || '')}" oninput="worldDraft.places[${pi}].zones[${i}].ref=this.value">
    <div class="ops-hint" style="margin-top:10px;">구역 카드 문구 · 한 줄에 한 문구를 입력해 주세요. 카드를 누를 때마다 무작위로 출력됩니다.</div>
    <textarea class="ops-in" style="min-height:96px; margin-top:6px;" placeholder="예) 항구에서는 갈매기가 우는 소리가 들린다." oninput="worldDraft.places[${pi}].zones[${i}].lines=this.value.split('\\n')">${worldEsc((z.lines || []).join('\n'))}</textarea>
    ${(z.info || []).map((r, k) => `<div class="wm-kv" style="margin-top:6px;"><input class="ops-in" maxlength="20" placeholder="항목" value="${worldEsc(r.k)}" oninput="worldDraft.places[${pi}].zones[${i}].info[${k}].k=this.value">
      <input class="ops-in" maxlength="80" placeholder="내용" value="${worldEsc(r.v)}" oninput="worldDraft.places[${pi}].zones[${i}].info[${k}].v=this.value">
      <button class="ops-btn icon" onclick="worldDraft.places[${pi}].zones[${i}].info.splice(${k},1); renderWorld()"><i class="fa-solid fa-xmark"></i></button></div>`).join('')}
    ${(z.info || []).length < 4 ? `<button class="ops-btn" style="margin-top:6px;" onclick="(worldDraft.places[${pi}].zones[${i}].info=worldDraft.places[${pi}].zones[${i}].info||[]).push({k:'',v:''}); renderWorld()"><i class="fa-solid fa-plus"></i> 정보 추가</button>` : ''}
  </div>`).join('')}</div>`;
}
function worldEditHtml() {
  const d = worldDraft, chs = d.chapters, ps = d.places;
  const chOpts = (sel) => `<option value="0" ${!sel ? 'selected' : ''}>처음부터 공개</option>` + chs.map((c, i) => `<option value="${i + 1}" ${sel === i + 1 ? 'selected' : ''}>Chapter ${i + 1} · ${worldEsc(c.title)}</option>`).join('');
  const chapterRows = chs.map((c, i) => `<div class="ops-card" style="padding:14px 16px;">
      <div class="ops-row"><span class="ops-hint" style="width:44px; flex:none;">Ch. ${i + 1}</span>
        <input class="ops-in" value="${worldEsc(c.title)}" maxlength="40" placeholder="챕터 제목" oninput="worldDraft.chapters[${i}].title=this.value">
        <button class="ops-btn icon" onclick="worldMove('chapters',${i},-1)" data-tip="위로"><i class="fa-solid fa-angle-up"></i></button>
        <button class="ops-btn icon" onclick="worldMove('chapters',${i},1)" data-tip="아래로"><i class="fa-solid fa-angle-down"></i></button>
        <button class="ops-btn icon" onclick="worldDel('chapters',${i})" data-tip="삭제"><i class="fa-solid fa-trash-can"></i></button></div>
      <textarea class="ops-in" style="min-height:70px; margin-top:8px;" maxlength="600" placeholder="챕터 요약 (해금되면 러너에게 공개됩니다.)" oninput="worldDraft.chapters[${i}].summary=this.value">${worldEsc(c.summary)}</textarea></div>`).join('');
  const p = ps[worldEditIdx];
  const placeList = ps.map((x, i) => `<div class="wm-li ${i === worldEditIdx ? 'on' : ''}" onclick="worldEditIdx=${i}; renderWorld()">
      <span class="nm">${worldEsc(x.name)}</span><span class="ch">${x.chapter ? 'Ch. ' + x.chapter : '공개'}</span>
      <button class="ops-btn icon" onclick="event.stopPropagation(); worldMove('places',${i},-1)" data-tip="앞으로"><i class="fa-solid fa-angle-left"></i></button>
      <button class="ops-btn icon" onclick="event.stopPropagation(); worldMove('places',${i},1)" data-tip="뒤로"><i class="fa-solid fa-angle-right"></i></button>
      <button class="ops-btn icon" onclick="event.stopPropagation(); worldDel('places',${i})" data-tip="삭제"><i class="fa-solid fa-trash-can"></i></button></div>`).join('');
  const editor = !p ? emptyHtml('fa-location-dot', '장소를 추가해 주세요', '', null, true) : `
    <div class="ops-field"><span class="lb">아이콘 이미지</span><div class="wm-imgpick"><span class="pv" style="${p.image ? `background-image:url('${worldEsc(p.image)}')` : ''}"></span>
      <label class="ops-btn"><i class="fa-solid fa-image"></i> 이미지 삽입<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display:none" onchange="worldPlaceImage(event,'${p.id}')"></label>
      ${p.image ? `<button class="ops-btn" onclick="worldDraft.places[${worldEditIdx}].image=null; renderWorld()">이미지 삭제</button>` : ''}</div></div>
    <div class="ops-row" style="margin-top:14px;"><div class="ops-field" style="flex:1; margin:0;"><span class="lb">장소 이름</span><input class="ops-in" maxlength="30" value="${worldEsc(p.name)}" oninput="worldDraft.places[${worldEditIdx}].name=this.value"></div>
      <div class="ops-field" style="flex:1; margin:0;"><span class="lb">영문 표기 (지도 위 큰 글자)</span><input class="ops-in" maxlength="30" value="${worldEsc(p.en)}" placeholder="THE SHADOW" oninput="worldDraft.places[${worldEditIdx}].en=this.value"></div></div>
    <div class="ops-row" style="margin-top:14px;"><div class="ops-field" style="flex:1; margin:0;"><span class="lb">한 줄 소개 (지도 아래 작은 글자)</span><input class="ops-in" maxlength="30" value="${worldEsc(p.sub)}" placeholder="GUILD vs GUILD" oninput="worldDraft.places[${worldEditIdx}].sub=this.value"></div>
      <div class="ops-field" style="flex:1; margin:0;"><span class="lb">공개 시점</span><select class="ops-in" onchange="worldDraft.places[${worldEditIdx}].chapter=+this.value">${chOpts(p.chapter)}</select></div></div>
    <div class="ops-field" style="margin-top:14px;"><span class="lb">장소 설명</span><textarea class="ops-in" maxlength="1200" style="min-height:110px;" oninput="worldDraft.places[${worldEditIdx}].desc=this.value">${worldEsc(p.desc)}</textarea></div>
    <div class="ops-field"><span class="lb">정보 칸 (최대 8개)</span>
      ${(p.info || []).map((it, k) => `<div class="wm-kv"><input class="ops-in" maxlength="20" placeholder="항목" value="${worldEsc(it.k)}" oninput="worldDraft.places[${worldEditIdx}].info[${k}].k=this.value">
        <input class="ops-in" maxlength="80" placeholder="내용" value="${worldEsc(it.v)}" oninput="worldDraft.places[${worldEditIdx}].info[${k}].v=this.value">
        <button class="ops-btn icon" onclick="worldDraft.places[${worldEditIdx}].info.splice(${k},1); renderWorld()"><i class="fa-solid fa-xmark"></i></button></div>`).join('')}
      ${(p.info || []).length < 8 ? `<button class="ops-btn" onclick="(worldDraft.places[${worldEditIdx}].info=worldDraft.places[${worldEditIdx}].info||[]).push({k:'',v:''}); renderWorld()"><i class="fa-solid fa-plus"></i> 정보 추가</button>` : ''}</div>
    <div class="ops-field" style="margin-top:6px;"><span class="lb">구역 카드 (1~4구역)</span>${worldZoneEditHtml(p)}</div>`;
  return `<div class="wm-edit">
    <div class="ops-card"><h3><i class="fa-solid fa-book-open"></i> 챕터<span class="sub">
      <select class="ops-in" style="height:32px; width:auto;" onchange="worldDraft.unlocked=+this.value"><option value="0">해금 없음</option>${chs.map((c, i) => `<option value="${i + 1}" ${d.unlocked === i + 1 ? 'selected' : ''}>Ch. ${i + 1}까지 해금</option>`).join('')}</select></span></h3>
      <div style="display:flex; flex-direction:column; gap:10px;">${chapterRows || '<div class="ops-hint">챕터가 없습니다.</div>'}</div>
      <div class="ops-foot"><button class="ops-btn" onclick="worldAddChapter()"><i class="fa-solid fa-plus"></i> 챕터 추가</button></div></div>
    <div class="ops-card"><h3><i class="fa-solid fa-map-location-dot"></i> 장소<span class="sub">지도에는 위 목록 순서대로 왼쪽부터 놓입니다</span></h3>
      <div class="wm-list">${placeList}</div>
      <div class="ops-foot" style="padding-top:10px; margin-top:0; justify-content:flex-start;"><button class="ops-btn" onclick="worldAddPlace()"><i class="fa-solid fa-plus"></i> 장소 추가</button></div>
      <div style="border-top:1px solid var(--line); margin-top:14px; padding-top:16px;">${editor}</div></div>
  </div>`;
}

// PC 사이드바 : 전체 화면 버튼은 맨 위, 나머지 메뉴는 "Team 1" 제목 높이부터 나열
function alignSidebar() {
  const gap = document.getElementById('sidebarAlign');
  if (!gap) return;
  if (window.innerWidth <= 900) { gap.style.height = ''; return; }
  const label = document.getElementById('teamALabel');
  if (!label || !label.offsetParent) return;   // 기숙사 화면 등에서는 마지막 위치 유지
  const lr = label.getBoundingClientRect();
  const sb = gap.parentElement, rowGap = parseFloat(getComputedStyle(sb).rowGap) || 0;
  const first = gap.nextElementSibling;
  const iconH = (first && first.offsetHeight) || 40;
  const top = gap.getBoundingClientRect().top;
  const h = Math.round(lr.top + lr.height / 2 - iconH / 2 - rowGap - top);
  gap.style.height = Math.max(0, h) + 'px';
}
window.addEventListener('resize', alignSidebar);
window.addEventListener('load', alignSidebar);
if (window.ResizeObserver) {
  const _ro = new ResizeObserver(alignSidebar);
  document.addEventListener('DOMContentLoaded', () => { const t = document.querySelector('.topbar.v2'); if (t) _ro.observe(t); alignSidebar(); });
}

// ==================================================================
// PLAY 룸 : LOOP 러닝 시뮬레이션 — 무작위 사건에서 선택을 이어 가며 전쟁 이후까지 살아남습니다.
// 체력(몸)과 정신(마음) 두 가지를 지켜야 해요. 체력 0 = 사망, 정신 0 = 정신 붕괴.
// 변동은 고른 뒤에만 서버가 알려 줘요(고르기 전에는 선택지 문장만 와요).
// 새로 나타나는 글은 한 글자씩 부드럽게 떠오르고, 화면을 누르면 바로 다 보여요.
// 선택지 · 다음 버튼은 화면 아래에 고정(스크롤과 상관없이 늘 누를 수 있게).
// 오른쪽(휴대폰은 아래 기록 버튼) 기록판에는 이번 생애에 지나온 사건이 쌓입니다.
// ==================================================================
const IS_PLAY = BATTLE_TYPE === 'play';
// LOOP : 운영진이 정한 사이트 색과 상관없이 운명 시작 전에는 보라, 시작하면 출신 국가 색(아르카디아 노랑 · 노바 파랑).
var loopPointTheme = IS_PLAY ? 'purple' : null;
function loopSyncPoint(d) {
  // 출신 국가는 BIRTH에서 밝혀져요 : 프롤로그의 서력 역사를 읽는 동안에는 아직 보라.
  const r = d && d.run, c = r && r.country;
  const born = r && !(r.status === 'prologue' && loopProStep[`pro|${r.life_no}`] !== 'birth');
  const before = loopPointTheme;
  loopPointTheme = born && c === 'arcadia' ? 'yellow' : born && c === 'nova' ? 'blue' : 'purple';
  // 탄생(BIRTH)에서 국가가 밝혀지는 순간 : 보라에서 일렁이다가 그 나라 색으로 물들어요(새로고침으로 들어온 때는 바로).
  if (before === 'purple' && loopPointTheme !== 'purple' && r && r.status === 'prologue' && loopDyeArmed) loopDye(loopPointTheme);
  else if (!loopDyeT) applyPointTheme();
  loopDyeArmed = !!(r && r.status === 'prologue' && loopPointTheme === 'purple');
}
var loopDyeArmed = false, loopDyeT = 0;
const LOOP_DYE_RGB = { purple: [164, 141, 255], yellow: [240, 200, 98], blue: [111, 147, 255] };
function loopDye(target) {
  const root = document.documentElement.style, to = LOOP_DYE_RGB[target] || LOOP_DYE_RGB.blue, T = 2400, t0 = performance.now();
  const hsl = (h, s, l) => { s /= 100; l /= 100; const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
    return [0, 8, 4].map(n => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1))))); };
  const set = c => { const v = c.join(','); root.setProperty('--point', `rgb(${v})`); root.setProperty('--point-rgb', v); root.setProperty('--accent-blue', `rgb(${v})`); };
  // 안내는 상태 팝업과 같은 모양으로
  clearTimeout(loopNarrTimer); loopNarrQ = [{ t: '운명의 색이 물듭니다.', ic: 'fa-droplet' }]; loopNarrNext();
  cancelAnimationFrame(loopDyeT);
  const step = now => {
    const p = Math.min(1, (now - t0) / T);
    // 처음 잠깐 아주 살짝 흔들리고(보라 언저리), 곧 그 나라 색으로 느리고 부드럽게 번져요.
    const wave = hsl(255 + 10 * Math.sin(Math.min(p / .25, 1) * Math.PI), 62, 76);
    const k = p < .15 ? 0 : (1 - Math.cos(Math.PI * (p - .15) / .85)) / 2;
    set(wave.map((x, i) => Math.round(x + (to[i] - x) * k)));
    if (p < 1) { loopDyeT = requestAnimationFrame(step); return; }
    loopDyeT = 0; ['--point', '--point-rgb', '--accent-blue'].forEach(k2 => root.removeProperty(k2)); applyPointTheme();
  };
  loopDyeT = requestAnimationFrame(step);
}
if (IS_PLAY) applyPointTheme();
let loopData = null, loopRes = null, loopCountry = null, loopBusy = false, loopLastKey = '', loopTailMs = 0;
const loopShown = new Set();   // 이미 한 번 떠오른 글 : 다시 그릴 때는 애니메이션 없이
const LOOP_CH_MS = 16;         // 글자 사이 간격
const LOOP_RES = { res: ['공명자', '루프와 공명한 사람. 기대와 의무, 관리의 대상이 됩니다.'], non: ['비공명자', '공명하지 못한 사람. 능력의 유무가 삶의 문을 가릅니다.'] };
const LOOP_STAT = { hp: ['체력', 'fa-heart'], mind: ['정신', 'fa-brain'] };
const LOOP_ASSETS = [['wealth', 'fa-coins'], ['intel', 'fa-lightbulb'], ['talent', 'fa-star']];
const LOOP_ASSET_NAME = { wealth: '재산', intel: '지능', talent: '재능', strain: '균열 압력' };
function loopAssetName(k, r) { return k === 'talent' ? ((r && r.talent_name) || '재능') : LOOP_ASSET_NAME[k]; }
function loopGainHtml(g, r) {
  return Object.entries(g || {}).filter(([, v]) => v).map(([k, v]) => `<span class="pl-delta asset ${k} ${v > 0 ? 'up' : 'down'}"><i class="fa-solid ${(LOOP_ASSETS.find(a => a[0] === k) || [0, 'fa-house-crack'])[1]}"></i>${loopEsc(loopAssetName(k, r))} <b>${loopSign(v)}</b></span>`).join('');
}
const LOOP_COUNTRY = { arcadia: ['아르카디아 연방', '공명자가 기득권, 비공명자가 비기득권인 나라.'], nova: ['노바 공화국', '비공명자가 기득권, 공명자가 비기득권인 나라.'] };
function loopPriv(country, res) { return (country === 'arcadia' && res === 'res') || (country === 'nova' && res === 'non'); }
function loopEsc(s) { return mailEsc(s == null ? '' : String(s)); }
function loopSign(d) { return d > 0 ? '+' + d : d < 0 ? '−' + (-d) : '0'; }
// 결과 칩 : 체력 · 정신 각각(둘 다 그대로면 '변화 없음' 하나)
function loopDeltaHtml(dh, dm) {
  const chip = (k, d) => `<span class="pl-delta ${k} ${d > 0 ? 'up' : 'down'}"><i class="fa-solid ${LOOP_STAT[k][1]}"></i>${LOOP_STAT[k][0]} <b>${loopSign(d)}</b></span>`;
  const out = (dh ? chip('hp', dh) : '') + (dm ? chip('mind', dm) : '');
  return `<div class="pl-deltas">${out || '<span class="pl-delta zero"><i class="fa-solid fa-minus"></i>체력 · 정신 그대로</span>'}</div>`;
}
function loopMiniDelta(dh, dm) {
  const one = (k, d) => `<span class="d ${k} ${d > 0 ? 'up' : d < 0 ? 'down' : 'zero'}"><i class="fa-solid ${LOOP_STAT[k][1]}"></i><b>${loopSign(d)}</b></span>`;
  // 변동이 있는 것만 적어요(둘 다 그대로면 아무것도 안 붙어요).
  const out = (dh ? one('hp', dh) : '') + (dm ? one('mind', dm) : '');
  return out ? `<span class="dd">${out}</span>` : '';
}
// 글 묶음을 문단으로 : key가 처음 보이는 글이면 한 글자씩 떠오르게. 다 뜨는 데 걸리는 시간(ms)을 같이 돌려줍니다.
function loopType(lines, key, start, pCls, ms) {
  const CH = ms || LOOP_CH_MS;
  const fresh = key && !loopShown.has(key);
  let t = start || 0;
  const html = (lines || []).map(line => {
    const cls = (pCls || '') + (/^["“]/.test(line) ? ' q' : '');
    if (!fresh) return `<p class="${cls}">${loopEsc(line)}</p>`;
    const chars = Array.from(line).map(ch => {
      const span = `<span class="tc" style="animation-delay:${t}ms">${ch === ' ' ? ' ' : loopEsc(ch)}</span>`;
      t += ch === ' ' ? CH / 2 : CH;
      return span;
    }).join('');
    t += 180;  // 문단 사이 숨 고르기
    return `<p class="${cls}">${chars}</p>`;
  }).join('');
  return { html, end: fresh ? t : (start || 0), fresh };
}
function loopAfter(ms, fresh) { return fresh ? ` style="animation-delay:${ms}ms"` : ''; }
var loopEndPage = {};   // 사망 · 엔딩 장면을 단독 페이지로 넘긴 생애
function renderLoop() {
  const page = document.getElementById('playPage');
  if (!page) return;
  const d = loopData;
  renderLoopLog();
  // 시작 화면 연출이 흐르는 동안에는 다시 그리지 않아요(다시 그리면 타이핑이 끊겨요). 끝나면 저절로 정돈돼요.
  if (d && d.me && !d.run && loopIntroStage === 'opening' && page.querySelector('.pl-intro.opening .pl-quote')) return;
  if (!d || !d.me) {
    page.innerHTML = `<div class="pl-scroll"><div class="pl-wrap">${d ? loopHeadHtml(d) : ''}${!d ? emptyHtml('fa-circle-notch fa-spin', 'LOOP를 불러오는 중이에요') : emptyHtml('fa-infinity', '캐릭터로 입장해 주세요', 'LOOP는 캐릭터마다 자기 생애를 진행해요.')}</div></div>`;
    return;
  }
  const r = d.run;
  const marks = [];  // 이번에 떠오르기 시작한 글 key : 그린 뒤에 '본 것'으로 표시
  let main = '', dock = '';
  loopTailMs = 0;
  if (loopLifePeek != null && (d.lives || [])[loopLifePeek]) {
    // 지난 운명 리플레이 : 그 생애의 사건을 한 장씩(상황 · 고른 답 · 결과), 마지막 장은 끝 장면
    const x = loopReplayHtml(d, loopLifePeek);
    page.innerHTML = `<div class="pl-scroll"><div class="pl-wrap">${loopHeadHtml(d)}${x.main}</div></div>`
      + (x.dock ? `<div class="pl-dock"><div class="pl-dock-in">${x.dock}</div></div>` : '');
    return;
  }
  if (!r) { const x = loopStartHtml(d); main = x.main; dock = x.dock; }
  else if (r.status === 'ended') { const x = loopEndedHtml(d, r); main = x.main; dock = x.dock; }
  else if (r.status === 'prologue') { const x = loopPrologueHtml(d, r, marks); main = x.main; dock = x.dock; }
  else {
    // 사망 · 정신 붕괴 · 엔딩은 따로 한 장 : 먼저 마지막 사건의 결과를 보여 주고, '계속'을 누르면 그 장면만 단독으로.
    const endKey = `${r.life_no}|${r.loop_no}|${r.count}|${r.status}`;
    const isEnd = (r.status === 'dead' && r.death) || (r.status === 'ending' && r.ending);
    if (isEnd && (loopEndPage[endKey] || !r.event)) {
      loopTailMs = 0;
      const x = r.status === 'dead' ? loopDeathHtml(r, marks) : loopEndingHtml(r, marks);
      main = x.main; dock = x.dock;
    } else {
      main = loopStatusHtml(d, r);
      const pk = `${r.life_no}|${r.loop_no}|${(r.log || []).length}`;
      if (loopPeek != null && (!loopPeekKey || loopPeekKey === pk) && (r.log || [])[loopPeek]) {
        loopPeekKey = pk;
        const x = loopPeekHtml(d, r, loopPeek); main += x.main; dock = x.dock;
      } else if (r.event) { if (loopPeek != null) { loopPeek = null; setTimeout(renderLoopLog, 0); } const x = loopEventHtml(r, marks); main += x.main; dock = x.dock; }
      if (isEnd && loopPeek == null) dock = `<div class="pl-actions pl-fade"${loopAfter(loopTailMs + 300, loopTailMs > 0)}><button class="pl-btn primary wide" onclick="event.stopPropagation(); loopEndPage['${endKey}'] = true; loopLastKey = ''; renderLoop()">계속<i class="fa-solid fa-arrow-right"></i></button></div>`;
    }
  }
  const key = r ? `${r.status}|${r.event ? r.event.id : ''}|${r.count}|${r.loop_no}|${loopEndPage[`${r.life_no}|${r.loop_no}|${r.count}|${r.status}`] ? 'p' : ''}` : 'none';
  const changed = key !== loopLastKey;
  const scrollTo = changed ? (r && (r.status === 'result' ? '.pl-result' : r.status === 'dead' ? '.pl-result' : r.status === 'event' && (loopLastKey || window.matchMedia('(max-width:900px)').matches) ? 'top' : '')) : '';
  loopLastKey = key;
  if (changed) page.classList.remove('pl-skip');
  const old = page.querySelector('.pl-scroll');
  const keep = old ? old.scrollTop : 0;
  page.classList.toggle('pl-opening', !r && loopIntroStage === 'opening');
  document.body.classList.toggle('pl-intro-on', !r && loopIntroStage === 'opening');
  page.innerHTML = `<div class="pl-scroll" onclick="loopSkip()"><div class="pl-wrap">${loopHeadHtml(d)}${main}</div></div>`
    + (dock ? `<div class="pl-dock"><div class="pl-dock-in">${dock}</div></div>` : '');
  const sc = page.querySelector('.pl-scroll');
  sc.scrollTop = keep;
  marks.forEach(k => loopShown.add(k));
  if (scrollTo === 'top') setTimeout(() => { const ev = sc.querySelector('.pl-ev'); if (ev) sc.scrollTo({ top: ev.offsetTop - 12, behavior: 'smooth' }); }, 60);
  else if (scrollTo) { const el = sc.querySelector(scrollTo); if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60); }
}
// 떠오르는 중에 화면을 누르면 남은 글과 버튼을 한 번에 보여 줍니다.
function loopSkip() { const p = document.getElementById('playPage'); if (p) p.classList.add('pl-skip'); if (loopIntroStage === 'opening') loopIntroSettle(); }
const LOOP_QUOTE_EN = '— Life and death are inevitable. Destiny is a phenomenon beyond defiance.';
const LOOP_QUOTE_KO = '삶과 죽음은 필연. 운명은 거부할 수 없는 현상이다.';
// 인트로 : 기록 장치가 켜지듯 시스템 줄이 몇 개 찍히고, 문구가 커서와 함께 한 글자씩 기록돼요.
const LOOP_TERM = ['> LOOP.SYS  boot … ok', '> load record : 空歷 / 西暦 22c', '> decode fate.log … 100%'];
// 운명이 끝난 뒤 다시 시작할 때(리트라이) : 같은 연출, 다른 문구
const LOOP_RETRY = {
  term: n => ['> LOOP.SYS  rewind … ok', `> fate.log #${String(n).padStart(3, '0')} : terminated`, '> reload world … retry'],
  en: '— Again. Another world, a different you. Fate waits at the end of the road.',
  ko: '다시. 다른 세계, 다른 당신. 운명은 길 끝에서 기다린다.',
  // 문구 속 한 낱말이 '다른' ↔ '같은'으로 계속 오가요
  swap: { en: ['a different', 'the same'], ko: ['다른 당신', '같은 당신'] },
};
// 바뀌는 낱말을 감싼 문구(HTML)
function loopSwapHtml(text, pair) {
  const t = loopEsc(text);
  if (!pair) return t;
  const a = loopEsc(pair[0]), i = t.lastIndexOf(a);
  // 두 낱말을 같은 칸에 겹쳐 두고 번갈아 보이게 해요 : 칸 폭이 그대로라 뒤 글자가 흔들리지 않아요.
  return i < 0 ? t : t.slice(0, i) + `<span class="pq-swap"><span class="on">${a}</span><span>${loopEsc(pair[1])}</span></span>` + t.slice(i + a.length);
}
setInterval(() => document.querySelectorAll('.pq-swap').forEach(el => {
  const [x, y] = el.children; if (!y) return;
  x.classList.toggle('on'); y.classList.toggle('on');
}), 2400);
// 지금 인트로에 쓸 문구(처음 / 리트라이)
var loopIntroText = { term: LOOP_TERM, en: LOOP_QUOTE_EN, ko: LOOP_QUOTE_KO };
function loopTermType(el, text, ms, done) {
  const caret = document.querySelector('.pl-intro .pq-caret');
  let i = 0;
  const chars = Array.from(text);
  if (caret) el.appendChild(caret);
  const step = () => {
    if (loopIntroStage !== 'opening' || !document.body.contains(el)) return;
    el.insertBefore(document.createTextNode(chars[i++]), caret && caret.parentNode === el ? caret : null);
    if (i < chars.length) setTimeout(step, chars[i - 1] === ' ' ? ms / 2 : ms); else if (done) done();
  };
  step();
}
// 순서대로 기록 : 시스템 줄 → 영어(메인) → 한국어(서브). 걸리는 시간(ms)을 대략 돌려줘요.
function loopSwapWrap() {
  const sw = loopIntroText.swap; if (!sw) return;
  [['.en p', 'en'], ['.ko p', 'ko']].forEach(([sel, k]) => {
    const el = document.querySelector('.pl-intro ' + sel); if (!el || el.querySelector('.pq-swap')) return;
    const caret = el.querySelector('.pq-caret');
    el.innerHTML = loopSwapHtml(loopIntroText[k], sw[k]);
    if (caret) el.appendChild(caret);
  });
}
function loopTermRun() {
  const q = s => document.querySelector('.pl-intro.opening ' + s);
  const lines = [...document.querySelectorAll('.pl-intro.opening .pq-term p')];
  const T = loopIntroText;
  const seq = lines.map((el, i) => [el, T.term[i], 16, 260]).concat([[q('.en p'), T.en, 42, 500], [q('.ko p'), T.ko, 60, 0]]);
  const run = (k) => {
    if (k >= seq.length) return;
    const [el, text, ms, pause] = seq[k];
    if (!el) return;
    setTimeout(() => loopTermType(el, text, ms, () => run(k + 1)), k ? pause : 500);   // 연출 중에는 낱말이 바뀌지 않아요(정돈된 뒤부터)
  };
  run(0);
  return 500 + T.term.join('').length * 16 + 3 * 260 + T.en.length * 42 + 500 + T.ko.length * 60;
}
// 시작 화면 연출 단계 : opening(문구만) → settling(작아지며 나머지가 떠오름) → done
var loopIntroStage = 'done', loopIntroT = null;
function loopIntroTimer(ms) { clearTimeout(loopIntroT); loopIntroT = setTimeout(loopIntroSettle, ms); }
function loopIntroSettle() {
  clearTimeout(loopIntroT);
  if (loopIntroStage !== 'opening') return;
  loopIntroStage = 'settling';
  const en = document.querySelector('.pl-intro .en p'); if (en) { en.textContent = loopIntroText.en; en.lang = 'en'; en.className = ''; }
  const ko = document.querySelector('.pl-intro .ko p'); if (ko) { ko.textContent = loopIntroText.ko; ko.className = ''; }
  loopSwapWrap();
  document.querySelectorAll('.pl-intro .pq-caret, .pl-intro .pq-term').forEach(e => e.remove());
  const box = document.querySelector('.pl-intro'), page = document.getElementById('playPage');
  if (box) { box.classList.remove('opening'); box.classList.add('settling'); }
  if (page) page.classList.remove('pl-opening');
  document.body.classList.remove('pl-intro-on');
  loopIntroT = setTimeout(() => { loopIntroStage = 'done'; const b = document.querySelector('.pl-intro'); if (b) { b.classList.remove('settling'); b.classList.add('done'); } }, 1400);
}
function loopTopSub(d) {
  const el = document.getElementById('plTopSub'); if (!el) return;
  const r = d && d.run, e = r && r.era;
  el.textContent = r && e && ['event', 'result', 'dead'].includes(r.status) ? `${e.no}. ${e.name}` : '러닝 시뮬레이션';
}
function loopWarStarted(r) { return !!(r && r.era && r.era.id >= 4); }
function loopHeadHtml(d) {
  // 제목은 왼쪽, 이번 생애 정보는 아래 한 줄(점으로 구분), 새로 시작은 오른쪽 위 작은 버튼.
  const r = d.run;
  const country = (r && r.country) || d.country, faction = (r && r.faction) || d.faction;
  // 프롤로그(BIRTH)에서는 같은 정보를 태그로 보여 주니 여기서는 숨깁니다.
  // 진영은 전쟁(IV 시대)부터, 몇 번째 생애인지는 루프에 들어간 뒤부터만 보여요.
  const it = [];
  if (r && r.status !== 'prologue') {
    if (country) it.push(`<span class="c ${country}"><i></i>${loopEsc((LOOP_COUNTRY[country] || [''])[0])}</span>`);
    it.push(`<span>${loopEsc((LOOP_RES[r.res] || [''])[0])}</span><span class="${r.privileged ? 'up' : ''}">${r.privileged ? '기득권' : '비기득권'}</span>`);
    if (faction && loopWarStarted(r)) it.push(`<span>${loopEsc(faction)}</span>`);
    if (r.view) it.push(`<span>문명관 ${loopEsc(r.view.name)}</span>`);
    if (r.loop_no) it.push(`<span>${r.life_no}번째 생애</span><span class="up"><i class="fa-solid fa-infinity"></i> 루프 ${r.loop_no}</span>`);
  }
  const playing = r && !['prologue', 'ended'].includes(r.status) && r.era;
  const folded = playing && loopFold;
  const fold = playing ? `<button class="pl-restart pl-fold" onclick="event.stopPropagation(); loopToggleFold()"><i class="fa-solid ${folded ? 'fa-chevron-down' : 'fa-chevron-up'}"></i><span>${folded ? '펼치기' : '접기'}</span></button>` : '';
  if (folded) { it.length = 0; it.push(loopMiniHtml(d, r)); }
  const restart = fold;   // '새로 시작'은 기록판(Log) 머리로 옮겼어요
  return `<div class="pl-box glow pl-head ${folded ? 'folded' : ''}"><div class="pl-head-top"><div class="pl-logo"><b>Loop</b><span>러닝 시뮬레이션</span></div>
    ${it.length ? `<div class="pl-meta">${it.join('')}</div>` : '<div class="pl-meta-gap"></div>'}${restart}</div></div>`;
}
// 진행 중인 생애를 버리고 처음(공명 여부 고르기)부터. 지난 생애 기록은 남아요. 기록은 이 브라우저에만 저장돼요.
// 끝난 운명에서 다시(Loop) : 시작 연출을 리트라이 문구로 다시 보여 줘요.
function loopRetry() {
  loopShown.delete('intro|en'); loopShown.delete('intro|ko'); loopProStep = {};
  loopEmit('loop_reset');
}
function loopRestart() {
  uiConfirm('지금 기록된 인물의 삶을 버리고, 다른 인물로 새로 시작할까요?', { title: '초기화', okText: '초기화', icon: 'fa-eraser', danger: true }).then(ok => {
    if (!ok) return;
    loopShown.clear(); loopProStep = {}; loopLifePeek = null; loopEndCache = {}; loopLifeFull = {};
    loopEmit('loop_reset', { force: true });
  });
}
// 상태판 접기 : 접으면 헤더에 체력 · 정신 · 시대만. 기기마다 기억해요(처음엔 휴대폰은 접힘, PC는 펼침).
var loopFold = (() => { try { const v = localStorage.getItem('loopFold'); if (v != null) return v === '1'; } catch (e) {} return window.matchMedia('(max-width:900px)').matches; })();
function loopToggleFold() { loopFold = !loopFold; try { localStorage.setItem('loopFold', loopFold ? '1' : '0'); } catch (e) {} renderLoop(); }
function loopMiniHtml(d, r) {
  const dots = (k, v, max) => `<span class="pm ${k} ${v <= 1 ? 'low' : ''}"><i class="fa-solid ${LOOP_STAT[k][1]}"></i><span class="pm-d">${Array.from({ length: max }, (_, i) => `<i class="${i < v ? 'on' : ''}"></i>`).join('')}</span><b>${v}</b></span>`;
  const e = r.era || {};
  return `<span class="pl-mini">${dots('hp', r.hp, d.hp_max || 5)}${dots('mind', r.mind, d.mind_max || 5)}<span class="pm era"><i class="fa-solid fa-hourglass-half"></i><b>${loopEsc(e.no || '')}</b><em>${Math.min(r.era_step + (r.status === 'event' ? 1 : 0), r.era_len)}/${r.era_len}</em></span></span>`;
}
function loopStatusHtml(d, r) {
  loopNarrHtml(r);
  if (loopFold) return '';
  const bar = (k, v, max) => `<div class="pl-hp ${k} ${v <= 1 ? 'low' : ''}">${Array.from({ length: max }, (_, i) => `<i class="${i < v ? 'on' : ''}"></i>`).join('')}<b>${v}<span> / ${max}</span></b></div>`;
  const nowIdx = r.eras.indexOf(r.era.id);
  const eraById = Object.fromEntries((d.eras || []).map(e => [e.id, e]));
  const eras = r.eras.map((id, i) => {
    const e = eraById[id] || { no: id };
    const st = i < nowIdx || (r.status === 'ending' && !(r.ending || {}).paused) ? 'done' : i === nowIdx && r.status !== 'ending' ? 'now' : (r.closed_eras || []).includes(id) ? 'locked' : '';
    if (st === 'locked') return `<span class="pl-era locked" data-tip="다음 업데이트에서 공개돼요"><i class="fa-solid fa-lock"></i>${e.no}</span>`;
    return `<span class="pl-era ${st}">${e.no}${st === 'now' ? `<em><span class="nm">${loopEsc(e.name)} · </span>${Math.min(r.era_step + (r.status === 'event' ? 1 : 0), r.era_len)}/${r.era_len}</em>` : ''}</span>`;
  }).join('');
  const mood = [...(r.mood || []), ...(r.mood_mind || [])];
  const A = r.assets || {};
  const note = r.country === 'nova' ? '노바는 지능과 기술이 중요해요' : r.country === 'arcadia' ? '아르카디아는 재산과 재능이 중요해요' : '';
  const sv = r.strain || 0, sm = r.strain_max || 10;
  const strainText = sv === 0 ? '지구는 아직 조용합니다.' : sv < sm * 0.3 ? '땅이 가끔 뒤척입니다.' : sv < sm * 0.6 ? '문명이 커질수록 재난이 잦아집니다.' : '지구가 인류를 덜어 내려 합니다.';
  const cell = (cls, k, ic, label, body, tip) => `<div class="ps-c ${cls}"><span class="pl-k"${tip ? ` data-tip="${loopEsc(tip)}"` : ''}><i class="fa-solid ${ic}"></i>${label}</span><div class="ps-v">${body}</div></div>`;
  // PC : 두 칸(왼쪽 체력 · 정신 · 상태 / 오른쪽 자원 · 균열 · 시대) — 휴대폰 : 체력 · 정신 나란히, 나머지는 한 줄씩
  return `<div class="pl-box pl-stat">
    ${cell('hp', 'hp', LOOP_STAT.hp[1], LOOP_STAT.hp[0], bar('hp', r.hp, d.hp_max || 5))}
    ${cell('assets', 'a', 'fa-gem', '자원', `<div class="pl-assets">${LOOP_ASSETS.map(([k, ic]) => `<span class="pl-asset ${k}"><i class="fa-solid ${ic}"></i>${k === 'talent' ? loopEsc(r.talent_name || '재능') : LOOP_ASSET_NAME[k]}<b>${A[k] || 0}</b></span>`).join('')}</div>`, note)}
    ${cell('mind', 'mind', LOOP_STAT.mind[1], LOOP_STAT.mind[0], bar('mind', r.mind, d.mind_max || 5))}
    ${cell('strain', 's', 'fa-house-crack', '균열', `<div class="pl-strain ${sv >= sm * 0.6 ? 'hot' : ''}">${Array.from({ length: sm }, (_, i) => `<i class="${i < sv ? 'on' : ''}"></i>`).join('')}<span>${strainText}</span></div>`, strainText)}
    ${cell('eras', 'e', 'fa-hourglass-half', '시대', `<div class="pl-eras">${eras}</div>`)}</div>`;
}
// 몸 · 마음 상태 문장 : 화면에 붙여 두지 않고, 상태가 바뀔 때만 잠깐 팝업으로 알려 줘요(처음 들어왔을 때는 조용히).
var loopNarrLast = null, loopNarrTimer = null, loopNarrQ = [];
const loopSentences = lines => lines.join(' ').split(/(?<=[.!?。…])\s+/).map(t => t.trim()).filter(Boolean);
function loopNarrHtml(r) {
  // 체력 · 정신 각각 문장 단계가 바뀐 순간(그 지점을 넘겼을 때)에만, 새로 생긴 문장만 한 번씩.
  const key = `${r.life_no}|${r.loop_no}`, hp = (r.mood || []).join(' '), mind = (r.mood_mind || []).join(' ');
  const prev = loopNarrLast; loopNarrLast = { key, hp, mind };
  if (!prev || prev.key !== key) return '';
  const fresh = [];
  [[hp, prev.hp], [mind, prev.mind]].forEach(([now, was]) => {
    if (!now || now === was) return;
    const old = loopSentences([was]);
    loopSentences([now]).forEach(t => { if (!old.includes(t) && !fresh.includes(t)) fresh.push(t); });
  });
  if (!fresh.length) return '';
  const low = r.hp <= 1 || r.mind <= 1;
  fresh.forEach(t => { if (!loopNarrQ.some(x => x.t === t)) loopNarrQ.push({ t, low }); });
  const el = document.getElementById('loopNarrPop');
  if (!el || !el.classList.contains('on')) { clearTimeout(loopNarrTimer); loopNarrTimer = setTimeout(loopNarrNext, 80); }   // 화면을 다 그린 뒤 자리 잡기
  return '';
}
// 팝업은 아래쪽 고정 버튼(다음 사건 · 선택지) 바로 위에 떠요.
function loopNarrPlace(el) {
  const dock = document.querySelector('#playPage .pl-dock');
  const r = dock && dock.offsetParent ? dock.getBoundingClientRect() : null;
  const top = r ? r.top : window.innerHeight - 36;
  el.style.bottom = Math.max(16, Math.round(window.innerHeight - top + 14)) + 'px';
  // 가로 가운데도 아래 버튼(다음 사건 · 선택지)의 가운데에 맞춰요.
  el.style.left = r ? Math.round(r.left + r.width / 2) + 'px' : '50%';
}
function loopNarrNext() {
  let el = document.getElementById('loopNarrPop');
  if (!el) { el = document.createElement('div'); el.id = 'loopNarrPop'; el.onclick = () => { loopNarrQ = []; el.classList.remove('on'); }; document.body.appendChild(el); }
  const it = loopNarrQ.shift();
  if (!it) { el.classList.remove('on'); return; }
  const show = () => {
    el.className = it.low ? 'low' : '';
    el.innerHTML = `<i class="fa-solid ${it.ic || 'fa-feather-pointed'}"></i><p>${loopEsc(it.t)}</p>`;
    loopNarrPlace(el); void el.offsetWidth; el.classList.add('on');
    loopNarrTimer = setTimeout(() => { el.classList.remove('on'); loopNarrTimer = setTimeout(loopNarrNext, 380); }, 2600);
  };
  if (el.classList.contains('on')) { el.classList.remove('on'); loopNarrTimer = setTimeout(show, 380); } else show();
}
function loopEventHtml(r, marks) {
  const ev = r.event, res = r.result;
  const done = r.status !== 'event';
  const base = `${r.life_no}|${r.loop_no}|${r.count - (done ? 1 : 0)}|${ev.id}`;
  const story = loopType(ev.story, 'ev|' + base, 450);
  if (story.fresh) marks.push('ev|' + base);
  loopTailMs = story.end;
  const first = !r.loop_no && (r.count === 0 || (r.count === 1 && done));
  const origin = false && first && r.country ? `<div class="pl-memory pl-origin pl-fade"${loopAfter(0, story.fresh)}><i class="fa-solid fa-dice"></i> 이번 생애, 당신은 <b>${loopEsc((LOOP_COUNTRY[r.country] || [''])[0])}</b>에서 태어났습니다. ${loopEsc((LOOP_RES[r.res] || [''])[0])}는 이 나라의 <b>${r.privileged ? '기득권' : '비기득권'}</b>입니다.</div>` : '';
  const memory = r.memory && r.loop_no && (r.count === 0 || (r.count === 1 && done)) ? `<div class="pl-memory pl-fade"${loopAfter(story.end, story.fresh)}><i class="fa-solid fa-infinity"></i> 대부분의 기억은 흐릿합니다. 다만 한 장면만은 선명합니다 — <b>${loopEsc(r.memory)}</b>.</div>` : '';
  let resHtml = '', dock = '';
  if (!done) {
    const lock = c => (c.need || []).some(x => !x.ok);
    // 선택지 조건 : 쓰는(소모) 게 아니라 '이만큼 있어야 고를 수 있다'는 조건이라, 충족 / 부족으로 보여요
    const need = c => (c.need || []).map(x => `<em class="${x.ok ? 'ok' : ''}"><i class="fa-solid ${(LOOP_ASSETS.find(a => a[0] === x.k) || [])[1]}"></i>${loopEsc(x.name)} ${x.ok ? '충족' : '부족'}</em>`).join('');
    const canSolve = (r.solve || []).filter(x => x.ok);
    const solve = canSolve.length ? `<div class="pl-solve pl-fade"${loopAfter(story.end + 200, story.fresh)}><span><i class="fa-solid fa-key"></i> 해결하기</span>${canSolve.map(x => `<button class="pl-sv" ${loopBusy ? 'disabled' : ''} onclick="loopEmit('loop_solve', { event: '${ev.id}', kind: '${x.k}' })"><i class="fa-solid ${x.k === 'wealth' ? 'fa-coins' : 'fa-lightbulb'}"></i>${loopEsc(x.name)} ${x.cost} 쓰기</button>`).join('')}</div>` : '';
    // 해결하기(쓸 수 있을 때만)가 선택지 위에 먼저, 그다음 A · B · C
    const chAt = i => story.end + 200 + (canSolve.length ? 160 : 0) + i * 140;
    dock = `${solve}<div class="pl-choices">${ev.choices.map((c, i) => `<button class="pl-ch pl-fade ${lock(c) ? 'locked' : ''}"${loopAfter(chAt(i), story.fresh)} ${loopBusy || lock(c) ? 'disabled' : ''} onclick="loopChoose('${ev.id}', ${i})"><span class="k">${lock(c) ? '<i class="fa-solid fa-lock"></i>' : 'ABC'[i]}</span><span class="lbl">${loopEsc(c.label)}${need(c) ? `<span class="pl-need">${need(c)}</span>` : ''}</span></button>`).join('')}</div>`;
  } else if (res) {
    const rk = 'res|' + base;
    const rt = loopType(res.text, rk, 200);
    if (rt.fresh) marks.push(rk);
    let tw = '', tt_end = rt.end;
    if (res.twist) {
      const tt = loopType([res.twist.text], rk + '|tw', rt.end + 600);
      tw = `<div class="tw ${res.twist.kind}"><i class="fa-solid ${res.twist.kind === 'purge' ? 'fa-house-crack' : res.twist.kind === 'risk' ? 'fa-bolt' : 'fa-leaf'} pl-fade"${loopAfter(rt.end + 520, rt.fresh)}></i>${tt.html}</div>`;
      if (tt.fresh) marks.push(rk + '|tw');
      tt_end = tt.end;
    }
    const picked = res.solved ? { label: `${loopAssetName(res.solved, r)} ${res.cost}을(를) 써서 해결했다.` } : (ev.choices[res.choice] || {});
    loopTailMs = rt.fresh ? (res.twist ? tt_end + 200 : rt.end + 450) : 0;
    resHtml = `<div class="pl-picked"><span class="k">${res.solved ? `<i class="fa-solid ${res.solved === 'wealth' ? 'fa-coins' : 'fa-lightbulb'}"></i>` : 'ABC'[res.choice]}</span>${loopEsc(picked.label)}</div>
      <div class="pl-result">${rt.html}<div class="pl-fade pl-res-fx"${loopAfter(rt.end + 150, rt.fresh)}>${res.solved ? `<div class="pl-deltas">${loopGainHtml(res.gain, r)}</div>` : loopDeltaHtml(res.delta, res.dmind).replace('</div>', loopGainHtml(res.gain, r) + '</div>')}</div>${tw}</div>`;
    if (r.status === 'result') dock = `<div class="pl-actions pl-fade"${loopAfter(loopTailMs, rt.fresh)}><button class="pl-btn primary wide" ${loopBusy ? 'disabled' : ''} onclick="loopEmit('loop_next')">다음 사건<i class="fa-solid fa-arrow-right"></i></button></div>`;
  }
  return { main: `<div class="pl-box glow pl-ev"><div class="pl-ev-meta pl-fade"${loopAfter(0, story.fresh)}><span class="pl-ev-no">EVENT ${String(r.count + (done ? 0 : 1)).padStart(2, '0')}</span><span>${loopEsc(ev.era.no)}. ${loopEsc(ev.era.name)}</span></div>
    ${origin}<h2 class="pl-ev-title pl-fade"${loopAfter(120, story.fresh)}>${loopEsc(ev.title)}</h2><div class="pl-story">${story.html}</div>${memory}</div>${resHtml ? `<div class="pl-answer">${resHtml}</div>` : ''}`, dock };
}
// 지난 사건 다시 보기 : 읽기만 해요(고른 결과 · 깎인 체력 · 정신은 그대로).
var loopPeek = null, loopPeekKey = '';
function loopPeekGo(i) {
  loopPeek = i; loopPeekKey = ''; renderLoop();
  if (document.body.classList.contains('m-chat-open') && typeof toggleMobileChat === 'function') toggleMobileChat(false); const sc = document.querySelector('#playPage .pl-scroll'); if (sc) sc.scrollTop = 0; }
function loopPeekHtml(d, r, i) {
  const l = r.log[i], eraBy = Object.fromEntries((d.eras || []).map(e => [e.id, e])), e = eraBy[l.era] || {};
  const cur = r.log.length - (r.status === 'event' ? 0 : 1);
  const story = loopType(l.story || [], null), res = loopType(l.text || [], null);
  const tw = l.twist && l.twist.text ? `<div class="tw ${l.twist.kind}"><i class="fa-solid ${l.twist.kind === 'purge' ? 'fa-house-crack' : l.twist.kind === 'risk' ? 'fa-bolt' : 'fa-leaf'}"></i><p>${loopEsc(l.twist.text)}</p></div>` : '';
  const fx = l.solved ? `<div class="pl-deltas">${loopGainHtml(l.gain, r)}</div>` : loopDeltaHtml(l.delta, l.dmind).replace('</div>', loopGainHtml(l.gain, r) + '</div>');
  const main = `<div class="pl-box glow pl-ev peek"><div class="pl-ev-meta"><span class="pl-ev-no">EVENT ${String(i + 1).padStart(2, '0')}</span><span>${loopEsc(e.no || '')}. ${loopEsc(e.name || '')}</span><span class="pl-peek-tag"><i class="fa-solid fa-clock-rotate-left"></i>지난 사건</span></div>
    <h2 class="pl-ev-title">${loopEsc(l.title)}</h2><div class="pl-story">${story.html || '<p class="q">기록이 흐릿합니다.</p>'}</div>
    </div><div class="pl-answer"><div class="pl-picked"><span class="k">${l.solved ? `<i class="fa-solid ${l.solved === 'wealth' ? 'fa-coins' : 'fa-lightbulb'}"></i>` : 'ABC'[l.pick] || '·'}</span>${loopEsc(l.choice)}</div>
    ${res.html || fx || tw ? `<div class="pl-result">${res.html}<div class="pl-res-fx">${fx}</div>${tw}</div>` : ''}</div>`;
  const dock = `<div class="pl-actions two peek"><button class="pl-btn" ${i <= 0 ? 'disabled' : ''} onclick="event.stopPropagation(); loopPeekGo(${i - 1})"><i class="fa-solid fa-chevron-left"></i>이전 사건</button>
    <button class="pl-btn primary" onclick="event.stopPropagation(); ${i + 1 < cur ? `loopPeekGo(${i + 1})` : 'loopPeek = null; renderLoop()'}">${i + 1 < cur ? '다음 사건' : '지금으로 돌아가기'}<i class="fa-solid fa-chevron-right"></i></button></div>`;
  return { main, dock };
}
// 끝 장면(사망 · 엔딩 · 기록됨)은 모두 같은 카드 하나 : 글자 자리 그대로, 버튼도 카드 안에서 바로 아래.
var loopEndCache = {};   // 이번 운명의 끝 장면(기록된 뒤에도 같은 글을 그대로 보여 주려고)
function loopEndCardHtml(o) {
  return `<div class="pl-box glow pl-death pl-endpage ${o.cls || ''} ${o.still ? 'still' : ''}"><div class="t">${o.tag}</div><h3>${loopEsc(o.title)}</h3>
    <div class="pl-end-text">${o.text}</div>
    <div class="pl-end-foot pl-fade"${o.after || ''}>${o.meta ? `<div class="at">${o.meta}</div>` : ''}${o.actions ? `<div class="pl-end-acts">${o.actions}</div>` : ''}${o.note ? `<div class="pl-end-note">${o.note}</div>` : ''}</div></div>`;
}
function loopDeathHtml(r, marks) {
  const d = r.death, k = `death|${r.life_no}|${r.loop_no}|${r.count}`;
  const tx = loopType(d.text, k, loopTailMs + 500);
  if (tx.fresh) marks.push(k);
  const tag = d.kind === 'loop' ? 'LOOP' : d.kind === 'mind' ? 'COLLAPSE' : 'DEATH';
  const cls = `${d.kind === 'loop' ? 'loop' : ''} ${d.kind === 'mind' ? 'mind' : ''}`;
  const meta = `${loopEsc(d.at)}에서 · ${r.count}개의 사건을 지나왔습니다`;
  loopEndCache[`${r.life_no}|${r.loop_no}`] = { tag, cls, title: d.title, text: d.text, meta };
  const btn = (mode, ic, t, primary) => `<button class="pl-btn ${primary ? 'primary' : ''}" ${loopBusy ? 'disabled' : ''} onclick="loopEmit('loop_death', { mode: '${mode}' })"><i class="fa-solid ${ic}"></i>${t}</button>`;
  return { main: loopEndCardHtml({ tag, cls, title: d.title, text: tx.html, meta, after: loopAfter(tx.end + 200, tx.fresh),
    actions: r.loop_open ? btn('end', 'fa-book', '기록 남기고 끝내기') + btn('loop', 'fa-infinity', '루프 진입', true) : btn('end', 'fa-book', '기록 남기기', true),
    note: r.loop_open ? '루프 진입 : 기억 일부를 안고 전쟁 이전의 평행 세계에서 다시 시작합니다' : '' }), dock: '' };
}
// 프롤로그 : 서력의 역사 → 탄생 → 문명관. 고르는 것 없이 자동으로 정해진 나레이션이에요.
// 프롤로그는 두 장 : 서력의 역사만 먼저 보여 주고, '다음'을 누르면 탄생(출신 · 공명 · 집안 · 문명관).
var loopProStep = {};
function loopPrologueHtml(d, r, marks) {
  const P = r.prologue || {}, k = `pro|${r.life_no}`;
  if (loopProStep[k] !== 'birth') {
    const h = loopType(P.history, k + '|h', 300);
    if (h.fresh) marks.push(k + '|h');
    return { main: `<div class="pl-box glow pl-pro"><div class="pl-ev-meta"><span class="pl-ev-no">PROLOGUE</span><span>서력의 기억</span></div>${h.html}</div>`,
      dock: `<div class="pl-actions pl-fade"${loopAfter(h.end + 300, h.fresh)}><button class="pl-btn primary wide" onclick="event.stopPropagation(); loopProStep['${k}'] = 'birth'; loopSyncPoint(loopData); renderLoop()">다음<i class="fa-solid fa-arrow-right"></i></button></div>` };
  }
  const b = loopType(P.birth, k + '|b', 300);
  const v = loopType(P.view, k + '|v', b.end + 500);
  [b, v].forEach((x, i) => { if (x.fresh) marks.push(k + '|' + 'bv'[i]); });
  const tags = [`<span class="c ${r.country}"><i></i>${loopEsc((LOOP_COUNTRY[r.country] || [''])[0])}</span>`, `<span>${loopEsc((LOOP_RES[r.res] || [''])[0])}</span>`,
    `<span class="${r.privileged ? 'up' : ''}">${r.privileged ? '기득권' : '비기득권'}</span>`].concat(r.view ? [`<span><i class="fa-solid fa-earth-asia"></i>문명관 ${loopEsc(r.view.name)}</span>`] : []);
  return { main: `<div class="pl-box glow pl-pro"><div class="pl-ev-meta"><span class="pl-ev-no">BIRTH</span>${r.loop_no ? `<span>${r.life_no}번째 생애</span>` : ''}</div>
      <div class="pl-tags">${tags.join('')}</div>${b.html}
      ${r.view ? `<div class="pl-view pl-fade"${loopAfter(b.end + 300, b.fresh)}><span class="pl-view-k"><i class="fa-solid fa-earth-asia"></i> 문명관 · ${loopEsc(r.view.name)}</span>${v.html}</div>` : ''}</div>`,
    dock: `<div class="pl-actions pl-fade"${loopAfter(v.end + 300, v.fresh)}><button class="pl-btn primary wide" ${loopBusy ? 'disabled' : ''} onclick="loopEmit('loop_begin')">삶을 시작한다<i class="fa-solid fa-arrow-right"></i></button></div>` };
}
function loopEndingHtml(r, marks) {
  const e = r.ending, k = `ending|${r.life_no}|${r.loop_no}`;
  const tx = loopType(e.text, k, 400);
  if (tx.fresh) marks.push(k);
  const tag = e.paused ? 'TO BE CONTINUED' : 'SURVIVED', meta = `${r.count}개의 매듭을 잇습니다 · 남은 체력 ${r.hp} · 정신 ${r.mind}`;
  loopEndCache[`${r.life_no}|${r.loop_no}`] = { tag, cls: 'loop', title: e.title, text: e.text, meta };
  const b = (ev, ic, t, primary) => `<button class="pl-btn ${primary ? 'primary' : ''}" ${loopBusy ? 'disabled' : ''} onclick="loopEmit('${ev}')"><i class="fa-solid ${ic}"></i>${t}</button>`;
  return { main: loopEndCardHtml({ tag, cls: 'loop', title: e.title, text: tx.html, meta, after: loopAfter(tx.end + 200, tx.fresh),
    actions: r.can_resume ? b('loop_finish', 'fa-book', '여기서 기록 남기기') + b('loop_resume', 'fa-forward', '이어서 살기', true) : b('loop_finish', 'fa-book', '기록 남기기', true),
    note: e.paused && !r.can_resume ? '기록을 남기지 않고 두면, 다음 이야기가 열릴 때 이 자리에서 이어서 살 수 있어요.' : '' }), dock: '' };
}
// 기록된 뒤 : 방금 본 끝 장면과 같은 카드 그대로, '기록됨' 표시와 다음 운명(Loop) 버튼만 바뀌어요.
function loopEndedHtml(d, r) {
  const last = (d.lives || [])[0] || {};
  const c = loopEndCache[`${r.life_no}|${r.loop_no}`];
  const survived = r.outcome === 'survived' || r.outcome === 'paused';
  const summary = `${last.count || 0}개의 사건 · ${last.loop_no ? `루프 ${last.loop_no} · ` : ''}${survived ? '생존' : loopEsc((last.death || {}).at || '') + '에서 ' + ((last.death || {}).kind === 'mind' ? '정신 붕괴' : '사망')}`;
  const actions = `<button class="pl-btn primary" ${loopBusy ? 'disabled' : ''} onclick="loopRetry()"><i class="fa-solid fa-infinity"></i>새 운명 (Loop)</button>`;
  const stamp = '<span class="pl-end-stamp"><i class="fa-solid fa-book"></i>기록에 남았습니다</span>';
  if (c) return { main: loopEndCardHtml({ tag: c.tag, cls: c.cls, title: c.title, text: (c.text || []).map(t => `<p class="${/^["“]/.test(t) ? 'q' : ''}" style="opacity:1;animation:none">${loopEsc(t)}</p>`).join(''),
    meta: `${stamp}${c.meta}`, actions, still: true }), dock: '' };
  return { main: loopEndCardHtml({ tag: survived ? 'SURVIVED' : 'RECORD', cls: survived ? 'loop' : '',
    title: r.outcome === 'paused' ? '여기까지 살아남았습니다' : survived ? '전쟁 이후에 도달했습니다' : '운명이 끝났습니다',
    text: '', meta: `${stamp}${summary}`, actions, still: true }), dock: '' };
}
function loopStartHtml(d) {
  // 출신 국가는 생애마다 무작위 : 고르는 건 공명 여부뿐이에요.
  const RES_ICON = { res: ['fa-wave-square', 'RESONANT'], non: ['fa-circle-half-stroke', 'NON-RESONANT'] };
  // 한 번 기록을 남긴 공명 여부는 고정 : 그 카드만 보여요.
  const res = Object.entries(LOOP_RES).filter(([k]) => k === 'res').map(([k, [t, ds]]) => `<div class="prc ${k}">
      <span class="prc-ic"><i class="fa-solid ${RES_ICON[k][0]}"></i></span>
      <span class="prc-t"><small>${RES_ICON[k][1]}</small><b>${t}</b></span>
      <span class="prc-d">${ds}</span>
      <button class="prc-go" ${loopBusy ? 'disabled' : ''} onclick="event.stopPropagation(); loopRes='${k}'; loopEmit('loop_start', { res: '${k}' })">운명 시작<i class="fa-solid fa-arrow-right"></i></button></div>`).join('');
  // 연출 : 처음에는 문구만 가운데에 크게(영어가 메인, 한국어가 서브) → 잠시 뒤 작아지며 제자리로 → 제목 · 카드가 떠올라요.
  // 로그인 화면이 아직 덮고 있으면 연출을 아껴 두었다가, 화면이 보이는 순간 시작해요.
  const gate = document.getElementById('loginGate');
  if (!loopShown.has('intro|en') && ((gate && gate.classList.contains('on')) || document.documentElement.classList.contains('booting'))) {
    setTimeout(() => { if (loopData && !loopData.run) renderLoop(); }, 200);
    return { main: '<div class="pl-box pl-intro opening"></div>', dock: '' };
  }
  const fresh = !loopShown.has('intro|en');
  const tries = (d.lives || []).length;
  loopIntroText = tries ? { term: LOOP_RETRY.term(tries), en: LOOP_RETRY.en, ko: LOOP_RETRY.ko, swap: LOOP_RETRY.swap } : { term: LOOP_TERM, en: LOOP_QUOTE_EN, ko: LOOP_QUOTE_KO };
  const sw = loopIntroText.swap || {};
  let enHtml = `<p>${loopSwapHtml(loopIntroText.en, sw.en)}</p>`, koHtml = `<p>${loopSwapHtml(loopIntroText.ko, sw.ko)}</p>`;
  if (fresh) {
    // 영어(메인) : 여러 나라 말로 빠르게 바뀌다가 영어로 멈춰요. 한국어(서브) : 그다음 조용히 떠올라요.
    loopShown.add('intro|en'); loopShown.add('intro|ko'); loopIntroStage = 'opening';
    enHtml = '<p></p>';
    koHtml = '<p></p>';
    setTimeout(() => { const t = loopTermRun(); loopIntroTimer(t + 1800); }, 0);
  }
  return { main: `<div class="pl-box glow pl-intro ${loopIntroStage}">
    <div class="pl-intro-top"><div class="pl-ev-meta"><span class="pl-ev-no">NEW LIFE</span></div>
    <h2 class="pl-ev-title">${tries ? `${tries + 1}번째 운명을 시작합니다` : '운명을 시작합니다'}</h2></div>
    ${loopIntroStage === 'opening' ? `<div class="pq-term">${loopIntroText.term.map(() => '<p></p>').join('')}</div>` : ''}
    <div class="pl-quote"><div class="en">${enHtml}</div><div class="ko">${koHtml}</div>${loopIntroStage === 'opening' ? '<span class="pq-caret"></span>' : ''}</div>
    <div class="pl-intro-rest">
      <div class="pl-k" style="margin-top:18px">이번 생애의 당신은</div><div class="pl-res one">${res}</div>
      <div class="pl-k-note" style="margin-top:14px"><i class="fa-solid fa-dice"></i> ${d.res_fixed ? '대개 이전과 같은 나라에서 다시 태어나요.' : '출신 국가는 무작위로 정해져요.'}</div></div></div>`,
    dock: '' };
}
// 지난 생애 : 끝난 생애가 있을 때만 아래에 보여요.
// 지난 운명을 누르면 그 운명이 끝났을 때의 카드를 다시 보여 줘요(읽기 전용).
var loopLifePeek = null, loopLifeStep = 0, loopLifeFull = {};
// 지난 운명 리플레이 : 기록 전체는 열 때만 서버에서 받아요
socket.on('loop_life', d => { if (!d || !loopData) return; const l = (loopData.lives || [])[d.i]; if (l && l.life_no === d.life_no) { loopLifeFull[`${d.life_no}|${d.ended}`] = d.log || []; renderLoop(); } });
function loopReplayClose() { loopLifePeek = null; renderLoop(); renderLoopLog(); }
function loopReplayGo(step) { loopLifeStep = step; renderLoop(); const sc = document.querySelector('#playPage .pl-scroll'); if (sc) sc.scrollTop = 0; }
function loopReplayHtml(d, li) {
  const life = d.lives[li], key = `${life.life_no}|${life.ended}`, log = loopLifeFull[key];
  const head = (label) => `<div class="pl-replay-h"><button class="bt-back" onclick="event.stopPropagation(); loopReplayClose()" aria-label="기록 닫기" data-tip="기록 닫기"><i class="fa-solid fa-chevron-left"></i></button>
      <span class="pl-replay-t"><i class="fa-solid fa-infinity"></i>${life.life_no}번째 운명의 기록${life.loop_no ? ` · 루프 ${life.loop_no}` : ''}</span><span class="pl-replay-n">${label}</span></div>`;
  if (!log) { socket.emit('loop_life', { i: li }); return { main: head('') + `<div class="pl-box">${emptyHtml('fa-circle-notch fa-spin', '기록을 불러오는 중이에요', '', null, true)}</div>`, dock: '' }; }
  const n = log.length, step = Math.max(0, Math.min(loopLifeStep, n));
  const nav = (prevOk, nextLabel, nextFn) => `<div class="pl-actions two peek"><button class="pl-btn" ${prevOk ? '' : 'disabled'} onclick="event.stopPropagation(); loopReplayGo(${step - 1})"><i class="fa-solid fa-chevron-left"></i>이전</button>
      <button class="pl-btn primary" onclick="event.stopPropagation(); ${nextFn}">${nextLabel}<i class="fa-solid fa-chevron-right"></i></button></div>`;
  if (step >= n) {   // 마지막 장 : 그 운명이 끝난 장면
    const card = loopLifeCardHtml(d, life);
    return { main: head('END') + card, dock: nav(n > 0, '처음부터', 'loopReplayGo(0)') };
  }
  const l = log[step], eraBy = Object.fromEntries((d.eras || []).map(e => [e.id, e])), e = eraBy[l.era] || {};
  const rr = { talent_name: life.country === 'nova' ? '기술' : '재능' };
  const story = loopType(l.story || [], null), res = loopType(l.text || [], null);
  const tw = l.twist && l.twist.text ? `<div class="tw ${l.twist.kind}"><i class="fa-solid ${l.twist.kind === 'purge' ? 'fa-house-crack' : l.twist.kind === 'risk' ? 'fa-bolt' : 'fa-leaf'}"></i><p>${loopEsc(l.twist.text)}</p></div>` : '';
  const fx = l.solved ? `<div class="pl-deltas">${loopGainHtml(l.gain, rr)}</div>` : loopDeltaHtml(l.delta, l.dmind).replace('</div>', loopGainHtml(l.gain, rr) + '</div>');
  const main = head(`${step + 1} / ${n}`) + `<div class="pl-box glow pl-ev peek"><div class="pl-ev-meta"><span class="pl-ev-no">EVENT ${String(step + 1).padStart(2, '0')}</span><span>${loopEsc(e.no || '')}. ${loopEsc(e.name || '')}</span></div>
    <h2 class="pl-ev-title">${loopEsc(l.title)}</h2><div class="pl-story">${story.html || '<p class="q">기록이 흐릿합니다.</p>'}</div>
    </div><div class="pl-answer"><div class="pl-picked"><span class="k">${l.solved ? `<i class="fa-solid ${l.solved === 'wealth' ? 'fa-coins' : 'fa-lightbulb'}"></i>` : 'ABC'[l.pick] || '·'}</span>${loopEsc(l.choice)}</div>
    ${res.html || fx || tw ? `<div class="pl-result">${res.html}<div class="pl-res-fx">${fx}</div>${tw}</div>` : ''}</div>`;
  return { main, dock: nav(step > 0, step + 1 < n ? '다음' : '마지막', `loopReplayGo(${step + 1})`) };
}
function loopLifePeekGo(i) {
  loopLifePeek = loopLifePeek === i ? null : i; loopLifeStep = 0; loopPeek = null; renderLoop();
  if (document.body.classList.contains('m-chat-open') && typeof toggleMobileChat === 'function') toggleMobileChat(false);
  const sc = document.querySelector('#playPage .pl-scroll'); if (sc) sc.scrollTop = 0;
}
function loopLifeCardHtml(d, l) {
  const e = l.end || {}, survived = l.outcome === 'survived' || l.outcome === 'paused';
  const at = survived ? (l.outcome === 'paused' ? '다음 이야기를 기다리며' : '전쟁 이후까지') : `${loopEsc((l.death || {}).at || '')}에서`;
  return loopEndCardHtml({ tag: e.tag || 'RECORD', cls: `${survived || e.kind === 'loop' ? 'loop' : ''} ${e.kind === 'mind' ? 'mind' : ''}`, title: e.title || '',
    text: (e.text || []).map(t => `<p class="${/^["“]/.test(t) ? 'q' : ''}" style="opacity:1;animation:none">${loopEsc(t)}</p>`).join(''),
    meta: `<span class="pl-end-stamp"><i class="fa-solid fa-infinity"></i>${l.life_no}번째 운명${l.loop_no ? ` · 루프 ${l.loop_no}` : ''}</span>${at} · ${l.count}개의 사건`,
    actions: '', still: true });
}
function loopLivesHtml(d) {
  const lives = d.lives || [];
  if (!lives.length) return '';
  const eraNo = id => ((d.eras || []).find(e => e.id === id) || {}).no || '';
  return `<div class="lp-past"><div class="lp-era">지난 운명 <span>${lives.length}</span></div><div class="pl-log">${lives.map((l, li) => `<div class="row go ${loopLifePeek === li ? 'on' : ''}" onclick="loopLifePeekGo(${li})"><span class="era">${loopEsc(eraNo(l.era))}</span><span class="ttl"><b>${l.life_no}번째 운명${l.loop_no ? ` · 루프 ${l.loop_no}` : ''} · ${l.outcome === 'survived' ? '생존' : l.outcome === 'paused' ? '잠시 멈춤' : (l.death || {}).kind === 'mind' ? '정신 붕괴' : '사망'}</b><span>${l.country ? loopEsc((LOOP_COUNTRY[l.country] || [''])[0]) + ' · ' : ''}${loopEsc((LOOP_RES[l.res] || [''])[0])} · ${l.outcome === 'survived' ? '전쟁 이후까지' : l.outcome === 'paused' ? '다음 이야기를 기다리며' : loopEsc((l.death || {}).at || '') + '에서'}</span></span><span class="d zero">${l.count}사건</span></div>`).join('')}</div></div>${(d.run && (d.run.log || []).length) ? `<div class="lp-era lp-now">${d.run.status === 'ended' ? '방금 끝난 운명' : '이번 운명'}</div>` : ''}`;
}
// 오른쪽 기록판 : 이번 생애에 지나온 사건(오래된 것부터 아래로 쌓이고, 새 사건이 생기면 맨 아래로).
function renderLoopLog() {
  const body = document.getElementById('playLogBody');
  if (!body) return;
  const d = loopData, r = d && d.run;
  const log = (r && r.log) || [];
  // 지난 운명은 기록판 맨 위에, 그 아래로 이번 운명의 사건이 쌓여요.
  const past = d ? loopLivesHtml(d) : '';
  const rs = document.getElementById('playLogRestart'); if (rs) rs.style.display = r || (d && (d.lives || []).length) ? '' : 'none';   // 기록이 있으면 언제든 초기화
  if (!log.length) { body.innerHTML = past || emptyHtml('fa-scroll', '아직 지나온 사건이 없어요', '사건을 고를 때마다 여기에 기록돼요.', null, true); body.dataset.n = 0; return; }
  const eraBy = Object.fromEntries(((d && d.eras) || []).map(e => [e.id, e]));
  let last = null, html = '';
  log.forEach((l, i) => {
    if (l.era !== last) { const e = eraBy[l.era] || {}; html += `<div class="lp-era">${loopEsc(e.no || '')}. ${loopEsc(e.name || '')}</div>`; last = l.era; }
    const g = Object.entries(l.gain || {}).filter(([, v]) => v).map(([k, v]) => `<em class="${k} ${v > 0 ? 'up' : 'down'}">${loopEsc(loopAssetName(k, r))} ${loopSign(v)}</em>`).join('');
    // 누르면 그 사건을 다시 읽어요(읽기 전용). 지금 보고 있는 사건이면 지금으로 돌아가요.
    const cur = i === log.length - 1 && r.status !== 'event';
    html += `<div class="lp-row go ${loopPeek === i ? 'on' : ''}" onclick="${cur ? 'loopPeek = null; renderLoop()' : `loopPeekGo(${i})`}"><span class="n">${i + 1}</span><span class="ttl"><b>${loopEsc(l.title)}</b><span>${loopEsc(l.choice)}</span>${g ? `<span class="lp-gain">${g}</span>` : ''}</span>${loopMiniDelta(l.delta, l.dmind)}</div>`;
  });
  const atEnd = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  const grew = (body.dataset.n | 0) !== log.length;
  body.innerHTML = past + html;
  body.dataset.n = log.length;
  if (grew || atEnd) body.scrollTop = body.scrollHeight;
}
function loopEmit(ev, data) { if (loopBusy) return; loopBusy = true; renderLoop(); socket.emit(ev, data || {}); }
function loopChoose(id, idx) { loopEmit('loop_choose', { event: id, idx }); }
if (IS_PLAY) {
  socket.on('loop_data', d => { bootReady('state'); loopData = d; loopBusy = false; loopSyncPoint(d); loopTopSub(d); renderLoop(); });
  socket.on('loop_result', r => { loopBusy = false; if (r && !r.ok) uiToast(r.message); });
  socket.on('joined', () => socket.emit('loop_state'));
  document.addEventListener('DOMContentLoaded', () => {
    const b = document.getElementById('sidebarBattleBtn');
    if (b) { b.dataset.tip = 'LOOP'; const i = b.querySelector('i'); if (i) i.className = 'fa-solid fa-infinity'; }
    const c = document.getElementById('sidebarChatBtn');
    if (c) { c.dataset.tip = '기록'; const i = c.querySelector('i'); if (i) i.className = 'fa-solid fa-scroll'; }
    renderLoop();
  });
}

// ==================================================================
// LOOP 편집(운영진) : 운영 페이지의 'LOOP 편집' 탭. 사건 · 규칙 · 수치 · 문장을 고쳐서 저장하면
// 다음 사건부터 바로 반영돼요(loop_content.json). 체력 · 정신 변동이 들어 있어서 운영진에게만 와요.
// 입력칸은 고칠 때마다 작업본(la.c)에 바로 들어가고, '저장'을 눌러야 서버에 올라갑니다.
// ==================================================================
const la = { c: null, saved: '', custom: false, sub: 'events', sel: null, q: '', loading: false, navMini: (() => { try { return localStorage.getItem('laNavMini') === '1'; } catch (e) { return false; } })() };
const LA_KIND = { life: '일상', war: '전쟁', plague: '병', purge: '자정작용', loop: '루프', mind: '정신 붕괴' };
const LA_DELTA = [3, 2, 1, 0, -1, -2, -3];
const LA_RES = [['wealth', '재산', 'fa-coins'], ['intel', '지능', 'fa-lightbulb'], ['talent', '재능·기술', 'fa-star']];
const LA_GAIN = LA_RES.concat([['strain', '균열 압력', 'fa-house-crack']]);
function laEsc(s) { return mailEsc(s == null ? '' : String(s)); }
function laDirty() { return !!la.c && JSON.stringify(la.c) !== la.saved; }
function laP(path) { return `data-p='${laEsc(JSON.stringify(path))}'`; }
function laGet(path) { return path.reduce((o, k) => (o == null ? o : o[k]), la.c); }
function laSetPath(path, v) {
  let o = la.c;
  for (let i = 0; i < path.length - 1; i++) { if (o[path[i]] == null) o[path[i]] = typeof path[i + 1] === 'number' ? [] : {}; o = o[path[i]]; }
  o[path[path.length - 1]] = v;
}
// 입력칸 하나 → 작업본. data-t : num · pct(퍼센트) · lines(한 줄 = 한 항목) · tags(쉼표 · 띄어쓰기) · seq(시대 순서)
function laInput(el, rerender) {
  const path = JSON.parse(el.dataset.p), t = el.dataset.t;
  let v = el.type === 'checkbox' ? el.checked : el.value;
  if (t === 'num') v = v === '' ? '' : Number(v);
  else if (t === 'pct') v = Math.max(0, Math.min(100, Number(v) || 0)) / 100;
  else if (t === 'lines') v = v.split('\n');
  else if (t === 'tags') v = v.split(/[\s,]+/).filter(Boolean).map(x => x.toUpperCase());
  else if (t === 'seq') v = v.split(/[\s,>→·]+/).map(Number).filter(Boolean);
  else if (t === 'fixed') v = el.checked ? 'open' : undefined;
  else if (t === 'chapter') v = v === '' ? undefined : Number(v);
  laSetPath(path, v);
  if (rerender) renderLoopAdmin(); else laSyncBar();
}
function laSyncBar() {
  const bar = document.getElementById('laBar'); if (!bar) return;
  bar.classList.toggle('dirty', laDirty());
  bar.querySelector('.st').innerHTML = laDirty() ? '<i class="fa-solid fa-circle"></i> 저장하지 않은 변경이 있어요' : (la.custom ? '<i class="fa-solid fa-check"></i> 저장된 내용을 쓰는 중' : '<i class="fa-solid fa-check"></i> 기본 내용을 쓰는 중');
}
function laTa(path, lines, rows, ph) {
  return `<textarea class="ops-in" rows="${rows || 4}" ${laP(path)} data-t="lines" placeholder="${laEsc(ph || '')}" oninput="laInput(this)">${laEsc((lines || []).join('\n'))}</textarea>`;
}
function laDeltaSel(path, v, stat) {
  return `<select class="ops-in la-d ${stat}" ${laP(path)} data-t="num" onchange="laInput(this); this.className='ops-in la-d ${stat} '+(this.value>0?'up':this.value<0?'down':'')">${LA_DELTA.map(n => `<option value="${n}" ${n === (v || 0) ? 'selected' : ''}>${n > 0 ? '+' + n : n}</option>`).join('')}</select>`;
}
function laSeg(path, value, opts, rerender) {
  return `<div class="ops-seg">${opts.map(([v, t]) => `<button class="${(value || '') === v ? 'on' : ''}" onclick='laSetPath(${JSON.stringify(path)}, ${JSON.stringify(v || undefined) || 'undefined'}); renderLoopAdmin()'>${t}</button>`).join('')}</div>`;
}

const LA_SECTIONS = [
  ['release', '공개 범위', 'fa-flag-checkered', '업데이트 단계별로 플레이어에게 열리는 범위'],
  ['events', '사건', 'fa-scroll', '사건 카드 · 선택지 · 출현 조건'],
  ['rules', '규칙 · 수치', 'fa-sliders', '체력 · 정신 · 시대 · 균열 · 자원'],
  ['prologue', '프롤로그', 'fa-landmark', '서력의 역사 · 탄생 · 문명관'],
  ['texts', '문장', 'fa-align-left', '상태 · 사망 · 엔딩 · 재난 · 해결'],
];
function openLoopAdmin() {
  if (!opsIsGm()) return;
  if (opsOpen()) closeOps();
  closeWorldMap(true);
  document.body.classList.add('view-loopadmin');
  document.getElementById('sidebarLoopEditBtn').classList.add('active');
  document.getElementById('sidebarBattleBtn').classList.remove('active');
  renderLoopAdmin();
}
function closeLoopAdmin() {
  if (!document.body.classList.contains('view-loopadmin')) return;
  if (laDirty()) uiToast('LOOP 편집에 저장하지 않은 변경이 있어요. 다시 열면 이어서 고칠 수 있어요.');
  document.body.classList.remove('view-loopadmin');
  const lb = document.getElementById('sidebarLoopEditBtn'); if (lb) lb.classList.remove('active');
  document.getElementById('sidebarBattleBtn').classList.add('active');
}
function laOpen() { return document.body.classList.contains('view-loopadmin'); }
function laToggleNav() { la.navMini = !la.navMini; try { localStorage.setItem('laNavMini', la.navMini ? '1' : '0'); } catch (e) {} renderLoopAdmin(); }
function loopStudioHtml() {
  if (!la.c) { if (!la.loading) { la.loading = true; socket.emit('loop_admin_get'); } return emptyHtml('fa-circle-notch fa-spin', 'LOOP 내용을 불러오는 중이에요'); }
  const rel = la.c.rules.chapters[la.c.rules.release] || {};
  const nav = `<button class="la-nav-fold" onclick="laToggleNav()" aria-label="메뉴 접기"><i class="fa-solid ${la.navMini ? 'fa-angles-right' : 'fa-angles-left'}"></i><span><b>${la.navMini ? '' : '메뉴 접기'}</b></span></button>`
    + LA_SECTIONS.map(([k, t, ic, d]) => `<button class="${la.sub === k ? 'on' : ''}" onclick="la.sub='${k}'; renderLoopAdmin(); document.getElementById('laMain').scrollTop = 0" ${la.navMini ? `data-tip="${t}"` : ''}><i class="fa-solid ${ic}"></i><span><b>${t}</b><em>${d}</em></span></button>`).join('');
  const body = la.sub === 'release' ? laReleaseHtml() : la.sub === 'events' ? laEventsHtml() : la.sub === 'rules' ? laRulesHtml() : la.sub === 'prologue' ? laPrologueHtml() : laTextsHtml();
  return `<div class="topbar v2 panel la-top"><div class="seg la-brand">Loop Studio</div><span class="sep">▶</span><div class="seg">${laEsc((LA_SECTIONS.find(x => x[0] === la.sub) || [])[1] || '')}</div>
      <div class="spacer"></div><span class="la-live"><i class="fa-solid fa-circle"></i> 공개 중 : <b>${laEsc(rel.name || '')}</b> ${laEsc(rel.sub || '')}</span></div>
    <div class="la-shell ${la.navMini ? 'mini' : ''}"><nav class="la-nav">${nav}<div class="la-nav-hint">이야기 속 <b>{조국}</b> · <b>{이웃}</b>은 출신 국가, <b>{적}</b>은 상대 진영으로 바뀌어요.</div></nav>
      <div class="la-main" id="laMain"><div class="la-wrap">${body}</div></div></div>
    <div class="la-bar" id="laBar"><span class="st"></span>
      <button class="ops-btn" onclick="laRevert()"><i class="fa-solid fa-rotate-left"></i> 마지막 저장으로</button>
      <button class="ops-btn primary" onclick="laSave()"><i class="fa-solid fa-floppy-disk"></i> 저장</button></div>`;
}
function renderLoopAdmin() {
  if (!laOpen()) return;
  const page = document.getElementById('loopAdminPage');
  const main = page.querySelector('#laMain'), keep = main ? main.scrollTop : 0;
  const list = page.querySelector('.la-list'), keepList = list ? list.scrollTop : 0;
  page.innerHTML = loopStudioHtml();
  const m2 = page.querySelector('#laMain'); if (m2) m2.scrollTop = keep;
  const l2 = page.querySelector('.la-list'); if (l2) l2.scrollTop = keepList;
  laSyncBar();
}

// ── 공개 범위 ─────────────────────────────────
function laReleaseHtml() {
  const R = la.c.rules, chs = R.chapters;
  const cnt = id => la.c.events.filter(ev => !ev.draft && laEvChapter(ev) === id).length;
  const drafts = la.c.events.filter(ev => ev.draft).length;
  const cards = chs.map((ch, i) => {
    const live = i <= R.release, now = i === R.release;
    return `<div class="ops-card la-ch-card ${live ? 'live' : ''} ${now ? 'now' : ''}">
      <div class="la-ch-top"><span class="la-step">${i === 0 ? 'BASE' : 'PATCH ' + i}</span>${live ? '<span class="la-badge on">공개 중</span>' : '<span class="la-badge">공개 전</span>'}</div>
      <div class="la-grid two"><div class="ops-field"><span class="lb">이름</span><input class="ops-in" ${laP(['rules', 'chapters', i, 'name'])} value="${laEsc(ch.name)}" oninput="laInput(this)"></div>
        <div class="ops-field"><span class="lb">부제</span><input class="ops-in" ${laP(['rules', 'chapters', i, 'sub'])} value="${laEsc(ch.sub)}" oninput="laInput(this)"></div></div>
      <div class="ops-field"><span class="lb">이 단계에 열리는 시대 (시대 번호를 쉼표로)</span><input class="ops-in" ${laP(['rules', 'chapters', i, 'eras'])} data-t="seq" value="${ch.eras.join(', ')}" onchange="laInput(this, true)"></div>
      <div class="la-ch-eras">${ch.eras.map(e => `<span>${laEsc(laEraName(e))}</span>`).join('') || '<span class="none">시대 없음</span>'}</div>
      <label class="la-chk"><input type="checkbox" ${laP(['rules', 'chapters', i, 'loop'])} ${ch.loop ? 'checked' : ''} onchange="laInput(this, true)"> 이 단계부터 루프 진입이 열려요</label>
      <div class="la-ch-foot"><span class="ops-hint">사건 ${cnt(i)}장</span>
        ${now ? '<span class="la-now"><i class="fa-solid fa-check"></i> 지금 공개 단계</span>' : `<button class="ops-btn ${i > R.release ? 'primary' : ''}" onclick="la.c.rules.release=${i}; renderLoopAdmin()">${i > R.release ? '여기까지 공개하기' : '여기까지로 되돌리기'}</button>`}</div>
      ${chs.length > 1 && i === chs.length - 1 ? `<button class="ops-btn icon danger la-ch-del" onclick="la.c.rules.chapters.pop(); la.c.rules.release=Math.min(la.c.rules.release, la.c.rules.chapters.length-1); renderLoopAdmin()"><i class="fa-solid fa-trash-can"></i></button>` : ''}
    </div>`;
  }).join('');
  return `<div class="la-lead"><b>업데이트 단계마다 플레이어에게 열리는 범위를 정해요.</b>
      <span>공개 전 시대에 닿으면 플레이어는 '이야기는 여기서 잠시 멈춥니다' 엔딩을 보고, 다음 단계를 공개하면 그 자리에서 <b>이어서 살기</b>를 할 수 있어요. 공개 단계를 바꾼 뒤 <b>저장</b>을 눌러야 반영돼요.</span></div>
    <div class="la-chs-row">${cards}
      <div class="ops-card la-add" onclick="la.c.rules.chapters.push({ id: la.c.rules.chapters.length, name: (la.c.rules.chapters.length) + '차 패치', sub: '', eras: [], loop: false }); renderLoopAdmin()"><i class="fa-solid fa-plus"></i> 단계 추가</div></div>
    <div class="ops-hint" style="margin-top:14px">작업 중으로 표시된 사건 ${drafts}장은 어느 단계에서도 플레이에 나오지 않아요. 사건마다 '공개 단계'를 따로 정하면 시대와 상관없이 그 단계에 열려요(예 : III 시대의 루프 사건을 2차 패치에).</div>`;
}
function laEraChapter(era) { const ch = la.c.rules.chapters.find(c => c.eras.includes(era)); return ch ? ch.id : 0; }
function laEvChapter(ev) { return ev.chapter != null && ev.chapter !== '' ? Number(ev.chapter) : laEraChapter(ev.era); }

// ── 사건 ─────────────────────────────────────
function laEraName(id) { const e = (la.c.eras || []).find(x => x.id === id); return e ? `${e.no}. ${e.name}` : `시대 ${id}`; }
function laCondBadges(ev) {
  const c = ev.cond || {}, b = [];
  if (ev.draft) b.push('<em class="draft">작업 중</em>');
  else if (laEvChapter(ev) > la.c.rules.release) b.push(`<em class="lock"><i class="fa-solid fa-lock"></i> ${laEsc((la.c.rules.chapters[laEvChapter(ev)] || {}).name || '')}</em>`);
  if (c.country) b.push(`<em>${c.country === 'arcadia' ? '아르카디아' : '노바'}</em>`);
  if ((c.tags || []).length) b.push('<em>태그</em>');
  if (c.loops) b.push(`<em>루프 ${c.loops}+</em>`);
  return b.join('');
}
// 챕터(시대) → 사건 칸(1 ~ 사건 개수) → 칸마다 스크립트 블럭 여러 개. 플레이 때는 칸마다 조건이 맞는 블럭 하나가 무작위로 나와요.
function laSlotOf(ev) { return Number(ev.slot) || 1; }
function laMatch(ev, q) { return !q || `${ev.title} ${(ev.story || []).join(' ')}`.toLowerCase().includes(q); }
function laBlocks(era, slot) { return la.c.events.map((ev, i) => [ev, i]).filter(([ev]) => ev.era === era && laSlotOf(ev) === slot); }
function laSlotCount(era) { const e = la.c.eras.find(x => x.id === era) || {}; return Math.max(Number(e.len) || 1, ...la.c.events.filter(ev => ev.era === era).map(laSlotOf)); }
function laEnsureSlot() {
  const eras = la.c.eras || [], ev = la.c.events[la.sel];
  if (ev && (!la.slot || la.slot.era !== ev.era || la.slot.slot !== laSlotOf(ev))) la.slot = { era: ev.era, slot: laSlotOf(ev) };
  if (!la.slot || !eras.some(e => e.id === la.slot.era)) la.slot = eras[0] ? { era: eras[0].id, slot: 1 } : null;
  if (la.sel != null && !ev) la.sel = null;
}
function laPickSlot(era, slot) {
  la.slot = { era, slot };
  const b = laBlocks(era, slot); la.sel = b.length ? b[0][1] : null;
  renderLoopAdmin(); const m = document.getElementById('laMain'); if (m) m.scrollTop = 0;
}
// 블럭 끌어서 옮기기 : 왼쪽 칸에 놓으면 그 칸의 맨 뒤로(다른 챕터 · 다른 칸), 오른쪽 블럭 위에 놓으면 그 블럭 앞으로.
let laDragI = null;
function laDragStart(e, i) { laDragI = i; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', String(i)); } catch (x) {} document.body.classList.add('la-dragging'); }
function laDragEnd() { laDragI = null; document.body.classList.remove('la-dragging'); document.querySelectorAll('.la-drop').forEach(x => x.classList.remove('la-drop')); }
function laDragOver(e) { if (laDragI == null) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; e.currentTarget.classList.add('la-drop'); }
function laDragLeave(e) { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.classList.remove('la-drop'); }
function laDrop(e, era, slot, before) {
  e.preventDefault(); e.stopPropagation();
  const i = laDragI; laDragEnd();
  if (i == null || i === before || !la.c.events[i]) return;
  const evs = la.c.events, ev = evs.splice(i, 1)[0];
  ev.era = era; ev.slot = slot;
  let at;
  if (before != null) at = before > i ? before - 1 : before;
  else { at = evs.length; for (let k = evs.length - 1; k >= 0; k--) if (evs[k].era === era && laSlotOf(evs[k]) === slot) { at = k + 1; break; } }
  evs.splice(at, 0, ev);
  la.sel = at; la.slot = { era, slot };
  renderLoopAdmin();
}
function laPickBlock(i) { la.sel = la.sel === i ? null : i; renderLoopAdmin(); }
// 칸에 두 나라 모두 나올 블럭이 있는지(작업 중 제외). 없으면 그 나라 플레이어는 이 칸을 건너뛰어요.
function laSlotCover(blocks) {
  const live = blocks.filter(([ev]) => !ev.draft);
  const miss = ['arcadia', 'nova'].filter(cc => !live.some(([ev]) => !(ev.cond || {}).country || ev.cond.country === cc));
  if (!blocks.length) return '<em class="empty">비어 있음</em>';
  if (miss.length === 2) return '<em class="draft">작업 중만</em>';
  return miss.map(cc => `<em class="warn">${cc === 'arcadia' ? '아르카디아' : '노바'} 없음</em>`).join('');
}
const LA_ROMAN = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];
function laAddEra() {
  const id = Math.max(0, ...la.c.eras.map(e => e.id)) + 1;
  if (la.c.eras.length >= 12) { uiToast('챕터는 12개까지 만들 수 있어요.'); return; }
  la.c.eras.push({ id, no: LA_ROMAN[id] || String(id), name: '새 챕터', period: '', level: '', len: 3, risk: 0, luck: 0, risk_text: [] });
  la.slot = { era: id, slot: 1 }; la.sel = null; renderLoopAdmin();
}
function laDelEra(id) {
  if (la.c.events.some(ev => ev.era === id)) { uiToast('블럭이 남아 있는 챕터는 지울 수 없어요.'); return; }
  la.c.eras = la.c.eras.filter(e => e.id !== id); la.slot = null; renderLoopAdmin();
}
function laEventsHtml() {
  laEnsureSlot();
  const q = la.q.trim().toLowerCase();
  const groups = (la.c.eras || []).map((era, ei) => {
    const n = laSlotCount(era.id), len = Number(era.len) || 1;
    let items = '';
    for (let s = 1; s <= n; s++) {
      const bl = laBlocks(era.id, s);
      if (q && !bl.some(([ev]) => laMatch(ev, q))) continue;
      const on = la.slot && la.slot.era === era.id && la.slot.slot === s;
      const first = bl.find(([ev]) => laMatch(ev, q));
      items += `<button class="la-item la-slot ${on ? 'on' : ''} ${s > len ? 'out' : ''}" onclick="laPickSlot(${era.id}, ${s})" ondragover="laDragOver(event)" ondragleave="laDragLeave(event)" ondrop="laDrop(event, ${era.id}, ${s})">
        <span class="sn">${s}</span><span class="t">${first ? laEsc(first[0].title) || '(제목 없음)' : '사건 ' + s}</span>
        <span class="b">${s > len ? '<em class="lock">칸 밖 · 안 나옴</em>' : ''}${bl.length ? `<em class="cnt">블럭 ${bl.length}</em>` : ''}</span></button>`;
    }
    if (q && !items) return '';
    const empty = !la.c.events.some(ev => ev.era === era.id);
    return `<div class="la-g la-g2"><span class="nm">${laEsc(era.no)}. ${laEsc(era.name)}${laEraChapter(era.id) > la.c.rules.release ? '<i class="fa-solid fa-lock"></i>' : ''}</span>
        <span class="la-g-n"><em>사건</em>${laStepper(['eras', ei, 'len'], len, 1, 30)}</span>${empty ? `<button class="ops-btn icon danger la-g-x" onclick="laDelEra(${era.id})" data-tip="챕터 지우기"><i class="fa-solid fa-trash-can"></i></button>` : ''}</div>${items}`;
  }).join('');
  return `<div class="la-ev">
    <div class="ops-card la-left"><div class="ops-row"><input class="ops-in" placeholder="제목 · 내용 검색" value="${laEsc(la.q)}" oninput="la.q=this.value; laFilterList()"></div>
      <div class="la-count" id="laCount">${laCountHtml()}</div>
      <div class="la-list" id="laList">${groups || '<div class="ops-empty">찾는 사건이 없어요.</div>'}${q ? '' : '<button class="la-add-era" onclick="laAddEra()"><i class="fa-solid fa-plus"></i> 챕터 추가</button>'}</div></div>
    <div class="la-right">${la.slot ? laSlotHtml() : `<div class="ops-card">${emptyHtml('fa-scroll', '챕터를 만들어 주세요', '왼쪽 아래 챕터 추가로 시작해요.')}</div>`}</div></div>`;
}
// 오른쪽 : 고른 사건 칸의 스크립트 블럭들. 펼친 블럭 하나만 편집기로, 나머지는 한 줄 요약.
function laSlotHtml() {
  const { era, slot } = la.slot, e = la.c.eras.find(x => x.id === era) || {}, bl = laBlocks(era, slot);
  const rows = bl.map(([ev, i], k) => i === la.sel ? laEventForm(i, k + 1) :
    `<button class="ops-card la-blk-row" data-i="${i}" onclick="laPickBlock(${i})" draggable="true" ondragstart="laDragStart(event, ${i})" ondragend="laDragEnd()" ondragover="laDragOver(event)" ondragleave="laDragLeave(event)" ondrop="laDrop(event, ${era}, ${slot}, ${i})"><span class="k"><i class="fa-solid fa-grip-vertical"></i>${k + 1}</span><span class="t">${laEsc(ev.title) || '(제목 없음)'}</span><span class="b">${laCondBadges(ev)}</span><i class="fa-solid fa-chevron-down"></i></button>`).join('');
  const cover = laSlotCover(bl);   // 국가별로 빠진 블럭 경고 : 오른쪽 위에
  return `<div class="la-slot-h"><span class="la-slot-tag">${laEsc(e.no)} · 사건 ${slot}</span><b>${laEsc(e.name)}</b>${cover ? `<span class="la-slot-cover">${cover}</span>` : ''}
      <span class="ops-hint">블럭 ${bl.length}개${bl.length > 1 ? ' · 조건이 맞는 블럭 중 하나가 무작위로 나와요' : ''}${slot > (Number(e.len) || 1) ? ' · 사건 개수보다 뒤라 지금은 안 나와요' : ''}</span></div>
    ${rows || `<div class="ops-card la-slot-empty">${emptyHtml('fa-scroll', '아직 블럭이 없어요', '이 칸이 비어 있으면 플레이 때 건너뛰어요.')}</div>`}
    <button class="la-add-blk" onclick="laAddEvent()" ondragover="laDragOver(event)" ondragleave="laDragLeave(event)" ondrop="laDrop(event, ${era}, ${slot})"><i class="fa-solid fa-plus"></i> 사건 추가하기</button>`;
}
let laFilterT = null;
function laFilterList() { clearTimeout(laFilterT); laFilterT = setTimeout(() => { const l = document.getElementById('laList'); if (!l) return; const tmp = document.createElement('div'); tmp.innerHTML = laEventsHtml(); l.innerHTML = tmp.querySelector('.la-list').innerHTML; const c = document.getElementById('laCount'); if (c) c.innerHTML = laCountHtml(); }, 150); }
// 등록된 사건 수(검색 중이면 찾은 수도). 작업 중인 사건은 따로 세어요.
function laCountHtml() {
  const evs = la.c.events, q = la.q.trim().toLowerCase();
  const found = q ? evs.filter(ev => `${ev.title} ${(ev.story || []).join(' ')}`.toLowerCase().includes(q)).length : null;
  const drafts = evs.filter(ev => ev.draft).length;
  return `<span>챕터 <b>${la.c.eras.length}</b> · 블럭 <b>${evs.length}</b>${drafts ? ` · 작업 중 ${drafts}` : ''}</span>${found != null ? `<span class="f">찾은 블럭 ${found}</span>` : ''}`;
}
// 숫자 하나를 − / + 로 바꾸는 작은 조절기(범위 안에서). 0이 아니면 색이 붙어요.
function laStep(path, d, min, max) {
  const v = Math.max(min, Math.min(max, (Number(laGet(path)) || 0) + d));
  laSetPath(path, v); renderLoopAdmin();
}
function laStepper(path, v, min, max, cls, signed) {
  v = Number(v) || 0;
  const tone = v > 0 ? 'up' : v < 0 ? 'down' : 'zero';
  const P = laEsc(JSON.stringify(path));
  return `<span class="la-stp ${cls || ''} ${tone}"><button type="button" ${v <= min ? 'disabled' : ''} onclick='laStep(${P}, -1, ${min}, ${max})'><i class="fa-solid fa-minus"></i></button><b>${signed && v > 0 ? '+' + v : v}</b><button type="button" ${v >= max ? 'disabled' : ''} onclick='laStep(${P}, 1, ${min}, ${max})'><i class="fa-solid fa-plus"></i></button></span>`;
}
const LA_ETABS = [['story', '이야기', 'fa-book-open'], ['choices', '선택지', 'fa-list-ol'], ['cond', '세부 조건', 'fa-filter'], ['memo', '작업 메모', 'fa-note-sticky']];
function laEventForm(i, no) {
  const ev = la.c.events[i], P = k => ['events', i, ...k], c = ev.cond || {};
  la.etab = la.etab || 'story';
  const eraOpts = (la.c.eras || []).map(e => `<option value="${e.id}" ${e.id === ev.era ? 'selected' : ''}>${laEsc(e.no)}. ${laEsc(e.name)}</option>`).join('');
  const kindOpts = Object.entries(LA_KIND).filter(([k]) => k !== 'mind').map(([k, t]) => `<option value="${k}" ${k === (ev.kind || 'life') ? 'selected' : ''}>${t}</option>`).join('');
  const chOpts = `<option value="" ${ev.chapter == null || ev.chapter === '' ? 'selected' : ''}>시대를 따라 (${laEsc((la.c.rules.chapters[laEraChapter(ev.era)] || {}).name || '')})</option>` + la.c.rules.chapters.map(ch => `<option value="${ch.id}" ${ev.chapter != null && ev.chapter !== '' && Number(ev.chapter) === ch.id ? 'selected' : ''}>${laEsc(ch.name)}</option>`).join('');
  const condCount = (c.loops ? 1 : 0) + ((c.tags || []).length ? 1 : 0) + ((c.no_tags || []).length ? 1 : 0) + Object.values(c.min || {}).filter(Boolean).length;
  const tabs = LA_ETABS.map(([k, t, ic]) => {
    const n = k === 'cond' ? condCount : k === 'story' ? (ev.extra || []).length : 0;
    const dot = k === 'memo' && (ev.note || '').trim() ? '<span class="dot"></span>' : '';
    return `<button class="${la.etab === k ? 'on' : ''}" onclick="la.etab='${k}'; renderLoopAdmin()"><i class="fa-solid ${ic}"></i>${t}${n ? `<em>${n}</em>` : ''}${dot}</button>`;
  }).join('');
  let body = '';
  if (la.etab === 'story') {
    const extras = (ev.extra || []).map((x, k) => {
      const w = x.when || {}, wt = w.tag ? 'tag' : 'hp_lte' in w ? 'hp_lte' : 'mind_lte' in w ? 'mind_lte' : 'loops' in w ? 'loops' : 'always';
      const wv = w.tag || w.hp_lte || w.mind_lte || w.loops || '';
      return `<div class="la-x"><div class="la-x-row">
          <select class="ops-in" onchange="laExtraWhen(${i}, ${k}, this.value, this.nextElementSibling.value)"><option value="always" ${wt === 'always' ? 'selected' : ''}>항상</option><option value="tag" ${wt === 'tag' ? 'selected' : ''}>이 태그가 있으면</option><option value="hp_lte" ${wt === 'hp_lte' ? 'selected' : ''}>체력이 이하면</option><option value="mind_lte" ${wt === 'mind_lte' ? 'selected' : ''}>정신이 이하면</option><option value="loops" ${wt === 'loops' ? 'selected' : ''}>루프 n회 이상이면</option></select>
          <input class="ops-in" value="${laEsc(wv)}" ${wt === 'always' ? 'disabled' : ''} placeholder="${wt === 'tag' ? '태그' : '숫자'}" onchange="laExtraWhen(${i}, ${k}, this.previousElementSibling.value, this.value)">
          <span class="la-x-arrow"><i class="fa-solid fa-arrow-right"></i></span>
          <select class="ops-in" onchange="laExtraAt(${i}, ${k}, this.value)"><option value="story" ${x.at !== 'result' ? 'selected' : ''}>상황 서술 끝에</option>${[0, 1, 2].map(n => `<option value="r${n}" ${x.at === 'result' && x.choice === n ? 'selected' : ''}>${'ABC'[n]} 결과 끝에</option>`).join('')}</select>
          <button class="ops-btn icon danger" onclick="la.c.events[${i}].extra.splice(${k}, 1); renderLoopAdmin()"><i class="fa-solid fa-trash-can"></i></button></div>
        ${laTa(P(['extra', k, 'text']), x.text, 2, '덧붙는 문장')}</div>`;
    }).join('');
    body = `<div class="la-blk"><div class="la-blk-h"><b>상황 서술</b><span>한 줄 = 한 문단 · 큰따옴표로 시작하는 줄은 대사(굵게)</span></div>${laTa(P(['story']), ev.story, 10)}</div>
      <div class="la-blk"><div class="la-blk-h"><b>조건부 문장</b><span>조건이 맞을 때만 서술이나 결과 끝에 덧붙어요</span>
        <button class="ops-btn" onclick="(la.c.events[${i}].extra = la.c.events[${i}].extra || []).push({ when: {}, at: 'story', text: [''] }); renderLoopAdmin()"><i class="fa-solid fa-plus"></i> 추가</button></div>
        ${extras || '<div class="la-none">없어요. 필요할 때만 추가하세요.</div>'}</div>`;
  } else if (la.etab === 'choices') {
    body = '<div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 체력 · 정신 변화는 플레이어가 고른 뒤에만 보여요. 자원 · 태그는 필요할 때만 펼쳐서 넣으세요.</div>' + (ev.choices || []).map((ch, k) => {
      const need = ch.need || {}, gain = ch.gain || {};
      const used = LA_RES.some(([rk]) => need[rk]) || LA_GAIN.some(([rk]) => gain[rk]) || (ch.tags || []).length;
      const open = used || (la.xopen || {})[`${i}:${k}`];
      const sum = [...LA_RES.filter(([rk]) => need[rk]).map(([rk, rn]) => `${rn} ${need[rk]} 필요`), ...LA_GAIN.filter(([rk]) => gain[rk]).map(([rk, rn]) => `${rn} ${gain[rk] > 0 ? '+' : ''}${gain[rk]}`), ...(ch.tags || []).map(t => '#' + t)];
      return `<div class="la-chc">
        <div class="la-chc-h"><span class="k">${'ABC'[k]}</span><input class="ops-in la-chc-label" ${laP(P(['choices', k, 'label']))} value="${laEsc(ch.label)}" placeholder="선택지 문장" oninput="laInput(this)"></div>
        <div class="la-chc-b">
          <div class="la-chc-res">${laTa(P(['choices', k, 'result']), Array.isArray(ch.result) ? ch.result : String(ch.result || '').split('\n'), 3, '고른 뒤 나오는 결과 문장')}</div>
          <div class="la-chc-fx">
            <div class="la-fx"><span><i class="fa-solid fa-heart"></i> 체력</span>${laStepper(P(['choices', k, 'hp']), ch.hp, -3, 3, 'hp', true)}</div>
            <div class="la-fx"><span><i class="fa-solid fa-brain"></i> 정신</span>${laStepper(P(['choices', k, 'mind']), ch.mind, -3, 3, 'mind', true)}</div>
          </div></div>
        <details class="la-more" ${open ? 'open' : ''} ontoggle="(la.xopen = la.xopen || {})['${i}:${k}'] = this.open"><summary><i class="fa-solid fa-chevron-right"></i> 자원 · 태그 ${sum.length ? `<span class="la-sum">${sum.map(laEsc).join(' · ')}</span>` : '<span class="la-sum none">없음</span>'}</summary>
          <div class="la-more-b">
            <div class="la-more-row"><span class="lb">필요<i class="la-q" data-tip="모자라면 이 선택지는 잠겨요">?</i></span>${LA_RES.map(([rk, rn, ic]) => `<div class="la-fx sm"><span><i class="fa-solid ${ic}"></i> ${rn}</span>${laStepper(P(['choices', k, 'need', rk]), need[rk], 0, 10)}</div>`).join('')}</div>
            <div class="la-more-row"><span class="lb">변화<i class="la-q" data-tip="고르면 바로 더하거나 빼요">?</i></span>${LA_GAIN.map(([rk, rn, ic]) => `<div class="la-fx sm"><span><i class="fa-solid ${ic}"></i> ${rn}</span>${laStepper(P(['choices', k, 'gain', rk]), gain[rk], -3, 3, rk === 'strain' ? 'strain' : '', true)}</div>`).join('')}</div>
            <div class="la-more-row"><span class="lb">붙는 태그</span><input class="ops-in" ${laP(P(['choices', k, 'tags']))} data-t="tags" value="${laEsc((ch.tags || []).join(', '))}" placeholder="예) ENLISTED, LOOP_CONTACT" onchange="laInput(this, true)"></div>
          </div></details></div>`;
    }).join('');
  } else if (la.etab === 'cond') {
    body = `<div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 루프 횟수 · 태그 · 자원 조건이에요. 아무것도 정하지 않으면 누구에게나 나와요. (출신 국가는 위에서 골라요)</div>
      <div class="la-rows">
        <div class="la-r"><span class="lb">루프 횟수</span>${laStepper(P(['cond', 'loops']), c.loops, 0, 20)}<span class="la-r-note">회 이상 (0 = 상관없음)</span></div>
        <div class="la-r"><span class="lb">있어야 하는 태그</span><input class="ops-in" ${laP(P(['cond', 'tags']))} data-t="tags" value="${laEsc((c.tags || []).join(', '))}" placeholder="하나라도 있으면 나와요 · 쉼표로 구분" onchange="laInput(this, true)"></div>
        <div class="la-r"><span class="lb">있으면 안 되는 태그</span><input class="ops-in" ${laP(P(['cond', 'no_tags']))} data-t="tags" value="${laEsc((c.no_tags || []).join(', '))}" placeholder="하나라도 있으면 안 나와요" onchange="laInput(this, true)"></div>
        <div class="la-r top"><span class="lb">최소 자원</span><div class="la-r-wrap">${LA_GAIN.map(([rk, rn, ic]) => `<div class="la-fx sm"><span><i class="fa-solid ${ic}"></i> ${rn}</span>${laStepper(P(['cond', 'min', rk]), (c.min || {})[rk], 0, 10)}</div>`).join('')}</div></div>
      </div>`;
  } else {
    body = `<div class="la-memo"><div class="la-memo-h"><i class="fa-solid fa-note-sticky"></i> 작업 메모 <span>주제 · 필요한 내용 · 예상 선택지 · 예상 결과 — 플레이어에게는 안 보여요</span></div>
      <textarea class="ops-in" rows="10" ${laP(P(['note']))} placeholder="예) 주제 : 공명로 사고 / 필요 : 도시 정전, 공명자 책임론 / A 복구 지원 → 체력−, 균열+ / B 피신 → 정신− / C 고발 → 재산−" oninput="laInput(this)">${laEsc(ev.note || '')}</textarea></div>`;
  }
  return `<div class="ops-card la-form2" data-i="${i}" ondragover="laDragOver(event)" ondragleave="laDragLeave(event)" ondrop="laDrop(event, ${ev.era}, ${laSlotOf(ev)}, ${i})">
    <div class="la-eh">
      <button class="la-eh-no" onclick="laPickBlock(${i})" data-tip="접기 · 끌어서 옮기기" draggable="true" ondragstart="laDragStart(event, ${i})" ondragend="laDragEnd()"><i class="fa-solid fa-grip-vertical"></i>${no || ''}</button>
      <input class="ops-in la-eh-title" ${laP(P(['title']))} value="${laEsc(ev.title)}" maxlength="60" placeholder="사건 제목" oninput="laInput(this)">
      <button class="ops-btn icon" onclick="laDupEvent(${i})" data-tip="복제"><i class="fa-regular fa-copy"></i></button>
      <button class="ops-btn icon danger" onclick="laDelEvent(${i})" data-tip="삭제"><i class="fa-solid fa-trash-can"></i></button></div>
    <div class="la-meta">
      <label><span>챕터</span><select class="ops-in" ${laP(P(['era']))} data-t="num" onchange="laInput(this, true)">${eraOpts}</select></label>
      <label><span>출신 국가</span><select class="ops-in" onchange='laSetPath(${JSON.stringify(P(["cond", "country"]))}, this.value || undefined); renderLoopAdmin()'>${[['', '전체'], ['arcadia', '아르카디아'], ['nova', '노바']].map(([v, t]) => `<option value="${v}" ${(c.country || '') === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label><span>종류 <i class="la-q" data-tip="체력이 0이 되어 죽을 때 이 종류의 사망 문장이 나와요.">?</i></span><select class="ops-in" ${laP(P(['kind']))} onchange="laInput(this)">${kindOpts}</select></label>
      <label><span>공개 단계</span><select class="ops-in" ${laP(P(['chapter']))} data-t="chapter" onchange="laInput(this, true)">${chOpts}</select></label>
      <label class="tg warn ${ev.draft ? 'on' : ''}"><input type="checkbox" ${laP(P(['draft']))} ${ev.draft ? 'checked' : ''} onchange="laInput(this, true)"><i class="fa-solid fa-pen"></i> 작업 중 (플레이에 안 나옴)</label>
    </div>
    <div class="la-etabs">${tabs}</div>
    <div class="la-ebody">${body}</div>
  </div>`;
}
function laExtraAt(i, k, v) { const x = la.c.events[i].extra[k]; if (v === 'story') { x.at = 'story'; delete x.choice; } else { x.at = 'result'; x.choice = Number(v.slice(1)); } laSyncBar(); }
function laExtraWhen(i, k, type, val) {
  const x = la.c.events[i].extra[k];
  x.when = type === 'always' ? {} : { [type]: type === 'tag' ? String(val || '').trim().toUpperCase() : Number(val) || 0 };
  renderLoopAdmin();
}
function laNextId() { let n = 1; const ids = new Set(la.c.events.map(e => e.id)); while (ids.has(String(n).padStart(3, '0'))) n++; return String(n).padStart(3, '0'); }
function laAddEvent() {
  const at = la.slot || { era: (la.c.eras[0] || {}).id || 1, slot: 1 };
  la.c.events.push({ id: laNextId(), era: at.era, slot: at.slot, title: '새 사건', kind: 'life', draft: true, story: [''], choices: [0, 1, 2].map(() => ({ label: '', hp: 0, mind: 0, result: '', tags: [] })) });
  la.sel = la.c.events.length - 1; la.q = '';
  renderLoopAdmin();
}
function laDupEvent(i) { const ev = JSON.parse(JSON.stringify(la.c.events[i])); ev.id = laNextId(); ev.title += ' (복제)'; la.c.events.splice(i + 1, 0, ev); la.sel = i + 1; renderLoopAdmin(); }
function laDelEvent(i) {
  uiConfirm(`「${la.c.events[i].title}」 사건을 지울까요? 저장해야 반영돼요.`, { title: '사건 지우기', okText: '지우기', icon: 'fa-trash-can' }).then(ok => {
    if (!ok) return; la.c.events.splice(i, 1); la.sel = null; renderLoopAdmin();
  });
}

// ── 규칙 · 수치 ─────────────────────────────────
const LA_RTABS = [['base', '체력 · 정신 · 순서', 'fa-heart'], ['eras', '시대', 'fa-hourglass-half'], ['res', '자원 · 해결', 'fa-coins'], ['strain', '균열 압력', 'fa-house-crack']];
function laRulesHtml() {
  const r = la.c.rules;
  la.rtab = la.rtab || 'base';
  const tabs = LA_RTABS.map(([k, t, ic]) => `<button class="${la.rtab === k ? 'on' : ''}" onclick="la.rtab='${k}'; renderLoopAdmin()"><i class="fa-solid ${ic}"></i>${t}</button>`).join('');
  let body = '';
  if (la.rtab === 'base') {
    body = `<div class="la-rows">
        <div class="la-r"><span class="lb"><i class="fa-solid fa-heart"></i> 체력</span><span class="la-r-k">시작</span>${laStepper(['rules', 'hp_start'], r.hp_start, 1, 20)}<span class="la-r-k">최대</span>${laStepper(['rules', 'hp_max'], r.hp_max, 1, 20)}<span class="la-r-note">0이 되면 사망</span></div>
        <div class="la-r"><span class="lb"><i class="fa-solid fa-brain"></i> 정신</span><span class="la-r-k">시작</span>${laStepper(['rules', 'mind_start'], r.mind_start, 1, 20)}<span class="la-r-k">최대</span>${laStepper(['rules', 'mind_max'], r.mind_max, 1, 20)}<span class="la-r-note">0이 되면 정신 붕괴</span></div>
        <div class="la-r"><span class="lb"><i class="fa-solid fa-route"></i> 첫 생애 시대 순서</span><input class="ops-in" ${laP(['rules', 'first_life'])} data-t="seq" value="${r.first_life.join(', ')}" onchange="laInput(this, true)">${laSeqChips(r.first_life)}</div>
        <div class="la-r"><span class="lb"><i class="fa-solid fa-infinity"></i> 루프 뒤 시대 순서</span><input class="ops-in" ${laP(['rules', 'loop_life'])} data-t="seq" value="${r.loop_life.join(', ')}" onchange="laInput(this, true)">${laSeqChips(r.loop_life)}</div>
      </div>
      <div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 시대 순서는 시대 번호를 쉼표로 적어요. 마지막 시대의 사건을 모두 견디면 '전쟁 이후' 엔딩이에요.</div>
      <div class="la-danger"><div><b>기본값으로 되돌리기</b><span>처음 만들어 둔 사건 · 규칙 · 문장으로 모두 되돌려요. 저장된 편집 내용은 사라져요.</span></div>
        <button class="ops-btn danger" onclick="laResetAll()"><i class="fa-solid fa-rotate"></i> 되돌리기</button></div>`;
  } else if (la.rtab === 'eras') {
    la.eraOpen = la.eraOpen == null ? -1 : la.eraOpen;
    body = `<div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 사건 수만큼 나오면 다음 시대로 넘어가요. 위험 = 선택과 상관없이 체력이나 정신이 1 깎일 확률, 행운 = 더 모자란 쪽이 1 채워질 확률.</div>
      <div class="la-et"><div class="la-et-h"><span>표기</span><span>이름</span><span>시기</span><span>난이도</span><span>사건 수</span><span>위험 %</span><span>행운 %</span><span></span></div>
      ${la.c.eras.map((e, i) => `<div class="la-et-row ${la.eraOpen === i ? 'open' : ''}">
          <input class="ops-in c" ${laP(['eras', i, 'no'])} value="${laEsc(e.no)}" maxlength="8" oninput="laInput(this)">
          <input class="ops-in" ${laP(['eras', i, 'name'])} value="${laEsc(e.name)}" oninput="laInput(this)">
          <input class="ops-in" ${laP(['eras', i, 'period'])} value="${laEsc(e.period)}" oninput="laInput(this)">
          <input class="ops-in" ${laP(['eras', i, 'level'])} value="${laEsc(e.level)}" oninput="laInput(this)">
          ${laStepper(['eras', i, 'len'], e.len, 1, 30)}
          <input class="ops-in num c" type="number" min="0" max="100" ${laP(['eras', i, 'risk'])} data-t="pct" value="${Math.round(e.risk * 100)}" oninput="laInput(this)">
          <input class="ops-in num c" type="number" min="0" max="100" ${laP(['eras', i, 'luck'])} data-t="pct" value="${Math.round(e.luck * 100)}" oninput="laInput(this)">
          <button class="ops-btn la-et-x" onclick="la.eraOpen = la.eraOpen === ${i} ? -1 : ${i}; renderLoopAdmin()">위험 문장 ${(e.risk_text || []).length} <i class="fa-solid fa-chevron-${la.eraOpen === i ? 'up' : 'down'}"></i></button>
        </div>
        ${la.eraOpen === i ? `<div class="la-et-more">${(e.risk_text || []).map((t, k) => `<div class="la-rt2">${laSeg(['eras', i, 'risk_text', k, 'stat'], t.stat, [['hp', '체력'], ['mind', '정신']])}
            <input class="ops-in" ${laP(['eras', i, 'risk_text', k, 'text'])} value="${laEsc(t.text)}" oninput="laInput(this)">
            <button class="ops-btn icon danger" onclick="la.c.eras[${i}].risk_text.splice(${k}, 1); renderLoopAdmin()"><i class="fa-solid fa-trash-can"></i></button></div>`).join('')}
          <button class="ops-btn" onclick="la.c.eras[${i}].risk_text.push({ stat: 'hp', text: '' }); renderLoopAdmin()"><i class="fa-solid fa-plus"></i> 위험 문장 추가</button></div>` : ''}`).join('')}
      </div>`;
  } else if (la.rtab === 'res') {
    const rr = r.res, C2 = { arcadia: '아르카디아', nova: '노바' };
    const rng = (cc, pv, k) => { const v = rr.start[cc][pv][k]; return `<span class="la-rng2">${laStepper(['rules', 'res', 'start', cc, pv, k, 0], v[0], 0, 10)}<i>~</i>${laStepper(['rules', 'res', 'start', cc, pv, k, 1], v[1], 0, 10)}</span>`; };
    body = `<div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 재산 · 지능은 써서 줄어드는 자원, 재능(노바는 '기술')은 선택지 조건으로 쓰는 능력치예요.</div>
      <div class="la-blk"><div class="la-blk-h"><b>해결 비용</b><span>사건을 자원으로 넘길 때 드는 양 · 0이면 그 자원으로는 해결 못 해요</span></div>
        <div class="la-mx cost"><span></span><span class="h"><i class="fa-solid fa-coins"></i> 재산</span><span class="h"><i class="fa-solid fa-lightbulb"></i> 지능</span>
        ${Object.entries(C2).map(([cc, cn]) => `<span class="cc">${cn}</span>${['wealth', 'intel'].map(k => `<span>${laStepper(['rules', 'res', 'cost', cc, k], rr.cost[cc][k], 0, 10)}</span>`).join('')}`).join('')}</div>
        <div class="la-rows" style="margin-top:12px">
          <div class="la-r"><span class="lb">해결 쓰는 시대</span><input class="ops-in" ${laP(['rules', 'res', 'solve_eras'])} data-t="seq" value="${(rr.solve_eras || []).join(', ')}" onchange="laInput(this, true)">${laSeqChips(rr.solve_eras || [])}</div>
          <div class="la-r"><span class="lb">자원 최대</span>${laStepper(['rules', 'res', 'max'], rr.max, 1, 10)}</div></div></div>
      <div class="la-blk"><div class="la-blk-h"><b>시작 자원</b><span>생애를 시작할 때 이 범위에서 무작위</span></div>
        <div class="la-mx start"><span></span><span></span>${LA_RES.map(([, rn, ic]) => `<span class="h"><i class="fa-solid ${ic}"></i> ${rn}</span>`).join('')}
        ${Object.entries(C2).map(([cc, cn], ci) => `${ci ? '<i class="sep"></i>' : ''}<span class="cc" style="grid-row: span 2">${cn}</span>` + [['priv', '기득권'], ['non', '비기득권']].map(([pv, pn]) => `<span class="pv">${pn}</span>${LA_RES.map(([rk]) => `<span>${rng(cc, pv, rk)}</span>`).join('')}`).join('')).join('')}</div>
        <div class="la-hint-line" style="margin-top:10px">아르카디아는 공명자, 노바는 비공명자가 기득권이에요.</div></div>`;
  } else {
    const st = r.strain;
    body = `<div class="la-hint-line"><i class="fa-solid fa-circle-info"></i> 문명을 밀어붙이는 선택(+)으로 쌓이고, 쌓인 만큼 선택과 상관없이 재난이 덮쳐요. 절제하는 선택(−)으로 내려가요. 재난 문장은 '문장'에서 고쳐요.</div>
      <div class="la-rows">
        <div class="la-r"><span class="lb">최대</span>${laStepper(['rules', 'strain', 'max'], st.max, 1, 20)}</div>
        <div class="la-r"><span class="lb">압력 1당 재난 확률</span><input class="ops-in num c" type="number" min="0" max="20" step="0.5" ${laP(['rules', 'strain', 'per'])} data-t="pct" value="${+(st.per * 100).toFixed(1)}" oninput="laInput(this)"><span class="la-r-note">% · 예) 압력 6 × 2.5% = 사건마다 15%</span></div>
        <div class="la-r"><span class="lb">루프 뒤에 남는 비율</span><input class="ops-in num c" type="number" min="0" max="100" ${laP(['rules', 'strain', 'loop_keep'])} data-t="pct" value="${Math.round(st.loop_keep * 100)}" oninput="laInput(this)"><span class="la-r-note">%</span></div>
      </div>`;
  }
  return `<div class="ops-card la-form2"><div class="la-etabs">${tabs}</div><div class="la-ebody">${body}</div></div>`;
}
function laSeqChips(seq) {
  return `<span class="la-seq">${(seq || []).map(id => { const e = (la.c.eras || []).find(x => x.id === id); return `<em>${laEsc(e ? e.no : id)}</em>`; }).join('<i class="fa-solid fa-angle-right"></i>')}</span>`;
}
// ── 문장 ─────────────────────────────────────
function laPrologueHtml() { const h = laTextsAllHtml(); return h.slice(0, h.indexOf(LA_TEXT_SPLIT)); }
function laTextsHtml() { const h = laTextsAllHtml(); return h.slice(h.indexOf(LA_TEXT_SPLIT) + LA_TEXT_SPLIT.length); }
const LA_TEXT_SPLIT = '<div class="la-sec" style="margin-top:20px"><b>나머지 문장</b></div>';
function laTextsAllHtml() {
  const t = la.c.texts;
  const mood = (key, lb, ic) => `<div class="ops-card"><h3><i class="fa-solid ${ic}"></i> ${lb} 상태 문장<span class="sub">값이 이 이상이면</span></h3>
      ${(t[key] || []).map((m, k) => `<div class="la-mood"><div class="ops-row"><input class="ops-in num" type="number" min="0" max="20" ${laP(['texts', key, k, 'min'])} data-t="num" value="${m.min}" oninput="laInput(this)"><span class="ops-hint">이상</span>
        <button class="ops-btn icon danger" style="margin-left:auto" onclick="la.c.texts['${key}'].splice(${k}, 1); renderLoopAdmin()"><i class="fa-solid fa-trash-can"></i></button></div>${laTa(['texts', key, k, 'text'], m.text, 2)}</div>`).join('')}
      <div class="ops-foot"><button class="ops-btn" onclick="la.c.texts['${key}'].push({ min: 0, text: [''] }); renderLoopAdmin()"><i class="fa-solid fa-plus"></i> 추가</button></div></div>`;
  const titled = (group, k, lb) => `<div class="ops-card"><h3>${lb}</h3>
      <div class="ops-field"><span class="lb">제목</span><input class="ops-in" ${laP(['texts', group, k, 'title'])} value="${laEsc(t[group][k].title)}" oninput="laInput(this)"></div>
      <div class="ops-field"><span class="lb">문장 (한 줄 = 한 문단)</span>${laTa(['texts', group, k, 'text'], t[group][k].text, 6)}</div></div>`;
  return `<div class="la-sec"><b>프롤로그</b><span class="ops-hint">생애를 시작하면 사건 전에 나와요. 문명관은 생애마다 무작위로 하나 붙고, 태그가 있으면 사건 조건으로 쓸 수 있어요.</span></div>
    <div class="ops-grid">
      <div class="ops-card"><h3><i class="fa-solid fa-landmark"></i> 서력의 역사<span class="sub">한 줄 = 한 문단</span></h3>${laTa(['texts', 'history'], t.history, 10)}</div>
      <div class="ops-card"><h3><i class="fa-solid fa-baby"></i> 탄생 문장</h3>
        ${[['arcadia', '아르카디아 출신'], ['nova', '노바 출신'], ['res_priv', '공명자 · 기득권'], ['res_non', '공명자 · 비기득권'], ['non_priv', '비공명자 · 기득권'], ['non_non', '비공명자 · 비기득권']].map(([bk, bl]) => `<div class="ops-field"><span class="lb">${bl}</span><input class="ops-in" ${laP(['texts', 'birth', bk])} value="${laEsc((t.birth || {})[bk])}" oninput="laInput(this)"></div>`).join('')}
        <div class="ops-hint" style="margin-top:10px">집안 형편 · 지능 · 재능 문장은 시작 자원(0 · 1 · 2 · 3 이상 네 단계)에 따라 자동으로 붙어요.</div></div>
    </div>
    <div class="la-views">${(t.views || []).map((v, k) => `<div class="ops-card"><h3><i class="fa-solid fa-earth-asia"></i> 문명관 ${k + 1}<span class="sub"><button class="ops-btn icon danger" onclick="la.c.texts.views.splice(${k}, 1); renderLoopAdmin()"><i class="fa-solid fa-trash-can"></i></button></span></h3>
        <div class="la-grid"><div class="ops-field"><span class="lb">이름</span><input class="ops-in" ${laP(['texts', 'views', k, 'name'])} value="${laEsc(v.name)}" oninput="laInput(this)"></div>
        <div class="ops-field la-span2"><span class="lb">붙는 태그</span><input class="ops-in" ${laP(['texts', 'views', k, 'tag'])} value="${laEsc(v.tag)}" oninput="laInput(this)"></div></div>
        <div class="ops-field" style="margin-top:12px"><span class="lb">나오는 출신 국가</span><select class="ops-in" ${laP(['texts', 'views', k, 'country'])} onchange="laInput(this)">${[['', '두 나라 모두'], ['arcadia', '아르카디아만'], ['nova', '노바만']].map(([cv, cl]) => `<option value="${cv}" ${(v.country || '') === cv ? 'selected' : ''}>${cl}</option>`).join('')}</select></div>
        <div class="ops-field" style="margin-top:12px"><span class="lb">나레이션</span>${laTa(['texts', 'views', k, 'text'], v.text, 3)}</div></div>`).join('')}
      <div class="ops-card la-add" onclick="la.c.texts.views.push({ id: 'v' + Date.now().toString(36), name: '새 문명관', tag: '', text: [''] }); renderLoopAdmin()"><i class="fa-solid fa-plus"></i> 문명관 추가</div></div>
    <div class="la-sec" style="margin-top:20px"><b>나머지 문장</b></div>
    <div class="ops-grid">
      <div class="ops-card"><h3><i class="fa-solid fa-seedling"></i> 새 생애 소개</h3>${laTa(['texts', 'intro'], t.intro, 6)}</div>
      <div class="ops-card"><h3><i class="fa-solid fa-house-crack"></i> 재난 문장<span class="sub">균열 압력으로 재난이 덮칠 때, 한 줄에 하나</span></h3>${laTa(['texts', 'purge'], t.purge, 6)}</div>
      <div class="ops-card"><h3><i class="fa-solid fa-leaf"></i> 행운 문장<span class="sub">한 줄에 하나</span></h3>
        <div class="ops-field"><span class="lb">체력이 채워질 때</span>${laTa(['texts', 'luck', 'hp'], t.luck.hp, 3)}</div>
        <div class="ops-field"><span class="lb">정신이 채워질 때</span>${laTa(['texts', 'luck', 'mind'], t.luck.mind, 3)}</div></div>
      <div class="ops-card"><h3><i class="fa-solid fa-key"></i> 해결 문장<span class="sub">재산 · 지능을 써서 넘길 때, 한 줄에 하나</span></h3>
        <div class="ops-field"><span class="lb">재산으로 해결</span>${laTa(['texts', 'solve', 'wealth'], (t.solve || {}).wealth, 3)}</div>
        <div class="ops-field"><span class="lb">지능으로 해결</span>${laTa(['texts', 'solve', 'intel'], (t.solve || {}).intel, 3)}</div></div>
      ${mood('mood_hp', '체력', 'fa-heart')}${mood('mood_mind', '정신', 'fa-brain')}
    </div>
    <div class="la-sec" style="margin-top:20px"><b>사망 문장</b><span class="ops-hint">체력 0이면 마지막 사건의 종류에 맞는 문장, 정신 0이면 '정신 붕괴'. 루프와 닿은 적 있으면 '루프'가 섞여 나와요.</span></div>
    <div class="ops-grid">${Object.keys(t.death).map(k => titled('death', k, LA_KIND[k] || k)).join('')}</div>
    <div class="la-sec" style="margin-top:20px"><b>엔딩 문장</b></div>
    <div class="ops-grid">${titled('ending', 'first', '첫 생애에 살아남았을 때')}${titled('ending', 'loop', '루프 뒤에 살아남았을 때')}${titled('ending', 'pause', '공개 전 시대에 닿았을 때 (잠시 멈춤)')}</div>`;
}

// ── 저장 · 되돌리기 ─────────────────────────────
function laSave() {
  if (!laDirty()) { uiToast('바뀐 내용이 없어요.'); return; }
  socket.emit('loop_admin_save', { content: la.c });
}
function laRevert() {
  if (!laDirty()) return;
  uiConfirm('저장하지 않은 편집을 버리고 마지막 저장으로 돌아갈까요?', { title: '되돌리기', okText: '되돌리기', icon: 'fa-rotate-left' }).then(ok => { if (ok) { la.c = JSON.parse(la.saved); renderLoopAdmin(); } });
}
function laResetAll() {
  uiConfirm('모든 사건 · 규칙 · 문장을 처음 기본값으로 되돌릴까요? 저장된 편집 내용은 사라져요.', { title: '기본값으로 되돌리기', okText: '되돌리기', icon: 'fa-rotate' }).then(ok => { if (ok) socket.emit('loop_admin_reset'); });
}
socket.on('loop_admin', d => {
  la.loading = false;
  la.c = d.content; la.saved = JSON.stringify(d.content); la.custom = !!d.custom;
  if (la.sel != null && !la.c.events[la.sel]) la.sel = 0;
  renderLoopAdmin();
});
socket.on('loop_admin_result', r => { if (r) uiToast(r.message); });
window.addEventListener('beforeunload', e => { if (BATTLE_TYPE === 'play' && laDirty()) { e.preventDefault(); e.returnValue = ''; } });
// 운영진이 저장하면 내 플레이 화면도 새 공개 범위로 다시 불러와요.
socket.on('loop_admin', () => { if (typeof IS_PLAY !== 'undefined' && IS_PLAY) socket.emit('loop_state'); });
