const socket = io();
// 화면 오류 기록 : 스크립트 오류가 나면 서버 오류 기록(logs/)에 메시지 · 위치만 보내요(한 화면에서 최대 5건)
(function () {
  let sent = 0;
  const send = (message, src, line, stack) => {
    if (sent >= 5 || !message) return; sent++;
    try { socket.emit('client_error', { message: String(message).slice(0, 300), src: String(src || '').slice(-120), line: line || '', stack: String(stack || '').slice(0, 1500) }); } catch (e) {}
  };
  window.addEventListener('error', e => { if (e && e.message) send(e.message, e.filename, e.lineno, e.error && e.error.stack); });
  window.addEventListener('unhandledrejection', e => { const r = e && e.reason; send(r && r.message ? r.message : String(r), '', '', r && r.stack); });
})();
// ---------- 연출 순서표 : 컷인 · 피해/회복 숫자 · 라운드 띠가 한꺼번에 터지지 않게 하나씩 차례로 ----------
// fxSchedule(할 일, 그 연출이 차지하는 시간 ms) : 앞 연출이 끝나면(+ 짧은 쉼) 다음 연출이 시작됩니다.
// 창이 가려져 있으면(다른 탭) 쌓아 두지 않고 버립니다. 너무 많이 밀리면 오래된 숫자부터 건너뜁니다.
var fxQ = [], fxBusyUntil = 0, fxPumpTimer = null;
function fxSchedule(fn, dur, kind) {
  if (document.hidden) return;
  if (fxQ.length > 40) fxQ = fxQ.filter(t => t.kind !== 'num');
  fxQ.push({ fn, dur: dur || 0, kind: kind || '' });
  fxPump();
}
function fxPump() {
  if (fxPumpTimer || !fxQ.length) return;
  fxPumpTimer = setTimeout(() => {
    fxPumpTimer = null;
    const t = fxQ.shift();
    try { t.fn(); } catch (e) { console.warn(e); }
    fxBusyUntil = Date.now() + t.dur;
    fxPump();
  }, Math.max(0, fxBusyUntil - Date.now()));
}
// 올리는 파일 크기 기준(사이트 전체 공통, 서버 webapp.py와 같게) : 이미지 15MB, 소리(음악 · 효과음) 20MB
var UPLOAD_IMG_MB = 15, UPLOAD_AUDIO_MB = 20, UPLOAD_IMG_BYTES = UPLOAD_IMG_MB * 1024 * 1024, UPLOAD_AUDIO_BYTES = UPLOAD_AUDIO_MB * 1024 * 1024;
// 접속 기기 : 운영진 유저 리스트에 PC · 태블릿 · 모바일과 운영체제 · 브라우저를 보여주는 용도(운영진에게만 전달)
// LOOP(PLAY 룸) 기록용 기기 번호 : 같은 TEST 아이디라도 기기(브라우저)마다 따로 저장됩니다.
const LOOP_DEVICE = (() => {
  const mk = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, '0')).join('');
  try {
    let v = localStorage.getItem('loopDeviceId');
    if (!/^[A-Za-z0-9]{8,40}$/.test(v || '')) { v = mk(); localStorage.setItem('loopDeviceId', v); }
    return v;
  } catch (e) { return mk(); }
})();
const MY_DEVICE = (() => {
  const ua = navigator.userAgent || '';
  const touch = (navigator.maxTouchPoints || 0) > 1;
  const ipad = /iPad/.test(ua) || (/Macintosh/.test(ua) && touch);  // iPadOS는 Mac처럼 보입니다
  const os = ipad ? 'iPadOS' : /iPhone|iPod/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android'
    : /Windows/.test(ua) ? 'Windows' : /Mac OS X|Macintosh/.test(ua) ? 'macOS' : /CrOS/.test(ua) ? 'ChromeOS' : /Linux/.test(ua) ? 'Linux' : '기타';
  const browser = /SamsungBrowser/.test(ua) ? '삼성 인터넷' : /Whale/.test(ua) ? '웨일' : /Edg\//.test(ua) ? 'Edge'
    : /KAKAOTALK/i.test(ua) ? '카카오톡' : /NAVER/.test(ua) ? '네이버' : /Firefox|FxiOS/.test(ua) ? 'Firefox'
    : /CriOS|Chrome/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : '기타';
  const shortSide = Math.min(screen.width || 0, screen.height || 0);
  const type = ipad || (/Android/.test(ua) && !/Mobile/.test(ua)) || (/Tablet/.test(ua)) ? 'tablet'
    : (/Mobi|iPhone|Android/.test(ua) || (touch && shortSide < 600)) ? 'mobile' : 'pc';
  return { type, os, browser };
})();
let roundDeadlineAt = null;
// 서버 시계와 내 PC 시계의 차이(초). 접속자마다 PC 시계가 조금씩 달라도 타이머/시계가 모두
// 서버 기준으로 똑같이 보이도록, 서버가 상태를 보낼 때 함께 보내는 server_now로 계산합니다.
let serverTimeOffset = 0;
let serverOffsetSampled = false;
function updateServerTimeOffset(serverNow) {
  if (!serverNow) return;
  // 받은 순간 계산한 값은 "실제 차이 - 전송 지연"이라 실제보다 항상 조금 작게 나옵니다.
  // 그래서 여러 번 받은 값 중 가장 큰 값(지연이 가장 짧았던 값)을 씁니다. 단, 2초 넘게
  // 벌어지면 PC 시계가 바뀐 것이므로 새 값으로 바로 갈아탑니다.
  const sample = serverNow - Date.now() / 1000;
  if (!serverOffsetSampled || Math.abs(sample - serverTimeOffset) > 2) serverTimeOffset = sample;
  else serverTimeOffset = Math.max(serverTimeOffset, sample);
  serverOffsetSampled = true;
}
function serverNowSec() {
  return Date.now() / 1000 + serverTimeOffset;
}
let MY_NICKNAME = '';
let chatFilter = 'all';
let lastChat = [];
// '이전 대화 더보기'로 받아 둔 예전 대화 등 : 상태가 뒤쪽 스크립트보다 먼저 도착해도 쓸 수 있게 여기서 선언합니다.
var olderChat = [], olderChatHasMore = null, lastChatTotal = 0, lastPublicChat = [], olderChatLoading = false;
let lastBattleForPanel = null;
let actionPanelActorName = null;
let lastUserInfoHidden = new Set();  // 운영진이 눈을 끈(GM이 아닌 사람에게 숨긴) 이름들
let lastRoster = [];  // 캐릭터 데이터베이스에 등록된 전체 이름 목록 (전투 참여 여부와 무관)
let lastRosterProfiles = {};
var lastFactionPeriod = 1;  // 지금 마이룸 기간(1·2·3차) : 진영 표시에 씁니다
let lastRosterMypage = {};  // 이름 -> 마이페이지용 등록 정보(전투에 없는 캐릭터용)  // 이름 -> { color, avatar_url } (채팅창 프로필 이미지/닉네임 색상용)
let lastOnlineCharacters = [];  // 지금 그 이름으로 로그인(접속)해 있는 캐릭터 이름 목록 (유저 접속정보 팝업용)

const STAT_KEYS = ["체력", "공격", "방어", "이능", "정신", "민첩", "행운"];
// "방어"는 가디언의 능동 방어 부여(아군 지정 가능, type "defend")와 메딕의 "본인방어"를 대신하는
// 표시명(자기 자신만, type "self_defend")이 글자만 같고 서로 다른 행동입니다. ACTION_LABELS는
// 평면 맵이라 같은 글자를 두 값에 매핑할 수 없으므로, resolveActionType()에서 행동자 직군을 보고
// "방어"를 구분해서 풀어줍니다.
const ACTION_LABELS = {
  "공격": "attack", "본인방어": "self_defend", "방어": "defend",
  "회피": "dodge", "힐": "heal", "회복": "heal", "시간초과": "timeout", "도주": "flee",
  "방어 정산": "defense_settle", "이동": "move", "지휘": "command", "배치": "swap", "수호": "guard",
  "붕괴": "collapse", "방출": "emission", "차폐": "shield", "편광": "polarize",
  "환류": "reflux", "복원": "restore", "후공": "declare_defer",
};
function resolveActionType(label, actorRole) {
  return ACTION_LABELS[label];
}
const NEEDS_TARGET = new Set(["attack", "defend", "guard", "heal", "command", "swap", "collapse", "shield", "restore"]);
const MULTI_TARGET_ACTIONS = { "환류": 3 };
const ALLY_TARGET_ACTIONS = new Set(["방어", "수호", "힐", "회복", "배치", "차폐", "복원"]);
const ENEMY_TARGET_ACTIONS = new Set(["공격", "붕괴", "지휘"]);
const SELF_ONLY_ACTIONS = new Set(["본인방어", "회피", "도주", "방어 정산", "방출", "편광"]);
const RANGE_IGNORING_ACTIONS = new Set(["배치"]);
const ROLE_MOVE_COLOR = { "스트라이커": "#ff5555", "가디언": "#4a90ff", "메딕": "#ffe066" };
const ROLE_MOVE_EMOJI = { "스트라이커": "🔴", "가디언": "🔵", "메딕": "🟡" };
const ACTION_RANGE_COLOR = "#ffffff";
// 적(2팀)의 공격 범위 : 적은 범위와 상관없이 공격하지만, 이 안에서 맞으면 받는 피해가 1.2배(서버 config.ENEMY_ZONE_DAMAGE_MULT)
const ENEMY_ZONE_COLOR = "#ff6f8a";

let explicitlyJoined = false;

function updateChatVisibility() {
  // 로그인(캐릭터 입장) 전에도 입력칸/커맨드 블록 자체는 항상 보이고, 전송 버튼만 비활성화합니다.
  // 단, 전투 관전 탭은 애초에 미참여(비로그인) 인원이 모여서 대화하는 곳이라 예외입니다.
  refreshChatSendEnabled();
  refreshCmdPanel();
}

function refreshChatSendEnabled() {
  const btn = document.getElementById('chatSendBtn');
  if (!btn) return;
  const onLogTab = document.getElementById('memberTabLog').classList.contains('active');
  const onSpectateTab = document.getElementById('memberTabSpectate').classList.contains('active');
  btn.disabled = onLogTab ? true : (onSpectateTab ? false : !explicitlyJoined);
}

const SAVED_NAME_KEY = 'joinedName_' + ROOM_ID;
// 방을 옮겨도 로그인이 이어지도록 : 마지막으로 로그인한 캐릭터(모든 방 공통)와 운영진 통행증(7일)
const LAST_NAME_KEY = 'joinedName_last', GM_PASS_KEY = 'gmPass', NO_AUTO_ADMIN_KEY = 'noAutoAdmin';
const WATCH_ONLY = new URLSearchParams(location.search).get('watch') === '1';   // 룸 목록에서 관전으로 들어옴
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }

function silentJoin() {
  // 페이지에 들어오면 일단 '익명'으로 관전만 가능하게 조용히 접속합니다.
  // 실제 캐릭터로 입장하려면 상단 아바타 동그라미를 클릭해야 합니다.
  MY_NICKNAME = '익명';
  socket.emit('join', { room_id: ROOM_ID, key: KEY, nickname: MY_NICKNAME, device: MY_DEVICE });
}

// 새로고침해도 로그인이 유지되도록, 저장된 캐릭터 이름이 있으면 그걸로 바로 재입장을 시도합니다.
function autoRejoinOrSilentJoin() {
  let saved = localStorage.getItem(SAVED_NAME_KEY);
  // 관전으로 들어왔으면 로그인 창 없이 바로 관전
  if (!saved && WATCH_ONLY) { silentJoin(); hideLoginGate(); return; }
  // 이 방에 처음 왔어도, 다른 방에서 로그인한 캐릭터가 있으면 그대로 이어서(LOOP는 TEST 전용이라 제외)
  if (!saved && BATTLE_TYPE !== 'play') saved = lsGet(LAST_NAME_KEY);
  if (saved) {
    // 저장된 이름이 "GM"이었더라도 비밀번호는 저장하지 않으므로, 새로고침 후에는
    // 다시 비밀번호를 입력해야 합니다(권한 우회 방지) - 실패하면 조용히 관전으로 전환합니다.
    attemptCharacterJoin(saved, null, hideLoginGate, () => {
      localStorage.removeItem(SAVED_NAME_KEY);
      if (saved.toLowerCase() === 'gm') lsSet(GM_PASS_KEY, null);
      silentJoin();
      openJoinModal();
    });
  } else if (explicitlyJoined) {
    hideLoginGate();
  } else {
    silentJoin();
    openJoinModal();
  }
}

function attemptCharacterJoin(name, password, onSuccess, onFail) {
  const prevNickname = MY_NICKNAME;
  MY_NICKNAME = name;
  // "GM" + 비밀번호 오류는 서버가 join을 거부하고 error 이벤트만 보냅니다(닉네임이 실제로
  // bind되지 않음) - myControlInfo는 MY_NICKNAME 문자열만 보고 'all'을 반환하므로, 그것만으로는
  // 서버가 실제로 승인했는지 알 수 없습니다. 짧은 시간 동안 error를 감시해서 구분합니다.
  let rejected = false;
  const onErr = () => { rejected = true; };
  socket.once('error', onErr);
  const sentAt = Date.now();
  const gmPass = !password && String(name).toLowerCase() === 'gm' ? lsGet(GM_PASS_KEY) || undefined : undefined;
  socket.emit('join', { room_id: ROOM_ID, key: KEY, nickname: MY_NICKNAME, gm_password: password || undefined, gm_pass: gmPass, device: MY_DEVICE, loop_device: LOOP_DEVICE });
  // 서버가 join → public_state 순으로 응답할 때까지 기다린 뒤(회선이 느리면 오래 걸려요 : 최대 8초), 이 이름이 실제 전투에
  // 참여 중인 캐릭터거나(전투 시작 전이어도) 캐릭터 데이터베이스에 등록되어 있는지 확인합니다.
  // 예전에는 0.35초만 기다려서, 느린 회선 · 재접속 때 로그인된 사람을 '로그인 실패'로 잘못 처리하곤 했어요.
  const waitState = (fn) => {
    const tick = () => {
      if (rejected || lastPublicStateAt > sentAt) return fn(true);
      if (Date.now() - sentAt > 8000) return fn(false);
      setTimeout(tick, 120);
    };
    setTimeout(tick, 200);
  };
  waitState((gotState) => {
    socket.off('error', onErr);
    if (rejected) {
      MY_NICKNAME = prevNickname;
      if (onFail) onFail();
      return;
    }
    const control = myControlInfo(lastBattleForPanel);
    const inBattle = control.scope === 'character' || control.scope === 'all';
    // 끝내 상태를 못 받았으면(연결이 끊김 등) 로그아웃시키지 않고 이름을 그대로 둬요 : 다시 연결되면 자동으로 재입장해요.
    const inRoster = lastRoster.includes(name) || (BATTLE_TYPE === 'play' && name.toUpperCase() === 'TEST') || (!gotState && !password);
    if (BATTLE_TYPE === 'play' && name.toUpperCase() === 'TEST') MY_NICKNAME = 'TEST';
    if (inBattle || inRoster) {
      explicitlyJoined = true;
      updateChatVisibility();
      updateAvatarDots();
      localStorage.setItem(SAVED_NAME_KEY, MY_NICKNAME);
      if (BATTLE_TYPE !== 'play' && MY_NICKNAME !== '익명') { lsSet(LAST_NAME_KEY, MY_NICKNAME); lsSet(NO_AUTO_ADMIN_KEY, null); }
      // 전투 시작 전(팀 편성 미리보기 단계)에 입장하면 lastAllForCards가 아직 비어있으므로,
      // renderCards() 대신 미리보기 카드를 다시 그려줘야 방금 그렸던 카드가 사라지지 않습니다.
      if (lastBattleForPanel) renderCards();
      else if (lastPreviewTeams) renderPreviewCards(lastPreviewTeams);
      updateAvatarDots();
      refreshGmActPanelVisibility();
      refreshCmdPanel();
      refreshGmControlPanelVisibility();
      refreshLogViewControls();
      refreshChatTabSettingsVisibility();
      if (onSuccess) onSuccess();
    } else if (onFail) {
      onFail();
    }
  });
}
var lastPublicStateAt = 0;
// 첫 로딩 가림막 걷기 : 첫 상태를 받아 그리고, 글꼴이 준비된 뒤(최대 7초) 두 프레임 쉬고 부드럽게.
var bootDone = false;
function bootReady(why) {
  if (bootDone) return;
  if (why === 'state') bootReady.state = true;
  if (!(bootReady.state || why === 'timeout')) return;
  bootDone = true;
  const go = () => requestAnimationFrame(() => requestAnimationFrame(() => {
    document.documentElement.classList.remove('booting');
    const v = document.getElementById('bootVeil'); if (v) { v.classList.add('gone'); setTimeout(() => v.remove(), 500); }
  }));
  (document.fonts && document.fonts.ready ? Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 1500))]) : Promise.resolve()).then(() => setTimeout(go, 120));
}
setTimeout(() => bootReady('timeout'), 7000);

// ------------------------------------------------------------------
// 캐릭터 이름으로 입장/로그아웃 (아바타 동그라미 한 번 클릭으로 둘 다 처리)
// ------------------------------------------------------------------
function onAvatarDotClick() {
  // 전투 시작 전(등록된 이름으로만 입장)이거나 전투에 없는 이름으로 입장한 경우에도
  // 로그아웃할 수 있도록, 실제로 입장한 상태인지(explicitlyJoined)만 봅니다.
  if (explicitlyJoined) {
    const who = String(MY_NICKNAME || '').toLowerCase() === 'gm' ? '운영진(GM)' : `'${MY_NICKNAME}'`;
    uiConfirm(`${who}에서 로그아웃할까요?`, {title:'로그아웃', okText:'로그아웃', icon:'fa-power-off'}).then(ok => ok && logout());
  } else {
    openJoinModal();
  }
}

function onInputAvatarDotDblClick() {
  if (!myLoggedInName()) return;
  document.getElementById('myAvatarFileInput').click();
}

function logout() {
  lastTeamChat = [];
  localStorage.removeItem(SAVED_NAME_KEY);
  // 로그아웃하면 모든 방에서 이어지지 않게 : 방마다 저장된 이름 · 마지막 이름 · 운영진 통행증을 다 지워요(LOOP의 TEST는 그대로)
  try { Object.keys(localStorage).filter(k => k.startsWith('joinedName_') && localStorage.getItem(k) !== 'TEST').forEach(k => localStorage.removeItem(k)); } catch (e) {}
  lsSet(LAST_NAME_KEY, null); lsSet(GM_PASS_KEY, null);
  lsSet(NO_AUTO_ADMIN_KEY, '1');   // 메인 페이지 운영진 로그인으로 자동 입장하던 것도 멈춰요(다시 로그인하면 풀려요)
  MY_NICKNAME = '익명';
  socket.emit('join', { room_id: ROOM_ID, key: KEY, nickname: MY_NICKNAME, device: MY_DEVICE });
  explicitlyJoined = false;
  updateChatVisibility();
  updateAvatarDots();
  if (lastBattleForPanel) renderCards();
  else if (lastPreviewTeams) renderPreviewCards(lastPreviewTeams);
  refreshGmActPanelVisibility();
  refreshCmdPanel();
  refreshGmControlPanelVisibility();
  refreshLogViewControls();
  refreshChatTabSettingsVisibility();
  renderMyPage();
  // 전투 방은 관전이 막혀 있을 수 있어요 : 로그아웃하면 룸 목록으로
  if (!IS_LOUNGE && BATTLE_TYPE !== 'play' && window.BT_LOBBY_URL) { location.href = BT_LOBBY_URL; return; }
  openJoinModal();
}

function isMatchedCharacter(battle) {
  if (!explicitlyJoined) return false;
  const control = myControlInfo(battle !== undefined ? battle : lastBattleForPanel);
  return control.scope === 'character' || control.scope === 'all';
}

// 로그인 화면 : 로그인하지 않은 상태에서는 항상 이 화면이 방을 덮습니다(닫기 없음).
function openJoinModal() {
  const g = document.getElementById('loginGate');
  document.getElementById('joinModalError').textContent = '';
  document.getElementById('joinPasswordInput').value = '';
  onJoinNameInput();
  g.classList.add('on'); g.classList.remove('checking');
  document.getElementById('gateGoBtn').disabled = false;
  setTimeout(() => document.getElementById('joinNameInput').focus(), 0);
}
function hideLoginGate() {
  const g = document.getElementById('loginGate');
  g.classList.remove('on', 'checking');
  document.getElementById('joinNameInput').value = '';
  document.getElementById('joinPasswordInput').value = '';
}
const closeJoinModal = hideLoginGate;

// 이름 입력칸에 "GM"을 입력하면 비밀번호 입력칸을 추가로 보여줍니다.
function onJoinNameInput() {
  document.getElementById('joinModalError').textContent = '';
  const gm = document.getElementById('joinNameInput').value.trim().toLowerCase() === 'gm';
  document.getElementById('joinPasswordInput').style.display = gm ? '' : 'none';
  document.getElementById('joinPasswordLabel').style.display = gm ? '' : 'none';
}

function submitJoinModal() {
  const name = document.getElementById('joinNameInput').value.trim();
  if (!name) {
    document.getElementById('joinModalError').textContent = '캐릭터 이름을 입력해주세요.';
    return;
  }
  const isGm = name.toLowerCase() === 'gm';
  const password = isGm ? document.getElementById('joinPasswordInput').value : null;
  if (isGm && !password) {
    document.getElementById('joinModalError').textContent = '비밀번호를 입력해주세요.';
    return;
  }
  const go = document.getElementById('gateGoBtn');
  go.disabled = true;
  document.getElementById('joinModalError').textContent = '';
  attemptCharacterJoin(name, password, () => { go.disabled = false; hideLoginGate(); }, () => {
    go.disabled = false;
    document.getElementById('joinModalError').textContent = isGm
      ? '비밀번호가 올바르지 않습니다.'
      : BATTLE_TYPE === 'play' ? '이 방은 TEST로만 입장할 수 있습니다.' : '등록된 캐릭터 이름이 아닙니다. 이름을 다시 확인해 주세요.';
  });
}

// 마이페이지를 편집할 수 있는지 - 본인 캐릭터로 로그인했거나, GM(남의 마이페이지도 전부 수정 가능)
// 등록된 캐릭터 이름으로 로그인한 상태면 그 이름(전투 참여 여부와 무관), 아니면 null
function myLoggedInName() {
  if (!explicitlyJoined) return null;
  const n = (MY_NICKNAME || '').trim();
  if (!n || n === '익명' || n.toLowerCase() === 'gm') return null;
  if (BATTLE_TYPE === 'play' && n.toUpperCase() === 'TEST') return null;   // LOOP 방 미리보기의 TEST는 보기 전용 예시
  return lastRoster.includes(n) ? n : null;
}
function canEditMyPage() {
  if (typeof myPageIsView === 'function' && myPageIsView()) return false;
  return myControlInfo(lastBattleForPanel).scope === 'all' || !!myLoggedInName();
}
// 지금 마이페이지에 떠 있는 캐릭터 이름 (GM이 남의 마이페이지를 수정할 때 서버에 함께 보냅니다)
function myPageEditName() {
  const c = myPageTargetChar();
  return c ? c.name : undefined;
}

// 색 피커가 화면 구석에서 열리지 않게, 숨긴 입력칸을 누른 점 바로 위로 옮긴 뒤 열어요
function openMyColorPicker(btn) {
  if (!canEditMyPage()) return;
  const input = document.getElementById('myColorInput');
  const r = btn.getBoundingClientRect();
  input.style.left = r.left + 'px';
  input.style.top = r.bottom + 'px';
  input.click();
}
function onMyColorChange(hex) {
  const mypageOpen = document.getElementById('myPageModal').style.display === 'flex';
  socket.emit('set_my_color', { color: hex, name: mypageOpen ? myPageEditName() : undefined });
  if (mypageOpen) {   // 서버 응답 전에 바로 : 색 점 · 프로필 상단 빛줄
    document.getElementById('myPageColorDot').style.background = hex;
    const hero = document.querySelector('#myPageModal .mp-hero'); if (hero) hero.style.setProperty('--mp-c', hex);
  }
}

function myCharacterColor(battle) {
  if (!explicitlyJoined) return null;
  const control = myControlInfo(battle !== undefined ? battle : lastBattleForPanel);
  if (control.scope === 'character') return control.character.color || null;
  return null;
}

// 채팅 입력줄의 네모 칸은 색으로 채우지 않고 항상 프로필 이미지만 보여줍니다(없으면 빈 칸).
function myCharacterAvatarUrl(battle) {
  if (!explicitlyJoined) return null;
  const control = myControlInfo(battle !== undefined ? battle : lastBattleForPanel);
  if (control.scope === 'character') return control.character.avatar_url || null;
  const me = myLoggedInName();
  return me && lastRosterMypage[me] ? (lastRosterMypage[me].avatar_url || null) : null;
}

function updateAvatarDots(battle) {
  if (typeof syncOpsBtn === 'function') setTimeout(syncOpsBtn, 0);
  const url = myCharacterAvatarUrl(battle);
  const el = document.getElementById('inputAvatarDot');
  if (el) el.style.backgroundImage = url ? `url('${url}')` : 'none';
  // 좌측 패널 입장/로그아웃 버튼 : 로그인 전에는 들어가기(→]), 로그인 후에는 나가기([→) 아이콘
  const loginIcon = document.querySelector('#sidebarLoginBtn i');
  if (loginIcon) loginIcon.className = explicitlyJoined ? 'fa-solid fa-power-off' : 'fa-solid fa-right-to-bracket';
  const loginLabel = document.querySelector('#sidebarLoginBtn .sb-label');
  if (loginLabel) loginLabel.textContent = explicitlyJoined ? '로그아웃' : '로그인';
  // 로그인(캐릭터 또는 GM)하지 않았으면 마이페이지 아이콘을 아예 숨깁니다.
  const myBtn = document.getElementById('sidebarMyPageBtn');
  const loggedIn = explicitlyJoined && (myLoggedInName() || myControlInfo(lastBattleForPanel).scope === 'all');
  if (myBtn) myBtn.style.display = loggedIn || (BATTLE_TYPE === 'play' && explicitlyJoined) ? '' : 'none';   // LOOP 방 : 마이페이지 미리보기
  // 로그인하지 않았으면 채팅창과 우체통도 숨깁니다(전투 화면은 그대로 구경할 수 있어요).
  document.body.classList.toggle('logged-out', !loggedIn);
  if (!loggedIn) {
    document.body.classList.remove('m-chat-open');
    const mm = document.getElementById('mailModal'); if (mm) mm.style.display = 'none';
  }
}

socket.on('connect', () => {
  autoRejoinOrSilentJoin();
});

// 세로 태블릿·휴대폰 : 지금 열린 창에 맞춰 하단 탭의 켜진 표시를 옮깁니다.
function syncMobileTab() {
  const open = id => { const m = document.getElementById(id); return !!m && m.style.display === 'flex'; };
  let t = '';
  if (open('sbSheet')) t = 'sheet';   // 하단 탭 위 목록이 떠 있으면 그 묶음 탭이 켜져 보여요
  else if (document.body.classList.contains('m-chat-open')) t = 'chat';
  else if (open('myPageModal')) t = 'my';
  else if (open('shopModal')) t = 'shop';
  else if (open('noticeModal') || open('mailModal') || open('newsSheet')) t = 'news';
  else if (open('userInfoModal')) t = 'users';
  if (t) document.body.dataset.mtab = t; else delete document.body.dataset.mtab;
}
{
  const mo = new MutationObserver(syncMobileTab);
  ['myPageModal', 'shopModal', 'noticeModal', 'mailModal', 'newsSheet', 'userInfoModal', 'sbSheet'].forEach(id => {
    const m = document.getElementById(id); if (m) mo.observe(m, { attributes:true, attributeFilter:['style'] });
  });
  mo.observe(document.body, { attributes:true, attributeFilter:['class'] });
}

// 메뉴 묶음(아코디언) : 소식 · 전투 · 사람. 하위 메뉴는 원래 버튼 그대로라(보이기 규칙 · 알림 점 · 켜진 표시) 묶음 머리가 그 상태를 따라가요.
const SB_MOBILE = () => window.matchMedia('(max-width:900px)').matches;
function sbKids(g) { return [...g.querySelectorAll('.sb-sub-in > .sidebar-icon')].filter(b => getComputedStyle(b).display !== 'none'); }
function sbClose() {
  const sb = document.querySelector('.sidebar'); if (!sb || !sb.classList.contains('sb-open')) return;
  sb.classList.remove('sb-open');
  document.querySelectorAll('.sb-group.open').forEach(g => g.classList.remove('open'));
}
function sbGroupClick(e, gid) {
  e.stopPropagation();
  const g = document.getElementById(gid), kids = sbKids(g);
  if (!kids.length) return;
  if (kids.length === 1) { sbClose(); kids[0].click(); return; }   // 하위 메뉴가 하나뿐이면 바로 그 메뉴로
  if (SB_MOBILE()) { sbSheetOpen(g, kids); return; }
  const sb = document.querySelector('.sidebar');
  if (sb.classList.contains('sb-open') && g.classList.contains('open')) { g.classList.remove('open'); return; }
  document.querySelectorAll('.sb-group.open').forEach(x => x.classList.remove('open'));
  g.classList.add('open'); sb.classList.add('sb-open');
}
function sbSheetOpen(g, kids) {
  const body = document.getElementById('sbSheetBody');
  body.innerHTML = '';
  kids.forEach(k => {
    const b = document.createElement('button');
    const ic = k.querySelector('i'), lb = k.querySelector('.sb-label'), dot = k.querySelector('.notice-dot');
    b.innerHTML = `<i></i><span></span><span class="notice-dot ${dot && dot.classList.contains('on') ? 'on' : ''}"></span><i class="fa-solid fa-chevron-right go"></i>`;
    b.firstChild.className = ic ? ic.className : '';
    b.children[1].textContent = lb ? lb.textContent : '';
    b.onclick = () => { sbSheetClose(); k.click(); };
    body.appendChild(b);
  });
  document.querySelectorAll('.sb-ghead.sheet-on').forEach(h => h.classList.remove('sheet-on'));
  g.querySelector('.sb-ghead').classList.add('sheet-on');
  document.getElementById('sbSheet').style.display = 'flex';
}
function sbSheetClose() {
  document.getElementById('sbSheet').style.display = 'none';
  document.querySelectorAll('.sb-ghead.sheet-on').forEach(h => h.classList.remove('sheet-on'));
}
function sbSync() {
  document.querySelectorAll('.sb-group').forEach(g => {
    const kids = sbKids(g), head = g.querySelector('.sb-ghead');
    if (g.classList.contains('sb-empty') !== !kids.length) g.classList.toggle('sb-empty', !kids.length);
    const act = kids.some(k => k.classList.contains('active'));
    if (head.classList.contains('active') !== act) head.classList.toggle('active', act);
    const dotOn = kids.some(k => { const d = k.querySelector('.notice-dot'); return d && d.classList.contains('on'); });
    const hd = head.querySelector('.notice-dot');
    if (hd.classList.contains('on') !== dotOn) hd.classList.toggle('on', dotOn);
    // 하위 메뉴가 하나뿐이면 묶음 머리가 그 메뉴의 아이콘 · 이름을 그대로 써요
    if (!head.dataset.icon) { head.dataset.icon = head.querySelector('i').className; head.dataset.label = head.querySelector('.sb-label').textContent; }
    const one = kids.length === 1 ? kids[0] : null;
    const ic = one ? one.querySelector('i').className : head.dataset.icon;
    const lb = one ? one.querySelector('.sb-label').textContent : head.dataset.label;
    const hi = head.querySelector('i'), hl = head.querySelector('.sb-label');
    if (hi.className !== ic) hi.className = ic;
    if (hl.textContent !== lb) hl.textContent = lb;
    if (head.getAttribute('aria-label') !== lb) head.setAttribute('aria-label', lb);
    if (head.classList.contains('single') !== !!one) head.classList.toggle('single', !!one);
  });
}
{
  const sb = document.querySelector('.sidebar');
  let raf = 0;
  const later = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; sbSync(); }); };
  new MutationObserver(later).observe(sb, { subtree:true, attributes:true, attributeFilter:['class', 'style'] });
  new MutationObserver(later).observe(document.body, { attributes:true, attributeFilter:['class'] });
  window.addEventListener('resize', () => { later(); if (SB_MOBILE()) sbClose(); else sbSheetClose(); });
  sbSync();
  // 펼친 메뉴 : 메뉴를 고르면(소리 버튼 빼고) · 바깥을 누르면 · Esc로 접혀요
  sb.addEventListener('click', e => {
    const b = e.target.closest('.sidebar-icon');
    if (b && !b.classList.contains('sb-ghead') && b.id !== 'sidebarSoundBtn') sbClose();
  });
  document.addEventListener('click', e => { if (!sb.contains(e.target)) sbClose(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') sbClose(); });
}

// 세로 태블릿·휴대폰 : 하단 탭을 누르면 열려 있던 창 · 채팅을 닫고 그 탭으로 이동합니다.
document.querySelector('.sidebar').addEventListener('click', (e) => {
  if (!window.matchMedia('(max-width:900px)').matches || !e.target.closest('.sidebar-icon') || e.target.closest('.sb-ghead')) return;
  if (typeof noticeEditing !== 'undefined' && noticeEditing && document.getElementById('noticeModal').style.display === 'flex') {
    e.stopPropagation(); closeNotices(); return;
  }
  const closers = { myPageModal: closeMyPage, noticeModal: closeNotices };
  let closed = 0;
  document.querySelectorAll('.modal-overlay').forEach(m => {
    if (m.id === 'uiDialog' || getComputedStyle(m).display === 'none') return;
    if (closers[m.id]) closers[m.id](); else m.style.display = 'none';
    closed++;
  });
  // 채팅 탭 : 채팅 위에 유저 리스트 등이 떠 있으면 그것만 닫고 채팅으로 돌아오고, 아니면 채팅을 열고 닫습니다.
  if (e.target.closest('#sidebarChatBtn')) {
    if (closed && document.body.classList.contains('m-chat-open')) e.stopPropagation();
    return;
  }
  document.body.classList.remove('m-chat-open');
}, true);

socket.on('joined', (d) => {
  if (d && d.gm_pass) lsSet(GM_PASS_KEY, d.gm_pass);
  if (d && d.admin && !explicitlyJoined && BATTLE_TYPE !== 'play' && !WATCH_ONLY && !lsGet(NO_AUTO_ADMIN_KEY)) attemptCharacterJoin('GM', null, hideLoginGate);
  updateAvatarDots();
});

// 'i' 아이콘(운영진이 PVP 카드용으로 디자인한 것) : 알림 토스트 · 안내 창 · 카드 정보에 같이 씁니다.
var UI_INFO_SVG = `<svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
<path opacity="0.8" d="M5.9999 11.6004C9.0927 11.6004 11.5999 9.09319 11.5999 6.00039C11.5999 2.9076 9.0927 0.400391 5.9999 0.400391C2.90711 0.400391 0.399902 2.9076 0.399902 6.00039C0.399902 9.09319 2.90711 11.6004 5.9999 11.6004Z" fill="#B3B3B3" fill-opacity="0.2" stroke="white" stroke-width="0.8"/>
<path d="M6.3 4.74348V8.79948H5.54V4.74348H6.3ZM5.5 3.06348H6.34V3.91148H5.5V3.06348Z" fill="white"/>
</svg>`;
// 알림 토스트(공통) : 모든 안내 · 오류 메시지가 같은 모양으로 화면 아래 가운데에 잠깐 떠요. kind : 'info' | 'error'
function uiToast(msg, kind, ms) {
  const el = document.getElementById('shopToast'); if (!el || !msg) return;
  el.className = kind === 'error' ? 'err' : '';
  el.innerHTML = `<span class="t-ic">${UI_INFO_SVG}</span><span class="t-msg"></span>`;
  el.querySelector('.t-msg').textContent = msg;
  void el.offsetWidth; el.classList.add('show');
  clearTimeout(uiToast._t);
  uiToast._t = setTimeout(() => el.classList.remove('show'), ms || (kind === 'error' ? 4500 : 2600));
}
function showError(msg) { uiToast(msg, 'error'); }

socket.on('error', (d) => { if (!(d && d.quiet)) showError(d.message); });   // quiet : 로그인 전 관전 입장 거절(로그인 창으로 충분)
socket.on('action_error', (d) => showError(d.message));

// 화면 파일(html)과 짝이 맞는 서버 버전. 서버 .py를 고치면 webapp.py의 SERVER_BUILD와 함께 올립니다.
const EXPECTED_SERVER_BUILD = "2026-10-13.101";
socket.on('public_state', (state) => {
  lastPublicStateAt = Date.now();
  bootReady('state');
  const notice = document.getElementById('serverRestartNotice');
  if (notice) notice.style.display = state.server_build === EXPECTED_SERVER_BUILD ? 'none' : '';
  const roomNameEl = document.getElementById('roomNameLabel');
  if (roomNameEl && state.room_name) roomNameEl.textContent = state.room_name;
  const gateRoom = document.getElementById('gateRoomName');
  if (gateRoom && state.room_name) gateRoom.textContent = state.room_name;
  lastRoster = state.roster || [];
  lastUserInfoHidden = new Set(state.userinfo_hidden || []);
  lastRosterProfiles = state.roster_profiles || {};
  lastRosterMypage = state.roster_mypage || {};
  if (state.faction_period) lastFactionPeriod = state.faction_period;
  if (document.getElementById('myPageModal') && document.getElementById('myPageModal').style.display === 'flex' && !(homeMenu && homeMenu.open)) renderMyPageHome(myPageTargetChar());
  lastShop = state.shop || lastShop;
  lastMapBg = state.map_bg || null;
  if (state.sfx_defaults) lastSfxDefaults = state.sfx_defaults;
  lastTrackBg = state.track_bg || null;
  lastScene = state.scene || null;
  applyScene();
  lastBossImages = state.boss_images || {};
  lastOnlineCharacters = state.online_characters || [];
  if (playPreviewOn()) playPreviewFill();   // LOOP 방 : 예시 캐릭터로
  if (document.getElementById('userInfoModal').style.display === 'flex') renderUserInfoList();
  lastSiteDice = state.site_dice || null;
  lastAttackLines = state.attack_lines || [];
  lastPreviewTeams = state.preview_teams || null;
  telegraphRevealedCells = new Set((state.telegraph_cells || []).map(([x, y]) => `${x},${y}`));
  lastPublicObstacleHits = state.obstacle_hits || 3;
  lastBattleForPanel = fillGmMobHp(state.battle);
  if (state.chat_tabs) chatTabsEnabled = state.chat_tabs;
  if (state.chat_tab_labels) chatTabLabels = state.chat_tab_labels;
  applyChatTabLabels();
  renderChatTabVisibility();
  renderBattle(lastBattleForPanel);
  renderPubLog(state.log, state.log_total);
  lastChatTotal = state.chat_total != null ? state.chat_total : (state.chat || []).length;
  renderChat(state.chat);
  renderMusic(state.music, state.server_now);
  renderShop();
  { const bs = document.getElementById('btShop'); if (bs) bs.outerHTML = btShopHtml(); }   // 룸 목록의 상점 블럭 : P · 소지품 개수 갱신
  renderMyPagePoints();
  applyMapBackground();
  renderMapBgModal();
  renderSoundSettings();
  renderRoundTrack();
  renderTrackBgModal();
});

socket.on('battle_starting', () => {
  document.getElementById('formatLabel').textContent = '전투 시작...';
  document.getElementById('roundInfo').textContent = '선후공 다이스를 굴리는 중...';
});

// 스킬 기록이 오면 그 캐릭터 칸 위로 ✶. 컷인이 함께 나오면 컷인이 끝난 뒤(약 3초)에 띄워 가려지지 않게 합니다.
socket.on('chat_message', (entry) => { appendChat(entry); if (entry && entry.category === 'skill') popSkillMark(entry.nickname, entry.fx ? 3000 : 0); });
// 스킬을 쓴 캐릭터의 지도 칸 윗선 위로 ✶를 띄웁니다(격자 전투에서만).
function popSkillMark(name, delayMs) {
  if (delayMs) { setTimeout(() => popSkillMark(name, 0), delayMs); return; }
  const frame = document.querySelector('#gridSection .map-frame');
  const table = document.querySelector('#gridMap table.gmap');
  const c = (lastAllForCards || []).find(x => x.name === name);
  if (!frame || !table || !c || !c.grid_pos) return;
  const row = table.rows[c.grid_pos[1]];
  const td = row && row.cells[c.grid_pos[0]];
  if (!td) return;
  const fr = frame.getBoundingClientRect(), r = td.getBoundingClientRect();
  const el = document.createElement('span');
  el.className = 'skill-pop';
  el.textContent = '✶';
  el.style.left = (r.left - fr.left + frame.scrollLeft + r.width / 2) + 'px';
  el.style.top = (r.top - fr.top + frame.scrollTop) + 'px';
  frame.appendChild(el);
  setTimeout(() => el.remove(), 1900);
}

function statsTitle(c) {
  const parts = STAT_KEYS.map(k => `${k} ${c.stats[k]}`);
  parts.push(`총합 ${c.stat_total}`);
  return parts.join(' · ');
}

// ------------------------------------------------------------------
// 실시간 시계
// ------------------------------------------------------------------
// 세계관 날짜 · 시간 표기(화면 전체 공통) : 연도 대신 '空歷', 월日 한자, 오전/오후 대신 AM/PM
//   etTime(13, 7)            → "PM.01:07"
//   etDate(date)             → "空歷 10月14日"
//   etStamp(date)            → "空歷 10月14日 PM.01:07"
function etPad(n) { return String(n).padStart(2, '0'); }
function etTime(h, m, sec) {
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h < 12 ? 'AM' : 'PM'}.${etPad(h12)}:${etPad(m)}${sec != null ? ':' + etPad(sec) : ''}`;
}
function etDate(d) { return `空歷 ${etPad(d.getMonth() + 1)}月${etPad(d.getDate())}日`; }
function etStamp(d) { return `${etDate(d)} ${etTime(d.getHours(), d.getMinutes())}`; }
function tickClock() {
  const el = document.getElementById('liveClock');
  if (!el) return;
  const now = new Date(serverNowSec() * 1000);  // 서버 시각 기준
  // 세계관 표기 : 연도 대신 항상 '空歷'(공력), 예) 空歷 10月06日 AM.10:18:32
  const pad = n => String(n).padStart(2, '0');
  const h24 = now.getHours();
  const ampm = h24 < 12 ? 'AM' : 'PM';
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  const t = `${etDate(now)} ${etTime(h24, now.getMinutes(), now.getSeconds())}`;
  if (el.textContent !== t) el.textContent = t;   // 글자가 바뀔 때만 그려요
}
setInterval(tickClock, 200);
tickClock();

// ------------------------------------------------------------------
// 카드 정렬 - 항상 포지션(스트라이커 → 가디언 → 메딕) 순으로 고정합니다.
// ------------------------------------------------------------------
const ROLE_SORT_ORDER = { '스트라이커': 0, '가디언': 1, '메딕': 2 };

function sortByRole(all) {
  const arr = all.slice();
  arr.sort((a, b) => {
    const ra = ROLE_SORT_ORDER[a.role] ?? 99;
    const rb = ROLE_SORT_ORDER[b.role] ?? 99;
    return ra - rb || a.name.localeCompare(b.name);
  });
  return arr;
}

let mobCarouselIndex = 0;
// BOSS(부위 4개)처럼 한 개체가 여러 부위로 나뉘어 있을 때만 의미 있는 보기 모드.
// 'total' = 부위 전체 합산 HP 하나로, 'parts' = 부위별로 슬라이드(페이지네이션)해서.
let siteViewMode = 'total';

function renderSiteStatusCard(battle) {
  const el = document.getElementById('siteStatusCard');
  const toggleEl = document.getElementById('siteViewToggle');
  if (!el) return;
  const isSiege = BATTLE_TYPE === 'siege';
  const isMassRaid = BATTLE_TYPE === 'mass_raid';
  if ((!isSiege && !isMassRaid) || !battle || !battle.team_b || !battle.team_b.length) {
    el.style.display = 'none';
    if (toggleEl) toggleEl.style.display = 'none';
    return;
  }
  const mobs = battle.team_b;
  const isBossGroup = mobs.length > 1 && mobs[0].boss_group && mobs.every(m => m.boss_group === mobs[0].boss_group);
  if (mobCarouselIndex >= mobs.length) mobCarouselIndex = 0;
  const dice = lastSiteDice;
  const diceText = (isSiege && dice && dice.value) ? ` (${dice.used}/${dice.value})` : '';

  // 카드 목록 위 정렬 탭(체력순/포지션순/가나다순)과 같은 자리에, 카드 위에 올라오는
  // 좌측정렬 탭 형태로 전체/개별을 전환합니다. BOSS처럼 부위가 여럿일 때만 보입니다.
  if (toggleEl) {
    toggleEl.style.display = isBossGroup ? '' : 'none';
    document.getElementById('siteModeTotalBtn').classList.toggle('active', siteViewMode === 'total');
    document.getElementById('siteModePartsBtn').classList.toggle('active', siteViewMode === 'parts');
  }

  if (isBossGroup && siteViewMode === 'total') {
    const totalCurrent = mobs.reduce((sum, m) => sum + m.current_hp, 0);
    const totalMax = mobs.reduce((sum, m) => sum + m.max_hp, 0);
    const hpRatio = totalMax > 0 ? totalCurrent / totalMax : 0;
    // 그룹 이름표는 첫 부위 이름의 첫 토큰(공백/하이픈 앞)을 씁니다 - "BOSS-NW"→"BOSS",
    // "NOVA 1구역"→"NOVA"처럼, 합성 이름이든 원래 고유한 이름이든 자연스럽게 뽑힙니다.
    const groupLabel = mobs[0].name.split(/[ -]/)[0];
    el.innerHTML = `
      <div class="site-head">
        <div class="site-title">${groupLabel}${diceText}</div>
        <div class="site-hp">${mobs.some(m => m.hp_hidden) ? '???' : `${totalCurrent}/${totalMax}`}</div>
      </div>
      <div class="hpbar-track" style="margin-top:8px;"><div class="hpbar-fill ${hpRatio <= 0.3 ? 'low' : (hpRatio <= 0.6 ? 'mid' : '')}" style="width:${Math.max(0, hpRatio * 100)}%;"></div></div>
    `;
    el.classList.toggle('is-defeated', mobs.every(isDefeatedStatus));
    el.style.display = '';
    el.dataset.fx = 'group:' + groupLabel; el.dataset.hp = totalCurrent; el.dataset.max = totalMax;
    if (mobs.some(m => m.hp_hidden)) el.dataset.hpHidden = '1'; else delete el.dataset.hpHidden;
    runHpFx(el.parentNode || el);
    return;
  }

  const site = mobs[mobCarouselIndex];
  const hpRatio = site.max_hp > 0 ? site.current_hp / site.max_hp : 0;
  const badges = [];
  if (site.defense_count) badges.push(makeStatusTag('guard', `수호${site.defense_count > 1 ? ' ' + site.defense_count : ''}`));
  if (site.shield_hp) badges.push(makeStatusTag('shield', `보호막 ${site.shield_hp}`));
  if (site.has_leech_buff) badges.push(makeStatusTag('leech', '흡수'));
  const navHtml = (mobs.length > 1)
    ? `<div class="site-nav">
        <button onclick="shiftMobCarousel(-1)" aria-label="이전 몹">‹</button>
        <span>${mobCarouselIndex + 1} / ${mobs.length}</span>
        <button onclick="shiftMobCarousel(1)" aria-label="다음 몹">›</button>
      </div>`
    : '';
  el.innerHTML = `
    <div class="site-head">
      <div class="site-title">${displayNameOf(site)}${diceText}${statusTagFor(site)}</div>
      <div class="site-hp">${hpNumText(site)}</div>
    </div>
    <div class="hpbar-track" style="margin-top:8px;"><div class="hpbar-fill ${hpRatio <= 0.3 ? 'low' : (hpRatio <= 0.6 ? 'mid' : '')}" style="width:${Math.max(0, hpRatio * 100)}%;"></div></div>
    ${badges.length ? `<div class="cbadges" style="margin-top:8px;">${badges.join('&nbsp;&nbsp;')}</div>` : ''}
    ${navHtml}
  `;
  el.classList.toggle('is-defeated', isDefeatedStatus(site));
  el.style.display = '';
  el.dataset.fx = site.name; el.dataset.hp = site.current_hp; el.dataset.max = site.max_hp;
  if (site.hp_hidden) el.dataset.hpHidden = '1'; else delete el.dataset.hpHidden;
  runHpFx(el.parentNode || el);
}

function setSiteViewMode(mode) {
  siteViewMode = mode;
  renderSiteStatusCard(lastBattleForPanel);
}

function shiftMobCarousel(delta) {
  const battle = lastBattleForPanel;
  if (!battle || !battle.team_b || !battle.team_b.length) return;
  const len = battle.team_b.length;
  mobCarouselIndex = (mobCarouselIndex + delta + len) % len;
  renderSiteStatusCard(battle);
}

let lastPreviewTeams = null;  // 전투 시작 전 "무작위 배치" 미리보기 - {"team_a":[...], "team_b":[...]} 또는 null

// 1팀/2팀(teamLabel 'A'/'B')을 각자의 칸(teamsA/teamsB)에 나눠 그립니다. 공성전/마스 레이드는 2팀(거점/몹)을
// siteStatusCard에서 따로 보여주므로 2팀 칸은 통째로 숨깁니다. 두 팀 모두 항상 포지션 순
// (스트라이커 → 가디언 → 메딕)으로 고정 정렬합니다.
function splitAndRenderTeams(list, renderOne) {
  const allA = list.filter(c => c.teamLabel === 'A');
  const allB = list.filter(c => c.teamLabel === 'B');
  document.getElementById('teamsA').innerHTML = sortByRole(allA).map(renderOne).join('');
  const teamBBlock = document.getElementById('teamBBlock');
  if (BATTLE_TYPE === 'pvp') {
    document.getElementById('teamsB').innerHTML = sortByRole(allB).map(renderOne).join('');
    if (teamBBlock) teamBBlock.style.display = '';
  } else if (teamBBlock) {
    teamBBlock.style.display = 'none';
  }
}

function renderPreviewCards(previewTeams) {
  // 실제 전투 화면과 완전히 같은 카드 렌더러를 재사용합니다(마스 레이드는 컴팩트,
  // 그 외는 일반 카드) - 그래야 "미리보기"와 "전투 시작 후" 카드 UI가 절대 어긋나지 않습니다.
  const all = [
    ...(previewTeams.team_a || []).map(c => ({ ...c, teamLabel: 'A' })),
    ...(previewTeams.team_b || []).map(c => ({ ...c, teamLabel: 'B' })),
  ];
  const renderOne = BATTLE_TYPE === 'mass_raid' ? renderCompactCardHtml : renderCardHtml;
  splitAndRenderTeams(all, renderOne);
}

function renderBattle(battle) {
  if (!battle) {
    document.getElementById('formatLabel').textContent = '(전투 시작 전)';
    document.getElementById('roundInfo').textContent = lastPreviewTeams ? '팀 편성 미리보기' : '-';
    roundDeadlineAt = null;
    tickTimer();
    if (lastPreviewTeams) {
      renderPreviewCards(lastPreviewTeams);
    } else {
      document.getElementById('teamsA').innerHTML = '';
      document.getElementById('teamsB').innerHTML = '';
    }
    lastAllForCards = [];
    fxHpMemory = {};
    fxLastRound = null;
    renderSiteStatusCard(null);
    renderGrid(null, []);
    renderMyPage();   // 전투가 없을 때(라운지 등)도 마이페이지 수정이 바로 보이게
    return;
  }
  document.getElementById('formatLabel').textContent = `${battle.format_label} ${BATTLE_TYPE_LABEL}`;
  document.getElementById('roundInfo').textContent = battle.finished
    ? `종료 - ${battle.winner ? battle.winner + ' 승리' : '무승부'}`
    : `Round ${battle.round_no} · ${battle.current_turn_team === battle.round_first_team ? '선공' : '후공'} · ${battle.current_turn_team} 행동`;
  roundDeadlineAt = battle.finished ? null : battle.round_deadline_at;
  tickTimer();
  maybeShowRoundBanner(battle);

  const control = myControlInfo(battle);
  const seesAll = control.scope === 'all';
  const myTeam = control.scope === 'character' ? control.character.team : null;

  const all = [...battle.team_a.map(c => ({...c, teamLabel:'A'})), ...battle.team_b.map(c => ({...c, teamLabel:'B'}))];
  lastAllForCards = all;
  lastCanSeeStats = seesAll || myTeam !== null;
  lastMyTeam = myTeam;
  lastSeesAll = seesAll;
  lastForcedTargetNames = new Set((battle.forced_targets || []).map(f => f.target));
  renderCards();
  renderSiteStatusCard(battle);
  updateAvatarDots(battle);
  refreshGmActPanelVisibility();
  refreshCmdPanel();
  refreshGmControlPanelVisibility();
  refreshLogViewControls();
  refreshChatTabSettingsVisibility();
  renderMyPage();

  renderGrid(battle, all);
}

function renderCards() {
  const useCompact = BATTLE_TYPE === 'mass_raid';
  const renderOne = useCompact ? renderCompactCardHtml : renderCardHtml;
  // 공성전/마스 레이드는 러너(1팀)만 이 칸에 넣습니다(2팀은 siteStatusCard에서 따로 보여줍니다).
  splitAndRenderTeams(lastAllForCards, renderOne);
  if (lastBattleForPanel) runHpFx(document);
  const slot = document.getElementById('multiSkillSlot');
  if (slot) slot.innerHTML = renderMultiSkillTrigger();
}

// 완전히 사망/도주 성공한 상태만 카드 전체를 무채색으로 흐리게 처리합니다. 다운(기절)과
// 도주 시도 중(아직 상대 턴을 못 넘김)은 아직 되돌아올 수 있는 상태라, 회색 처리 없이
// 이름 옆에 *상태 표시만 남깁니다(statusTagFor).
function isDefeatedStatus(c) {
  return c.status === 'dead' || c.status === 'fled';
}
function statusTagFor(c) {
  const t = statusTagBase(c);
  // PVP : 한 차례에 여러 번 행동하는 캐릭터(NPC 등)는 남은 횟수를 같이
  if (!t && (c.actions_per_turn || 1) > 1) return ` *행동 ${c.actions_left != null ? c.actions_left : c.actions_per_turn}/${c.actions_per_turn}`;
  return t;
}
function statusTagBase(c) {
  if (c.status === 'dead') return ' *사망';
  if (c.status === 'fled' || c.status === 'fleeing') return ' *도주';
  if (c.status === 'downed') return ' *기절';
  if (c.dodging_this_round) return ' *회피';
  return '';
}

// 몹(운영진이 정함) : 참가자 화면에는 정확한 체력 대신 비율(100 기준)만 와요 → 숫자는 ???로
function hpNumText(c) { return c && c.hp_hidden ? '???' : `${c.current_hp}/${c.max_hp}`; }
function hpHiddenAttr(c) { return c && c.hp_hidden ? ' data-hp-hidden="1"' : ''; }
function renderCompactCardHtml(c) {
  const isTarget = selectedTargetName === c.name;
  const canSeeStats = lastSeesAll || (lastMyTeam !== null && c.team === lastMyTeam);
  const hpRatio = c.max_hp > 0 ? c.current_hp / c.max_hp : 0;
  const badges = [];
  if (c.shield_hp) badges.push(makeStatusTag('shield', `보호막 ${c.shield_hp}`));
  if (c.self_defense_count) badges.push(makeStatusTag('selfdef', '직접 방어'));
  if (c.defense_count - (c.self_defense_count || 0) > 0) badges.push(makeStatusTag('guard', `수호${c.defense_count - (c.self_defense_count || 0) > 1 ? ' ' + (c.defense_count - (c.self_defense_count || 0)) : ''}`));
  if (c.polarize_active) badges.push(makeStatusTag('polarize', '편광중'));
  if (c.has_leech_buff) badges.push(makeStatusTag('leech', '흡수'));
  if (c.pending_attacks) badges.push(makeStatusTag('pending', `피해 보류 ${c.pending_attacks}`));
  if (c.pending_heals) badges.push(makeStatusTag('heal', `회복 +${c.pending_heals}`));
  if (c.interceptors && c.interceptors.length) badges.push(makeStatusTag('proxydef', `대리 방어 ${c.interceptors.join(', ')}`, c.interceptors.length));
  if (c.commanded_by) badges.push(makeStatusTag('command', `지휘 ${c.commanded_by}`, 1));
  return `<div data-fx="${c.name}" data-hp="${c.current_hp}" data-max="${c.max_hp}"${hpHiddenAttr(c)} class="compact-card ${isTarget ? 'selected-target' : ''} ${isDefeatedStatus(c) ? 'is-defeated' : ''} ${isTurnPending(c) ? 'turn-pending' : ''}" onclick="onCardClick('${c.name}')">${isTarget ? '<span class="tgt-line" aria-hidden="true"></span>' : ''}
    <div class="crow">
      <div class="cavatar-sm" style="background:${c.color || '#4a4a4e'};"${canSeeStats ? ` data-tip="${shopEsc(statsTitle(c))}"` : ''}>${cardShines(c) ? '<span class="turn-shine" aria-hidden="true"></span>' : ''}</div>
      <div class="cname-sm">${displayNameOf(c)}${statusTagFor(c)}</div>
      <div class="chp-sm">${hpNumText(c)}</div>
    </div>
    <div class="hpbar-track-sm"><div class="hpbar-fill-sm ${hpRatio <= 0.3 ? 'low' : (hpRatio <= 0.6 ? 'mid' : '')}" style="width:${Math.max(0, hpRatio * 100)}%;"></div></div>
    <div class="cbadges-sm">${badges.join('&nbsp;&nbsp;')}</div>
  </div>`;
}

let lastAllForCards = [];
let lastMyTeam = null;
let lastSeesAll = false;
let lastForcedTargetNames = new Set();
let lastAttackLines = [];  // 이번 라운드 보스·거점 공격선 [{from, to}]
let lastSiteDice = null;  // 공성전 : { round_no, value, used, stale }

function roleColorVar(role) {
  return `var(--role-${role}, #9aa0a6)`;
}

function displayNameOf(c) {
  if (!c) return '';
  // 마스 레이드에서는 본인이 마이페이지에서 설정한 짧은 표기 이름이 있으면 그걸 우선합니다
  // (부위가 나뉜 BOSS/NOVA는 표기 이름을 쓰지 않습니다).
  if (BATTLE_TYPE === 'mass_raid' && !c.boss_section && c.raid_display_name) return c.raid_display_name;
  if (!c.boss_section) return c.name;
  // "BOSS-NW"처럼 한 줄을 4부위로 자동 생성한 합성 이름이면 접두어만 뽑아서 "BOSS [NW]"로,
  // "NOVA 1구역"처럼 이미 고유하게 등록된 이름이면 원래 이름 뒤에 부위 코드만 덧붙입니다.
  const parts = c.name.split('-');
  const base = (parts.length === 2 && parts[1] === c.boss_section) ? parts[0] : c.name;
  return `${base} [${c.boss_section}]`;
}

// 카드 우상단의 "스탯 보기" 아이콘 - 마우스를 올리면 화면 위에 떠 있는 툴팁(floatTip)으로 스탯이 떠요(카드 목록 밖으로 잘리지 않게). 카드마다 이 SVG가
// 반복되므로, id가 겹치면 안 되는 clipPath(원래 안에 들어있던)는 빼고 넣었습니다(패스 자체가
// viewBox 안에 다 들어와서 클리핑 없이도 모양은 동일합니다).
const CARD_INFO_ICON_SVG = UI_INFO_SVG;

// 지금 이 캐릭터 팀의 차례이고, 살아 있고, 아직 이번 라운드 행동을 하지 않았으면 true
// 카드 샤인 : 지금 차례이고 아직 행동하지 않은 캐릭터 카드 모두에(누가 보든 똑같이)
function cardShines(c) { return isTurnPending(c); }
function isTurnPending(c) {
  const battle = lastBattleForPanel;
  if (!battle || battle.finished || isDefeatedStatus(c) || c.has_acted) return false;
  const turnTeamLabel = battle.current_turn_team === '1팀' ? 'A' : 'B';
  return c.teamLabel === turnTeamLabel;
}

// 캐릭터 상태 배지(지휘 · 방어 · 보호막 · 피해 보류 · 회복 예정 …) : PVP 카드와 격자 칸 툴팁이 같은 모양을 씁니다.
// 카드는 회피를 이름 옆 상태 표시로 따로 보여 주므로, 회피 배지는 툴팁(withDodge)에서만 붙입니다.
function charStatusBadges(c, withDodge) {
  const badges = [];
  if (withDodge && c.dodging_this_round) badges.push(makeStatusTag('dodge', '회피'));
  if (lastForcedTargetNames.has(c.name)) badges.push(makeStatusTag('command', '지휘'));
  if (c.self_defense_count) badges.push(makeStatusTag('selfdef', '직접 방어'));
  if (c.defense_count - (c.self_defense_count || 0) > 0) badges.push(makeStatusTag('guard', `수호${c.defense_count - (c.self_defense_count || 0) > 1 ? ' ' + (c.defense_count - (c.self_defense_count || 0)) : ''}`));
  if (c.shield_hp) badges.push(makeStatusTag('shield', `보호막 ${c.shield_hp}`));
  if (c.polarize_active) badges.push(makeStatusTag('polarize', '편광중'));
  if (c.has_leech_buff) badges.push(makeStatusTag('leech', '흡수'));
  if (c.pending_attacks) badges.push(makeStatusTag('pending', `피해 보류 ${c.pending_attacks}`));
  if (c.pending_heals) badges.push(makeStatusTag('heal', `회복 +${c.pending_heals}`));
  if (c.interceptors && c.interceptors.length) badges.push(makeStatusTag('proxydef', `대리 방어 ${c.interceptors.join(', ')}`, c.interceptors.length));
  if (c.commanded_by) badges.push(makeStatusTag('command', `지휘 ${c.commanded_by}`, 1));
  return badges;
}

function renderCardHtml(c) {
  const canSeeStats = lastSeesAll || (lastMyTeam !== null && c.team === lastMyTeam);
  const isAlly = lastMyTeam !== null && c.team === lastMyTeam;
  const isTarget = selectedTargetName === c.name;
  const isMine = myControlInfo(lastBattleForPanel).scope === 'character' && myControlInfo(lastBattleForPanel).character.name === c.name;
  const statusTag = statusTagFor(c);
  const hpRatio = c.max_hp > 0 ? c.current_hp / c.max_hp : 0;
  const badges = charStatusBadges(c);

  return `<div data-fx="${c.name}" data-hp="${c.current_hp}" data-max="${c.max_hp}"${hpHiddenAttr(c)} class="char-card v2 team-${c.teamLabel} ${isTarget ? 'selected-target' : ''} ${isAlly ? 'ally' : ''} ${isDefeatedStatus(c) ? 'is-defeated' : ''} ${isTurnPending(c) ? 'turn-pending' : ''}" onclick="onCardClick('${c.name}')">${isTarget ? '<span class="tgt-line" aria-hidden="true"></span>' : ''}
    <div class="row1">
      <div>
        <span class="cname">${displayNameOf(c)}</span>
        <span class="crole" style="color:${roleColorVar(c.role)}">${c.role}${(c.skill && BATTLE_TYPE === 'mass_raid') ? ' 【' + c.skill + '】' : ''}</span>
      </div>
      ${canSeeStats ? `<div class="card-info-icon" data-tip="${shopEsc(statsTitle(c))}">${CARD_INFO_ICON_SVG}</div>` : ''}
    </div>
    <div class="portrait-row">
      <div class="portrait" style="${c.avatar_url ? `background-image:url('${c.avatar_url}');` : ''}">${cardShines(c) ? '<span class="turn-shine" aria-hidden="true"></span>' : ''}</div>
      <div class="portrait-side">
        <div class="cbadges-row">
          <div class="cbadges">${badges.map(b => `<div>${b}</div>`).join('')}</div>
          <div class="cstatus-tag">${statusTag}</div>
        </div>
        <div class="hpbar-wrap">
          <div class="hpnum">${c.hp_hidden ? '<b>???</b>' : `<b>${c.current_hp}</b><span>/${c.max_hp}</span>`}</div>
          <div class="hpbar-track"><div class="hpbar-fill ${hpRatio <= 0.3 ? 'low' : (hpRatio <= 0.6 ? 'mid' : '')}" style="width:${Math.max(0, hpRatio * 100)}%;"></div></div>
        </div>
      </div>
    </div>
  </div>`;
}

// ------------------------------------------------------------------
// 카드 클릭 → 대상 지정 → 행동 팝업 (기존 격자 팝업과 동일한 필터링 로직을 카드에 적용)
// ------------------------------------------------------------------
let selectedTargetName = null;
let pendingMultiLabel = null;   // 환류처럼 여러 명을 순서대로 지정해야 하는 스킬
let pendingMultiTargets = [];

function myActorName(battle) {
  const control = myControlInfo(battle);
  if (control.scope === 'character') return control.character.name;
  if (control.scope === 'all') {
    if (!actionPanelActorName || !lastAllForCards.find(c => c.name === actionPanelActorName)) {
      actionPanelActorName = lastAllForCards[0] ? lastAllForCards[0].name : null;
    }
    return actionPanelActorName;
  }
  return null;
}

function onCardClick(name) {
  const battle = lastBattleForPanel;
  if (!battle) return;
  const control = myControlInfo(battle);
  if (control.scope === 'none') return;

  if (pendingMultiLabel) {
    // 환류 등 다중 지정 스킬 진행 중 - 클릭할 때마다 대상 목록에 추가합니다.
    const actor = myActorName(battle);
    const actorChar = lastAllForCards.find(c => c.name === actor);
    if (actorChar && name !== actor && actorChar.team === lastAllForCards.find(c => c.name === name).team) {
      if (!pendingMultiTargets.includes(name)) pendingMultiTargets.push(name);
    }
    renderMultiPopup();
    return;
  }

  selectedTargetName = (selectedTargetName === name) ? null : name;
  renderCards();
  syncCmdPanelFromCardClick();
}

function closeActionPopup() {
  selectedTargetName = null;
  pendingMultiLabel = null;
  pendingMultiTargets = [];
  document.getElementById('actionPopup').style.display = 'none';
  renderCards();
}

// 대상(카드)과 행동자의 관계(적/아군/본인)에 따라 그 대상에게 쓸 수 있는 행동만 추립니다.
function actionLabelsForTarget(actor, target) {
  const isSelf = actor.name === target.name;
  const isEnemy = actor.teamLabel !== target.teamLabel;
  // 메딕의 "방어"(본인방어를 대신하는 표시명)는 자기 자신에게만 쓸 수 있어서, 가디언의 아군 대상
  // "방어"(능동 방어 부여)와 달리 아군(비본인) 대상 목록에서는 빼야 합니다.
  // '방어'는 본인 지정 = 직접 방어, 아군 지정 = 대리 방어. '수호'는 본인을 뺀 아군에게만 쓸 수 있습니다.
  const allyTargetLabels = ALLY_TARGET_ACTIONS;
  const allowedLabels = isEnemy ? ENEMY_TARGET_ACTIONS
    : isSelf ? new Set([...allyTargetLabels, ...SELF_ONLY_ACTIONS].filter(l => l !== '수호'))
    : allyTargetLabels;
  return actor.available_actions.filter(l => l !== '이동' && l !== '시간초과' && allowedLabels.has(l) && !MULTI_TARGET_ACTIONS[l]);
}

// 선택된 행동에 따라 고를 수 있는 대상 목록(적 전체/아군 전체/본인만)을 돌려줍니다.
function targetsForAction(actor, label) {
  if (ENEMY_TARGET_ACTIONS.has(label)) return lastAllForCards.filter(c => c.teamLabel !== actor.teamLabel);
  if (SELF_ONLY_ACTIONS.has(label)) return [actor];
  if (label === '수호') return lastAllForCards.filter(c => c.teamLabel === actor.teamLabel && c.name !== actor.name);
  if (ALLY_TARGET_ACTIONS.has(label)) return lastAllForCards.filter(c => c.teamLabel === actor.teamLabel);
  return [actor];
}

// 커맨드 전송 바([행동] [대상] [전송]) - 라운드 진행 등으로 전투 상태가 바뀔 때마다 호출해서
// 드롭다운 목록을 최신으로 맞춥니다.
// 서버(_check_actor_turn)와 같은 기준 : 전투 중 · 살아 있음 · 아직 행동 안 함 · 우리 팀 차례
// (1라운드에 후공을 선언한 메딕은 후공 페이즈에도 가능)
function cmdCanActNow(actor) {
  const b = lastBattleForPanel;
  if (!explicitlyJoined || !actor || !b || b.finished || !b.current_turn_team) return false;
  if (isDefeatedStatus(actor) || actor.status === 'fleeing' || actor.has_acted) return false;
  if (actor.teamLabel === (b.current_turn_team === '1팀' ? 'A' : 'B')) return true;
  return !!actor.deferred_this_round && b.current_turn_team !== b.round_first_team;
}
function setCmdLocked(locked) {
  const bar = document.getElementById('commandSendBar');
  if (!bar) return;
  bar.classList.toggle('cmd-off', locked);
  if (locked) bar.classList.remove('armed');
  bar.querySelectorAll('select, button').forEach(el => { el.disabled = locked; });
}
function refreshCmdPanel() {
  const actionSel = document.getElementById('cmdActionSelect');
  const targetSel = document.getElementById('cmdTargetSelect');
  if (!actionSel || !targetSel) return;
  const actorName = myActorName(lastBattleForPanel);
  const actor = lastAllForCards.find(c => c.name === actorName);
  if (!cmdCanActNow(actor)) {
    ['cmdActionSelect', 'cmdTargetSelect', 'cmdTarget2', 'cmdTarget3'].forEach(id => { document.getElementById(id).innerHTML = ''; });
    document.getElementById('cmdTarget2').style.display = document.getElementById('cmdTarget3').style.display = 'none';
    setCmdLocked(true);
    return;
  }
  setCmdLocked(false);
  const labels = actor.available_actions.filter(l => l !== '이동' && l !== '시간초과');
  const prevLabel = actionSel.value;
  actionSel.innerHTML = labels.map(l => `<option value="${l}">${l}</option>`).join('');
  if (labels.includes(prevLabel)) actionSel.value = prevLabel;
  refreshCmdTargetOptions();
}

function refreshCmdTargetOptions() {
  const targetSel = document.getElementById('cmdTargetSelect');
  if (!targetSel) return;
  const actorName = myActorName(lastBattleForPanel);
  const actor = lastAllForCards.find(c => c.name === actorName);
  const label = document.getElementById('cmdActionSelect').value;
  const t2 = document.getElementById('cmdTarget2'), t3 = document.getElementById('cmdTarget3');
  const multi = actor && label ? MULTI_TARGET_ACTIONS[label] : 0;
  t2.style.display = t3.style.display = multi === 3 ? '' : 'none';
  if (!actor || !label) { targetSel.innerHTML = '<option value="">-</option>'; return; }
  if (multi === 3) {
    // 환류 : 아군 3명을 각각 고릅니다.
    const allies = lastAllForCards.filter(c => c.teamLabel === actor.teamLabel && !isDefeatedStatus(c));
    const opts = '<option value="">대상 선택</option>' + allies.map(c => `<option value="${c.name}">${c.name === actor.name ? '본인' : displayNameOf(c)}</option>`).join('');
    [targetSel, t2, t3].forEach(sel => {
      const prev = sel.value;
      sel.innerHTML = opts;
      if (allies.some(c => c.name === prev)) sel.value = prev;
    });
    return;
  }
  const pool = targetsForAction(actor, label);
  const prevTarget = targetSel.value;
  targetSel.innerHTML = pool.map(c => `<option value="${c.name}">${c.name === actor.name ? '본인' : displayNameOf(c)}</option>`).join('')
    || '<option value="">-</option>';
  if (pool.some(c => c.name === prevTarget)) targetSel.value = prevTarget;
  else if (pool.some(c => c.name === selectedTargetName)) targetSel.value = selectedTargetName;
}

// 대상 드롭다운을 직접 바꾸면 카드 쪽 선택 표시(테두리)도 맞춰줍니다.
function onCmdTargetChange() {
  selectedTargetName = document.getElementById('cmdTargetSelect').value || null;
  renderCards();
}

// 카드를 클릭하면, 그 대상에게 실제로 쓸 수 있는 행동 중 하나를 자동으로 골라
// [행동]/[대상] 드롭다운을 함께 맞춰줍니다("알아서 인식").
function syncCmdPanelFromCardClick() {
  const actorName = myActorName(lastBattleForPanel);
  const actor = lastAllForCards.find(c => c.name === actorName);
  const actionSel = document.getElementById('cmdActionSelect');
  const targetSel = document.getElementById('cmdTargetSelect');
  if (!actor || !actionSel || !targetSel) return;
  if (!cmdCanActNow(actor)) { refreshCmdPanel(); return; }
  const target = lastAllForCards.find(c => c.name === selectedTargetName);
  if (!target) { refreshCmdPanel(); return; }

  const validLabels = actionLabelsForTarget(actor, target);
  const allLabels = actor.available_actions.filter(l => l !== '이동' && l !== '시간초과');
  const currentLabel = actionSel.value;
  const nextLabel = validLabels.includes(currentLabel) ? currentLabel : (validLabels[0] || allLabels[0] || '');
  actionSel.innerHTML = allLabels.map(l => `<option value="${l}">${l}</option>`).join('');
  actionSel.value = nextLabel;
  refreshCmdTargetOptions();
  if ([...targetSel.options].some(o => o.value === target.name)) targetSel.value = target.name;
}

function startMultiAction(label) {
  pendingMultiLabel = label;
  pendingMultiTargets = [];
  selectedTargetName = null;
  document.getElementById('actionPopup').style.display = 'none';
  renderMultiPopup();
}

function renderMultiPopup() {
  const popup = document.getElementById('actionPopup');
  if (!pendingMultiLabel) { popup.style.display = 'none'; return; }
  const need = MULTI_TARGET_ACTIONS[pendingMultiLabel];
  const actorName = myActorName(lastBattleForPanel);
  popup.innerHTML = `
    <div class="ap-head"><b>${pendingMultiLabel}</b> - 아군 ${need}명을 카드에서 순서대로 클릭하세요 (${pendingMultiTargets.length}/${need})</div>
    <div style="font-size:14px; color:var(--text); margin-bottom:8px;">${pendingMultiTargets.join(', ') || '(아직 없음)'}</div>
    <div class="ap-grid">
      <button class="ap-btn" ${pendingMultiTargets.length === need ? '' : 'disabled style="opacity:.4;"'}
        onclick="commitMultiAction('${pendingMultiLabel}','${actorName}')">실행</button>
      <button class="ap-btn" onclick="closeActionPopup()">취소</button>
    </div>
  `;
  popup.style.display = 'block';
}

function commitMultiAction(label, actorName) {
  const type = ACTION_LABELS[label];
  doActionThenAnnounce(type, { name: actorName, targets: pendingMultiTargets.slice() },
    actorName, label, pendingMultiTargets.join(', '));
  closeActionPopup();
}

function commitAction(label, actorName, targetName) {
  const actorForType = lastAllForCards.find(c => c.name === actorName);
  const type = resolveActionType(label, actorForType ? actorForType.role : null);
  const payloadBuilders = {
    attack: () => ({ attacker: actorName, target: targetName }),
    self_defend: () => ({ name: actorName }),
    defend: () => ({ tanker: actorName, target: targetName || actorName }),
    guard: () => ({ tanker: actorName, target: targetName }),
    dodge: () => ({ name: actorName }),
    heal: () => ({ healer: actorName, target: targetName }),
    timeout: () => ({ name: actorName }),
    flee: () => ({ name: actorName }),
    defense_settle: () => ({ name: actorName }),
    command: () => ({ guardian: actorName, target: targetName || actorName }),
    swap: () => ({ medic: actorName, target: targetName }),
    collapse: () => ({ attacker: actorName, target: targetName }),
    emission: () => ({ attacker: actorName }),
    shield: () => ({ name: actorName, target: targetName || actorName }),
    polarize: () => ({ name: actorName }),
    restore: () => ({ name: actorName, target: targetName || null }),
  };
  const payload = payloadBuilders[type] ? payloadBuilders[type]() : { name: actorName, target: targetName };
  doActionThenAnnounce(type, payload, actorName, label, targetName === actorName ? '본인' : targetName);
  selectedTargetName = null;
  renderCards();
  refreshCmdPanel();
}

// 행동을 실행하고, 서버가 짧은 시간 안에 action_error를 보내지 않으면(=성공한 것으로 보고)
// "[행동: 이름] [대상: 이름]" 형식으로 커맨드 창(채팅)에 남깁니다. 실패한 행동은 채팅에 남지 않습니다.
// as_character로 실제 행동한 캐릭터 이름을 함께 보내서, GM이 다른 캐릭터를 대신 조작한 경우에도
// 로그에는 GM이 아니라 그 캐릭터의 이름/색상으로 표시되게 합니다(서버가 권한을 재검증합니다).
function doActionThenAnnounce(type, payload, actorName, label, targetLabel) {
  let failed = false;
  const onErr = () => { failed = true; };
  socket.once('action_error', onErr);
  doAction(type, payload);
  setTimeout(() => {
    socket.off('action_error', onErr);
    if (!failed) socket.emit('chat_message', { text: `[행동: ${label}] [대상: ${targetLabel}]`, as_character: actorName });
  }, 400);
}

// 커맨드 전송 바의 [전송] 버튼 - 환류 등 다중 지정 스킬이 진행 중이면 그걸 커밋하고,
// 아니면 [행동]/[대상] 드롭다운에 지금 골라져 있는 값 그대로 실행합니다.
function submitCmd() {
  if (!cmdCanActNow(lastAllForCards.find(c => c.name === myActorName(lastBattleForPanel)))) return;
  if (pendingMultiLabel) {
    if (pendingMultiTargets.length === MULTI_TARGET_ACTIONS[pendingMultiLabel]) {
      commitMultiAction(pendingMultiLabel, myActorName(lastBattleForPanel));
    }
    return;
  }
  const actorName = myActorName(lastBattleForPanel);
  const label = document.getElementById('cmdActionSelect').value;
  const targetName = document.getElementById('cmdTargetSelect').value;
  if (!actorName || !label) {
    showError('행동을 선택해주세요.');
    return;
  }
  const need = MULTI_TARGET_ACTIONS[label];
  if (need) {
    const targets = ['cmdTargetSelect', 'cmdTarget2', 'cmdTarget3'].slice(0, need)
      .map(id => document.getElementById(id).value).filter(Boolean);
    if (targets.length !== need || new Set(targets).size !== need) {
      showError(`${label}은(는) 서로 다른 아군 ${need}명을 골라야 합니다.`);
      return;
    }
    doActionThenAnnounce(ACTION_LABELS[label], { name: actorName, targets }, actorName, label, targets.join(', '));
    return;
  }
  commitAction(label, actorName, targetName || actorName);
}

let selectedGridChar = null;  // 지도에서 선택된 "행동하는" 캐릭터 (범위 미리보기 대상)
let selectedGridTargetName = null;  // 범위 내에서 클릭해 지정한 대상 (본인 포함)
const GRID_CELL_PX = 36;
// GM이 '전조 출력'으로 공개한 격자 칸. 곧 그 칸에 무조건 피해가 발생한다는 시각적 경고입니다.
let telegraphRevealedCells = new Set();
var lastPublicObstacleHits = 3;   // 이 방의 장애물 타격 횟수(운영진 전투 설정)

// 격자 칸 툴팁 : 이름 · 포지션 · 팀 / 체력 · 위치 / 이번 라운드 상태 / 걸린 효과 / 전조 · 범위
function gridCellTip(c, x, y, key, telKeys, rangeCells, rangeIsAction) {
  // 칸 툴팁(HTML) : 이름 · 역할(러너/몹 구분은 넣지 않음) · 칸 / HP / 효과 / 전조 · 범위 알림. 행동 완료 여부는 지도 샤인으로만 구분합니다.
  const e = shopEsc;
  const pos = cellLabel(x, y);
  let h = '';
  if (c) {
    h += `<div class="tt-head"><b>${e(displayNameOf(c))}</b>${c.role ? `<span>${e(c.role)}</span>` : ''}<span class="tt-pos">${pos}</span></div>`;
    const ratio = c.max_hp > 0 ? Math.max(0, Math.min(1, c.current_hp / c.max_hp)) : 0;
    const cls = ratio <= 0.3 ? 'low' : (ratio <= 0.6 ? 'mid' : '');
    h += `<div class="tt-hp"><div class="bar"><i class="${cls}" style="width:${ratio * 100}%"></i></div>`
      + `<div class="num"><span>${c.hp_hidden ? 'HP <b>???</b>' : `HP <b>${c.current_hp}</b> / ${c.max_hp}`}</span></div></div>`;
    if (isDefeatedStatus(c) || c.status === 'downed') {
      const st = c.status === 'downed' ? '기절' : statusTagFor(c).replace(/^\s*\*/, '');
      h += `<div class="tt-note bad"><i class="fa-solid fa-skull"></i>${e(st)}</div>`;
    }
    const badges = charStatusBadges(c, true);
    if (badges.length) h += `<div class="tt-sec"><div class="k">효과</div><div class="tt-tags">${badges.join('')}</div></div>`;
  }
  if (telKeys.has(key)) {
    h += `<div class="tt-note warn"><i class="fa-solid fa-triangle-exclamation"></i>${telegraphRevealedCells.has(key) ? '전조 구역 · 곧 재해가 발생합니다' : '전조로 고른 칸'}</div>`;
  }
  return h;
}

function cellLabel(x, y) {
  let col = '';
  let n = x;
  do {
    col = String.fromCharCode(65 + (n % 26)) + col;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return `${col}${y + 1}`;
}

function crossPlusNeighbors(px, py, crossLen, includeDiagonal) {
  const cells = new Set();
  for (let d = 1; d <= crossLen; d++) {
    cells.add(`${px + d},${py}`); cells.add(`${px - d},${py}`);
    cells.add(`${px},${py + d}`); cells.add(`${px},${py - d}`);
  }
  if (includeDiagonal) {
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        if (dx === 0 && dy === 0) continue;
        cells.add(`${px + dx},${py + dy}`);
      }
    }
  }
  cells.delete(`${px},${py}`);
  return cells;
}

function computeHighlightCells(character, showActionRange) {
  const [px, py] = character.grid_pos;
  // 보스 · 거점(2팀)은 사거리 제한 없이 지도 위 모든 캐릭터를 대상으로 고를 수 있습니다.
  if (showActionRange && character.teamLabel === 'B') {
    return new Set((lastAllForCards || []).filter(c => c.grid_pos && c.status !== 'dead' && c.status !== 'fled')
      .map(c => `${c.grid_pos[0]},${c.grid_pos[1]}`));
  }
  if (showActionRange) {
    return crossPlusNeighbors(px, py, 3, true);
  }
  const agi = (character.stats && character.stats['민첩']) || 0;
  const cells = crossPlusNeighbors(px, py, character.move_range || 0, agi > 0);
  // 장애물 : 그 칸과, 십자 줄에서 장애물 너머 칸으로는 이동할 수 없어요(서버 Battle.obstacle_blocks_move와 같은 규칙)
  const obs = gridObstacleKeys();
  if (obs.size) {
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
      let blocked = false;
      for (let d = 1; d <= (character.move_range || 0); d++) {
        const k = `${px + dx * d},${py + dy * d}`;
        if (blocked) { if (!(Math.abs(dx * d) <= 1 && Math.abs(dy * d) <= 1 && agi > 0)) cells.delete(k); continue; }
        if (obs.has(k)) { blocked = true; cells.delete(k); }
      }
    });
    obs.forEach(k => cells.delete(k));
  }
  return cells;
}
// 지금 지도의 장애물 칸("x,y") : 운영진이 전조를 고르는 중이면 고르는 중인 장애물
function gridObstacleKeys() {
  if (typeof telegraphMode !== 'undefined' && telegraphMode && myControlInfo(lastBattleForPanel).scope === 'all') return new Set(telegraphObstacleCells);
  return new Set(((lastBattleForPanel && lastBattleForPanel.obstacles) || []).map(o => `${o.x},${o.y}`));
}
function gridObstacleAt(x, y) { return ((lastBattleForPanel && lastBattleForPanel.obstacles) || []).find(o => o.x === x && o.y === y) || null; }
// 장애물 공격 : 행동 사거리 안의 장애물을 누르면 확인 후 공격(크리티컬이면 한 번에 부서져요)
function onGridObstacleClick(actorName, x, y) {
  const o = gridObstacleAt(x, y); if (!o) return;
  uiConfirm(`${actorName}(이)가 장애물 ${cellLabel(x, y)}을(를) 공격할까요?\n남은 타격 ${o.hits}/${o.max} · 크리티컬이면 한 번에 부서져요.`, { title: '장애물 공격', okText: '공격' })
    .then(ok => { if (ok) { selectedGridChar = null; selectedGridTargetName = null; disarmGridCommand(); doAction('attack_obstacle', { attacker: actorName, x, y }); } });
}

// 서버 Battle.enemy_zone_cells와 같은 계산 : 차지한 칸(BOSS는 살아 있는 부위 전부)마다 십자 3칸 + 주변 8칸
function enemyZoneCells(unit) {
  if (!unit || unit.teamLabel !== 'B' || !unit.grid_pos) return new Set();
  const alive = c => c.grid_pos && c.status !== 'dead' && c.status !== 'fled';
  const parts = unit.boss_group ? (lastAllForCards || []).filter(c => c.teamLabel === 'B' && c.boss_group === unit.boss_group && alive(c)) : [unit];
  const own = new Set(parts.map(c => `${c.grid_pos[0]},${c.grid_pos[1]}`));
  const cells = new Set();
  parts.forEach(c => crossPlusNeighbors(c.grid_pos[0], c.grid_pos[1], 3, true).forEach(k => cells.add(k)));
  own.forEach(k => cells.delete(k));
  return cells;
}

function onGridActorClick(name) {
  selectedGridChar = name;
  selectedGridTargetName = null;
  disarmGridCommand();
  renderGrid(lastBattleForPanel, lastAllForCards);
}

// 격자에서 대상을 누르면 : 내 칸의 포인트 테두리가 대상으로 옮겨 가 반짝이고,
// 아래 커맨드 블록(러너 = 행동/대상/보내기, 운영진 = 캐릭터/행동/대상/실행)이 그 대상으로 맞춰져 켜집니다.
let gridArmGm = false;
function onGridTargetClick(actorName, targetName) {
  selectedGridChar = actorName;
  selectedGridTargetName = targetName;
  renderGrid(lastBattleForPanel, lastAllForCards);
  armCommandFromGrid(actorName, targetName);
}
function flashArm(el) { if (!el) return; el.classList.remove('armed'); void el.offsetWidth; el.classList.add('armed'); }
function armCommandFromGrid(actorName, targetName) {
  const control = myControlInfo(lastBattleForPanel);
  const actor = lastAllForCards.find(c => c.name === actorName), target = lastAllForCards.find(c => c.name === targetName);
  if (!actor || !target) return;
  const labels = actionLabelsForTarget(actor, target);
  if (control.scope === 'all') {
    gridArmGm = true;
    refreshGmActPanelVisibility();
    const a = document.getElementById('gmActActor'); if (!a) return;
    a.value = actorName; refreshGmActTypeOptions();
    const t = document.getElementById('gmActType');
    if (!labels.includes(t.value) && labels.length && [...t.options].some(o => o.value === labels[0])) t.value = labels[0];
    refreshGmActTargetOptions();
    const tg = document.getElementById('gmActTarget');
    if ([...tg.options].some(o => o.value === targetName)) tg.value = targetName;
    flashArm(document.getElementById('gmActPanel'));
  } else if (control.scope === 'character' && control.character.name === actorName) {
    if (!cmdCanActNow(actor)) return;
    selectedTargetName = targetName;
    syncCmdPanelFromCardClick();
    flashArm(document.getElementById('commandSendBar'));
  }
}
function disarmGridCommand() {
  ['commandSendBar', 'gmActPanel'].forEach(id => { const el = document.getElementById(id); if (el) el.classList.remove('armed'); });
  if (gridArmGm) { gridArmGm = false; refreshGmActPanelVisibility(); }
}

function onGridMoveClick(x, y) {
  if (!selectedGridChar) return;
  const name = selectedGridChar;
  selectedGridChar = null;
  selectedGridTargetName = null;
  disarmGridCommand();
  doAction('move', { name, x, y });
}

function renderGrid(battle, all) {
  const section = document.getElementById('gridSection');
  const el = document.getElementById('gridMap');
  if (!section || !el) return;  // PVP처럼 격자 지도가 없는 전투 유형은 이 섹션 자체가 DOM에 없음
  const gridWidth = battle ? battle.grid_width : (GRID_SIZE > 0 ? GRID_SIZE : null);
  const gridHeight = battle ? battle.grid_height : (GRID_SIZE > 0 ? GRID_SIZE : null);
  if (!gridWidth) { section.style.display = 'none'; return; }
  section.style.display = '';
  const posMap = {};
  // 사망/도주(완료)한 캐릭터는 격자에 그리지 않습니다(칸을 그대로 차지한 것처럼 보이면 혼동됨).
  all.forEach(c => { if (c.grid_pos && c.status !== 'dead' && c.status !== 'fled') posMap[`${c.grid_pos[0]},${c.grid_pos[1]}`] = c; });

  let highlightCells = new Set();
  let highlightIsAction = false;
  let selChar = null;
  let enemyZone = new Set();
  // 운영진(GM)은 양 팀을 모두 움직이므로 '적 턴'이 없습니다. 러너는 2팀 차례가 적 턴입니다.
  const gmView = myControlInfo(battle).scope === 'all';
  const isEnemyTurn = !gmView && !!(battle && battle.current_turn_team && battle.current_turn_team !== '1팀');
  // 메딕은 라운드가 후공 페이즈에 들어서면(엔진의 allow_free_turn 규칙과 동일) 상대 턴이라도
  // 힐/환류/복원으로 행동할 수 있으므로, 이 경우에는 적 턴 잠금을 풀어줍니다.
  const isSecondPhase = !!(battle && battle.current_turn_team && battle.current_turn_team !== battle.round_first_team);
  let medicFreeTurn = false;
  if (selectedGridChar) {
    selChar = all.find(c => c.name === selectedGridChar);
    if (selChar && selChar.grid_pos) {
      medicFreeTurn = selChar.role === '메딕' && isSecondPhase;
      // 고른 캐릭터 팀의 차례일 때만 범위를 보여줍니다(GM이 2팀 보스 · 거점을 고르면 2팀 차례에 범위가 뜸).
      const selTurn = !!(battle && battle.current_turn_team === (selChar.teamLabel === 'A' ? '1팀' : '2팀'));
      // 러너가 적을 누르면 적의 이동 범위 대신 공격 범위(받는 피해 1.2배 구역)만 보여줍니다.
      if (selChar.teamLabel === 'B') enemyZone = enemyZoneCells(selChar);
      if ((selTurn || (gmView && medicFreeTurn)) && (gmView || selChar.teamLabel === 'A')) {
        highlightIsAction = selChar.teamLabel === 'B' ? !selChar.has_acted : !!selChar.moved_this_round;
        highlightCells = computeHighlightCells(selChar, highlightIsAction);
      }
    } else {
      selectedGridChar = null;
    }
  }

  // 고른 대상(2x2 보스면 부위 4칸 모두) : 그 칸들이 포인트 테두리로 반짝입니다.
  const gridTargetChar = selChar && selectedGridTargetName ? all.find(c => c.name === selectedGridTargetName) : null;
  const isGridTarget = (c) => !!(gridTargetChar && c && (c.name === gridTargetChar.name || (gridTargetChar.boss_group && c.boss_group === gridTargetChar.boss_group)));
  // 칸 크기는 가운데 영역 폭에 맞춰 최대한 크게(정사각형) 잡습니다.
  const frame = section.querySelector('.map-frame') || section;
  const fcs = getComputedStyle(frame);
  const avail = frame.clientWidth - parseFloat(fcs.paddingLeft) - parseFloat(fcs.paddingRight);
  // 세로로도 스크롤 없이 한 화면에 다 들어오도록, 가운데 스크롤 영역의 남은 높이도 함께 봅니다.
  const scroller = section.closest('.teams-col-scroll');
  let availH = Infinity;
  if (scroller) {
    const top = frame.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    const legendH = (document.getElementById('gridLegend') || {}).offsetHeight || 0;
    availH = scroller.clientHeight - top - parseFloat(fcs.paddingTop) - parseFloat(fcs.paddingBottom) - legendH - 36;
  }
  const byW = Math.floor((avail - gridWidth) / gridWidth);
  const byH = Math.floor((availH - gridHeight) / gridHeight);
  const fitCellPx = Math.max(window.innerWidth <= 900 ? 18 : 28, Math.min(120, byW, byH > 0 ? byH : byW));
  // 휴대폰 : 확대 배율(맞춤 = 1). 확대하면 칸이 커지고 지도 틀 안에서 스크롤 · 드래그로 이동합니다.
  const zoom = gridZoomOn() ? gridZoom : 1;
  const cellPx = Math.min(96, Math.round(fitCellPx * zoom));
  frame.classList.toggle('zoomed', zoom > 1.001);
  const zl = document.getElementById('gridZoomLabel'); if (zl) zl.textContent = Math.round(zoom * 100) + '%';
  const fontPx = Math.max(11, Math.round(cellPx * 0.3));

  // 전조 구역 : 운영진이 고르는 중이면 고른 칸, 아니면 공개된 칸
  const telSelecting = typeof telegraphMode !== 'undefined' && telegraphMode && myControlInfo(battle).scope === 'all';
  const telKeys = telSelecting ? telegraphSelectedCells : telegraphRevealedCells;
  const obsKeys = gridObstacleKeys();
  const TEL_EDGE = 'rgba(255,176,32,.38)';
  // 옅은 사선 줄무늬(한 줄 간격 7.07px = 가로 10px)가 천천히 흘러가도록 CSS(td.tel)에서 움직입니다.
  const TEL_STRIPES = 'repeating-linear-gradient(135deg, rgba(255,176,32,.08) 0 2.5px, rgba(255,176,32,0) 2.5px 7.0711px)';
  // 움직임 이어 붙이기 : 지도를 다시 그려도 샤인 · 전조 줄무늬가 처음으로 튀지 않게, 지금 시각 기준으로 시작점을 맞춥니다.
  const nowMs = performance.now();
  const phase = ms => `-${((nowMs % ms) / 1000).toFixed(3)}s`;
  // 칸 간격(칸 + 격자선 1px). 줄무늬는 가로 10px마다 반복하므로, 칸 위치만큼 밀면 옆 칸과 이어집니다.
  const pitch = cellPx + 1;
  let html = `<table class="gmap" style="--tel-phase:${phase(2400)}; --shine-phase:${phase(3200)}; --tgt-phase:${phase(1800)}; --obs-phase:${phase(14000)}; --obs-phase-b:${phase(22000)};">`;
  for (let y = 0; y < gridHeight; y++) {
    html += '<tr>';
    for (let x = 0; x < gridWidth; x++) {
      const key = `${x},${y}`;
      const c = posMap[key];
      let selBorder = '';
      let cursor = 'default';
      let onclick = '';
      let cellCls = '';
      let cellStyle = '';
      let cornerMarks = '';
      if (c) {
        const canTargetNow = !!(selectedGridChar && highlightIsAction);
        const isSelectedActor = selectedGridChar && c.name === selectedGridChar;
        const actorIgnoresRange = selChar && selChar.available_actions.some(l => RANGE_IGNORING_ACTIONS.has(l));
        const inRangeOrExempt = highlightCells.has(key) || (actorIgnoresRange && c.teamLabel === selChar.teamLabel);
        const isTargetable = canTargetNow && !isSelectedActor && inRangeOrExempt;
        const isSelfTargetable = canTargetNow && isSelectedActor;
        // 내 팀 차례인데 아직 행동 전 = 빛이 훑고 지나가는 샤인, 행동을 마치면 샤인이 꺼집니다.
        // 이동만 마치고 행동 전이면 모서리에 작은 삼각형을 함께 둡니다.
        cursor = 'pointer';
        onclick = (isSelfTargetable || isTargetable)
          ? `onclick="onGridTargetClick('${selectedGridChar}','${c.name}')"`
          : `onclick="onGridActorClick('${c.name}')"`;
        const bossImg = c.boss_section ? (bossImageFor(c) || c.avatar_url) : null;
        if (bossImg) {
          // BOSS(2x2)는 4칸에 걸쳐 한 장의 이미지가 이어지도록, 칸마다 이미지의 해당 1/4만 보여줍니다.
          const pos = { NW: '0% 0%', NE: '100% 0%', SW: '0% 100%', SE: '100% 100%' }[c.boss_section] || 'center';
          cellCls = 'boss';
          cellStyle = `background-image:url('${bossImg}'); background-size:200% 200%; background-position:${pos};`;
        } else {
          cellCls = c.teamLabel === 'A' ? 'ally' : 'enemy';
        }
        const turnLbl = battle && !battle.finished && battle.current_turn_team ? (battle.current_turn_team === '1팀' ? 'A' : 'B') : null;
        if (turnLbl && c.teamLabel === turnLbl && !c.has_acted && !isDefeatedStatus(c) && c.status !== 'downed') cellCls += ' ready';
        // 모서리 표시 : 받을 피해(왼쪽 빨강) / 보호 · 회복 효과(오른쪽 흰색)
        const hurt = !!c.pending_attacks;
        const buff = !!(c.shield_hp || c.defense_count || c.polarize_active || c.has_leech_buff || c.pending_heals || (c.interceptors && c.interceptors.length));
        cornerMarks = (hurt ? '<i class="gmk hurt"></i>' : '') + (buff ? '<i class="gmk buff"></i>' : '');
      } else if (obsKeys.has(key)) {
        // 장애물 : 행동 사거리 안이면 눌러서 공격
        cellCls = 'obst';
        // 장애물마다 무늬의 다른 부분이 보이게(이웃 칸이 똑같아 보이지 않게)
        cellStyle = `--ox:${-((x * 37) % 120)}px; --oy:${-((y * 53) % 120)}px;`;
        const o = gridObstacleAt(x, y);
        if (o && selChar && highlightIsAction && highlightCells.has(key) && selChar.teamLabel === 'A' && !selChar.has_acted) {
          cursor = 'pointer';
          onclick = `onclick="onGridObstacleClick('${selChar.name}',${x},${y})"`;
        }
      } else if (highlightCells.has(key) && !highlightIsAction) {
        cursor = 'pointer';
        onclick = `onclick="onGridMoveClick(${x},${y})"`;
      }
      // 이동/사거리 범위 : 격자 선 자체의 색을 바꿔 범위의 바깥 테두리를 그립니다(두께는 격자 선 그대로).
      // 표의 선은 옆 칸과 같이 쓰므로, 경계인 선은 양쪽 칸 모두에 색을 줍니다. 범위 안 칸은 옅게 물듭니다.
      let tdStyle = '';
      {
        // 사거리는 흰색, 메딕만 이동 범위처럼 노란색(회복 사거리). 이동 범위는 직군 색.
        const isMedicSel = selChar && selChar.role === '메딕';
        // 적을 골랐으면(운영진이 BOSS를 옮기는 중이 아니면) 적의 공격 범위를 적 색으로 그립니다.
        const showZone = enemyZone.size && (!highlightCells.size || highlightIsAction);
        const visCells = showZone ? enemyZone : highlightCells;
        // 이동 범위는 흰색, 행동(사거리)은 직군 색
        const rngCol = showZone ? ENEMY_ZONE_COLOR : highlightCells.size ? (highlightIsAction ? (ROLE_MOVE_COLOR[selChar && selChar.role] || ACTION_RANGE_COLOR) : ACTION_RANGE_COLOR) : null;
        // 대상을 골랐으면 내 칸의 포인트 테두리는 대상으로 옮겨 갑니다(대상 칸이 반짝임).
        const selfKey = selChar && selChar.grid_pos && !gridTargetChar ? `${selChar.grid_pos[0]},${selChar.grid_pos[1]}` : null;
        const edge = (dx, dy) => {
          const nx = x + dx, ny = y + dy;
          const nk = `${nx},${ny}`;
          // 지도 밖 칸은 언제나 '범위 밖'으로 봅니다(범위 계산이 지도 밖 좌표를 담아도 가장자리 선이 끊기지 않게).
          const outside = nx < 0 || ny < 0 || nx >= gridWidth || ny >= gridHeight;
          const inHl = k => !outside && visCells.has(k);
          const inTel = k => !outside && telKeys.has(k);
          if (selfKey && (key === selfKey || nk === selfKey)) return 'var(--point)';
          if (rngCol && visCells.has(key) !== inHl(nk)) return rngCol;
          // 전조 구역(운영진이 고르는 중이거나 공개된 칸)도 같은 방식 : 구역 바깥 격자 선만 붉게
          if (telKeys.has(key) !== inTel(nk)) return TEL_EDGE;
          return null;
        };
        [['top', 0, -1], ['right', 1, 0], ['bottom', 0, 1], ['left', -1, 0]].forEach(([side, dx, dy]) => {
          const col = edge(dx, dy); if (col) tdStyle += `border-${side}-color:${col};`;
        });
        // 바탕 : 내 칸/범위는 옅은 색, 전조는 호박색 사선 줄무늬(겹쳐도 둘 다 보이게 색 + 무늬를 따로 깝니다)
        if (key === selfKey) tdStyle += 'background-color:color-mix(in srgb, var(--point) 18%, transparent);';
        else if (rngCol && visCells.has(key)) tdStyle += `background-color:color-mix(in srgb, ${rngCol} ${showZone ? 10 : 14}%, transparent);`;
        if (telKeys.has(key)) tdStyle += `background-image:${TEL_STRIPES}; --tx:${-(((x + y) * pitch) % 10)}px;`;
      }
      // 운영진 전조 선택 중 : 모든 칸을 눌러 고르고(Shift+클릭 가로 한 줄, Shift+우클릭 세로 한 줄), 고른 칸은 붉게 표시
      if (typeof telegraphMode !== 'undefined' && telegraphMode && myControlInfo(battle).scope === 'all') {
        cursor = 'crosshair';
        onclick = `onclick="onTelegraphCellClick(${x},${y},event)" oncontextmenu="return onTelegraphCellRightClick(${x},${y},event)"`;

      }
      const glow = '';
      // 빈 칸은 칸 번호만 짧게, 캐릭터 칸은 정리된 툴팁(HTML)
      const obsO = !c && obsKeys.has(key) ? (gridObstacleAt(x, y) || { hits: (lastPublicObstacleHits || 3), max: (lastPublicObstacleHits || 3), draft: true }) : null;
      const tipAttr = c ? `data-tip-html="${shopEsc(gridCellTip(c, x, y, key, telKeys, highlightCells, highlightIsAction))}"`
        : obsO ? `data-tip="${cellLabel(x, y)} · 장애물 · 남은 타격 ${obsO.hits}/${obsO.max}${obsO.draft ? ' (공개하면 놓여요)' : ''}"` : `data-tip="${cellLabel(x, y)}"`;
      let inner = '';
      if (c) {
        // BOSS 부위는 칸이 4개라 이름 앞 두 글자만(예: NOVA → NO) 씁니다. 본인이 정한 표기 이름이 있으면 그걸 우선합니다.
        const label = c.raid_display_name || (c.boss_section ? c.name.slice(0, 2) : c.name);
        const ratio = c.max_hp > 0 ? Math.max(0, c.current_hp / c.max_hp) : 0;
        const hpCls = ratio <= 0.3 ? 'low' : (ratio <= 0.6 ? 'mid' : '');
        // 이름이 길면 칸 안에 들어가도록 글자 크기를 줄입니다.
        // 한글은 영문보다 넓어서(글자당 약 1em) 따로 셉니다.
        const em = [...label].reduce((a, ch) => a + (/[\u3131-\uD79D]/.test(ch) ? 1 : 0.62), 0);
        const fitPx = Math.min(fontPx, Math.floor(cellPx * 0.92 / Math.max(1, em)));
        inner = `<span class="gname" style="font-size:${Math.max(window.innerWidth <= 900 ? 7 : 9, fitPx)}px;">${label}</span>`
          + `<div class="ghp"><div class="${hpCls}" style="width:${ratio * 100}%;"></div></div>` + cornerMarks;
      }
      html += `<td ${onclick} ${tipAttr}${telKeys.has(key) ? ' class="tel"' : ''} style="cursor:${cursor}; ${tdStyle}">`
        + `<div class="gcell ${cellCls}" style="width:${cellPx}px; height:${cellPx}px; ${cellStyle} ${glow}">${inner}<div class="gsel ${isGridTarget(c) ? 'tgt' : ''}" style="${isGridTarget(c) ? '' : selBorder}"></div></div></td>`;
    }
    html += '</tr>';
  }
  html += '</table>';
  el.innerHTML = html;
  applyMapBackground();
  drawAttackLines();
  // 이동/사거리 안내는 지도 아래가 아니라 지도 위 알림줄(라디오 아이콘 옆)에 함께 보여줍니다.
  const guide = (selChar && selChar.teamLabel === 'B' && enemyZone.size && !(gmView && highlightCells.size && !highlightIsAction))
    ? `${displayNameOf(selChar).replace(/\s*[\[-]\s*[NS][EW]\]?$/, '')}의 사거리를 표시합니다. 사거리 내의 캐릭터가 피격될 시 피해가 1.2배 가산됩니다.`
    : isEnemyTurn
    ? '적 턴입니다. 적을 누르면 사거리가 표시됩니다. 사거리 내의 캐릭터가 피격될 시 피해가 1.2배 가산됩니다.'
    : (selChar
      ? (highlightIsAction
          ? `${displayNameOf(selChar)}의 사거리를 표시합니다. 사거리 내의 대상을 눌러 행동을 선택합니다.`
          : `${displayNameOf(selChar)}의 이동 범위를 표시합니다. 이동할 칸을 눌러 이동합니다.`)
      : '캐릭터를 누르면 이동 범위와 사거리가 표시됩니다.');
  renderGridNotice(battle, guide);
  const legend = document.getElementById('gridLegend');
  if (legend) { legend.textContent = ''; legend.style.display = 'none'; }

  renderGridActionPopup(battle, all);
}

// 맵 위 알림줄 : 공성전은 이번 라운드 거점 행동 횟수, 마스 레이드는 공개된 전조(피해 구역) 칸 수를 안내합니다.
let lastGridGuide = '';
function renderGridNotice(battle, guide) {
  const el = document.getElementById('gridNoticeText');
  if (!el) return;
  if (guide !== undefined) lastGridGuide = guide;
  const parts = [];
  // 운영진 전조 선택 중 : 다른 안내 대신 선택 방법과 고른 칸 수만
  if (typeof telegraphMode !== 'undefined' && telegraphMode && myControlInfo(battle).scope === 'all') {
    el.textContent = BATTLE_TYPE === 'mass_raid'
      ? `전조 선택 중 · 피해 장판 ${telegraphSelectedCells.size}칸 · 장애물 ${telegraphObstacleCells.size}칸 — 왼쪽 클릭은 피해 장판, 오른쪽 클릭은 장애물. Shift+클릭은 가로 한 줄, Shift+우클릭은 세로 한 줄.`
      : `전조 선택 중 · 고른 칸 ${telegraphSelectedCells.size}개 — 칸을 눌러 선택합니다. Shift+클릭은 가로 한 줄, Shift+우클릭은 세로 한 줄을 한꺼번에 선택합니다.`;
    return;
  }
  if (BATTLE_TYPE === 'siege' && lastSiteDice && lastSiteDice.value != null && !lastSiteDice.stale) {
    parts.push(`이번 턴 적이 ${lastSiteDice.value}회 공격합니다.`);
  }
  if (telegraphRevealedCells.size > 0) {
    parts.push(`${telegraphRevealedCells.size}칸의 재해 구역이 공개됩니다.`);
  }
  if (!battle) parts.push('전투 시작 전입니다.');
  else if (lastGridGuide) parts.push(lastGridGuide);
  else if (!parts.length) parts.push('새 알림이 없습니다.');
  el.textContent = parts.join(' ');
}

// 창 크기가 바뀌면 맵 칸 크기를 다시 계산합니다.
let gridResizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(gridResizeTimer);
  gridResizeTimer = setTimeout(() => {
    if (document.getElementById('gridSection')) renderGrid(lastBattleForPanel, lastAllForCards);
  }, 120);
});

function renderGridActionPopup(battle, all) {
  const popup = document.getElementById('gridActionPopup');
  if (!popup) return;
  // 예전 파란 팝업은 쓰지 않습니다 : 대상을 고르면 아래 커맨드 블록이 대신 맞춰져 켜집니다(armCommandFromGrid).
  popup.style.display = 'none'; return;
  if (!battle || !selectedGridChar || !selectedGridTargetName) { popup.style.display = 'none'; return; }
  const control = myControlInfo(battle);
  const canAct = control.scope === 'all' || (control.scope === 'character' && control.character.name === selectedGridChar);
  if (!canAct) { popup.style.display = 'none'; return; }
  const actor = all.find(c => c.name === selectedGridChar);
  const target = all.find(c => c.name === selectedGridTargetName);
  if (!actor || !target) { popup.style.display = 'none'; return; }

  const isSelf = actor.name === target.name;
  const isEnemy = actor.teamLabel !== target.teamLabel;
  // '방어'는 본인 지정 = 직접 방어, 아군 지정 = 대리 방어. '수호'는 본인을 뺀 아군에게만 쓸 수 있습니다.
  const allyTargetLabels = ALLY_TARGET_ACTIONS;
  const allowedLabels = isEnemy ? ENEMY_TARGET_ACTIONS
    : isSelf ? new Set([...allyTargetLabels, ...SELF_ONLY_ACTIONS].filter(l => l !== '수호'))
    : allyTargetLabels;

  const buttons = actor.available_actions.filter(label => allowedLabels.has(label)).map(label => {
    const type = resolveActionType(label, actor.role);
    if (NEEDS_TARGET.has(type)) {
      return `<button onclick="quickAction('${type}','${actor.name}','${target.name}'); closeGridSelection();">${label}</button>`;
    }
    return `<button onclick="quickAction('${type}','${actor.name}'); closeGridSelection();">${label}</button>`;
  }).join(' ');

  const targetLabel = isSelf ? '본인' : displayNameOf(target);
  popup.innerHTML = `<b>${displayNameOf(actor)}</b> → <b>${targetLabel}</b> 행동 선택 : ${buttons || '<i>이 대상에게 가능한 행동이 없습니다</i>'} <button onclick="closeGridSelection()" style="float:right;">닫기</button>`;
  popup.style.display = 'block';
}

function closeGridSelection() {
  selectedGridChar = null;
  selectedGridTargetName = null;
  disarmGridCommand();
  renderGrid(lastBattleForPanel, lastAllForCards);
}

// 캐릭터를 눌러 이동/사거리를 띄운 상태에서 다른 곳을 누르면 선택을 끕니다.
// 지도에서 누를 수 있는 칸(캐릭터 · 이동 칸), 아래 커맨드 블록, 확대/축소 버튼, 팝업 안은 그대로 둡니다. Esc로도 끕니다.
document.addEventListener('click', (e) => {
  if (!selectedGridChar || !e.target || !e.target.closest) return;
  if (e.target.closest('td[onclick], .action-bar-bottom, #gridZoomCtl, .modal-overlay, #floatTip')) return;
  closeGridSelection();
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !selectedGridChar) return;
  if (document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  closeGridSelection();
});

function tickTimer() {
  const el = document.getElementById('roundTimer');
  if (roundDeadlineAt == null) {
    setFlipClock(el, '--:--');
    el.style.color = '';
    return;
  }
  const remain = Math.max(0, Math.ceil(roundDeadlineAt - serverNowSec()));
  const m = String(Math.floor(remain / 60)).padStart(2, '0');
  const s = String(remain % 60).padStart(2, '0');
  setFlipClock(el, `${m}:${s}`);
  el.style.color = remain <= 30 ? '#ff8080' : '';
}

// 플립 시계 : 숫자가 바뀌면 윗장이 아래로 넘어가며 새 숫자가 드러납니다.
function setFlipClock(el, text) {
  if (el.dataset.flipText === text) return;
  const chars = [...text];
  if (!el.querySelector('.flip') || el.children.length !== chars.length) {
    el.innerHTML = chars.map(ch => ch === ':'
      ? '<span class="flip-sep">:</span>'
      : `<span class="flip" data-v="${ch}"><span class="f-half f-top"><span>${ch}</span></span><span class="f-half f-bot"><span>${ch}</span></span></span>`).join('');
    el.dataset.flipText = text;
    return;
  }
  chars.forEach((ch, i) => {
    const card = el.children[i];
    if (!card.classList.contains('flip') || card.dataset.v === ch) return;
    const old = card.dataset.v;
    card.dataset.v = ch;
    card.querySelectorAll('.f-flip').forEach(n => n.remove());
    card.querySelector('.f-top > span').textContent = ch;          // 뒤에 있는 윗장 = 새 숫자
    card.querySelector('.f-bot > span').textContent = old;         // 아랫장은 넘어올 때까지 옛 숫자
    card.insertAdjacentHTML('beforeend',
      `<span class="f-half f-top f-flip f-out"><span>${old}</span></span><span class="f-half f-bot f-flip f-in"><span>${ch}</span></span>`);
    setTimeout(() => {
      if (card.dataset.v !== ch) return;
      card.querySelector('.f-bot:not(.f-flip) > span').textContent = ch;
      card.querySelectorAll('.f-flip').forEach(n => n.remove());
    }, 620);
  });
  el.dataset.flipText = text;
}
setInterval(tickTimer, 200);

const LOG_GROUP_START_TAGS = new Set(['action', 'defend', 'taunt', 'round', 'wait']);
// 로그 아이콘 : 이모지 대신 한 벌의 단색 아이콘(Font Awesome)으로 통일
const LOG_TAG_ICON = {
  action: 'fa-solid fa-bolt', damage: 'fa-solid fa-burst', defend: 'fa-solid fa-shield-halved', defend_value: 'fa-solid fa-shield-halved',
  taunt: 'fa-solid fa-crosshairs', heal: 'fa-solid fa-plus', crit: 'glyph-crit', wait: 'fa-solid fa-pause', hp: 'fa-solid fa-heart',
  system: 'fa-solid fa-circle-info', summary: 'fa-solid fa-list', formula: '',
};
// 라운드/단계 안내 한 줄 (채팅창·로그창 공통) : "✶ Round 1"은 기호 + Baunk 제목,
// "선공 단계 : 2팀"은 기호 없이 Round 글자의 왼쪽 선에 맞춰 흰색으로 씁니다.
function roundHeadHtml(text, fmt) {
  const t = (text || '').trim();
  const f = fmt || (x => x);
  if (/^round\s*\d+/i.test(t)) return `<span class="rh"><span class="rh-mark">✶</span><span class="rh-main">${f(t)}</span></span>`;
  return `<span class="rh"><span class="rh-mark"></span><span class="rh-sub">${f(t.replace(/^▶\s*/, ''))}</span></span>`;
}
// 예전에 저장된 안내 문구에 남아 있는 구슬 이모지는 표시할 때 지웁니다.
function stripLegacyEmoji(t) { return typeof t === 'string' ? t.replace(/\u{1F52E}\s*/gu, '').replace('[규칙] 1팀이 항상 선공입니다.', '[규칙] 러너 팀이 항상 선공입니다.') : t; }
// 공성전 : 거점(2팀)의 2x2 부위 이름(BOSS-NW 등)은 행동 문구에서 거점 이름 하나(BOSS)로 보여줍니다.
// (체력 변화 줄은 어느 부위가 맞았는지 알 수 있도록 부위 이름을 그대로 둡니다)
function siteLabelize(text) {
  if (BATTLE_TYPE !== 'siege' || typeof text !== 'string') return text;
  let out = text;
  (lastAllForCards || []).forEach(c => {
    if (c.teamLabel === 'B' && c.boss_group && c.boss_section) {
      out = out.split(c.name).join(c.name.split(/[ -]/)[0]);
    }
  });
  return out;
}
// 로그 한 줄 정리 : 서버가 쓰는 모든 문구를 같은 규칙으로 다듬습니다.
//  - 글 앞 이모지(⚠ ⚡ 🛡 🩸 🧪 ⚔ ✚ ❤)는 빼고 아이콘 칸이 대신합니다(⚠는 주의 색).
//  - "→ …" 로 시작하는 설명 줄은 조용한 메모(↳)로.
//  - [분류]는 작은 회색 글자, 【스킬】은 포인트 글자, 숫자는 흰 굵은 글자, 화살표는 흐리게.
//  - "이름 HP a → b"·"(a→b)"는 같은 체력 표시, 변화가 없으면 생략. "피해량 N"은 "피해 N".
function logLineParts(text, tag) {
  let t = typeof text === 'string' ? text : String(text || '');
  let tone = '';
  const em = t.match(/^\s*(⚠|⚡|🛡|🩸|🧪|⚔|✚|❤)️?\s*/u);
  if (em) { if (em[1] === '⚠') tone = 'warn'; t = t.slice(em[0].length); }
  if (/^→\s*/.test(t)) { t = t.replace(/^→\s*/, ''); tone = tone || 'note'; }
  if (tag === 'crit') tone = 'crit';
  else if (/다운!|사망/.test(t) && (tag === 'system')) tone = 'bad';
  else if (/위기를 넘|복귀했습니다|회피 성공|도주 성공/.test(t)) tone = 'good';
  t = t.replace(/^(.+?) HP (\d+)\s*→\s*(\d+)\s*$/, '$1 ($2→$3)');
  t = t.replace(/^피해량\s*(\d+)/, '피해 $1');
  const html = t.split(/(<[^>]+>)/).map((seg, i) => {
    if (i % 2) return seg;
    let x = seg;
    x = x.replace(/^\s*\[([^\]]{1,40})\]\s*/, (m, lab) => /,/.test(lab) && tag === 'summary'
      ? `<span class="lg-sum">${lab}</span>` : `<span class="lg-lab">${lab.replace(/\s*-\s*/g, ' · ')}</span>`);
    x = x.replace(/【([^】]{1,20})】/g, '<span class="lg-skill">$1</span>');
    x = x.replace(/\s*\((\d+)\s*→\s*(\d+)\)/g, (m, a, b) => {
      const d = (+b) - (+a);
      if (!d) return '';
      const delta = (tag === 'heal' && d > 0) ? '' : `<em class="${d > 0 ? 'up' : 'down'}">${d > 0 ? '+' : ''}${d}</em>`;
      return ` <span class="lg-hp">${a}<i>→</i><b>${b}</b>${delta}</span>`;
    });
    x = x.replace(/(^|[\s(])\+(\d+)(?=[\s*),]|$)/g, '$1<b class="lg-num">+$2</b>');
    x = x.replace(/(수치|피해|회복|보호막)\s+(\d+)(?=[\s(,]|$)/g, '$1 <b class="lg-num">$2</b>');
    x = x.replace(/ (→|↔) /g, ' <i class="lg-ar">$1</i> ');
    return x;
  }).join('');
  return { html, tone };
}
function decorateLogText(text, tag) { return logLineParts(text, tag).html; }
function formatLogLineHtml(l, noIcon, asHead) {
  l = { ...l, text: stripLegacyEmoji(l.text) };
  if (l.tag !== 'hp') l.text = siteLabelize(l.text);
  if (l.tag === 'round') {
    const main = /^round\s*\d+/i.test((l.text || '').trim());
    return `<div class="logline tag-round${main ? ' is-round-main' : ''}">${roundHeadHtml(l.text)}</div>`;
  }
  if (l.tag === 'arrow') return '<div class="logsep"></div>';
  // 블록 첫 줄(누가 무엇을)만 굵게 : 블록을 그리는 쪽이 알려주면(asHead) 그 값을, 아니면 태그로 판단합니다.
  const head = asHead !== undefined ? asHead : LOG_GROUP_START_TAGS.has(l.tag);
  let { html, tone } = logLineParts(l.text, l.tag);
  // 즉시 정산(공격 수치 → 방어 → 최종 → HP)을 한 줄로 : "공격 nn · 방어 nn · 최종 nn   HP 현재"
  if (l._res) {
    html = l._resOnly ? `<span class="st-atk">${shopEsc(siteLabelize(l.text))}</span>방어 <b class="lg-num">${l._res.def}</b> · 최종 <b class="lg-num">${l._res.dmg}</b>${l._res.zone ? `<span class="lg-zone">사거리 ×${l._res.zone}</span>` : ''}${logResHp(null, l._res.hp)}`
      : html.replace(/공격 수치(\s*<b class="lg-num">)/, '공격$1') + ` · 방어 <b class="lg-num">${l._res.def}</b> · 최종 <b class="lg-num">${l._res.dmg}</b>${l._res.zone ? `<span class="lg-zone">사거리 ×${l._res.zone}</span>` : ''}${logResHp(l._res.hpName, l._res.hp)}`;
  }
  // 크리티컬은 따로 한 줄을 쓰지 않고, 그 타격(회복) 줄 끝에 작은 표시로 붙입니다.
  if (l._crit) html += `<span class="lg-crit ${l.tag === 'heal' ? 'heal' : 'atk'}"><i>✦</i>크리티컬</span>`;
  if (l._res && l._res.defCrit) html += '<span class="lg-crit def"><i>✦</i>방어 크리티컬</span>';
  // 공성전 : 거점 행동 횟수(1/3 …)를 행동 첫 줄 끝에 붙입니다.
  if (l._tail) html += `<span class="lg-lab lg-tail">${l._tail}</span>`;
  // 아이콘은 블록 첫 줄에만 둡니다(아래 줄은 비워 정렬만 맞춤). 주의(⚠) 줄만 예외로 항상 표시.
  const ic = tone === 'warn' ? 'fa-solid fa-triangle-exclamation'
    : noIcon ? '' : tone === 'note' ? 'fa-solid fa-turn-up fa-rotate-90' : (LOG_TAG_ICON[l.tag] || '');
  // 직군 색은 블록 왼쪽 선이 맡고, 글줄은 모두 같은 색으로 둡니다(아이콘 칸 + 글 칸 두 칸 정렬).
  return `<div class="logline${head ? ' group-start' : ''} tag-${l.tag}${tone ? ' tone-' + tone : ''}"><span class="li">${ic === 'glyph-crit' ? '<i class="lg-gl">✦</i>' : ic ? `<i class="${ic}"></i>` : ''}</span><span class="lt">${html}</span></div>`;
}
// 블록 첫 줄의 내용으로 공격/방어/힐 중 어떤 행동인지 구분해 그 색을 입힙니다. 피해 정산처럼
// 자동으로 발생한 안내성 줄("["로 시작)이나 이동/배치처럼 셋 중 어디에도 안 속하는 행동은
// 무채색(기본 테두리색) 그대로 둡니다.
function logActionClass(head) {
  if (head.tag === 'defend') return 'def';
  if (head.tag === 'heal') return 'heal';
  if (head.tag !== 'action') return '';
  const t = head.text;
  if (t.startsWith('[')) return '';
  if (t.includes('공격') || t.includes('【붕괴】') || t.includes('【방출】')) return 'atk';
  if (t.includes('힐')) return 'heal';
  if (t.includes('방어') || t.includes('회피')) return 'def';
  return '';
}
// 캐릭터 한 명의 행동(공격 → 크리티컬 → 공격 수치 …)을 하나의 블록으로 묶어 보여줍니다.
// 라운드 최종 결과 : "이름  시작 → 종료 (상태)" 줄들을 표로 정리합니다(팀별로 나누고, 변화량과 체력 막대 표시).
function formatRoundSummaryHtml(section) {
  const head = section[0];
  const esc = t => String(t).replace(/[&<>]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
  const rows = [];
  const rest = [];
  section.slice(1).forEach(l => {
    const m = l.tag === 'summary' && (l.text || '').match(/^(.+?)\s+(\d+)\s*→\s*(\d+)(?:\s*\((.+)\))?\s*$/);
    if (m) rows.push({ name: m[1].trim(), start: +m[2], end: +m[3], state: m[4] || '' });
    else if (l.tag !== 'system' || !/시작 체력/.test(l.text || '')) rest.push(l);
  });
  if (!rows.length) return section.map((l, i) => formatLogLineHtml(l, i > 0)).join('');
  const chars = lastAllForCards || [];
  const info = n => chars.find(c => c.name === n) || {};
  const rowHtml = r => {
    const c = info(r.name);
    const d = r.end - r.start;
    const label = c.name ? displayNameOf(c) : r.name;
    return `<div class="rs-row${r.state ? ' out' : ''}">
      <span class="rs-name">${esc(label)}${r.state ? ` <em>${esc(r.state)}</em>` : ''}</span>
      <span class="rs-num">${r.start}</span><span class="rs-arrow">→</span><span class="rs-num end">${r.end}</span>
      <span class="rs-delta ${d < 0 ? 'minus' : d > 0 ? 'plus' : ''}">${d < 0 ? '<i class="fa-solid fa-caret-down"></i>' + Math.abs(d) : d > 0 ? '<i class="fa-solid fa-caret-up"></i>' + d : '–'}</span>
    </div>`;
  };
  const teamA = rows.filter(r => info(r.name).teamLabel !== 'B');
  const teamB = rows.filter(r => info(r.name).teamLabel === 'B');
  const block = (title, list) => list.length ? `<div class="rs-team">${title}</div>${list.map(rowHtml).join('')}` : '';
  return formatLogLineHtml(head)
    + `<div class="round-summary">
        ${block(BATTLE_TYPE === 'pvp' ? 'Team 1' : '러너', teamA)}${block(BATTLE_TYPE === 'pvp' ? 'Team 2' : (BATTLE_TYPE === 'siege' ? '거점' : '보스'), teamB)}
      </div>`
    + rest.map(l => formatLogLineHtml(l, true)).join('');
}
// 같은 [분류]로 시작하는 회복 줄이 연달아 나오면("[환류 - 메딕 회복] AG +18 (240→240)" 여러 줄)
// 한 줄로 묶습니다 : [환류 · 메딕 회복] AG +18 · F +24 · C +36 …
function mergeLogRuns(lines) {
  const out = [];
  const RX = /^\s*\[([^\]]{1,30})\]\s*(\S+)\s+\+(\d+)(.*)$/;
  lines.forEach(l => {
    const m = l.tag === 'heal' && typeof l.text === 'string' && l.text.match(RX);
    const prev = out[out.length - 1];
    if (m && prev && prev._merge && prev._merge.label === m[1]) { prev._merge.items.push({ name: m[2], amt: m[3], rest: m[4] }); return; }
    out.push(m ? { ...l, _merge: { label: m[1], items: [{ name: m[2], amt: m[3], rest: m[4] }] } } : l);
  });
  return out.map(l => {
    if (!l._merge || l._merge.items.length < 2) return l._merge ? { tag: l.tag, role: l.role, text: l.text } : l;
    const items = l._merge.items.map(it => `<span class="lg-it">${it.name} +${it.amt}${/정산 후/.test(it.rest) ? '*' : ''}</span>`).join(' · ');
    const note = l._merge.items.some(it => /정산 후/.test(it.rest)) ? ' (*피해 정산 후 적용)' : '';
    return { tag: l.tag, role: l.role, text: `[${l._merge.label}] ${items}${note}` };
  });
}
// 격자 전투 이동("NAME 이동 K7 → J7")은 행동 횟수를 쓰지 않으므로, 단계(선공/후공)마다 단계 안내 바로 아래
// 첫 행동 블록 바로 앞 한 블록으로 모아 보여줍니다(행동 블록들과 섞이지 않게). 화면 표시 순서만 바꾸고 기록은 그대로입니다.
const LOG_MOVE_RX = /^(.+?) 이동 ([A-Z]+\d+) → ([A-Z]+\d+)$/;
function isLogMoveLine(l) { return l && l.tag === 'action' && typeof l.text === 'string' && LOG_MOVE_RX.test(l.text); }
function groupPhaseMoves(lines) {
  const out = [];
  let seg = [];
  const flush = () => {
    const moves = seg.filter(isLogMoveLine);
    const rest = seg.filter(l => !isLogMoveLine(l));
    // 단계 첫머리의 안내 줄(전조 공개 등) 다음, 첫 행동 블록 앞에 둡니다.
    let at = rest.findIndex(l => LOG_GROUP_START_TAGS.has(l.tag));
    if (at < 0) at = rest.length;
    if (moves.length) rest.splice(at, 0, { tag: 'movegroup', moves });
    out.push(...rest);
    seg = [];
  };
  lines.forEach(l => { if (l.tag === 'round') { flush(); out.push(l); } else seg.push(l); });
  flush();
  return out;
}
function formatMoveGroupHtml(g) {
  const rows = g.moves.map(l => {
    const m = l.text.match(LOG_MOVE_RX);
    return `<div class="logline tag-move"><span class="li"></span><span class="lt"><span class="mv-name">${shopEsc(m[1])}</span>`
      + `<span class="mv-cells">${m[2]}<i class="lg-ar">→</i>${m[3]}</span></span></div>`;
  }).join('');
  return `<div class="logblock moves"><div class="logline group-start tag-action"><span class="li"><i class="fa-solid fa-shoe-prints"></i></span>`
    + `<span class="lt">이동<span class="lg-cnt">${g.moves.length}명</span></span></div>${rows}</div>`;
}
// "이름 【스킬】 …" 로 시작하는 줄이면 {who, skill}, 아니면 null
const LOG_SKILL_HEAD_RX = /^(\S+) 【([^】]{1,20})】/;
function logSkillHead(l) {
  const m = l && typeof l.text === 'string' && l.text.match(LOG_SKILL_HEAD_RX);
  return m ? { who: m[1], skill: m[2] } : null;
}
// 마스 레이드 · 공성전은 러너 팀이 항상 선공이라, 선공 결정(민첩 비교 · 규칙 안내) 줄을 로그창에 띄우지 않습니다.
const LOG_FIRST_TEAM_RX = /^(\[선공 결정\]|→ 민첩 합산이 더 높은|민첩 합산 동점|→ 주사위 결과|\[규칙\] .*항상 선공)/;
// 예전 문구로 이미 저장된 로그도 지금 문구로 보여줍니다(서버를 다시 켜기 전 전투 · 지난 전투 기록).
const LOG_LEGACY_TEXT = [
  [/^(⚡ 편광 : .+?)이\(가\) 못 막은 피해 /, '$1의 잔여 피해 '],
  [/^(전조 발동 — .+?)의 공격이 /, '$1의 공명이 '],
  [/^전조 공개 : (\d+)칸에 곧 피해가 발생합니다\./, '전조 공개 : $1칸에 곧 재해가 발생합니다.'],
  [/^전조 공개 : 이번 라운드는 피해 구역이 없습니다\./, '전조 공개 : 이번 라운드는 재해 구역이 없습니다.'],
  [/ \(다이스 ×\d+, (?:각 )?\d+회 공격\)$/, ''],
  [/ 다운! \(팀 전체가 이번 라운드 행동을 마쳐야 생사가 확정됩니다\)$/, ' 다운!'],
  [/ 사망 \(팀의 라운드 행동이 모두 끝났습니다\)$/, ' 사망'],
  [/, 이 효과로는 죽지 않습니다\)/, ')'],
];
function modernizeLogText(t) {
  if (typeof t !== 'string') return t;
  LOG_LEGACY_TEXT.forEach(([rx, to]) => { t = t.replace(rx, to); });
  return t;
}
function dropFirstTeamLines(lines) {
  // 단계 사이 ↓ 줄은 블록 안에 끼어 빈 줄처럼 보이므로 뺍니다(단계 제목이 이미 구분해 줍니다).
  lines = lines.filter(l => l.tag !== 'arrow').map(l => (typeof l.text === 'string' ? { ...l, text: modernizeLogText(l.text) } : l));
  return (BATTLE_TYPE === 'mass_raid' || BATTLE_TYPE === 'siege') ? lines.filter(l => !(l.tag === 'system' && LOG_FIRST_TEAM_RX.test(l.text || ''))) : lines;
}
// "크리티컬!" 줄 + 바로 다음 타격(회복) 줄 → 그 줄 하나에 크리티컬 표시. "(강제 크리티컬 적용)" 문구도 같은 표시로 바꿉니다.
function mergeCritLines(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i], n = lines[i + 1];
    if (l.tag === 'crit' && /^\s*크리티컬!?\s*$/.test(l.text || '') && n && (n.tag === 'damage' || n.tag === 'heal')) {
      out.push({ ...n, text: typeof n.text === 'string' ? n.text.replace(/\s*\(강제 크리티컬 적용\)/, '') : n.text, _crit: true }); i++; continue;
    }
    if (typeof l.text === 'string' && /\s*\(강제 크리티컬 적용\)/.test(l.text)) {
      out.push({ ...l, text: l.text.replace(/\s*\(강제 크리티컬 적용\)/, ''), _crit: true }); continue;
    }
    out.push(l);
  }
  return out;
}
// 스킬 블록 정리 : 첫 줄은 "C 환류"처럼 누가 · 어떤 스킬만, 내용은 아래 줄로 내리고,
// 아래 줄마다 반복되는 "C 【환류】" · "[환류 - …]" · "[붕괴 1/2]"의 스킬 이름은 뺍니다.
function tidySkillSection(section) {
  const hk = logSkillHead(section[0]);
  if (!hk) return section;
  const pre = `${hk.who} 【${hk.skill}】`;
  const labRx = new RegExp('^\\s*\\[' + hk.skill + '(?:\\s*[-·]\\s*|\\s*→\\s*|\\s+)?([^\\]]*)\\]\\s*');
  const out = [];
  section.forEach((l, i) => {
    const t = typeof l.text === 'string' ? l.text : '';
    const own = t.startsWith(pre + ' ');
    const rest = own ? t.slice(pre.length + 1) : t;
    if (i === 0) {
      if (own && !/^[→:]/.test(rest)) { out.push({ ...l, text: pre }); out.push({ ...l, text: rest }); }
      else out.push(l);
      return;
    }
    out.push({ ...l, text: rest.replace(labRx, (m, r) => r.trim() ? `[${r.trim()}] ` : '') });
  });
  return out;
}
// 피해 정산 : "[피해 정산] 공격자 → 대상" + 방어 값 · 피해량 · HP 줄들을 정산 1회 = 한 줄로 줄이고,
// 같은 대상의 정산이 연달아 나오면(바로 앞의 "대상 방어 정산" 줄 포함) 한 블록으로 묶습니다.
const LOG_SETTLE_RX = /^\[피해 정산\]\s*(.+?) → (.+?)(?:\s*\(공격 수치 (\d+)\))?$/;
function parseSettleSection(sec) {
  const m = typeof sec[0].text === 'string' && sec[0].tag === 'action' && sec[0].text.match(LOG_SETTLE_RX);
  if (!m) return null;
  const row = { atk: m[1], tgt: m[2], atkVal: m[3] || null, def: null, dmg: null, hp: null, hpName: null, defCrit: false, notes: [] };
  sec.slice(1).forEach(l => {
    const t = typeof l.text === 'string' ? l.text : '';
    let k;
    if (l.tag === 'defend_value' && (k = t.match(/방어 값 (\d+)/))) row.def = k[1];
    else if (l.tag === 'damage' && (k = t.match(/^피해량 (\d+)(?:\s*\((?:범위|사거리) ×([\d.]+)\))?/))) { row.dmg = k[1]; row.zone = k[2] || null; }
    else if (l.tag === 'hp' && (k = t.match(/^(.+?) HP (\d+)\s*→\s*(\d+)/))) { row.hpName = k[1]; row.hp = [+k[2], +k[3]]; }
    else if (l.tag === 'crit' && /방어 크리티컬/.test(t)) row.defCrit = true;
    else row.notes.push(l);
  });
  return row;
}
function combineSettlements(sections) {
  const out = [];
  sections.forEach(sec => {
    const row = parseSettleSection(sec);
    if (!row) { out.push(sec); return; }
    const prev = out[out.length - 1];
    if (prev && prev.settle && prev.settle.tgt === row.tgt) { prev.settle.rows.push(row); return; }
    // 바로 앞이 "대상 방어 정산" 한 줄짜리 블록이면 그 줄을 머리로 씁니다.
    if (Array.isArray(prev) && prev.length === 1 && prev[0].text === `${row.tgt} 방어 정산`) {
      out[out.length - 1] = { settle: { tgt: row.tgt, head: prev[0].text, rows: [row] } };
      return;
    }
    out.push({ settle: { tgt: row.tgt, head: null, rows: [row] } });
  });
  return out;
}
function formatSettleGroupHtml(g) {
  const nm = t => shopEsc(siteLabelize(t));
  const head = `<div class="logline group-start tag-defend"><span class="li"><i class="fa-solid fa-shield-halved"></i></span>`
    + `<span class="lt">${g.head ? nm(g.head) : `${nm(g.tgt)} 피해 정산`}${g.rows.length > 1 ? `<span class="lg-cnt">${g.rows.length}회</span>` : ''}</span></div>`;
  const rows = g.rows.map(r => {
    // 공격 nn · 방어 nn · 최종 nn   HP 현재 체력
    const parts = [];
    if (r.atkVal != null) parts.push(`공격 <b class="lg-num">${r.atkVal}</b>`);
    if (r.def != null) parts.push(`방어 <b class="lg-num">${r.def}</b>`);
    if (r.dmg != null) parts.push(`최종 <b class="lg-num">${r.dmg}</b>${r.zone ? `<span class="lg-zone">사거리 ×${r.zone}</span>` : ''}`);
    const hp = r.hp ? logResHp(r.hpName && r.hpName !== r.tgt ? r.hpName : null, r.hp[1]) : '';
    const crit = r.defCrit ? '<span class="lg-crit def"><i>✦</i>방어 크리티컬</span>' : '';
    const notes = [...r.notes];
    // 회피처럼 수치 줄이 없으면 첫 안내를 그 줄 내용으로 씁니다.
    const body = parts.length ? parts.join(' · ') : (notes.length ? logLineParts(siteLabelize(notes.shift().text), 'heal').html : '');
    return `<div class="logline tag-damage st-row"><span class="li"></span>`
      + `<span class="lt"><span class="st-atk">${nm(r.atk)}</span>${body}${hp}${crit}</span></div>`
      + notes.map(l => formatLogLineHtml(l, true, false)).join('');
  }).join('');
  return `<div class="logblock settle def">${head}${rows}</div>`;
}
// 공성전 : "거점 추가 행동 가능 (남은 횟수 N회)" · "거점의 이번 라운드 행동이 모두 끝났습니다." 줄을 따로 두지 않고,
// 바로 앞 거점 행동의 첫 줄 끝에 "1/3"처럼 횟수로 붙입니다(전조 다이스 줄의 총 횟수 기준).
function mergeSiteCounters(lines) {
  if (BATTLE_TYPE !== 'siege') return lines;
  const out = [];
  let total = null;
  lines.forEach(l => {
    const t = typeof l.text === 'string' ? l.text : '';
    let m;
    if (l.tag === 'system' && (m = t.match(/거점(?:은|과) (\d+)회 (?:행동합니다|대치합니다)/))) total = +m[1];
    const left = l.tag === 'system' && (m = t.match(/^거점 (?:추가 행동 가능 \(이번 라운드 남은 횟수|행동 게이지 \(라운드 내) (\d+)회\)$/)) ? +m[1]
      : (l.tag === 'system' && /^거점의 이번 라운드 행동이 모두 끝났습니다\.?$/.test(t) ? 0 : null);
    if (left == null) { out.push(l); return; }
    for (let i = out.length - 1; i >= 0; i--) {
      if (LOG_GROUP_START_TAGS.has(out[i].tag) && out[i].tag !== 'round') {
        out[i] = { ...out[i], _tail: total ? `${total - left}/${total}` : (left ? `남은 ${left}회` : '행동 끝') };
        return;
      }
    }
    out.push(l);
  });
  return out;
}
// 같은 행동 묶기 : "AA 방어 (직접 방어)" · "AB 방어 (직접 방어)" …처럼 내용이 같은 짧은 행동 블록이
// 연달아 나오면 한 블록으로 합칩니다(제목 = 행동, 아래 줄 = 누가 · 수치). 공격 수치 · 회복 한 줄짜리까지만.
function sameActionKey(sec) {
  if (!Array.isArray(sec) || !sec.length || sec.length > 2) return null;
  const h = sec[0];
  if (!(h.tag === 'action' || h.tag === 'defend') || typeof h.text !== 'string' || logSkillHead(h) || h._tail) return null;
  if (h.text.startsWith('[') || isLogMoveLine(h)) return null;
  const m = h.text.match(/^(\S+) (.+)$/);
  if (!m) return null;
  const sub = sec[1];
  if (sub && !((sub.tag === 'damage' && /^공격 수치 \d+/.test(sub.text || '')) || (sub.tag === 'heal' && /^회복 \d+/.test(sub.text || '')))) return null;
  return { key: siteLabelize(m[2]), name: m[1], tag: h.tag, sub: sub || null, head: h };
}
function combineSameActions(sections) {
  const out = [];
  sections.forEach(sec => {
    const k = sameActionKey(sec);
    const prev = out[out.length - 1];
    if (k && prev && prev.same && prev.same.key === k.key && prev.same.tag === k.tag && !!prev.same.rows[0].sub === !!k.sub) {
      prev.same.rows.push(k); return;
    }
    if (k && prev && !prev.same && sameActionKey(prev)) {
      const pk = sameActionKey(prev);
      if (pk.key === k.key && pk.tag === k.tag && !!pk.sub === !!k.sub) { out[out.length - 1] = { same: { key: k.key, tag: k.tag, head: pk.head, rows: [pk, k] } }; return; }
    }
    out.push(sec);
  });
  return out;
}
function formatSameActionHtml(g) {
  const cls = logActionClass(g.head);
  const ic = LOG_TAG_ICON[g.tag] || '';
  const head = `<div class="logline group-start tag-${g.tag}"><span class="li">${ic ? `<i class="${ic}"></i>` : ''}</span>`
    + `<span class="lt">${logLineParts(g.key, g.tag).html}<span class="lg-cnt">${g.rows.length}명</span></span></div>`;
  const nm = t => shopEsc(siteLabelize(t));
  const body = g.rows[0].sub
    ? g.rows.map(r => {
        const crit = r.sub._crit ? `<span class="lg-crit ${r.sub.tag === 'heal' ? 'heal' : 'atk'}"><i>✦</i>크리티컬</span>` : '';
        return `<div class="logline tag-${r.sub.tag} st-row"><span class="li"></span><span class="lt"><span class="st-atk">${nm(r.name)}</span>${logLineParts(r.sub.text, r.sub.tag).html}${crit}</span></div>`;
      }).join('')
    : `<div class="logline tag-${g.tag}"><span class="li"></span><span class="lt">${g.rows.map(r => nm(r.name)).join(' · ')}</span></div>`;
  return `<div class="logblock${cls ? ' ' + cls : ''}">${head}${body}</div>`;
}
// 정산 줄의 체력 표시 : 현재 체력만 (다른 사람이 대신 맞았으면 그 이름도)
function logResHp(name, cur) {
  return `<span class="lg-hp">${name ? shopEsc(siteLabelize(name)) + ' ' : ''}HP <b>${cur}</b></span>`;
}
// 블록 안 즉시 정산 : [공격 수치 N] + (상대 방어 크리티컬!) + 방어 값 + 피해량 + HP 줄을 한 줄로 합칩니다.
function compactResolutions(section) {
  const out = [];
  for (let i = 0; i < section.length; i++) {
    let j = i, defCrit = false;
    if (section[j] && section[j].tag === 'crit' && /방어 크리티컬/.test(section[j].text || '')) { defCrit = true; j++; }
    const dv = section[j], dm = section[j + 1], hp = section[j + 2];
    const mDv = dv && dv.tag === 'defend_value' && (dv.text || '').match(/방어 값 (\d+)/);
    const mDm = dm && dm.tag === 'damage' && (dm.text || '').match(/^피해량 (\d+)/);
    const mHp = hp && hp.tag === 'hp' && (hp.text || '').match(/^(.+?) HP (\d+)\s*→\s*(\d+)/);
    if (mDv && mDm && mHp) {
      const prev = out[out.length - 1];
      const res = { def: mDv[1], dmg: mDm[1], hp: +mHp[3], hpName: null, defCrit, zone: (dm.text.match(/\((?:범위|사거리) ×([\d.]+)\)/) || [])[1] };
      if (prev && prev.tag === 'damage' && /공격 수치 \d+/.test(prev.text || '') && !prev._res) {
        out[out.length - 1] = { ...prev, _res: res };
      } else {
        out.push({ tag: 'damage', text: `${mHp[1]}`, _res: { ...res, hpName: null }, _resOnly: true });
      }
      i = j + 2;
      continue;
    }
    out.push(section[i]);
  }
  return out;
}
// 선공 결정(PVP) : 제목 · 민첩 비교 · 결과 세 줄짜리 블록으로
function formatFirstTeamHtml(section) {
  const lines = [];
  let result = '';
  section.forEach(l => {
    const t = (l.text || '').trim();
    let m;
    if ((m = t.match(/^\[선공 결정\]\s*(.+)$/))) lines.push(m[1].replace(/\s+vs\s+/, ' vs ').replace(/\s{2,}/g, ' '));
    else if ((m = t.match(/^민첩 합산 동점!\s*(.+)$/))) lines.push('동점 · ' + m[1].replace(/\s{2,}/g, ' '));
    else if ((m = t.match(/^→\s*.*?(\d팀)이 선공입니다/))) result = `= ${m[1]} 선공입니다.`;
    else if (t) lines.push(t);
  });
  const row = t => `<div class="logline tag-system"><span class="li"></span><span class="lt">${shopEsc(t)}</span></div>`;
  return `<div class="logblock cont first-team"><div class="logline group-start tag-system"><span class="li"><i class="fa-solid fa-dice"></i></span><span class="lt">선공 결정</span></div>`
    + lines.map(row).join('') + (result ? `<div class="logline tag-system ft-result"><span class="li"></span><span class="lt">${shopEsc(result)}</span></div>` : '') + '</div>';
}
function formatLogHtml(lines) {
  return combineSameActions(combineSettlements(splitLogIntoSections(groupPhaseMoves(mergeLogRuns(mergeCritLines(mergeSiteCounters(dropFirstTeamLines(lines || [])))))))).map(section => {
    if (section.settle) return formatSettleGroupHtml(section.settle);
    if (section.same) return formatSameActionHtml(section.same);
    if (/^\[선공 결정\]/.test((section[0] && section[0].text) || '')) return formatFirstTeamHtml(section);
    section = compactResolutions(section);
    if (logSkillHead(section[0]) && section.length > 1) section = tidySkillSection(section);
    const head = section[0];
    if (head.tag === 'movegroup') return formatMoveGroupHtml(head);
    if (head.tag === 'round' && /최종 결과/.test(head.text || '')) return formatRoundSummaryHtml(section);
    if (head.tag === 'round') {
      // 라운드 안내 줄 다음에 바로 붙은 결과 줄(회복 · 안내 등)도 떠 보이지 않게 일반 블록으로 묶습니다.
      let out = '', run = [];
      const flush = () => {
        if (!run.length) return;
        const kind = run.some(l => l.tag === 'heal') ? ' heal' : '';
        out += `<div class="logblock cont${kind}">${run.map((l, i) => formatLogLineHtml(l, i > 0)).join('')}</div>`;
        run = [];
      };
      section.forEach(l => { if (l.tag === 'round') { flush(); out += formatLogLineHtml(l, false); } else run.push(l); });
      flush();
      return out;
    }
    const isGroup = LOG_GROUP_START_TAGS.has(head.tag) || !!logSkillHead(head);
    const actionCls = isGroup ? logActionClass(head) : '';
    const cls = `logblock${isGroup ? '' : ' cont'}${actionCls ? ' ' + actionCls : ''}`;
    // 블록 첫 줄(⚔ NOVA 공격 → E)과 바로 아래 줄(⚔ 공격 수치)의 아이콘이 겹치므로, 아래 줄이 있으면 첫 줄 아이콘은 뺍니다.
    return `<div class="${cls}">${section.map((l, i) => formatLogLineHtml(l, i > 0, i === 0 && isGroup)).join('')}</div>`;
  }).join('');
}

let lastPublicLog = [];
let lastOperatorLog = [];
let lastPublicLogTotal = 0;    // 서버가 실제로 갖고 있는 전체 줄 수(전송량 절약을 위해 log는 최근 일부만 옴)
let lastOperatorLogTotal = 0;
let logView = 'public';  // 'public' | 'operator' - GM(비밀번호 입장)만 전환 가능

// 출력창에 새 로그가 한꺼번에 우르르 뜨지 않도록, 그룹(섹션) 단위로 끊어서 약간의
// 딜레이를 두고 하나씩 표시합니다. 서버는 세션이 길어져도 전송량이 안 불어나게 최근
// 일부 줄 + 누적 총 줄 수(log_total)만 보내므로, "이미 본 총 줄 수"를 기억해뒀다가
// 그 이후 줄만 새로 추가된 것으로 봅니다.
const LOG_SECTION_DELAY_MS = 180;
let logSeenTotal = { public: 0, operator: 0 };
let logRevealQueue = { public: [], operator: [] };
let logRevealBusy = { public: false, operator: false };
let logInitialized = { public: false, operator: false };

function splitLogIntoSections(lines) {
  // group-start 태그(action/defend/taunt/round)나 "이름 【스킬】 …" 줄이 나오면 새 섹션의 시작으로 봅니다.
  // 같은 사람의 같은 스킬 줄이 이어지면(환류 : 본인 회복 → 흡수 버프 부여) 한 블록으로 둡니다.
  const sections = [];
  let current = [];
  lines.forEach(line => {
    const sk = logSkillHead(line), hk = current.length ? logSkillHead(current[0]) : null;
    const sameSkill = !!(sk && hk && sk.who === hk.who && sk.skill === hk.skill);
    if ((LOG_GROUP_START_TAGS.has(line.tag) || line.tag === 'movegroup' || sk) && !sameSkill && current.length) {
      sections.push(current);
      current = [];
    }
    current.push(line);
  });
  if (current.length) sections.push(current);
  return sections;
}

function renderPubLog(log, logTotal) {
  const prevTotal = lastPublicLogTotal;
  lastPublicLog = log || [];
  lastPublicLogTotal = logTotal != null ? logTotal : lastPublicLog.length;
  // 로그창을 보고 있지 않을 때 새 로그가 쌓이면 로그창 탭에 안 읽음 점을 켭니다(처음 접속 때는 제외).
  if (logInitialized.public && lastPublicLogTotal > prevTotal && currentMemberView !== 'log') {
    unreadChat.log = true;
    updateUnreadBadges();
  }
  if (logView === 'public') {
    revealNewLogLines('public', lastPublicLog, lastPublicLogTotal);
  } else {
    logSeenTotal.public = lastPublicLogTotal;
    logRevealQueue.public = [];
  }
}

// 처음 열었을 때/재접속처럼 그동안 쌓인 로그를 한 번에 따라잡을 때는 애니메이션 없이 바로
// 전부 보여주고, 그 이후로 실시간으로 추가되는 부분만 섹션 단위로 딜레이를 둡니다.
// fullLog는 서버가 보낸 "최근 일부"이고, logTotal은 서버가 실제로 갖고 있는 총 줄 수입니다.
function revealNewLogLines(view, fullLog, logTotal) {
  if (!logInitialized[view]) {
    logInitialized[view] = true;
    renderCurrentLog();
    return;
  }
  const sliceStart = logTotal - fullLog.length;  // 이번에 받은 조각이 전체에서 시작하는 위치
  const already = logSeenTotal[view];
  if (logTotal < already || already < sliceStart) {
    // 되돌리기로 로그가 줄었거나(logTotal < already), 안 보는 사이 너무 많이 쌓여서
    // 받은 조각 앞부분도 처음 보는 경우(already < sliceStart) - 그냥 받은 걸 통째로 다시 그립니다.
    renderCurrentLog();
    return;
  }
  if (logTotal === already) return;  // 새 줄 없음
  const newLines = fullLog.slice(already - sliceStart);
  // 새 행동 · 방어 · 정산 줄은 앞 블록(같은 행동 묶음 · 정산 묶음 · 이동 묶음 · 거점 횟수)에 합쳐질 수 있으므로,
  // 그런 줄이 있으면 보던 위치를 지킨 채 로그 전체를 다시 그립니다.
  if (newLines.some(l => l.tag === 'action' || l.tag === 'defend' || (typeof l.text === 'string' && /^거점(의 이번 라운드 행동이 모두| 추가 행동 가능| 행동 게이지)/.test(l.text)))) {
    const el = document.getElementById('pubLog');
    logSeenTotal[view] = logTotal;
    logRevealQueue[view] = [];
    scrollKeepingView(el, () => { el.innerHTML = formatLogHtml(fullLog); });
    return;
  }
  logSeenTotal[view] = logTotal;
  logRevealQueue[view].push(...splitLogIntoSections(newLines));
  processLogRevealQueue(view);
}

function processLogRevealQueue(view) {
  if (logRevealBusy[view]) return;
  if (logView !== view) { logRevealQueue[view] = []; return; }  // 지금 안 보이는 탭이면 큐를 비웁니다.
  const queue = logRevealQueue[view];
  if (!queue.length) return;
  logRevealBusy[view] = true;
  const section = queue.shift();
  const el = document.getElementById('pubLog');
  scrollKeepingView(el, () => { el.innerHTML += formatLogHtml(section); });
  setTimeout(() => {
    logRevealBusy[view] = false;
    processLogRevealQueue(view);
  }, LOG_SECTION_DELAY_MS);
}

function renderCurrentLog() {
  const el = document.getElementById('pubLog');
  const log = logView === 'operator' ? lastOperatorLog : lastPublicLog;
  const total = logView === 'operator' ? lastOperatorLogTotal : lastPublicLogTotal;
  el.innerHTML = formatLogHtml(log);
  el.scrollTop = el.scrollHeight;
  logSeenTotal[logView] = total;
  logRevealQueue[logView] = [];
  logRevealBusy[logView] = false;
  logInitialized[logView] = true;
}

function setLogView(view) {
  logView = view;
  document.getElementById('logTabPublic').classList.toggle('active', view === 'public');
  document.getElementById('logTabOperator').classList.toggle('active', view === 'operator');
  renderCurrentLog();
}

// GM(비밀번호 입장)일 때만 로그 전환 탭 + 수식 설정 톱니를 보여줍니다. 일반 러너 화면에는
// 둘 다 표시되지 않습니다.
function refreshLogViewControls() {
  const show = myControlInfo(lastBattleForPanel).scope === 'all';
  const tabs = document.getElementById('logViewTabs');
  const gear = document.getElementById('formulaGearBtn');
  if (tabs) tabs.style.display = show ? '' : 'none';
  if (gear) gear.style.display = show ? '' : 'none';
  const head = document.getElementById('logToolsHead');
  if (head) head.style.display = show ? '' : 'none';
  if (!show) {
    logView = 'public';
    closeFormulaPanel();
  }
}

let formulaFields = [];
let formulaCategories = [];
let formulaActiveCategory = null;
let formulaValues = {};  // key -> 입력칸 현재 값(문자열). 탭을 옮겨도 값이 안 사라지도록 여기 보관합니다.

function toggleFormulaPanel() {
  if (myControlInfo(lastBattleForPanel).scope !== 'all') return;
  document.getElementById('formulaModal').style.display = 'flex';
  socket.emit('get_formulas', {});
}

function closeFormulaPanel() {
  document.getElementById('formulaModal').style.display = 'none';
}

// 지금 화면에 그려진 입력칸 값을 formulaValues에 반영합니다 - 탭을 옮기거나 저장하기 직전에
// 호출해서, 안 보이는 탭에 입력해둔 값이 사라지지 않게 합니다.
function captureFormulaInputs() {
  formulaFields.forEach(f => {
    const input = document.getElementById('f_' + f.key);
    if (input) formulaValues[f.key] = input.value;
  });
}

function renderFormulaCategoryTabs() {
  const el = document.getElementById('formulaCategoryTabs');
  el.innerHTML = formulaCategories.map(c =>
    `<button class="sort-btn ${c.key === formulaActiveCategory ? 'active' : ''}" onclick="setFormulaCategory('${c.key}')">${c.label}</button>`
  ).join('');
  const activeCat = formulaCategories.find(c => c.key === formulaActiveCategory);
  document.getElementById('formulaCategoryDesc').textContent = activeCat ? activeCat.desc : '';
}

function setFormulaCategory(key) {
  captureFormulaInputs();
  formulaActiveCategory = key;
  renderFormulaCategoryTabs();
  renderFormulaFields();
}

function formulaFieldInputHtml(f) {
  if (f.widget === 'select') {
    const opts = (f.options || []).map(opt =>
      `<option value="${opt}" ${String(opt) === String(formulaValues[f.key]) ? 'selected' : ''}>${opt}</option>`
    ).join('');
    return `<select id="f_${f.key}" style="width:100px;">${opts}</select>`;
  }
  const step = f.step != null ? f.step : (f.type === 'float' ? '0.01' : '1');
  return `<input id="f_${f.key}" type="number" step="${step}" value="${formulaValues[f.key]}" style="width:100px;">`;
}

function renderFormulaFields() {
  const el = document.getElementById('formulaFields');
  const fields = formulaFields.filter(f => f.category === formulaActiveCategory);
  el.innerHTML = fields.map(f => `
    <div class="fml-field">
      <div class="fml-top"><label for="f_${f.key}">${f.label}</label>${formulaFieldInputHtml(f)}</div>
      <div class="fml-desc">${f.desc}</div>
    </div>
  `).join('');
}

function saveFormulas() {
  captureFormulaInputs();
  socket.emit('save_formulas', { values: formulaValues });
}

socket.on('formulas', (d) => {
  formulaFields = d.fields;
  formulaCategories = d.categories || [];
  formulaValues = {};
  formulaFields.forEach(f => { formulaValues[f.key] = f.value; });
  if (!formulaActiveCategory || !formulaCategories.some(c => c.key === formulaActiveCategory)) {
    formulaActiveCategory = formulaCategories[0] ? formulaCategories[0].key : null;
  }
  renderFormulaCategoryTabs();
  renderFormulaFields();
});

socket.on('formulas_saved', (d) => {
  const el = document.getElementById('formulaSaveMsg');
  el.textContent = d.message;
  setTimeout(() => { el.textContent = ''; }, 4000);
});

let lastRosterDetail = [];
var lastOnlineDevices = {};  // 운영진 전용 : 캐릭터 이름 → 접속 기기 목록
var DEVICE_ICON = { pc: 'fa-desktop', tablet: 'fa-tablet-screen-button', mobile: 'fa-mobile-screen-button' };
var DEVICE_NAME = { pc: 'PC', tablet: '태블릿', mobile: '모바일' };
function deviceBadgesHtml(name) {
  const list = (lastOnlineDevices || {})[name] || [];
  return list.map(d => `<span class="ui-dev" data-tip="${DEVICE_NAME[d.type] || ''} · ${mailEsc(d.os || '')} · ${mailEsc(d.browser || '')}"><i class="fa-solid ${DEVICE_ICON[d.type] || 'fa-desktop'}"></i><em>${mailEsc(d.os || '')}</em></span>`).join('');
}  // GM 전용 - 등록된 캐릭터 전체 정보(전투에 없는 캐릭터의 마이페이지용)
// 운영진 화면 : 운영진 상태(gm_state)의 전투 정보로 몹의 정확한 체력을 채워요(공개 상태보다 조금 늦게 와요)
var gmFullBattle = null;
function fillGmMobHp(b) {
  if (!b || !gmFullBattle || myControlInfo(b).scope !== 'all') return b;
  const full = {}; [...(gmFullBattle.team_a || []), ...(gmFullBattle.team_b || [])].forEach(c => { full[c.name] = c; });
  const fix = list => (list || []).map(c => c.hp_hidden && full[c.name] ? { ...c, current_hp: full[c.name].current_hp, max_hp: full[c.name].max_hp, hp_hidden: false } : c);
  return { ...b, team_a: fix(b.team_a), team_b: fix(b.team_b) };
}
socket.on('gm_state', (state) => {
  gmFullBattle = state.battle || null;
  if (lastBattleForPanel && [...(lastBattleForPanel.team_a || []), ...(lastBattleForPanel.team_b || [])].some(c => c.hp_hidden)) {
    lastBattleForPanel = fillGmMobHp(lastBattleForPanel); renderBattle(lastBattleForPanel);
  }
  lastRosterDetail = state.roster_detail || [];
  lastOnlineDevices = state.online_devices || {};
  if (document.getElementById('userInfoModal') && document.getElementById('userInfoModal').style.display === 'flex') renderUserInfoList();
  lastShopRequests = state.shop_requests || [];
  // LOOP 방은 공개 상태에서 상점 · 명단을 빼고 보내요 : 운영진 화면은 운영진 상태의 것을 써요.
  if (BATTLE_TYPE === 'play') {
    if (state.shop) lastShop = state.shop;
    if (state.roster) lastRoster = state.roster;
    if (state.roster_mypage) lastRosterMypage = state.roster_mypage;
  }
  renderShop();
  lastOperatorLog = state.operator_log || [];
  lastOperatorLogTotal = state.operator_log_total != null ? state.operator_log_total : lastOperatorLog.length;
  if (logView === 'operator') {
    revealNewLogLines('operator', lastOperatorLog, lastOperatorLogTotal);
  } else {
    logSeenTotal.operator = lastOperatorLogTotal;
    logRevealQueue.operator = [];
  }
  refreshLogViewControls();
});

// 채팅창/전투 관전/아군회의 탭에 새 채팅이 쌓이면(지금 보고 있는 탭이 아닐 때) 탭 모서리에
// 빨간 점으로 표시합니다.
let unreadChat = { general: false, spectator: false, team: false, log: false };
// 지금 화면에 보이는 Member 패널 탭 ('chat' | 'log' | 'meeting' | 'spectate')
let currentMemberView = 'chat';
const CHAT_TAB_TO_VIEW = { general: 'chat', team: 'meeting', spectator: 'spectate' };
function chatTabFor(entry) {
  if (entry.category === 'presence') return null;
  if (entry.category === 'team') return canSeeTeamMeeting(entry) ? 'team' : null;
  if (entry.category === 'spectator') return 'spectator';
  return 'general';
}
function updateUnreadBadges() {
  document.getElementById('unreadDotChat').classList.toggle('show', unreadChat.general);
  document.getElementById('unreadDotSpectate').classList.toggle('show', unreadChat.spectator);
  document.getElementById('unreadDotMeeting').classList.toggle('show', unreadChat.team);
  const logDot = document.getElementById('unreadDotLog');
  if (logDot) logDot.classList.toggle('show', unreadChat.log);
  const mDot = document.getElementById('mChatDot');
  if (mDot) mDot.classList.toggle('on', mobileChatUnread);
  const mDot2 = document.getElementById('mChatDot2'); if (mDot2) mDot2.classList.toggle('on', mobileChatUnread);
}

// ==================================================================
// 뒤로 가기(아이폰 스와이프 · 안드로이드 뒤로 버튼) : 사이트를 나가지 않고 맨 위 화면부터 하나씩 닫습니다.
// 화면을 열 때마다 기록(history)을 하나 쌓고, 뒤로 가기가 오면 그 화면을 닫습니다.
// ==================================================================
function backLayers() {
  const shown = id => { const el = document.getElementById(id); return !!el && getComputedStyle(el).display !== 'none'; };
  const L = [];
  const dlg = document.getElementById('uiDialog');
  if (dlg && dlg.style.display === 'flex' && uiDialogResolve) L.push(() => uiDialogResolve(null));
  if (typeof homeMenu !== 'undefined' && homeMenu.open) L.push(() => closeHomeMenu());
  const small = [['wmReader', () => { document.getElementById('wmReader').style.display = 'none'; }],
    ['dormAddModal', () => closeDormAddModal()], ['dormCreditModal', () => { document.getElementById('dormCreditModal').style.display = 'none'; }],
    ['mapBgModal', () => closeMapBgModal()], ['soundModal', () => closeSoundSettings()], ['sceneModal', () => closeSceneModal()],
    ['trackBgModal', () => closeTrackBgModal()], ['formulaModal', () => closeFormulaPanel()], ['chatTabSettingsModal', () => closeChatTabSettings()],
    ['newsSheet', () => { document.getElementById('newsSheet').style.display = 'none'; }]];
  small.forEach(([id, fn]) => { if (shown(id)) L.push(fn); });
  if (shown('mailModal') && typeof mailOpenId !== 'undefined' && mailOpenId) L.push(() => { mailOpenId = null; renderMail(); });
  [['userInfoModal', () => closeUserInfoPanel()], ['myPageModal', () => closeMyPage()], ['shopModal', () => closeShop()],
   ['mailModal', () => closeMail()], ['noticeModal', () => closeNotices()]].forEach(([id, fn]) => { if (shown(id)) L.push(fn); });
  if (document.body.classList.contains('m-chat-open')) L.push(() => toggleMobileChat(false));
  if (shown('dormModal')) {
    if (typeof dormView !== 'undefined' && dormView === 'room') L.push(() => dormLeaveRoom());
    else if (typeof dormView !== 'undefined' && dormView !== 'halls') L.push(() => setDormView('halls'));
    else if (!IS_LOUNGE) L.push(() => closeDorm());
  }
  if (typeof worldOpen === 'function' && worldOpen()) L.push(() => closeWorldMap());
  if (typeof opsOpen === 'function' && opsOpen()) L.push(() => closeOps());
  return L;
}
var backDepth = 0, backSkip = 0;
function backSync() {
  if (!window.history || !history.pushState) return;
  // +1 : 맨 바닥 화면에서 실수로 뒤로 가도 바로 나가지 않도록 한 칸을 더 깔아 둡니다.
  const n = backLayers().length + 1;
  while (backDepth < n) { history.pushState({ etLayer: backDepth + 1 }, ''); backDepth++; }
  // X 버튼 · 탭으로 닫아서 남은 기록은 조용히 되돌립니다.
  if (backDepth > n) { const d = backDepth - n; backDepth = n; backSkip += d; history.go(-d); }
}
window.addEventListener('popstate', () => {
  if (backSkip > 0) { backSkip--; return; }
  if (backDepth > 0) backDepth--;
  const top = backLayers()[0];
  if (top) { try { top(); } catch (e) {} }
  else if (typeof showShopToast === 'function') showShopToast('한 번 더 뒤로 가면 사이트에서 나갑니다.');
  // 닫기에 확인창이 뜨는 경우(저장 안 한 꾸미기 등) 등은 다음 터치 때 다시 맞춥니다.
});
// 화면은 누르기(탭 · 클릭)로 열리므로, 누를 때마다 열린 화면 수와 기록을 맞춥니다(사용자 동작 직후라 브라우저가 기록을 인정해요).
['click', 'keyup'].forEach(ev => document.addEventListener(ev, () => setTimeout(backSync, 60), true));

// 세로 태블릿(폭 900px 이하)에서는 카드 화면이 기본이고, 채팅은 사이드바 버튼으로 따로 엽니다.
var mobileChatUnread = false;
function isMobileChatHidden() {
  return window.matchMedia('(max-width:900px)').matches && !document.body.classList.contains('m-chat-open');
}
// 화면 바꿈(탭 전환) 한 번 동안 애니메이션 · 전환 효과를 꺼요 : 화면이 중간 단계를 거쳐 보이며 어지럽지 않게
function viewSwap() {
  document.body.classList.add('view-swap');
  clearTimeout(viewSwap._t);
  viewSwap._t = setTimeout(() => document.body.classList.remove('view-swap'), 260);
}
function toggleMobileChat(force) {
  const open = typeof force === 'boolean' ? force : !document.body.classList.contains('m-chat-open');
  // 지도 · 운영 · LOOP 편집 화면이 덮고 있으면 닫아요(기록 · 채팅이 그 화면 뒤에 가려서 안 열리던 문제).
  // 기록을 먼저 열고 같은 순간에 닫아, 중간에 LOOP 화면이 비치지 않게(애니메이션도 이번 한 번은 끔)
  const covered = open && !IS_LOUNGE && ((typeof worldOpen === 'function' && worldOpen()) || (typeof opsOpen === 'function' && opsOpen()) || document.body.classList.contains('view-loopadmin'));
  // LOOP 첫 소개 글이 떠오르는 중이면 바로 끝내요(소개 동안은 기록판이 숨어 있어서, 기록 대신 LOOP 화면이 남아 보이던 문제)
  if (open && typeof loopIntroSettle === 'function' && document.body.classList.contains('pl-intro-on')) loopIntroSettle();
  if (covered) { viewSwap(); document.body.classList.add('m-chat-instant'); }
  if (!open) document.body.classList.remove('m-chat-instant');
  document.body.classList.toggle('m-chat-open', open);
  if (covered) {
    if (typeof worldOpen === 'function' && worldOpen()) closeWorldMap(true);
    if (typeof opsOpen === 'function' && opsOpen()) closeOps();
    if (document.body.classList.contains('view-loopadmin') && typeof closeLoopAdmin === 'function') closeLoopAdmin();
  }
  if (open) {
    mobileChatUnread = false;
    updateUnreadBadges();
    const el = document.getElementById('chatLog');
    if (el) el.scrollTop = el.scrollHeight;
  }
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.body.classList.contains('m-chat-open')
      && !document.querySelector('.modal-overlay[style*="flex"]')) toggleMobileChat(false);
});

function setChatFilter(filter) {
  chatFilter = filter;
  unreadChat[filter] = false;
  updateUnreadBadges();
  renderChatFiltered();
}
setChatFilter('general');

// 채팅창/로그창/회의창/전투 관전 - Member 패널 상단 4탭. chatLog(채팅 로그)는 실제로는
// 하나뿐이라, 탭을 옮길 때마다 해당 탭의 마운트 지점으로 DOM을 그대로 옮겨서 재사용합니다.
// 입력창은 탭과 무관하게 항상 같은 자리(패널 맨 아래)에 고정되어 계속 보입니다.
const MEMBER_TAB_TITLES = { chat: 'Chat', log: 'Log', meeting: 'Council', spectate: 'Spectators' };
// 탭마다 보던 스크롤 자리를 기억 : 다시 오면 보던 자리 그대로, 맨 아래(최신)를 보고 있었거나 처음 열면 최신 대화로.
const memberScroll = {};
function setMemberTab(view) {
  const prevView = typeof currentMemberView !== 'undefined' ? currentMemberView : null;
  const prevEl = prevView ? activeChatScroller() : null;
  if (prevView && prevEl && prevEl.offsetParent) {
    memberScroll[prevView] = { top: prevEl.scrollTop, bottom: prevEl.scrollHeight - prevEl.scrollTop - prevEl.clientHeight < 40 };
  }
  currentMemberView = view;
  setTimeout(updateJumpBottom, 0);  // 탭을 바꾸면 그 탭의 스크롤 위치로 '맨 아래로' 버튼을 다시 판단
  const titleEl = document.getElementById('memberTitle');
  if (titleEl) titleEl.textContent = MEMBER_TAB_TITLES[view] || 'Chat';
  // 로그창에는 검색이 없으므로 검색 모드를 끄고 아이콘도 숨깁니다.
  if (view === 'log' && typeof toggleChatSearch === 'function') toggleChatSearch(false);
  const sb = document.getElementById('chatSearchBtn');
  if (sb) sb.style.display = view === 'log' ? 'none' : '';
  // 지금 연 탭의 안 읽음 표시는 지웁니다.
  const readKey = { chat: 'general', meeting: 'team', spectate: 'spectator', log: 'log' }[view];
  if (readKey) { unreadChat[readKey] = false; updateUnreadBadges(); }
  document.getElementById('memberTabBtnChat').classList.toggle('active', view === 'chat');
  document.getElementById('memberTabBtnLog').classList.toggle('active', view === 'log');
  document.getElementById('memberTabBtnMeeting').classList.toggle('active', view === 'meeting');
  document.getElementById('memberTabBtnSpectate').classList.toggle('active', view === 'spectate');
  document.getElementById('memberTabChat').classList.toggle('active', view === 'chat');
  document.getElementById('memberTabLog').classList.toggle('active', view === 'log');
  document.getElementById('memberTabMeeting').classList.toggle('active', view === 'meeting');
  document.getElementById('memberTabSpectate').classList.toggle('active', view === 'spectate');

  const mountId = view === 'meeting' ? 'chatLogMountMeeting' : view === 'spectate' ? 'chatLogMountSpectate' : 'chatLogMountChat';
  document.getElementById(mountId).appendChild(document.getElementById('chatLog'));
  refreshChatSendEnabled();

  if (view === 'meeting') {
    unreadChat.team = false;
    updateUnreadBadges();
    setChatFilter('team');
  } else if (view === 'spectate') {
    unreadChat.spectator = false;
    updateUnreadBadges();
    setChatFilter('spectator');
  } else if (view === 'chat' && chatFilter !== 'general') {
    setChatFilter('general');
  }
  const restore = () => {
    const el = activeChatScroller(); if (!el) return;
    const st = memberScroll[view];
    el.scrollTop = !st || st.bottom ? el.scrollHeight : Math.min(st.top, el.scrollHeight);
    updateJumpBottom();
  };
  restore(); requestAnimationFrame(restore);
}
setMemberTab('chat');

// 채팅창 = 참여 인원(참가자·운영진)만, 전투 관전 = 미참여(관전) 인원만, 아군 회의 = 팀 전용.
// 입장/퇴장 기록(presence)은 어디에도 남기지 않습니다.
// 아군 회의는 내 캐릭터의 팀 회의만 보입니다. GM(비밀번호 입장)만 양 팀 회의를 모두 봅니다.
// (같은 화면에서 다른 팀 캐릭터로 다시 로그인해도 이전 팀 회의가 남아 보이지 않도록 매번 확인합니다.)
function canSeeTeamMeeting(entry) {
  const control = myControlInfo(lastBattleForPanel);
  if (control.scope === 'all') return true;
  if (control.scope === 'character') return entry.team === control.character.team;
  return false;
}

function matchesFilter(entry) {
  if (entry.category === 'presence') return false;
  if (chatFilter === 'team') return entry.category === 'team' && canSeeTeamMeeting(entry);
  if (chatFilter === 'spectator') return entry.category === 'spectator';
  return entry.category === 'player' || entry.category === 'operator' || entry.category === 'round' || entry.category === 'skill';
}

// 운영진이 전투 관전/아군 회의 탭을 켜둘지/이름을 바꿀지 고르는 설정 (방 전체 공통 - public_state.chat_tabs).
let chatTabsEnabled = { spectator: true, team: true };
let chatTabLabels = { spectator: '전투 관전', team: '아군 회의' };

function applyChatTabLabels() {
  document.getElementById('memberTabSpectateLabel').textContent = chatTabLabels.spectator;
  document.getElementById('memberTabMeetingLabel').textContent = chatTabLabels.team;
}

function renderChatTabVisibility() {
  document.getElementById('memberTabBtnSpectate').style.display = chatTabsEnabled.spectator ? '' : 'none';
  document.getElementById('memberTabBtnMeeting').style.display = chatTabsEnabled.team ? '' : 'none';
  // 탭 자체가 꺼졌는데 지금 그 탭을 보고 있다면 채팅창 탭으로 돌려보냅니다.
  if (!chatTabsEnabled.spectator && document.getElementById('memberTabSpectate').classList.contains('active')) {
    setMemberTab('chat');
  }
  if (!chatTabsEnabled.team && document.getElementById('memberTabMeeting').classList.contains('active')) {
    setMemberTab('chat');
  }
}

function toggleGmMenu(ev) {
  ev.stopPropagation();
  document.getElementById('gmMenu').classList.toggle('open');
}
function closeGmMenu() { document.getElementById('gmMenu').classList.remove('open'); }
document.addEventListener('click', (e) => { if (!e.target.closest || !e.target.closest('.gm-menu-wrap')) closeGmMenu(); });

function toggleChatTabSettings() {
  if (myControlInfo(lastBattleForPanel).scope !== 'all') return;
  document.getElementById('chatTabCfgSpectator').checked = chatTabsEnabled.spectator;
  document.getElementById('chatTabNameSpectator').value = chatTabLabels.spectator;
  document.getElementById('chatTabCfgTeam').checked = chatTabsEnabled.team;
  document.getElementById('chatTabNameTeam').value = chatTabLabels.team;
  document.getElementById('chatTabSettingsModal').style.display = 'flex';
}

function closeChatTabSettings() {
  document.getElementById('chatTabSettingsModal').style.display = 'none';
}

function onChatTabConfigChange() {
  socket.emit('set_chat_tabs', {
    tabs: {
      spectator: document.getElementById('chatTabCfgSpectator').checked,
      team: document.getElementById('chatTabCfgTeam').checked,
    },
    labels: {
      spectator: document.getElementById('chatTabNameSpectator').value,
      team: document.getElementById('chatTabNameTeam').value,
    },
  });
}

// GM(비밀번호 입장)일 때만 채팅 탭 설정 톱니를 보여줍니다.
function refreshChatTabSettingsVisibility() {
  const gear = document.getElementById('chatTabSettingsBtn');
  const isGm = myControlInfo(lastBattleForPanel).scope === 'all';
  // 채팅 탭 설정은 전투 설정(운영 페이지)으로 옮겼어요 : 채팅창 머리에는 로그 내려받기 버튼만
  if (gear) gear.style.display = 'none';
  const dl = document.getElementById('chatLogDlBtn');
  if (dl) dl.style.display = '';
}

// 아군 회의(팀 전용 채팅)는 새는 걸 막으려고 서버가 공용 스냅샷(room.chat_log)에는 안
// 남기고 실시간 전송으로만 보냅니다 - 그래서 매 행동마다 오는 공용 스냅샷으로 lastChat을
// 통째로 덮어쓰면 방금 받은 아군 회의 내용이 사라져버립니다. lastTeamChat에 따로 모아뒀다가
// 매번 다시 합쳐줍니다.
let lastTeamChat = [];

// '이전 대화 더보기'로 받아 둔 예전 대화(서버가 매번 보내는 최근 200개보다 앞의 것)
function renderChat(chat) {
  lastPublicChat = chat || [];
  // 공용 채팅은 서버 순서 그대로(예전 대화 + 최근 대화), 아군 회의는 시각에 맞춰 사이사이에 끼워 넣습니다.
  const seen = new Set(lastPublicChat.map(e => e.id));
  const pub = olderChat.filter(e => !seen.has(e.id)).concat(lastPublicChat);
  const merged = pub.slice();
  lastTeamChat.forEach(t => {
    let i = merged.length;
    while (i > 0 && (merged[i - 1].time || '') > (t.time || '')) i--;
    merged.splice(i, 0, t);
  });
  lastChat = merged;
  renderChatFiltered();
}
function chatHasOlder() {
  if (olderChatHasMore === false) return false;
  return lastChatTotal > lastPublicChat.length + olderChat.length;
}
function loadOlderChat() {
  if (olderChatLoading) return;
  const first = olderChat[0] || lastPublicChat[0];
  if (!first) return;
  olderChatLoading = true;
  socket.emit('chat_older', { before: first.id });
}
socket.on('chat_older_result', (d) => {
  olderChatLoading = false;
  const el = document.getElementById('chatLog');
  const fromBottom = el.scrollHeight - el.scrollTop;   // 위에 대화가 붙어도 보던 자리를 그대로 지킵니다
  olderChat = (d.entries || []).concat(olderChat);
  olderChatHasMore = !!d.has_more;
  renderChat(lastPublicChat);
  el.scrollTop = el.scrollHeight - fromBottom;
});

// 새 글/로그가 추가돼도 사용자가 보던 위치를 유지합니다. 맨 아래를 보고 있었을 때만(또는 forceBottom)
// 새 내용을 따라 아래로 내려가고, 위로 올려서 읽던 중이면 그 화면 그대로 둡니다.
function scrollKeepingView(el, mutate, forceBottom) {
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  const prev = el.scrollTop, prevH = el.scrollHeight;
  mutate();
  el.scrollTop = (forceBottom || atBottom) ? el.scrollHeight : prev;
  // 위로 올려 읽는 중에 새 글이 붙으면 '맨 아래로' 버튼에 새 글 점을 켭니다.
  if (!forceBottom && !atBottom && el.scrollHeight > prevH) jumpNewMark(el);
  updateJumpBottom();
}
// ---- 채팅창 · 로그창 '맨 아래로' 버튼 : 위로 올려 읽는 중일 때만 보이고, 누르면 맨 아래로 ----
function activeChatScroller() {
  const logTab = document.getElementById('memberTabLog');
  return logTab && logTab.classList.contains('active') ? document.getElementById('pubLog') : document.getElementById('chatLog');
}
function ensureJumpBottomBtn() {
  let b = document.getElementById('jumpBottomBtn');
  if (b) return b;
  const body = document.querySelector('.member-panel .member-body');
  if (!body) return null;
  b = document.createElement('button');
  b.id = 'jumpBottomBtn'; b.className = 'jump-bottom'; b.type = 'button';
  b.setAttribute('aria-label', '맨 아래로'); b.dataset.tip = '맨 아래로';
  b.innerHTML = '<i class="fa-solid fa-arrow-down"></i><span class="dot"></span>';
  b.onclick = () => { const el = activeChatScroller(); if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); b.classList.remove('new'); };
  body.appendChild(b);
  ['chatLog', 'pubLog'].forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener('scroll', updateJumpBottom, { passive: true }); });
  return b;
}
function jumpNewMark(el) { const b = ensureJumpBottomBtn(); if (b && el === activeChatScroller()) b.classList.add('new'); }
function updateJumpBottom() {
  const b = ensureJumpBottomBtn(); if (!b) return;
  const el = activeChatScroller();
  const away = !!(el && el.offsetParent && el.scrollHeight - el.scrollTop - el.clientHeight > 120);
  b.classList.toggle('show', away);
  if (!away) b.classList.remove('new');
}

function renderChatFiltered() {
  const el = document.getElementById('chatLog');
  const shown = lastChat.filter(e => matchesFilter(e) && matchesChatSearch(e));
  // 맨 위 : 더 예전 대화가 있으면 '이전 대화 더보기', 다 보이고 있으면 '대화의 처음이에요'
  const more = chatSearchQuery || !shown.length ? ''
    : chatHasOlder() ? `<button class="chat-more" onclick="loadOlderChat()"><i class="fa-solid fa-clock-rotate-left"></i>이전 대화 더보기</button>`
    : `<div class="chat-start">대화의 처음이에요</div>`;
  scrollKeepingView(el, () => { el.innerHTML = more + shown.map(fmtChat).join(''); markChatContinuations(el); }, !!chatSearchQuery);
  updateChatSearchCount(shown.length);
}

// 같은 사람이 3분 안에 이어서 쓴 글은 프로필·이름을 생략하고 바로 아래에 붙여 보여줍니다.
function chatSecondsOf(t) {
  const p = (t || '').split(':').map(Number);
  return p.length >= 2 && !p.some(isNaN) ? p[0] * 3600 + p[1] * 60 + (p[2] || 0) : null;
}
function markChatContinuation(line) {
  const prev = line && line.previousElementSibling;
  if (!line || !line.dataset.who || !prev || !prev.dataset || !prev.dataset.who) return;
  if (line.classList.contains('is-round') || prev.classList.contains('is-round')) return;
  const a = chatSecondsOf(prev.dataset.t), b = chatSecondsOf(line.dataset.t);
  const close = a != null && b != null && b >= a && b - a <= 180;
  line.classList.toggle('cont', prev.dataset.who === line.dataset.who && close);
}
function markChatContinuations(el) { [...el.children].forEach(markChatContinuation); }

// 채팅에서 말한 사람의 프로필(색상/이미지). 전투 중인 캐릭터면 실시간 값을, 아니면 등록 DB 값을 씁니다.
function chatProfileOf(nickname) {
  const c = lastAllForCards.find(x => x.name === nickname);
  if (c) return { color: c.color || null, avatar_url: c.avatar_url || null };
  return lastRosterProfiles[nickname] || { color: null, avatar_url: null };
}

function formatChatTime(timeStr) {
  // timeStr: 서버가 보내는 "HH:MM:SS"(24시간제) 문자열을 "PM.03:07"처럼 초 없이 표시합니다.
  const parts = (timeStr || '').split(':');
  const h = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10) || 0;
  if (isNaN(h)) return timeStr;
  return etTime(h, m);
}

function fmtChat(entry) {
  entry = { ...entry, text: siteLabelize(stripLegacyEmoji(entry.text)), nickname: stripLegacyEmoji(entry.nickname) };
  // 전투 진행 안내(✶ Round N / ▶ 선공 단계 등)는 아바타 없이 포인트 컬러로 한 줄 표시합니다.
  const canDel = entry.id && myControlInfo(lastBattleForPanel).scope === 'all';
  const delBtn = canDel ? `<button class="chat-del" onclick="deleteChatMessage('${entry.id}')"><i class="fa-solid fa-trash-can"></i></button>` : '';
  const idAttr = entry.id ? ` data-chat-id="${entry.id}"` : '';
  if (entry.category === 'skill') {
    // 스킬 사용 기록 : 다른 채팅 줄과 같은 자리(프로필 · 이름 · 시간) 아래에 작은 스킬 카드, 누르면 컷인 다시 보기
    const c = typeof sfxCharacter === 'function' ? sfxCharacter(entry.nickname) : null;
    const who = c ? displayNameOf(c) : entry.nickname;
    const prof = chatProfileOf(entry.nickname);
    const av = prof.avatar_url ? `<div class="chat-avatar" style="background-image:url('${prof.avatar_url}');"></div>`
      : `<div class="chat-avatar"></div>`;
    // 컷인이 있거나 격자 지도(✶ 다시 보기)가 있으면 ▶ 버튼을 둡니다.
    const can = !!entry.fx || !!document.getElementById('gridSection');
    return `<div class="chat-line is-skill"${idAttr}>${av}
      <div class="chat-body"><div class="chat-meta"><b${prof.color ? ` style="color:${prof.color};"` : ''}>${shopEsc(who || '')}</b><span class="time">${formatChatTime(entry.time)}</span></div>
        <div class="chat-text">${shopEsc(entry.text || ('【' + (entry.skill || '') + '】'))}${entry.fx && entry.fx.title ? ' ' + shopEsc(entry.fx.title) : ''}${entry.uses_left > 0 ? ` (잔여 ${entry.uses_left}회)` : ''}${can ? ` <button type="button" class="sr-play" onclick="replaySkillCutin('${entry.id}')" data-tip="다시 보기"><i class="fa-solid fa-play"></i></button>` : ''}</div></div>${delBtn}</div>`;
  }
  if (entry.category === 'round') {
    const main = /^round\s*\d+/i.test((entry.text || '').trim());
    return `<div class="chat-line is-round${main ? ' is-round-main' : ''}"${idAttr}>${roundHeadHtml(entry.text, highlightChat)}${delBtn}</div>`;
  }
  const isCommand = (entry.text || '').startsWith('[스킬:') || (entry.text || '').startsWith('[액션:') || (entry.text || '').startsWith('[행동:');
  const cls = entry.category === 'system' ? 'is-system' : (isCommand ? 'is-command' : '');
  const isStar = entry.role === 'system' || entry.role === 'gm' || (entry.nickname || '').trim().toLowerCase() === 'gm';
  const profile = chatProfileOf(entry.nickname);
  const dot = isStar
    ? `<div class="chat-dot chat-star">✶</div>`
    : (profile.avatar_url
      ? `<div class="chat-avatar" style="background-image:url('${profile.avatar_url}');"></div>`
      : `<div class="chat-avatar"></div>`);
  // GM은 양 팀 아군 회의를 같은 탭에서 같이 보므로, 어느 팀 회의인지 작게 표시해줍니다.
  const teamTag = entry.category === 'team' && myControlInfo(lastBattleForPanel).scope === 'all'
    ? ` <span style="color:var(--muted); font-size:12px;">(${entry.team === 'A' ? '1팀' : '2팀'} 회의)</span>`
    : '';
  const who = shopEsc(`${entry.nickname || ''}|${entry.category || ''}|${entry.team || ''}`);
  return `<div class="chat-line ${cls}"${idAttr} data-who="${who}" data-t="${shopEsc(entry.time || '')}">
    ${dot}
    <div class="chat-body"><div class="chat-meta"><b${!isStar && profile.color ? ` style="color:${profile.color};"` : ''}>${highlightChat(entry.nickname)}</b>${teamTag}<span class="time">${formatChatTime(entry.time)}</span></div>
    <div class="chat-text">${highlightChat(entry.text)}</div></div>
    ${delBtn}
  </div>`;
}

// 채팅 스킬 기록의 ▶ : 컷인(있으면)을 다시 보여주고, 지도 칸 위 ✶도 다시 띄웁니다(턴이 지나도 다시 볼 수 있게).
function replaySkillCutin(id) {
  const e = (lastChat || []).find(x => x.id === id);
  if (!e) return;
  if (e.fx) {
    const c = typeof sfxCharacter === 'function' ? sfxCharacter(e.fx.actor) : null;
    showSkillCutin({ ...e.fx, actor: c ? displayNameOf(c) : e.fx.actor });
  }
  popSkillMark(e.nickname, e.fx ? 3000 : 0);
}

function appendChat(entry) {
  lastChat.push(entry);
  if (entry.category === 'team') {
    lastTeamChat.push(entry);
    if (lastTeamChat.length > 200) lastTeamChat.shift();
  }
  // 그 글이 들어갈 탭을 지금 보고 있지 않으면(다른 탭/로그창을 보는 중) 탭 이름 옆에 안 읽음 점을 켭니다.
  const tab = chatTabFor(entry);
  if (tab && isMobileChatHidden()) { mobileChatUnread = true; updateUnreadBadges(); }
  if (tab && CHAT_TAB_TO_VIEW[tab] !== currentMemberView) {
    unreadChat[tab] = true;
    updateUnreadBadges();
  }
  if (!matchesFilter(entry) || !matchesChatSearch(entry)) return;
  const el = document.getElementById('chatLog');
  // 내가 보낸 글이면 맨 아래로, 남이 보낸 글이면 보던 위치 유지
  scrollKeepingView(el, () => {
    el.insertAdjacentHTML('beforeend', fmtChat(entry));
    const last = el.lastElementChild;
    if (last) { last.classList.add('fx-chat-in'); markChatContinuation(last); }
  }, entry.nickname === MY_NICKNAME);
}

function sendChat() {
  const onLogTab = document.getElementById('memberTabLog').classList.contains('active');
  if (onLogTab) return;
  const onSpectateTab = document.getElementById('memberTabSpectate').classList.contains('active');
  if (!explicitlyJoined && !onSpectateTab) return;
  const input = document.getElementById('chatInput');
  if (!input.value.trim()) return;
  const payload = { text: input.value };
  // 지금 보고 있는 탭(아군 회의/전투 관전)에 그대로 보이도록, 실제 역할과 무관하게
  // 탭에 맞는 카테고리로 보내달라고 서버에 표시합니다.
  if (chatFilter === 'team') payload.mode = 'team';
  else if (chatFilter === 'spectator') payload.mode = 'spectator';
  socket.emit('chat_message', payload);
  input.value = '';
}

function doAction(type, payload) {
  socket.emit('battle_action', { type, payload });
  // 행동을 보냈으면 격자에서 고른 대상 표시와 켜진 커맨드 블록을 정리합니다(이동은 onGridMoveClick이 따로 정리).
  if (type !== 'move' && selectedGridTargetName) closeGridSelection();
}

function myControlInfo(battle) {
  const nick = (MY_NICKNAME || '').trim();
  if (nick.toLowerCase() === 'gm') return { scope: 'all' };
  if (!battle) return { scope: 'none' };
  const all = [...battle.team_a, ...battle.team_b];
  const mine = all.find(c => c.name === nick);
  if (mine) return { scope: 'character', character: mine };
  return { scope: 'none' };
}

// ------------------------------------------------------------------
// GM(비밀번호로 입장) 전용 진행 컨트롤 - 다음 턴/시간 초과는 모든 전투 유형 공통이고,
// 다이스 굴리기(공성전)/전조 출력(마스 레이드)은 전투 유형에 맞는 것만 표시됩니다.
// ------------------------------------------------------------------
function refreshGmControlPanelVisibility() {
  const panel = document.getElementById('gmControlPanel');
  if (!panel) return;
  const control = myControlInfo(lastBattleForPanel);
  const show = !!lastBattleForPanel && control.scope === 'all';
  if (show) {
    renderSiteDiceStatusGm(lastSiteDice);
    renderTelegraphControls();
  }
}

function rollSiteDice() {
  socket.emit('roll_site_dice', {});
}

function renderSiteDiceStatusGm(siteDice) {
  const el = document.getElementById('siteDiceStatusGm');
  if (!el) return;
  const btn = document.getElementById('siteDiceBtn');
  if (!siteDice || siteDice.value == null || siteDice.stale) {
    el.textContent = '';
    if (btn) btn.dataset.tip = '다이스 · 아직 굴리지 않았어요';
    return;
  }
  const remaining = siteDice.value - siteDice.used;
  el.textContent = `${remaining}/${siteDice.value}`;
  if (btn) btn.dataset.tip = `다이스 · 이번 라운드 ${siteDice.value}회 중 ${siteDice.used}회 사용 (남음 ${remaining}회)`;
}

let telegraphMode = false;               // GM이 칸을 고르는 중인지
let telegraphSelectedCells = new Set();  // GM이 고른 칸 (아직 미공개, "x,y")
let telegraphObstacleCells = new Set();  // 마스 레이드 : 오른쪽 클릭으로 고른 장애물 칸("x,y") - 공개하면 이대로 바뀌어요

function toggleTelegraphMode() {
  telegraphMode = !telegraphMode;
  if (!telegraphMode) { telegraphSelectedCells.clear(); telegraphObstacleCells.clear(); }
  else {
    // 지금 공개된 전조를 고른 칸으로 그대로 불러와요 : 보이는 칸 = 공개하면 나가는 칸
    telegraphSelectedCells = new Set(telegraphRevealedCells);
    telegraphObstacleCells = new Set(((lastBattleForPanel && lastBattleForPanel.obstacles) || []).map(o => `${o.x},${o.y}`));
    selectedGridChar = null; selectedGridTargetName = null; disarmGridCommand();
  }
  renderTelegraphControls();
  renderGrid(lastBattleForPanel, lastAllForCards);
}

function currentGridDims() {
  const battle = lastBattleForPanel;
  return {
    width: battle ? battle.grid_width : GRID_SIZE,
    height: battle ? battle.grid_height : GRID_SIZE,
  };
}

function toggleTelegraphRow(y) {
  const { width } = currentGridDims();
  const keys = [];
  for (let x = 0; x < width; x++) keys.push(`${x},${y}`);
  const allSelected = keys.every(k => telegraphSelectedCells.has(k));
  keys.forEach(k => { if (allSelected) telegraphSelectedCells.delete(k); else telegraphSelectedCells.add(k); });
}

function toggleTelegraphColumn(x) {
  const { height } = currentGridDims();
  const keys = [];
  for (let y = 0; y < height; y++) keys.push(`${x},${y}`);
  const allSelected = keys.every(k => telegraphSelectedCells.has(k));
  keys.forEach(k => { if (allSelected) telegraphSelectedCells.delete(k); else telegraphSelectedCells.add(k); });
}

function onTelegraphCellClick(x, y, evt) {
  // Shift+왼쪽 클릭 : 가로 한 줄 전체를 일괄 선택/해제
  if (evt && evt.shiftKey) {
    toggleTelegraphRow(y);
  } else {
    const key = `${x},${y}`;
    if (telegraphSelectedCells.has(key)) telegraphSelectedCells.delete(key);
    else telegraphSelectedCells.add(key);
  }
  renderTelegraphControls();
  renderGrid(lastBattleForPanel, lastAllForCards);
}

function onTelegraphCellRightClick(x, y, evt) {
  // Shift+오른쪽 클릭 : 세로 한 줄 전체를 일괄 선택/해제 / 오른쪽 클릭 : 장애물 놓기 · 치우기(마스 레이드)
  if (evt) evt.preventDefault();
  if (evt && evt.shiftKey) {
    toggleTelegraphColumn(x);
  } else if (BATTLE_TYPE === 'mass_raid') {
    const key = `${x},${y}`;
    if (telegraphObstacleCells.has(key)) telegraphObstacleCells.delete(key); else telegraphObstacleCells.add(key);
  } else return false;
  renderTelegraphControls();
  renderGrid(lastBattleForPanel, lastAllForCards);
  return false;
}

function revealTelegraph() {
  const cells = [...telegraphSelectedCells].map(k => k.split(',').map(Number));
  const payload = { cells };
  if (BATTLE_TYPE === 'mass_raid') payload.obstacles = [...telegraphObstacleCells].map(k => k.split(',').map(Number));
  socket.emit('telegraph_reveal', payload);
  telegraphMode = false;
  telegraphSelectedCells.clear(); telegraphObstacleCells.clear();
  renderTelegraphControls();
}

function clearTelegraph() {
  socket.emit('telegraph_clear', {});
}

function renderTelegraphControls() {
  const modeBtn = document.getElementById('telegraphModeBtn');
  if (!modeBtn) return;
  const revealBtn = document.getElementById('telegraphRevealBtn');
  const clearBtn = document.getElementById('telegraphClearBtn');
  const status = document.getElementById('telegraphStatus');
  modeBtn.querySelector('.t').textContent = telegraphMode ? '전조 선택 중' : '전조 출력';
  modeBtn.classList.toggle('on', telegraphMode);
  revealBtn.style.display = telegraphMode ? '' : 'none';
  clearBtn.style.display = telegraphRevealedCells.size > 0 ? '' : 'none';
  // 안내는 지도 위 알림줄(라디오 아이콘 옆)에서 합니다.
  status.textContent = '';
  renderGridNotice(lastBattleForPanel);
  status.title = status.textContent;
}

// ------------------------------------------------------------------
// GM(비밀번호로 입장) 전용 행동 실행 패널 - PVP/공성전에서는 격자가 없어 카드 클릭만으로는
// "누구로 행동할지"를 고를 수 없으므로, 행동자/행동/대상을 직접 드롭다운으로 지정합니다.
// ------------------------------------------------------------------
function refreshGmActPanelVisibility() {
  const panel = document.getElementById('gmActPanel');
  if (!panel) return;
  const control = myControlInfo(lastBattleForPanel);
  const isGm = !!lastBattleForPanel && control.scope === 'all';
  // 운영진의 캐릭터 조작 칸(캐릭터 · 행동 · 대상 · 실행)은 항상 보여요 : 마스 레이드도 지도에서 캐릭터를 누르지 않아도 고를 수 있게
  const fields = isGm;
  // GM은 러너용 커맨드 바 대신 이 한 블록(캐릭터·행동·대상·실행 + 진행 버튼)만 씁니다.
  panel.style.display = isGm ? '' : 'none';
  document.getElementById('gmActFields').style.display = fields ? '' : 'none';
  // 마스 레이드 : 지도에서 대상을 골라 행동 칸이 나타나면 진행 버튼과 겹치지 않게 두 줄로
  panel.classList.toggle('wrap-fields', fields && BATTLE_TYPE === 'mass_raid');
  const runnerBar = document.getElementById('commandSendBar');
  if (runnerBar) runnerBar.style.display = isGm ? 'none' : '';
  if (fields) refreshGmActorOptions();
}

function refreshGmActorOptions() {
  const sel = document.getElementById('gmActActor');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = lastAllForCards.map(c => `<option value="${c.name}">${displayNameOf(c)} · ${c.teamLabel === 'A' ? '1팀' : '2팀'}</option>`).join('');
  if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
  refreshGmActTypeOptions();
}

function refreshGmActTypeOptions() {
  const typeSel = document.getElementById('gmActType');
  if (!typeSel) return;
  const actor = lastAllForCards.find(c => c.name === document.getElementById('gmActActor').value);
  if (!actor) { typeSel.innerHTML = ''; refreshGmActTargetOptions(); return; }
  const prevType = typeSel.value;
  const labels = actor.available_actions.filter(label => label !== '이동');
  typeSel.innerHTML = labels.map(label => `<option value="${label}">${label}</option>`).join('');
  if ([...typeSel.options].some(o => o.value === prevType)) typeSel.value = prevType;
  refreshGmActTargetOptions();
}

function refreshGmActTargetOptions() {
  const targetSel = document.getElementById('gmActTarget');
  const multiWrap = document.getElementById('gmActTargetMultiWrap');
  if (!targetSel || !multiWrap) return;
  const actor = lastAllForCards.find(c => c.name === document.getElementById('gmActActor').value);
  const label = document.getElementById('gmActType').value;
  if (!actor || !label) {
    targetSel.innerHTML = '<option value="">-</option>';
    multiWrap.style.display = 'none';
    return;
  }
  const multiCount = MULTI_TARGET_ACTIONS[label];
  let pool;
  if (ENEMY_TARGET_ACTIONS.has(label)) {
    pool = lastAllForCards.filter(c => c.teamLabel !== actor.teamLabel);
  } else if (ALLY_TARGET_ACTIONS.has(label) || multiCount) {
    pool = lastAllForCards.filter(c => c.teamLabel === actor.teamLabel && (label !== '수호' || c.name !== actor.name));
  } else {
    pool = [actor];
  }
  const optsHtml = '<option value="">-</option>' + pool.map(c => `<option value="${c.name}">${displayNameOf(c)}</option>`).join('');

  if (multiCount === 3) {
    multiWrap.style.display = '';
    [targetSel, document.getElementById('gmActTarget2'), document.getElementById('gmActTarget3')].forEach(sel => {
      const prev = sel.value;
      sel.innerHTML = optsHtml;
      if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
    });
    return;
  }
  multiWrap.style.display = 'none';
  const prevTarget = targetSel.value;
  targetSel.innerHTML = optsHtml;
  if ([...targetSel.options].some(o => o.value === prevTarget)) targetSel.value = prevTarget;
}

function submitGmAct() {
  const actor = document.getElementById('gmActActor').value;
  const actorChar = lastAllForCards.find(c => c.name === actor);
  const label = document.getElementById('gmActType').value;
  const type = resolveActionType(label, actorChar ? actorChar.role : null);
  const target = document.getElementById('gmActTarget').value;
  if (!type) return;

  const payloadMap = {
    attack: { attacker: actor, target },
    self_defend: { name: actor },
    defend: { tanker: actor, target: target || actor },
    guard: { tanker: actor, target },
    dodge: { name: actor },
    heal: { healer: actor, target },
    timeout: { name: actor },
    flee: { name: actor },
    defense_settle: { name: actor },
    command: { guardian: actor, target: target || actor },
    swap: { medic: actor, target },
    collapse: { attacker: actor, target },
    emission: { attacker: actor },
    shield: { name: actor, target: target || actor },
    polarize: { name: actor },
    restore: { name: actor, target: target || null },
    declare_defer: { name: actor },
    reflux: {
      name: actor,
      targets: [target, document.getElementById('gmActTarget2').value, document.getElementById('gmActTarget3').value]
        .filter(Boolean),
    },
  };
  doAction(type, payloadMap[type]);
}

// 카드 팝업에서 다중 지정 스킬(환류 등) 버튼을 노출하기 위해, 본인 캐릭터의 available_actions에서
// 그런 스킬이 있으면 사이드 패널 위 카드 그리드 상단에 별도 버튼을 하나 더 그립니다.
function renderMultiSkillTrigger() {
  const battle = lastBattleForPanel;
  if (!battle) return '';
  const actorName = myActorName(battle);
  const actor = lastAllForCards.find(c => c.name === actorName);
  if (!actor) return '';
  // 메딕 '후공' 버튼은 쓰지 않고, 환류 같은 다중 지정 스킬도 아래 행동 블럭(전송 버튼)에서 고릅니다.
  return '';
}

// 1라운드 선공팀 힐러만 "후공" 버튼으로 이번 라운드 행동을 후공 페이즈까지 미루겠다고
// 선언할 수 있습니다(서버가 실제로 상태를 기록함 - perform_declare_defer 참고). 이 선언을
// 해야만 (1) 아직 행동 안 해도 턴 전환이 막히지 않고, (2) 후공 페이즈(상대 턴)에도 힐을
// 쓸 수 있습니다. 2라운드부터는 선공팀이 고정되어 있으므로 이 버튼 자체가 뜨지 않습니다.
function canDeclareDefer(battle, actor) {
  if (actor.role !== '메딕' || actor.has_acted || actor.deferred_this_round) return false;
  if (battle.round_no !== 1) return false;
  const myTeamKr = actor.teamLabel === 'A' ? '1팀' : '2팀';
  return battle.current_turn_team === myTeamKr && battle.current_turn_team === battle.round_first_team;
}

function renderDeferButton(battle, actor) {
  if (!canDeclareDefer(battle, actor)) return '';
  return `<button class="sort-btn" onclick="declareDefer('${actor.name}')">후공</button>`;
}

function declareDefer(actorName) {
  doAction('declare_defer', { name: actorName });
}

function quickAction(type, actorName, targetName) {
  const payloadBuilders = {
    attack: () => ({ attacker: actorName, target: targetName }),
    self_defend: () => ({ name: actorName }),
    defend: () => ({ tanker: actorName, target: targetName || actorName }),
    guard: () => ({ tanker: actorName, target: targetName }),
    dodge: () => ({ name: actorName }),
    heal: () => ({ healer: actorName, target: targetName }),
    timeout: () => ({ name: actorName }),
    flee: () => ({ name: actorName }),
    defense_settle: () => ({ name: actorName }),
    command: () => ({ guardian: actorName, target: targetName || actorName }),
    swap: () => ({ medic: actorName, target: targetName }),
    collapse: () => ({ attacker: actorName, target: targetName }),
    emission: () => ({ attacker: actorName }),
    shield: () => ({ name: actorName, target: targetName || actorName }),
    polarize: () => ({ name: actorName }),
    restore: () => ({ name: actorName, target: targetName || null }),
  };
  doAction(type, payloadBuilders[type]());
}

function quickMultiAction(type, actorName, count) {
  const targets = [];
  for (let i = 0; i < count; i++) {
    const v = document.getElementById(`qaMulti_${type}_${i}`).value;
    if (v) targets.push(v);
  }
  doAction(type, { name: actorName, targets });
}

// ------------------------------------------------------------------
// 배경음악 (유튜브/mp3, 서버 시각 기준으로 방 전체 동기화)
// ------------------------------------------------------------------
let musicState = null;
let musicKey = null;
let ytPlayer = null;
let ytApiReady = false;

// 음량은 서버와 동기화하지 않고, 이 브라우저(개인)에만 적용/저장됩니다.
let musicVolume = parseInt(localStorage.getItem('musicVolume') || '70', 10);
(function initVolumeSlider() {
  const slider = document.getElementById('musicVolumeSlider');
  if (slider) slider.value = musicVolume;
  refreshVolumeUi();
})();

// ---------- 전체 화면 : 모바일 · 태블릿은 첫 터치 때 주소창 없이 전체 화면으로 바꿉니다 ----------
// (브라우저 정책상 터치 같은 사용자 동작이 있어야만 전체 화면이 돼요. 아이폰 Safari는 전체 화면을 지원하지 않아
//  '홈 화면에 추가'로 열어야 주소창이 사라집니다.)
function fsActive() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
function fsEnter() {
  const d = document.documentElement, f = d.requestFullscreen || d.webkitRequestFullscreen;
  if (!f) return;
  try { const r = f.call(d, { navigationUI: 'hide' }); if (r && r.catch) r.catch(() => {}); } catch (e) {}
}
function fsExit() {
  const f = document.exitFullscreen || document.webkitExitFullscreen;
  if (!f) return;
  try { const r = f.call(document); if (r && r.catch) r.catch(() => {}); } catch (e) {}
}
(function autoFullscreen() {
  const touch = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  const installed = window.matchMedia('(display-mode: fullscreen), (display-mode: standalone)').matches || navigator.standalone;
  if (!touch || installed) return;
  const d = document.documentElement;
  if (d.requestFullscreen || d.webkitRequestFullscreen) {
    const once = () => { document.removeEventListener('pointerup', once, true); if (!fsActive()) fsEnter(); };
    document.addEventListener('pointerup', once, true);
  } else if (/iPhone|iPod/.test(navigator.userAgent)) {
    // 아이폰 : 한 번만 안내합니다.
    let shown = null; try { shown = localStorage.getItem('a2hsHintShown'); } catch (e) {}
    if (!shown) setTimeout(() => {
      try { localStorage.setItem('a2hsHintShown', '1'); } catch (e) {}
      if (typeof showShopToast === 'function') showShopToast('주소창 없이 보려면 Safari 공유 버튼에서 \'홈 화면에 추가\'를 눌러 그 아이콘으로 열어 주세요.');
    }, 4000);
  }
})();
function toggleFullscreen() { fsActive() ? fsExit() : fsEnter(); }
// 휴대폰은 세로로만 : 전체 화면이 되면 세로로 고정하고(안드로이드), 고정이 안 되는 환경에서 가로로 돌리면 안내 화면을 덮어요.
const IS_PHONE = window.matchMedia('(hover: none) and (pointer: coarse)').matches && Math.min(screen.width, screen.height) < 600;
function lockPortrait() {
  if (!IS_PHONE || !screen.orientation || !screen.orientation.lock) return;
  try { const p = screen.orientation.lock('portrait'); if (p && p.catch) p.catch(() => {}); } catch (e) {}
}
if (IS_PHONE) {
  document.documentElement.classList.add('is-phone');
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(ev => document.addEventListener(ev, () => { if (fsActive()) lockPortrait(); }));
  lockPortrait();   // 홈 화면에 추가한 앱으로 열었을 때
}
// 전체 화면일 때는 화면 높이를 '지금까지 본 가장 큰 높이'로 고정해요. 시스템 바가 잠깐 나와 화면이 줄어도 그대로 두고,
// 화면 방향(가로 폭)이 바뀌거나 전체 화면을 켜고 끌 때만 다시 재요.
(function stableViewport() {
  if (!window.matchMedia('(hover: none) and (pointer: coarse)').matches) return;
  const root = document.documentElement;
  let w = 0, maxH = 0;
  const full = () => fsActive() || window.matchMedia('(display-mode: fullscreen), (display-mode: standalone)').matches || navigator.standalone;
  function upd(reset) {
    if (!full()) { root.classList.remove('vp-lock'); root.style.removeProperty('--app-h'); w = 0; maxH = 0; return; }
    const iw = window.innerWidth, ih = window.innerHeight;
    if (reset || Math.abs(iw - w) > 40) { w = iw; maxH = ih; } else maxH = Math.max(maxH, ih);
    root.style.setProperty('--app-h', maxH + 'px');
    root.classList.add('vp-lock');
  }
  // 글을 쓰는 동안(가상 키보드가 올라와 있을 때)은 고정을 풀어요 : 키보드에 입력 칸이 가려지지 않게
  const typing = () => { const a = document.activeElement; return !!a && (a.matches('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]):not([type=file]), textarea, select') || a.isContentEditable); };
  document.addEventListener('focusin', () => { if (typing()) { root.classList.remove('vp-lock'); root.style.removeProperty('--app-h'); } });
  document.addEventListener('focusout', () => setTimeout(() => { if (!typing()) upd(true); }, 300));
  window.addEventListener('resize', () => { if (!typing()) upd(false); });
  window.addEventListener('orientationchange', () => setTimeout(() => upd(true), 350));
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(ev => document.addEventListener(ev, () => setTimeout(() => upd(true), 250)));
  upd(true);
})();
// ---------- 스마트폰 · 태블릿 : 탭이 여럿인 화면은 본문을 옆으로 쓱 밀어 이웃 탭으로 넘깁니다 ----------
// [본문, 그 본문의 탭 줄]. 지도 · 마이룸 방 · 옆으로 스크롤되는 칸 · 입력칸에서 시작한 밀기는 건드리지 않아요.
const SWIPE_TABS = [
  ['#shopBody', '#shopTabs'], ['#mailBody', '#mailTabs'], ['#opsBody', '#opsTabs'], ['#dormPalette', '#dormCatTabs'],
  ['.member-panel:not(.dorm-side) > .member-body', '.member-panel:not(.dorm-side) > .member-toptabs'],
];
(function swipeTabs() {
  if (!window.matchMedia('(hover: none) and (pointer: coarse)').matches) return;
  let st = null;
  const skip = (el, stop) => {
    if (el.closest('input, textarea, select, [contenteditable="true"], .map-frame, #gridSection, .wm-stage, .zoom-ctl, .dorm-edit-bar, .no-swipe')) return true;
    // 옆으로 스크롤되는 칸 안이면(표 · 칩 줄 등) 그 칸의 스크롤에 맡깁니다.
    for (let n = el; n && n !== stop; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 4 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return true;
    }
    return false;
  };
  document.addEventListener('touchstart', (e) => {
    st = null;
    if (e.touches.length !== 1) return;
    const t = e.touches[0], target = e.target;
    for (const [bodySel, tabsSel] of SWIPE_TABS) {
      const body = target.closest && target.closest(bodySel);
      if (!body || !body.offsetParent) continue;
      if (skip(target, body)) return;
      const tabs = document.querySelector(tabsSel);
      if (tabs && tabs.offsetParent) st = { x: t.clientX, y: t.clientY, at: Date.now(), tabs };
      return;
    }
  }, { passive: true });
  // LOOP(PLAY 룸) : 루프 화면을 왼쪽으로 밀면 지나온 사건 기록, 기록을 오른쪽으로 밀면 다시 루프 화면.
  let ps = null;
  if (BATTLE_TYPE === 'play') {
    document.addEventListener('touchstart', (e) => {
      ps = null;
      if (e.touches.length !== 1 || document.querySelector('.modal-overlay[style*="flex"]')) return;
      const b = document.body.classList;
      if (b.contains('view-map') || b.contains('view-loopadmin') || b.contains('view-ops')) return;
      const target = e.target, open = b.contains('m-chat-open');
      const area = target.closest && target.closest(open ? '#playLogPanel' : '#playPage');
      if (!area || skip(target, area)) return;
      ps = { x: e.touches[0].clientX, y: e.touches[0].clientY, at: Date.now(), open };
    }, { passive: true });
    document.addEventListener('touchend', (e) => {
      if (!ps) return;
      const t = e.changedTouches[0], dx = t.clientX - ps.x, dy = t.clientY - ps.y, p = ps;
      ps = null;
      if (Date.now() - p.at > 700 || Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx) * 0.6) return;
      if (!p.open && dx < 0) toggleMobileChat(true);
      else if (p.open && dx > 0) toggleMobileChat(false);
    }, { passive: true });
  }
  document.addEventListener('touchend', (e) => {
    if (!st) return;
    const t = e.changedTouches[0], dx = t.clientX - st.x, dy = t.clientY - st.y, tabs = st.tabs, quick = Date.now() - st.at < 700;
    st = null;
    if (!quick) return;
    if (Math.abs(dx) < 60 || Math.abs(dy) > Math.abs(dx) * 0.6) return;
    const btns = [...tabs.querySelectorAll('button')].filter(b => b.offsetParent && !b.disabled);
    const cur = btns.findIndex(b => b.classList.contains('active') || b.classList.contains('on'));
    const next = btns[cur + (dx < 0 ? 1 : -1)];
    if (cur < 0 || !next) return;
    next.click();
    next.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, { passive: true });
})();
['fullscreenchange', 'webkitfullscreenchange'].forEach(ev => document.addEventListener(ev, () => {
  const btn = document.getElementById('sidebarFullscreenBtn');
  // 켜진 탭처럼 표시하지 않고 아이콘만 바꿔요(전체 화면 ↔ 원래 크기)
  if (btn) { btn.classList.remove('active'); btn.innerHTML = `<i class="fa-solid ${fsActive() ? 'fa-compress' : 'fa-expand'}"></i>`; btn.blur(); }
}));

// 등록된 캐릭터 전원을 보여주고, 지금 그 이름으로 접속 중이면 초록 점을 켭니다.
function renderUserInfoList() {
  const listEl = document.getElementById('userInfoList');
  const onlineSet = new Set(lastOnlineCharacters);
  // 선생님 NPC(앙투안 · 이네이타)는 모든 방의 유저 리스트에 함께 보여요(LOOP 방은 미리보기 목록에 이미 있어요).
  // 몹으로 정한 캐릭터는 유저 리스트에서 빼요.
  const npcs = playPreviewOn() ? [] : SITE_NPC_NAMES.filter(n => !lastRoster.includes(n));
  const roster = [...lastRoster.filter(n => !((lastRosterMypage || {})[n] || {}).mob), ...npcs];
  if (!roster.length) {
    listEl.innerHTML = '<div class="hint" style="padding:8px 2px;">등록된 캐릭터가 없습니다.</div>';
    return;
  }
  // GM은 전원을 보고 이름 옆 눈 아이콘으로 숨김을 켜고 끕니다. GM이 아닌 사람에게는 숨긴 이름이 아예 안 보입니다.
  const isGm = myControlInfo(lastBattleForPanel).scope === 'all';
  const pvNote = document.getElementById('userInfoPreviewNote'); if (pvNote) pvNote.style.display = playPreviewOn() ? '' : 'none';
  const gmHint = document.getElementById('userInfoGmHint');
  if (gmHint) gmHint.style.display = isGm ? '' : 'none';
  // 가나다순(한국어 정렬, 숫자는 크기순 - 예: NOVA 2구역 < NOVA 10구역)
  // 탭(이름순/포지션순/진영순)마다 섹션 제목으로 나누고, 섹션 안에서는 가나다순
  const visible = isGm ? roster : roster.filter(n => !lastUserInfoHidden.has(n));
  const q = ((document.getElementById('userInfoSearch') || {}).value || '').trim().toLowerCase();
  const names = visible.filter(n => !q || n.toLowerCase().includes(q));
  const onlineCount = visible.filter(n => onlineSet.has(n)).length;
  document.getElementById('userInfoCount').innerHTML = `<b>${onlineCount}</b> / ${visible.length}<span class="ui-count-w">명 접속</span>`;
  document.querySelectorAll('#userInfoFilter button').forEach(b => {
    const on = b.dataset.v === userInfoFilter;
    b.classList.toggle('on', on);
    const ic = b.querySelector('.ui-sort-ic');
    if (ic) ic.className = 'ui-sort-ic fa-solid ' + (b.dataset.v === 'name' ? 'fa-chevron-down' + (on && userInfoDesc ? ' up' : '') : 'fa-arrows-rotate') + (on ? ' on' : '');
  });
  document.querySelectorAll('#userInfoView button').forEach(b => b.classList.toggle('on', b.dataset.v === userInfoView));
  if (!names.length) { listEl.innerHTML = `<div class="hint" style="padding:16px 4px; text-align:center;">${q ? '검색 결과가 없어요.' : '등록된 캐릭터가 없어요.'}</div>`; return; }
  const esc = t => String(t).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const info = n => (lastRosterMypage || {})[n] || npcEntry(n) || {};
  const CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  const BASE = { 'ㄲ': 'ㄱ', 'ㄸ': 'ㄷ', 'ㅃ': 'ㅂ', 'ㅆ': 'ㅅ', 'ㅉ': 'ㅈ' };
  const initialOf = (n) => {
    const ch = (n || '').trim()[0] || '#';
    const code = ch.charCodeAt(0) - 0xAC00;
    if (code >= 0 && code < 11172) { const c = CHO[Math.floor(code / 588)]; return BASE[c] || c; }
    if (/[a-z]/i.test(ch)) return ch.toUpperCase();
    return '#';
  };
  // 포지션순 : 누를 때마다 맨 위 포지션이 스트라이커 → 가디언 → 메딕으로 돌아가요
  const ROLE_BASE = ['스트라이커', '가디언', '메딕'];
  const ROLE_ORDER = ROLE_BASE.map((_, i) => ROLE_BASE[(i + userInfoRoleRot) % ROLE_BASE.length]);
  // 국가순 : 출신지(맵의 장소)로 아르카디아 연방 · 노바 공화국을 나눠요
  const countryOf = (n) => { const c = UI_COUNTRIES.find(x => (info(n).hometown || '').split(':')[0] === x[0]); return c ? c[1] : ''; };
  const keyOf = (n) => userInfoFilter === 'role' ? (info(n).role || '기타')
    : userInfoFilter === 'nation' ? (countryOf(n) || '국가 미정') : initialOf(n);
  const groups = {};
  names.forEach(n => { (groups[keyOf(n)] = groups[keyOf(n)] || []).push(n); });
  const keys = Object.keys(groups).sort((a, b) => {
    if (userInfoFilter === 'role') return (ROLE_ORDER.indexOf(a) + 1 || 99) - (ROLE_ORDER.indexOf(b) + 1 || 99);
    if (userInfoFilter === 'nation') {
      // 국가순 : 누를 때마다 맨 위 국가가 차례로 돌아가요(국가 미정은 늘 맨 끝)
      const F0 = UI_COUNTRIES.map(f => f[1]), NO = F0.map((_, i) => F0[(i + userInfoNationRot) % F0.length]);
      const ia = NO.indexOf(a), ib = NO.indexOf(b);
      if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    }
    const last = userInfoFilter === 'nation' ? '국가 미정' : '#';
    if (a === last) return 1; if (b === last) return -1;
    return a.localeCompare(b, 'ko');
  });
  // 이름순을 한 번 더 누르면 역순(#은 늘 맨 끝). 묶음 안 이름도 거꾸로
  const desc = userInfoFilter === 'name' && userInfoDesc;
  if (desc) {
    const tail = keys.filter(k => k === '#');
    keys.splice(0, keys.length, ...keys.filter(k => !tail.includes(k)).reverse(), ...tail);
  }
  // 섹션 안은 접속 여부와 관계없이 가나다순(접속 중인 사람은 초록 점으로만 표시)
  const byOnlineThenName = (a, b) => (desc ? -1 : 1) * a.localeCompare(b, 'ko', { numeric: true });
  const grid = userInfoView === 'grid';
  listEl.innerHTML = (grid ? '<div class="ui-grid">' : '') + keys.map(k => {
    const list = groups[k].sort(byOnlineThenName);
    const on = list.filter(n => onlineSet.has(n)).length;
    const color = userInfoFilter === 'role' && ROLE_ORDER.includes(k) ? ` style="color:${roleColorVar(k)}"`
      : userInfoFilter === 'nation' && UI_COUNTRIES.find(x => x[1] === k) ? ` style="color:${UI_COUNTRIES.find(x => x[1] === k)[2]}"` : '';
    // 썸네일 보기 : 묶음 제목 · 칸 나눔 없이 같은 순서로 빈틈없이 이어 채워요
    return (grid ? '' : `<div class="ui-sec"><span${color}>${esc(k)}</span><em>${on ? `${on} / ` : ''}${list.length}</em></div>`) + list.map(name => {
      const online = onlineSet.has(name);
      const hidden = lastUserInfoHidden.has(name);
      const js = name.replace(/'/g, "\\'");
      const eye = isGm && !npcEntry(name)
        ? `<button class="userinfo-eye" onclick="event.stopPropagation(); toggleUserInfoHidden('${js}')">`
          + `<i class="fa-solid ${hidden ? 'fa-eye-slash' : 'fa-eye'}"></i></button>`
        : '';
      // 누르면 그 캐릭터의 마이페이지(운영진 = 수정 가능, 그 외 = 보기 전용).
      // 왼쪽 절반(점 + 이름)에만 마우스를 올리면 프로필 사진 카드가 따라다니고, 오른쪽 링크 아이콘은 그 캐릭터의 프로필 문서로 가요.
      const doc = docUrlOf(name);
      // 링크가 없으면 흐린 아이콘(운영진은 눌러서 그 캐릭터의 마이페이지 '프로필' 칸에 넣어요). NPC는 사이트 안 프로필 창
      const link = npcProfileOf(name) ? `<button type="button" class="ui-doc" onclick="event.stopPropagation(); openNpcProfile('${js}')" aria-label="${esc(name)} 프로필" data-tip="프로필"><i class="fa-solid fa-link"></i></button>`
        : doc ? `<a class="ui-doc" ${docLinkAttrs(doc)} onclick="event.stopPropagation()" aria-label="${esc(name)} 프로필 문서" data-tip="프로필 문서"><i class="fa-solid fa-link"></i></a>`
        : isGm ? `<button type="button" class="ui-doc empty" onclick="event.stopPropagation(); openUserDocEdit('${js}')" data-tip="프로필 문서 링크 넣기"><i class="fa-solid fa-link"></i></button>`
        : `<span class="ui-doc empty" data-tip="프로필 문서 없음"><i class="fa-solid fa-link"></i></span>`;
      if (grid) {
        // 썸네일 보기 : 사진 · 접속 점 · 이름 · 문서 링크. 누르면 마이페이지(보기 전용)
        const av = info(name).avatar_url;
        return `<div class="ui-card ${hidden ? 'is-hidden' : ''} ${online ? 'is-online' : ''}" data-name="${esc(name)}" onclick="openUserFromList('${js}')">
          <div class="pic">${av ? `<img src="${esc(av)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ''}
            ${link}</div>
          <div class="cap"><span class="ui-dot"></span><span class="t"><b>${esc(name)}</b></span>${eye}</div></div>`;
      }
      return `<div class="userinfo-row ${hidden ? 'is-hidden' : ''} ${online ? 'is-online' : ''}" data-name="${esc(name)}" onclick="openUserFromList('${js}')">
        <span class="ui-left" onmouseenter="uiHoverShow(this.parentNode, event)" onmousemove="uiHoverMove(event)" onmouseleave="uiHoverHide()"><span class="ui-dot"></span><span class="userinfo-name"><b>${esc(name)}${npcProfileOf(name) ? '<span class="npc-tag">NPC</span>' : ''}</b></span></span><span class="ui-prof" onclick="uiProfArea(this, event)"></span>${isGm && online ? deviceBadgesHtml(name) : ''}${link}${eye}</div>`;
    }).join('');
  }).join('') + (grid ? '</div>' : '');
}
// 목록 오른쪽 빈 곳 : 누르면 그 줄의 프로필(링크 아이콘과 같은 동작). 프로필이 없으면 평소처럼 마이페이지
function uiProfArea(el, e) {
  const d = el.parentNode.querySelector('.ui-doc');
  if (!d || d.tagName === 'SPAN') return;
  e.stopPropagation();
  d.click();
}
// 유저 리스트 보기 방식(목록 / 썸네일) : 이 기기에 기억해요
var userInfoView = (() => { try { return localStorage.getItem('userInfoView') === 'grid' ? 'grid' : 'list'; } catch (e) { return 'list'; } })();
function setUserInfoView(v) {
  userInfoView = v === 'grid' ? 'grid' : 'list';
  try { localStorage.setItem('userInfoView', userInfoView); } catch (e) {}
  uiHoverHide();
  const list = document.getElementById('userInfoList'); if (list) list.scrollTop = 0;
  renderUserInfoList();
}

// 유저 리스트 국가순 : [맵 장소 id, 국가 이름, 색]
const UI_COUNTRIES = [['arcadia', '아르카디아 연방', '#e9c05b'], ['nova', '노바 공화국', '#6aa5ff']];
let userInfoFilter = 'name', userInfoDesc = false, userInfoRoleRot = 0, userInfoNationRot = 0;
// 같은 정렬 탭을 다시 누르면 : 이름순 = 역순 전환, 포지션순 · 진영순 = 맨 위 항목 돌림
function setUserInfoFilter(v) {
  if (v === userInfoFilter) {
    if (v === 'role') userInfoRoleRot = (userInfoRoleRot + 1) % 3;
    else if (v === 'nation') userInfoNationRot = (userInfoNationRot + 1) % UI_COUNTRIES.length;
    else userInfoDesc = !userInfoDesc;
  } else { userInfoFilter = v; userInfoDesc = false; userInfoRoleRot = 0; userInfoNationRot = 0; }
  const l = document.getElementById('userInfoList'); if (l) l.scrollTop = 0;
  renderUserInfoList();
}
function toggleUserInfoHidden(name) {
  socket.emit('set_userinfo_hidden', { name, hidden: !lastUserInfoHidden.has(name) });
}

// LOOP 방(웹 공개) 미리보기 : 실제 참가자 정보는 받지 않고, 화면 안에서 만든 예시 캐릭터로 유저 리스트 · 마이페이지를 보여 줘요.
// [이름, 포지션, 표시 컬러, 나이, 캐치프레이즈, 접속 중, 출신지(장소:구역), 프로필 사진]
const PLAY_PREVIEW_CHARS = [
  ['앙투안 얀 다비드', '메딕', '#f0d27a', '??', '', 1, 'arcadia:0', '/static/preview/antoine.png'],
  ['이네이타 장', '가디언', '#e25a5a', '??', '', 1, 'nova:0', '/static/preview/ineita.png'],
  ['TEST', '스트라이커', '', 13, '', 1, '', null],
];
// NPC 프로필(특별한 캐릭터) : 프로필 칸 · 유저 리스트 링크 아이콘을 누르면 소개 한 줄이 알림으로 떠요
const NPC_PROFILES = {
  '앙투안 얀 다비드': '앙투안 얀 다비드는 아르카디아 연방 소속 교수로, 뛰어난 감각으로 확고한 사조를 가지고 활동하던 예술가이자 감각계 레저넌트다. 온정적인 성격의 그는 모두에게 공정하다.',
  '이네이타 장': '이네이타 장은 노바 공화국 소속 교수로, 뛰어난 지성으로 학계에서 월등한 실적을 내던 학자로서 초빙되었으며 정신계 레저넌트다. 예리한 성격의 그는 모두에게 공정하다.',
};
function npcProfileOf(name) { return NPC_PROFILES[name] || null; }
// 마이페이지 칸들이 읽는 등록 정보 : 실제 캐릭터는 받은 정보, NPC는 미리 정한 값
function myPageInfoOf(name) { return (lastRosterMypage || {})[name] || npcEntry(name) || {}; }
const SITE_NPC_NAMES = Object.keys(NPC_PROFILES);
// NPC 마이페이지 정보(보기 전용) : 미리보기 목록의 값을 그대로 써요
function npcEntry(name) {
  if (!NPC_PROFILES[name]) return null;
  const row = PLAY_PREVIEW_CHARS.find(c => c[0] === name); if (!row) return null;
  const [, role, color, age, catchphrase, , hometown, avatar] = row;
  return { name, role, color, age, catchphrase, nation: '', hometown: hometown || '', doc_url: '', inventory: '', points: 0, items: {}, avatar_url: avatar || null, npc: true };
}
// 지도 구역 카드와 같은 알림(이름 + 소개)으로 띄워요
function openNpcProfile(name) {
  const t = NPC_PROFILES[name], el = document.getElementById('wmToast'); if (!t || !el) return;
  el.innerHTML = '<div class="l1"><b></b></div><div class="l2"></div>';
  el.querySelector('b').textContent = name; el.querySelector('.l2').textContent = t;
  el.classList.remove('on'); void el.offsetWidth; el.classList.add('on');
  clearTimeout(openNpcProfile._t); openNpcProfile._t = setTimeout(() => el.classList.remove('on'), 6500);
}
function playPreviewOn() { return BATTLE_TYPE === 'play' && myControlInfo(lastBattleForPanel).scope !== 'all'; }
function playPreviewFill() {
  lastRoster = PLAY_PREVIEW_CHARS.map(c => c[0]);
  lastRosterMypage = Object.fromEntries(PLAY_PREVIEW_CHARS.map(([name, role, color, age, catchphrase, , hometown, avatar]) =>
    [name, { name, role, color, age, catchphrase, nation: '', hometown: hometown || '', doc_url: '', inventory: '', points: 0, items: {}, avatar_url: avatar || null, npc: !!NPC_PROFILES[name] }]));
  lastOnlineCharacters = PLAY_PREVIEW_CHARS.filter(c => c[5]).map(c => c[0]);
  lastUserInfoHidden = new Set();
}
function toggleUserInfoPanel() {
  if (playPreviewOn()) playPreviewFill();
  renderUserInfoList();
  document.getElementById('userInfoModal').style.display = 'flex';
}
function closeUserInfoPanel() {
  document.getElementById('userInfoModal').style.display = 'none';
  uiHoverHide();
}
function openUserDocEdit(name) {
  openUserFromList(name);
  setTimeout(() => { const i = document.querySelector('#myPageDoc input'); if (i) { i.scrollIntoView({ block:'center' }); i.focus(); } }, 120);
}
// 유저 리스트에서 연 마이페이지 : 왼쪽 위 '이전' 버튼으로 유저 리스트(보던 자리 그대로)로 돌아가요
var myPageFromList = false, userInfoScroll = 0;
function setMyPageBack(on) { myPageFromList = on; const b = document.getElementById('myPageBack'); if (b) b.hidden = !on; }
function openUserFromList(name) {
  uiHoverHide();
  const l = document.getElementById('userInfoList'); userInfoScroll = l ? l.scrollTop : 0;
  closeUserInfoPanel();
  openMyPageFor(name);
  setMyPageBack(true);
}
function myPageGoBack() {
  closeMyPage();
  toggleUserInfoPanel();
  const l = document.getElementById('userInfoList'); if (l) l.scrollTop = userInfoScroll;
}
// 유저 리스트 호버 카드 : 프로필 사진(없으면 검은 블럭)이 커서를 부드럽게 따라옵니다. 마우스가 있는 기기에서만.
const uiHover = { el: null, x: 0, y: 0, tx: 0, ty: 0, raf: 0, on: false };
function uiHoverEl() {
  if (!uiHover.el) {
    uiHover.el = document.createElement('div');
    uiHover.el.className = 'ui-hovercard';
    uiHover.el.innerHTML = '<div class="pic"></div><div class="cap"><b></b><span></span></div>';
    document.body.appendChild(uiHover.el);
  }
  return uiHover.el;
}
function uiHoverShow(row, e) {
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  const name = row.dataset.name, d = (lastRosterMypage || {})[name] || npcEntry(name) || {};
  const el = uiHoverEl(), pic = el.querySelector('.pic');
  const fresh = !uiHover.on;
  pic.style.backgroundImage = 'none';
  if (d.avatar_url) {
    // 이미지를 다 받은 뒤에 바꿔 끼워서, 못 불러오면 검은 블럭을 그대로 둡니다.
    const img = new Image(), want = name;
    img.onload = () => { if (uiHover.name === want) { pic.style.backgroundImage = `url('${d.avatar_url}')`; } };
    img.src = d.avatar_url;
  }
  uiHover.name = name;
  el.querySelector('.cap b').textContent = name;
  el.querySelector('.cap span').textContent = d.role || '';
  uiHover.tx = e.clientX; uiHover.ty = e.clientY;
  if (fresh) { uiHover.x = uiHover.tx; uiHover.y = uiHover.ty; }
  uiHover.on = true;
  el.classList.add('on');
  if (!uiHover.raf) uiHoverTick();
}
function uiHoverMove(e) { uiHover.tx = e.clientX; uiHover.ty = e.clientY; }
function uiHoverHide() {
  uiHover.on = false;
  if (uiHover.el) uiHover.el.classList.remove('on');
}
function uiHoverTick() {
  uiHover.x += (uiHover.tx - uiHover.x) * 0.18;
  uiHover.y += (uiHover.ty - uiHover.y) * 0.18;
  const el = uiHover.el;
  // 카드는 커서 오른쪽에 둬서 이름이 가려지지 않게, 화면 밖으로는 나가지 않게
  const w = el.offsetWidth || 168, h = el.offsetHeight || 210;
  let left = uiHover.x + 28, top = uiHover.y - h / 2;
  if (left + w > window.innerWidth - 12) left = uiHover.x - w - 28;
  top = Math.max(12, Math.min(window.innerHeight - h - 12, top));
  el.style.transform = `translate3d(${left}px, ${top}px, 0)`;
  const moving = Math.abs(uiHover.tx - uiHover.x) + Math.abs(uiHover.ty - uiHover.y) > 0.3;
  uiHover.raf = (uiHover.on || moving) ? requestAnimationFrame(uiHoverTick) : 0;
}

// ------------------------------------------------------------------
// 마이페이지 팝업 - 로그인 기준자(캐릭터면 본인, GM이면 지금 선택된 행동자)를 보여줍니다.
// 체력/소지품은 운영진만 수정 가능하고, 그 외(표기 이름/색상/스킬 로그)는 본인(캐릭터로
// 직접 로그인한 사람)만 수정 가능합니다.
// ------------------------------------------------------------------
// 유저 리스트에서 눌러 연 캐릭터 이름(없으면 평소처럼 본인/선택된 행동자 기준)
let myPageViewName = null;
// 남의 마이페이지를 보기만 하는 중(운영진이 아닐 때) : 수정은 막고, 진영 · 스킬 로그 · 효과음은 감춥니다.
function myPageIsView() { return !!myPageViewName && ((myControlInfo(lastBattleForPanel).scope !== 'all' && myPageViewName !== myLoggedInName()) || !!npcEntry(myPageViewName)); }

function openMyPageFor(name) {
  // 운영진은 누구의 마이페이지든 수정할 수 있고, 그 외에는 남의 마이페이지를 보기만 합니다(본인이면 평소 마이페이지).
  if (myControlInfo(lastBattleForPanel).scope !== 'all' && name === myLoggedInName()) { openMyPage(); return; }
  myPageViewName = name;
  skillLogTypeLocal = null;
  document.getElementById('myPageModal').style.display = 'flex';
  renderMyPage();
  renderMyPagePoints();
  renderMyPageRoom();
}

function myPageTargetChar() {
  if (myPageViewName) {
    const live = lastAllForCards.find(c => c.name === myPageViewName);
    if (live) return live;
    // 전투에 없는 캐릭터는 등록 정보만 보여줍니다(체력은 전투 중에만 있음).
    const d = lastRosterDetail.find(r => r.name === myPageViewName) || (lastRosterMypage || {})[myPageViewName] || npcEntry(myPageViewName);
    return d ? { ...d, name: myPageViewName, current_hp: null, max_hp: null } : null;
  }
  const battle = lastBattleForPanel;
  if (battle) {
    const actorName = myActorName(battle);
    const live = lastAllForCards.find(c => c.name === actorName);
    if (live) return live;
  }
  // 전투에 없더라도 로그인한 캐릭터면 등록 정보로 마이페이지를 보여줍니다.
  const me = myLoggedInName();
  return me && lastRosterMypage[me] ? { ...lastRosterMypage[me] } : null;
}

function openMyPage() {
  // LOOP 방 : 내(TEST) 마이페이지를 예시로, 보기 전용으로 보여 줘요
  if (playPreviewOn()) { playPreviewFill(); openMyPageFor('TEST'); setMyPageBack(false); return; }
  setMyPageBack(false);
  myPageViewName = null;
  skillLogTypeLocal = null;
  document.getElementById('myPageModal').style.display = 'flex';
  renderMyPage();
  renderMyPagePoints();
  renderMyPageRoom();
}

function closeMyPage() {
  if (typeof closeHomeMenu === 'function') closeHomeMenu();
  setMyPageBack(false);
  myPageViewName = null;
  document.getElementById('myPageModal').style.display = 'none';
}

// 진영 : 마이룸 기간을 따라갑니다. 1차·3차는 모두 Resonans(레저넌트), 2차는 使徒(사도) · Void(보이드) 중 하나를 골라요.
// 2차 선택은 캐릭터 정보의 nation 칸에 저장하고, 본인과 운영진이 고를 수 있어요.
const FACTIONS = [['Resonans', 'var(--fac-resonans)', '레저넌트'], ['使徒', 'var(--fac-apostle)', '사도'], ['Void', 'var(--fac-void)', '보이드']];
const FACTION_CHOICES = ['使徒', 'Void'];
function factionPeriod() { return (dormData && dormData.period && dormData.period.no) || lastFactionPeriod || 1; }
function factionOf(name) {
  if (factionPeriod() !== 2) return 'Resonans';
  const v = ((lastRosterMypage || {})[name] || {}).nation || '';
  return FACTION_CHOICES.includes(v) ? v : '';
}
function nationColor(n) { const f = FACTIONS.find(x => x[0] === n); return f ? f[1] : null; }
function factionTip(n) { const f = FACTIONS.find(x => x[0] === n); return f ? f[2] : ''; }
function renderMyPageNation(c) {
  const el = document.getElementById('myPageNation'); if (!el) return;
  if (!c) { el.innerHTML = ''; return; }
  const cur = factionOf(c.name);
  const tag = n => `<button class="on" disabled style="--nc:${nationColor(n)}" data-tip="${factionTip(n)}">${n}</button>`;
  if (factionPeriod() !== 2) { el.innerHTML = tag('Resonans'); return; }
  if (!canEditMyPage()) { el.innerHTML = cur ? tag(cur) : '<span class="none">미정</span>'; return; }
  el.innerHTML = FACTION_CHOICES.map(n => `<button class="${n === cur ? 'on' : ''}" style="--nc:${nationColor(n)}" data-tip="${factionTip(n)}" onclick='setMyPageNation(${JSON.stringify(c.name)}, ${JSON.stringify(n === cur ? '' : n)})'>${n}</button>`).join('');
}
function setMyPageNation(name, nation) {
  if (myControlInfo(lastBattleForPanel).scope === 'all') socket.emit('set_mypage_gm_fields', { name, nation });
  else socket.emit('set_my_skill_log', { name: myPageEditName(), nation });
}
// 마이룸 한마디 : 방에 들어온 사람에게 말풍선으로 보이는 방 주인 대사. 마이페이지 맨 위에서 본인만 고쳐요.
function renderMyPageLine(c) {
  const el = document.getElementById('myPageLine'); if (!el) return;
  const name = c && c.name;
  const hasRoom = !!(name && dormData && dormHallOf(name));
  const line = hasRoom ? (((dormData.rooms || {})[name] || {}).line || '') : '';
  const mine = hasRoom && name === dormMe() && !dormIsGm();
  if (!hasRoom || (!mine && !line)) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = '';
  if (!mine) { el.innerHTML = `<i class="fa-solid fa-quote-left"></i><span class="t">${mailEsc(line)}</span>`; return; }
  if (document.activeElement && document.activeElement.id === 'myPageLineInput') return;
  el.innerHTML = `<i class="fa-solid fa-quote-left"></i><input id="myPageLineInput" maxlength="80" autocomplete="off" placeholder="마이룸에 들어온 사람에게 보일 한마디" value="${mailEsc(line)}"
    onchange="saveMyPageLine(this.value)" onkeydown="if(event.key==='Enter') this.blur()"><i class="fa-solid fa-pen ed"></i>`;
}
function saveMyPageLine(v) {
  const name = dormMe(); if (!name) return;
  const text = String(v || '').trim().slice(0, 80);
  if (dormData && dormData.rooms && dormData.rooms[name]) dormData.rooms[name].line = text;
  socket.emit('dorm_line_save', { owner: name, text });
}
// 출신지 : 맵의 장소 · 구역 중에서 고릅니다(맵 구역 카드를 누르면 '00의 출신지.'로 나옵니다). 본인과 운영진이 바꿀 수 있어요.
function myPageHomeLabel(key) {
  const [pid, zi] = String(key || '').split(':');
  const p = ((worldData && worldData.places) || []).find(x => x.id === pid);
  if (!p || p.locked) return key ? '비공개 지역' : '';
  const z = (p.zones || [])[+zi] || {};
  return `${p.name} · ${+zi + 1}구역${z.title ? ' ' + z.title : ''}`;
}
function renderMyPageHome(c) {
  const el = document.getElementById('myPageHome'); if (!el) return;
  if (!c) { el.innerHTML = ''; return; }
  if (!worldData) socket.emit('world_get');
  const cur = myPageInfoOf(c.name).hometown || '';
  if (!canEditMyPage()) { el.innerHTML = cur ? `<span class="v">${worldEsc(myPageHomeLabel(cur))}</span>` : '<span class="none">없음</span>'; return; }
  // 기본 select는 목록(그룹 제목 등)을 꾸밀 수 없어서, 사이트 디자인에 맞춘 드롭다운을 직접 띄웁니다.
  el.innerHTML = `<button type="button" class="mp-home-btn ${homeMenu.open ? 'open' : ''}" onclick="toggleHomeMenu(this)">
    <span class="${cur ? '' : 'muted'}">${cur ? worldEsc(myPageHomeLabel(cur) || cur) : '없음'}</span><i class="fa-solid fa-chevron-down"></i></button>`;
}
var homeMenu = { open: false, el: null };  // var : 상태가 이 줄보다 먼저 도착해도 오류가 나지 않게
function closeHomeMenu() {
  homeMenu.open = false;
  if (homeMenu.el) homeMenu.el.remove(); homeMenu.el = null;
  document.querySelectorAll('.mp-home-btn.open').forEach(b => b.classList.remove('open'));
}
function toggleHomeMenu(btn) {
  if (homeMenu.open) { closeHomeMenu(); return; }
  const c = myPageTargetChar(); if (!c || !canEditMyPage()) return;
  const cur = myPageInfoOf(c.name).hometown || '';
  const places = ((worldData && worldData.places) || []).filter(p => !p.locked && (p.zones || []).length);
  const opt = (v, label, sub) => `<button type="button" class="hm-opt ${v === cur ? 'on' : ''}" onclick="pickHome(${worldEsc(JSON.stringify(v))})">
      <span class="t">${label}${sub ? `<em>${sub}</em>` : ''}</span>${v === cur ? '<i class="fa-solid fa-check"></i>' : ''}</button>`;
  const m = document.createElement('div');
  m.className = 'home-menu';
  m.innerHTML = opt('', '없음')
    + places.map(p => `<div class="hm-group">${worldEsc(p.name)}</div>`
      + p.zones.map((z, i) => opt(`${p.id}:${i}`, `${i + 1}구역`, z.title ? worldEsc(z.title) : '')).join('')).join('')
    + (cur && !places.some(p => cur.startsWith(p.id + ':')) ? opt(cur, worldEsc(myPageHomeLabel(cur) || cur)) : '');
  document.body.appendChild(m);
  homeMenu.open = true; homeMenu.el = m; btn.classList.add('open');
  // 버튼 바로 아래(공간이 없으면 위)에 버튼 폭 이상으로 띄웁니다.
  const r = btn.getBoundingClientRect(), w = Math.max(r.width, 260);
  const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left));
  m.style.width = w + 'px'; m.style.left = left + 'px';
  const below = window.innerHeight - r.bottom - 16, above = r.top - 16;
  const maxH = Math.min(380, Math.max(below, above));
  m.style.maxHeight = maxH + 'px';
  if (below >= Math.min(260, m.scrollHeight) || below >= above) m.style.top = (r.bottom + 6) + 'px';
  else m.style.top = (r.top - 6 - Math.min(maxH, m.scrollHeight)) + 'px';
  const on = m.querySelector('.hm-opt.on'); if (on) on.scrollIntoView({ block: 'center' });
}
function pickHome(v) { closeHomeMenu(); setMyPageHome(v); }
document.addEventListener('pointerdown', (e) => { if (homeMenu.open && !e.target.closest('.home-menu, .mp-home-btn')) closeHomeMenu(); }, true);
document.addEventListener('keydown', (e) => { if (homeMenu.open && e.key === 'Escape') closeHomeMenu(); });
window.addEventListener('resize', () => homeMenu.open && closeHomeMenu());
document.addEventListener('scroll', (e) => { if (homeMenu.open && !(e.target.closest && e.target.closest('.home-menu'))) closeHomeMenu(); }, true);
// 나이 : 1차 입학(空歷 514年) 때 나이 13~16세(정하지 않으면 13세). 운영진만 고를 수 있고, 참가자는 보기만 해요.
const MYPAGE_AGES = [13, 14, 15, 16];
function renderMyPageAge(c) {
  const el = document.getElementById('myPageAge'); if (!el) return;
  if (!c) { el.innerHTML = ''; return; }
  const cur = myPageInfoOf(c.name).age || 13;
  if (cur === '??') { el.innerHTML = '<button class="on" disabled style="--nc:var(--point)">??</button>'; return; }   // NPC : 나이 비공개
  if (!canEditMyPage() || !dormIsGm()) { el.innerHTML = `<button class="on" disabled style="--nc:var(--point)">1차 ${cur}세</button>`; return; }
  el.innerHTML = MYPAGE_AGES.map(a => `<button class="${a === cur ? 'on' : ''}" style="--nc:var(--point)" data-tip="1차(空歷 514年) 때 나이" onclick="setMyPageAge(${a})">${a}세</button>`).join('');
}
function setMyPageAge(a) {
  if (!canEditMyPage() || !dormIsGm()) return;
  const name = myPageEditName();
  socket.emit('set_my_skill_log', { name, age: a });
  if (name && lastRosterMypage[name]) lastRosterMypage[name].age = a;
  renderMyPageAge(myPageTargetChar());
}
// 프로필 문서 링크(구글 문서 등) : 운영진만 넣고, 모두 유저 리스트 오른쪽 링크 아이콘 · 마이페이지에서 열어요.
function docUrlOf(name) { const u = ((lastRosterMypage || {})[name] || {}).doc_url || ''; return /^https:\/\//.test(u) ? u : ''; }
function docLinkAttrs(u) { return `href="${String(u).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]))}" target="_blank" rel="noopener noreferrer"`; }
function renderMyPageDoc(c) {
  const el = document.getElementById('myPageDoc'); if (!el) return;
  if (!c) { el.innerHTML = ''; return; }
  if (npcProfileOf(c.name)) { el.innerHTML = `<button type="button" class="mp-doc-link" onclick="openNpcProfile(${mailEsc(JSON.stringify(c.name))})"><i class="fa-solid fa-id-badge"></i>프로필</button>`; return; }
  const cur = docUrlOf(c.name);
  if (canEditMyPage() && dormIsGm()) {
    const inp = el.querySelector('input');
    if (inp && document.activeElement === inp) return;
    el.innerHTML = `<input type="url" class="mp-doc-input" placeholder="문서 링크 (https://…)" autocomplete="off" onchange="setMyPageDoc(this.value)" onkeydown="if(event.key==='Enter') this.blur()">`
      + (cur ? `<a class="mp-doc-go" ${docLinkAttrs(cur)} aria-label="프로필 문서 열기"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : '');
    el.querySelector('input').value = cur;
    return;
  }
  el.innerHTML = cur ? `<a class="mp-doc-link" ${docLinkAttrs(cur)}><i class="fa-solid fa-link"></i>프로필 문서</a>` : '<span class="none">없음</span>';
}
function setMyPageDoc(v) {
  if (!canEditMyPage() || !dormIsGm()) return;
  v = String(v || '').trim();
  if (v && !/^https:\/\/\S+$/.test(v)) { uiToast('https://로 시작하는 문서 주소를 넣어 주세요.', 'error'); return; }
  const name = myPageEditName();
  socket.emit('set_my_skill_log', { name, doc_url: v });
  if (name && lastRosterMypage[name]) lastRosterMypage[name].doc_url = v;
  const inp = document.querySelector('#myPageDoc input'); if (inp) inp.blur();
  renderMyPageDoc(myPageTargetChar());
  if (document.getElementById('userInfoModal').style.display === 'flex') renderUserInfoList();
}
function setMyPageHome(v) {
  if (!canEditMyPage()) return;
  const name = myPageEditName();
  socket.emit('set_my_skill_log', { name, hometown: v });
  // 서버 응답을 기다리지 않고 바로 보여줍니다(전투가 없는 방에서도 바로 바뀌게).
  if (name && lastRosterMypage[name]) lastRosterMypage[name].hometown = v;
  renderMyPageHome(myPageTargetChar());
}

function renderMyPage() {
  if (document.getElementById('myPageModal').style.display !== 'flex') return;
  const control = myControlInfo(lastBattleForPanel);
  const isGm = control.scope === 'all';
  const isSelf = !!myLoggedInName();
  const viewOnly = myPageIsView();
  document.querySelector('#myPageModal .modal-box.mypage').classList.toggle('is-view', viewOnly);
  document.querySelector('#myPageModal .modal-box.mypage').classList.toggle('is-npc', !!(myPageViewName && npcEntry(myPageViewName)));   // NPC : 재화 · 소지품 · 마이룸 없이
  const pvNote = document.getElementById('myPagePreviewNote'); if (pvNote) pvNote.style.display = playPreviewOn() ? '' : 'none';
  // GM은 남의 마이페이지도 전부 수정할 수 있습니다. 러너는 남의 마이페이지를 보기만 합니다.
  const canEdit = (isSelf || isGm) && !viewOnly;
  const c = myPageTargetChar();

  const hpView = document.getElementById('myPageCurrentHpView');
  const hpInput = document.getElementById('myPageCurrentHpInput');

  if (!c) {
    document.getElementById('myPageName').textContent = '미로그인';
    document.getElementById('myPagePortrait').style.backgroundImage = 'none';
    document.getElementById('myPagePortraitIcon').style.display = '';
    document.getElementById('myPageColorDot').style.background = '#fff';
    document.getElementById('myPageRaidNameInput').value = '';
    document.getElementById('myPageRaidNameInput').disabled = true;
    document.getElementById('myPageRoles').innerHTML = '';
    renderMyPageNation(null);
    renderMyPageLine(null);
    renderMyPageHome(null);
    renderMyPageAge(null);
    renderMyPageDoc(null);
    document.getElementById('myPageCurrentHpView').textContent = '000';
    document.getElementById('myPageMaxHp').textContent = '000';
    document.getElementById('myPageHpBar').style.width = '0%';
    hpView.style.display = ''; hpInput.style.display = 'none';
    document.getElementById('myPageSoundStatus').textContent = '파일 업로드 (5mb 제한)';
    document.getElementById('myPageSoundFitBtn').disabled = true;
    document.getElementById('myPageSoundPreviewBtn').disabled = true;
    document.getElementById('myPageSoundUploadBtn').disabled = true;
    document.getElementById('myPageSoundVolume').disabled = true;
    return;
  }

  document.getElementById('myPageName').textContent = displayNameOf(c);
  if (npcProfileOf(c.name)) document.getElementById('myPageName').insertAdjacentHTML('beforeend', '<span class="npc-tag">NPC</span>');
  const portraitEl = document.getElementById('myPagePortrait');
  if (c.avatar_url) {
    portraitEl.style.backgroundImage = `url('${c.avatar_url}')`;
    document.getElementById('myPagePortraitIcon').style.display = 'none';
  } else {
    portraitEl.style.backgroundImage = 'none';
    document.getElementById('myPagePortraitIcon').style.display = '';
  }
  document.getElementById('myPageColorDot').style.background = c.color || '#fff';
  // 프로필 상단 빛줄 : 표시 컬러로(방명록 · 기록창처럼 캐릭터 색에 맞춰요)
  const hero = document.querySelector('#myPageModal .mp-hero'); if (hero) hero.style.setProperty('--mp-c', c.color || 'var(--point)');
  const raidInput = document.getElementById('myPageRaidNameInput');
  raidInput.disabled = !canEdit;
  if (document.activeElement !== raidInput) raidInput.value = c.raid_display_name || '';
  renderMyPageRoles(c, canEdit);
  renderMyPageNation(c);
  renderMyPageLine(c);
  renderMyPageHome(c);
  renderMyPageAge(c);
  renderMyPageDoc(c);

  const hasHp = c.max_hp != null;
  document.getElementById('myPageHpCard').style.display = viewOnly && !hasHp ? 'none' : '';
  const hpRatio = c.max_hp > 0 ? c.current_hp / c.max_hp : 0;
  document.getElementById('myPageMaxHp').textContent = hasHp ? (c.hp_hidden ? '???' : c.max_hp) : '-';
  document.getElementById('myPageHpBar').style.width = Math.max(0, hpRatio * 100) + '%';
  document.getElementById('myPageHpBar').className = hpRatio <= 0.3 ? 'low' : (hpRatio <= 0.6 ? 'mid' : '');

  if (isGm && !hasHp) {
    // 전투에 없는 캐릭터 : 체력은 표시만(-), 소지품은 GM이 수정 가능
    hpView.style.display = ''; hpInput.style.display = 'none';
    hpView.textContent = '-';
  } else if (isGm) {
    hpView.style.display = 'none'; hpInput.style.display = '';
    if (document.activeElement !== hpInput) { hpInput.value = c.current_hp; hpInput.max = c.max_hp; hpInput.min = 0; }
  } else {
    hpView.style.display = ''; hpInput.style.display = 'none';
    hpView.textContent = c.hp_hidden ? '???' : c.current_hp;
  }

  // 표기 이름/색상/스킬 로그는 본인(그 캐릭터로 직접 로그인한 사람)만 수정 가능합니다.
  document.getElementById('myPagePortrait').style.cursor = canEdit ? 'pointer' : 'default';
  document.getElementById('myPageColorBtn').style.cursor = canEdit ? 'pointer' : 'default';
  renderMyPageSkillLog(c, canEdit);

  document.getElementById('myPageSoundStatus').textContent = c.sound_effect ? '등록됨 (클릭해서 교체)' : '파일 업로드 (5mb 제한)';
  document.getElementById('myPageSoundUploadBtn').classList.toggle('has', !!c.sound_effect);
  document.getElementById('myPageSoundFitBtn').disabled = !canEdit || !c.sound_effect;
  setTimeout(updateMyPageSoundLevel, 0);
  document.getElementById('myPageSoundPreviewBtn').disabled = !c.sound_effect;
  document.getElementById('myPageSoundUploadBtn').disabled = !canEdit;
  const soundVolume = document.getElementById('myPageSoundVolume');
  soundVolume.disabled = !canEdit;
  soundVolume.value = c.sound_effect_volume != null ? c.sound_effect_volume : 100;
}

function commitRaidName() {
  if (!canEditMyPage()) return;
  const input = document.getElementById('myPageRaidNameInput');
  input.value = input.value.trim().slice(0, 3);
  socket.emit('set_my_raid_display_name', { raid_display_name: input.value, name: myPageEditName() });
}

// ---- 포지션 : 변경권(상점 아이템)을 1개 써서 바꿉니다. 운영진은 변경권 없이 바꿀 수 있어요. ----
const MYPAGE_ROLES = ['가디언', '스트라이커', '메딕'];
function myRoleTickets(name) {
  const d = (lastRosterMypage || {})[name] || {};
  return ((lastShop && lastShop.items) || []).filter(it => it.effect === 'role_change')
    .reduce((n, it) => n + ((d.items || {})[it.id] || 0), 0);
}
function renderMyPageRoles(c, canEdit) {
  const box = document.getElementById('myPageRoles');
  if (myPageIsView() && !c.role) { box.innerHTML = '<span class="none" style="font-size:13px;color:var(--muted)">없음</span>'; return; }
  box.innerHTML = (myPageIsView() ? [c.role] : MYPAGE_ROLES).map(r => `<button class="${r === c.role ? 'on' : ''}" style="--role-color:${roleColorVar(r)}"
    ${canEdit ? '' : 'disabled'} onclick="onRoleClick('${r}')">${r}</button>`).join('');
}
async function onRoleClick(role) {
  const c = myPageTargetChar();
  if (!c || role === c.role || !canEditMyPage()) return;
  if ((lastAllForCards || []).some(x => x.name === c.name)) {
    await uiAlert('전투 중에는 포지션을 바꿀 수 없어요.\n전투가 끝난 뒤에 다시 시도해 주세요.', { title: '포지션 변경', icon: 'fa-user-shield' });
    return;
  }
  const gm = myControlInfo(lastBattleForPanel).scope === 'all';
  const tickets = myRoleTickets(c.name);
  if (!tickets && !gm) {
    await uiAlert('포지션 변경권이 없어서 바꿀 수 없어요.\n상점에서 포지션 변경권을 구매한 뒤에 다시 시도해 주세요.',
      { title: '포지션 변경', icon: 'fa-user-shield' });
    return;
  }
  const msg = tickets
    ? `포지션을 ${c.role} → ${role}(으)로 변경하시겠어요?\n포지션 변경권 1개가 차감됩니다. (보유 ${tickets}개)`
    : `포지션을 ${c.role} → ${role}(으)로 변경하시겠어요?\n운영진 권한으로 변경권 없이 바꿉니다.`;
  const ok = await uiConfirm(msg, { title: '포지션 변경', okText: '변경', icon: 'fa-user-shield' });
  if (ok) socket.emit('change_position', { name: c.name, role });
}

// ---- 스킬 이펙트 : 스킬을 쓰면 모두의 화면 중앙에 딤 + 글/이미지 컷인이 뜹니다. ----
let skillLogTypeLocal = null;  // 이미지 탭으로 바꿨지만 아직 이미지를 안 올렸을 때 화면 유지용
function myPageSkillData(c) {
  const d = (lastRosterMypage || {})[c.name] || {};
  return {
    type: skillLogTypeLocal || d.skill_log_type || c.skill_log_type || 'text',
    title: d.skill_log_title || '',
    body: d.skill_log_text != null ? d.skill_log_text : (c.skill_log_text || ''),
    image: d.skill_log_image || null,
    catchphrase: d.catchphrase || '',
    motion: 'slash',
  };
}
function saveCatchphrase() {
  if (!canEditMyPage()) return;
  socket.emit('set_my_skill_log', { name: myPageEditName(), catchphrase: document.getElementById('myPageCatchphrase').value.trim() });
}
function renderMyPageSkillLog(c, canEdit) {
  const fx = myPageSkillData(c);
  document.querySelectorAll('#myPageSkillLogType button').forEach(b => {
    b.classList.toggle('on', b.dataset.v === fx.type);
    b.disabled = !canEdit;
  });
  document.getElementById('myPageSkillText').style.display = fx.type === 'text' ? '' : 'none';
  document.getElementById('myPageSkillImage').style.display = fx.type === 'image' ? '' : 'none';
  const title = document.getElementById('myPageSkillLogTitle');
  const body = document.getElementById('myPageSkillLogText');
  title.disabled = !canEdit;
  body.contentEditable = canEdit ? 'true' : 'false';
  if (document.activeElement !== title) title.value = fx.title;
  if (document.activeElement !== body && body.innerHTML !== fx.body) body.innerHTML = fx.body;
  const img = document.getElementById('myPageSkillImagePreview');
  img.style.display = fx.image ? '' : 'none';
  if (fx.image && img.getAttribute('src') !== fx.image) img.src = fx.image;
  document.getElementById('myPageSkillImageEmpty').style.display = fx.image ? 'none' : '';
  document.getElementById('myPageSkillImageClear').disabled = !canEdit || !fx.image;
  document.getElementById('myPageSkillImageBox').style.cursor = canEdit ? 'pointer' : 'default';
  const cp = document.getElementById('myPageCatchphrase');
  cp.disabled = !canEdit;
  if (document.activeElement !== cp) cp.value = fx.catchphrase;
}
function setSkillLogType(type) {
  if (!canEditMyPage()) return;
  skillLogTypeLocal = type;
  socket.emit('set_my_skill_log', { name: myPageEditName(), skill_log_type: type });
  renderMyPage();
}
function skillLogFormat(cmd) {
  document.getElementById('myPageSkillLogText').focus();
  document.execCommand(cmd);
}
function saveSkillLogText() {
  if (!canEditMyPage()) return;
  socket.emit('set_my_skill_log', {
    name: myPageEditName(),
    skill_log_title: document.getElementById('myPageSkillLogTitle').value.trim(),
    skill_log_text: document.getElementById('myPageSkillLogText').innerHTML,
  });
}
function onSkillImageChosen(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file || !canEditMyPage()) return;
  if (!/\.(png|apng|gif|webp)$/i.test(file.name)) { showError('png(apng)/gif/webp 이미지만 올릴 수 있어요.'); return; }
  if (file.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  file.arrayBuffer().then(buf => socket.emit('set_my_skill_log', {
    name: myPageEditName(), skill_log_type: 'image', image_data: buf, filename: file.name,
  }));
}
async function clearSkillLogImage() {
  if (!canEditMyPage()) return;
  const ok = await uiConfirm('스킬 이펙트 이미지를 삭제할까요?', { title: '이미지 삭제', okText: '삭제', danger: true, icon: 'fa-trash' });
  if (ok) socket.emit('set_my_skill_log', { name: myPageEditName(), clear_image: true });
}
function previewSkillCutin() {
  const c = myPageTargetChar();
  if (!c) return;
  const fx = myPageSkillData(c);
  if (fx.type === 'text') {
    fx.title = document.getElementById('myPageSkillLogTitle').value.trim();
    fx.body = document.getElementById('myPageSkillLogText').innerHTML;
  }
  fx.catchphrase = document.getElementById('myPageCatchphrase').value.trim();
  if (fx.type === 'image' ? !fx.image : !(fx.catchphrase || fx.title || fx.body.replace(/<[^>]*>/g, '').trim())) {
    showError(fx.type === 'image' ? '먼저 이미지를 올려 주세요.' : '먼저 캐치프레이즈나 스킬명을 써 주세요.');
    return;
  }
  showSkillCutin({ ...fx, actor: displayNameOf(c), color: c.color });
}
let skillCutinTimer = null;
function showSkillCutin(fx) {
  const el = document.getElementById('skillCutin');
  const band = document.getElementById('skillCutinBand');
  const esc = t => String(t || '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const motion = 'slash';   // 컷인 등장 모션은 고르지 않고 모두 기본 연출로
  // 이름 + 캐치프레이즈(공통), 그 아래 글(스킬명 · 본문) 또는 이미지
  // 이름 : 글자 뒤로 윤곽선 잔상 두 겹이 퍼지는 레이어드 타이포 (data-t를 ::before/::after가 그대로 씁니다)
  const head = `<div class="ci-name" data-t="${esc(fx.actor)}"><span>${esc(fx.actor)}</span></div>`
    + (fx.catchphrase ? `<div class="ci-phrase">${esc(fx.catchphrase)}</div>` : '');
  let main = '';
  if (fx.type === 'image') {
    const u = esc(fx.image).replace(/'/g, '%27');
    // 그림 : HUD 프레임(모서리 꺾쇠 · 이중 테두리 · 눈금 · 훑는 빛 · 이름표)이 그려지며 열립니다
    main = `<div class="ci-frame"><img class="ci-img" src="${u}" alt=""><i class="ci-scan"></i>
      <i class="ck tl"></i><i class="ck tr"></i><i class="ck bl"></i><i class="ck br"></i>
      <i class="tk t"></i><i class="tk b"></i><i class="tk l"></i><i class="tk r"></i>
      <span class="ci-tag">SKILL<b>${esc(fx.title || '')}</b></span></div>`;
  } else if (fx.title || (fx.body || '').replace(/<[^>]*>/g, '').trim()) {
    // 본문은 서버에서 굵게/기울임만 남기고 정리된 HTML입니다(미리 보기는 내 화면에서만 표시).
    main = `<div class="ci-skill">${fx.title ? `<div class="ci-title"><em>SKILL</em>${esc(fx.title)}</div>` : ''}${fx.body ? `<div class="ci-body">${fx.body}</div>` : ''}</div>`;
  }
  // 배경 효과 층 : 크게 흐르는 윤곽선 워터마크 + 모션별 효과(::before/::after)
  const wm = esc(fx.title || fx.actor || '');
  document.getElementById('skillCutinFx').innerHTML = wm ? `<div class="ci-wm"><span>${wm}&nbsp;&nbsp;·&nbsp;&nbsp;${wm}&nbsp;&nbsp;·&nbsp;&nbsp;${wm}&nbsp;&nbsp;·&nbsp;&nbsp;</span></div>` : '';
  band.innerHTML = fx.type === 'image' ? `${main}<div class="ci-head">${head}</div>` : `<div class="ci-head">${head}</div>${main}`;
  el.className = 'skill-cutin';
  void el.offsetWidth;  // 애니메이션을 처음부터 다시 재생
  el.className = `skill-cutin show m-${motion} ${fx.type === 'image' ? 'image' : 'text'}`;
  clearTimeout(skillCutinTimer);
  skillCutinTimer = setTimeout(hideSkillCutin, 3000);
}
function hideSkillCutin() {
  clearTimeout(skillCutinTimer);
  document.getElementById('skillCutin').className = 'skill-cutin';
}
socket.on('skill_cutin', (d) => {
  // 여러 명이 거의 동시에 스킬을 써도 컷인은 한 명씩 : 앞 컷인(3초)이 끝난 뒤 다음 사람
  fxSchedule(() => {
    const c = sfxCharacter(d.actor);
    showSkillCutin({ ...d, actor: c ? displayNameOf(c) : d.actor });
  }, 3300, 'cutin');
});

// 효과음은 지금은 등록(파일 업로드)/미리듣기만 지원합니다 - 행동마다 실제로 재생하는 기능은
// 나중에 추가되고, 그때 공통 효과음이 기본이며 여기서 등록한 사람만 자기 행동에 한해 이
// 파일+음량을 쓰게 됩니다.
const SOUND_EFFECT_MAX_BYTES = UPLOAD_AUDIO_BYTES;
const SOUND_EFFECT_MAX_SECONDS = 6;

function onMySoundEffectFileChosen(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (!canEditMyPage()) {
    showError('로그인한 뒤에 효과음을 등록할 수 있습니다.');
    return;
  }
  if (file.size > SOUND_EFFECT_MAX_BYTES) {
    showError(`파일이 너무 큽니다 (최대 ${Math.floor(SOUND_EFFECT_MAX_BYTES / (1024 * 1024))}MB).`);
    return;
  }
  const c = myPageTargetChar();
  if (!c) return;
  const fd = new FormData();
  fd.append('room_id', ROOM_ID);
  fd.append('key', KEY);
  fd.append('name', c.name);
  fd.append('file', file);
  fetch('/upload_sound_effect', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => { if (data.error) showError(data.error); })
    .catch(() => showError('효과음 업로드에 실패했습니다.'));
}

// 본인에게만 들리는 미리듣기 - 서버로 보내지 않고 이 브라우저에서만 재생하고, 아무리 길어도
// 6초가 지나면 멈춥니다.
let myPagePreviewAudio = null;
function previewMySoundEffect() {
  const c = myPageTargetChar();
  if (!c || !c.sound_effect) return;
  if (myPagePreviewAudio) { myPagePreviewAudio.pause(); myPagePreviewAudio = null; }
  const audio = new Audio(c.sound_effect);
  audio.volume = (c.sound_effect_volume != null ? c.sound_effect_volume : 100) / 100;
  myPagePreviewAudio = audio;
  audio.play().catch(() => showError('효과음을 재생할 수 없습니다.'));
  setTimeout(() => {
    if (myPagePreviewAudio === audio) { audio.pause(); myPagePreviewAudio = null; }
  }, SOUND_EFFECT_MAX_SECONDS * 1000);
}

function onMySoundEffectVolumeChange() {
  if (!canEditMyPage()) return;
  socket.emit('set_my_sound_effect_volume', {
    name: myPageEditName(),
    sound_effect_volume: parseInt(document.getElementById('myPageSoundVolume').value, 10),
  });
}

function onMyPageGmFieldChange() {
  if (myControlInfo(lastBattleForPanel).scope !== 'all') return;
  const c = myPageTargetChar();
  if (!c) return;
  socket.emit('set_mypage_gm_fields', {
    name: c.name,
    current_hp: parseInt(document.getElementById('myPageCurrentHpInput').value, 10),
  });
}

// 프로필 이미지는 본인(캐릭터로 직접 로그인한 사람)만 등록할 수 있고, 반드시 정사각형이어야
// 합니다(가로/세로 다르면 거부) - 투명 배경을 쓸 수 있도록 png/webp/gif만 허용합니다.
function onMyAvatarFileChosen(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (!canEditMyPage()) {
    showError('로그인한 뒤에 프로필 이미지를 등록할 수 있습니다.');
    return;
  }
  const c = myPageTargetChar();
  if (!c) return;
  if (file.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  const objUrl = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    URL.revokeObjectURL(objUrl);
    if (img.width !== img.height) {
      showError('정사각형 이미지만 등록할 수 있습니다.');
      return;
    }
    const fd = new FormData();
    fd.append('room_id', ROOM_ID);
    fd.append('key', KEY);
    fd.append('name', c.name);
    fd.append('file', file);
    fetch('/upload_avatar', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => { if (data.error) showError(data.error); })
      .catch(() => showError('이미지 업로드에 실패했습니다.'));
  };
  img.onerror = () => { URL.revokeObjectURL(objUrl); showError('이미지를 열 수 없습니다.'); };
  img.src = objUrl;
}

function onVolumeChange(value) {
  musicVolume = parseInt(value, 10);
  localStorage.setItem('musicVolume', musicVolume);
  applyVolume();
  refreshVolumeUi();
}

// 슬라이더의 채워진 부분(왼쪽 파란색) 길이를 현재 값에 맞춥니다.
function paintRange(el) {
  if (!el) return;
  const min = parseFloat(el.min || 0), max = parseFloat(el.max || 100);
  el.style.setProperty('--fill', `${((parseFloat(el.value) - min) / (max - min)) * 100}%`);
}

let musicVolumeBeforeMute = null;
function toggleMusicMute() {
  if (musicVolume > 0) {
    musicVolumeBeforeMute = musicVolume;
    onVolumeChange(0);
  } else {
    onVolumeChange(musicVolumeBeforeMute || 70);
  }
  const slider = document.getElementById('musicVolumeSlider');
  if (slider) slider.value = musicVolume;
  refreshVolumeUi();
}

function toggleSoundPop(e) {
  if (e) e.stopPropagation();
  const w = document.getElementById('sbSound'); if (!w) return;
  w.classList.toggle('open');
  if (w.classList.contains('open')) { const sl = document.getElementById('sbVolSlider'); if (sl) sl.value = musicVolume; refreshVolumeUi(); }
}
document.addEventListener('click', (e) => { const w = document.getElementById('sbSound'); if (w && w.classList.contains('open') && !w.contains(e.target)) w.classList.remove('open'); });
function refreshVolumeUi() {
  paintRange(document.getElementById('musicVolumeSlider'));
  const sbs = document.getElementById('sbVolSlider');
  if (sbs) { sbs.value = musicVolume; paintRange(sbs); }
  const sbn = document.getElementById('sbVolNum'); if (sbn) sbn.textContent = musicVolume;
  const sbIcon = musicVolume === 0 ? 'fa-volume-xmark' : (musicVolume < 40 ? 'fa-volume-low' : 'fa-volume-high');
  ['sidebarSoundBtn'].forEach(id => { const b = document.getElementById(id); const i = b && b.querySelector('i'); if (i) i.className = `fa-solid ${sbIcon}`; });
  try { updateMusicStatusText(); } catch (e) {}   // 팝업 막대도 바로 맞춰요
  const num = document.getElementById('musicVolumeNum');
  if (num) num.textContent = musicVolume;
  const btn = document.getElementById('musicMuteBtn');
  if (btn) {
    const icon = musicVolume === 0 ? 'fa-volume-xmark' : (musicVolume < 40 ? 'fa-volume-low' : 'fa-volume-high');
    btn.innerHTML = `<i class="fa-solid ${icon}"></i>`;
  }
}

function applyVolume() {
  // 기숙사 방 음악이 나오는 동안에는 전투 배경음악을 잠시 0으로 낮춥니다.
  const v = (typeof dormMusicActive !== 'undefined' && dormMusicActive) ? 0 : musicVolume;
  const audio = document.getElementById('mp3Player');
  if (audio) audio.volume = v / 100;
  if (ytPlayer && ytPlayer.setVolume) { try { ytPlayer.setVolume(v); } catch (e) {} }
  if (typeof dormAudio !== 'undefined' && dormAudio) dormAudio.volume = musicVolume / 100;
}

(function loadYouTubeApi() {
  if (window.YT && window.YT.Player) { ytApiReady = true; return; }
  const tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(tag);
  window.onYouTubeIframeAPIReady = () => { ytApiReady = true; };
})();

function updateMusicStatusText() {
  const statusEl = document.getElementById('musicStatus');
  if (!statusEl) return;
  const player = document.getElementById('bgmPlayer');
  const kicker = document.getElementById('musicKicker');
  if (!musicState) {
    statusEl.textContent = '재생 없음';
    if (player) player.classList.remove('playing');
    if (kicker) kicker.textContent = 'BGM';
    return;
  }
  const audio = document.getElementById('mp3Player');
  let playing = false;
  if (musicState.type === 'mp3') {
    playing = !!(audio && audio.src && !audio.paused && !audio.ended);
  } else if (musicState.type === 'youtube') {
    playing = !!(ytPlayer && ytPlayer.getPlayerState && ytPlayer.getPlayerState() === 1);
  }
  const title = musicState.title || '배경음악';
  statusEl.textContent = title;
  statusEl.parentElement.title = title;
  if (player) player.classList.toggle('playing', playing);
  if (kicker) kicker.textContent = playing ? 'NOW PLAYING' : 'PAUSED';
  sbEqSync(playing);
}
setInterval(updateMusicStatusText, 1000);
// 사이드바 음량 팝업의 막대(마이룸 음악과 같은 모양) : 음악이 나오면 움직이고, 음소거면 납작하게
function sbEqSync(playing) {
  const eq = document.getElementById('sbEq'); if (!eq) return;
  eq.classList.toggle('muted', musicVolume === 0);
  eq.classList.toggle('playing', !!playing && musicVolume > 0);
}
// 브라우저는 사용자가 화면을 한 번 누르기 전까지 소리 자동 재생을 막아요(그래서 노래가 안 나왔어요).
// 처음 누르거나 키를 칠 때, 나와야 하는데 멈춰 있는 배경음악 · 방 음악을 다시 틀어요.
function musicKick() {
  try {
    if (typeof dormAutoBlocked !== 'undefined' && dormAutoBlocked && dormAudio) {
      dormAutoBlocked = false; dormMusicPaused = false;
      dormAudio.play().then(() => { dormMusicActive = true; applyVolume(); renderDormMusicBtn(); }).catch(() => {});
    }
    if (!musicState) return;
    if (musicState.type === 'mp3') {
      const a = document.getElementById('mp3Player');
      if (!a) return;
      if (!a.getAttribute('src')) startMusicPlayback();
      else if (a.paused) { applyVolume(); a.play().then(updateMusicStatusText).catch(() => {}); }
    } else if (musicState.type === 'youtube') {
      if (!ytPlayer && ytApiReady) startMusicPlayback();
      else if (ytPlayer && ytPlayer.getPlayerState && ![1, 3].includes(ytPlayer.getPlayerState())) { applyVolume(); ytPlayer.playVideo(); }
    }
  } catch (e) {}
}
['pointerdown', 'keydown', 'touchend'].forEach(ev => document.addEventListener(ev, musicKick, { capture: true, passive: true }));

function renderMusic(music, serverNow) {
  updateServerTimeOffset(serverNow);
  const key = music ? `${music.type}:${music.src}:${music.started_at}` : null;
  if (key === musicKey) {
    // 같은 곡이면 재생은 그대로 두고, 표시 이름만 바뀐 경우를 반영합니다.
    if (music && musicState && music.title !== musicState.title) { musicState = music; updateMusicStatusText(); }
    return;
  }
  musicKey = key;
  musicState = music;
  stopLocalPlayback();
  if (!music) {
    updateMusicStatusText();
    return;
  }
  startMusicPlayback();
  updateMusicStatusText();
}

function stopLocalPlayback() {
  const audio = document.getElementById('mp3Player');
  if (audio) { audio.pause(); audio.removeAttribute('src'); }
  if (ytPlayer) { try { ytPlayer.stopVideo(); } catch (e) {} }
  updateMusicStatusText();
}

function currentElapsedSeconds() {
  const nowServer = Date.now() / 1000 + serverTimeOffset;
  return Math.max(0, nowServer - musicState.started_at);
}

function startMusicPlayback() {
  if (!musicState) return;

  if (musicState.type === 'mp3') {
    const audio = document.getElementById('mp3Player');
    audio.src = musicState.src;
    audio.loop = true;
    const seekAndPlay = () => {
      const dur = audio.duration || 0;
      const elapsed = currentElapsedSeconds();
      audio.currentTime = dur > 0 ? (elapsed % dur) : 0;
      applyVolume();
      audio.play().then(updateMusicStatusText).catch(updateMusicStatusText);
    };
    if (audio.readyState >= 1) seekAndPlay();
    else audio.addEventListener('loadedmetadata', seekAndPlay, { once: true });
  } else if (musicState.type === 'youtube') {
    const elapsed = currentElapsedSeconds();
    const create = () => {
      if (ytPlayer) {
        ytPlayer.loadVideoById({ videoId: musicState.src, startSeconds: elapsed });
        applyVolume();
      } else {
        ytPlayer = new YT.Player('youtubePlayer', {
          width: 200, height: 113,
          videoId: musicState.src,
          playerVars: { autoplay: 1, loop: 1, playlist: musicState.src, start: Math.floor(elapsed) },
          events: {
            onReady: (e) => {
              e.target.playVideo();
              applyVolume();
              setTimeout(updateMusicStatusText, 1200);
            },
            onStateChange: (e) => {
              if (e.data === YT.PlayerState.ENDED) {
                ytPlayer.seekTo(0, true);
                ytPlayer.playVideo();
              }
              updateMusicStatusText();
            },
          },
        });
      }
    };
    if (ytApiReady) create();
    else {
      const check = setInterval(() => {
        if (ytApiReady) { clearInterval(check); create(); }
      }, 200);
    }
  }
}
// ==================================================================
// 상점 : 참가자(상점/소지품) + 운영진(상품 관리/재화·소지품/처리 요청)
// ==================================================================
let lastShop = null;          // {items, effect_labels, timing_labels, stat_keys}
let lastShopRequests = [];    // 운영진 전용
let shopTab = 'shop';
let shopGmTarget = '';        // 운영진이 상점/소지품 탭에서 대신 조작할 캐릭터

function shopIsGm() { return myControlInfo(lastBattleForPanel).scope === 'all'; }
function shopEsc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
function shopTargetName() { return shopIsGm() ? (shopGmTarget || null) : myLoggedInName(); }
function shopCharData(name) { return name ? (lastRosterMypage[name] || null) : null; }
function shopItemById(id) { return (lastShop && lastShop.items || []).find(it => it.id === id) || null; }

function showShopToast(msg) { uiToast(msg); }
socket.on('shop_result', (d) => showShopToast(d.message));

function openShop(tab) {
  if (tab) shopTab = tab;
  document.getElementById('shopModal').style.display = 'flex';
  renderShop();
}
function closeShop() { document.getElementById('shopModal').style.display = 'none'; }
function setShopTab(tab) { shopTab = tab; renderShop(); }

// 상품 아이콘 : 이미지 대신 아이콘만(운영진이 상품 관리에서 골라요)
let shopIconPickFor = null;
function shopIconHtml(it, editable) {
  const ic = (it && it.icon) || 'fa-box';
  return editable
    ? `<button class="shop-icon editable ${shopIconPickFor === it.id ? 'on' : ''}" onclick="shopIconPickFor = shopIconPickFor === '${it.id}' ? null : '${it.id}'; renderShop()" data-tip="아이콘 고르기"><i class="fa-solid ${ic}"></i></button>`
    : `<span class="shop-icon"><i class="fa-solid ${ic}"></i></span>`;
}
function shopIconPickerHtml(it) {
  const list = (lastShop && lastShop.icon_choices) || [];
  return `<div class="shop-icon-pick">${list.map(ic => `<button class="${ic === it.icon ? 'on' : ''}" onclick="shopIconPickFor=null; shopEditItem('${it.id}', {icon:'${ic}'})"><i class="fa-solid ${ic}"></i></button>`).join('')}</div>`;
}
// 사용 시점 · 효과를 한 줄 글로(예: 전투 중 · 체력 회복 50)
function shopMetaText(it) {
  const tl = (lastShop && lastShop.timing_labels) || {};
  const el = (lastShop && lastShop.effect_labels) || {};
  let eff = el[it.effect] || it.effect;
  if (it.effect === 'heal') eff += ` ${it.value}`;
  if (it.effect === 'stat_up') eff += ` +${it.value}`;
  return `${shopEsc(tl[it.timing] || it.timing)} · ${shopEsc(eff)}`;
}

function renderShop() {
  const modal = document.getElementById('shopModal');
  if (!modal || modal.style.display !== 'flex') return;
  const gm = shopIsGm();
  if (shopTab === 'inventory' || (!gm && ['items', 'wallets', 'requests'].includes(shopTab))) shopTab = 'shop';

  // 상단 지갑 : 참가자는 본인 P, 운영진은 대신 조작할 캐릭터 선택
  const wallet = document.getElementById('shopWallet');
  const target = shopTargetName();
  const data = shopCharData(target);
  if (gm) {
    const opts = ['<option value="">(캐릭터 선택)</option>'].concat(
      (lastRoster || []).map(n => `<option value="${shopEsc(n)}" ${n === shopGmTarget ? 'selected' : ''}>${shopEsc(n)}</option>`));
    wallet.innerHTML = `<span>대상</span><select onchange="shopGmTarget=this.value; renderShop();">${opts.join('')}</select>` +
      (data ? `<span class="pts"><b>${data.points || 0}</b>P</span>` : '');
  } else {
    wallet.innerHTML = target ? `<span>${shopEsc(target)}</span><span class="pts"><b>${data ? (data.points || 0) : 0}</b>P</span>` : '<span>로그인 필요</span>';
  }

  const pending = (lastShopRequests || []).filter(r => !r.done).length;
  const tabs = [['shop', '상점', '', 0, 'fa-store']];   // 소지품은 상점 카드마다 보유 개수 · 사용으로 합쳤어요
  if (gm) tabs.push(['items', '상품 관리', 'gm', 0, 'fa-tags'], ['wallets', '재화·소지품', 'gm', 0, 'fa-coins'], ['requests', '처리 요청', 'gm', pending, 'fa-inbox']);
  document.getElementById('shopTabs').style.display = tabs.length > 1 ? '' : 'none';   // 참가자는 상점 하나라 탭 줄 없이
  document.getElementById('shopTabs').innerHTML = tabs.map(([k, label, cls, cnt, ic], i) =>
    (cls === 'gm' && i === 1 ? '<span class="shop-tab-sep">운영진</span>' : '') +
    `<button class="shop-tab ${cls || ''} ${shopTab === k ? 'active' : ''}" onclick="setShopTab('${k}')"><i class="fa-solid ${ic}"></i>${label}${cnt ? `<span class="cnt">${cnt}</span>` : ''}</button>`).join('');

  const body = document.getElementById('shopBody');
  // 입력 중인 칸이 있으면(운영진 편집) 다시 그리지 않아 입력이 끊기지 않게 합니다.
  if (body.contains(document.activeElement) && ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
  const scroll = body.scrollTop;
  if (!lastShop) { body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '상점을 불러오는 중이에요'); return; }
  if (shopTab === 'shop') body.innerHTML = renderShopList(target, data);
  else if (shopTab === 'items') body.innerHTML = renderShopItemsAdmin();
  else if (shopTab === 'wallets') body.innerHTML = renderShopWallets();
  else if (shopTab === 'requests') body.innerHTML = renderShopRequests();
  body.scrollTop = scroll;
}

function renderShopList(target, data) {
  const items = lastShop.items || [];
  const mine = (data && data.items) || {};
  // 판매가 끝났지만 아직 가지고 있는 상품은 맨 아래에 따로
  const gone = Object.entries(mine).filter(([id, n]) => n > 0 && !shopItemById(id));
  if (!items.length && !gone.length) return emptyHtml('fa-store', '판매 중인 상품이 없어요', '운영진이 상품을 올리면 여기에 보여요.');
  const points = data ? (data.points || 0) : 0;
  const statKeys = lastShop.stat_keys || [];
  const cards = items.map(it => {
    const can = !!target && points >= it.price;
    const owned = mine[it.id] || 0;
    let extra = '';
    if (owned && it.effect === 'stat_up') extra = `<select id="shopStat_${it.id}">${statKeys.map(k => `<option>${k}</option>`).join('')}</select>`;
    if (owned && it.effect === 'request') extra = `<input id="shopMemo_${it.id}" maxlength="200" placeholder="요청 내용 (선택)">`;
    const use = !owned ? '' : it.effect === 'role_change'
      ? `<button class="shop-btn ghost" onclick="closeShop(); openMyPage();">마이페이지에서 사용</button>`
      : `<button class="shop-btn ghost" onclick="shopUse('${it.id}')">사용</button>`;
    return `<div class="shop-card ${owned ? 'has' : ''}">
      <div class="sc-head">${shopIconHtml(it, false)}
        <div class="sc-title"><b>${shopEsc(it.name)}</b><span>${shopMetaText(it)}</span></div>
        <span class="sc-price">${it.price}<small>P</small></span></div>
      <p class="sc-desc">${shopEsc(it.desc)}</p>
      ${extra ? `<div class="sc-foot sc-use">${extra}</div>` : ''}
      <div class="sc-foot">${target ? `<span class="sc-owned ${owned ? 'on' : ''}"><i class="fa-solid fa-briefcase"></i>보유 ${owned}개</span>` : ''}
        ${use}<button class="shop-btn" ${can ? '' : 'disabled'} onclick="shopBuy('${it.id}')">구매</button></div>
    </div>`;
  });
  gone.forEach(([id, n]) => cards.push(`<div class="shop-card has"><div class="sc-head"><span class="shop-icon"><i class="fa-solid fa-ban"></i></span>
      <div class="sc-title"><b>삭제된 상품</b><span>판매가 끝난 상품이에요</span></div><span class="sc-count">×${n}</span></div></div>`));
  return '<div class="shop-grid">' + cards.join('') + '</div>';
}

// 빈 화면(공통) : 아이콘 · 제목 · 설명 · 버튼([글자, onclick, 아이콘])
function emptyHtml(icon, title, desc, btn, small) {
  return `<div class="empty-state${small ? ' sm' : ''}"><span class="es-ic"><i class="fa-solid ${icon}"></i></span><b class="es-t">${title}</b>`
    + (desc ? `<span class="es-d">${desc}</span>` : '')
    + (btn ? `<button type="button" class="es-btn" onclick="${btn[1]}">${btn[2] ? `<i class="fa-solid ${btn[2]}"></i>` : ''}${btn[0]}</button>` : '') + '</div>';
}
function renderShopItemsAdmin() {
  const el = lastShop.effect_labels || {}, tl = lastShop.timing_labels || {};
  const sel = (map, cur) => Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${shopEsc(v)}</option>`).join('');
  const rows = (lastShop.items || []).map(it => `<div class="shop-edit">
      ${shopIconHtml(it, true)}
      <input value="${shopEsc(it.name)}" maxlength="30" onchange="shopEditItem('${it.id}', {name:this.value})" placeholder="이름">
      <input type="number" min="0" value="${it.price}" onchange="shopEditItem('${it.id}', {price:this.value})" data-tip="가격(P)">
      <select onchange="shopEditItem('${it.id}', {effect:this.value})">${sel(el, it.effect)}</select>
      <select onchange="shopEditItem('${it.id}', {timing:this.value})">${sel(tl, it.timing)}</select>
      <input type="number" value="${it.value}" onchange="shopEditItem('${it.id}', {value:this.value})" data-tip="효과 수치 (회복량 / 스탯 증가량)" ${it.effect === 'request' ? 'disabled' : ''}>
      <div class="ops">
        <button class="shop-ico-btn" onclick="shopMoveItem('${it.id}',-1)"><i class="fa-solid fa-arrow-up"></i></button>
        <button class="shop-ico-btn" onclick="shopMoveItem('${it.id}',1)"><i class="fa-solid fa-arrow-down"></i></button>
        <button class="shop-ico-btn danger" onclick="shopDeleteItem('${it.id}')"><i class="fa-solid fa-trash-can"></i></button>
      </div>
      <input class="desc" value="${shopEsc(it.desc)}" maxlength="200" onchange="shopEditItem('${it.id}', {desc:this.value})" placeholder="설명">
      ${shopIconPickFor === it.id ? shopIconPickerHtml(it) : ''}
    </div>`).join('');
  return `<div class="shop-toolbar"><span>고치면 바로 저장돼요 · 아이콘 칸을 누르면 아이콘을 고를 수 있어요</span>
      <div style="flex:1"></div><button class="shop-btn" onclick="shopAddItem()"><i class="fa-solid fa-plus"></i> 상품 추가</button></div>
    <div class="shop-edit-head"><span>아이콘</span><span>이름</span><span>가격(P)</span><span>효과</span><span>사용 시점</span><span>수치</span><span></span></div>
    ${rows || emptyHtml('fa-tags', '상품이 없어요', '위에서 새 상품을 추가해 주세요.', null, true)}`;
}

let shopWalletQuery = '';
function renderShopWallets() {
  const q = shopWalletQuery.trim().toLowerCase();
  const names = (lastRoster || []).filter(n => !q || n.toLowerCase().includes(q));
  if (!names.length) return emptyHtml('fa-users', '등록된 캐릭터가 없어요');
  const itemOpts = (lastShop.items || []).map(it => `<option value="${it.id}">${shopEsc(it.name)}</option>`).join('');
  const rows = names.map(n => {
    const d = lastRosterMypage[n] || {};
    const chips = Object.entries(d.items || {}).filter(([, c]) => c > 0).map(([id, c]) => {
      const it = shopItemById(id);
      const nm = it ? it.name : '삭제된 상품';
      return `<span class="shop-chip">${shopEsc(nm)} ×${c}<button onclick="shopGive('${shopEsc(n)}','${id}',-1)" data-tip="1개 회수">−</button><button onclick="shopGive('${shopEsc(n)}','${id}',1)" data-tip="1개 지급">+</button></span>`;
    }).join('');
    const key = encodeURIComponent(n).replace(/[^a-zA-Z0-9]/g, '_');
    return `<div class="shop-char">
      <span class="shop-char-name">${shopEsc(n)}</span>
      <span class="shop-char-pts"><input type="number" min="0" value="${d.points || 0}" onchange="shopSetPoints('${shopEsc(n)}', this.value)" data-tip="보유 P (고치면 바로 저장)">P</span>
      <div class="shop-char-items">${chips || '<span class="none">소지품 없음</span>'}</div>
      <span class="shop-char-give"><select id="shopGiveSel_${key}">${itemOpts}</select>
        <button class="shop-ico-btn" onclick="shopGive('${shopEsc(n)}', document.getElementById('shopGiveSel_${key}').value, 1)" data-tip="아이템 1개 지급"><i class="fa-solid fa-gift"></i></button></span>
    </div>`;
  }).join('');
  return `<div class="shop-toolbar">
      <input type="text" placeholder="이름 검색" value="${shopEsc(shopWalletQuery)}" oninput="shopWalletQuery=this.value; const b=document.getElementById('shopBody'); const s=this.selectionStart; b.innerHTML=renderShopWallets(); const i=b.querySelector('.shop-toolbar input[type=text]'); i.focus(); i.setSelectionRange(s,s);" style="width:160px;">
      <div style="flex:1"></div>
      <span>전원 P</span><input type="number" id="shopBulkPoints" value="100">
      <button class="shop-btn ghost sm" onclick="shopBulkPoints(1)"><i class="fa-solid fa-plus"></i> 지급</button>
      <button class="shop-btn ghost sm" onclick="shopBulkPoints(-1)"><i class="fa-solid fa-minus"></i> 차감</button></div>
    ${rows || emptyHtml('fa-magnifying-glass', '검색 결과가 없어요', '다른 이름으로 찾아보세요.', null, true)}`;
}

function renderShopRequests() {
  const reqs = lastShopRequests || [];
  if (!reqs.length) return emptyHtml('fa-inbox', '들어온 요청이 없어요', '참가자가 아이템 사용을 요청하면 여기에 쌓여요.');
  return reqs.map(r => `<div class="shop-req ${r.done ? 'done' : ''}">
      <span class="when">${shopEsc(r.time)}</span>
      <div class="what"><b>${shopEsc(r.character)}</b> · ${shopEsc(r.item_name)}${r.memo ? `<div class="memo">${shopEsc(r.memo)}</div>` : ''}</div>
      <button class="shop-btn ${r.done ? 'ghost' : ''} sm" onclick="shopReqDone('${r.id}', ${!r.done})">${r.done ? '되돌리기' : '처리 완료'}</button>
    </div>`).join('');
}

// ---- 참가자 동작 ----
function shopPayloadName() { return shopIsGm() ? { name: shopGmTarget } : {}; }
function shopBuy(itemId) {
  const it = shopItemById(itemId);
  if (!it || !shopTargetName()) return;
  uiConfirm(`${it.name}을(를) ${it.price}P에 구매할까요?`, {title:'구매', okText:`${it.price}P 구매`, icon:'fa-cart-shopping'})
    .then(ok => ok && socket.emit('shop_buy', { item_id: itemId, qty: 1, ...shopPayloadName() }));
}
function shopUse(itemId) {
  const it = shopItemById(itemId);
  if (!it) return;
  const payload = { item_id: itemId, ...shopPayloadName() };
  if (it.effect === 'stat_up') payload.stat = document.getElementById(`shopStat_${itemId}`).value;
  if (it.effect === 'request') payload.memo = document.getElementById(`shopMemo_${itemId}`).value;
  const what = it.effect === 'stat_up' ? ` (${payload.stat} +${it.value})` : '';
  uiConfirm(`${it.name}${what}을(를) 사용할까요?`, {title:'아이템 사용', okText:'사용', icon:'fa-flask'})
    .then(ok => ok && socket.emit('shop_use', payload));
}

// ---- 운영진 동작 ----
function shopEditItem(id, fields) { socket.emit('shop_admin_item', { action: 'update', item_id: id, fields }); }
function shopAddItem() { socket.emit('shop_admin_item', { action: 'add', fields: { name: '새 상품', price: 100 } }); }
function shopMoveItem(id, delta) { socket.emit('shop_admin_item', { action: 'move', item_id: id, delta }); }
function shopDeleteItem(id) {
  const it = shopItemById(id);
  uiConfirm(`'${it ? it.name : ''}' 상품을 삭제할까요?\n이미 산 사람의 소지품에는 '삭제된 상품'으로 남아요.`, {title:'상품 삭제', okText:'삭제', danger:true})
    .then(ok => ok && socket.emit('shop_admin_item', { action: 'delete', item_id: id }));
}
function shopSetPoints(name, v) { socket.emit('shop_admin_points', { name, set: parseInt(v || '0', 10) }); }
function shopBulkPoints(sign) {
  const v = parseInt(document.getElementById('shopBulkPoints').value || '0', 10) * sign;
  if (!v) return;
  uiConfirm(`등록된 캐릭터 전원에게 ${v > 0 ? '+' : ''}${v}P 할까요?`, {title:'P 일괄 지급', okText:'적용', icon:'fa-coins'})
    .then(ok => ok && socket.emit('shop_admin_points', { names: lastRoster || [], delta: v }));
}
function shopGive(name, itemId, delta) { socket.emit('shop_admin_give', { name, item_id: itemId, delta }); }
function shopReqDone(id, done) { socket.emit('shop_admin_request', { request_id: id, done }); }

// ---- 마이페이지 재화/아이템 ----
function renderMyPagePoints() {
  if (document.getElementById('myPageModal').style.display !== 'flex') return;
  const c = myPageTargetChar();
  const d = c ? (lastRosterMypage[c.name] || {}) : {};
  const view = document.getElementById('myPagePointsView');
  const input = document.getElementById('myPagePointsInput');
  const gm = shopIsGm();
  view.textContent = `${d.points || 0}P`;
  view.style.display = gm ? 'none' : '';
  input.style.display = gm ? '' : 'none';
  if (document.activeElement !== input) input.value = d.points || 0;
  const esc = t => String(t).replace(/[&<>]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
  const items = Object.entries(d.items || {}).filter(([, n]) => n > 0)
    .map(([id, n]) => { const it = shopItemById(id); return `${esc(it ? it.name : '삭제된 상품')} ${n}`; });
  document.getElementById('myPageItemsView').innerHTML = items.length ? items.join(', ') : '<span style="color:var(--muted)">없음</span>';
}
function openShopFromMyPage() {
  if (myPageIsView()) return;  // 남의 마이페이지에서는 소지품을 보기만 합니다
  const c = myPageTargetChar();
  if (shopIsGm() && c) shopGmTarget = c.name;
  closeMyPage();
  openShop('shop');
}
function onMyPagePointsChange() {
  const c = myPageTargetChar();
  if (!c) return;
  socket.emit('shop_admin_points', { name: c.name, set: parseInt(document.getElementById('myPagePointsInput').value || '0', 10) });
}
// ==================================================================
// 격자 지도 배경 이미지 (운영진이 설정, 방 전체에 동일하게 표시)
// ==================================================================
let lastMapBg = null;
const MAP_BG_DEFAULTS = { url: null, mode: 'frame', dim: 40, line: 22 };
function mapBgCfg() { return Object.assign({}, MAP_BG_DEFAULTS, lastMapBg || {}); }

function applyMapBackground(preview) {
  const frame = document.querySelector('#gridSection .map-frame');
  const btn = document.getElementById('mapBgBtn');
  if (btn) btn.style.display = myControlInfo(lastBattleForPanel).scope === 'all' ? 'inline-flex' : 'none';
  if (!frame) return;
  const cfg = Object.assign(mapBgCfg(), preview || {});
  const table = frame.querySelector('.gmap');
  frame.style.setProperty('--grid-line', (cfg.line / 100).toFixed(2));
  const layer = cfg.url
    ? `linear-gradient(rgba(0,0,0,${cfg.dim / 100}), rgba(0,0,0,${cfg.dim / 100})), url('${cfg.url}')`
    : '';
  if (!cfg.url) {
    frame.style.background = '';
    if (table) table.style.background = '';
  } else if (cfg.mode === 'grid') {
    frame.style.background = '';
    if (table) { table.style.backgroundImage = layer; table.style.backgroundSize = '100% 100%'; table.style.backgroundPosition = 'center'; table.style.backgroundRepeat = 'no-repeat'; }
  } else {
    if (table) table.style.background = '';
    frame.style.backgroundImage = layer;
    frame.style.backgroundSize = 'cover';
    frame.style.backgroundPosition = 'center';
    frame.style.backgroundRepeat = 'no-repeat';
  }
}

function openMapBgModal() { document.getElementById('mapBgModal').style.display = 'flex'; renderMapBgModal(); }
function closeMapBgModal() { document.getElementById('mapBgModal').style.display = 'none'; applyMapBackground(); }
function renderMapBgModal() {
  if (document.getElementById('mapBgModal').style.display !== 'flex') return;
  const cfg = mapBgCfg();
  const pv = document.getElementById('mapBgPreview');
  pv.style.backgroundImage = cfg.url ? `url('${cfg.url}')` : '';
  document.getElementById('mapBgPreviewText').textContent = cfg.url ? '클릭해서 다른 이미지로 바꾸기' : `클릭해서 배경 이미지 올리기 (최대 ${UPLOAD_IMG_MB}MB)`;
  document.getElementById('mapBgModeFrame').classList.toggle('on', cfg.mode === 'frame');
  document.getElementById('mapBgModeGrid').classList.toggle('on', cfg.mode === 'grid');
  const dim = document.getElementById('mapBgDim'), line = document.getElementById('mapBgLine');
  if (document.activeElement !== dim) dim.value = cfg.dim;
  if (document.activeElement !== line) line.value = cfg.line;
  paintRange(dim); paintRange(line);
  onMapBgSlider();
  renderBossImgSection();
}
// 슬라이더를 움직이는 동안에는 내 화면에서만 미리 보여주고, 손을 떼면(change) 저장합니다.
function onMapBgSlider() {
  const dim = parseInt(document.getElementById('mapBgDim').value, 10);
  const line = parseInt(document.getElementById('mapBgLine').value, 10);
  document.getElementById('mapBgDimVal').textContent = `${dim}%`;
  document.getElementById('mapBgLineVal').textContent = `${line}%`;
  document.getElementById('mapBgPreviewDim').style.background = `rgba(0,0,0,${dim / 100})`;
  applyMapBackground({ dim, line });
}
function setMapBg(fields) { socket.emit('set_map_bg', fields); }
function onMapBgFileChosen(ev) {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  document.getElementById('mapBgPreviewText').textContent = '올리는 중...';
  f.arrayBuffer().then(buf => socket.emit('set_map_bg', { filename: f.name, data: buf }));
}
// ---- 2x2 몹(BOSS) 이미지 : 4칸이 한 세트로 이어지는 한 장의 이미지 ----
let lastBossImages = {};
let bossImgTargetKey = null;
function bossKeyOf(c) { return c && c.boss_group ? String(c.boss_group).split('#')[0] : null; }
function bossImageFor(c) { const k = bossKeyOf(c); return k ? (lastBossImages[k] || null) : null; }
function currentBossGroups() {
  const groups = {};
  const all = lastAllForCards || [];
  all.forEach(c => {
    const k = bossKeyOf(c);
    if (!k) return;
    if (!groups[k]) groups[k] = { key: k, members: [], fallback: null };
    groups[k].members.push(c.name);
    if (!groups[k].fallback && c.avatar_url) groups[k].fallback = c.avatar_url;
  });
  // 지금 전투에는 없어도 예전에 등록해 둔 몹 이미지는 보여줍니다(지우기 가능).
  Object.keys(lastBossImages || {}).forEach(k => { if (!groups[k]) groups[k] = { key: k, members: [], fallback: null }; });
  return Object.values(groups);
}
function renderBossImgSection() {
  const box = document.getElementById('bossImgSection');
  if (!box) return;
  const groups = currentBossGroups();
  const rows = groups.map(g => {
    const url = lastBossImages[g.key] || null;
    const esc = shopEsc(g.key);
    return `<div class="boss-img-row">
      <div class="boss-img-thumb" style="${url ? `background-image:url('${url}')` : ''}" onclick="pickBossImg('${esc}')"><i></i><i></i><i></i><i></i></div>
      <div class="boss-img-name">${esc}<small>${g.members.length ? `지금 전투: ${g.members.map(shopEsc).join(', ')}` : '지금 전투에는 없음'}${!url && g.fallback ? ' · 현재 프로필 이미지 사용 중' : ''}</small></div>
      ${url ? `<button class="shop-btn danger sm" onclick="clearBossImg('${esc}')">지우기</button>` : `<button class="shop-btn ghost sm" onclick="pickBossImg('${esc}')">등록</button>`}
    </div>`;
  }).join('');
  box.innerHTML = `<div class="boss-img-title">몹(2x2) 이미지</div>
    <div class="boss-img-hint">한 장을 올리면 4칸에 나눠서 이어지게 보여요. 정사각형 이미지를 권장해요. 같은 이름의 몹이면 다음 전투에도 그대로 쓰여요.</div>
    ${rows || '<div class="boss-img-hint">지금 전투에 2x2 몹이 없어요. (이름이 BOSS/NOVA로 시작하는 캐릭터)</div>'}`;
}
function pickBossImg(key) { bossImgTargetKey = key; document.getElementById('bossImgFileInput').click(); }
function clearBossImg(key) { uiConfirm(`'${key}' 몹 이미지를 지울까요?`, {title:'몹 이미지 삭제', okText:'지우기', danger:true}).then(ok => ok && socket.emit('set_boss_image', { key, clear: true })); }
function onBossImgChosen(ev) {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!f || !bossImgTargetKey) return;
  if (f.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  f.arrayBuffer().then(buf => socket.emit('set_boss_image', { key: bossImgTargetKey, filename: f.name, data: buf }));
}
// ==================================================================
// 공지사항 (벨 아이콘) : 모두 읽기, 운영진은 서식 있는 글쓰기/수정/삭제
// ==================================================================
let lastNotices = [];
let noticeEditingId = null;   // null이면 새 글, 문자열이면 그 글 수정 중
let noticeEditing = false;
const openNoticeIds = new Set();
const NOTICE_SEEN_KEY = 'noticeSeenAt';
function noticeSeenAt() { try { return parseFloat(localStorage.getItem(NOTICE_SEEN_KEY) || '0'); } catch (e) { return 0; } }
function markNoticesSeen() {
  const latest = Math.max(0, ...lastNotices.map(n => n.updated_at || n.created_at || 0));
  try { localStorage.setItem(NOTICE_SEEN_KEY, String(latest)); } catch (e) {}
  refreshNoticeDot();
}
function refreshNoticeDot() {
  const seen = noticeSeenAt();
  const hasNew = lastNotices.some(n => (n.updated_at || n.created_at || 0) > seen);
  document.getElementById('noticeDot').classList.toggle('on', hasNew);
  syncNewsDot();
}
socket.on('notices', (d) => {
  lastNotices = d.notices || [];
  // 공지는 처음에 모두 닫힌 채로(첫 공지를 자동으로 펼치지 않아요)
  refreshNoticeDot();
  if (document.getElementById('noticeModal').style.display === 'flex') {
    renderNotices();
    if (!noticeEditing) markNoticesSeen();
  }
});
socket.on('notice_saved', () => { noticeEditing = false; noticeEditingId = null; renderNotices(); showShopToast('공지사항을 저장했어요.'); });

function openNotices() {
  document.getElementById('noticeModal').style.display = 'flex';
  renderNotices();
  // 열어보기 전 기준으로 'NEW' 표시를 한 번 보여준 뒤 읽음 처리합니다.
  setTimeout(markNoticesSeen, 0);
}
function closeNotices() {
  const doClose = () => { noticeEditing = false; noticeEditingId = null; const m = document.getElementById('noticeModal'); m.style.display = 'none'; m.classList.remove('no-anim'); };
  if (!noticeEditing) { doClose(); return; }
  uiConfirm('작성 중인 내용이 사라져요. 닫을까요?', {title:'공지 닫기', okText:'닫기', danger:true}).then(ok => ok && doClose());
}
// 공지는 현실 날짜로 : 2026.10.16 PM 10:18
function fmtNoticeRealDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, '0'), h = d.getHours();
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${h < 12 ? 'AM' : 'PM'} ${p(h % 12 || 12)}:${p(d.getMinutes())}`;
}
function fmtNoticeDate(ts) {
  if (!ts) return '';
  return etStamp(new Date(ts * 1000));
}
// 펼치기 · 접기 : 목록을 다시 그리지 않고 그 카드만 부드럽게 열고 닫아요(화면이 덜컹거리지 않게)
function toggleNotice(id) {
  if (openNoticeIds.has(id)) openNoticeIds.delete(id); else openNoticeIds.add(id);
  const card = document.querySelector(`.notice-card[data-id="${id}"]`);
  if (card) card.classList.toggle('open', openNoticeIds.has(id)); else renderNotices();
}
function renderNotices() {
  const gm = myControlInfo(lastBattleForPanel).scope === 'all';
  const list = document.getElementById('noticeList');
  const editor = document.getElementById('noticeEditor');
  document.getElementById('noticeNewBtn').style.display = (gm && !noticeEditing) ? '' : 'none';
  const ntTitle = document.getElementById('noticeModalTitle');
  ntTitle.textContent = noticeEditing ? (noticeEditingId ? '공지 수정' : '새 공지') : 'Notice';
  ntTitle.classList.toggle('page-title', !noticeEditing);
  list.style.display = noticeEditing ? 'none' : '';
  editor.style.display = noticeEditing ? 'flex' : 'none';
  if (noticeEditing) return;
  if (!lastNotices.length) {
    list.innerHTML = emptyHtml('fa-bullhorn', '아직 공지사항이 없어요', gm ? '오른쪽 아래 버튼으로 첫 공지를 써 보세요.' : '새 공지가 올라오면 여기에 보여요.');
    return;
  }
  const seen = noticeSeenAt();
  list.innerHTML = lastNotices.map(n => {
    const open = openNoticeIds.has(n.id);
    const isNew = (n.updated_at || n.created_at || 0) > seen;
    const tmp = document.createElement('div');
    tmp.innerHTML = (n.html || '').replace(/<\/(p|h1|h2|h3|li|div|blockquote)>|<br\s*\/?>/gi, ' $&');
    const preview = (tmp.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    return `<div class="notice-card ${open ? 'open' : ''} ${n.pinned ? 'pinned' : ''}" data-id="${n.id}">
      <div class="notice-card-head" onclick="toggleNotice('${n.id}')">
        <div class="nc-main">
          <div class="nc-title">${n.pinned ? '<span class="pin"><i class="fa-solid fa-thumbtack"></i>고정</span>' : ''}<span class="t">${shopEsc(n.title)}</span>${isNew ? '<span class="new"></span>' : ''}</div>
          ${n.pinned ? '' : `<div class="nc-meta">${fmtNoticeRealDate(n.created_at)}</div>`}
          ${preview ? `<div class="nc-pv-wrap"><div class="nc-pv">${shopEsc(preview)}</div></div>` : ''}
        </div>
        <span class="chev"><i class="fa-solid fa-chevron-down"></i></span>
      </div>
      <div class="notice-card-body"><div class="nc-inner"><div class="nc-pad">
        <div class="notice-content">${n.html || ''}</div>
        ${gm ? `<div class="notice-gm-ops"><button class="shop-ico-btn" onclick="startNoticeEdit('${n.id}')" data-tip="수정"><i class="fa-solid fa-pen"></i></button><button class="shop-ico-btn danger" onclick="deleteNotice('${n.id}')" data-tip="삭제"><i class="fa-solid fa-trash-can"></i></button></div>` : ''}
      </div></div></div>
    </div>`;
  }).join('');
}
function startNoticeEdit(id) {
  const n = id ? lastNotices.find(x => x.id === id) : null;
  noticeEditing = true;
  noticeEditingId = n ? n.id : null;
  renderNotices();
  document.getElementById('noticeTitleInput').value = n ? n.title : '';
  document.getElementById('noticeEditArea').innerHTML = n ? (n.html || '') : '';
  document.getElementById('noticePinnedInput').checked = !!(n && n.pinned);
  try { document.execCommand('styleWithCSS', false, false); } catch (e) {}
  document.getElementById(n ? 'noticeEditArea' : 'noticeTitleInput').focus();
  refreshNoticeToolbar();
}
function cancelNoticeEdit() {
  uiConfirm('작성 중인 내용을 버릴까요?', {title:'작성 취소', okText:'버리기', danger:true}).then(ok => {
    if (!ok) return;
    noticeEditing = false; noticeEditingId = null;
    renderNotices();
  });
}
function noticeCmd(cmd, value) {
  if (!value && ['fontSize', 'formatBlock'].includes(cmd)) return;
  const area = document.getElementById('noticeEditArea');
  area.focus();
  if (cmd === 'hiliteColor') {
    // 형광펜은 span style로 넣어야 저장 후에도 유지됩니다.
    try { document.execCommand('styleWithCSS', false, true); } catch (e) {}
    document.execCommand('hiliteColor', false, value);
    try { document.execCommand('styleWithCSS', false, false); } catch (e) {}
  } else {
    document.execCommand(cmd, false, value || null);
  }
  refreshNoticeToolbar();
}
function noticeLink() {
  // 팝업이 뜨면 편집기 선택 영역이 풀리므로 미리 저장했다가 되살립니다.
  const sel = window.getSelection();
  const range = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
  uiPrompt('링크 주소를 입력하세요.', 'https://', {title:'링크 넣기', okText:'넣기', placeholder:'https://...', icon:'fa-link'}).then(url => {
    if (!url || !/^https?:\/\//i.test(url)) return;
    const area = document.getElementById('noticeEditArea');
    area.focus();
    if (range) { const s2 = window.getSelection(); s2.removeAllRanges(); s2.addRange(range); }
    noticeCmd('createLink', url);
  });
}
function refreshNoticeToolbar() {
  document.querySelectorAll('#noticeToolbar button[data-cmd]').forEach(b => {
    let on = false;
    try { on = document.queryCommandState(b.dataset.cmd); } catch (e) {}
    b.classList.toggle('on', !!on);
  });
}
function saveNotice() {
  const title = document.getElementById('noticeTitleInput').value.trim();
  const html = document.getElementById('noticeEditArea').innerHTML;
  if (!title) { showError('제목을 입력해주세요.'); return; }
  socket.emit('notice_save', { id: noticeEditingId, title, html, pinned: document.getElementById('noticePinnedInput').checked });
}
function deleteNotice(id) {
  const n = lastNotices.find(x => x.id === id);
  uiConfirm(`'${n ? n.title : ''}' 공지를 삭제할까요?`, {title:'공지 삭제', okText:'삭제', danger:true}).then(ok => ok && socket.emit('notice_delete', { id }));
}
// ------------------------------------------------------------------
// 상태 태그 아이콘 (Font Awesome). Pro 전용 아이콘이 로드되지 않으면 무료 대체 아이콘으로 자동 전환합니다.
// ------------------------------------------------------------------
const STATUS_TAG_ICONS = {
  pending:   { cls: 'fa-solid fa-radiation',               fallback: 'fa-solid fa-radiation' },
  selfdef:   { cls: 'fa-solid fa-shield-halved',           fallback: 'fa-solid fa-shield-halved' },
  proxydef:  { cls: 'fa-solid fa-shield-user',             fallback: 'fa-solid fa-user-shield' },
  guard:     { cls: 'fa-solid fa-shield-cross',            fallback: 'fa-solid fa-shield-heart' },
  command:   { cls: 'fa-sharp fa-solid fa-bullseye-pointer', fallback: 'fa-solid fa-bullseye' },
  heal:      { cls: 'fa-solid fa-hand-holding-medical',    fallback: 'fa-solid fa-hand-holding-medical' },
  leech:     { cls: 'fa-sharp fa-solid fa-droplet-plus',   fallback: 'fa-solid fa-droplet' },
  shield:    { cls: 'fa-solid fa-shield',                  fallback: 'fa-solid fa-shield' },
  polarize:  { cls: 'fa-solid fa-circle-half-stroke',      fallback: 'fa-solid fa-circle-half-stroke' },
  dodge:     { cls: 'fa-solid fa-person-running',          fallback: 'fa-solid fa-person-running' },
};
const statusIconOk = {};
function detectStatusIcons() {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute; left:-9999px; top:-9999px;';
  document.body.appendChild(probe);
  Object.entries(STATUS_TAG_ICONS).forEach(([k, v]) => {
    const i = document.createElement('i');
    i.className = v.cls;
    probe.appendChild(i);
    const content = getComputedStyle(i, '::before').content;
    statusIconOk[k] = !!content && content !== 'none' && content !== 'normal' && content !== '""';
  });
  probe.remove();
}
// 카드가 좁을 때(모바일)는 글자는 숨기고 아이콘+개수만 보이도록, 이름(st-l)과 개수(st-n)를 나눠 둡니다.
function makeStatusTag(kind, text, count) {
  const ic = STATUS_TAG_ICONS[kind];
  const cls = ic ? (statusIconOk[kind] === false ? ic.fallback : ic.cls) : '';
  let label = String(text), num = count != null ? String(count) : '';
  if (count == null) {
    const m = label.match(/^(.*?)\s*([+]?\d+)$/);
    if (m) { label = m[1]; num = m[2]; }
  }
  const full = count != null ? label : String(text);
  return `<span class="stag stag-${kind}">${cls ? `<i class="${cls}"></i>` : ''}<span class="st-l">${label}</span>${num && count == null ? `<span class="st-n">${num}</span>` : ''}${count != null && count > 1 ? `<span class="st-n st-only">${count}</span>` : ''}</span>`;
}
// 아이콘 폰트가 늦게 로드될 수 있어서, 로드 후 한 번 더 확인하고 화면을 다시 그립니다.
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => { detectStatusIcons(); if (typeof renderBattle === 'function' && lastBattleForPanel !== undefined) renderBattle(lastBattleForPanel); });
}
// ==================================================================
// 행동 효과음 : 서버가 행동 성공 시 action_sfx를 보내면, 그 캐릭터의 개인 소리(마이페이지 등록)
// 또는 기본 소리(공격/방어, 지휘/회복)를 재생합니다. 내 효과음 음량은 이 브라우저에만 저장됩니다.
// ==================================================================
let lastSfxDefaults = {};
let sfxVolume = 70;
try { const v = localStorage.getItem('sfxVolume'); if (v != null) sfxVolume = parseInt(v, 10); } catch (e) {}
let sfxVolumeBeforeMute = null;
let sfxDefaultTargetKind = null;

function sfxCharacter(name) {
  return (lastAllForCards || []).find(c => c.name === name) || (lastRosterMypage || {})[name] || null;
}
function playSfx(url, vol) {
  if (!url || vol <= 0) return;
  const audio = new Audio(url);
  audio.volume = Math.max(0, Math.min(1, vol));
  audio.play().catch(() => {});
  setTimeout(() => audio.pause(), (typeof SOUND_EFFECT_MAX_SECONDS !== 'undefined' ? SOUND_EFFECT_MAX_SECONDS : 6) * 1000);
}
socket.on('action_sfx', (d) => {
  if (sfxVolume <= 0) return;
  const c = sfxCharacter(d.actor);
  const def = lastSfxDefaults[d.kind];
  if (d.kind === 'boss_hit' && def && def.url) {
    playSfx(def.url, ((def.volume != null ? def.volume : 100) / 100) * (sfxVolume / 100));
  } else if (c && c.sound_effect) {
    playSfx(c.sound_effect, ((c.sound_effect_volume != null ? c.sound_effect_volume : 100) / 100) * (sfxVolume / 100));
  } else if (def) {
    playSfx(def.url, ((def.volume != null ? def.volume : 100) / 100) * (sfxVolume / 100));
  }
});

function openSoundSettings() { document.getElementById('soundModal').style.display = 'flex'; renderSoundSettings(); }
function closeSoundSettings() { document.getElementById('soundModal').style.display = 'none'; }
function onSfxVolumeChange(v) {
  sfxVolume = parseInt(v, 10);
  try { localStorage.setItem('sfxVolume', String(sfxVolume)); } catch (e) {}
  refreshSfxVolumeUi();
}
function toggleSfxMute() {
  if (sfxVolume > 0) { sfxVolumeBeforeMute = sfxVolume; onSfxVolumeChange(0); }
  else onSfxVolumeChange(sfxVolumeBeforeMute || 70);
  document.getElementById('sfxVolumeSlider').value = sfxVolume;
  refreshSfxVolumeUi();
}
function refreshSfxVolumeUi() {
  const slider = document.getElementById('sfxVolumeSlider');
  if (document.activeElement !== slider) slider.value = sfxVolume;
  paintRange(slider);
  document.getElementById('sfxVolumeNum').textContent = sfxVolume;
  const icon = sfxVolume === 0 ? 'fa-volume-xmark' : (sfxVolume < 40 ? 'fa-volume-low' : 'fa-volume-high');
  document.getElementById('sfxMuteBtn').innerHTML = `<i class="fa-solid ${icon}"></i>`;
}
const SFX_OPTIONAL_KINDS = ['round', 'boss_hit'];  // 기본 소리 없이, 운영진이 등록해야 울리는 종류
function renderSoundSettings() {
  if (document.getElementById('soundModal').style.display !== 'flex') return;
  refreshSfxVolumeUi();
  const box = document.getElementById('sfxDefaultsSection');
  const gm = myControlInfo(lastBattleForPanel).scope === 'all';
  // 러너에게는 운영진이 아직 등록하지 않은 소리(라운드 전환·보스 타격)는 보여주지 않습니다.
  const kinds = Object.entries(lastSfxDefaults || {}).filter(([, d]) => gm || d.url);
  if (!kinds.length) { box.innerHTML = ''; return; }
  if (box.contains(document.activeElement)) return;
  box.innerHTML = `<div class="snd-sec-title" style="margin-top:14px;">기본 효과음 ${gm ? '<span>(운영진 설정 · 모두에게 적용)</span>' : ''}</div>` +
    kinds.map(([kind, d]) => `<div class="snd-default">
      <div class="snd-default-top"><b>${shopEsc(d.label || kind)}</b><span class="snd-level" id="sfxLevel_${kind}" style="margin:0;"></span>
        ${d.url ? `<button class="shop-btn ghost sm" onclick="previewDefaultSfx('${kind}')"><i class="fa-solid fa-play"></i> 듣기</button>` : '<span class="snd-hint" style="margin:0;">미등록</span>'}
        ${gm ? `<button class="shop-btn ghost sm" onclick="pickSfxDefault('${kind}')">${d.url ? '파일 바꾸기' : '파일 등록'}</button>
        ${d.url ? `<button class="shop-btn ghost sm" onclick="uiConfirm('${SFX_OPTIONAL_KINDS.includes(kind) ? '등록한 소리를 지울까요?' : '처음 기본 소리로 되돌릴까요?'}', {title:'효과음 초기화', okText:'${SFX_OPTIONAL_KINDS.includes(kind) ? '지우기' : '초기화'}', danger:true}).then(ok => ok && socket.emit('set_default_sfx', {kind:'${kind}', reset:true}))">${SFX_OPTIONAL_KINDS.includes(kind) ? '지우기' : '초기화'}</button>` : ''}` : ''}
      </div>
      ${gm ? `<div class="snd-row"><span class="snd-hint" style="margin:0;width:56px;">기본 음량</span>
        <input type="range" class="nice-range" min="0" max="100" value="${d.volume}" oninput="paintRange(this); this.nextElementSibling.textContent=this.value"
          onchange="socket.emit('set_default_sfx', {kind:'${kind}', volume:parseInt(this.value,10)})">
        <span class="bgm-vol-num">${d.volume}</span></div>` : ''}
    </div>`).join('');
  box.querySelectorAll('input[type="range"]').forEach(paintRange);
  kinds.forEach(([kind, d]) => analyzeLoudness(d.url).then(m => {
    const el = document.getElementById(`sfxLevel_${kind}`);
    if (!el || !m) return;
    const eff = m.rms_db + 20 * Math.log10(Math.max(d.volume, 1) / 100);
    el.innerHTML = `<span class="lv">${eff.toFixed(1)} dB</span> ${loudnessBadge(eff)}`;
  }));
}
function previewDefaultSfx(kind) {
  const d = lastSfxDefaults[kind];
  if (d) playSfx(d.url, ((d.volume != null ? d.volume : 100) / 100) * (Math.max(sfxVolume, 1) / 100));
}
function pickSfxDefault(kind) { sfxDefaultTargetKind = kind; document.getElementById('sfxDefaultFileInput').click(); }
function onSfxDefaultFileChosen(ev) {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!f || !sfxDefaultTargetKind) return;
  if (f.size > UPLOAD_AUDIO_BYTES) { showError(`파일이 너무 커요 (최대 ${UPLOAD_AUDIO_MB}MB).`); return; }
  f.arrayBuffer().then(buf => socket.emit('set_default_sfx', { kind: sfxDefaultTargetKind, filename: f.name, data: buf }));
}
// ==================================================================
// 효과음 크기(dB) 측정 : 소리 파일을 브라우저에서 분석해 '소리가 나는 구간'의 평균 크기(RMS, dBFS)를 구합니다.
// 기본 효과음 기준으로 정한 적정 크기(SFX_TARGET_DB)에 맞추면 모든 캐릭터 효과음 크기가 비슷해집니다.
// 표시하는 값은 '음량 슬라이더까지 적용한 실제 크기'입니다.
// ==================================================================
// 적정 크기 : 배경음악(보통 -14 LUFS 내외로 마스터링된 곡을 기본 음량 70%로 틀면 소리 구간 평균 약 -17 dB)
// 위에 겹쳐 들릴 때 묻히지도, 튀지도 않는 수준. 효과음은 짧고 어택이 있어 같은 평균값이면 더 크게 들리므로
// 음악보다 약간 낮은 -20 dB를 기준으로 ±3 dB를 '적정'으로 봅니다(-23 ~ -17 dB).
const SFX_TARGET_DB = -20;
const SFX_TOLERANCE_DB = 3;    // ±3 dB 안이면 '적정'
const sfxLoudnessCache = {};
function analyzeLoudness(url) {
  if (!url) return Promise.resolve(null);
  if (sfxLoudnessCache[url]) return sfxLoudnessCache[url];
  const p = fetch(url).then(r => r.arrayBuffer()).then(buf => {
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const ctx = new Ctx(1, 44100, 44100);
    return new Promise((res, rej) => {
      // 콜백과 함께 Promise도 돌려주는 브라우저에서 실패 시 '처리 안 된 오류'가 따로 뜨지 않도록 막아 둡니다.
      const pr = ctx.decodeAudioData(buf, res, rej);
      if (pr && pr.catch) pr.catch(() => {});
    });
  }).then(audio => {
    const sr = audio.sampleRate;
    const maxLen = Math.min(audio.length, Math.floor(sr * SOUND_EFFECT_MAX_SECONDS));  // 실제로 재생되는 6초까지만
    const ch = [];
    for (let i = 0; i < audio.numberOfChannels; i++) ch.push(audio.getChannelData(i));
    const win = Math.floor(sr * 0.05);
    const gate = Math.pow(10, -50 / 20);
    let sumSq = 0, wins = 0, peak = 0;
    for (let start = 0; start + win <= maxLen; start += win) {
      let s = 0;
      for (let j = start; j < start + win; j++) {
        let v = 0;
        for (const c of ch) v += c[j];
        v /= ch.length;
        s += v * v;
        if (Math.abs(v) > peak) peak = Math.abs(v);
      }
      const r = Math.sqrt(s / win);
      if (r > gate) { sumSq += r * r; wins++; }
    }
    if (!wins) return { rms_db: -Infinity, peak_db: -Infinity };
    return { rms_db: 20 * Math.log10(Math.sqrt(sumSq / wins)), peak_db: 20 * Math.log10(peak) };
  }).catch(() => null);
  sfxLoudnessCache[url] = p;
  return p;
}
function loudnessBadge(effDb) {
  if (!isFinite(effDb)) return '<span class="badge quiet">무음</span>';
  if (effDb > SFX_TARGET_DB + SFX_TOLERANCE_DB) return '<span class="badge loud">큼</span>';
  if (effDb < SFX_TARGET_DB - SFX_TOLERANCE_DB) return '<span class="badge quiet">작음</span>';
  return '<span class="badge ok">적정</span>';
}
function volumeForTarget(rmsDb) {
  return Math.round(100 * Math.pow(10, (SFX_TARGET_DB - rmsDb) / 20));
}
let myPageSoundNeed = null;  // 적정 크기에 맞추려면 필요한 음량(%) - '음량 맞추기' 버튼이 씁니다.
function updateMyPageSoundLevel() {
  const el = document.getElementById('myPageSoundLevel');
  if (!el || document.getElementById('myPageModal').style.display !== 'flex') return;
  const row = (db, st, cls) => `<span class="lbl">파일 음량:</span><span class="db">${db}</span><span class="st ${cls || ''}">${st}</span>`;
  const c = myPageTargetChar();
  myPageSoundNeed = null;
  if (!c || !c.sound_effect) { el.innerHTML = row('-', `*적정 ${SFX_TARGET_DB} dB`); return; }
  const vol = parseInt(document.getElementById('myPageSoundVolume').value, 10);
  const url = c.sound_effect;
  el.innerHTML = row('측정 중...', '');
  analyzeLoudness(url).then(m => {
    if (myPageTargetChar() !== c && (!myPageTargetChar() || myPageTargetChar().sound_effect !== url)) return;
    if (!m) { el.innerHTML = row('측정 불가', ''); return; }
    const eff = m.rms_db + 20 * Math.log10(Math.max(vol, 1) / 100);
    myPageSoundNeed = volumeForTarget(m.rms_db);
    const st = eff > SFX_TARGET_DB + SFX_TOLERANCE_DB ? ['*큼', ''] : eff < SFX_TARGET_DB - SFX_TOLERANCE_DB ? ['*작음', ''] : ['*적정', 'ok'];
    el.innerHTML = row(isFinite(eff) ? `${eff.toFixed(1)} dB` : '-', st[0], st[1]);
  });
}
function fitMySoundVolume() {
  if (!canEditMyPage() || myPageSoundNeed == null) return;
  const v = Math.max(0, Math.min(100, myPageSoundNeed));
  document.getElementById('myPageSoundVolume').value = v;
  onMySoundEffectVolumeChange();
  updateMyPageSoundLevel();
  if (myPageSoundNeed > 100) showShopToast('원본 소리가 작아서 최대 음량으로 맞췄어요. 더 큰 파일을 권장해요.');
  else showShopToast(`음량을 ${v}%로 맞췄어요.`);
}
// ==================================================================
// 홀로그램(글리터) 효과 : 마우스가 있는 영역(카드 영역 .holo-zone이면 그 안 카드 전부, 아니면 그 블럭 하나)에
// 포인터 위치를 넣고 .holo-on을 붙입니다. 화면이 자주 다시 그려지므로 문서 전체에서 이벤트를 받아 처리합니다.
// ==================================================================
(function setupHoloCards() {
  const SEL = '.char-card, .site-card, .compact-card, .member-panel:not(.pl-logpanel), .topbar.v2, .action-bar-bottom, .map-frame, .bgm-player';
  let activeEls = [];
  function clear() { activeEls.forEach(el => el.classList.remove('holo-on')); activeEls = []; }
  document.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    const t = e.target;
    if (!t || !t.closest || t.closest('.modal-overlay')) { clear(); return; }
    const zone = t.closest('.holo-zone');
    let els;
    if (zone) els = [...zone.querySelectorAll(SEL)];
    else { const one = t.closest(SEL); els = one ? [one] : []; }
    activeEls.forEach(el => { if (!els.includes(el)) el.classList.remove('holo-on'); });
    activeEls = els;
    for (const el of els) {
      const r = el.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      el.style.setProperty('--mouse-x', `${x}px`);
      el.style.setProperty('--mouse-y', `${y}px`);
      el.style.setProperty('--ratio-x', (x / r.width).toFixed(3));
      el.style.setProperty('--ratio-y', (y / r.height).toFixed(3));
      el.classList.add('holo-on');
    }
  }, { passive: true });
  document.addEventListener('pointerleave', clear);
  window.addEventListener('blur', clear);
})();
// ==================================================================
// 디자인된 확인/입력 팝업 : uiConfirm(메시지, 옵션) / uiPrompt(메시지, 기본값, 옵션) → Promise
// (브라우저 기본 confirm/prompt 창 대신 사이트 디자인에 맞춘 팝업을 띄웁니다)
// ==================================================================
let uiDialogResolve = null;
function openUiDialog(opts) {
  const ov = document.getElementById('uiDialog'), box = document.getElementById('uiDialogBox');
  const input = document.getElementById('uiDialogInput');
  box.classList.toggle('danger', !!opts.danger);
  // 안내 · 확인 창의 기본 아이콘은 'i' 아이콘(위험한 동작만 경고 삼각형, 따로 정한 아이콘은 그대로)
  const ic = opts.icon || (opts.danger ? 'fa-triangle-exclamation' : 'info');
  document.getElementById('uiDialogIcon').innerHTML = ic === 'info' || ic === 'fa-circle-info' ? UI_INFO_SVG : `<i class="fa-solid ${ic}"></i>`;
  document.getElementById('uiDialogTitle').textContent = opts.title || '확인';
  document.getElementById('uiDialogMsg').textContent = opts.message || '';
  document.getElementById('uiDialogOk').textContent = opts.okText || '확인';
  document.getElementById('uiDialogCancel').textContent = opts.cancelText || '취소';
  document.getElementById('uiDialogCancel').style.display = opts.alert ? 'none' : '';
  document.getElementById('uiDialogMsg').style.whiteSpace = 'pre-line';
  input.style.display = opts.prompt ? '' : 'none';
  input.value = opts.defaultValue || '';
  input.placeholder = opts.placeholder || '';
  ov.style.display = 'flex';
  setTimeout(() => (opts.prompt ? input : document.getElementById('uiDialogOk')).focus(), 0);
  return new Promise(res => { uiDialogResolve = (v) => { ov.style.display = 'none'; uiDialogResolve = null; res(v); }; });
}
function uiConfirm(message, opts = {}) { return openUiDialog({ ...opts, message }).then(v => v !== null); }
function uiAlert(message, opts = {}) { return openUiDialog({ ...opts, message, alert: true, icon: opts.icon || 'fa-circle-info' }); }
function uiPrompt(message, defaultValue = '', opts = {}) { return openUiDialog({ ...opts, message, prompt: true, defaultValue, icon: opts.icon || 'fa-pen' }); }
document.getElementById('uiDialogOk').onclick = () => {
  if (!uiDialogResolve) return;
  const input = document.getElementById('uiDialogInput');
  uiDialogResolve(input.style.display === 'none' ? true : input.value);
};
document.getElementById('uiDialogCancel').onclick = () => uiDialogResolve && uiDialogResolve(null);
document.getElementById('uiDialog').addEventListener('click', (e) => { if (e.target.id === 'uiDialog' && uiDialogResolve) uiDialogResolve(null); });
document.addEventListener('keydown', (e) => {
  if (!uiDialogResolve) return;
  if (e.key === 'Escape') { e.preventDefault(); uiDialogResolve(null); }
  else if (e.key === 'Enter') { e.preventDefault(); document.getElementById('uiDialogOk').click(); }
}, true);
// ==================================================================
// 라운드 트랙 (PVP) : 라운드마다 [선공 | 후공] 두 칸, 진행한 칸은 채우고 지금 칸은 행동한 비율만큼 채웁니다.
// 높이는 창 크기에 맞춰 카드와 행동 블럭 사이 남는 공간을 채우고, 배경 이미지는 운영진이 설정(모두에게 적용).
// ==================================================================
let lastTrackBg = null;
const RT_WINDOW = 8;  // 한 번에 보여줄 라운드 수
(function initRoundTrackSizing() {
  // 창 크기에 따라 트랙 높이가 바뀌므로, 낮아지면 작은 글씨를 숨기는 compact 모드를 자동으로 켭니다.
  const el = document.getElementById('roundTrack');
  if (!el || !window.ResizeObserver) return;
  new ResizeObserver(() => el.classList.toggle('compact', el.getBoundingClientRect().height < 64)).observe(el);
})();

function renderRoundTrack() {
  const el = document.getElementById('roundTrack');
  if (!el) return;
  const inner = document.getElementById('roundTrackInner');
  const bg = document.getElementById('roundTrackBg');
  const cfg = Object.assign({ url: null, dim: 45 }, lastTrackBg || {});
  bg.style.backgroundImage = cfg.url ? `linear-gradient(rgba(0,0,0,${cfg.dim / 100}), rgba(0,0,0,${cfg.dim / 100})), url('${cfg.url}')` : '';
  document.getElementById('roundTrackBgBtn').classList.toggle('gm', myControlInfo(lastBattleForPanel).scope === 'all');
  const b = lastBattleForPanel;
  if (!b) { inner.innerHTML = '<div class="rt-empty">전투가 시작되면 라운드 진행이 여기에 표시돼요.</div>'; return; }
  const cur = b.round_no || 1;
  const first = b.round_first_team || '1팀';
  const second = first === '1팀' ? '2팀' : '1팀';
  const inSecond = !b.finished && b.current_turn_team && b.current_turn_team !== first;
  const turnTeam = b.current_turn_team;
  const start = Math.max(1, cur - RT_WINDOW + 3);
  // 점 : 지난 라운드(흰 점) / 지금 라운드(포인트 컬러 점 + 옅은 고리) / 남은 라운드(어두운 점)
  const nodes = [];
  for (let r = start; r < start + RT_WINDOW; r++) {
    const state = r < cur || (r === cur && b.finished) ? 'past' : (r === cur ? 'now' : 'next');
    nodes.push(`<div class="rt-node ${state}"><span class="r">${r}</span></div>`);
  }
  const fill = Math.max(0, Math.min(1, (cur - start) / (RT_WINDOW - 1)));
  const phase = b.finished
    ? `<span class="chip">종료</span>${b.winner ? `<b>${b.winner}</b> 승리` : ''}`
    : `<span class="chip">${inSecond ? '후공' : '선공'}</span><b>${turnTeam}</b> 행동`;
  inner.innerHTML = `<div class="rt-round"><span class="k">Round</span><span class="n">${cur}</span></div>
    <div class="rt-line" style="--rt-fill:${fill}">${nodes.join('')}</div>
    <div class="rt-phase">${phase}</div>`;
}

function openTrackBgModal() { document.getElementById('trackBgModal').style.display = 'flex'; renderTrackBgModal(); }
function closeTrackBgModal() { document.getElementById('trackBgModal').style.display = 'none'; renderRoundTrack(); }
function renderTrackBgModal() {
  if (document.getElementById('trackBgModal').style.display !== 'flex') return;
  const cfg = Object.assign({ url: null, dim: 45 }, lastTrackBg || {});
  document.getElementById('trackBgPreview').style.backgroundImage = cfg.url ? `url('${cfg.url}')` : '';
  document.getElementById('trackBgPreviewText').textContent = cfg.url ? '클릭해서 다른 이미지로 바꾸기' : `클릭해서 배경 이미지 올리기 (최대 ${UPLOAD_IMG_MB}MB)`;
  const dim = document.getElementById('trackBgDim');
  if (document.activeElement !== dim) dim.value = cfg.dim;
  paintRange(dim);
  onTrackBgSlider();
}
function onTrackBgSlider() {
  const dim = parseInt(document.getElementById('trackBgDim').value, 10);
  document.getElementById('trackBgDimVal').textContent = `${dim}%`;
  document.getElementById('trackBgPreviewDim').style.background = `rgba(0,0,0,${dim / 100})`;
  const cfg = Object.assign({ url: null }, lastTrackBg || {});
  const bg = document.getElementById('roundTrackBg');
  if (bg && cfg.url) bg.style.backgroundImage = `linear-gradient(rgba(0,0,0,${dim / 100}), rgba(0,0,0,${dim / 100})), url('${cfg.url}')`;
}
function onTrackBgFileChosen(ev) {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  document.getElementById('trackBgPreviewText').textContent = '올리는 중...';
  f.arrayBuffer().then(buf => socket.emit('set_track_bg', { filename: f.name, data: buf }));
}

// ==================================================================
// 화면 전체 배경 + 날씨 효과 (운영진이 설정, 모두에게 적용 / 각자 내 화면에서만 끌 수 있음)
// ==================================================================
var lastScene = null;
function sceneCfg() { return Object.assign({ url: null, dim: 40, weather: 'none', amount: 2, layer: 'back' }, lastScene || {}); }
function weatherMyOff() { try { return localStorage.getItem('weatherOff') === '1'; } catch (e) { return false; } }
function setWeatherMyOff(v) { try { localStorage.setItem('weatherOff', v ? '1' : '0'); } catch (e) {} applyScene(); }
function applyScene() {
  const cfg = sceneCfg();
  const bg = document.getElementById('sceneBg');
  if (bg) {
    bg.style.backgroundImage = cfg.url ? `linear-gradient(rgba(0,0,0,${cfg.dim / 100}), rgba(0,0,0,${cfg.dim / 100})), url('${cfg.url}')` : '';
    bg.classList.toggle('on', !!cfg.url);
  }
  Weather.set(weatherMyOff() ? 'none' : cfg.weather, cfg.amount, cfg.layer);
  renderSceneModal();
}
function openSceneModal() { document.getElementById('sceneModal').style.display = 'flex'; renderSceneModal(); }
function closeSceneModal() { document.getElementById('sceneModal').style.display = 'none'; }
function renderSceneModal() {
  const m = document.getElementById('sceneModal');
  if (!m || m.style.display !== 'flex') return;
  const cfg = sceneCfg();
  document.getElementById('scenePreview').style.backgroundImage = cfg.url ? `url('${cfg.url}')` : '';
  document.getElementById('scenePreviewText').textContent = cfg.url ? '클릭해서 다른 이미지로 바꾸기' : `클릭해서 화면 배경 올리기 (png·apng·gif·webp·jpg, 최대 ${UPLOAD_IMG_MB}MB)`;
  const dim = document.getElementById('sceneDim');
  if (document.activeElement !== dim) dim.value = cfg.dim;
  paintRange(dim); onSceneDimSlider();
  [['sceneWeatherSeg', cfg.weather], ['sceneWeatherSeg2', cfg.weather], ['sceneWeatherSeg3', cfg.weather], ['sceneWeatherSeg4', cfg.weather], ['sceneAmountSeg', String(cfg.amount)], ['sceneLayerSeg', cfg.layer]].forEach(([id, v]) =>
    document.querySelectorAll(`#${id} button`).forEach(b => b.classList.toggle('on', b.dataset.v === v)));
  document.getElementById('sceneMyOff').checked = weatherMyOff();
}
function onSceneDimSlider() {
  const d = parseInt(document.getElementById('sceneDim').value, 10);
  document.getElementById('sceneDimVal').textContent = `${d}%`;
  document.getElementById('scenePreviewDim').style.background = `rgba(0,0,0,${d / 100})`;
  const cfg = sceneCfg(), bg = document.getElementById('sceneBg');
  if (bg && cfg.url) bg.style.backgroundImage = `linear-gradient(rgba(0,0,0,${d / 100}), rgba(0,0,0,${d / 100})), url('${cfg.url}')`;
}
function onSceneFileChosen(ev) {
  const f = ev.target.files && ev.target.files[0];
  ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_IMG_BYTES) { showError(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  document.getElementById('scenePreviewText').textContent = '올리는 중...';
  f.arrayBuffer().then(buf => socket.emit('set_scene', { filename: f.name, data: buf }));
}

// 날씨 : 캔버스 하나에 입자를 그립니다. 종류마다 [개수 / 생성 / 움직임·그리기 / 화면 밖 판정]을 따로 정의합니다.
// 탭이 숨겨지면 멈춥니다.
var Weather = (function () {
  const cv = document.getElementById('weatherCanvas');
  const ctx = cv ? cv.getContext('2d') : null;
  let kind = 'none', amount = 2, parts = [], raf = 0, W = 0, H = 0, dpr = 1, last = 0, T = 0;
  let flash = 0, bolt = null, nextBolt = 0;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = arr => arr[Math.floor(Math.random() * arr.length)];
  function resize() {
    if (!cv) return;
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = window.innerWidth; H = window.innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  // ---- 공통 그리기 ----
  function petal(p, colors) {
    ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.scale(1, .55 + .45 * Math.abs(Math.sin(p.ph)));
    ctx.globalAlpha = p.a; ctx.fillStyle = p.c; ctx.beginPath();
    ctx.moveTo(0, -p.s); ctx.bezierCurveTo(p.s * .9, -p.s * .7, p.s * .7, p.s * .6, 0, p.s);
    ctx.bezierCurveTo(-p.s * .7, p.s * .6, -p.s * .9, -p.s * .7, 0, -p.s); ctx.fill(); ctx.restore();
  }
  function leaf(p) {
    ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.scale(1, .45 + .55 * Math.abs(Math.sin(p.ph)));
    ctx.globalAlpha = p.a; ctx.fillStyle = p.c; ctx.beginPath();
    ctx.moveTo(-p.s, 0); ctx.quadraticCurveTo(0, -p.s * .75, p.s, 0); ctx.quadraticCurveTo(0, p.s * .75, -p.s, 0); ctx.fill();
    ctx.strokeStyle = 'rgba(60,30,10,.35)'; ctx.lineWidth = .6; ctx.beginPath(); ctx.moveTo(-p.s, 0); ctx.lineTo(p.s, 0); ctx.stroke(); ctx.restore();
  }
  function glow(x, y, r, color, a) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, color.replace('A', a)); g.addColorStop(1, color.replace('A', 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fill();
  }
  function rainDraw(p, rgb) {
    ctx.strokeStyle = `rgba(${rgb},${p.a})`; ctx.lineWidth = p.w || 1; ctx.beginPath(); ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + p.vx * .02 * (p.len / 16), p.y + p.len); ctx.stroke();
  }
  const fall = p => p.y > H + 40 || p.x < -80 || p.x > W + 80;
  const rise = p => p.y < -40 || p.x < -80 || p.x > W + 80;
  // ---- 오로라 렌더러 ----
  const Aur = (function () {
    let off = null, octx = null, strips = null; const SC = 4;
    function strip(stops) { const c = document.createElement('canvas'); c.width = 1; c.height = 256; const x = c.getContext('2d');
      const g = x.createLinearGradient(0, 0, 0, 256); stops.forEach(([o, col]) => g.addColorStop(o, col)); x.fillStyle = g; x.fillRect(0, 0, 1, 256); return c; }
    function ensure() {
      if (!strips) strips = [
        strip([[0, 'rgba(150,90,255,0)'], [.3, 'rgba(130,100,255,.16)'], [.62, 'rgba(60,210,200,.42)'], [.86, 'rgba(100,255,170,.9)'], [.93, 'rgba(190,255,215,.75)'], [1, 'rgba(120,255,180,0)']]),
        strip([[0, 'rgba(255,90,200,0)'], [.35, 'rgba(180,90,255,.2)'], [.72, 'rgba(100,160,255,.5)'], [.9, 'rgba(160,220,255,.8)'], [1, 'rgba(140,200,255,0)']]),
      ];
      const w = Math.ceil(W / SC), h = Math.ceil(H / SC);
      if (!off || off.width !== w || off.height !== h) { off = document.createElement('canvas'); off.width = w; off.height = h; octx = off.getContext('2d'); }
    }
    return {
      begin() { ensure(); octx.globalCompositeOperation = 'source-over'; octx.clearRect(0, 0, off.width, off.height); octx.globalCompositeOperation = 'lighter'; },
      draw(p) {
        const cols = off.width, st = p.alt ? strips[1] : strips[0];
        for (let c = 0; c < cols; c++) {
          const x = c * SC;
          const y = p.base + (x / W - .5) * p.tilt + Math.sin(x * p.f1 + p.ph) * p.amp + Math.sin(x * p.f2 - p.ph * 1.7) * p.amp * .3;
          const h = p.h * (.55 + .45 * Math.sin(x * p.f2 * .7 + p.ph * 1.3)) * (.85 + .15 * Math.sin(x * .05 + p.ph * 4));
          const edge = Math.min(1, x / (W * .12), (W - x) / (W * .12));
          let a = .35 + .65 * (.5 + .5 * Math.sin(x * p.f1 * 1.6 - p.ph * .9)); a = a * (.8 + .2 * Math.sin(x * .07 + p.ph * 5)) * p.str * Aur.k * edge;
          if (a < .01) continue;
          octx.globalAlpha = Math.min(1, a);
          octx.drawImage(st, c, (y - h) / SC, 1.4, h / SC);
        }
        octx.globalAlpha = 1;
      },
      end() { ctx.save(); ctx.globalCompositeOperation = 'lighter'; if (cv.classList.contains('front')) ctx.globalAlpha = .75; ctx.imageSmoothingEnabled = true; ctx.filter = 'blur(10px)';
        ctx.drawImage(off, 0, 0, W, H); ctx.filter = 'blur(2px)'; ctx.globalAlpha *= .7; ctx.drawImage(off, 0, 0, W, H); ctx.filter = 'none'; ctx.restore(); },
      k: .8,
    };
  })();
  // ---- 수면 렌더러 : 물속에서 올려다본 잔잔한 장면 ----
  // 1) 위는 밝고 아래는 깊은 물빛 그라데이션  2) 수면에서 내려오는 부드러운 빛줄기(천천히 흔들림)
  // 3) 화면 위쪽에만 아른거리는 수면 빛 무늬(아래로 갈수록 사라짐)  4) 천천히 떠다니는 작은 입자
  const Water = (function () {
    let off = null, octx = null, img = null, t = 0, frameN = 0, beams = [], motes = [], lastW = 0;
    const SC = 6, BAND = .3;
    const hash = (x, y, k) => { const v = Math.sin(x * 127.1 + y * 311.7 + k * 74.7) * 43758.5453; return v - Math.floor(v); };
    function edge(x, y, cs, sp, k) {
      const gx = Math.floor(x / cs), gy = Math.floor(y / cs); let f1 = 1e9, f2 = 1e9;
      for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
        const cx = gx + i, cy = gy + j, h1 = hash(cx, cy, k), h2 = hash(cy, cx, k + 1);
        const px = (cx + .5 + .4 * Math.sin(t * sp + h1 * 6.28)) * cs, py = (cy + .5 + .4 * Math.cos(t * sp * 1.27 + h2 * 6.28)) * cs;
        const d = Math.hypot(x - px, y - py); if (d < f1) { f2 = f1; f1 = d; } else if (d < f2) f2 = d;
      }
      return f2 - f1;
    }
    function init() {
      lastW = W;
      beams = Array.from({ length: 7 }, () => ({ x: rnd(-.1, 1.05), w: rnd(.04, .11), sk: rnd(.05, .18), ph: rnd(0, 6.28), sp: rnd(.12, .25), a: rnd(.05, .11) }));
      motes = Array.from({ length: 34 }, () => ({ x: rnd(0, W), y: rnd(0, H), r: rnd(.6, 1.6), vx: rnd(-4, 4), vy: -rnd(3, 10), ph: rnd(0, 6.28), a: rnd(.15, .4) }));
    }
    return {
      draw(dt) {
        if (!beams.length || lastW !== W) init();
        t += dt * .32; frameN++;
        const k = [0, .6, 1, 1.4][amount] * (cv.classList.contains('front') ? .55 : 1);
        ctx.save();
        // 1) 물빛
        ctx.globalCompositeOperation = 'source-over';
        const g = ctx.createLinearGradient(0, 0, 0, H);
        g.addColorStop(0, `rgba(40,150,200,${.16 * k})`); g.addColorStop(.45, `rgba(14,80,120,${.10 * k})`); g.addColorStop(1, `rgba(2,22,40,${.14 * k})`);
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
        ctx.globalCompositeOperation = 'lighter';
        // 2) 빛줄기
        for (const b of beams) {
          b.ph += dt * b.sp;
          const sway = Math.sin(b.ph) * .03, x0 = (b.x + sway) * W, w = b.w * W, x1 = x0 + b.sk * W, a = b.a * k * (.65 + .35 * Math.sin(b.ph * 1.7));
          const lg = ctx.createLinearGradient(0, 0, 0, H * .85);
          lg.addColorStop(0, `rgba(170,225,255,${a})`); lg.addColorStop(1, 'rgba(170,225,255,0)');
          ctx.fillStyle = lg; ctx.beginPath(); ctx.moveTo(x0, 0); ctx.lineTo(x0 + w, 0); ctx.lineTo(x1 + w * 1.9, H * .85); ctx.lineTo(x1 - w * .4, H * .85); ctx.closePath(); ctx.fill();
        }
        // 3) 위쪽 수면 빛 무늬 (2프레임에 한 번 계산)
        const w = Math.ceil(W / SC), h = Math.ceil(H * BAND / SC);
        if (!off || off.width !== w || off.height !== h) { off = document.createElement('canvas'); off.width = w; off.height = h; octx = off.getContext('2d'); img = octx.createImageData(w, h); }
        if (frameN % 2 === 0) {
          const d = img.data;
          for (let y = 0; y < h; y++) {
            const fade = Math.pow(1 - y / h, 1.6);
            const sq = .55 + .45 * (y / h);  // 위로 갈수록 무늬를 납작하게(원근감)
            for (let x = 0; x < w; x++) {
              const wx = x + Math.sin(y * .2 + t) * 1.5, wy = y / sq + Math.cos(x * .12 + t * .8) * 1.2;
              const e = edge(wx, wy, 16, .6, 3);
              const v = Math.exp(-(e * e) / 5) * fade;
              const i4 = (y * w + x) * 4;
              d[i4] = 190; d[i4 + 1] = 235; d[i4 + 2] = 255; d[i4 + 3] = 255 * v;
            }
          }
          octx.putImageData(img, 0, 0);
        }
        ctx.globalAlpha = .42 * k; ctx.filter = 'blur(11px)'; ctx.drawImage(off, 0, 0, W, H * BAND); ctx.filter = 'none';
        // 4) 떠다니는 입자
        ctx.globalAlpha = 1;
        for (const m of motes) {
          m.ph += dt * .8; m.x += (m.vx + Math.sin(m.ph) * 3) * dt; m.y += m.vy * dt;
          if (m.y < -10) { m.y = H + 10; m.x = rnd(0, W); }
          ctx.fillStyle = `rgba(200,235,255,${m.a * k * (.6 + .4 * Math.sin(m.ph * 1.3))})`; ctx.beginPath(); ctx.arc(m.x, m.y, m.r, 0, 6.283); ctx.fill();
        }
        ctx.restore();
      },
    };
  })();
  // ---- 종류별 정의 ----
  const K = {
    snow: { n: 70,
      spawn(p, i) { p.x = rnd(-40, W + 40); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.r = rnd(1, 3.2); p.vy = rnd(18, 48) * (p.r / 2.2); p.vx = rnd(-8, 8); p.ph = rnd(0, 6.28); p.a = rnd(.35, .85); },
      step(p, dt) { p.ph += dt; p.x += (p.vx + Math.sin(p.ph) * 14) * dt; p.y += p.vy * dt;
        ctx.fillStyle = `rgba(255,255,255,${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill(); }, out: fall },
    blizzard: { n: 160,
      spawn(p, i) { p.x = i ? rnd(-W * .2, W * 1.2) : rnd(W * .2, W + 300); p.y = i ? rnd(-H, H) : rnd(-80, -10); p.r = rnd(.8, 2.4); p.vy = rnd(140, 260); p.vx = -rnd(260, 420); p.a = rnd(.35, .9); p.ph = rnd(0, 6.28); },
      step(p, dt) { p.ph += dt * 3; p.x += (p.vx + Math.sin(p.ph) * 40) * dt; p.y += p.vy * dt;
        ctx.strokeStyle = `rgba(255,255,255,${p.a})`; ctx.lineWidth = p.r; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.vx * .012, p.y - p.vy * .012); ctx.stroke(); },
      out: p => p.y > H + 40 || p.x < -80, overlay: 'rgba(220,230,245,.05)' },
    rain: { n: 110,
      spawn(p, i) { p.x = rnd(-40, W + 120); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.len = rnd(10, 22); p.vy = rnd(620, 900); p.vx = -110; p.a = rnd(.12, .32); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt; rainDraw(p, '190,205,230'); }, out: fall },
    storm: { n: 150, lightning: true,
      spawn(p, i) { p.x = rnd(-40, W + 200); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.len = rnd(14, 26); p.vy = rnd(800, 1100); p.vx = -220; p.a = rnd(.14, .34); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt; rainDraw(p, '180,195,225'); }, out: fall, overlay: 'rgba(10,14,30,.12)' },
    bloodrain: { n: 100,
      spawn(p, i) { p.x = rnd(-40, W + 120); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.len = rnd(12, 24); p.vy = rnd(560, 820); p.vx = -90; p.a = rnd(.25, .55); p.w = rnd(1, 1.6); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt; rainDraw(p, '150,18,28'); }, out: fall, overlay: 'rgba(90,0,10,.08)' },
    sakura: { n: 34,
      spawn(p, i) { p.x = rnd(-40, W + 40); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.s = rnd(5, 9); p.vy = rnd(28, 60); p.vx = rnd(10, 40); p.rot = rnd(0, 6.28); p.vr = rnd(-1.6, 1.6); p.ph = rnd(0, 6.28); p.a = rnd(.55, .9);
        p.c = pick(['#f9c9d6', '#f5b5c8', '#fbd7e1', '#f2a7bd']); },
      step(p, dt) { p.ph += dt * 1.4; p.rot += p.vr * dt; p.x += (p.vx + Math.sin(p.ph) * 22) * dt; p.y += p.vy * dt; petal(p); }, out: fall },
    leaves: { n: 26,
      spawn(p, i) { p.x = rnd(-40, W + 40); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.s = rnd(7, 12); p.vy = rnd(30, 70); p.vx = rnd(20, 60); p.rot = rnd(0, 6.28); p.vr = rnd(-2, 2); p.ph = rnd(0, 6.28); p.a = rnd(.6, .9);
        p.c = pick(['#c8642a', '#d98a2b', '#a8431f', '#e0a93a', '#8a3a1a']); },
      step(p, dt) { p.ph += dt * 1.6; p.rot += p.vr * dt; p.x += (p.vx + Math.sin(p.ph) * 30) * dt; p.y += p.vy * dt; leaf(p); }, out: fall },
    dandelion: { n: 22,
      spawn(p, i) { p.x = rnd(-60, W); p.y = i ? rnd(0, H) : H + rnd(10, 60); p.s = rnd(5, 9); p.vy = -rnd(10, 26); p.vx = rnd(14, 34); p.ph = rnd(0, 6.28); p.rot = rnd(-.4, .4); p.a = rnd(.45, .8); },
      step(p, dt) { p.ph += dt * .9; p.x += (p.vx + Math.sin(p.ph) * 10) * dt; p.y += (p.vy + Math.cos(p.ph * .7) * 6) * dt;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot + Math.sin(p.ph) * .25); ctx.globalAlpha = p.a;
        ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = .6; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, p.s * 1.3);
        for (let k = 0; k < 9; k++) { const an = -Math.PI / 2 + (k - 4) * .32; ctx.moveTo(0, 0); ctx.lineTo(Math.cos(an) * p.s, Math.sin(an) * p.s); }
        ctx.stroke(); ctx.fillStyle = 'rgba(255,255,255,.9)'; ctx.beginPath(); ctx.arc(0, p.s * 1.3, .9, 0, 6.283); ctx.fill(); ctx.restore(); },
      out: p => p.y < -40 || p.x > W + 60 },
    embers: { n: 60, add: true,
      spawn(p, i) { p.x = rnd(0, W); p.y = i ? rnd(0, H) : H + rnd(5, 40); p.r = rnd(.8, 2.2); p.vy = -rnd(30, 90); p.vx = rnd(-15, 25); p.ph = rnd(0, 6.28); p.life = rnd(.6, 1); p.hue = rnd(14, 38); },
      step(p, dt) { p.ph += dt * rnd(4, 9); p.x += (p.vx + Math.sin(p.ph * .5) * 18) * dt; p.y += p.vy * dt;
        const a = (.55 + .45 * Math.sin(p.ph)) * p.life * Math.min(1, (p.y / H) + .25);
        glow(p.x, p.y, p.r * 5, `hsla(${p.hue},100%,55%,A)`, a * .35);
        ctx.fillStyle = `hsla(${p.hue + 10},100%,72%,${a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill(); },
      out: rise, overlay: 'rgba(120,40,0,.05)' },
    ash: { n: 70,
      spawn(p, i) { p.x = rnd(-40, W + 40); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.s = rnd(1.2, 3.2); p.vy = rnd(14, 34); p.vx = rnd(-6, 14); p.rot = rnd(0, 6.28); p.vr = rnd(-2, 2); p.ph = rnd(0, 6.28); p.a = rnd(.25, .6); p.g = Math.round(rnd(110, 170)); },
      step(p, dt) { p.ph += dt; p.rot += p.vr * dt; p.x += (p.vx + Math.sin(p.ph) * 10) * dt; p.y += p.vy * dt;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = `rgba(${p.g},${p.g},${p.g},${p.a})`; ctx.fillRect(-p.s, -p.s * .5, p.s * 2, p.s); ctx.restore(); },
      out: fall, overlay: 'rgba(40,36,32,.08)' },
    fog: { n: 12,
      spawn(p, i) { p.r = rnd(Math.max(W, H) * .25, Math.max(W, H) * .45); p.x = i ? rnd(-p.r, W + p.r) : -p.r; p.y = rnd(H * .1, H * 1.05); p.vx = rnd(8, 22); p.a = rnd(.08, .16); p.ph = rnd(0, 6.28); },
      step(p, dt) { p.ph += dt * .2; p.x += p.vx * dt; glow(p.x, p.y + Math.sin(p.ph) * 12, p.r, 'rgba(200,205,215,A)', p.a); },
      out: p => p.x - p.r > W },
    sand: { n: 140,
      spawn(p, i) { p.x = i ? rnd(-W * .3, W) : -rnd(20, 200); p.y = rnd(-20, H + 20); p.len = rnd(14, 60); p.vx = rnd(520, 900); p.vy = rnd(-20, 40); p.a = rnd(.12, .4); p.w = rnd(.6, 1.6); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt;
        ctx.strokeStyle = `rgba(214,180,128,${p.a})`; ctx.lineWidth = p.w; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.len, p.y - p.len * p.vy / p.vx); ctx.stroke(); },
      out: p => p.x - p.len > W + 20 || p.y > H + 40, overlay: 'rgba(150,110,55,.10)' },
    fireflies: { n: 30, add: true,
      spawn(p) { p.x = rnd(0, W); p.y = rnd(H * .15, H); p.vx = rnd(-14, 14); p.vy = rnd(-10, 10); p.ph = rnd(0, 6.28); p.sp = rnd(.8, 1.8); p.r = rnd(1.2, 2.2);
        p.c = pick(['200,255,160', '170,215,255', '235,250,180']); },
      step(p, dt) { p.ph += dt * p.sp; p.vx += rnd(-20, 20) * dt; p.vy += rnd(-20, 20) * dt; p.vx *= .99; p.vy *= .99;
        p.x += p.vx * dt; p.y += p.vy * dt; if (p.x < -20) p.x = W + 20; if (p.x > W + 20) p.x = -20; if (p.y < -20) p.y = H + 20; if (p.y > H + 20) p.y = -20;
        const a = Math.max(0, Math.sin(p.ph)) ** 2;
        glow(p.x, p.y, p.r * 7, `rgba(${p.c},A)`, a * .4); ctx.fillStyle = `rgba(${p.c},${a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill(); },
      out: () => false },
    meteors: { n: 5, add: true,
      spawn(p, i) { p.wait = i ? rnd(0, 3) : rnd(.6, 4); p.x = rnd(W * .3, W * 1.2); p.y = rnd(-H * .3, H * .25); const sp = rnd(700, 1100); p.vx = -sp * .8; p.vy = sp * .5; p.len = rnd(90, 180); p.a = rnd(.6, 1); p.t = 0; },
      step(p, dt) { if (p.wait > 0) { p.wait -= dt; return; } p.t += dt; p.x += p.vx * dt; p.y += p.vy * dt;
        const k = p.len / Math.hypot(p.vx, p.vy), tx = p.x - p.vx * k, ty = p.y - p.vy * k;
        const g = ctx.createLinearGradient(p.x, p.y, tx, ty); g.addColorStop(0, `rgba(255,255,255,${p.a})`); g.addColorStop(.3, `rgba(170,195,255,${p.a * .5})`); g.addColorStop(1, 'rgba(120,150,255,0)');
        ctx.strokeStyle = g; ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(tx, ty); ctx.stroke();
        glow(p.x, p.y, 6, 'rgba(220,230,255,A)', p.a * .8); },
      out: p => p.wait <= 0 && (p.x < -200 || p.y > H + 200) },
    hail: { n: 70,
      spawn(p, i) { p.x = rnd(-40, W + 80); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.r = rnd(1.4, 3); p.vy = rnd(520, 760); p.vx = -rnd(30, 70); p.a = rnd(.55, .9); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt;
        ctx.fillStyle = `rgba(230,238,250,${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
        ctx.strokeStyle = `rgba(230,238,250,${p.a * .25})`; ctx.lineWidth = p.r; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - p.vx * .02, p.y - p.vy * .02); ctx.stroke(); },
      out: fall },
    // 오로라 : 물결치는 띠를 따라 가는 세로 빛줄기(커튼)를 촘촘히 세웁니다. 아래 가장자리는 밝은 초록,
    // 위로 갈수록 청록 → 보라로 옅어집니다. 저해상도 캔버스에 그린 뒤 부드럽게 확대해서 번지는 느낌을 냅니다.
    aurora: { n: 3, add: true,
      spawn(p) { const k = parts.length; p.base = H * (.24 + k * .08) + rnd(-12, 12); p.tilt = rnd(-.18, .18) * H; p.amp = rnd(40, 70); p.f1 = rnd(.0045, .0075); p.f2 = rnd(.011, .018);
        p.sp = rnd(.18, .3) * (k % 2 ? -1 : 1); p.h = rnd(200, 320) * (k === 0 ? 1 : .7); p.ph = rnd(0, 6.28); p.str = k === 0 ? 1 : rnd(.5, .75); p.alt = k === 2; },
      step(p, dt) { p.ph += dt * p.sp; Aur.draw(p); }, out: () => false, pre() { Aur.begin(); }, post() { Aur.end(); } },
    godrays: { n: 6, add: true,
      spawn(p) { p.x = rnd(-W * .1, W * .9); p.w = rnd(40, 140); p.sk = rnd(H * .25, H * .5); p.sp = rnd(.2, .5); p.ph = rnd(0, 6.28); p.a = rnd(.10, .2); p.vx = rnd(-4, 4); },
      step(p, dt) { p.ph += dt * p.sp; p.x += p.vx * dt; const a = p.a * (.5 + .5 * Math.sin(p.ph));
        const g = ctx.createLinearGradient(p.x, 0, p.x + p.sk, H); g.addColorStop(0, `rgba(255,244,220,${a})`); g.addColorStop(1, 'rgba(255,244,220,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(p.x, -10); ctx.lineTo(p.x + p.w, -10); ctx.lineTo(p.x + p.w * 1.8 + p.sk, H); ctx.lineTo(p.x + p.sk, H); ctx.closePath(); ctx.fill(); },
      out: p => p.x > W + 200 || p.x < -W * .4 },
    stars: { n: 90, add: true,
      spawn(p) { p.x = rnd(0, W); p.y = rnd(0, H); p.s = rnd(1.5, 4.5); p.ph = rnd(0, 6.28); p.sp = rnd(.6, 2); },
      step(p, dt) { p.ph += dt * p.sp; const a = Math.max(0, Math.sin(p.ph)) ** 3, r = p.s * (.6 + .4 * a); if (a < .02) return;
        ctx.fillStyle = `rgba(235,240,255,${a * .9})`; ctx.beginPath(); const k = r * .18;
        ctx.moveTo(p.x, p.y - r); ctx.quadraticCurveTo(p.x + k, p.y - k, p.x + r, p.y); ctx.quadraticCurveTo(p.x + k, p.y + k, p.x, p.y + r);
        ctx.quadraticCurveTo(p.x - k, p.y + k, p.x - r, p.y); ctx.quadraticCurveTo(p.x - k, p.y - k, p.x, p.y - r); ctx.fill();
        glow(p.x, p.y, r * 3, 'rgba(170,190,255,A)', a * .25); },
      out: () => false },
    // 수면 : 물속에서 올려다본 듯 일렁이는 빛 무늬(코스틱). 낮은 해상도로 계산해서 부드럽게 확대합니다.
    water: { n: 1, add: true,
      spawn() {}, step(p, dt) { Water.draw(dt); }, out: () => false },
    arrows: { n: 34,
      spawn(p, i) { p.x = rnd(-W * .3, W + 100); p.y = i ? rnd(-H, H) : rnd(-120, -20); const sp = rnd(750, 1000); p.vx = sp * .42; p.vy = sp; p.len = rnd(30, 44); p.a = rnd(.55, .85); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt; const an = Math.atan2(p.vy, p.vx);
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(an); ctx.globalAlpha = p.a;
        ctx.strokeStyle = '#cfc6b6'; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(-p.len, 0); ctx.lineTo(0, 0); ctx.stroke();
        ctx.fillStyle = '#d9d9de'; ctx.beginPath(); ctx.moveTo(4, 0); ctx.lineTo(-3, -2.6); ctx.lineTo(-3, 2.6); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = '#a8584a'; ctx.lineWidth = 1; ctx.beginPath();
        ctx.moveTo(-p.len, 0); ctx.lineTo(-p.len - 4, -3); ctx.moveTo(-p.len + 4, 0); ctx.lineTo(-p.len, -3);
        ctx.moveTo(-p.len, 0); ctx.lineTo(-p.len - 4, 3); ctx.moveTo(-p.len + 4, 0); ctx.lineTo(-p.len, 3); ctx.stroke(); ctx.restore(); },
      out: fall },
    smoke: { n: 22,
      spawn(p, i) { p.x = rnd(-50, W + 50); p.y = i ? rnd(H * .2, H + 80) : H + rnd(40, 120); p.r = rnd(60, 140); p.vy = -rnd(14, 34); p.vx = rnd(4, 18); p.a = rnd(.14, .26); p.gr = rnd(6, 14); },
      step(p, dt) { p.x += p.vx * dt; p.y += p.vy * dt; p.r += p.gr * dt; const fade = Math.min(1, Math.max(0, p.y / H + .1));
        glow(p.x, p.y, p.r, 'rgba(22,22,26,A)', p.a * fade); },
      out: p => p.y + p.r < 0 || p.x - p.r > W, overlay: 'rgba(20,18,16,.06)' },
    poison: { n: 12,
      spawn(p, i) { p.r = rnd(Math.max(W, H) * .2, Math.max(W, H) * .4); p.x = i ? rnd(-p.r, W + p.r) : -p.r; p.y = rnd(H * .3, H * 1.1); p.vx = rnd(6, 18); p.a = rnd(.08, .16); p.ph = rnd(0, 6.28); },
      step(p, dt) { p.ph += dt * .25; p.x += p.vx * dt; glow(p.x, p.y + Math.sin(p.ph) * 14, p.r, 'rgba(110,200,70,A)', p.a); },
      out: p => p.x - p.r > W, overlay: 'rgba(25,55,10,.08)' },
    feathers: { n: 18,
      spawn(p, i) { p.x = rnd(-40, W + 40); p.y = i ? rnd(-H, H) : rnd(-60, -10); p.s = rnd(10, 18); p.vy = rnd(24, 50); p.vx = rnd(-10, 20); p.rot = rnd(0, 6.28); p.vr = rnd(-1, 1); p.ph = rnd(0, 6.28); p.a = rnd(.7, .95); },
      step(p, dt) { p.ph += dt * 1.1; p.rot += (p.vr + Math.sin(p.ph) * .8) * dt; p.x += (p.vx + Math.sin(p.ph) * 34) * dt; p.y += p.vy * dt;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.globalAlpha = p.a;
        ctx.fillStyle = '#16161a'; ctx.beginPath(); ctx.moveTo(0, -p.s); ctx.quadraticCurveTo(p.s * .42, -p.s * .2, p.s * .1, p.s * .8);
        ctx.lineTo(-p.s * .1, p.s * .8); ctx.quadraticCurveTo(-p.s * .42, -p.s * .2, 0, -p.s); ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,.22)'; ctx.lineWidth = .7; ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, -p.s * .9); ctx.lineTo(0, p.s * 1.1); ctx.strokeStyle = 'rgba(255,255,255,.3)'; ctx.stroke(); ctx.restore(); },
      out: fall },
    arcane: { n: 50, add: true,
      spawn(p, i) { p.cx = rnd(0, W); p.y = i ? rnd(0, H) : H + rnd(10, 40); p.rad = rnd(6, 26); p.ph = rnd(0, 6.28); p.sp = rnd(1.5, 3.5); p.vy = -rnd(30, 70); p.r = rnd(1, 2.2);
        p.hue = pick([255, 270, 290, 220, 190]); },
      step(p, dt) { p.ph += dt * p.sp; p.y += p.vy * dt; p.cx += Math.sin(p.ph * .3) * 6 * dt; const x = p.cx + Math.cos(p.ph) * p.rad;
        const a = .5 + .5 * Math.sin(p.ph * 2);
        glow(x, p.y, p.r * 6, `hsla(${p.hue},100%,65%,A)`, a * .35); ctx.fillStyle = `hsla(${p.hue},100%,82%,${.4 + a * .6})`; ctx.beginPath(); ctx.arc(x, p.y, p.r, 0, 6.283); ctx.fill(); },
      out: p => p.y < -40, overlay: 'rgba(40,10,70,.06)' },
    glitch: { n: 7, add: true,
      spawn(p) { p.life = rnd(.05, .35); p.wait = rnd(0, 1.6); p.y = rnd(0, H); p.h = rnd(2, 18); p.x = rnd(-W * .2, W * .6); p.w = rnd(W * .2, W * .8); p.c = pick(['92,134,255', '255,60,90', '120,255,220']); p.a = rnd(.05, .14); },
      step(p, dt) { if (p.wait > 0) { p.wait -= dt; return; } p.life -= dt; if (Math.random() < .3) p.x += rnd(-30, 30);
        ctx.fillStyle = `rgba(${p.c},${p.a})`; ctx.fillRect(p.x, p.y, p.w, p.h); ctx.fillStyle = `rgba(255,255,255,${p.a * .4})`; ctx.fillRect(p.x + rnd(-6, 6), p.y + p.h / 2, p.w * .6, 1); },
      out: p => p.wait <= 0 && p.life <= 0, scan: true },
    lightning: { n: 0, lightning: true },
  };
  function cfgN() {
    const d = K[kind]; if (!d) return 0;
    const area = Math.min(1.6, (W * H) / (1400 * 900));
    return Math.round(d.n * [0, .5, 1, 1.8][amount] * Math.max(.45, area));
  }
  function reset() { parts = []; const d = K[kind]; if (kind === 'aurora') Aur.k = [0, .55, .8, 1.05][amount]; const N = kind === 'aurora' || kind === 'water' ? K[kind].n : cfgN();
    for (let i = 0; i < N; i++) { const p = {}; d.spawn(p, true); parts.push(p); } nextBolt = performance.now() + rnd(1500, 4000); }
  function makeBolt() {
    let x = rnd(W * .15, W * .85), y = 0; const pts = [[x, y]];
    while (y < H * rnd(.45, .75)) { x += rnd(-40, 40); y += rnd(18, 46); pts.push([x, y]); }
    return { pts, a: 1 };
  }
  function frame(t) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(.05, (t - (last || t)) / 1000); last = t; T += dt;
    const d = K[kind]; if (!d) return;
    ctx.clearRect(0, 0, W, H);
    if (d.overlay) { ctx.fillStyle = d.overlay; ctx.fillRect(0, 0, W, H); }
    if (d.scan) { ctx.fillStyle = 'rgba(255,255,255,.022)'; for (let y = (T * 40) % 4; y < H; y += 4) ctx.fillRect(0, y, W, 1); }
    ctx.globalCompositeOperation = d.add ? 'lighter' : 'source-over';
    if (d.pre) d.pre();
    for (const p of parts) { d.step(p, dt); if (d.out(p)) d.spawn(p, false); }
    if (d.post) d.post();
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    if (d.lightning) {
      if (t > nextBolt) { flash = 1; bolt = makeBolt(); nextBolt = t + rnd(3500, 9000) / Math.max(1, amount * .8); }
      if (flash > 0) { ctx.fillStyle = `rgba(200,215,255,${flash * .16})`; ctx.fillRect(0, 0, W, H); flash = Math.max(0, flash - dt * 2.6); }
      if (bolt) {
        ctx.save(); ctx.strokeStyle = `rgba(220,230,255,${bolt.a})`; ctx.lineWidth = 1.6; ctx.shadowColor = 'rgba(160,190,255,.8)'; ctx.shadowBlur = 12;
        ctx.beginPath(); bolt.pts.forEach((q, i) => i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.stroke(); ctx.restore();
        bolt.a -= dt * 3.2; if (bolt.a <= 0) bolt = null;
      }
    }
  }
  function start() { if (!raf && kind !== 'none' && !document.hidden) { last = 0; raf = requestAnimationFrame(frame); } }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  window.addEventListener('resize', () => { if (kind === 'none') return; resize(); reset(); });
  document.addEventListener('visibilitychange', () => { document.hidden ? stop() : start(); });
  return {
    kinds: Object.keys(K),
    set(k, amt, layer) {
      if (!cv) return;
      cv.classList.toggle('front', layer === 'front');
      k = K[k] ? k : 'none';
      if (k === kind && amt === amount) return;
      kind = k; amount = amt || 2;
      stop();
      cv.classList.toggle('on', kind !== 'none');
      if (kind === 'none') { ctx.clearRect(0, 0, W, H); return; }
      resize(); reset(); start();
    },
  };
})();

// ==================================================================
// 우체통 : 캐릭터끼리 편지. 받는 사람 지정 / 랜덤, 익명 보내기. 운영진은 전체 편지를 볼 수 있습니다.
// ==================================================================
let mailData = null, mailTab = 'inbox', mailOpenId = null;
const mailDraft = { mode: 'pick', to: [], q: '', anon: true, text: '', images: [], era: null, year: null, noYear: false, randomCount: 1 };
// 편지의 시기 : 대분류(1차 러닝 · 1~2차 리뉴얼 · 2차 러닝 · 2~3차 리뉴얼 · 3차 기간) → 리뉴얼 기간만 연도를 고릅니다.
// 목록은 서버(mailbox.ERAS)가 보내 주고, 처음에는 지금 마이룸 기간의 러닝을 골라 둡니다.
function mailEras() { return (mailData && mailData.eras) || []; }
function mailEra(id) { return mailEras().find(e => e.id === id) || null; }
function mailEraLabel(l) {
  const e = l && mailEra(l.era);
  return e ? `空歷 ${l.year != null ? l.year : e.from}年 · ${e.name}` : '';
}
function mailEnsureEra() {
  // 시기(리뉴얼 기간)는 운영진이 정한 지금 기간, 쓰는 사람은 연도만 고릅니다.
  const e = mailEra(mailData && mailData.era_now) || mailEras()[0]; if (!e) return;
  if (mailDraft.era !== e.id) { mailDraft.era = e.id; mailDraft.year = null; }
  if (mailDraft.year == null || mailDraft.year < e.from || mailDraft.year > e.to) mailDraft.year = e.from;
}
// 나이 : 캐릭터 정보의 나이 = 1차 입학(空歷 514年) 때 나이. 고른 해에 맞춰 더하거나 뺍니다.
function mailAgeAt(age, year) { return age == null ? null : age + (year - ((mailData && mailData.age_base) || 514)); }
// 나이 안내 : 내 캐릭터 = 내 1차 나이 + (고른 해 − 514), 전체 나이 폭 = 1차 기준 13~16세(4살 차이)에 같은 만큼 더한 범위
function mailAgeCells(year) {
  const d = mailData || {};
  const lo = d.age_min != null ? d.age_min : 13, hi = d.age_max != null ? d.age_max : 16;
  const fmt = a => a < 0 ? '출생 전' : `${a}세`;
  const mine = d.my_age != null ? fmt(mailAgeAt(d.my_age, year)) : '-';
  const range = `${fmt(mailAgeAt(lo, year))} ~ ${fmt(mailAgeAt(hi, year))}`;
  return `<div class="my-cell"><em>내 캐릭터</em><b>${mine}</b></div><div class="my-cell"><em>전체 나이 폭</em><b>${range}</b></div>`;
}
function mailEraHtml() {
  mailEnsureEra();
  const e = mailEra(mailDraft.era); if (!e) return '';
  const off = mailDraft.noYear;
  return `<div class="mail-year-grid ${off ? 'off' : ''}">
      <div class="my-step">
        <button onclick="mailStepYear(-1)" ${off || mailDraft.year <= e.from ? 'disabled' : ''} aria-label="이전 해"><i class="fa-solid fa-minus"></i></button>
        <div class="my-y"><b>空歷 ${mailDraft.year}年</b><span>${e.from} ~ ${e.to}年</span></div>
        <button onclick="mailStepYear(1)" ${off || mailDraft.year >= e.to ? 'disabled' : ''} aria-label="다음 해"><i class="fa-solid fa-plus"></i></button>
      </div>
      ${mailAgeCells(mailDraft.year)}
    </div>
    <label class="my-none"><input type="checkbox" ${off ? 'checked' : ''} onchange="mailDraft.noYear=this.checked; mailRefreshEra()"> 연도 없음 <span>(시기 · 연도 없이 보내요)</span></label>`;
}
function mailStepYear(d) { const e = mailEra(mailDraft.era); if (!e) return; mailDraft.year = Math.max(e.from, Math.min(e.to, (mailDraft.year || e.from) + d)); mailRefreshEra(); }
function mailRefreshEra() { const el = document.getElementById('mailEraBox'); if (el) el.innerHTML = mailEraHtml(); }
// 편지 첨부 이미지 : 4장까지, 장당 15MB(사이트 공통 이미지 기준) (png · jpg · gif · webp). 첨부 칸을 누르거나 그 칸에 끌어다 놓아요(본문 붙여넣기는 안 받아요).
const MAIL_IMG_MAX = 4, MAIL_IMG_BYTES = UPLOAD_IMG_BYTES;
function mailAddImages(files) {
  const list = [...(files || [])].filter(f => f && /^image\/(png|jpe?g|gif|webp)$/.test(f.type));
  if (!list.length) { if (files && files.length) showShopToast('png · jpg · gif · webp 이미지만 붙일 수 있어요.'); return; }
  list.forEach(f => {
    if (mailDraft.images.length >= MAIL_IMG_MAX) { showShopToast(`이미지는 ${MAIL_IMG_MAX}장까지 붙일 수 있어요.`); return; }
    if (f.size > MAIL_IMG_BYTES) { showShopToast(`${f.name || '이미지'}는 ${UPLOAD_IMG_MB}MB가 넘어서 붙일 수 없어요.`); return; }
    const item = { name: f.name || 'image', url: URL.createObjectURL(f), buf: null };
    mailDraft.images.push(item);
    f.arrayBuffer().then(b => { item.buf = b; });
  });
  mailRefreshImages();
}
function mailRemoveImage(i) {
  const it = mailDraft.images.splice(i, 1)[0];
  if (it) URL.revokeObjectURL(it.url);
  mailRefreshImages();
}
function mailClearImages() { mailDraft.images.forEach(it => URL.revokeObjectURL(it.url)); mailDraft.images = []; }
function mailImagesHtml() {
  return mailDraft.images.map((it, i) => `<span class="mail-thumb"><img src="${it.url}" alt=""><button onclick="mailRemoveImage(${i})" aria-label="빼기"><i class="fa-solid fa-xmark"></i></button></span>`).join('')
    // 첨부 칸 : 누르거나 이 칸에 끌어다 놓기(본문에는 이미지를 넣지 않아요). 한 장 붙일 때마다 같은 크기 칸이 옆에 생겨요(최대 4장)
    + (mailDraft.images.length < MAIL_IMG_MAX ? `<button class="mail-attach" onclick="document.getElementById('mailImgFile').click()"
        ondragover="event.preventDefault(); this.classList.add('drag')" ondragleave="this.classList.remove('drag')"
        ondrop="event.preventDefault(); this.classList.remove('drag'); mailAddImages(event.dataTransfer.files)"><i class="fa-regular fa-image"></i><span>${mailDraft.images.length} / ${MAIL_IMG_MAX}</span></button>` : '');
}
function mailRefreshImages() { const el = document.getElementById('mailImgs'); if (el) el.innerHTML = mailImagesHtml(); }
function mailOnPaste(e) {
  const files = [...((e.clipboardData && e.clipboardData.items) || [])].filter(x => x.kind === 'file').map(x => x.getAsFile());
  if (files.length) { e.preventDefault(); mailAddImages(files); }
}
function mailEsc(t) { return shopEsc(t); }
function mailTime(at) {
  return etStamp(new Date(at * 1000));
}
// 실제로 보낸 시각(현실 날짜) : 26.10.01 PM 3:12
function mailRealTime(at) {
  const d = new Date(at * 1000), p = n => String(n).padStart(2, '0'), h = d.getHours();
  return `${String(d.getFullYear()).slice(2)}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${h < 12 ? 'AM' : 'PM'} ${h % 12 || 12}:${p(d.getMinutes())}`;
}
// 편지 속 연도(설정상 공력) : 空歷 520年
function mailYearLabel(l) { const e = l && mailEra(l.era); return e ? `空歷 ${l.year != null ? l.year : e.from}年` : ''; }
function updateMailDot() {
  const dot = document.getElementById('mailDot');
  if (dot) dot.classList.toggle('on', !!(mailData && mailData.unread > 0));
  syncNewsDot();
}
// 세로 태블릿·휴대폰 : 공지와 우체통을 '소식' 탭 하나로 묶어요.
function syncNewsDot() {
  const n = document.getElementById('noticeDot'), m = document.getElementById('mailDot');
  const nOn = !!(n && n.classList.contains('on')), mOn = !!(m && m.classList.contains('on')) && !document.body.classList.contains('logged-out');
  const set = (id, on) => { const el = document.getElementById(id); if (el) el.classList.toggle('on', on); };
  set('newsDot', nOn || mOn); set('newsNoticeDot', nOn); set('newsMailDot', mOn);
  document.querySelectorAll('.nsw-notice-dot').forEach(el => el.classList.toggle('on', nOn));
  document.querySelectorAll('.nsw-mail-dot').forEach(el => el.classList.toggle('on', mOn));
}
function openNewsSheet() { syncNewsDot(); document.getElementById('newsSheet').style.display = 'flex'; }
// 휴대폰 · 태블릿 '소식' 탭 : 바로 공지 페이지로. 일반 룸은 공지 · 우체통 페이지 위쪽 전환 버튼으로 오갑니다.
function openNewsTab() { syncNewsDot(); openNotices(); }
// 공지 ↔ 우체통 전환은 같은 창 안에서 탭을 바꾸는 것처럼 : 창이 새로 열리는 애니메이션 없이 바로 바꿔요.
function switchNews(k) {
  const still = id => document.getElementById(id).classList.add('no-anim');
  if (k === 'mail') {
    if (noticeEditing) { closeNotices(); return; }
    still('mailModal'); closeNotices(); openMail();
  } else { still('noticeModal'); closeMail(); openNotices(); }
}
function openMail(tab) {
  if (tab) mailTab = tab;
  mailOpenId = null;
  document.getElementById('mailModal').style.display = 'flex';
  socket.emit('mail_list');
  renderMail();
  mailRetry(0);
}
// 응답이 안 오면(재접속 중 등) 조금 뒤에 다시 물어봐요. 무한 로딩 방지.
function mailRetry(n) {
  clearTimeout(mailRetry.t);
  mailRetry.t = setTimeout(() => {
    if (document.getElementById('mailModal').style.display !== 'flex' || (mailData && mailData.me) || n >= 4) return;
    if (socket.connected) socket.emit('mail_list');
    mailRetry(n + 1);
  }, 2500);
}
function closeMail() { const m = document.getElementById('mailModal'); m.style.display = 'none'; m.classList.remove('no-anim'); }
var mailListTab = 'inbox';   // 편지 쓰기에서 돌아갈 목록
function setMailTab(t) {
  if (t === 'write' && mailTab !== 'write') mailListTab = mailTab;
  mailTab = t; mailOpenId = null; renderMail();
  const b = document.getElementById('mailBody'); if (b) b.scrollTop = 0;
}
socket.on('joined', () => socket.emit('mail_list'));
socket.on('mail_data', (d) => {
  mailData = d; updateMailDot();
  if (typeof opsRenderMailEras === 'function') opsRenderMailEras();
  if (mailTab === 'write') mailRefreshEra();
  // 편지를 쓰는 중이면 입력이 끊기지 않도록 다시 그리지 않습니다.
  if (document.getElementById('mailModal').style.display === 'flex' && mailTab !== 'write') renderMail();
});
socket.on('mail_new', (d) => showShopToast(d && d.from ? `${d.from}에게서 편지가 왔어요.` : '새 편지가 도착했어요.'));
socket.on('mail_result', (d) => {
  showShopToast(d.message);
  if (d.ok) { mailDraft.text = ''; mailDraft.to = []; mailDraft.anon = true; mailClearImages(); mailTab = 'outbox'; mailOpenId = null; renderMail(); }
  else { const b = document.getElementById('mailSendBtn'); if (b) b.disabled = false; }
});

function renderMail() {
  const d = mailData || { me: null, inbox: [], outbox: [], roster: [] };
  const body = document.getElementById('mailBody'), tabsEl = document.getElementById('mailTabs');
  // 운영진일 때만 누구의 우체통인지 보여요(참가자는 늘 자기 우체통이라 필요 없어요)
  document.getElementById('mailMe').innerHTML = d.me && d.is_gm ? `<b>${mailEsc(d.me)}</b>의 우체통` : '';
  if (!d.me) {
    tabsEl.innerHTML = '';
    body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '우체통을 불러오는 중이에요');
    return;
  }
  // 받은 편지함 · 보낸 편지함(관리자는 전체)만 탭으로, 편지 쓰기는 오른쪽 별도 버튼(일반 메일 앱처럼)
  const tabs = [['inbox', 'fa-solid fa-inbox', '받은 편지함', d.unread], ['outbox', 'fa-solid fa-paper-plane', '보낸 편지함']];
  if (d.is_gm) tabs.push(['all', 'fa-solid fa-envelopes-bulk', '전체 편지']);
  // 편지 쓰기는 따로 들어가는 화면 : 탭 대신 '← 새 편지' 머리(눌러서 목록으로 돌아가기)
  tabsEl.classList.toggle('write-mode', mailTab === 'write');
  document.getElementById('mailBody').classList.toggle('writing', mailTab === 'write');
  tabsEl.innerHTML = mailTab === 'write'
    ? `<div class="mail-write-head"><button class="mail-back" onclick="setMailTab(mailListTab || 'inbox')" aria-label="목록으로" data-tip="목록으로"><i class="fa-solid fa-chevron-left"></i></button><b>새 편지</b></div>`
    : tabs.map(([k, ic, t, n]) => `<button class="shop-tab ${mailTab === k ? 'active' : ''}" onclick="setMailTab('${k}')"><i class="${ic}"></i>${t}${n ? `<span class="cnt">${n}</span>` : ''}</button>`).join('');
  // 편지 쓰기 : 목록 위에 떠 있는 버튼(오른쪽 아래). 쓰는 중이거나 미리보기(보낼 수 없는 방)에서는 숨겨요.
  document.getElementById('mailFab').style.display = mailTab === 'write' ? 'none' : '';
  const pv = d.preview ? '<div class="mail-preview"><i class="fa-solid fa-eye"></i>미리보기예요. 이 방에서는 편지를 보내거나 받을 수 없어요.</div>' : '';
  if (mailTab === 'write') {
    const keep = body.scrollTop;   // 다시 그려도 보던 위치 그대로(덜컹거리지 않게)
    body.innerHTML = mailComposeHtml(d);   // 미리보기 안내는 목록에만(편지 쓰기에서는 중복이라 빼요)
    body.scrollTop = keep;
    const sb = document.getElementById('mailSendBtn');
    if (d.preview && sb) sb.remove();   // 미리보기 방 : 보낼 수 없으니 보내기 버튼 자체를 빼요(위 안내로 충분)
    return;
  }
  const list = mailTab === 'outbox' ? d.outbox : mailTab === 'all' ? (d.all || []) : d.inbox;
  const open = mailOpenId && list.find(l => l.id === mailOpenId);
  if (open) { body.innerHTML = mailLetterHtml(open, d); return; }
  if (!list.length) {
    body.innerHTML = pv + (mailTab === 'inbox' ? emptyHtml('fa-inbox', '아직 받은 편지가 없어요', '누군가 편지를 보내면 여기에 모여요.')
      : mailTab === 'outbox' ? emptyHtml('fa-paper-plane', '아직 보낸 편지가 없어요', '오른쪽 아래 버튼으로 첫 편지를 써 보세요.')
      : emptyHtml('fa-envelope-open', '편지가 없어요'));
    return;
  }
  // 시기(대분류 · 연도) 순으로 쌓기 : 늦은 시기가 위, 같은 시기 안에서는 최근 편지가 위. 시기가 없는 옛 편지는 맨 아래.
  const eraIdx = l => { const i = mailEras().findIndex(e => e.id === l.era); return i < 0 ? -1 : i; };
  const sorted = list.slice().sort((a, b) => (eraIdx(b) - eraIdx(a)) || ((b.year || 0) - (a.year || 0)) || (b.at - a.at));
  // 리뉴얼 기간 = 제목, 空歷 연도 = 부제목, 그 연도의 편지들은 블록 하나에 담습니다.
  const groups = [];
  sorted.forEach(l => {
    const e = mailEra(l.era);
    const eraName = e ? e.name : '시기 없음';
    const yearName = e ? (l.year != null ? `空歷 ${l.year}年` : '연도 없음') : '';
    let g = groups[groups.length - 1];
    if (!g || g.era !== eraName) { g = { era: eraName, years: [] }; groups.push(g); }
    let y = g.years[g.years.length - 1];
    if (!y || y.name !== yearName) { y = { name: yearName, items: [] }; g.years.push(y); }
    y.items.push(l);
  });
  body.innerHTML = '<div class="mail-list">' + groups.map(g => `<section class="mail-grp"><div class="mg-h">${mailEsc(g.era)}</div>`
    + g.years.map(y => (y.name ? `<div class="mg-y">${mailEsc(y.name)}</div>` : '') + `<div class="mg-block">${y.items.map(mailItemHtml).join('')}</div>`).join('')
    + '</section>').join('') + '</div>';
}
function mailItemHtml(l) {
    const unread = mailTab === 'inbox' && !l.read;
    let who;
    if (mailTab === 'inbox') who = l.from ? `<span class="mail-who">${mailEsc(l.from)}</span>` : '<span class="mail-who anon">익명</span>';
    else if (mailTab === 'outbox') who = (l.to_list || []).length > 1 ? `<span class="mail-who">To. ${mailEsc(l.to_list[0])} 외 ${l.to_list.length - 1}명</span>`
      : l.to ? `<span class="mail-who">To. ${mailEsc(l.to)}</span>` : '<span class="mail-who anon">To. 누군가 (랜덤)</span>';
    else who = `<span class="mail-who">${mailEsc(l.from)} → ${mailEsc(l.to)}</span>`;
    const badges = (l.anonymous && mailTab !== 'inbox' ? '<span class="mail-badge">익명</span>' : '') + (l.random && mailTab !== 'outbox' ? '<span class="mail-badge">랜덤</span>' : '') + (mailTab === 'outbox' && l.random && (l.send_count || 1) > 1 ? `<span class="mail-badge">${l.send_count}통</span>` : '');
    return `<div class="mail-item ${unread ? 'unread' : ''}" onclick="openLetter('${l.id}')">
      <div class="mail-ic"><i class="fa-solid ${unread ? 'fa-envelope' : 'fa-envelope-open'}"></i></div>
      <div class="mail-main"><div class="mail-top">${who}${badges}<span class="mail-time">${mailRealTime(l.at)}</span>${unread ? '<span class="mail-dot"></span>' : ''}</div>
      <div class="mail-prev">${(l.images || []).length ? `<i class="fa-regular fa-image"></i>${l.images.length > 1 ? `${l.images.length}장${l.text ? ' · ' : ''}` : ''}` : ''}${l.text ? mailEsc(l.text.replace(/\s+/g, ' ')) : (l.images || []).length === 1 ? '이미지' : ''}</div></div></div>`;
}
function openLetter(id) {
  mailOpenId = id;
  const l = mailData && mailData.inbox.find(x => x.id === id);
  if (mailTab === 'inbox' && l && !l.read) { l.read = true; mailData.unread = Math.max(0, (mailData.unread || 1) - 1); updateMailDot(); socket.emit('mail_read', { id }); }
  renderMail();
}
function mailLetterHtml(l, d) {
  const many = (l.to_list || []).length > 1;
  const toName = many ? l.to_list.map(mailEsc).join(', ') : l.to ? mailEsc(l.to) : '누군가 (랜덤)';
  const fromName = l.from ? mailEsc(l.from) : '익명';
  const canDelete = mailTab !== 'all' || d.is_gm;
  return `<div class="mail-write-head"><button class="mail-back" onclick="mailOpenId=null; renderMail()" aria-label="목록으로" data-tip="목록으로"><i class="fa-solid fa-chevron-left"></i></button><b>편지</b></div>
    <div class="mail-letter">${mailEraLabel(l) ? `<div class="era">${mailEsc(mailEraLabel(l))}</div>` : ''}<div class="to">To.<b>${toName}</b></div>${l.text ? `<div class="txt">${mailEsc(l.text)}</div>` : ''}${(l.images || []).length ? `<div class="mail-imgs n${Math.min(l.images.length, 4)}">${l.images.map(u => `<a href="${mailEsc(u)}" target="_blank" rel="noopener"><img src="${mailEsc(u)}" alt="" loading="lazy"></a>`).join('')}</div>` : ''}
      <div class="from">From.<b>${fromName}</b></div><div class="date">${mailYearLabel(l) ? `<span class="y">${mailYearLabel(l)}</span>` : ''}<span class="r"><i class="fa-regular fa-clock"></i>${mailRealTime(l.at)} 발송</span></div></div>
    <div class="mail-actions"><span style="display:flex;align-items:center;gap:10px;">
      ${canDelete ? `<button class="mail-del" onclick="deleteLetter('${l.id}')"><i class="fa-solid fa-trash-can"></i> ${mailTab === 'all' ? '편지 지우기' : '내 목록에서 지우기'}</button>` : ''}
      ${many && mailTab === 'outbox' ? `<span class="mail-badge">${l.to_list.length}명 중 ${l.read_count || 0}명 읽음</span>` : ''}${l.anonymous ? '<span class="mail-badge">익명 편지</span>' : ''}${l.random ? '<span class="mail-badge">랜덤 편지</span>' : ''}</span>
      ${mailTab === 'inbox' && l.from ? `<button class="btn mail-send" onclick="replyLetter(${mailEsc(JSON.stringify(l.from))})"><i class="fa-solid fa-reply"></i> 답장</button>` : ''}</div>`;
}
function deleteLetter(id) {
  uiConfirm('이 편지를 지울까요?', { title: '편지 지우기', okText: '지우기', danger: true }).then(ok => {
    if (!ok) return;
    socket.emit('mail_delete', { id }); mailOpenId = null; renderMail();
  });
}
function replyLetter(name) { mailDraft.mode = 'pick'; mailDraft.to = [name]; mailTab = 'write'; mailOpenId = null; renderMail(); }
function mailComposeHtml(d) {
  const roster = (d.roster || []).filter(n => n !== d.me);
  const q = mailDraft.q.trim().toLowerCase();
  const names = roster.filter(n => !q || n.toLowerCase().includes(q));
  const pick = mailDraft.mode === 'pick';
  mailEnsureEra();
  const era = mailEra(mailDraft.era);
  const touch = window.matchMedia('(hover: none)').matches;
  // ① 받는 사람 ② 연도 ③ 내용 순서로 칸을 나누고, 아래 보내기 줄은 늘 화면 아래에 붙어 있어요.
  return `<div class="mail-form">
    <section class="mf-sec">
      <header class="mf-h"><span class="mf-n">1</span><b>연도</b><span class="mf-aside">${era ? mailEsc(era.name) : ''}</span></header>
      <div id="mailEraBox">${mailEraHtml()}</div>
    </section>
    <section class="mf-sec">
      <header class="mf-h"><span class="mf-n">2</span><b>받는 사람</b><span class="mf-aside" id="mailToCnt">${mailToAside()}</span></header>
      <div class="mail-seg"><button class="${pick ? 'on' : ''}" onclick="mailDraft.mode='pick'; renderMail()"><i class="fa-solid fa-user"></i> 직접 고르기</button>
        <button class="${pick ? '' : 'on'}" onclick="mailDraft.mode='random'; renderMail()"><i class="fa-solid fa-shuffle"></i> 랜덤</button></div>
      ${pick ? `<div class="mf-search"><i class="fa-solid fa-magnifying-glass"></i><input type="text" placeholder="이름 검색" value="${mailEsc(mailDraft.q)}" oninput="mailDraft.q=this.value; mailRefreshNames()" autocomplete="off"></div>
        <div class="mail-picked" id="mailPicked">${mailPickedHtml()}</div>
        <div class="mail-names" id="mailNames">${mailNamesHtml(names)}</div>`
        : `<div class="mail-rcount"><span>몇 명에게</span>${[1, 2, 3, 4, 5].map(n => `<button class="${mailDraft.randomCount === n ? 'on' : ''}" onclick="mailDraft.randomCount=${n}; renderMail()">${n}명</button>`).join('')}</div>
          <div class="mail-rand"><i class="fa-solid fa-shuffle"></i><span>누구에게 갔는지는 보낸 사람에게도 공개되지 않아요.</span></div>`}
    </section>
    <section class="mf-sec">
      <header class="mf-h"><span class="mf-n">3</span><b>내용</b><span class="mf-aside mail-count" id="mailCount">${mailDraft.text.length} / 2000</span></header>
      <textarea class="mail-text" id="mailText" maxlength="2000" placeholder="편지를 써 주세요."
        ondrop="if(event.dataTransfer.files.length) event.preventDefault()" oninput="mailDraft.text=this.value; document.getElementById('mailCount').textContent=this.value.length+' / 2000'">${mailEsc(mailDraft.text)}</textarea>
      <div class="mail-imgrow" id="mailImgs">${mailImagesHtml()}</div>
      <input type="file" id="mailImgFile" accept="image/png,image/jpeg,image/gif,image/webp" multiple style="display:none" onchange="mailAddImages(this.files); this.value=''">
    </section>
    <div class="mail-foot">
      ${pick ? `<span class="mail-anon off"><i class="fa-solid fa-signature"></i>이름을 밝혀서 보내요</span>`
        : `<label class="mail-anon"><input type="checkbox" ${mailDraft.anon ? 'checked' : ''} onchange="mailDraft.anon=this.checked"> 익명으로 보내기</label>`}
      <button class="btn mail-send" id="mailSendBtn" onclick="sendLetter()"><i class="fa-solid fa-paper-plane"></i> 보내기</button>
    </div></div>`;
}
function mailToAside() {
  // 직접 고르기 · 랜덤 같은 모양 : '직접 n명' / '무작위 n명'
  if (mailDraft.mode !== 'pick') return `무작위 <b>${mailDraft.randomCount}명</b>`;
  return `직접 <b>${mailDraft.to.length}명</b>`;
}
function mailNamesHtml(names) {
  const me = mailData && mailData.me;
  // 맨 앞 : 나에게 보내기(편지가 어떻게 보이는지 확인해 볼 때)
  const self = me && !mailDraft.q.trim() ? `<button class="mail-name self ${mailDraft.to.includes(me) ? 'on' : ''}" onclick="mailToggleTo(${mailEsc(JSON.stringify(me))})">${mailDraft.to.includes(me) ? '<i class="fa-solid fa-check"></i> ' : '<i class="fa-solid fa-user-pen"></i> '}나에게</button>` : '';
  if (!names.length) return self || '<span class="mail-none">찾는 이름이 없어요.</span>';
  // 고르면 색만 바뀌어요(체크 아이콘을 끼워 넣으면 칸 폭이 바뀌어 이름들이 밀려요)
  return self + names.map(n => `<button class="mail-name ${mailDraft.to.includes(n) ? 'on' : ''}" onclick="mailToggleTo(${mailEsc(JSON.stringify(n))})">${mailEsc(n)}</button>`).join('');
}
// 직접 고르기는 여러 명을 고를 수 있어요 (한 사람에게 한 통씩 가요)
function mailToggleTo(n) {
  const i = mailDraft.to.indexOf(n);
  if (i >= 0) mailDraft.to.splice(i, 1); else if (mailDraft.to.length < 30) mailDraft.to.push(n); else showShopToast('한 번에 30명까지 보낼 수 있어요.');
  mailRefreshNames();
}
function mailPickedHtml() {
  if (!mailDraft.to.length) return '<span class="mail-picked-none">고른 사람이 여기에 보여요</span>';
  return mailDraft.to.map(n => `<span class="mail-chip">${n === (mailData && mailData.me) ? '나에게' : mailEsc(n)}<button onclick="mailToggleTo(${mailEsc(JSON.stringify(n))})" aria-label="빼기"><i class="fa-solid fa-xmark"></i></button></span>`).join('');
}
function mailRefreshNames() {
  const el = document.getElementById('mailNames');
  if (!el || !mailData) return;
  const q = mailDraft.q.trim().toLowerCase();
  el.innerHTML = mailNamesHtml((mailData.roster || []).filter(n => n !== mailData.me && (!q || n.toLowerCase().includes(q))));
  const pk = document.getElementById('mailPicked'); if (pk) pk.innerHTML = mailPickedHtml();
  const tc = document.getElementById('mailToCnt'); if (tc) tc.innerHTML = mailToAside();
}
function sendLetter() {
  const text = (mailDraft.text || '').trim();
  if (!text && !mailDraft.images.length) { showShopToast('편지 내용을 쓰거나 이미지를 붙여 주세요.'); return; }
  if (mailDraft.images.some(it => !it.buf)) { showShopToast('이미지를 읽는 중이에요. 잠시 뒤 다시 눌러 주세요.'); return; }
  const pick = mailDraft.mode === 'pick';
  if (pick && !mailDraft.to.length) { showShopToast('받는 사람을 골라 주세요.'); return; }
  mailEnsureEra();
  document.getElementById('mailSendBtn').disabled = true;
  socket.emit('mail_send', { to: pick ? mailDraft.to : [], random: !pick, random_count: mailDraft.randomCount, anonymous: pick ? false : mailDraft.anon, text,
    year: mailDraft.noYear ? null : mailDraft.year, no_year: !!mailDraft.noYear,
    images: mailDraft.images.map(it => ({ data: it.buf })) });
}

// ==================================================================
// 기숙사(마이룸) : 관(6명) 목록 → 방 구경 / 자기 방 꾸미기(아이소메트릭 방 위에 도트 소품을 자유 배치).
// 운영진은 관 배치·도트 자료·출처를 관리합니다. 위치는 방 그림의 픽셀 좌표로 저장합니다.
// ==================================================================
let dormData = null, dormRoster = [], dormView = 'halls', dormRoom = null, dormEdit = null, dormSel = -1, dormPick = null, dormCat = 'furniture';
let dormHallsDraft = null, dormCreditsDraft = null, dormSaving = false;
const dormUp = { buf: null, filename: '', url: '', name: '', category: 'deco', credit: '', nw: 0, nh: 0 };
const DORM_CATS = [['furniture', '가구'], ['deco', '소품'], ['wall', '벽 장식'], ['surface', '벽지·바닥'], ['room', '방']];
let dormSet = '', dormQ = '';
function dormIsGm() { return myControlInfo(lastBattleForPanel).scope === 'all'; }
// 마이룸 기간(1차 기숙사 · 2차 캠프 · 3차 선실) : 이름 · 단위(관/막사/구역)를 기간마다 바꿔 씁니다.
const DORM_P_DEFAULT = { id: 'p1', no: 1, name: '기숙사', en: 'Dorm', unit: '관', unit_en: 'Hall', status: 'current' };
function dormP() { return (dormData && dormData.period) || DORM_P_DEFAULT; }
// 받침에 따라 조사 고르기 : josa('막사', '을', '를') → '막사를'
function josa(w, withBatchim, without) {
  const c = String(w || '').charCodeAt(String(w || '').length - 1);
  const has = c >= 0xAC00 && c <= 0xD7A3 && (c - 0xAC00) % 28 > 0;
  return w + (has ? withBatchim : without);
}
let dormManagePeriod = null;   // 운영진 관리 화면에서 배치를 고치는 기간(기본 = 지금 기간)
let dormPast = { owner: null, rooms: [] };   // 지난 기간의 내 방(본인만)
// 기숙사 목록 New! : 방이 바뀐 때(꾸밈·음악·대사·방명록)가 이 브라우저에서 마지막으로 그 방을 본 때보다 나중이면 표시합니다.
// 처음 쓰는 브라우저는 지금 상태를 기준으로 잡아서 전부 New!가 뜨지 않게 합니다.
function dormSeenMap() { try { return JSON.parse(localStorage.getItem('dormSeen') || 'null'); } catch (e) { return null; } }
function dormSeenSave(m) { try { localStorage.setItem('dormSeen', JSON.stringify(m)); } catch (e) {} }
function dormSyncSeenBaseline() {
  if (!dormData || !dormData.rooms) return;
  let m = dormSeenMap();
  if (!m) { m = {}; Object.entries(dormData.rooms).forEach(([n, r]) => { m[n] = r.activity || 0; }); dormSeenSave(m); }
}
function dormIsNew(name) {
  const r = dormData && dormData.rooms && dormData.rooms[name], m = dormSeenMap() || {};
  return !!(r && r.activity && r.activity > (m[name] || 0) + 0.5);
}
function dormMarkSeen(name, activity) { const m = dormSeenMap() || {}; m[name] = Math.max(m[name] || 0, activity || 0); dormSeenSave(m); }
function dormMe() { return myLoggedInName(); }
function dormAsset(id) { return (dormData && dormData.assets || []).find(a => a.id === id) || null; }
function dormHallOf(name) { return (dormData && dormData.halls || []).find(h => (h.slots || []).includes(name)) || null; }
function dormCanEdit(owner) { return dormIsGm() || (dormMe() && dormMe() === owner); }
function dormBase(r) { return dormAsset(r && r.base) || dormAsset(dormData.default_base); }
// 크기 : 자료마다 기본 배율(a.s)이 있고, 놓은 소품은 각자 배율(it.z)을 가질 수 있어요.
function dormZ(it, a) { return (it && it.z) || (a && a.s) || 1; }
function dormBW(b) { return b.w * (b.s || 1); }
function dormBH(b) { return b.h * (b.s || 1); }

// 기숙사는 팝업이 아니라 전투 화면과 나란한 '페이지'예요. 사이드바 집 / 지구본 아이콘으로 오갑니다.
function setMainView(dorm) {
  if (typeof closeBattleHub === 'function') closeBattleHub();
  document.body.classList.toggle('view-dorm', dorm);
  document.getElementById('sidebarDormBtn').classList.toggle('active', dorm);
  if (!dorm) ['sidebarMyDormBtn', 'sidebarDormManageBtn'].forEach(id => { const b = document.getElementById(id); if (b) b.classList.remove('active'); });
  document.getElementById('sidebarBattleBtn').classList.toggle('active', !dorm && !document.body.classList.contains('view-ops'));
  if (!dorm && typeof drawAttackLines === 'function') setTimeout(() => { window.dispatchEvent(new Event('resize')); }, 30);
}
// 메뉴 마이룸 묶음 : 전체 관 · 내 방 · (운영진) 마이룸 관리
function openDormView(v) {
  if (!IS_LOUNGE) { goLounge(v === 'mine' ? 'mydorm' : v === 'manage' ? 'dormmanage' : 'dorm'); return; }
  closeWorldMap(true); closeOps();
  const go = () => {
    if (v === 'mine') {
      const me = dormMe();
      if (!me) { uiToast('로그인한 뒤에 볼 수 있어요.'); return; }
      if (dormData && !dormHallOf(me)) { uiToast('아직 방이 배정되지 않았어요.'); if (dormView === 'room') setDormView('halls'); return; }
      openDormRoom(me);
    } else if (v === 'manage') { if (dormIsGm()) setDormView('manage'); }
    else if (dormView !== 'halls') setDormView('halls');
  };
  if (dormEdit && !(v === 'mine' && dormRoom && dormRoom.owner === dormMe())) {
    uiConfirm('저장하지 않은 꾸미기가 있어요. 나갈까요?', { title: '방 나가기', okText: '나가기' }).then(ok => { if (ok) { dormEdit = null; openDorm(); go(); } });
    return;
  }
  openDorm(); go();
}
// 지금 보는 마이룸 화면에 맞춰 메뉴의 켜진 표시를 옮겨요
function syncDormMenu() {
  const on = document.body.classList.contains('view-dorm');
  const mine = on && dormView === 'room' && dormRoom && !dormRoom.past && !dormRoom.isDefault && dormRoom.owner === dormMe();
  const manage = on && (dormView === 'manage' || (dormView === 'room' && dormRoom && dormRoom.isDefault));
  const set = (id, v) => { const b = document.getElementById(id); if (b && b.classList.contains('active') !== v) b.classList.toggle('active', v); };
  set('sidebarDormBtn', on && !mine && !manage); set('sidebarMyDormBtn', !!mine); set('sidebarDormManageBtn', !!manage);
  const P = dormData && dormP();
  const lb = document.getElementById('sidebarDormLabel'); if (lb && P && P.unit) lb.textContent = '전체 ' + P.unit;
}
function openDorm() {
  document.getElementById('dormModal').style.display = 'flex';
  setMainView(true);
  socket.emit('dorm_get');
  if (dormView === 'manage' && !dormIsGm()) dormView = 'halls';
  renderDorm();
}
function closeDorm() {
  if (dormEdit) { uiConfirm('저장하지 않은 꾸미기가 있어요. 닫을까요?', { title: '마이룸 닫기', okText: '닫기' }).then(ok => { if (ok) { dormEdit = null; closeDorm(); } }); return; }
  document.getElementById('dormModal').style.display = 'none';
  setMainView(false);
  syncDormMusic();
}
function setDormView(v) { dormView = v; if (v === 'manage') { dormHallsDraft = null; dormCreditsDraft = null; } renderDorm(); }
function openDormRoom(owner) { dormGbEditing = false; dormZoom = 1; dormPan = { x: 0, y: 0 }; dormView = 'room'; dormRoom = { owner, loading: true }; dormEdit = null; dormSel = -1; socket.emit('dorm_room_get', { name: owner }); renderDorm(); }
socket.on('dorm_data', (d) => {
  // 기간이 바뀌면 지난 마이룸 목록 · 관리 초안을 새로 받습니다.
  if (dormData && dormData.period && d.period && dormData.period.id !== d.period.id) {
    dormPast = { owner: null, rooms: [] }; dormHallsDraft = null; dormManagePeriod = null;
    if (dormRoom && !dormRoom.past && dormView === 'room') dormView = 'halls';
  }
  // 운영진 관리 정보는 운영진 요청에만 오므로, 모두에게 가는 알림에 없으면 앞 값을 지킵니다.
  if (dormData && dormData.period_halls && !d.period_halls) d.period_halls = dormData.period_halls;
  if (dormData && dormData.period_defaults && !d.period_defaults) d.period_defaults = dormData.period_defaults;
  dormData = d; if (d.roster) dormRoster = d.roster;
  dormSyncSeenBaseline();
  if (document.getElementById('dormModal').style.display === 'flex' && !dormEdit) renderDorm();
  else if (dormEdit) renderDormPalette();  // 꾸미기 중 자료가 늘거나 줄면 아이템 목록만 새로
  renderMyPageRoom();
});
socket.on('joined', () => socket.emit('dorm_get'));
// 마이페이지(ID card)에 내 방 미리보기
function renderMyPageRoom() {
  const box = document.getElementById('myPageRoomBox');
  if (!box || document.getElementById('myPageModal').style.display !== 'flex') return;
  const c = myPageTargetChar(), name = c && c.name;
  renderMyPageLine(c); renderMyPageNation(c);
  const hall = name && dormData ? dormHallOf(name) : null;
  // 지난 기간의 마이룸 : 본인 마이페이지에서만(서버도 본인 것만 보내 줍니다)
  const self = !!(name && name === dormMe() && !dormIsGm());
  if (self && dormPast.owner !== name) { dormPast = { owner: name, rooms: [], loading: true }; socket.emit('dorm_past_get'); }
  const past = self && dormPast.owner === name ? (dormPast.rooms || []) : [];
  // 배정 전이어도 미리보기 자리는 늘 보여요(빈 방 안내).
  box.style.display = '';
  const P = dormP ? dormP() : { no: '', name: '' };
  document.getElementById('myPageRoomSub').textContent = hall ? `${P.no}차 ${P.name} · ${hall.name}` : '아직 배정되지 않았어요';
  const prev = document.getElementById('myPageRoomPrev');
  prev.style.display = '';
  prev.classList.toggle('empty', !hall);
  if (hall) {
    prev.innerHTML = dormMiniHtml(name, 160, 130);
    prev.onclick = () => { document.getElementById('myPageModal').style.display = 'none'; openDorm(); openDormRoom(name); };
    prev.dataset.tip = '눌러서 방으로 가기';
  } else {
    prev.innerHTML = '<div class="idc-room-empty"><i class="fa-solid fa-door-closed"></i><span>마이룸이 배정되면 여기에서 미리 볼 수 있어요.</span></div>';
    prev.onclick = null; delete prev.dataset.tip;
  }
  const pastEl = document.getElementById('myPageRoomPast');
  pastEl.innerHTML = past.length ? `<div class="idc-past-h">지난 마이룸</div>` + past.map((e, i) =>
    `<button class="idc-past" onclick="openDormPastRoom(${i})"><span class="mini">${dormMiniRoomHtml(e.room, 56, 44)}</span>
      <span class="t"><b>${e.period.no}차 ${mailEsc(e.period.name)}</b><span>${mailEsc(e.hall || '')}</span></span><i class="fa-solid fa-chevron-right"></i></button>`).join('') : '';
}
socket.on('dorm_past', (d) => { dormPast = { owner: d.owner, rooms: d.rooms || [] }; renderMyPageRoom(); if (dormEdit) renderDormEditBar(); });
// 지난 기간 방 미리보기(방 자료를 직접 받아 그림)
function dormMiniRoomHtml(r, w, maxH) {
  if (!dormData || !r) return '';
  const base = dormBase(r); if (!base) return '';
  const sc = Math.min(w / dormBW(base), (maxH || 1e9) / dormBH(base));
  return `<div class="dorm-mini" style="width:${Math.round(dormBW(base) * sc)}px; height:${Math.round(dormBH(base) * sc)}px">${dormStageHtml(r, base, sc, false, true)}</div>`;
}
// 지난 기간의 내 방 열기 : 구경만(꾸미기 · 방명록 쓰기 없음)
function openDormPastRoom(i) {
  const e = (dormPast.rooms || [])[i]; if (!e) return;
  document.getElementById('myPageModal').style.display = 'none';
  openDorm();
  dormZoom = 1; dormPan = { x: 0, y: 0 }; dormView = 'room'; dormEdit = null; dormSel = -1;
  dormRoom = Object.assign({}, e.room, { past: e.period, pastHall: e.hall });
  renderDorm();
}
socket.on('dorm_room', (r) => {
  if (!dormRoom || dormRoom.owner !== r.owner || dormRoom.past) return;
  dormMarkSeen(r.owner, r.activity);  // 지금 보고 있는 방만 '봤음'으로
  if (dormEdit && !dormSaving) { dormRoom = r; return; }
  dormRoom = r; dormSaving = false; dormEdit = null; dormSel = -1; dormPick = null;
  if (document.getElementById('dormModal').style.display === 'flex') renderDorm();
});
socket.on('dorm_result', (d) => {
  showShopToast(d.message); if (!d.ok) dormSaving = false;
  // 기본 방 저장이 끝나면 관리 화면으로 돌아갑니다.
  if (d.default_saved && dormRoom && dormRoom.isDefault) { dormSaving = false; dormEdit = null; setDormView('manage'); return; }
  // 방금 올린 자료는 바로 놓을 수 있게 골라 둡니다.
  if (d.asset_id && dormEdit) { dormCat = 'mine'; dormPick = d.asset_id; dormSel = -1; setTimeout(() => { renderDormPalette(); dormUpdateGhost(); }, 0); }
});

function renderDorm() {
  const box = document.querySelector('#dormModal .dorm-modal');
  box.classList.toggle('is-gm', dormIsGm());
  box.dataset.view = dormView;
  renderDormTop();
  const body = document.getElementById('dormBody');
  if (!dormData) { body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '마이룸을 불러오는 중이에요'); return; }
  if (dormView === 'manage' && dormIsGm()) { body.innerHTML = dormManageHtml(); return; }
  if (dormView === 'room' && dormRoom) { renderDormRoom(body); syncDormMusic(); return; }
  body.innerHTML = dormHallsHtml();
  syncDormMusic();
}
// ---------- 방 음악 : 그 방에 있는 동안만 반복 재생 (음량은 배경음악 음량을 따라요) ----------
var dormAudio = null, dormMusicActive = false, dormMusicUrl = null, dormMusicPaused = false, dormAutoBlocked = false;
function syncDormMusic() {
  const shown = document.getElementById('dormModal').style.display === 'flex';
  const want = shown && dormView === 'room' && dormRoom && !dormRoom.loading && dormRoom.music ? dormRoom.music.url : null;
  if (want !== dormMusicUrl) {
    if (dormAudio) { dormAudio.pause(); dormAudio = null; }
    dormMusicUrl = want; dormMusicPaused = false;
    if (want) { dormAudio = new Audio(want); dormAudio.loop = true; dormAudio.volume = musicVolume / 100; dormAudio.play().catch(() => { dormMusicPaused = true; dormAutoBlocked = true; renderDormMusicBtn(); }); }
  }
  dormMusicActive = !!(dormAudio && !dormMusicPaused);
  applyVolume();
  renderDormMusicBtn();
}
function toggleDormMusic() {
  if (!dormAudio) return;
  dormMusicPaused = !dormMusicPaused;
  if (dormMusicPaused) dormAudio.pause(); else dormAudio.play().catch(() => {});
  dormMusicActive = !dormMusicPaused; applyVolume(); renderDormMusicBtn();
}
function renderDormMusicBtn() {
  const b = document.getElementById('dormMusicBtn');
  if (b) b.innerHTML = `<i class="fa-solid ${dormMusicPaused || !dormAudio ? 'fa-play' : 'fa-pause'}"></i>`;
  const eq = document.getElementById('dormMusicEq'); if (eq) eq.classList.toggle('playing', !!(dormAudio && !dormMusicPaused));
}
function pickDormMusic() { document.getElementById('dormMusicFile').click(); }
function onDormMusicFile(ev) {
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_AUDIO_BYTES) { showShopToast(`음악 파일이 너무 커요 (최대 ${UPLOAD_AUDIO_MB}MB).`); return; }
  showShopToast('음악을 올리는 중…');
  f.arrayBuffer().then(buf => socket.emit('dorm_music_upload', { owner: dormRoom.owner, filename: f.name, data: buf }));
}
function clearDormMusic() {
  uiConfirm('방 음악을 지울까요?', { title: '방 음악 지우기', okText: '지우기', danger: true }).then(ok => ok && socket.emit('dorm_music_clear', { owner: dormRoom.owner }));
}
// 상단 바 : 전투 화면 헤더와 같은 모양 (Dorm ▶ 관 ▶ 방) + 오른쪽 버튼
function renderDormTop() {
  const el = document.getElementById('dormTop'); if (!el) return;
  const me = dormMe(), mine = me && dormData && dormHallOf(me);
  const P = dormP();
  const segs = [`<div class="seg dorm-brand">${mailEsc(P.en)}</div>`];
  let right = '';
  if (dormView === 'room' && dormRoom && dormRoom.past) {
    // 지난 기간의 내 방 : 구경만(꾸미기 · 방명록 쓰기 없음)
    const pp = dormRoom.past;
    segs[0] = `<div class="seg dorm-brand">${mailEsc(pp.en)}</div>`;
    segs.push(`<span class="sep mid">▶</span><div class="seg mid">${pp.no}차 ${mailEsc(pp.name)}${dormRoom.pastHall ? ' · ' + mailEsc(dormRoom.pastHall) : ''}</div>`);
    segs.push(`<span class="sep">▶</span><div class="seg">${mailEsc(dormRoom.owner)}</div>`);
    right = `<span class="dorm-past-tag"><i class="fa-solid fa-clock-rotate-left"></i>지난 마이룸</span>`;
  } else if (dormView === 'room' && dormRoom && dormRoom.isDefault) {
    // 운영진 : 기간 기본 방 꾸미기(아직 꾸미지 않은 방들이 이 모양으로 보여요)
    const dp = (dormData.periods || []).find(p => p.id === dormRoom.isDefault) || P;
    segs[0] = `<div class="seg dorm-brand">${mailEsc(dp.en)}</div>`;
    segs.push(`<span class="sep mid">▶</span><div class="seg dorm-link mid" onclick="dormLeaveRoom()">관리</div>`);
    segs.push(`<span class="sep">▶</span><div class="seg">${dp.no}차 ${mailEsc(dp.name)} 기본 방</div>`);
    right = `<button class="dorm-tbtn" onclick="dormLeaveRoom()" data-tip="취소"><i class="fa-solid fa-xmark"></i><span class="t">취소</span></button>
      <button class="dorm-tbtn primary" onclick="saveDormRoom()" data-tip="저장"><i class="fa-solid fa-floppy-disk"></i><span class="t">저장</span></button>`;
  } else if (dormView === 'room' && dormRoom) {
    const hall = dormData && dormHallOf(dormRoom.owner);
    segs.push(`<span class="sep mid">▶</span><div class="seg dorm-link mid" onclick="dormLeaveRoom()">${hall ? mailEsc(hall.name) : mailEsc(P.name)}</div>`);
    segs.push(`<span class="sep">▶</span><div class="seg">${mailEsc(dormRoom.owner)}</div>`);
    const can = dormCanEdit(dormRoom.owner) && hall && !dormRoom.loading;
    if (dormEdit) right = `<button class="dorm-tbtn" onclick="dormEdit=null; dormSel=-1; dormPick=null; renderDorm()" data-tip="취소"><i class="fa-solid fa-xmark"></i><span class="t">취소</span></button>
      <button class="dorm-tbtn primary" onclick="saveDormRoom()" data-tip="저장"><i class="fa-solid fa-floppy-disk"></i><span class="t">저장</span></button>`;
    else if (can) right = `<button class="dorm-tbtn primary" onclick="startDormEdit()" data-tip="꾸미기"><i class="fa-solid fa-paintbrush"></i><span class="t">꾸미기</span></button>`;
  } else if (dormView === 'manage') {
    segs.push('<span class="sep">▶</span><div class="seg">관리</div>');
  } else if (dormData) {
    segs.push(`<span class="sep mid">▶</span><div class="seg mid">${P.no}차 ${mailEsc(P.name)} · ${mailEsc(P.unit)} ${(dormData.halls || []).length}개</div>`);
    if (mine) right = `<button class="dorm-tbtn primary" onclick="openDormRoom(${mailEsc(JSON.stringify(me))})" data-tip="내 방"><i class="fa-solid fa-door-open"></i><span class="t">내 방</span></button>`;
  }
  // 방 안에서는 출처 버튼 없이 꾸미기(취소 · 저장) 버튼만 둡니다. 출처는 목록 화면에서 볼 수 있어요.
  // 마이룸 관리는 메뉴(마이룸 묶음)에서 열어요.
  const tools = dormView === 'room' ? '' : `<button class="dorm-tbtn icon" onclick="openDormCredits()" data-tip="도트 자료 출처"><i class="fa-solid fa-circle-info"></i></button>`;
  syncDormMenu();
  el.innerHTML = segs.join('') + `<div class="spacer"></div><div class="dorm-tools-r">${right}${tools}</div>`;
}

function dormHallsHtml() {
  const me = dormMe(), P = dormP();
  const halls = dormData.halls || [];
  if (!halls.length) return emptyHtml('fa-building', `아직 ${mailEsc(josa(P.name, '이', '가'))} 없어요`, `운영진이 ${mailEsc(josa(P.unit, '을', '를'))} 만들고 방을 배정하면 여기에 보여요.`);
  return '<div class="dorm-halls">' + halls.map((h, hi) => {
    const n = (h.slots || []).filter(Boolean).length;
    const canRename = dormIsGm() || (me && (h.slots || []).includes(me));
    return `<section class="dorm-hall"><h2 class="dorm-hall-title"><span class="en">${mailEsc(P.unit_en)} ${hi + 1}</span><span class="ko">${mailEsc(h.name)}</span>
      ${canRename ? `<button class="dorm-rename" onclick="renameDormHall('${h.id}')" data-tip="${mailEsc(P.unit)} 이름 바꾸기"><i class="fa-solid fa-pen"></i></button>` : ''}
      <span class="cnt">${n} / ${dormData.hall_size}</span></h2>
    <div class="dorm-cards holo-zone">${(h.slots || []).map((nm, i) => nm
      ? `<div class="char-card dorm-card ${nm === me ? 'mine' : ''}" onclick="openDormRoom(${mailEsc(JSON.stringify(nm))})">${nm === me ? '<span class="tgt-line" aria-hidden="true"></span>' : ''}
          <div class="row1"><span class="cname">${mailEsc(nm)}</span>${dormIsNew(nm) ? '<span class="dorm-new">NEW</span>' : ''}</div>
          <div class="dorm-portrait">${dormMiniHtml(nm, 150, 112)}</div></div>`
      : `<div class="char-card dorm-card empty"><div class="row1"><span class="cname">빈 방</span></div>
          <div class="dorm-portrait"><i class="fa-solid fa-door-closed"></i></div></div>`).join('')}</div></section>`;
  }).join('') + '</div>';
}

// ---------- 방 ----------
function dormScale(frame, base) {
  const cs = getComputedStyle(frame);
  const aw = Math.max(160, frame.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
  const ah = Math.max(160, frame.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom));
  const s = Math.min(aw / dormBW(base), ah / dormBH(base));
  return s >= 1 ? Math.max(1, Math.floor(s * 4) / 4) : s;
}
function renderDormRoom(body) {
  const r = dormRoom;
  if (r.loading) { body.innerHTML = emptyHtml('fa-circle-notch fa-spin', '방을 불러오는 중이에요'); return; }
  // 방명록을 쓰는 중(입력칸에 커서)이면 입력칸은 그대로 두고 나머지만 새로 그립니다.
  // 모바일은 키보드가 올라오면 화면 크기가 바뀌어 다시 그리게 되는데, 입력칸까지 새로 만들면 키보드가 바로 닫혀요.
  const gb = document.getElementById('dormGbText'), gbSide = body.querySelector('.dorm-side');
  if (!dormEdit && gb && document.activeElement === gb && gbSide && body.contains(gb)) {
    const tmp = document.createElement('div'); tmp.innerHTML = dormGuestbookHtml(r);
    ['.dorm-roominfo', '.dorm-gb-list'].forEach(sel => {
      const o = gbSide.querySelector(sel), n = tmp.querySelector(sel);
      if (o && n && !(o.contains(gb) && dormGbEditing)) o.replaceWith(n);
    });
    dormRenderStage();
    return;
  }
  const side = dormEdit
    ? `<div class="member-panel panel dorm-side dorm-items"><div class="member-header"><b>Items</b><span class="dorm-gb-cnt" id="dormItemCnt"></span></div>
        <div class="member-toptabs dorm-cattabs" id="dormCatTabs"></div><div class="dorm-pfilter" id="dormFilter"></div>
        <div class="dorm-side-body" id="dormPalette"></div><div class="dorm-palette-foot" id="dormHint"></div></div>`
    : dormGuestbookHtml(r);
  const isOwner = dormMe() && dormMe() === r.owner;
  const bubble = r.line ? `<div class="dorm-line-bubble"><b>${mailEsc(r.owner)}</b><span>${mailEsc(r.line)}</span></div>` : '';
  body.innerHTML = `<div class="dorm-room-layout"><div class="dorm-frame-wrap">${dormEdit ? '' : bubble}<div class="map-frame dorm-frame ${dormEdit ? 'editing' : ''}" id="dormStageBox"></div>
    <button class="dorm-back" onclick="dormLeaveRoom()" aria-label="목록으로" data-tip="${mailEsc(dormP().name)} 목록으로"><i class="fa-solid fa-chevron-left"></i></button>
    <div class="zoom-ctl" id="dormZoom">
      <button onclick="dormZoomBy(1 / 1.25)" data-tip="축소"><i class="fa-solid fa-magnifying-glass-minus"></i></button>
      <span class="z" id="dormZoomLabel">100%</span>
      <button onclick="dormZoomBy(1.25)" data-tip="확대"><i class="fa-solid fa-magnifying-glass-plus"></i></button>
      <button class="fit" onclick="dormZoomReset()" data-tip="원래대로 맞춤"><i class="fa-solid fa-expand"></i></button>
    </div>${dormEdit ? '<div class="dorm-edit-bar" id="dormEditBar"></div>' : ''}</div>${side}</div>`;
  dormRenderStage();
  if (dormEdit) renderDormPalette();
}
// ---------- 방 확대/축소 · 이동 : 배율은 화면에만 적용(저장 안 함). 맞춤(100%)은 방이 칸에 꼭 맞는 크기 ----------
let dormZoom = 1, dormPan = { x: 0, y: 0 };
const DORM_ZOOM_MIN = 0.6, DORM_ZOOM_MAX = 4;
function dormRenderStage() {
  const frame = document.getElementById('dormStageBox'); if (!frame || !dormRoom) return;
  const src = dormEdit || dormRoom, base = dormBase(src);
  const fit = dormScale(frame, base);
  let s = fit * dormZoom;
  if (s >= 1) s = Math.round(s * 4) / 4;  // 도트가 뭉개지지 않게 0.25 단위로
  frame.innerHTML = dormStageHtml(src, base, s, !!dormEdit);
  dormClampPan(frame);
  dormApplyPan();
  const lb = document.getElementById('dormZoomLabel'); if (lb) lb.textContent = Math.round(dormZoom * 100) + '%';
  if (dormEdit) bindDormStage(s);
  else { bindDormSpeak(); bindDormHold(s); }
  bindDormPan(frame);
}
// 방에 놓인 캐릭터(SD)는 등록한 대사를 몇 초마다 저절로 말하고, 누르면 바로 한마디 합니다.
let dormSpeakTimer = null;
function dormSay(el) {
  const st = document.getElementById('dormStage'); if (!st || !el || !dormRoom) return false;
  const it = (dormRoom.items || [])[+el.dataset.i], a = it && dormAsset(it.a);
  const lines = (a && a.lines || []).filter(Boolean);
  if (!lines.length) return false;
  let pick = lines[Math.floor(Math.random() * lines.length)];
  if (lines.length > 1 && pick === el._lastLine) pick = lines[(lines.indexOf(pick) + 1) % lines.length];
  el._lastLine = pick;
  if (el._say) el._say.remove();
  const say = document.createElement('div');
  say.className = 'dorm-say'; say.textContent = pick;
  say.style.left = (el.offsetLeft + el.offsetWidth / 2) + 'px'; say.style.top = el.offsetTop + 'px';
  st.appendChild(say); el._say = say;
  setTimeout(() => { say.remove(); if (el._say === say) el._say = null; }, 3800);
  return true;
}
// 캐릭터 SD 꾹 눌러 들기 : 0.35초 누르고 있으면 살짝 들려 올라가고(진동 없음), 원래 자리 근처(반지름 DORM_HOLD_R 방 픽셀)
// 안에서만 끌 수 있어요. 손을 떼면 통통 튀며 내려앉습니다. 방 주인의 배치는 바뀌지 않고, 이 화면에서만 기억해요.
const DORM_HOLD_R = 40, DORM_HOLD_MS = 350;
const dormNudge = {};  // '주인:소품번호' -> [x, y] (방 픽셀)
function dormNudgeKey(el) { return `${dormRoom ? dormRoom.owner : ''}:${el.dataset.i}`; }
function dormSetNudge(el, x, y, s) { el.style.translate = `${x * s}px ${y * s}px`; }
function bindDormHold(s) {
  const st = document.getElementById('dormStage'); if (!st) return;
  st.querySelectorAll('.dorm-item.chara').forEach(el => { const n = dormNudge[dormNudgeKey(el)]; if (n) dormSetNudge(el, n[0], n[1], s); });
  let hold = null;
  const release = (e) => {
    if (!hold) return;
    const h = hold; hold = null;
    clearTimeout(h.timer);
    h.el.classList.remove('pressing');
    if (!h.lifted) return;
    h.el._justHeld = true;
    h.el.classList.remove('held');
    h.el.classList.remove('landing'); void h.el.offsetWidth; h.el.classList.add('landing');
    setTimeout(() => h.el.classList.remove('landing'), 520);
    if (e && e.pointerId != null && h.el.hasPointerCapture && h.el.hasPointerCapture(e.pointerId)) h.el.releasePointerCapture(e.pointerId);
  };
  st.addEventListener('pointerdown', (e) => {
    const el = e.target.closest('.dorm-item.chara'); if (!el || dormEdit) return;
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    const n = dormNudge[dormNudgeKey(el)] || [0, 0];
    hold = { el, id: e.pointerId, x: e.clientX, y: e.clientY, nx: n[0], ny: n[1], lifted: false };
    el.classList.add('pressing');
    hold.timer = setTimeout(() => {
      if (!hold || hold.el !== el) return;
      hold.lifted = true;
      el.classList.remove('pressing'); el.classList.add('held');
      try { el.setPointerCapture(hold.id); } catch (_) {}
      if (el._say) { el._say.remove(); el._say = null; }
    }, DORM_HOLD_MS);
  });
  st.addEventListener('pointermove', (e) => {
    if (!hold || e.pointerId !== hold.id) return;
    if (!hold.lifted) {
      // 들기 전에 손가락이 움직이면 '꾹 누르기'를 취소합니다.
      if (Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 6) { clearTimeout(hold.timer); hold.el.classList.remove('pressing'); hold = null; }
      return;
    }
    e.preventDefault();
    let x = hold.nx + (e.clientX - hold.x) / s, y = hold.ny + (e.clientY - hold.y) / s;
    const d = Math.hypot(x, y);
    if (d > DORM_HOLD_R) { x *= DORM_HOLD_R / d; y *= DORM_HOLD_R / d; }
    dormNudge[dormNudgeKey(hold.el)] = [x, y];
    dormSetNudge(hold.el, x, y, s);
  });
  st.addEventListener('pointerup', release);
  st.addEventListener('pointercancel', release);
  st.addEventListener('contextmenu', (e) => { if (e.target.closest('.dorm-item.chara')) e.preventDefault(); });
}
function bindDormSpeak() {
  const st = document.getElementById('dormStage'); if (!st) return;
  st.addEventListener('click', (e) => {
    const el = e.target.closest('.dorm-item.chara'); if (!el) return;
    if (el._justHeld) { el._justHeld = false; return; }  // 들었다 놓은 직후의 클릭은 대사 없이
    dormSay(el);
  });
  clearTimeout(dormSpeakTimer);
  const talkers = () => [...st.querySelectorAll('.dorm-item.chara')].filter(el => {
    const it = (dormRoom.items || [])[+el.dataset.i], a = it && dormAsset(it.a); return a && (a.lines || []).length; });
  if (!talkers().length) return;
  const tick = (first) => {
    dormSpeakTimer = setTimeout(() => {
      if (!document.body.contains(st) || dormEdit) return;
      const list = talkers().filter(el => !el._say);
      if (list.length) dormSay(list[Math.floor(Math.random() * list.length)]);
      tick(false);
    }, first ? 900 : 4200 + Math.random() * 3000);
  };
  tick(true);
}
function dormApplyPan() { const st = document.getElementById('dormStage'); if (st) st.style.transform = `translate(${dormPan.x}px, ${dormPan.y}px)`; }
function dormClampPan(frame) {
  const st = document.getElementById('dormStage'); if (!st || !frame) return;
  // 방이 칸보다 크면 가장자리까지만, 작으면 가운데 근처에서만 움직이게
  const mx = Math.max(40, (st.offsetWidth - frame.clientWidth) / 2 + 40), my = Math.max(40, (st.offsetHeight - frame.clientHeight) / 2 + 40);
  dormPan.x = Math.max(-mx, Math.min(mx, dormPan.x)); dormPan.y = Math.max(-my, Math.min(my, dormPan.y));
}
function dormZoomBy(f) {
  const z = Math.max(DORM_ZOOM_MIN, Math.min(DORM_ZOOM_MAX, dormZoom * f));
  if (Math.abs(z - 1) < 0.04) { dormZoomReset(); return; }
  const r = z / dormZoom; dormPan.x *= r; dormPan.y *= r; dormZoom = z;
  dormRenderStage();
}
function dormZoomReset() { dormZoom = 1; dormPan = { x: 0, y: 0 }; dormRenderStage(); }
function bindDormPan(frame) {
  if (frame._panBound) return; frame._panBound = true;
  let pan = null;
  frame.addEventListener('pointerdown', (e) => {
    // 꾸미기 중에는 소품을 잡거나 놓을 때는 이동하지 않습니다(빈 곳을 끌 때만).
    if (dormEdit && (dormPick || e.target.closest('.dorm-item'))) return;
    // 구경 중 캐릭터 SD를 누르면 '꾹 눌러 들기'가 먼저라서 방은 움직이지 않습니다.
    if (!dormEdit && e.target.closest('.dorm-item.chara')) return;
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    pan = { x: e.clientX, y: e.clientY, px: dormPan.x, py: dormPan.y, id: e.pointerId, on: false };
  });
  frame.addEventListener('pointermove', (e) => {
    if (!pan || e.pointerId !== pan.id) return;
    if (!pan.on) {
      if (Math.hypot(e.clientX - pan.x, e.clientY - pan.y) < 5) return;
      pan.on = true; frame.setPointerCapture(e.pointerId); frame.classList.add('panning');
    }
    dormPan.x = pan.px + e.clientX - pan.x; dormPan.y = pan.py + e.clientY - pan.y;
    dormClampPan(frame); dormApplyPan();
  });
  const end = () => { pan = null; frame.classList.remove('panning'); };
  frame.addEventListener('pointerup', end); frame.addEventListener('pointercancel', end);
  frame.addEventListener('wheel', (e) => { e.preventDefault(); dormZoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12); }, { passive: false });
}

function renameDormHall(id) {
  const h = (dormData.halls || []).find(x => x.id === id); if (!h) return;
  uiPrompt(`새 ${dormP().unit} 이름을 적어 주세요. (30자까지)`, h.name, { title: `${dormP().unit} 이름 바꾸기`, okText: '바꾸기' }).then(v => {
    if (v == null) return; v = String(v).trim();
    if (v && v !== h.name) socket.emit('dorm_hall_rename', { id, name: v });
  });
}
// ---------- 방명록 (한 방에 한 사람당 한 개, 다시 쓰면 고쳐져요) ----------
let dormGbDraft = {};
function dormGuestbookHtml(r) {
  // 지난 기간의 방은 구경만 : 방명록 쓰기 · 지우기 · 음악/대사 바꾸기를 숨깁니다.
  const me = r.past ? null : dormLoggedName(), list = r.guestbook || [], mine = me && list.find(e => e.author === me);
  const draft = dormGbDraft[r.owner] != null ? dormGbDraft[r.owner] : (mine ? mine.text : '');
  const canDel = (e) => !r.past && (dormIsGm() || me === e.author || me === r.owner);
  const fmt = (at) => mailRealTime(at);  // 실제 날짜 · 시간(26.10.15 PM 3:12)
  const color = (name) => { const p = (typeof lastRosterMypage !== 'undefined' && lastRosterMypage[name]) || {}; return p.color || '#6b6b73'; };
  const isOwner = !r.past && dormMe() && dormMe() === r.owner;
  const music = r.music;
  const info = (music || isOwner) ? `<div class="dorm-roominfo">
      <div class="dorm-music">
        <div class="bgm-eq" id="dormMusicEq"><span></span><span></span><span></span><span></span></div>
        <div class="t">${music ? mailEsc(music.title) : '<span class="muted">방 음악이 없어요</span>'}</div>
        ${music ? `<button class="dorm-ibtn" id="dormMusicBtn" onclick="toggleDormMusic()"><i class="fa-solid fa-pause"></i></button>` : ''}
        ${isOwner ? `<button class="dorm-ibtn" onclick="pickDormMusic()" data-tip="${music ? '음악 바꾸기' : '음악 올리기'} (mp3·ogg·wav·m4a, ${UPLOAD_AUDIO_MB}MB)"><i class="fa-solid fa-upload"></i></button>
          ${music ? `<button class="dorm-ibtn" onclick="clearDormMusic()" data-tip="음악 지우기"><i class="fa-solid fa-xmark"></i></button>` : ''}
          <input type="file" id="dormMusicFile" accept=".mp3,.ogg,.wav,.m4a,audio/*" style="display:none" onchange="onDormMusicFile(event)">` : ''}
      </div>
    </div>` : '';
  return `<div class="member-panel panel dorm-side">
    <div class="member-header"><b>Guestbook</b></div>${info}
    ${me && !mine ? `<div class="dorm-gb-write"><textarea id="dormGbText" maxlength="300" rows="3" placeholder="방명록을 작성해 주세요."
        oninput="dormGbDraft['${mailEsc(r.owner)}']=this.value">${mailEsc(draft)}</textarea>
      <div class="row"><button class="dorm-tbtn primary sm" onclick="writeDormGuestbook()">남기기</button></div></div>`
      : ''}
    <div class="dorm-side-body dorm-gb-list">${list.length ? list.map((e, i) => {
      const own = e.author === me, editing = own && dormGbEditing;
      // 카드에 보이는 건 다섯 가지 : 캐릭터 이름 · 캐릭터 색 · 시간 · (내 글이면) 고치기 아이콘 · 번호. 지우기는 고치는 중이나 마우스를 올렸을 때만.
      const delBtn = canDel(e) ? `<button class="dorm-note-btn del" onclick="deleteDormGuestbook(${mailEsc(JSON.stringify(e.author))})" data-tip="지우기"><i class="fa-solid fa-trash-can"></i></button>` : '';
      return `<article class="dorm-note ${own ? 'mine' : ''} ${editing ? 'editing' : ''}" style="--nc:${color(e.author)}">
        <div class="gn-h"><b>${mailEsc(e.author)}</b><span class="no">No.${String(list.length - i).padStart(2, '0')}</span></div>
        ${editing ? `<textarea id="dormGbText" maxlength="300" rows="3" oninput="dormGbDraft['${mailEsc(r.owner)}']=this.value">${mailEsc(draft)}</textarea>
          <div class="gn-edit">${delBtn}<span class="sp"></span><button class="gn-btn" onclick="dormGbEdit(false)">취소</button><button class="gn-btn on" onclick="writeDormGuestbook()">저장</button></div>`
          : `<p>${mailEsc(e.text)}</p>
        <div class="gn-f"><span class="t">${fmt(e.at)}</span>${own ? '' : delBtn}${own ? `<button class="dorm-note-btn" onclick="dormGbEdit(true)" data-tip="고치기"><i class="fa-solid fa-pen"></i></button>` : ''}</div>`}</article>`; }).join('')
      : emptyHtml('fa-feather-pointed', '아직 방명록이 없어요', me ? '첫 방명록을 남겨 보세요.' : '', null, true)}</div>
  </div>`;
}

function dormLoggedName() { return dormIsGm() ? '운영진' : dormMe(); }
// 내 방명록 고치기 : 내 글 옆 연필 아이콘을 누르면 그 자리에서 바로 고쳐요.
let dormGbEditing = false;
function dormGbEdit(on) {
  dormGbEditing = !!on;
  if (!on && dormRoom) delete dormGbDraft[dormRoom.owner];
  renderDorm();
  if (on) setTimeout(() => { const t = document.getElementById('dormGbText'); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } }, 0);
}
function writeDormGuestbook() {
  const el = document.getElementById('dormGbText'); const text = (el ? el.value : '').trim();
  if (!text) { showShopToast('방명록을 작성해 주세요.'); return; }
  delete dormGbDraft[dormRoom.owner];
  dormGbEditing = false;
  socket.emit('dorm_guestbook_write', { owner: dormRoom.owner, text });
}
function deleteDormGuestbook(author) {
  uiConfirm('이 방명록을 지울까요?', { title: '방명록 지우기', okText: '지우기', danger: true }).then(ok => {
    if (ok) { if (author === dormLoggedName()) delete dormGbDraft[dormRoom.owner]; socket.emit('dorm_guestbook_delete', { owner: dormRoom.owner, author }); }
  });
}
function dormLeaveRoom() {
  // 기본 방 꾸미기에서 나가면 관리 화면으로 돌아갑니다.
  const back = dormRoom && dormRoom.isDefault ? 'manage' : 'halls';
  if (!dormEdit) { setDormView(back); return; }
  uiConfirm('저장하지 않은 꾸미기가 있어요. 나갈까요?', { title: '방 나가기', okText: '나가기' }).then(ok => { if (ok) { dormEdit = null; setDormView(back); } });
}
// 운영진 : 기간 기본 방 꾸미기 열기(관리 화면의 '기본 방 꾸미기')
function openDormDefaultEdit(pid) {
  const d = (dormData.period_defaults && dormData.period_defaults[pid]) || { base: dormData.default_base, items: [] };
  dormZoom = 1; dormPan = { x: 0, y: 0 }; dormView = 'room'; dormSel = -1; dormPick = null;
  dormRoom = Object.assign({ owner: '', guestbook: [] }, JSON.parse(JSON.stringify(d)), { isDefault: pid });
  startDormEdit();
}
// 그리는 순서(뒤 → 앞) : 깔개(surface)가 맨 뒤, 그다음 겹침 순서(o, 앞/뒤로 보내기로 정함), 같으면 바닥 쪽(아래)일수록 앞
function dormDrawOrder(items) {
  return items.map((it, i) => ({ it, i, a: dormAsset(it.a) })).filter(o => o.a)
    .sort((p, q) => ((q.a.category === 'surface') - (p.a.category === 'surface')) || ((p.it.o || 0) - (q.it.o || 0))
      || (p.a.category === 'surface' ? p.i - q.i : (p.it.y + p.a.h * dormZ(p.it, p.a)) - (q.it.y + q.a.h * dormZ(q.it, q.a))))
    .map(o => o.i);
}
// 선택한 소품 겹침 순서 : top 최상단 · up 한 칸 앞 · down 한 칸 뒤 · bottom 최하단 (깔개끼리, 소품끼리 따로)
function dormLayerSel(kind) {
  if (!dormEdit || dormSel < 0) return;
  const items = dormEdit.items, sel = items[dormSel], sa = dormAsset(sel.a); if (!sa) return;
  const group = dormDrawOrder(items).filter(i => { const a = dormAsset(items[i].a); return a && (a.category === 'surface') === (sa.category === 'surface'); });
  const pos = group.indexOf(dormSel);
  if (kind === 'top' || kind === 'bottom') {
    const os = group.filter(i => i !== dormSel).map(i => items[i].o || 0);
    if (!os.length) return;
    sel.o = kind === 'top' ? Math.max(...os) + 1 : Math.min(...os) - 1;
  } else {
    const to = kind === 'up' ? pos + 1 : pos - 1;
    if (to < 0 || to >= group.length) { showShopToast(kind === 'up' ? '이미 맨 앞이에요.' : '이미 맨 뒤예요.'); return; }
    // 지금 보이는 순서를 그대로 번호로 고정한 뒤 이웃과 자리만 바꿉니다.
    group.forEach((i, k) => { items[i].o = k; });
    items[group[to]].o = pos; sel.o = to;
  }
  renderDorm();
}
function dormStageHtml(r, base, s, editing, mini) {
  const W = dormBW(base) * s, H = dormBH(base) * s;
  const items = dormDrawOrder(r.items || []).map(i => ({ it: r.items[i], i, a: dormAsset(r.items[i].a) }));
  const fit = base.fit || {}, fitted = [['wall', r.wall], ['floor', r.floor]].map(([k, id]) => {
    const a = dormAsset(id), f = fit[k]; if (!a || !f) return '';
    const sc = f[2] / a.w;
    return `<div class="dorm-surface" style="left:${f[0] * s}px; top:${f[1] * s}px; width:${f[2] * s}px; height:${a.h * sc * s}px; background-image:url('${a.url}');"></div>`;
  }).join('');
  return `<div class="dorm-stage ${editing ? 'editing' : ''} ${mini ? 'mini' : ''}" ${mini ? '' : 'id="dormStage"'} style="width:${W}px; height:${H}px; background:url('${base.url}') 0 0 / 100% 100% no-repeat;">${fitted}
    ${items.map(({ it, i, a }) => `<div class="dorm-item ${it.f ? 'dflip' : ''} ${a.smooth ? 'smooth' : ''} ${a.category === 'chara' ? 'chara' : ''} ${editing && i === dormSel ? 'sel' : ''}" data-i="${i}" ${a.category === 'chara' && !editing ? '' : `data-tip="${mailEsc(a.name)}"`}
      style="left:${it.x * s}px; top:${it.y * s}px; width:${a.w * dormZ(it, a) * s}px; height:${a.h * dormZ(it, a) * s}px; background-image:url('${a.url}');"></div>`).join('')}
    ${mini ? '' : '<div class="dorm-ghost" id="dormGhost"></div>'}</div>`;
}
// 작은 미리보기 (관 목록 문 카드·마이페이지) : 폭 w(px)에 맞춰 줄여 그립니다.
function dormMiniHtml(owner, w, maxH) {
  if (!dormData) return '';
  const r = (dormData.rooms && dormData.rooms[owner]) || { base: dormData.default_base, items: [] };
  const base = dormBase(r); if (!base) return '';
  const s = Math.min(w / dormBW(base), (maxH || 1e9) / dormBH(base));
  return `<div class="dorm-mini" style="width:${Math.round(dormBW(base) * s)}px; height:${Math.round(dormBH(base) * s)}px">${dormStageHtml(r, base, s, false, true)}</div>`;
}
// 지난 기간 내 방의 배치(바탕 · 벽지 · 바닥 · 소품)를 지금 꾸미기로 가져옵니다. 저장을 눌러야 실제로 바뀌어요.
function loadDormPastLayout(i) {
  const e = (dormPast.rooms || [])[i]; if (!e || !dormEdit) return;
  uiConfirm(`${e.period.no}차 ${e.period.name} 방 배치를 불러올까요? 지금 꾸미던 배치는 바뀌고, 저장을 눌러야 실제로 적용돼요.`,
    { title: '지난 마이룸 불러오기', okText: '불러오기' }).then(ok => {
    if (!ok) return;
    const r = e.room || {};
    dormEdit = { base: r.base || dormData.default_base, wall: r.wall || null, floor: r.floor || null, items: (r.items || []).map(it => Object.assign({}, it)) };
    dormSel = -1; dormPick = null; renderDorm();
    showShopToast(`${e.period.no}차 ${e.period.name} 배치를 불러왔어요. 고친 뒤 저장해 주세요.`);
  });
}
function startDormEdit() {
  const r = dormRoom;
  const me = dormMe();
  if (me && me === r.owner && !dormIsGm() && dormPast.owner !== me) { dormPast = { owner: me, rooms: [], loading: true }; socket.emit('dorm_past_get'); }
  dormEdit = { base: r.base || dormData.default_base, wall: r.wall || null, floor: r.floor || null, items: (r.items || []).map(i => Object.assign({}, i)) };
  dormSel = -1; dormPick = null; renderDorm();
}
function saveDormRoom() {
  if (!dormEdit) return;
  dormSaving = true;
  if (dormRoom && dormRoom.isDefault) { socket.emit('dorm_default_save', Object.assign({ period: dormRoom.isDefault }, dormEdit)); return; }
  socket.emit('dorm_room_save', Object.assign({ owner: dormRoom.owner }, dormEdit));
}
function dormAssetList() {
  // 참가자가 올린 자료(owner)는 '내 자료' 탭에서만 보입니다(본인 것만, 운영진은 전부). 캐릭터 SD도 '내 자료'에.
  const me = dormMe(), gm = dormIsGm();
  const all = (dormData.assets || []).filter(a => dormCat === 'mine'
    ? (a.owner ? (gm || a.owner === me) : a.category === 'chara')
    : (a.category === dormCat && !a.owner));
  const q = dormQ.trim().toLowerCase();
  return { all, list: all.filter(a => (!dormSet || (a.set || '내가 올린 자료') === dormSet) && (!q || a.name.toLowerCase().includes(q))) };
}
function renderDormPalette() {
  if (!document.getElementById('dormPalette')) return;
  const { all } = dormAssetList();
  const sets = [...new Set(all.map(a => a.set || '내가 올린 자료'))];
  if (dormSet && !sets.includes(dormSet)) dormSet = '';
  document.getElementById('dormCatTabs').innerHTML = [...DORM_CATS, ['mine', '내 자료']].map(([k, t]) =>
    `<button class="${dormCat === k ? 'active' : ''}" onclick="dormCat='${k}'; dormPick=null; dormSet=''; renderDormPalette(); dormUpdateGhost()"><span>${t}</span></button>`).join('');
  document.getElementById('dormFilter').innerHTML = `<select onchange="dormSet=this.value; renderDormGrid()"><option value="">전체 세트 · ${all.length}</option>${sets.map(t => `<option ${t === dormSet ? 'selected' : ''}>${mailEsc(t)}</option>`).join('')}</select>
    <div class="dorm-search"><i class="fa-solid fa-magnifying-glass"></i><input type="text" placeholder="이름 검색" value="${mailEsc(dormQ)}" oninput="dormQ=this.value; renderDormGrid()"></div>`;
  document.getElementById('dormHint').textContent = dormCat === 'mine' ? '직접 등록한 가구와 캐릭터 SD입니다. 캐릭터는 클릭 시 등록된 대사가 랜덤 출력됩니다.'
    : dormCat === 'room' ? '고르면 방 바탕이 바뀌어요.'
    : dormCat === 'surface' ? '벽지·바닥은 고르면 방에 딱 맞춰 깔려요. 다시 누르면 걷어내요.'
    : '고른 뒤 방을 눌러 놓아요.' + (window.matchMedia('(hover: none)').matches ? '' : ' Esc 고르기 취소');
  renderDormGrid();
}
// ---------- 아이템 추가 (참가자 : 가구 · 캐릭터 SD) ----------
// 그림은 원본 그대로 올리고, 큰 그림은 방에 처음 놓일 때 가구 220px · 캐릭터 160px 안에 들어오게 기본 배율만 정합니다.
const DORM_ADD_BOX = { furniture: 220, chara: 160 };
let dormAdd = null;
function openDormAddModal(editId) {
  if (!dormIsGm() && !dormMe()) return;
  const a = editId ? dormAsset(editId) : null;
  dormAdd = a ? { id: a.id, type: a.category === 'chara' ? 'chara' : 'furniture' } : { type: dormAdd && !dormAdd.id ? dormAdd.type : 'furniture' };
  document.getElementById('dormAddTitle').textContent = a ? 'Edit item' : 'Add item';
  document.getElementById('dormAddName').value = a ? a.name : '';
  document.getElementById('dormAddLines').value = a ? (a.lines || []).join('\n') : '';
  const pv = document.getElementById('dormAddPreview');
  pv.style.display = a ? '' : 'none'; if (a) pv.src = a.url;
  document.getElementById('dormAddEmpty').style.display = a ? 'none' : '';
  document.getElementById('dormAddDrop').classList.toggle('locked', !!a);
  document.getElementById('dormAddDel').style.display = a ? '' : 'none';
  document.getElementById('dormAddOk').textContent = a ? '저장' : '등록';
  dormAddSetType(dormAdd.type);
  document.getElementById('dormAddModal').style.display = 'flex';
}
function closeDormAddModal() { document.getElementById('dormAddModal').style.display = 'none'; if (dormAdd && dormAdd.url) URL.revokeObjectURL(dormAdd.url); dormAdd = null; }
function dormAddSetType(t) {
  if (!dormAdd || (dormAdd.id && dormAdd.type !== t)) return;
  dormAdd.type = t;
  document.querySelectorAll('#dormAddType button').forEach(b => { b.classList.toggle('on', b.dataset.v === t); b.disabled = !!dormAdd.id; });
  document.getElementById('dormAddLinesBox').style.display = t === 'chara' ? '' : 'none';
  // 캐릭터 SD는 이름이 필요 없습니다(목록에는 '캐릭터 SD'로 표시).
  document.getElementById('dormAddNameBox').style.display = t === 'chara' ? 'none' : '';
}
function onDormAddFile(ev) {
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (!f || !dormAdd || dormAdd.id) return;
  if (f.size > UPLOAD_IMG_BYTES) { showShopToast(`${UPLOAD_IMG_MB}MB 이하의 이미지만 등록할 수 있습니다.`); return; }
  if (dormAdd.url) URL.revokeObjectURL(dormAdd.url);
  dormAdd.url = URL.createObjectURL(f); dormAdd.file = f;
  if (!document.getElementById('dormAddName').value.trim()) document.getElementById('dormAddName').value = f.name.replace(/\.[^.]+$/, '').slice(0, 30);
  const img = new Image();
  img.onload = () => { dormAdd.img = img; const pv = document.getElementById('dormAddPreview'); pv.src = dormAdd.url; pv.style.display = ''; document.getElementById('dormAddEmpty').style.display = 'none'; };
  img.src = dormAdd.url;
}
async function dormAddPrepare() {
  // 원본 파일을 그대로 올립니다(압축·축소 없음). 큰 그림은 방에 놓일 때의 기본 배율(scale)만 작게 잡아요.
  const { file, img, type } = dormAdd, box = DORM_ADD_BOX[type];
  const w = img.naturalWidth, h = img.naturalHeight, fit = Math.min(1, box / w, box / h);
  return { data: await file.arrayBuffer(), filename: file.name, w, h, px: fit >= 1, scale: fit < 1 ? fit : undefined };
}
async function submitDormAdd() {
  if (!dormAdd) return;
  const name = dormAdd.type === 'chara' ? (dormAdd.id ? (dormAsset(dormAdd.id) || {}).name : '캐릭터 SD') : document.getElementById('dormAddName').value.trim();
  const lines = document.getElementById('dormAddLines').value.split('\n').map(x => x.trim()).filter(Boolean).slice(0, 20);
  if (dormAdd.id) {
    socket.emit('dorm_asset_update', { id: dormAdd.id, name, lines });
    closeDormAddModal(); return;
  }
  if (!dormAdd.img) { showShopToast('이미지를 먼저 삽입해 주세요.'); return; }
  if (dormAdd.type !== 'chara' && !name) { showShopToast('아이템 이름을 입력해 주세요.'); return; }
  const prep = await dormAddPrepare();
  socket.emit('dorm_asset_upload', { ...prep, name, category: dormAdd.type, lines });
  dormCat = 'mine'; closeDormAddModal();
}
function deleteDormAddAsset() {
  if (!dormAdd || !dormAdd.id) return;
  const id = dormAdd.id;
  uiConfirm('이 아이템을 삭제할까요? 방에 배치된 아이템도 함께 삭제됩니다.', { title: '아이템 삭제', okText: '삭제', danger: true }).then(ok => {
    if (!ok) return;
    if (dormEdit) dormEdit.items = dormEdit.items.filter(it => it.a !== id);
    socket.emit('dorm_asset_delete', { id }); closeDormAddModal();
  });
}
function renderDormGrid() {
  const el = document.getElementById('dormPalette'); if (!el) return;
  const { all, list } = dormAssetList();
  const isOn = (a) => dormCat === 'room' ? a.id === dormEdit.base : a.slot ? (dormEdit[a.slot] === a.id) : a.id === dormPick;
  const mine = dormCat === 'mine';
  const canManage = (a) => a.owner ? (dormIsGm() || a.owner === dormMe()) : dormIsGm();
  const tiles = list.map(a => `<div class="dorm-asset-wrap"><button class="dorm-asset ${isOn(a) ? 'on' : ''} ${a.smooth ? 'smooth' : ''}" data-tip="${mailEsc(a.name)}${a.set ? ' · ' + mailEsc(a.set) : ''}"
      style="background-image:url('${a.url}')" onclick="pickDormAsset('${a.id}')"></button>${a.category === 'chara' ? '<span class="dorm-asset-tag"><i class="fa-solid fa-comment-dots"></i></span>' : ''}
      ${mine && canManage(a) ? `<button class="dorm-asset-edit" onclick="openDormAddModal('${a.id}')" data-tip="수정"><i class="fa-solid fa-pen"></i></button>` : ''}</div>`).join('');
  const addTile = mine ? `<button class="dorm-asset dorm-asset-add" onclick="openDormAddModal()"><i class="fa-solid fa-plus"></i><span>아이템 추가</span></button>` : '';
  el.innerHTML = (list.length || mine) ? `<div class="dorm-assets">${addTile}${tiles}</div>`
    : (all.length ? emptyHtml('fa-magnifying-glass', '찾는 자료가 없어요', '다른 세트나 이름으로 찾아보세요.', null, true) : emptyHtml('fa-box-open', '이 종류의 자료가 아직 없어요', '', null, true));
  const cnt = document.getElementById('dormItemCnt'); if (cnt) cnt.textContent = `${dormEdit.items.length} / 150`;
  renderDormEditBar();
}
// 방 아래쪽 떠 있는 막대 : 놓는 중인 자료 / 고른 소품의 크기·반전·치우기
function renderDormEditBar() {
  const bar = document.getElementById('dormEditBar'); if (!bar) return;
  const sel = dormSel >= 0 ? dormEdit.items[dormSel] : null;
  if (sel) {
    const a = dormAsset(sel.a) || {};
    bar.className = 'dorm-edit-bar on';
    bar.innerHTML = `<span class="th" style="background-image:url('${a.url}')"></span><span class="nm">${mailEsc(a.name || '')}</span><span class="sep"></span>
      <button onclick="dormResizeSel(-1)" data-tip="작게 ( - )"><i class="fa-solid fa-minus"></i></button><span class="val">×${a.smooth ? +(dormZ(sel, a) / (a.s || 1)).toFixed(2) : dormZ(sel, a)}</span>
      <button onclick="dormResizeSel(1)" data-tip="크게 ( + )"><i class="fa-solid fa-plus"></i></button>
      <button class="txt" onclick="dormResizeSel(0)">원래 크기</button><span class="sep"></span>
      <button onclick="dormLayerSel('top')" data-tip="최상단으로"><i class="fa-solid fa-angles-up"></i></button>
      <button onclick="dormLayerSel('up')" data-tip="한 칸 앞으로"><i class="fa-solid fa-angle-up"></i></button>
      <button onclick="dormLayerSel('down')" data-tip="한 칸 뒤로"><i class="fa-solid fa-angle-down"></i></button>
      <button onclick="dormLayerSel('bottom')" data-tip="최하단으로"><i class="fa-solid fa-angles-down"></i></button><span class="sep"></span>
      <button onclick="dormFlipSel()" data-tip="좌우 반전"><i class="fa-solid fa-left-right"></i></button>
      <button class="del" onclick="dormDeleteSel()" data-tip="치우기 ( Delete )"><i class="fa-solid fa-trash-can"></i></button>
      <button onclick="dormSel=-1; renderDorm()" data-tip="선택 해제"><i class="fa-solid fa-xmark"></i></button>`;
  } else if (dormPick) {
    const a = dormAsset(dormPick) || {};
    bar.className = 'dorm-edit-bar on placing';
    bar.innerHTML = `<span class="th" style="background-image:url('${a.url}')"></span><span class="nm">${mailEsc(a.name || '')}</span>
      <span class="hint">방을 눌러 놓아요</span><button onclick="dormPick=null; renderDormGrid(); dormUpdateGhost()" data-tip="그만 놓기 ( Esc )"><i class="fa-solid fa-xmark"></i></button>`;
  } else {
    bar.className = 'dorm-edit-bar';
    // 내 방이고 지난 기간 방이 있으면 : 그 배치를 불러와 고쳐 쓸 수 있게(저장해야 적용)
    const mine = dormRoom && dormMe() && dormMe() === dormRoom.owner && !dormIsGm();
    const past = mine && dormPast.owner === dormRoom.owner ? (dormPast.rooms || []) : [];
    bar.innerHTML = `<i class="fa-solid fa-hand-pointer"></i><span class="hint">놓은 소품을 누르면 옮기거나 크기를 바꿀 수 있어요</span>`
      + (past.length ? '<span class="sep"></span>' + past.map((e, i) => `<button class="txt" onclick="loadDormPastLayout(${i})" data-tip="${e.period.no}차 ${mailEsc(e.period.name)} 방 배치를 불러와요 (저장해야 적용)"><i class="fa-solid fa-clock-rotate-left"></i> ${e.period.no}차 ${mailEsc(e.period.name)} 불러오기</button>`).join('') : '');
  }
}
function pickDormAsset(id) {
  if (dormCat === 'room') { dormEdit.base = id; renderDorm(); return; }
  const a = dormAsset(id);
  // 벽지·바닥은 고르면 방에 딱 맞춰 깔리고, 한 번 더 누르면 걷어냅니다.
  if (a && a.slot) { dormEdit[a.slot] = dormEdit[a.slot] === id ? null : id; dormPick = null; renderDorm(); return; }
  dormPick = dormPick === id ? null : id; dormSel = -1; renderDormGrid(); dormUpdateGhost();
  document.querySelectorAll('#dormStage .dorm-item.sel').forEach(x => x.classList.remove('sel'));
}
function dormResizeSel(dir) {
  if (dormSel < 0) return;
  const it = dormEdit.items[dormSel], a = dormAsset(it.a);
  const cur = dormZ(it, a), def = (a && a.s) || 1;
  // 원본 그림(smooth)은 기본 크기의 0.25배 단위로, 도트는 원래처럼 0.25배 단위로
  const z = dir === 0 ? def : a && a.smooth
    ? Math.max(def * 0.25, Math.min(def * 4, Math.round((cur / def + dir * 0.25) * 4) / 4 * def))
    : Math.max(0.25, Math.min(4, Math.round((cur + dir * 0.25) * 4) / 4));
  // 크기가 바뀌어도 바닥에 닿은 아래쪽 가운데 위치는 그대로 둡니다.
  const cx = it.x + a.w * cur / 2, by = it.y + a.h * cur;
  it.z = z; it.x = Math.round(cx - a.w * z / 2); it.y = Math.round(by - a.h * z);
  renderDorm();
}
function dormFlipSel() { if (dormSel >= 0) { dormEdit.items[dormSel].f = !dormEdit.items[dormSel].f; renderDorm(); } }
function dormDeleteSel() { if (dormSel >= 0) { dormEdit.items.splice(dormSel, 1); dormSel = -1; renderDorm(); } }
let dormGhostPos = null;
function dormClampPos(a, x, y, z) {
  const b = dormBase(dormEdit), w = a.w * (z || 1), h = a.h * (z || 1);
  return { x: Math.round(Math.max(-w / 2, Math.min(dormBW(b) - w / 2, x))), y: Math.round(Math.max(-h / 2, Math.min(dormBH(b) - h / 2, y))) };
}
function dormUpdateGhost() {
  const g = document.getElementById('dormGhost'); if (!g) return;
  const a = dormPick && dormAsset(dormPick);
  if (!a || !dormGhostPos) { g.style.display = 'none'; return; }
  const s = dormGhostPos.s, z = a.s || 1, p = dormClampPos(a, dormGhostPos.px - a.w * z / 2, dormGhostPos.py - a.h * z + 2, z);
  Object.assign(g.style, { display: 'block', left: p.x * s + 'px', top: p.y * s + 'px', width: a.w * z * s + 'px', height: a.h * z * s + 'px', backgroundImage: `url('${a.url}')` });
  dormGhostPos.x = p.x; dormGhostPos.y = p.y;
}
function bindDormStage(s) {
  const st = document.getElementById('dormStage'); if (!st) return;
  let drag = null;
  const ptAt = (e) => { const b = st.getBoundingClientRect(); return { px: (e.clientX - b.left) / s, py: (e.clientY - b.top) / s }; };
  st.addEventListener('pointermove', (e) => {
    const p = ptAt(e);
    if (drag) {
      const it = dormEdit.items[drag.i], a = dormAsset(it.a), q = dormClampPos(a, p.px - drag.ox, p.py - drag.oy, dormZ(it, a));
      it.x = q.x; it.y = q.y; drag.el.style.left = q.x * s + 'px'; drag.el.style.top = q.y * s + 'px'; drag.moved = true;
      return;
    }
    dormGhostPos = Object.assign(p, { s }); dormUpdateGhost();
  });
  st.addEventListener('pointerleave', () => { if (!drag) { dormGhostPos = null; dormUpdateGhost(); } });
  st.addEventListener('pointerdown', (e) => {
    const itemEl = e.target.closest('.dorm-item');
    if (itemEl && !dormPick) {
      const i = +itemEl.dataset.i, it = dormEdit.items[i], p = ptAt(e);
      dormSel = i; st.querySelectorAll('.dorm-item.sel').forEach(x => x.classList.remove('sel')); itemEl.classList.add('sel');
      drag = { i, el: itemEl, ox: p.px - it.x, oy: p.py - it.y, moved: false };
      st.setPointerCapture(e.pointerId); renderDormEditBar(); return;
    }
    const a = dormPick && dormAsset(dormPick);
    if (a) {
      if (!dormGhostPos) { dormGhostPos = Object.assign(ptAt(e), { s }); dormUpdateGhost(); }
      if (dormEdit.items.length >= 150) { showShopToast('소품은 150개까지 놓을 수 있어요.'); return; }
      // 캐릭터 SD는 방에 하나만 : 이미 있으면 새 캐릭터로 바꿉니다.
      if (a.category === 'chara' && dormEdit.items.some(x => (dormAsset(x.a) || {}).category === 'chara')) {
        dormEdit.items = dormEdit.items.filter(x => (dormAsset(x.a) || {}).category !== 'chara');
        dormSel = -1; showShopToast('캐릭터 SD는 방에 하나만 배치할 수 있어 기존 캐릭터를 교체했습니다.');
      }
      const nit = { a: a.id, x: dormGhostPos.x, y: dormGhostPos.y, f: false, z: a.s || 1 };
      const os = dormEdit.items.filter(x => x.o != null).map(x => x.o);
      if (os.length) nit.o = Math.max(...os) + 1;  // 순서를 정해 둔 방이면 새 소품은 맨 앞에
      dormEdit.items.push(nit); renderDorm();
    } else { dormSel = -1; st.querySelectorAll('.dorm-item.sel').forEach(x => x.classList.remove('sel')); renderDormEditBar(); }
  });
  st.addEventListener('pointerup', () => { if (drag && drag.moved) renderDorm(); drag = null; });
}
// 꾸미기 중 소품 밖(빈 곳 · 옆 패널 · 화면 다른 곳)을 누르면 선택이 풀립니다. 편집 바 · 확대 버튼 · 확인 창은 예외.
document.addEventListener('pointerdown', (e) => {
  if (!dormEdit || dormSel < 0) return;
  if (e.target.closest && e.target.closest('#dormStage .dorm-item, #dormEditBar, #dormZoom, .ui-dialog, .modal-overlay:not(#dormModal)')) return;
  dormSel = -1;
  document.querySelectorAll('#dormStage .dorm-item.sel').forEach(x => x.classList.remove('sel'));
  renderDormEditBar();
});
document.addEventListener('keydown', (e) => {
  if (!dormEdit || document.getElementById('dormModal').style.display !== 'flex') return;
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
  if ((e.key === 'Delete' || e.key === 'Backspace') && dormSel >= 0) { e.preventDefault(); dormDeleteSel(); }
  if ((e.key === '-' || e.key === '_') && dormSel >= 0) { e.preventDefault(); dormResizeSel(-1); }
  if ((e.key === '=' || e.key === '+') && dormSel >= 0) { e.preventDefault(); dormResizeSel(1); }
  if (e.key === 'Escape' && dormPick) { e.stopPropagation(); dormPick = null; renderDormGrid(); dormUpdateGhost(); }
  else if (e.key === 'Escape' && dormSel >= 0) { dormSel = -1; renderDorm(); }
});
window.addEventListener('resize', () => { if (dormView === 'room' && document.getElementById('dormModal').style.display === 'flex') renderDorm(); });

// ---------- 출처 ----------
function openDormCredits() {
  const m = document.getElementById('dormCreditModal'); m.style.display = 'flex';
  const cr = (dormData && dormData.credits) || [];
  const count = id => (dormData.assets || []).filter(a => a.credit === id).length;
  document.getElementById('dormCreditBody').innerHTML = cr.length ? cr.map(c => `<div class="dorm-credit"><div class="t">${mailEsc(c.title)}</div>
    <div class="m">${c.author ? `제작 ${mailEsc(c.author)}` : ''}${c.license ? ` · ${mailEsc(c.license)}` : ''} · 자료 ${count(c.id)}개</div>
    ${/^https?:\/\//.test(c.url) ? `<div class="m"><a href="${mailEsc(c.url)}" target="_blank" rel="noopener">${mailEsc(c.url)}</a></div>` : ''}</div>`).join('')
    : emptyHtml('fa-circle-info', '아직 등록된 출처가 없어요', '', null, true);
}

// ---------- 관리 (운영진) ----------
// 운영진 : 고치는 기간을 바꾸면 그 기간의 배치로 초안을 다시 잡습니다.
function setDormManagePeriod(pid) { dormManagePeriod = pid; dormHallsDraft = null; renderDorm(); }
function setDormCurrentPeriod(pid) {
  const p = (dormData.periods || []).find(x => x.id === pid); if (!p) return;
  uiConfirm(`지금 마이룸을 ${p.no}차 ${p.name}(으)로 바꿀까요? 모두의 마이룸이 이 기간의 배치로 바뀌고, 지난 기간의 방은 각자 마이페이지에서만 볼 수 있어요.`,
    { title: '마이룸 기간 바꾸기', okText: '바꾸기' }).then(ok => ok && socket.emit('dorm_period_set', { period: pid }));
}
function dormManageHtml() {
  const periods = dormData.periods || [DORM_P_DEFAULT];
  if (!dormManagePeriod || !periods.some(p => p.id === dormManagePeriod)) dormManagePeriod = dormP().id;
  const MP = periods.find(p => p.id === dormManagePeriod) || dormP();
  const srcHalls = (dormData.period_halls && dormData.period_halls[MP.id]) || (MP.id === dormP().id ? dormData.halls : []) || [];
  if (!dormHallsDraft) dormHallsDraft = JSON.parse(JSON.stringify(srcHalls));
  const stLabel = { current: '지금', past: '지난 기간', future: '다음 기간' };
  const periodSec = `<div class="dorm-sec"><h3><i class="fa-solid fa-calendar-days"></i> 마이룸 기간 <span class="dorm-room-sub">기간마다 배치 · 꾸밈 · 방명록이 따로예요</span></h3>
    <div class="dorm-periods">${periods.map(p => `<button class="dorm-period ${p.id === MP.id ? 'on' : ''} ${p.status}" onclick="setDormManagePeriod('${p.id}')">
        <span class="no">${p.no}차</span><b>${mailEsc(p.name)}</b><span class="st">${stLabel[p.status] || ''}</span></button>`).join('')}</div>
    <div class="dorm-default-row"><div class="dorm-default-prev">${dormMiniRoomHtml((dormData.period_defaults || {})[MP.id] || { base: dormData.default_base, items: [] }, 120, 90)}</div>
      <div class="dorm-default-txt"><b>${MP.no}차 ${mailEsc(MP.name)} 기본 방</b><span>아직 꾸미지 않은 방은 모두 이 모양으로 보여요. 기간마다 따로 꾸밀 수 있어요.</span></div>
      <button class="btn" onclick="openDormDefaultEdit('${MP.id}')"><i class="fa-solid fa-paintbrush"></i> 기본 방 꾸미기</button></div>
    ${MP.status !== 'current' ? `<div class="dorm-period-act"><span>${MP.no}차 ${mailEsc(MP.name)} 배치를 미리 짜 두고, 때가 되면 지금 기간으로 바꿔요.</span>
      <button class="btn" onclick="setDormCurrentPeriod('${MP.id}')"><i class="fa-solid fa-arrow-right-arrow-left"></i> 지금 기간으로 바꾸기</button></div>` : ''}</div>`;
  if (!dormCreditsDraft) dormCreditsDraft = JSON.parse(JSON.stringify(dormData.credits || []));
  const used = new Set(dormHallsDraft.flatMap(h => h.slots || []).filter(Boolean));
  const opt = (cur) => `<option value="">빈 방</option>` + dormRoster.map(n => `<option value="${mailEsc(n)}" ${n === cur ? 'selected' : ''} ${used.has(n) && n !== cur ? 'disabled' : ''}>${mailEsc(n)}</option>`).join('');
  const halls = dormHallsDraft.map((h, hi) => `<div class="dorm-hall-edit">
      <input type="text" value="${mailEsc(h.name)}" placeholder="${mailEsc(MP.unit)} 이름" oninput="dormHallsDraft[${hi}].name=this.value">
      ${[0, 1, 2, 3, 4, 5].map(si => `<select onchange="dormHallsDraft[${hi}].slots[${si}]=this.value||null; renderDorm()">${opt((h.slots || [])[si])}</select>`).join('')}
      <button class="dorm-x" data-tip="${mailEsc(MP.unit)} 지우기" onclick="dormHallsDraft.splice(${hi},1); renderDorm()"><i class="fa-solid fa-xmark"></i></button></div>`).join('');
  const crOpt = (cur) => `<option value="">출처 없음</option>` + (dormData.credits || []).map(c => `<option value="${c.id}" ${c.id === cur ? 'selected' : ''}>${mailEsc(c.title)}</option>`).join('');
  const catOpt = (cur) => DORM_CATS.map(([k, t]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${t}</option>`).join('');
  const builtinN = (dormData.assets || []).filter(a => a.builtin).length;
  const builtinSets = new Set((dormData.assets || []).filter(a => a.builtin).map(a => a.set)).size;
  const assets = (dormData.assets || []).filter(a => !a.builtin).map(a => `<div class="dorm-arow"><div class="th" style="background-image:url('${a.url}')"></div>
      <input type="text" value="${mailEsc(a.name)}" onchange="socket.emit('dorm_asset_update',{id:'${a.id}',name:this.value})">
      <select onchange="socket.emit('dorm_asset_update',{id:'${a.id}',category:this.value})">${catOpt(a.category)}</select>
      <span class="sz">${a.w}×${a.h}</span>
      <select class="cr" onchange="socket.emit('dorm_asset_update',{id:'${a.id}',credit:this.value})">${crOpt(a.credit)}</select>
      <button class="dorm-x" data-tip="자료 지우기" onclick="uiConfirm('이 자료를 지울까요? 이미 놓인 것도 사라져요.',{title:'자료 지우기',okText:'지우기',danger:true}).then(ok=>ok&&socket.emit('dorm_asset_delete',{id:'${a.id}'}))"><i class="fa-solid fa-xmark"></i></button></div>`).join('');
  const credits = dormCreditsDraft.map((c, ci) => `<div class="dorm-crow">
      <input type="text" value="${mailEsc(c.title)}" placeholder="자료 이름" oninput="dormCreditsDraft[${ci}].title=this.value">
      <input type="text" value="${mailEsc(c.author)}" placeholder="제작자" oninput="dormCreditsDraft[${ci}].author=this.value">
      <input type="text" value="${mailEsc(c.license)}" placeholder="라이선스 (예: CC0)" oninput="dormCreditsDraft[${ci}].license=this.value">
      <input type="text" value="${mailEsc(c.url)}" placeholder="주소 https://…" oninput="dormCreditsDraft[${ci}].url=this.value">
      <button class="dorm-x" onclick="dormCreditsDraft.splice(${ci},1); renderDorm()"><i class="fa-solid fa-xmark"></i></button></div>`).join('');
  return `
    ${periodSec}
    <div class="dorm-sec"><h3><i class="fa-solid fa-building"></i> ${MP.no}차 ${mailEsc(MP.name)} · ${mailEsc(MP.unit)} 배치 <span class="dorm-room-sub">한 ${mailEsc(MP.unit)}에 ${dormData.hall_size}명</span><span class="sp"></span>
      <button class="btn-plain" onclick="dormHallsDraft.push({name:'${(dormHallsDraft.length + 1)}${mailEsc(MP.unit)}', slots:[null,null,null,null,null,null]}); renderDorm()"><i class="fa-solid fa-plus"></i> ${mailEsc(MP.unit)} 추가</button>
      <button class="btn" onclick="socket.emit('dorm_halls_save',{halls:dormHallsDraft, period:'${MP.id}'}); dormHallsDraft=null">저장</button></h3>
      ${halls || '<div class="dorm-hint">관 추가를 눌러 첫 관을 만들어 주세요.</div>'}</div>
    <div class="dorm-sec"><h3><i class="fa-solid fa-chess-rook"></i> 도트 자료 <span class="dorm-room-sub">기본 ${builtinN}개(${builtinSets}세트) · 올린 자료 ${(dormData.assets || []).length - builtinN}개</span></h3>
      <div class="dorm-up">
        <div class="dorm-up-prev" onclick="document.getElementById('dormUpFile').click()" style="${dormUp.url ? `background-image:url('${dormUp.url}')` : ''}">${dormUp.url ? '' : '이미지<br>고르기'}</div>
        <input type="text" placeholder="이름 (예: 침대)" value="${mailEsc(dormUp.name)}" oninput="dormUp.name=this.value">
        <select onchange="dormUp.category=this.value">${catOpt(dormUp.category)}</select>
        <select onchange="dormUp.credit=this.value">${crOpt(dormUp.credit)}</select>
        <button class="btn" onclick="uploadDormAsset()"><i class="fa-solid fa-upload"></i> 올리기</button>
      </div>
      <div class="dorm-hint">png·gif·webp (최대 ${UPLOAD_IMG_MB}MB). 방 그림 크기에 맞춘 원본 크기 그대로 올려 주세요${dormUp.nw ? ` → <b style="color:var(--text)">${dormUp.nw}×${dormUp.nh}</b>` : ''}.
        "방" 종류로 올리면 방 바탕으로 쓸 수 있어요. 출처를 먼저 아래에 등록하면 자료마다 고를 수 있어요.</div>
      <input type="file" id="dormUpFile" accept="image/png,image/gif,image/webp" style="display:none" onchange="onDormUpFile(event)">
      <div class="dorm-alist">${assets}</div></div>
    <div class="dorm-sec"><h3><i class="fa-solid fa-circle-info"></i> 출처<span class="sp"></span>
      <button class="btn-plain" onclick="dormCreditsDraft.push({title:'',author:'',license:'',url:''}); renderDorm()"><i class="fa-solid fa-plus"></i> 출처 추가</button>
      <button class="btn" onclick="socket.emit('dorm_credits_save',{credits:dormCreditsDraft}); dormCreditsDraft=null">저장</button></h3>
      ${credits || '<div class="dorm-hint">도트 자료를 가져온 곳(자료 이름·제작자·라이선스·주소)을 적어 주세요. 마이룸 화면의 "출처"에 모두 보여요.</div>'}</div>`;
}
function onDormUpFile(ev) {
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (!f) return;
  if (f.size > UPLOAD_IMG_BYTES) { showShopToast(`이미지가 너무 커요 (최대 ${UPLOAD_IMG_MB}MB).`); return; }
  dormUp.filename = f.name; if (!dormUp.name) dormUp.name = f.name.replace(/\.[^.]+$/, '');
  if (dormUp.url) URL.revokeObjectURL(dormUp.url);
  dormUp.url = URL.createObjectURL(f);
  const img = new Image(); img.onload = () => { dormUp.nw = img.naturalWidth; dormUp.nh = img.naturalHeight; renderDorm(); }; img.src = dormUp.url;
  f.arrayBuffer().then(b => { dormUp.buf = b; });
}
function uploadDormAsset() {
  if (!dormUp.buf || !dormUp.nw) { showShopToast('먼저 이미지를 골라 주세요.'); return; }
  socket.emit('dorm_asset_upload', { filename: dormUp.filename, data: dormUp.buf, name: dormUp.name, category: dormUp.category, credit: dormUp.credit, w: dormUp.nw, h: dormUp.nh });
  if (dormUp.url) URL.revokeObjectURL(dormUp.url);
  Object.assign(dormUp, { buf: null, filename: '', url: '', name: '', nw: 0, nh: 0 });
}
// ==================================================================
// 채팅 검색 / 운영진 메시지 삭제
// ==================================================================
var chatSearchQuery = '';  // var: 위쪽에서 먼저 호출되는 채팅 렌더링에서도 쓰므로 호이스팅되게 둡니다
function chatPlain(t) { return String(t == null ? '' : t).replace(/<[^>]*>/g, ''); }
function matchesChatSearch(entry) {
  if (!chatSearchQuery) return true;
  const q = chatSearchQuery.toLowerCase();
  return chatPlain(entry.text).toLowerCase().includes(q) || chatPlain(entry.nickname).toLowerCase().includes(q);
}
// 검색어를 노란 형광펜으로 표시합니다. 서식(태그)이 들어간 글은 태그 밖 글자에만 표시합니다.
function highlightChat(html) {
  const s = String(html == null ? '' : html);
  if (!chatSearchQuery) return s;
  const esc = chatSearchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(esc, 'gi');
  return s.split(/(<[^>]*>)/).map(part => part.startsWith('<') ? part : part.replace(re, m => `<mark>${m}</mark>`)).join('');
}
// 검색 아이콘을 누르면 상단 제목 자리가 검색칸으로 바뀌고 아이콘은 X가 됩니다(X = 검색 모드 해제).
function toggleChatSearch(force) {
  const header = document.querySelector('.member-panel .member-header');
  const open = force === undefined ? !header.classList.contains('searching') : !!force;
  header.classList.toggle('searching', open);
  const btn = document.getElementById('chatSearchBtn');
  btn.innerHTML = open ? '<i class="fa-solid fa-xmark"></i>' : '<i class="fa-solid fa-magnifying-glass"></i>';
  const input = document.getElementById('chatSearchInput');
  if (open) { input.focus(); input.select(); }
  else {
    input.value = '';
    if (chatSearchQuery) { chatSearchQuery = ''; renderChatFiltered(); }
    updateChatSearchCount(0);
  }
}
function runChatSearch() {
  chatSearchQuery = document.getElementById('chatSearchInput').value.trim();
  renderChatFiltered();
}
function updateChatSearchCount(n) {
  const el = document.getElementById('chatSearchCount');
  if (el) el.textContent = chatSearchQuery ? `${n}건` : '';
}
function deleteChatMessage(id) { socket.emit('chat_delete', { id }); }
socket.on('chat_deleted', (d) => {
  lastChat = lastChat.filter(e => e.id !== d.id);
  lastTeamChat = lastTeamChat.filter(e => e.id !== d.id);
  document.querySelectorAll(`[data-chat-id="${d.id}"]`).forEach(el => el.remove());
});
