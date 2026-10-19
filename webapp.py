# -*- coding: utf-8 -*-
"""
webapp.py
=========
전투 관리 프로그램의 웹/멀티유저 프로토타입 서버.
기존 battle.py / models.py / database.py / config.py 의 로직을 그대로 재사용하고,
Flask-SocketIO로 방(room) 단위 실시간 동기화 + 역할(운영진/참가자) 구분만 얹었습니다.

실행:
    .venv\\Scripts\\python.exe webapp.py
"""

import gzip
import hmac
import json
import secrets
import safeio
import os
import random
import re
import threading
import time
import uuid

from flask import Flask, request, render_template, redirect, url_for, abort, jsonify, session
from flask_socketio import SocketIO, join_room, leave_room, emit
from itsdangerous import URLSafeTimedSerializer, BadSignature

import config
import shop as shop_mod
import notices as notices_mod
import mailbox as mailbox_mod
import dorm as dorm_mod
import world as world_mod
import loop_game as loop_mod
import backup as backup_mod
import errlog
import traceback
from battle import Battle, BattleError, cell_label
from database import CharacterDatabase, shared_db
from rooms import (
    create_room, get_room, delete_room, list_rooms, load_rooms, save_rooms, load_runtime, save_runtime, mark_runtime_dirty,
    ROOMS, BATTLE_TYPE_LABELS, BATTLE_TYPE_DEFAULTS, GRID_SIZES, ensure_lounge,
)

# 서버(.py) 버전 표시. 화면(html)에 적힌 기대 버전과 다르면 "서버를 다시 켜 주세요" 안내가 뜹니다.
# .py를 고칠 때마다 templates/guest.html의 EXPECTED_SERVER_BUILD와 함께 올려 주세요.
SERVER_BUILD = "2026-10-13.91"

app = Flask(__name__)
# 세션 서명 키 : 처음 켤 때 무작위로 만들어 git에 안 올라가는 secret_key.txt에 보관합니다.
def _load_secret_key():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret_key.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            k = f.readline().strip()
            if len(k) >= 32:
                return k
    except OSError:
        pass
    k = secrets.token_hex(32)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(k + "\n")
    except OSError:
        pass
    return k


app.config["SECRET_KEY"] = _load_secret_key()
# 운영진 로그인 유지 : 비밀번호로 한 번 들어오면 서명된 통행증(7일)을 브라우저에 맡겨, 다른 방 · 새로고침에서 다시 묻지 않아요.
_GM_PASS = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="gm-pass")
GM_PASS_AGE = 7 * 86400


def gm_pass_ok(token):
    try:
        return _GM_PASS.loads(str(token or ""), max_age=GM_PASS_AGE) == "gm"
    except (BadSignature, ValueError, TypeError):
        return False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7
# html(templates)을 고치면 서버를 다시 켜지 않아도 브라우저 새로고침(F5)만으로 바로 반영됩니다.
app.config["TEMPLATES_AUTO_RELOAD"] = True
# 올리는 파일 크기 기준(사이트 전체 공통) : 이미지(움직이는 이미지 포함) 15MB, 소리(음악 · 효과음) 20MB.
IMAGE_UPLOAD_MAX_BYTES = 15 * 1024 * 1024
AUDIO_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
# 편지는 이미지 4장을 한 번에 보내므로 소켓 한 번에 받을 수 있는 크기를 그만큼 넉넉히 둡니다.
socketio = SocketIO(app, async_mode="threading", max_http_buffer_size=70 * 1024 * 1024)
app.config["MAX_CONTENT_LENGTH"] = AUDIO_UPLOAD_MAX_BYTES + 1024 * 1024

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(_THIS_DIR, "static", "music")
os.makedirs(MUSIC_DIR, exist_ok=True)
AVATAR_DIR = os.path.join(_THIS_DIR, "static", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)
# 투명도를 지원하는 포맷만 허용합니다(마이페이지 프로필 이미지는 정사각형+투명 배경 전제).
AVATAR_ALLOWED_EXTS = (".png", ".webp", ".gif")
SOUND_EFFECT_DIR = os.path.join(_THIS_DIR, "static", "sound_effects")
os.makedirs(SOUND_EFFECT_DIR, exist_ok=True)
SOUND_EFFECT_ALLOWED_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".aac")
# 재생은 클라이언트에서 6초로 끊지만, 그와 별개로 업로드 자체도 너무 큰 파일은 막아둡니다.
SOUND_EFFECT_MAX_BYTES = AUDIO_UPLOAD_MAX_BYTES
# 스킬 이펙트(컷인) : 글(제목+본문) 또는 이미지(apng 등 움직이는 이미지 포함)
SKILL_LOG_DIR = os.path.join(_THIS_DIR, "static", "skill_fx")
os.makedirs(SKILL_LOG_DIR, exist_ok=True)
SKILL_LOG_IMAGE_EXTS = (".png", ".apng", ".gif", ".webp")
SKILL_LOG_IMAGE_MAX_BYTES = IMAGE_UPLOAD_MAX_BYTES
SKILL_LOG_TITLE_MAX = 30
SKILL_LOG_BODY_MAX = 300
SKILL_LOG_TAGS = {"b", "strong", "i", "em", "br", "div", "p", "span"}
# 이 행동을 하면 그 캐릭터의 스킬 이펙트(컷인)를 모두의 화면에 띄웁니다.
SKILL_ACTIONS = ("collapse", "emission", "shield", "polarize", "reflux", "restore")
SKILL_ACTION_LABELS = {"collapse": "붕괴", "emission": "방출", "shield": "차폐", "polarize": "편광", "reflux": "환류", "restore": "복원"}

# socket id -> {"room_id", "role", "nickname"}
CONNECTIONS = {}

# 참가자(guest) 링크에서 닉네임을 "GM"으로 입력해 전체 조작 권한("all")을 얻으려면
# 이 비밀번호가 필요합니다. 운영진 화면은 없앴으므로 운영 권한을 얻는 방법은 이것뿐입니다.
# 저장소가 공개되어 있으므로 실제 비밀번호는 git에 올라가지 않는 gm_password.txt(첫 줄)에 둡니다.
# 파일이 없을 때만 예전 비밀번호를 그대로 씁니다(이 값은 이미 공개되어 있으니 파일을 꼭 만들어 바꾸세요).
def _load_gm_password():
    try:
        with open(os.path.join(_THIS_DIR, "gm_password.txt"), "r", encoding="utf-8") as f:
            pw = f.readline().strip()
            if pw:
                return pw
    except OSError:
        pass
    return "Nexus**0010"


GM_GUEST_PASSWORD = _load_gm_password()

# 진영 : 1차·3차 마이룸 기간은 모두 Resonans, 2차 기간은 使徒 / Void 중 하나(캐릭터 정보의 nation 칸에 저장)
NATIONS = ("使徒", "Void")

# 스킬 컷인 : 캐치프레이즈 길이, 등장 모션 7종(마이페이지에서 고름)
CATCHPHRASE_MAX = 60
CUTIN_MOTIONS = ("slash", "impact", "rise", "glitch", "fade", "burst", "shutter")

# 포인트 컬러 : 운영진이 고르면 모든 방·모든 화면에 함께 적용됩니다(site_settings.json, git 밖).
POINT_THEMES = ("blue", "purple", "yellow")
SITE_SETTINGS_PATH = os.path.join(_THIS_DIR, "site_settings.json")


def _load_site_settings():
    try:
        with open(SITE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


SITE_SETTINGS = _load_site_settings()


def point_theme():
    t = SITE_SETTINGS.get("point_theme")
    return t if t in POINT_THEMES else "blue"

# 전투 로그(public_log/operator_log)는 방 하나가 몇 시간씩 이어지면 수천 줄까지 쌓일 수
# 있습니다 - 매 행동마다 상태를 통째로 재전송하는 구조라, 로그를 자르지 않으면 세션이
# 길어질수록 매 행동의 전송량이 계속 불어납니다(다인원·장시간일수록 체감 지연이 커짐).
# 그래서 실제 배열은 자르지 않고(되돌리기/로그 복사가 인덱스를 그대로 쓰므로) 전송량만
# 최근 이 줄 수로 제한합니다.
LOG_SEND_CAP = 300


@app.after_request
def add_no_cache_headers(response):
    """개발 중 수정한 화면이 브라우저 캐시에 걸려 옛 버전이 보이는 걸 방지합니다. + 기본 보안 헤더."""
    if request.path.startswith("/static/"):
        # 그림 · 글꼴 · 소리 : 매번 새로 받지 않고, 바뀌었는지만 확인(바뀌지 않았으면 304)해서 빠르게
        response.headers["Cache-Control"] = "no-cache"
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    h = response.headers
    _maybe_gzip(response)
    h.setdefault("X-Content-Type-Options", "nosniff")          # 올린 파일을 다른 형식(스크립트)으로 해석 못 하게
    h.setdefault("X-Frame-Options", "SAMEORIGIN")              # 다른 사이트가 우리 화면을 몰래 틀 안에 넣지 못하게
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")   # 바깥 사이트로는 주소(방 키)가 넘어가지 않게
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


def _maybe_gzip(response):
    """화면(html) · 데이터(json) 응답을 gzip으로 압축해 보내요 : 1MB 화면이 약 270KB로 줄어 휴대폰 첫 로딩이 빨라져요."""
    try:
        if (response.direct_passthrough or response.status_code != 200 or "Content-Encoding" in response.headers
                or "gzip" not in (request.headers.get("Accept-Encoding") or "").lower()):
            return
        if response.mimetype not in ("text/html", "application/json", "text/css", "application/javascript", "text/plain"):
            return
        data = response.get_data()
        if len(data) < 2048:
            return
        response.set_data(gzip.compress(data, compresslevel=5))
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception:
        pass


# ── 보안 : 접속 IP · 비밀번호 시도 제한 · 운영진 로그인 ──────────────────────
def client_ip():
    """Cloudflare 터널을 거치면 실제 접속자 IP는 CF-Connecting-IP에 들어 있어요."""
    env = request.environ
    return (request.headers.get("CF-Connecting-IP") or env.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.remote_addr or "?")


_FAILS = {}          # ip → [실패 시각들]
_FAIL_LIMIT, _FAIL_WINDOW = 6, 10 * 60
_FAIL_LOCK = threading.Lock()


def too_many_fails(ip):
    now = time.time()
    with _FAIL_LOCK:
        recent = [t for t in _FAILS.get(ip, []) if now - t < _FAIL_WINDOW]
        _FAILS[ip] = recent
        return len(recent) >= _FAIL_LIMIT


def note_fail(ip):
    with _FAIL_LOCK:
        _FAILS.setdefault(ip, []).append(time.time())
        if len(_FAILS) > 5000:
            _FAILS.clear()


def same_secret(a, b):
    return hmac.compare_digest(str(a or "").encode("utf-8"), str(b or "").encode("utf-8"))


def is_admin():
    return bool(session.get("admin"))


def room_channel(room_id: str, suffix: str) -> str:
    return f"{room_id}:{suffix}"


def _team_channel(room_id: str, team_letter: str) -> str:
    return room_channel(room_id, f"team_{team_letter}")


def _sync_team_channel(room, sid: str, nickname: str, role: str):
    """아군 회의(팀 전용 채팅)용 - 실제로 조작 가능한 캐릭터의 소속 팀 채널에만 넣어줍니다.
    운영진/참가자링크의 "GM"은 양 팀 회의를 다 볼 수 있어야 하므로 두 채널 모두에 넣고,
    팀이 없으면(미배정/관전) 어느 채널에도 들어가지 않습니다. 팀이 바뀔 수 있으므로
    (재입장, 전투 재시작 등) 매번 먼저 둘 다 나갔다가 다시 판단합니다."""
    leave_room(_team_channel(room.id, "A"), sid=sid)
    leave_room(_team_channel(room.id, "B"), sid=sid)
    if role == "gm" or (nickname or "").strip().lower() == "gm":
        join_room(_team_channel(room.id, "A"), sid=sid)
        join_room(_team_channel(room.id, "B"), sid=sid)
        return
    battle = room.game.battle
    if battle is None:
        return
    for c in battle.team_a + battle.team_b:
        if c.name == nickname:
            join_room(_team_channel(room.id, c.team), sid=sid)
            return


def _with_chat_id(entry):
    """채팅 한 줄마다 고유 id를 붙입니다(운영진 메시지 삭제용). 같은 dict를 그대로 돌려줍니다."""
    if not entry.get("id"):
        entry["id"] = uuid.uuid4().hex[:12]
    return entry


def post_system_chat(room, text: str, nickname: str = "system"):
    """채팅 로그에 타임스탬프가 찍힌 시스템 메시지를 남기고 전체에게 전송합니다."""
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": nickname,
        "role": "system",
        "category": "system",
        "text": text,
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))


# ----------------------------------------------------------------------
# 페이지 라우트
# ----------------------------------------------------------------------
@app.route("/manifest.webmanifest")
def web_manifest():
    """홈 화면에 추가하면 주소창 없이(전체 화면) 열리도록 하는 앱 정보. 추가한 그 페이지(방 주소)에서 바로 열립니다."""
    start = request.args.get("start") or "/"
    if not start.startswith("/") or start.startswith("//") or "\\" in start:
        start = "/"
    resp = jsonify({
        "name": "EarthTerrA", "short_name": "EarthTerrA",
        "start_url": start, "scope": "/", "display": "fullscreen",
        "display_override": ["fullscreen", "standalone"],
        "orientation": "any", "background_color": "#050505", "theme_color": "#050505",
        "icons": [
            {"src": "/static/app_icon_192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/app_icon_512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


_LOGIN_HTML = """<!doctype html><html lang="ko" data-point="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rooms</title><meta name="robots" content="noindex">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.7.2/css/all.min.css">
<style>
/* 방 로그인 화면(#loginGate)과 같은 디자인 */
@font-face{font-family:"Baunk";font-display:swap;src:url("/static/fonts/Baunk.ttf") format("truetype")}
:root{--bg:#050505;--text:#f2f2f4;--muted:#8b8b94;--point:#6f93ff;--point-rgb:111,147,255;--accent:#2d5ff5;--on-accent:#fff}
html[data-point="purple"]{--point:#a48dff;--point-rgb:164,141,255;--accent:#7650f0;--on-accent:#fff}
html[data-point="yellow"]{--point:#f0c862;--point-rgb:240,200,98;--accent:#e2b23c;--on-accent:#17171a}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px 16px;background:var(--bg);color:var(--text);font-family:"Pretendard","42dot Sans",system-ui,"Malgun Gothic",sans-serif;overflow:hidden}
.bg{position:fixed;inset:0;pointer-events:none;overflow:hidden}
.bg::before{content:"";position:absolute;inset:0;background:radial-gradient(55% 45% at 50% 42%,rgba(var(--point-rgb),.16),transparent 70%),radial-gradient(rgba(255,255,255,.07) 1px,transparent 1.2px) 0 0/22px 22px;-webkit-mask-image:radial-gradient(70% 60% at 50% 45%,#000 30%,transparent 75%);mask-image:radial-gradient(70% 60% at 50% 45%,#000 30%,transparent 75%)}
.orbit{position:absolute;left:50%;top:45%;border-radius:50%;border:1px solid rgba(var(--point-rgb),.16);transform:translate(-50%,-50%);animation:spin 60s linear infinite}
.o1{width:min(560px,130vw);height:min(560px,130vw)}
.o2{width:min(820px,190vw);height:min(820px,190vw);border-style:dashed;border-color:rgba(255,255,255,.06);animation-duration:120s;animation-direction:reverse}
.orbit::after{content:"";position:absolute;top:-3px;left:50%;width:6px;height:6px;border-radius:50%;background:var(--point);box-shadow:0 0 12px 2px rgba(var(--point-rgb),.6)}
.o2::after{background:#fff;opacity:.5;box-shadow:none;width:4px;height:4px;top:-2px}
@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}
.wrap{position:relative;width:380px;max-width:100%;display:flex;flex-direction:column;align-items:center;gap:18px}
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.42em;color:var(--muted);padding-left:.42em;display:flex;align-items:center;gap:12px}
.eyebrow::before,.eyebrow::after{content:"";width:28px;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.25))}
.eyebrow::after{transform:scaleX(-1)}
form{position:relative;width:100%;display:flex;flex-direction:column;gap:10px;padding:34px 28px 26px;background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.015)),rgba(16,16,19,.78);-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.08);border-radius:16px;box-shadow:0 30px 80px rgba(0,0,0,.55);animation:in .5s cubic-bezier(.2,.9,.25,1) both}
form::before{content:"";position:absolute;left:24px;right:24px;top:-1px;height:1px;background:linear-gradient(90deg,transparent,var(--point),transparent);opacity:.9}
@keyframes in{from{opacity:0;transform:translateY(16px) scale(.985)}}
.title{font-family:"Baunk","Pretendard",sans-serif;font-size:42px;line-height:1;text-align:center}
.chip{align-self:center;display:inline-flex;align-items:center;gap:7px;margin:6px 0 18px;padding:5px 12px;border-radius:999px;background:rgba(var(--point-rgb),.10);border:1px solid rgba(var(--point-rgb),.22);font-size:12px;font-weight:600}
.chip i{color:var(--point);font-size:11px}
.field{position:relative}
.field>i{position:absolute;left:15px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:14px;pointer-events:none;transition:color .15s}
.field:focus-within>i{color:var(--point)}
input{width:100%;height:50px;padding:0 14px 0 42px;font-size:15px;border-radius:12px;background:rgba(0,0,0,.35);border:1px solid rgba(255,255,255,.08);color:var(--text);font-family:inherit;transition:border-color .15s,box-shadow .15s}
input::placeholder{color:rgba(255,255,255,.32)}
input:focus{outline:none;border-color:rgba(var(--point-rgb),.7);box-shadow:0 0 0 3px rgba(var(--point-rgb),.14)}
.err{min-height:18px;margin:0;font-size:13px;color:#ff7a7a;text-align:center}
button{height:50px;border:none;border-radius:12px;background:var(--accent);color:var(--on-accent);font:inherit;font-size:15px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;box-shadow:0 10px 30px rgba(var(--point-rgb),.25);transition:transform .15s,box-shadow .15s,filter .15s}
button:hover{transform:translateY(-1px);filter:brightness(1.08);box-shadow:0 14px 34px rgba(var(--point-rgb),.35)}
.hint{font-size:12px;color:var(--muted);line-height:1.6;text-align:center;margin-top:6px}
@media (prefers-reduced-motion:reduce){.orbit,form{animation:none}}
</style></head><body>
<div class="bg"><span class="orbit o2"></span><span class="orbit o1"></span></div>
<div class="wrap"><div class="eyebrow">EARTHTERRA</div>
<form method="post" action="/login"><div class="title">Rooms</div>
<div class="chip"><i class="fa-solid fa-lock"></i>방 목록은 운영진만 볼 수 있어요</div>
<div class="field"><i class="fa-solid fa-key"></i><input type="password" name="password" placeholder="운영진 비밀번호" aria-label="운영진 비밀번호" autofocus autocomplete="current-password"></div>
{err}
<button>입장<i class="fa-solid fa-arrow-right"></i></button>
<div class="hint">참가자는 운영진이 보낸 방 링크로 들어가 주세요.</div>
</form></div></body></html>"""


@app.route("/login", methods=["GET", "POST"])
def admin_login():
    err = ""
    if request.method == "POST":
        ip = client_ip()
        if too_many_fails(ip):
            err = "시도가 너무 많아요. 10분 뒤에 다시 해 주세요."
        elif same_secret(request.form.get("password"), GM_GUEST_PASSWORD):
            session.clear()
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("index"))
        else:
            note_fail(ip)
            err = "비밀번호가 올바르지 않아요."
    html = _LOGIN_HTML.replace("{err}", f'<p class="err">{err}</p>' if err else '<p class="err"></p>').replace("{theme}", point_theme())
    return html, (429 if "너무" in err else 200), {"Content-Type": "text/html; charset=utf-8"}


@app.route("/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/robots.txt")
def robots_txt():
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/")
def index():
    # 방 목록에는 모든 방의 참가 링크(키)가 들어 있어서 운영진 로그인 뒤에만 보여 줍니다.
    if not is_admin():
        return redirect(url_for("admin_login"))
    rooms_view = [
        {
            "id": room.id,
            "name": room.name,
            "battle_type": room.battle_type,
            "battle_type_label": BATTLE_TYPE_LABELS.get(room.battle_type, room.battle_type),
            "guest_url": url_for("guest_page", room_id=room.id, key=room.guest_key, _external=True),
            "guest_key": room.guest_key,
        }
        for room in list_rooms()
        # 메인 페이지에는 일반 룸 · LOOP 룸만(전투 방은 일반 룸의 배틀 메뉴에서 만들고 들어가요)
        if room.battle_type in ("lounge", "play")
    ]
    return render_template("index.html", rooms=rooms_view, battle_type_labels=BATTLE_TYPE_LABELS, point_theme=point_theme())


@app.route("/yacht")
def yacht_page():
    return render_template("yacht.html")


@app.route("/create_room", methods=["POST"])
def create_room_route():
    if not is_admin():
        abort(403)
    # 메인 페이지에서는 LOOP(PLAY) 룸만 만들어요. 전투 방은 일반 룸의 배틀 메뉴에서 만들어요.
    battle_type = "play"
    room_name = request.form.get("room_name", "")
    room = create_room(battle_type, name=room_name)
    return redirect(url_for("guest_page", room_id=room.id, key=room.guest_key))


@app.route("/delete_room", methods=["POST"])
def delete_room_route():
    if not is_admin():
        abort(403)
    room_id = request.form.get("room_id", "")
    key = request.form.get("key", "")
    room = get_room(room_id)
    if room is not None and key in (room.gm_key, room.guest_key):
        delete_room(room_id)
    return redirect(url_for("index"))



@app.route("/room/<room_id>")
def guest_page(room_id):
    room = get_room(room_id)
    if room is None:
        abort(404)
    key = request.args.get("key", "")
    if not same_secret(key, room.guest_key):
        abort(403)
    default_team_a, default_team_b = BATTLE_TYPE_DEFAULTS.get(room.battle_type, (3, 3))
    return render_template(
        "guest.html", room_id=room_id, key=key,
        battle_type=room.battle_type,
        battle_type_label=BATTLE_TYPE_LABELS.get(room.battle_type, "PVP"),
        grid_size=GRID_SIZES.get(room.battle_type, 0),
        default_team_a=default_team_a, default_team_b=default_team_b,
        point_theme=point_theme(),
    )


_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|live/|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def extract_youtube_id(url_or_id: str):
    """유튜브 URL(다양한 형식) 또는 11자리 영상 ID 자체를 받아 영상 ID만 뽑아냅니다."""
    url_or_id = (url_or_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    m = _YOUTUBE_ID_RE.search(url_or_id)
    return m.group(1) if m else None


@app.route("/upload_music", methods=["POST"])
def upload_music():
    """운영진이 mp3 파일을 올리면 static/music/에 저장하고 재생용 URL을 돌려줍니다."""
    room_id = request.form.get("room_id", "")
    key = request.form.get("key", "")
    room = get_room(room_id)
    # 러너 링크로 GM 인증(비밀번호)까지 마친 소켓(sid)만 올릴 수 있습니다.
    sid_room = _require_gm_or_guest_gm(request.form.get("sid", ""))
    if room is None or sid_room is None or sid_room.id != room.id:
        return jsonify({"error": "권한이 없습니다."}), 403

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "파일이 없습니다."}), 400
    if not f.filename.lower().endswith(".mp3"):
        return jsonify({"error": "mp3 파일만 업로드할 수 있습니다."}), 400

    f.seek(0, os.SEEK_END)
    if f.tell() > AUDIO_UPLOAD_MAX_BYTES:
        return jsonify({"error": f"파일이 너무 큽니다 (최대 {AUDIO_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."}), 400
    f.seek(0)
    filename = f"{uuid.uuid4().hex}.mp3"
    f.save(os.path.join(MUSIC_DIR, filename))
    return jsonify({"url": url_for("static", filename=f"music/{filename}")})


@app.route("/upload_avatar", methods=["POST"])
def upload_avatar():
    """참가자가 마이페이지에서 자신의 프로필 이미지를 올리면 static/avatars/에 저장하고,
    캐릭터 등록 DB와(전투 중이면) live 캐릭터에도 즉시 반영합니다. 정사각형 여부는
    클라이언트에서 먼저 확인하지만, 서버에서도 투명도를 지원하는 포맷(png/webp/gif)인지만
    가볍게 검사합니다(치수 검사는 이미지 라이브러리 없이는 할 수 없어 생략합니다)."""
    room_id = request.form.get("room_id", "")
    key = request.form.get("key", "")
    name = (request.form.get("name") or "").strip()
    room = get_room(room_id)
    if room is None or room.battle_type == "play" or key not in (room.gm_key, room.guest_key):
        return jsonify({"error": "권한이 없습니다."}), 403
    if not name or not room.game.db.exists(name):
        return jsonify({"error": "존재하지 않는 캐릭터입니다."}), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "파일이 없습니다."}), 400
    ext = os.path.splitext(f.filename.lower())[1]
    if ext not in AVATAR_ALLOWED_EXTS:
        return jsonify({"error": "투명도를 지원하는 png/webp/gif 이미지만 업로드할 수 있습니다."}), 400

    f.seek(0, os.SEEK_END)
    if f.tell() > IMAGE_UPLOAD_MAX_BYTES:
        return jsonify({"error": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."}), 400
    f.seek(0)
    filename = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(AVATAR_DIR, filename))
    avatar_url = url_for("static", filename=f"avatars/{filename}")

    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=existing.get("color"), skill=existing.get("skill"),
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
        avatar_url=avatar_url, sound_effect=existing.get("sound_effect"),
        sound_effect_volume=existing.get("sound_effect_volume"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.avatar_url = avatar_url
    broadcast_state(room)
    return jsonify({"url": avatar_url})


@app.route("/upload_sound_effect", methods=["POST"])
def upload_sound_effect():
    """참가자가 마이페이지에서 자신의 효과음 파일을 올리면 static/sound_effects/에 저장하고,
    캐릭터 등록 DB와(전투 중이면) live 캐릭터에도 즉시 반영합니다. 실제 재생 시 6초로 끊는 건
    클라이언트가 처리하고, 여기서는 업로드 용량만 제한합니다(길이 검사는 오디오 라이브러리
    없이는 할 수 없어 생략합니다)."""
    room_id = request.form.get("room_id", "")
    key = request.form.get("key", "")
    name = (request.form.get("name") or "").strip()
    room = get_room(room_id)
    if room is None or room.battle_type == "play" or key not in (room.gm_key, room.guest_key):
        return jsonify({"error": "권한이 없습니다."}), 403
    if not name or not room.game.db.exists(name):
        return jsonify({"error": "존재하지 않는 캐릭터입니다."}), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "파일이 없습니다."}), 400
    ext = os.path.splitext(f.filename.lower())[1]
    if ext not in SOUND_EFFECT_ALLOWED_EXTS:
        return jsonify({"error": "mp3/wav/ogg/m4a/aac 음성 파일만 업로드할 수 있습니다."}), 400
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > SOUND_EFFECT_MAX_BYTES:
        limit_mb = SOUND_EFFECT_MAX_BYTES // (1024 * 1024)
        return jsonify({"error": f"파일이 너무 큽니다 (최대 {limit_mb}MB)."}), 400

    filename = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(SOUND_EFFECT_DIR, filename))
    sound_url = url_for("static", filename=f"sound_effects/{filename}")

    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=existing.get("color"), skill=existing.get("skill"),
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
        avatar_url=existing.get("avatar_url"), sound_effect=sound_url,
        sound_effect_volume=existing.get("sound_effect_volume"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.sound_effect = sound_url
    broadcast_state(room)
    return jsonify({"url": sound_url})


# ----------------------------------------------------------------------
# 상태 직렬화
# ----------------------------------------------------------------------
def build_character_public(c):
    return {
        "name": c.name,
        "role": c.role or "몹",
        "color": c.color,
        "current_hp": c.current_hp,
        "max_hp": c.max_hp,
        "status": c.status,
        "team": c.team,
        "has_acted": c.has_acted,
        "actions_per_turn": int(getattr(c, "actions_per_turn", 1) or 1),
        "actions_left": c.actions_left,
        "defended_this_round": c.defended_this_round,
        "dodging_this_round": c.dodging_this_round,
        "protecting_ally": c.protecting_ally,
        "pending_attacks": len(c.pending_attacks),
        "pending_heals": sum(h["amount"] for h in c.pending_heals),
        "stats": dict(c.stats),
        "stat_total": c.stat_total,
        "available_actions": c.available_actions(),
        "grid_pos": list(c.grid_pos) if c.grid_pos else None,
        "moved_this_round": c.moved_this_round,
        "move_range": config.calculate_move_range(c.stats, overrides=c.formula_overrides) if c.can_move else None,
        "skill": c.skill,
        "shield_hp": c.shield_hp,
        "defense_count": len(c.defense_grants),
        "self_defense_count": sum(1 for g in c.defense_grants if g is c),  # 직접 방어(본인이 건 방어)
        "polarize_active": c.polarize_active,
        "has_leech_buff": c.leech_buff_expires_round is not None,
        "boss_group": c.boss_group,
        "boss_section": c.boss_section,
        "deferred_this_round": c.deferred_this_round,
        "interceptors": [d.name for d in c.interceptors],  # 이 캐릭터를 대리 방어 중인 아군
        "commanded_by": c.commanded_by,  # 지휘로 이 캐릭터의 다음 행동을 강제한 적 가디언
        "raid_display_name": c.raid_display_name,
        "inventory": c.inventory,
        "skill_log_type": c.skill_log_type,
        "skill_log_text": c.skill_log_text,
        "avatar_url": c.avatar_url,
        "sound_effect": c.sound_effect,
        "sound_effect_volume": c.sound_effect_volume,
    }


def _first_team_display_name(room, battle):
    """전투 시작 안내 메시지용 - 선공 팀을 화면에 쓰는 이름으로 바꿉니다."""
    is_team_a = battle.round_first_team == Battle.TEAM_A
    if room.battle_type == "pvp":
        return battle.round_first_team
    return "러너팀" if is_team_a else "GM팀"


def build_preview_character(room, name):
    """전투 시작 전 '무작위 배치' 미리보기용 - 로스터에서 카드에 필요한 최소 정보만 뽑습니다.
    아직 전투가 없으므로 HP는 항상 최대치로 표시됩니다."""
    data = room.game.db.get(name)
    if not data:
        return None
    stats = data.get("stats", {})
    overrides = config.load_profile_overrides(room.battle_type)
    max_hp = config.calculate_max_hp(stats, overrides=overrides)
    return {
        "name": name,
        "role": data.get("role") or "몹",
        "color": data.get("color"),
        "skill": data.get("skill"),
        "current_hp": max_hp,
        "max_hp": max_hp,
        "stats": dict(stats),
        "stat_total": sum(stats.values()) if stats else 0,
        "raid_display_name": data.get("raid_display_name"),
        "inventory": data.get("inventory") or "",
        "skill_log_type": data.get("skill_log_type") or "text",
        "skill_log_text": data.get("skill_log_text") or "",
        "skill_log_title": data.get("skill_log_title") or "",
        "skill_log_image": data.get("skill_log_image"),
        "catchphrase": data.get("catchphrase") or "",
        "cutin_motion": data.get("cutin_motion") or "slash",
        "avatar_url": data.get("avatar_url"),
        "sound_effect": data.get("sound_effect"),
        "sound_effect_volume": data.get("sound_effect_volume"),
        "points": int(data.get("points") or 0),
        "items": dict(data.get("items") or {}),
        "nation": data.get("nation") or "",
        "hometown": data.get("hometown") or "",
        "age": mailbox_mod.age_of(data),
    }


def telegraph_pending(room, battle):
    """
    이번 라운드에 GM이 아직 전조(공성전 다이스 굴리기 / 마스 레이드 칸 공개)를 출력하지
    않았는지 여부. 전조는 GM의 행동이므로, 이게 True인 동안은 러너의 이동을 막고
    라운드 제한시간도 아직 시작시키지 않습니다.
    """
    if battle is None:
        return False
    if room.battle_type == "siege":
        return room.site_dice_round_no != battle.round_no
    if room.battle_type == "mass_raid":
        return room.telegraph_round_no != battle.round_no
    return False


def sync_round_timer(room):
    """
    라운드가 바뀔 때마다 제한시간 마감 시각을 새로 계산합니다. (모든 접속자가 같은 마감 시각을 봄)
    단, 이번 라운드 전조가 아직 안 나왔다면(telegraph_pending) 러너의 행동 시간이 깎이지
    않도록, 전조가 나올 때까지는 타이머를 시작하지 않습니다.
    """
    battle = room.game.battle
    if battle is None:
        room.round_deadline = None
        room.last_round_no = None
        return
    if room.last_round_no != battle.round_no:
        room.last_round_no = battle.round_no
        room.round_deadline = None
    if room.round_deadline is None and not telegraph_pending(room, battle):
        room.round_deadline = time.time() + config.get_value(
            "ROUND_TIME_LIMIT_SECONDS", config.load_profile_overrides(room.battle_type)
        )


def build_battle_common(battle):
    if battle is None:
        return None
    return {
        "round_no": battle.round_no,
        "round_first_team": battle.round_first_team,
        "current_turn_team": battle.current_turn_team,
        "current_turn_label": battle.current_turn_label(),
        "format_label": f"{len(battle.team_a)}:{len(battle.team_b)}",
        "finished": battle.finished,
        "winner": battle.winner,
        # 팀별로 독립적인 강제 지목(공격유도/지휘) 목록 - 양 팀에 동시에 걸려 있을 수 있습니다.
        "forced_targets": [
            {"team": team, "target": f["target"].name, "count": f["count"]}
            for team, f in battle.forced_targets.items()
        ],
        "can_advance_turn": battle.can_advance_turn(),
        "unacted_members": battle.unacted_members(),
        "grid_width": battle.grid_width,
        "grid_height": battle.grid_height,
        "team_a": [build_character_public(c) for c in battle.team_a],
        "team_b": [build_character_public(c) for c in battle.team_b],
    }


def _clean_device(d):
    """접속 기기(브라우저가 알려준 값) : 종류(pc/tablet/mobile) · 운영체제 · 브라우저. 운영진 화면에만 보냅니다."""
    if not isinstance(d, dict):
        return None
    kind = d.get("type") if d.get("type") in ("pc", "tablet", "mobile") else "pc"
    clip = lambda v: str(v or "")[:20]
    return {"type": kind, "os": clip(d.get("os")), "browser": clip(d.get("browser"))}


def _online_devices(room):
    """운영진 유저 리스트용 : 캐릭터 이름 → 지금 접속한 기기 목록(창을 여러 개 열면 여러 개)."""
    out = {}
    for info in list(CONNECTIONS.values()):
        if info.get("room_id") != room.id or not info.get("device"):
            continue
        nickname = info.get("nickname") or ""
        if room.game.db.exists(nickname):
            out.setdefault(nickname, []).append(info["device"])
    return out


def _online_character_names(room):
    """이 방에 지금 연결된 소켓들의 닉네임 중, 등록된 캐릭터 이름과 정확히 일치하는 것만
    모읍니다. 전투 시작 전/후 상관없이 동작합니다(resolve_control처럼 battle.team_a/b를 보는
    게 아니라 캐릭터 등록 DB 전체를 기준으로 하기 때문) - 유저 접속정보 팝업의 온라인 표시용."""
    names = set()
    for info in CONNECTIONS.values():
        if info.get("room_id") != room.id:
            continue
        nickname = info.get("nickname") or ""
        if room.game.db.exists(nickname):
            names.add(nickname)
    return names


def build_public_state(room, for_gm=False):
    battle = room.game.battle
    sync_round_timer(room)
    battle_payload = build_battle_common(battle)
    if battle_payload is not None:
        battle_payload["round_deadline_at"] = room.round_deadline
        battle_payload["round_limit_seconds"] = config.get_value(
            "ROUND_TIME_LIMIT_SECONDS", config.load_profile_overrides(room.battle_type)
        )
    preview_teams = None
    if battle is None and room.preview_teams:
        preview_teams = {
            "team_a": [c for c in (
                build_preview_character(room, n) for n in room.preview_teams.get("team_a", [])
            ) if c],
            "team_b": [c for c in (
                build_preview_character(room, n) for n in room.preview_teams.get("team_b", [])
            ) if c],
        }
    pub_log = battle.public_log if battle else []
    payload = {
        "room_id": room.id,
        "room_name": room.name,
        "battle": battle_payload,
        "attack_lines": [{"from": l["from"], "to": l["to"]} for l in _current_attack_lines(room)],
        # 세션이 길어지면(다인원 장시간) 로그가 수천 줄까지 쌓일 수 있어서, 매번 전체를 다
        # 보내면 매 행동마다 전송량이 계속 불어납니다. 최근 LOG_SEND_CAP줄만 보내고
        # log_total(누적 총 줄 수)을 같이 보내서, 클라이언트가 "새로 추가된 부분"만 골라
        # 표시할 수 있게 합니다(battle.public_log 자체는 되돌리기/로그 복사 기능이 인덱스를
        # 그대로 쓰므로 서버 메모리에서는 자르지 않습니다).
        "log": pub_log[-LOG_SEND_CAP:],
        "log_total": len(pub_log),
        "chat": [_with_chat_id(e) for e in room.chat_log[-CHAT_SEND_CAP:]],
        "chat_total": len(room.chat_log),  # 더 예전 대화가 있으면 채팅창 맨 위에 '이전 대화 더보기'를 띄웁니다
        "chat_tabs": room.chat_tabs_enabled,
        "battle_thumb": getattr(room, "thumb", None),
        "battle_hidden": bool(getattr(room, "hidden", False)),
        "action_counts": getattr(room, "action_counts", None) or {},
        "chat_tab_labels": room.chat_tab_labels,
        "roster": room.game.db.all_names_by_position(),
        # 전투에 참여하지 않은 캐릭터도 로그인하면 마이페이지를 볼/수정할 수 있도록 등록 정보를 함께 보냅니다
        # (스탯은 상대에게 비공개라 빼고 보냅니다).
        "roster_mypage": {
            name: {k: v for k, v in (build_preview_character(room, name) or {}).items() if k != "stats"}
            for name in room.game.db.all_names()
        },
        "faction_period": dorm_mod.shared_dorms().period_meta(dorm_mod.shared_dorms().current)["no"],
        "userinfo_hidden": list(room.userinfo_hidden),
        "online_characters": sorted(_online_character_names(room)),
        # 채팅창에서 말한 사람의 프로필 이미지/닉네임 색상을 보여주기 위한 정보(전투 참여 여부와 무관).
        "roster_profiles": {
            name: {"color": data.get("color"), "avatar_url": data.get("avatar_url")}
            for name, data in room.game.db.characters.items()
            if data.get("color") or data.get("avatar_url")
        },
        "music": room.music,
        "map_bg": room.map_bg,
        "sfx_defaults": SFX_CONFIG,
        "boss_images": room.boss_images or {},
        "track_bg": room.track_bg,
        "scene": getattr(room, "scene", None),
        "shop": shop_mod.shared_shop().public_payload(),
        "telegraph_cells": room.telegraph_cells,
        "preview_teams": preview_teams,
        "server_now": time.time(),
        "server_build": SERVER_BUILD,
        "point_theme": point_theme(),
        "remind_seconds": remind_seconds(),
        "chat_limit": chat_limit_key(),
    }
    if room.battle_type == "play" and not for_gm:
        # LOOP 방은 웹에 공개돼요(운영진 화면에는 그대로 보내요 : 상점 관리 등) : 다른 방 사람들(캐릭터 목록 · 프로필 · 접속 · 채팅 · 상점)은 보내지 않아요.
        payload.update({"roster": [], "roster_mypage": {}, "roster_profiles": {}, "online_characters": [],
                        "userinfo_hidden": [], "chat": [], "chat_total": 0, "log": [], "log_total": 0,
                        "shop": dict(payload["shop"], items=[]), "preview_teams": None})
    if room.battle_type == "siege":
        payload["site_dice"] = {
            "round_no": room.site_dice_round_no,
            "value": room.site_dice_value,
            "used": room.site_dice_used,
            "stale": battle is not None and room.site_dice_round_no != battle.round_no,
        }
    return payload


def build_gm_state(room):
    battle = room.game.battle
    payload = build_public_state(room, for_gm=True)
    op_log = battle.operator_log if battle else []
    payload["operator_log"] = op_log[-LOG_SEND_CAP:]
    payload["operator_log_total"] = len(op_log)
    payload["can_undo"] = battle.can_undo() if battle else False
    payload["online_devices"] = _online_devices(room)
    # 상점 '운영진 처리' 요청 - 최근 것부터
    payload["shop_requests"] = list(reversed(shop_mod.shared_shop().requests[-100:]))
    payload["roster_detail"] = [
        {"name": name, **room.game.db.get(name)}
        for name in room.game.db.all_names_by_position()
    ]
    payload["pending_reveal"] = room.pending_reveal
    return payload


def _mirror_round_logs(room):
    """전투 로그의 라운드/단계 안내 줄(✶ Round N, ▶ 선공 단계 등)을 일반 채팅창에도 남깁니다.
    되돌리기로 로그가 줄어들면, 그 범위에 해당하는 안내 채팅도 함께 지웁니다."""
    battle = room.game.battle
    if battle is None:
        return
    # 어디까지 옮겼는지는 전투 객체에 기록합니다(새 전투가 시작되면 0부터 다시).
    mirrored = getattr(battle, "_chat_mirrored_len", 0)
    # 서버를 다시 켜서 전투가 복원돼도 같은 값이 유지되도록 id() 대신 전투마다 고정 키를 씁니다.
    battle_key = getattr(battle, "_chat_key", None)
    if battle_key is None:
        battle_key = battle._chat_key = uuid.uuid4().hex
    log = battle.public_log
    if len(log) < mirrored:
        room.chat_log = [
            e for e in room.chat_log
            if not (e.get("category") == "round" and e.get("battle_key") == battle_key
                    and e.get("log_idx", 0) >= len(log))
        ]
        mirrored = len(log)
    for i in range(mirrored, len(log)):
        if log[i].get("tag") == "round":
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "nickname": "system",
                "role": "system",
                "category": "round",
                "text": log[i]["text"],
                "log_idx": i,
                "battle_key": battle_key,
            }
            room.chat_log.append(_with_chat_id(entry))
            mark_runtime_dirty()
            socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))
    battle._chat_mirrored_len = len(log)


# ----------------------------------------------------------------------
# 행동 효과음 : 기본 소리 2종(공격/방어, 지휘/회복). 캐릭터가 마이페이지에 자기 소리를 등록하면 그걸로 재생.
# 기본 소리 파일/음량은 운영진이 바꿀 수 있고 sfx.json에 저장됩니다(모든 방 공통).
# ----------------------------------------------------------------------
SFX_CONFIG_PATH = os.path.join(_THIS_DIR, "sfx.json")
SFX_DEFAULTS = {
    "combat": {"label": "공격 / 방어", "url": "/static/sfx/default_combat.wav", "volume": 100},
    "support": {"label": "지휘 / 회복", "url": "/static/sfx/default_support.wav", "volume": 100},
    # 운영진이 파일을 등록해야 울립니다(기본은 소리 없음).
    "round": {"label": "라운드 전환", "url": None, "volume": 100},
    "boss_hit": {"label": "보스 타격 (공성전·마스 레이드)", "url": None, "volume": 100},
}
# 행동 종류 → 효과음 종류 (이동/배치/시간초과/도주 등은 소리 없음)
ACTION_SFX_KIND = {
    "attack": "combat", "collapse": "combat", "emission": "combat",
    "defend": "combat", "self_defend": "combat", "guard": "combat", "shield": "combat",
    "polarize": "combat", "dodge": "combat", "defense_settle": "combat",
    "command": "support", "heal": "support", "restore": "support", "reflux": "support",
}


def _load_sfx_config():
    cfg = {k: dict(v) for k, v in SFX_DEFAULTS.items()}
    try:
        with open(SFX_CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for k in cfg:
            if isinstance(saved.get(k), dict):
                cfg[k].update({kk: saved[k][kk] for kk in ("url", "volume") if kk in saved[k]})
    except (OSError, ValueError):
        pass
    return cfg


SFX_CONFIG = _load_sfx_config()


def _save_sfx_config():
    safeio.write_json(SFX_CONFIG_PATH, {k: {"url": v["url"], "volume": v["volume"]} for k, v in SFX_CONFIG.items()}, indent=2)


def emit_action_sfx(room, actor_name, action_type):
    kind = ACTION_SFX_KIND.get(action_type)
    # 공성전·마스 레이드에서 보스·거점(2팀)이 공격하면, 운영진이 등록한 '보스 타격' 소리를 씁니다.
    if (kind and actor_name and action_type in ATTACK_LINE_ACTIONS and room.battle_type in ("siege", "mass_raid")
            and SFX_CONFIG.get("boss_hit", {}).get("url") and room.game.battle is not None):
        actor = room.game.battle.find_character(actor_name)
        if actor is not None and actor.team == "B":
            kind = "boss_hit"
    if kind and actor_name:
        socketio.emit("action_sfx", {"actor": actor_name, "kind": kind}, room=room_channel(room.id, "all"))
    if action_type in SKILL_ACTIONS and actor_name:
        fx = skill_cutin_payload(room.game.db.get(actor_name))
        if fx:
            socketio.emit("skill_cutin", dict(fx, actor=actor_name), room=room_channel(room.id, "all"))
        # 채팅창에도 '스킬 사용' 기록을 남깁니다(누르면 그때의 컷인을 다시 볼 수 있게 컷인 내용을 함께 저장).
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "nickname": actor_name,
            "role": "system",
            "category": "skill",
            "text": f"【{SKILL_ACTION_LABELS.get(action_type, action_type)}】",
            "skill": SKILL_ACTION_LABELS.get(action_type, action_type),
            "fx": dict(fx, actor=actor_name) if fx else None,
            # 스킬 사용 횟수 제한이 있는 캐릭터면 남은 횟수(없으면 None - 채팅에 표시하지 않음)
            "uses_left": getattr(room.game.battle.find_character(actor_name), "skill_uses_left", None)
            if room.game.battle is not None and room.game.battle.find_character(actor_name) is not None else None,
        }
        room.chat_log.append(_with_chat_id(entry))
        mark_runtime_dirty()
        socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))


# 격자 전투(공성전/마스 레이드)에서 보스·거점(2팀)이 공격하면, 지도에 공격자 → 피격자 방향의
# 빨간 점선을 그리도록 모두에게 알립니다.
ATTACK_LINE_ACTIONS = ("attack", "collapse", "emission")


def _set_site_group_acted(battle, actor_char, acted: bool):
    """공성전 거점 : 행동한 캐릭터가 2x2 부위 중 하나면 같은 거점의 모든 부위 행동 여부를 함께 맞춥니다."""
    group = [actor_char]
    if actor_char.boss_group:
        group = [c for c in battle.team_b if c.boss_group == actor_char.boss_group]
    for c in group:
        if c.is_alive:
            c.has_acted = acted


def emit_attack_lines(room, action_type, payload):
    if room.battle_type not in ("siege", "mass_raid") or action_type not in ATTACK_LINE_ACTIONS:
        return
    battle = room.game.battle
    if battle is None:
        return
    actor = battle.find_character((payload or {}).get("attacker") or "")
    if actor is None or actor.team != "B":
        return
    if action_type == "emission":
        targets = [c.name for c in battle.team_a if c.grid_pos and c.status not in ("dead", "fled")]
    else:
        targets = [payload.get("target")] if payload.get("target") else []
    if not targets:
        return
    # 라운드가 끝날 때까지 지도에 남깁니다. 되돌리기로 이 행동이 취소되면(로그가 그 앞으로 줄어들면) 함께 사라집니다.
    lines = [l for l in _current_attack_lines(room) if not (l["from"] == actor.name and l["to"] in targets)]
    log_len = len(battle.public_log)
    lines += [{"from": actor.name, "to": t, "log_len": log_len} for t in targets]
    room.attack_lines = lines
    room.attack_lines_round = battle.round_no


def _current_attack_lines(room):
    """지금 라운드에 그려야 하는 공격선 목록(지난 라운드 것이나 되돌리기로 취소된 것은 뺍니다)."""
    battle = room.game.battle
    if battle is None or getattr(room, "attack_lines_round", None) != battle.round_no:
        return []
    n = len(battle.public_log)
    return [l for l in (getattr(room, "attack_lines", None) or []) if l["log_len"] <= n]


def skill_cutin_payload(entry):
    """캐릭터 등록 정보에서 스킬 이펙트(컷인) 내용을 뽑습니다. 아무것도 설정하지 않았으면 None."""
    if not entry:
        return None
    common = {"catchphrase": entry.get("catchphrase") or "",
              "motion": entry.get("cutin_motion") if entry.get("cutin_motion") in CUTIN_MOTIONS else "slash"}
    if entry.get("skill_log_type") == "image":
        return dict(common, type="image", image=entry["skill_log_image"]) if entry.get("skill_log_image") else None
    title, body = entry.get("skill_log_title") or "", entry.get("skill_log_text") or ""
    if not title and not body and not common["catchphrase"]:
        return None
    return dict(common, type="text", title=title, body=body)


def _archive_battle_logs(room):
    """새 전투를 시작하기 전에 지금 전투의 로그를 보관해 둡니다(로그 내려받기용, 최근 10개)."""
    battle = room.game.battle
    if battle is None or not battle.public_log:
        return
    past = getattr(room, "past_battles", None)
    if past is None:
        past = room.past_battles = []
    started = getattr(battle, "_started_label", None) or config.et_stamp()
    past.append({
        "label": f"{started} 전투 ({len(battle.team_a)}:{len(battle.team_b)})",
        "public_log": list(battle.public_log),
        "operator_log": list(battle.operator_log),
        "teams": {c.name: c.team for c in battle.team_a + battle.team_b},
    })
    del past[:-10]


@socketio.on("export_log")
def on_export_log(data):
    """채팅 · 아군 회의 · 전투 로그(· 운영진 로그)를 HTML 파일 하나로 만들어 보내줍니다.
    아군 회의는 넣지 않고, 러너(참가자)가 받으면 운영진 로그도 뺍니다."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    is_gm = _require_gm_or_guest_gm(request.sid) is not None
    battles = list(getattr(room, "past_battles", None) or [])
    battle = room.game.battle
    if battle is not None and battle.public_log:
        started = getattr(battle, "_started_label", None) or "현재"
        battles.append({
            "label": f"{started} 전투 ({len(battle.team_a)}:{len(battle.team_b)}) · 진행 중" if not battle.finished
                     else f"{started} 전투 ({len(battle.team_a)}:{len(battle.team_b)})",
            "public_log": battle.public_log, "operator_log": battle.operator_log,
            "teams": {c.name: c.team for c in battle.team_a + battle.team_b},
        })
    # 파일 모양은 화면(채팅창 · 로그창)과 똑같아야 하므로, 서버는 원본 기록만 보내고
    # 브라우저가 채팅창 · 로그창을 그리는 같은 코드로 파일을 만듭니다(화면을 고치면 파일도 자동으로 같이 바뀜).
    # 운영진 로그는 GM 인증 소켓에만 보냅니다.
    emit("export_log_data", {
        "filename": f"battle_log_{room.id}_{time.strftime('%Y%m%d_%H%M')}.html",
        "room_name": room.name,
        "battle_type_label": BATTLE_TYPE_LABELS.get(room.battle_type, room.battle_type),
        "saved_at": config.et_stamp(),
        # 아군 회의는 팀끼리만 보는 대화라 파일에 넣지 않습니다(room.chat_log에는 원래 없음).
        "chat": [e for e in room.chat_log if e.get("category") != "team"],
        "battles": [
            {"label": b["label"], "public_log": list(b.get("public_log") or []),
             "operator_log": list(b.get("operator_log") or []) if is_gm else [],
             "teams": b.get("teams") or {}}
            for b in battles
        ],
        "include_operator": is_gm,
    })


def _emit_fx_numbers(room):
    """새로 쌓인 공개 로그에서 '공격 수치 / 회복 / 방어 값 / 피해량'을 뽑아, 카드 위에 띄울 수치로 보냅니다.
    (되돌리기로 로그가 줄었거나 서버를 막 켠 경우에는 띄우지 않고 위치만 맞춥니다)"""
    battle = room.game.battle
    if battle is None:
        room._fx_log_idx = None
        return
    n = len(battle.public_log)
    idx = getattr(room, "_fx_log_idx", None)
    room._fx_log_idx = n
    if idx is None or idx >= n:
        return
    names = sorted((c.name for c in battle.team_a + battle.team_b), key=len, reverse=True)

    def name_at_start(text):
        return next((nm for nm in names if text.startswith(nm)), None)

    events, target = [], None
    for line in battle.public_log[idx:n]:
        tag, text = line.get("tag"), (line.get("text") or "").strip()
        if tag in ("action", "defend"):
            body = text.replace("[피해 정산]", "").strip()
            target = None
            if "→" in body:
                after = body.rsplit("→", 1)[1].strip()
                target = name_at_start(after)
            continue
        m = re.search(r"(공격 수치|피해량|회복|방어 값)\s*(\d+)", text)
        if not m or tag not in ("damage", "heal", "defend_value"):
            continue
        who = name_at_start(text) or target
        if not who:
            continue
        value = int(m.group(2))
        kind = {"공격 수치": "atk", "피해량": "atk", "회복": "heal", "방어 값": "def"}[m.group(1)]
        events.append({"target": who, "kind": kind, "value": -value if kind == "atk" else value})
    if events:
        socketio.emit("fx_numbers", events, room=room_channel(room.id, "all"))


# 상태 묶어 보내기 : 상태 한 번이 수십 KB(채팅 · 로그 포함)라서, 30명이 한꺼번에 들어오거나 행동이 몰리면
# 같은 상태를 수십 번 다시 보내게 됩니다. 짧은 시간(_BCAST_DELAY) 안에 생긴 변경은 마지막 상태 한 번으로 묶어 보냅니다.
_BCAST_DELAY = 0.15
_BCAST_PENDING = set()
_BCAST_LOCK = threading.Lock()


def broadcast_state(room):
    _emit_fx_numbers(room)
    mark_runtime_dirty()
    _mirror_round_logs(room)
    with _BCAST_LOCK:
        if room.id in _BCAST_PENDING:
            return
        _BCAST_PENDING.add(room.id)
    socketio.start_background_task(_flush_state, room)


def _flush_state(room):
    socketio.sleep(_BCAST_DELAY)
    _note_battle_end(room)
    with _BCAST_LOCK:
        _BCAST_PENDING.discard(room.id)
    try:
        socketio.emit("public_state", build_public_state(room), room=room_channel(room.id, "all"))
        socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))
    except Exception as e:
        print(f"[broadcast] room {room.id} error: {e}")


def _require_gm(sid):
    info = CONNECTIONS.get(sid)
    if info is None or info["role"] != "gm":
        return None
    return get_room(info["room_id"])


# ==================================================================
# 전투 일정 : 운영진이 전투 방에 날짜 · 시간과 배정 캐릭터를 등록하면, 러너는 일반 룸의 '전투' 메뉴에서
# 방을 골라 들어갑니다. 입장 가능 시간 = 시작 3시간 전 ~ 전투가 끝난 뒤 3시간.
# (끝내지 않은 채면 : 진행 중에는 계속 열려 있고, 시작도 안 했으면 시작 6시간 뒤에 닫혀요.)
# ==================================================================
BATTLE_OPEN_BEFORE = 3 * 3600
BATTLE_OPEN_AFTER = 3 * 3600
BATTLE_TYPES_SCHEDULED = ("pvp", "siege", "mass_raid")


def _note_battle_end(room):
    sc = room.schedule
    b = room.game.battle
    if sc and sc.get("start") and not sc.get("ended_at") and b is not None and b.finished:
        sc["ended_at"] = time.time()
        save_rooms()


def battle_window(room, now=None):
    """(열림 시각, 닫힘 시각, 상태) — 상태 : none(일정 없음) · upcoming · open · closed"""
    sc = room.schedule or {}
    start = sc.get("start")
    if not start:
        return None, None, "none"
    now = now or time.time()
    opens = start - BATTLE_OPEN_BEFORE
    b = room.game.battle
    if sc.get("ended_at"):
        closes = sc["ended_at"] + BATTLE_OPEN_AFTER
    elif b is not None and not b.finished:
        closes = max(now + 60, start + BATTLE_OPEN_AFTER)   # 진행 중이면 계속 열려 있어요
    else:
        closes = start + 2 * BATTLE_OPEN_AFTER
    state = "upcoming" if now < opens else "open" if now <= closes else "closed"
    return opens, closes, state


def battle_participants(room):
    """전투 참여자 : 진행 중(또는 끝난) 전투의 양 팀, 전투 전이면 운영진이 편성해 둔 팀."""
    b = room.game.battle
    if b is not None:
        return [c.name for c in list(b.team_a) + list(b.team_b)]
    pt = room.preview_teams or {}
    return list(pt.get("team_a") or []) + list(pt.get("team_b") or [])


def battle_watch_ok(room):
    """관전자 입장 허용(전투 설정의 체크박스 = 관전 탭)."""
    return bool((room.chat_tabs_enabled or {}).get("spectator"))


def _battle_card(room, me, is_gm):
    members = battle_participants(room)
    mine = bool(me and me in members)
    b = room.game.battle
    live = bool(b and not b.finished)
    watch = (not is_gm) and (not mine) and battle_watch_ok(room)
    card = {"id": room.id, "name": room.name, "type": room.battle_type, "type_label": BATTLE_TYPE_LABELS.get(room.battle_type, ""),
            "state": "live" if live else "done" if b is not None else "ready", "live": live, "count": len(members),
            "mine": mine, "watch": watch, "watch_ok": battle_watch_ok(room), "can_enter": is_gm or ((mine or watch) and not getattr(room, "hidden", False)),
            "hidden": bool(getattr(room, "hidden", False)),
            "thumb": getattr(room, "thumb", None) or (room.scene or {}).get("url") or (room.map_bg or {}).get("url") or None}
    if is_gm:
        card["url"] = url_for("guest_page", room_id=room.id, key=room.guest_key)
    return card


def _battle_list_payload(sid):
    """모든 친구에게 모든 전투 방이 보여요. 들어갈 수 있는 건 참여자(와 관전 허용 방의 관전자)."""
    info = CONNECTIONS.get(sid) or {}
    is_gm = _require_gm_or_guest_gm(sid) is not None
    me = (info.get("nickname") or "").strip()
    rooms = [r for r in list_rooms() if r.battle_type in BATTLE_TYPES_SCHEDULED]
    if not is_gm:
        rooms = [r for r in rooms if not getattr(r, "hidden", False)]   # 비공개 전투는 운영진에게만
    # 운영진이 끌어서 정한 순서(정하지 않은 방은 뒤에, 만든 순서대로)
    rooms.sort(key=lambda r: (getattr(r, "order", None) is None, getattr(r, "order", None) or 0, r.created_at or 0))
    cards = [_battle_card(r, me, is_gm) for r in rooms]
    return {"battles": cards, "is_gm": is_gm, "now": time.time()}


def room_roster_names():
    try:
        lounge = next((r for r in list_rooms() if r.battle_type == "lounge"), None)
        return lounge.game.db.all_names() if lounge else []
    except Exception:
        return []


@socketio.on("battle_list")
def on_battle_list(data=None):
    emit("battle_list", _battle_list_payload(request.sid))


@socketio.on("battle_enter")
def on_battle_enter(data):
    """러너 : 입장 가능 시간이고 배정된 캐릭터면 그 방 주소(키 포함)를 알려 줘요."""
    rid = str((data or {}).get("room_id") or "")
    room = get_room(rid)
    if room is None or room.battle_type not in BATTLE_TYPES_SCHEDULED:
        emit("battle_enter", {"ok": False, "message": "없는 전투예요."})
        return
    info = CONNECTIONS.get(request.sid) or {}
    is_gm = _require_gm_or_guest_gm(request.sid) is not None
    card = _battle_card(room, (info.get("nickname") or "").strip(), is_gm)
    if not card["can_enter"]:
        msg = "이 전투의 참여자만 들어갈 수 있어요."
        emit("battle_enter", {"ok": False, "message": msg})
        return
    url = url_for("guest_page", room_id=room.id, key=room.guest_key)
    watch = bool(card.get("watch"))
    emit("battle_enter", {"ok": True, "room_id": room.id, "url": url + ("&watch=1" if watch else ""), "watch": watch})


def _broadcast_battle_lists():
    for sid in list(CONNECTIONS.keys()):
        info = CONNECTIONS.get(sid) or {}
        r = get_room(info.get("room_id"))
        if r is not None and r.battle_type == "lounge":
            socketio.emit("battle_list", _battle_list_payload(sid), to=sid)


@socketio.on("battle_schedule_set")
def on_battle_schedule_set(data):
    """운영진 : 전투 날짜 · 시간과 배정 캐릭터. start는 epoch 초(비우면 일정 없음)."""
    if _require_gm_or_guest_gm(request.sid) is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    data = data or {}
    room = get_room(str(data.get("room_id") or ""))
    if room is None or room.battle_type not in BATTLE_TYPES_SCHEDULED:
        return
    try:
        start = float(data.get("start")) if data.get("start") not in (None, "") else None
    except (TypeError, ValueError):
        start = None
    names = [str(n)[:40] for n in (data.get("assigned") or []) if str(n).strip()][:60]
    old = room.schedule or {}
    room.schedule = {"start": start, "assigned": names,
                     "ended_at": old.get("ended_at") if old.get("start") == start else None} if start else None
    if "name" in data and str(data.get("name") or "").strip():
        room.name = str(data["name"]).strip()[:30]
    save_rooms()
    _broadcast_battle_lists()
    emit("battle_saved", {"ok": True})


@socketio.on("battle_room_create")
def on_battle_room_create(data):
    if _require_gm_or_guest_gm(request.sid) is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    data = data or {}
    bt = data.get("type") if data.get("type") in BATTLE_TYPES_SCHEDULED else "pvp"
    room = create_room(bt, name=str(data.get("name") or "").strip()[:30] or None)
    room.hidden = True   # 새 전투는 비공개로 만들어 두고, 준비가 끝나면 전투 설정에서 공개해요
    save_rooms()
    _broadcast_battle_lists()
    emit("battle_saved", {"ok": True, "room_id": room.id})


@socketio.on("battle_reorder")
def on_battle_reorder(data):
    """운영진 : 룸 목록 순서(끌어서 놓기)."""
    if _require_gm_or_guest_gm(request.sid) is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    ids = [str(x) for x in ((data or {}).get("ids") or [])][:500]
    for i, rid in enumerate(ids):
        r = get_room(rid)
        if r is not None and r.battle_type in BATTLE_TYPES_SCHEDULED:
            r.order = i
    save_rooms()
    _broadcast_battle_lists()


@socketio.on("battle_set_hidden")
def on_battle_set_hidden(data):
    """운영진 : 비공개 / 공개."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None or room.battle_type not in BATTLE_TYPES_SCHEDULED:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    room.hidden = bool((data or {}).get("hidden"))
    save_rooms()
    broadcast_state(room)
    _broadcast_battle_lists()


@socketio.on("battle_room_delete")
def on_battle_room_delete(data):
    if _require_gm_or_guest_gm(request.sid) is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    rid = str((data or {}).get("room_id") or "")
    room = get_room(rid)
    if room is None or room.battle_type not in BATTLE_TYPES_SCHEDULED:
        return
    delete_room(rid)
    _broadcast_battle_lists()


def _require_gm_or_guest_gm(sid):
    """운영진(gm_key) 접속뿐 아니라, 참가자 링크에서 닉네임 "GM" + 비밀번호로 전체 조작
    권한을 얻은 접속도 허용합니다. 비밀번호 검증은 on_join에서 이미 끝났으므로(그때만
    닉네임이 "gm"으로 저장됨) 여기서는 다시 검사하지 않습니다."""
    info = CONNECTIONS.get(sid)
    if info is None:
        return None
    if info["role"] == "gm":
        return get_room(info["room_id"])
    if info["role"] == "guest" and (info.get("nickname") or "").strip().lower() == "gm":
        return get_room(info["room_id"])
    return None


def resolve_control(room, info):
    """
    이 접속(info)이 전투 행동을 어디까지 조작할 수 있는지 판정합니다.
    - 운영진 링크로 들어온 경우 : 항상 전체 조작 가능("all")
    - 참가자 링크라도 닉네임을 "GM"으로 입력하면 : 전체 조작 가능("all")
      (단, 이 경우에도 운영진 로그/수식은 여전히 gm_state를 받는 소켓에만 전송되므로 노출되지 않습니다)
    - 닉네임이 현재 전투에 참여 중인 캐릭터 이름과 일치하면 : 그 캐릭터만 조작 가능("character")
    - 그 외 : 조작 불가, 관전만 가능("none")
    """
    if info["role"] == "gm":
        return {"scope": "all"}
    nickname = (info.get("nickname") or "").strip()
    if nickname.lower() == "gm":
        return {"scope": "all"}
    battle = room.game.battle
    if battle is not None:
        for c in battle.team_a + battle.team_b:
            if c.name == nickname:
                return {"scope": "character", "name": c.name}
    return {"scope": "none"}


ACTOR_FIELD = {
    "attack": "attacker",
    "self_defend": "name",
    "defend": "tanker",
    "guard": "tanker",
    "taunt": "tanker",
    "dodge": "name",
    "heal": "healer",
    "timeout": "name",
    "flee": "name",
    "defense_settle": "name",
    "move": "name",
    "command": "guardian",
    "swap": "medic",
    "collapse": "attacker",
    "emission": "attacker",
    "shield": "name",
    "polarize": "name",
    "reflux": "name",
    "restore": "name",
    "declare_defer": "name",
}


# ----------------------------------------------------------------------
# 소켓 이벤트 : 입장/퇴장/채팅
# ----------------------------------------------------------------------
@socketio.on("join")
def on_join(data):
    room_id = data.get("room_id", "")
    key = data.get("key", "")
    nickname = (data.get("nickname") or "익명").strip()[:20] or "익명"

    room = get_room(room_id)
    if room is None:
        emit("error", {"message": "존재하지 않는 방입니다."})
        return

    # 운영진 화면은 없앴습니다. 운영 권한은 참가자 링크에서 "GM" + 비밀번호로만 얻습니다
    # (gm_key는 방 목록 페이지에 노출될 수 있어 더 이상 권한을 주지 않습니다).
    if same_secret(key, room.guest_key):
        role = "guest"
    else:
        emit("error", {"message": "잘못된 접속 키입니다."})
        return

    # 참가자 링크로 닉네임을 "GM"으로 입력해 전체 조작 권한을 얻으려면 비밀번호가 맞아야 합니다.
    if role == "guest" and nickname.lower() == "gm":
        ip = client_ip()
        if too_many_fails(ip):
            emit("error", {"message": "비밀번호 시도가 너무 많아요. 10분 뒤에 다시 해 주세요."})
            return
        if data.get("gm_password") in (None, "") and (gm_pass_ok(data.get("gm_pass")) or is_admin()):
            pass   # 통행증으로 다시 들어옴 · 메인 페이지에 운영진으로 로그인한 브라우저
        elif not same_secret(data.get("gm_password"), GM_GUEST_PASSWORD):
            note_fail(ip)
            emit("error", {"message": "비밀번호가 올바르지 않습니다."})
            return

    # 전투 방 : 캐릭터로는 이 전투의 참여자만, 익명(관전)은 관전 허용일 때만. 운영진은 언제나.
    if room.battle_type in BATTLE_TYPES_SCHEDULED and nickname.lower() != "gm":
        if getattr(room, "hidden", False):
            emit("error", {"message": "아직 공개되지 않은 전투예요."})
            return
        if nickname == "익명":
            if not battle_watch_ok(room):
                # 로그아웃(익명으로 다시 입장)이면 이전 캐릭터 연결도 끊어 둬요 : 로그인 상태가 남지 않게
                prev = CONNECTIONS.pop(request.sid, None)
                if prev is not None:
                    leave_room(room_channel(room_id, "gm"))
                    leave_room(_team_channel(room.id, "A"))
                    leave_room(_team_channel(room.id, "B"))
                    broadcast_state(room)
                emit("error", {"message": "관전이 허용되지 않은 전투예요.", "quiet": True})
                return
        elif nickname not in battle_participants(room):
            emit("error", {"message": "이 전투의 참여자만 들어갈 수 있어요."})
            return

    # PLAY 룸(LOOP)은 공용 아이디 TEST(와 운영진)로만 들어옵니다. 기록은 기기마다 따로 저장돼요.
    if room.battle_type == "play" and nickname.lower() not in ("gm", "익명"):
        if nickname.upper() != loop_mod.TEST_ID:
            emit("error", {"message": "이 방은 TEST로만 입장할 수 있습니다."})
            return
        nickname = loop_mod.TEST_ID

    previous = CONNECTIONS.get(request.sid)
    previous_nickname = previous["nickname"] if previous else None

    CONNECTIONS[request.sid] = {"room_id": room_id, "role": role, "nickname": nickname,
                                "device": _clean_device(data.get("device")),
                                "loop_device": loop_mod.clean_device_id(data.get("loop_device"))}
    join_room(room_channel(room_id, "all"))
    # 참가자 링크에서 닉네임 "GM"으로 (비밀번호 인증까지 마치고) 입장한 경우도 운영진 로그/수식이
    # 필요하므로 gm 채널에 넣어줍니다. 다른 이름으로 재입장(로그아웃 포함)하면 다시 빠집니다.
    if role == "gm" or nickname.lower() == "gm":
        join_room(room_channel(room_id, "gm"))
    elif role == "guest":
        leave_room(room_channel(room_id, "gm"))
    _sync_team_channel(room, request.sid, nickname, role)

    # 입장/퇴장 알림은 쓰지 않으므로 채팅 기록에도 남기지 않습니다.

    joined = {"role": role, "room_id": room_id}
    if nickname.lower() == "gm":
        joined["gm_pass"] = _GM_PASS.dumps("gm")
    elif nickname == "익명" and is_admin():
        joined["admin"] = True   # 메인 페이지에 운영진으로 로그인한 브라우저 : 화면이 바로 운영진으로 들어와요
    if room.battle_type in BATTLE_TYPES_SCHEDULED:
        # 전투 방에서 '룸 목록'으로 돌아갈 주소(일반 룸 · 전투 화면)
        lounge = next((r for r in list_rooms() if r.battle_type == "lounge"), None)
        if lounge is not None:
            joined["lobby_url"] = url_for("guest_page", room_id=lounge.id, key=lounge.guest_key) + "&view=battles"
    emit("joined", joined)
    emit("notices", {"notices": notices_mod.shared_board().payload()})
    # 누가 로그인/로그아웃하면 유저 접속정보(초록 점)가 모든 접속자 화면에 같이 바뀌도록 방 전체에 다시 보냅니다.
    broadcast_state(room)


@socketio.on("disconnect")
def on_disconnect(*_reason):   # 새 Flask-SocketIO는 끊긴 이유를 넘겨줘요(받지 않으면 정리가 안 됐어요)
    info = CONNECTIONS.pop(request.sid, None)
    if info is None:
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    # 온라인 표시(유저 접속정보 팝업)가 끊기자마자 바로 반영되도록 상태를 다시 보냅니다.
    broadcast_state(room)


@socketio.on("chat_message")
def on_chat_message(data):
    info = CONNECTIONS.get(request.sid)
    if info is None:
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    text = (data.get("text") or "").strip()
    if not text:
        return
    control = resolve_control(room, info)
    if control["scope"] != "all" and _chat_flood(request.sid):   # 운영진은 제한 없음
        emit("action_error", {"message": "채팅을 너무 빨리 보내고 있어요. 잠시 뒤에 다시 보내 주세요."})
        return
    category = {"all": "operator", "character": "player", "none": "spectator"}[control["scope"]]
    nickname = info["nickname"]
    role = info["role"]

    # GM(scope "all")이 다른 캐릭터를 대신 조작해 행동을 알릴 때는, 로그에 "GM"이 아니라
    # 실제로 행동한 캐릭터의 이름/색으로 표시되도록 as_character를 검증 후 신원을 덮어씁니다.
    # 조작 권한이 없는 캐릭터 이름으로 스푸핑하지 못하도록, scope가 그 캐릭터를 실제로
    # 조작할 수 있는 경우에만(all, 또는 본인 캐릭터) 허용합니다.
    as_character = (data.get("as_character") or "").strip()
    if as_character and control["scope"] in ("all", "character"):
        if control["scope"] == "character" and control["name"] != as_character:
            as_character = ""
        else:
            battle = room.game.battle
            live = battle.find_character(as_character) if battle is not None else None
            if live is None:
                as_character = ""
    else:
        as_character = ""

    if as_character:
        nickname = as_character
        role = "guest"
        category = "player"

    # 아군 회의 : "우리 팀만" 보이는 채팅입니다. 보내는 사람(또는 GM이 as_character로 대신
    # 보내는 경우 그 캐릭터)이 실제로 소속된 팀에만 전달합니다 - GM은 양 팀 회의 채널에
    # 모두 들어가 있으므로(_sync_team_channel) 별도로 GM 채널에 다시 보낼 필요가 없습니다.
    if data.get("mode") == "team":
        battle = room.game.battle
        speaker_name = as_character or (nickname if control["scope"] == "character" else None)
        speaker = battle.find_character(speaker_name) if battle is not None and speaker_name else None
        if speaker is None:
            emit("action_error", {"message": "아군 회의는 소속 팀이 있는 캐릭터만 보낼 수 있습니다."})
            return
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "nickname": nickname,
            "role": role,
            "category": "team",
            "team": speaker.team,
            "text": text[:500],
        }
        # 주의 : room.chat_log(공용 채팅 기록)에는 남기지 않습니다 - public_state의 "chat"
        # 필드는 방 전체에 그대로 재전송되는 공용 스냅샷이라, 여기에 남기면 재접속/새로고침
        # 시 상대 팀의 아군 회의 내용까지 함께 전송돼 버립니다(팀 채널로만 실시간 전달).
        _with_chat_id(entry)
        team_log = getattr(room, "team_chat_log", None)
        if team_log is None:
            team_log = room.team_chat_log = []
        team_log.append(entry)
        del team_log[:-2000]
        mark_runtime_dirty()
        socketio.emit("chat_message", entry, room=_team_channel(info["room_id"], speaker.team))
        return

    # 전투 관전 탭에서 보내면, 실제 역할(운영진/참가자)과 무관하게 지금 보고 있는 탭에
    # 그대로 표시되도록 카테고리를 관전으로 맞춰줍니다.
    if data.get("mode") == "spectator":
        category = "spectator"

    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": nickname,
        "role": role,
        "category": category,
        "text": text[:500],
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(info["room_id"], "all"))


@socketio.on("set_userinfo_hidden")
def on_set_userinfo_hidden(data):
    """운영진(비밀번호 입장 GM 포함)이 유저 접속정보 목록에서 특정 캐릭터를 GM이 아닌 사람에게
    숨기거나(눈 끄기) 다시 보이게(눈 켜기) 합니다. 방 설정으로 저장되어 서버를 재시작해도 유지됩니다."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()
    if not name:
        return
    hidden = set(room.userinfo_hidden)
    if data.get("hidden"):
        hidden.add(name)
    else:
        hidden.discard(name)
    room.userinfo_hidden = sorted(hidden)
    save_rooms()
    broadcast_state(room)


@socketio.on("set_chat_tabs")
def on_set_chat_tabs(data):
    """운영진(비밀번호 입장 GM 포함)이 참가자 화면 채팅창에 보여줄 탭과 그 이름을 고릅니다."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    values = data.get("tabs", {})
    for key in ("player", "spectator", "entry", "team"):
        if key in values:
            room.chat_tabs_enabled[key] = bool(values[key])
    if "spectator" in values and room.battle_type in BATTLE_TYPES_SCHEDULED:
        _broadcast_battle_lists()   # 관전 허용이 바뀌면 룸 목록도
    labels = data.get("labels", {})
    for key in ("player", "spectator", "entry", "team"):
        if key in labels:
            label = (labels[key] or "").strip()[:20]
            if label:  # 빈 이름은 무시(기존 이름 유지) - 탭에 아무 글자도 없으면 안 되므로
                room.chat_tab_labels[key] = label
    save_rooms()
    broadcast_state(room)


def _mypage_target_name(room, info, data):
    """마이페이지 수정 대상 캐릭터 이름. GM(운영진/비밀번호 입장)은 data["name"]으로 지정한 아무
    캐릭터나 수정할 수 있고, 일반 참가자는 본인(로그인한 캐릭터)만 수정할 수 있습니다."""
    wanted = (data.get("name") or "").strip()
    if wanted and _require_gm_or_guest_gm(request.sid) is not None and room.game.db.exists(wanted):
        return wanted
    control = resolve_control(room, info)
    if control["scope"] == "character":
        return control["name"]
    # 전투에 참여하지 않았어도, 등록된 캐릭터 이름으로 로그인했으면 본인 마이페이지는 수정할 수 있습니다.
    nickname = (info.get("nickname") or "").strip()
    if nickname and nickname != "익명" and room.game.db.exists(nickname):
        return nickname
    return None


@socketio.on("set_my_color")
def on_set_my_color(data):
    """참가자가 자신의 캐릭터 색상(아바타 동그라미/카드/채팅에 쓰이는 구분색)을 직접 지정합니다.
    본인 닉네임이 현재 전투에 참여 중인 캐릭터 이름과 일치할 때만 그 캐릭터의 색상을 바꿀 수 있습니다."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "로그인한 뒤에 색상을 바꿀 수 있습니다."})
        return
    color = (data.get("color") or "").strip()
    if not _HEX_COLOR_RE.match(color):
        emit("action_error", {"message": "색상 형식이 올바르지 않습니다."})
        return
    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=color, skill=existing.get("skill"),
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.color = color
    broadcast_state(room)


@socketio.on("set_my_raid_display_name")
def on_set_my_raid_display_name(data):
    """참가자가 마스 레이드 카드 등에 쓰일 자신의 짧은 표기 이름을 직접 지정합니다(마이페이지)."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "로그인한 뒤에 표기 이름을 바꿀 수 있습니다."})
        return
    raid_display_name = (data.get("raid_display_name") or "").strip()[:3] or None
    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=existing.get("color"), skill=existing.get("skill"),
        raid_display_name=raid_display_name, inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.raid_display_name = raid_display_name
    broadcast_state(room)


@socketio.on("set_my_sound_effect_volume")
def on_set_my_sound_effect_volume(data):
    """참가자가 자신의 효과음 재생 음량(0~100)을 지정합니다(마이페이지). 효과음 파일 자체는
    /upload_sound_effect로 올립니다 - 효과음마다 원본 음량이 제각각이라 따로 조절합니다."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "로그인한 뒤에 음량을 조절할 수 있습니다."})
        return
    try:
        volume = int(data.get("sound_effect_volume"))
    except (TypeError, ValueError):
        volume = 100
    volume = max(0, min(100, volume))
    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=existing.get("color"), skill=existing.get("skill"),
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
        avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
        sound_effect_volume=volume,
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.sound_effect_volume = volume
    broadcast_state(room)


@socketio.on("set_my_skill_log")
def on_set_my_skill_log(data):
    """참가자가 자신의 스킬 이펙트(스킬을 쓸 때 화면 중앙에 뜨는 컷인)를 지정합니다(마이페이지).
    글 : 제목(일반 글자) + 본문(굵게/기울임만 허용하는 HTML), 이미지 : png/apng/gif/webp 업로드."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    data = data or {}
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "로그인한 뒤에 설정할 수 있습니다."})
        return
    entry = room.game.db.get(name)
    if entry is None:
        return
    if data.get("skill_log_type") in ("text", "image"):
        entry["skill_log_type"] = data["skill_log_type"]
    if "skill_log_title" in data:
        title = (data.get("skill_log_title") or "").strip()[:SKILL_LOG_TITLE_MAX]
        if title:
            entry["skill_log_title"] = title
        else:
            entry.pop("skill_log_title", None)
    if "skill_log_text" in data:
        body = notices_mod.sanitize_html(data.get("skill_log_text") or "", SKILL_LOG_TAGS, 4000)
        if len(notices_mod.plain_text(body)) > SKILL_LOG_BODY_MAX:
            emit("action_error", {"message": f"본문은 {SKILL_LOG_BODY_MAX}자까지 쓸 수 있습니다."})
            return
        if notices_mod.plain_text(body).strip():
            entry["skill_log_text"] = body
        else:
            entry.pop("skill_log_text", None)
    if "catchphrase" in data:
        phrase = " ".join((data.get("catchphrase") or "").split())[:CATCHPHRASE_MAX]
        if phrase:
            entry["catchphrase"] = phrase
        else:
            entry.pop("catchphrase", None)
    if data.get("cutin_motion") in CUTIN_MOTIONS:
        entry["cutin_motion"] = data["cutin_motion"]
    # 2차 진영 : 본인도 고를 수 있어요(使徒 / Void / 미정)
    if "nation" in data:
        nation = (data.get("nation") or "").strip()
        if nation in NATIONS:
            entry["nation"] = nation
        elif not nation:
            entry.pop("nation", None)
    # 나이 : 운영진만 정할 수 있어요(1차 기준 13~16세). 참가자가 보낸 값은 무시합니다.
    if "age" in data and _require_gm_or_guest_gm(request.sid) is not None:
        age = mailbox_mod.clean_age(data.get("age"))
        if age is not None:
            entry["age"] = age
    # 출신지 : 맵의 '장소id:구역번호(0~3)' (맵 구역 카드를 누르면 '00의 출신지.'로 나옵니다)
    if "hometown" in data:
        home = (data.get("hometown") or "").strip()
        if home and re.fullmatch(r"[A-Za-z0-9_-]{1,16}:[0-3]", home):
            entry["hometown"] = home
        elif not home:
            entry.pop("hometown", None)
    if data.get("clear_image"):
        entry.pop("skill_log_image", None)
    blob = data.get("image_data")
    if blob is not None:
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in SKILL_LOG_IMAGE_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png(apng)/gif/webp 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > SKILL_LOG_IMAGE_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {SKILL_LOG_IMAGE_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(SKILL_LOG_DIR, filename), "wb") as f:
            f.write(blob)
        entry["skill_log_image"] = url_for("static", filename=f"skill_fx/{filename}")
        entry["skill_log_type"] = "image"
    room.game.db.save()
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.skill_log_type = entry.get("skill_log_type") or "text"
            live.skill_log_text = entry.get("skill_log_text") or ""
    if "age" in data:
        _emit_mail_data(request.sid)  # 편지 쓰기의 나이 안내도 바로 바뀌게
    _broadcast_all_rooms()


@socketio.on("change_position")
def on_change_position(data):
    """마이페이지 포지션 변경 : '포지션 변경권'(효과 role_change)을 1개 차감하고 포지션을 바꿉니다.
    변경권이 없으면 바꿀 수 없고, 전투에 참여 중일 때는 바꿀 수 없습니다(전투 전 전용).
    운영진(GM)은 변경권 없이 바로 바꿀 수 있습니다. 바뀐 포지션에서 쓸 수 없는 스킬은 해제됩니다."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    data = data or {}
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "로그인한 뒤에 포지션을 바꿀 수 있습니다."})
        return
    db = room.game.db
    entry = db.get(name)
    new_role = data.get("role")
    if entry is None or new_role not in config.ROLES:
        emit("action_error", {"message": "알 수 없는 포지션입니다."})
        return
    old_role = entry.get("role", config.DEFAULT_ROLE)
    if new_role == old_role:
        return
    if _live_battle_char(room, name) is not None:
        emit("action_error", {"message": "전투 중에는 포지션을 바꿀 수 없습니다."})
        return
    is_gm = _require_gm_or_guest_gm(request.sid) is not None
    shop = shop_mod.shared_shop()
    held = shop_mod.get_items(db, name)
    ticket = next((it for it in shop.items if it["effect"] == "role_change" and held.get(it["id"], 0) > 0), None)
    if ticket is None and not is_gm:
        emit("action_error", {"message": "포지션 변경권이 없습니다. 상점에서 구매한 뒤에 바꿀 수 있습니다."})
        return
    entry["role"] = new_role
    skill_note = ""
    if entry.get("skill") and entry["skill"] not in config.SKILL_OPTIONS.get(new_role, []):
        entry.pop("skill", None)
        skill_note = " (스킬은 해제되었습니다)"
    db.save()
    if ticket is not None:
        shop_mod.change_item_count(db, name, ticket["id"], -1)
        post_system_chat(room, f"{name} : {ticket['name']} 사용 → 포지션 {old_role} → {new_role}{skill_note}")
        emit("shop_result", {"message": f"포지션을 {new_role}(으)로 바꿨습니다. ({ticket['name']} -1){skill_note}"})
    else:
        post_system_chat(room, f"운영진이 {name}의 포지션을 {old_role} → {new_role}(으)로 바꿨습니다.{skill_note}")
        emit("shop_result", {"message": f"포지션을 {new_role}(으)로 바꿨습니다.{skill_note}"})
    _broadcast_all_rooms()


@socketio.on("set_mypage_gm_fields")
def on_set_mypage_gm_fields(data):
    """운영진이 마이페이지 팝업에서 캐릭터의 체력/소지품을 직접 수정합니다. 체력은 전투 중
    live 캐릭터에만 적용되고(스탯 기반 자동계산과 무관), 소지품은 등록 DB에도 저장되어
    다음 전투로 이어집니다. 참가자 링크에서 닉네임 "GM"+비밀번호로 들어온 경우에도 허용합니다
    (마이페이지는 참가자 화면에서만 열리므로, 실제 운영진 화면 접속에만 쓰는 _require_gm으로는
    항상 거부되어 버립니다)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()
    battle = room.game.battle
    live = battle.find_character(name) if battle is not None else None
    if live is None and not room.game.db.exists(name):
        emit("action_error", {"message": "존재하지 않는 캐릭터입니다."})
        return
    # 전투에 없는 캐릭터(유저 접속정보에서 연 마이페이지)는 체력이 없으므로 소지품만 저장합니다.
    if live is not None and "current_hp" in data:
        try:
            hp = int(data.get("current_hp"))
        except (TypeError, ValueError):
            hp = live.current_hp
        live.current_hp = max(0, min(hp, live.max_hp))
    if "inventory" in data:
        inventory = (data.get("inventory") or "").strip()[:200]
        if live is not None:
            live.inventory = inventory
        existing = room.game.db.get(name) or {}
        room.game.db.add_or_update(
            name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
            color=existing.get("color"), skill=existing.get("skill"),
            raid_display_name=existing.get("raid_display_name"), inventory=inventory,
            skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
        )
    # 2차 진영 : 使徒 / Void / 미정
    if "nation" in data:
        nation = (data.get("nation") or "").strip()
        if nation in NATIONS or nation == "":
            entry = room.game.db.get(name)
            if entry is not None:
                if nation:
                    entry["nation"] = nation
                else:
                    entry.pop("nation", None)
                room.game.db.save()
    broadcast_state(room)


@socketio.on("set_chat_limit")
def on_set_chat_limit(data):
    """운영진 : 채팅 도배 방지 기준(끄기 / n초에 m번)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    k = str((data or {}).get("limit") or "off")
    if k not in CHAT_LIMITS:
        return
    SITE_SETTINGS["chat_limit"] = k
    safeio.write_json(SITE_SETTINGS_PATH, SITE_SETTINGS, indent=1)
    for r in list_rooms():
        broadcast_state(r)


@socketio.on("set_remind_seconds")
def on_set_remind_seconds(data):
    """운영진 : 미행동자 안내 시점(라운드 제한시간이 몇 초 남았을 때)을 정합니다. 0 = 끄기."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    try:
        sec = int((data or {}).get("seconds"))
    except (TypeError, ValueError):
        return
    if sec not in REMIND_CHOICES:
        return
    SITE_SETTINGS["remind_seconds"] = sec
    safeio.write_json(SITE_SETTINGS_PATH, SITE_SETTINGS, indent=1)
    for r in list_rooms():
        broadcast_state(r)


@socketio.on("set_point_theme")
def on_set_point_theme(data):
    """운영진 : 포인트 컬러를 바꾸면 모든 방의 모든 접속자 화면에 바로 적용됩니다."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    theme = (data or {}).get("theme")
    if theme not in POINT_THEMES:
        return
    SITE_SETTINGS["point_theme"] = theme
    safeio.write_json(SITE_SETTINGS_PATH, SITE_SETTINGS, indent=1)
    for r in list_rooms():
        broadcast_state(r)


# ----------------------------------------------------------------------
# 소켓 이벤트 : 운영진 전용 행동
# ----------------------------------------------------------------------
@socketio.on("register_characters")
def on_register_characters(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("register_result", {"registered": [], "errors": ["방에 아직 입장하지 않았습니다. 먼저 입장해주세요."]})
        return
    text = data.get("text", "")
    if not text.strip():
        emit("register_result", {"registered": [], "errors": ["등록할 텍스트를 입력해주세요."]})
        return
    registered, errors = room.game.db.parse_bulk_text(text)
    if not registered and not errors:
        errors = ["형식을 인식하지 못했습니다. 이름 줄과 스탯 줄 형식을 확인해주세요."]
    emit("register_result", {"registered": registered, "errors": errors})
    broadcast_state(room)


@socketio.on("generate_dummies")
def on_generate_dummies(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("register_result", {"registered": [], "errors": ["방에 아직 입장하지 않았습니다. 먼저 입장해주세요."]})
        return
    try:
        count = int(data.get("count", 6))
    except (TypeError, ValueError):
        count = 6
    count = max(1, min(count, 100))
    created = room.game.db.generate_dummy_characters(count)
    emit("register_result", {"registered": created, "errors": []})
    broadcast_state(room)


@socketio.on("update_character")
def on_update_character(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()
    if not name or not room.game.db.exists(name):
        emit("action_error", {"message": "존재하지 않는 캐릭터입니다."})
        return
    role = data.get("role") or config.DEFAULT_ROLE
    stats = data.get("stats", {})
    skill = data.get("skill") or None
    existing = room.game.db.get(name) or {}
    warns = room.game.db.add_or_update(
        name, role, stats, color=existing.get("color"), skill=skill,
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
    )
    # 나이 : 1차 입학(空歷 514年) 때 나이(13~16세). 범위 밖이면 기본값(13세)으로 되돌립니다.
    if "age" in data:
        entry = room.game.db.get(name)
        age = mailbox_mod.clean_age(data.get("age"))
        if age is not None:
            entry["age"] = age
        else:
            entry.pop("age", None)
        room.game.db.save()
    if "nation" in data and ((data.get("nation") or "").strip() in NATIONS or not (data.get("nation") or "").strip()):
        entry = room.game.db.get(name)
        nation = (data.get("nation") or "").strip()
        if nation:
            entry["nation"] = nation
        else:
            entry.pop("nation", None)
        room.game.db.save()

    # 전투가 진행 중이고 이 캐릭터가 현재 전투에 참여 중이라면, 실시간 스탯도 즉시 갱신합니다.
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            clamped, _ = config.clamp_stats(stats)
            live.stats = clamped
            new_max_hp = config.calculate_max_hp(clamped, overrides=battle.formula_overrides)
            live.max_hp = new_max_hp
            live.current_hp = min(live.current_hp, new_max_hp)

    emit("register_result", {"registered": [name], "errors": warns})
    broadcast_state(room)


@socketio.on("delete_character")
def on_delete_character(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()
    room.game.db.delete(name)
    broadcast_state(room)


def _formula_fields_payload(battle_type: str = "pvp"):
    profile_overrides = config.load_profile_overrides(battle_type)
    payload = []
    for f in config.FORMULA_FIELDS:
        entry = {
            "key": f["key"],
            "label": f["label"],
            "desc": f["desc"],
            "type": "float" if f["type"] is float else "int",
            "category": f.get("category", "common"),
            "value": profile_overrides.get(f["key"], config.get_formula_value(f["key"])),
        }
        if "step" in f:
            entry["step"] = f["step"]
        if "widget" in f:
            entry["widget"] = f["widget"]
        if "options" in f:
            entry["options"] = f["options"]
        payload.append(entry)
    return payload


@socketio.on("get_formulas")
def on_get_formulas(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 전투 수식을 열람할 수 있습니다."})
        return
    emit("formulas", {
        "battle_type": room.battle_type,
        "fields": _formula_fields_payload(room.battle_type),
        "categories": config.FORMULA_CATEGORIES,
    })


@socketio.on("save_formulas")
def on_save_formulas(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 전투 수식을 수정할 수 있습니다."})
        return
    values = data.get("values", {})
    if room.battle_type == "pvp":
        config.save_formula_overrides(values)
    else:
        config.save_profile_overrides(room.battle_type, values)
    label = BATTLE_TYPE_LABELS.get(room.battle_type, room.battle_type)
    emit("formulas_saved", {"message": f"{label} 전용 수식으로 저장되었습니다."})
    emit("formulas", {
        "battle_type": room.battle_type,
        "fields": _formula_fields_payload(room.battle_type),
        "categories": config.FORMULA_CATEGORIES,
    })


@app.route("/health")
def health():
    return "ok"


def _find_empty_2x2_anchor(width, height, occupied, near):
    """width×height 격자에서 2x2로 통째로 비어있는 자리의 북서(anchor) 좌표를 찾습니다.
    near에 가장 가까운 자리를 우선합니다. 그런 자리가 전혀 없으면 None."""
    candidates = []
    for x in range(width - 1):
        for y in range(height - 1):
            block = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
            if block & occupied:
                continue
            candidates.append((x, y))
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a[0] + 0.5 - near[0]) ** 2 + (a[1] + 0.5 - near[1]) ** 2)
    return candidates[0]


def assign_mass_raid_positions(battle, width, height):
    """몹(2팀)은 격자 중앙 부근에 뭉쳐서, 러너(1팀)는 나머지 칸에 무작위로 배치합니다.
    "BOSS"(4부위, boss_group이 같은 캐릭터들)는 2x2 한 덩이로 중앙 부근에 먼저 배치됩니다."""
    cells = [(x, y) for x in range(width) for y in range(height)]
    center = ((width - 1) / 2, (height - 1) / 2)
    cells.sort(key=lambda c: (c[0] - center[0]) ** 2 + (c[1] - center[1]) ** 2)

    used = set()
    all_members = battle.team_a + battle.team_b

    seen_groups = set()
    for c in all_members:
        if not c.boss_group or c.boss_group in seen_groups:
            continue
        seen_groups.add(c.boss_group)
        anchor = _find_empty_2x2_anchor(width, height, used, near=center)
        if anchor is None:
            continue  # 격자가 너무 작아 2x2 자리가 없으면 건너뜁니다(개별 배치로는 넘기지 않음).
        for member in all_members:
            if member.boss_group != c.boss_group:
                continue
            ox, oy = config.BOSS_SECTION_OFFSETS.get(member.boss_section, (0, 0))
            pos = (anchor[0] + ox, anchor[1] + oy)
            member.grid_pos = pos
            used.add(pos)

    for c in battle.team_b:
        if c.boss_group:
            continue
        pos = next(cell for cell in cells if cell not in used)
        c.grid_pos = pos
        used.add(pos)

    remaining = [c for c in cells if c not in used]
    random.shuffle(remaining)
    idx = 0
    for c in battle.team_a:
        if c.boss_group:
            continue
        c.grid_pos = remaining[idx]
        idx += 1


@socketio.on("preview_teams")
def on_preview_teams(data):
    """전투 시작 전 "무작위 배치"를 누르면, 실제로 전투를 시작하지 않고도 배정된 팀을
    참가자 화면에 카드로 미리 보여줍니다."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    if room.battle_type in ("lounge", "play"):
        emit("action_error", {"message": "일반 룸 · PLAY 룸에서는 전투를 할 수 없어요."})
        return
    room.preview_teams = {
        "team_a": data.get("team_a", []),
        "team_b": data.get("team_b", []),
    }
    broadcast_state(room)
    _broadcast_battle_lists()   # 편성된 참여자가 룸 목록에서 바로 입장할 수 있게


def _apply_action_counts(room):
    """PVP 한정 : 운영진이 정한 캐릭터별 한 차례 행동 횟수(NPC 등)를 전투 캐릭터에 적용해요."""
    b = room.game.battle
    if b is None or room.battle_type != "pvp":
        return
    counts = getattr(room, "action_counts", None) or {}
    for c in list(b.team_a) + list(b.team_b):
        n = int(counts.get(c.name, 1) or 1)
        c.actions_per_turn = max(1, min(ACTION_COUNT_MAX, n))
        if c._acts_used is not None and c._acts_used > c.actions_per_turn:
            c._acts_used = c.actions_per_turn


ACTION_COUNT_MAX = 5


@socketio.on("set_action_count")
def on_set_action_count(data):
    """운영진 · PVP : 캐릭터 한 명의 한 차례 행동 횟수(1~5). 진행 중인 전투에도 바로 적용돼요."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None or room.battle_type != "pvp":
        emit("action_error", {"message": "PVP 전투 방에서 운영진만 바꿀 수 있어요."})
        return
    data = data or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return
    try:
        n = max(1, min(ACTION_COUNT_MAX, int(data.get("count") or 1)))
    except (TypeError, ValueError):
        n = 1
    counts = dict(getattr(room, "action_counts", None) or {})
    if n == 1:
        counts.pop(name, None)
    else:
        counts[name] = n
    room.action_counts = counts
    _apply_action_counts(room)
    save_rooms()
    broadcast_state(room)


def _apply_battle_rules(room, formula_overrides, grid_width, grid_height):
    """전투가 막 만들어진 직후, 전투 유형별 행동 목록 · 격자 배치 · 방 상태 초기화를 적용합니다
    (전투 시작과 모의전투 데모 방 만들기가 함께 씁니다)."""
    is_grid_battle = grid_width is not None
    # 공성전 거점 / 마스 레이드 적군(2팀) : 방어가 자동이라 역할과 무관하게 "방어 정산"/"공격"/"힐"만
    # 직접 선택합니다. 포지션이 없으므로 공격/힐 모두 치명타가 발생할 수 있습니다.
    if room.battle_type in ("siege", "mass_raid"):
        for c in room.game.battle.team_b:
            c.forced_actions = [config.ACTION_DEFENSE_SETTLE, config.ACTION_ATTACK, config.ACTION_HEAL]
            c.role = None

    # 마스 레이드 러너(1팀) : 같은 역할(가디언/스트라이커/메딕)이라도 마스 레이드에서는
    # 행동 목록이 다릅니다 (MASS_RAID_ROLE_ACTIONS). 이름/명칭은 다른 전투 유형과 공유하되
    # 행동만 마스 레이드 전용으로 덮어씁니다. 캐릭터가 선택한 스킬(붕괴/방출/차폐/편광/환류/복원)이
    # 있으면 "스킬" 버튼 대신 그 스킬 고유 이름으로 행동 목록에 추가됩니다.
    if room.battle_type == "mass_raid":
        for c in room.game.battle.team_a:
            base_actions = config.MASS_RAID_ROLE_ACTIONS.get(c.role, [])
            skill_actions = [c.skill] if c.skill else []
            c.forced_actions = base_actions + skill_actions + config.COMMON_ACTIONS
            # 차폐(가디언) 스킬을 선택한 캐릭터는 마스 레이드 전투 시작 시에만 영구 보호막을 자동으로 얻습니다.
            if c.skill == config.SKILL_SHIELD:
                c.shield_permanent = config.get_value("SKILL_SHIELD_INITIAL", formula_overrides)

    # PVP/공성전 가디언 : 어그로 강제 행동을 마스 레이드의 '지휘'와 같은 이름으로 통일합니다
    # (기존 '공격유도'는 본인 지정 시 능동 방어가 함께 붙는 차이만 있을 뿐 같은 어그로 강제
    # 메커닉이라, 웹 버전에서는 이름과 동작을 '지휘'(CommandSkill) 하나로 합칩니다).
    # 레거시 데스크톱 버전(gui.py)은 이 오버라이드를 거치지 않으므로 기존 '공격유도' 그대로입니다.
    if room.battle_type != "mass_raid":
        for c in room.game.battle.team_a + room.game.battle.team_b:
            if c.role == config.ROLE_TANKER:
                c.forced_actions = [
                    config.ACTION_ATTACK, config.ACTION_GUARD, config.ACTION_DEFEND, config.ACTION_COMMAND,
                ] + config.COMMON_ACTIONS

    # 격자 전투(마스 레이드/공성전) : 중앙에 몹(거점)을 두고 러너를 나머지 칸에 무작위 배치, 전원 이동 가능.
    if is_grid_battle:
        assign_mass_raid_positions(room.game.battle, grid_width, grid_height)
        for c in room.game.battle.team_a + room.game.battle.team_b:
            c.can_move = True

    room.site_dice_round_no = None
    room.site_dice_value = None
    room.site_dice_used = 0
    room.pending_reveal = None
    room.telegraph_cells = []
    room.telegraph_round_no = None
    room.telegraph_damage_round_no = None
    room.preview_teams = None


@socketio.on("start_battle")
def on_start_battle(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    if room.battle_type in ("lounge", "play"):
        emit("action_error", {"message": "일반 룸 · PLAY 룸에서는 전투를 할 수 없어요."})
        return
    # 공성전 · 마스 레이드는 러너 팀(1팀)이 항상 선공입니다(마스 레이드 전조 피해도 이 순서를 전제로 합니다).
    forced_first_team = Battle.TEAM_A if room.battle_type in ("siege", "mass_raid") else None
    formula_overrides = config.load_profile_overrides(room.battle_type)
    site_auto_defense = room.battle_type in ("siege", "mass_raid")
    grid_size = GRID_SIZES.get(room.battle_type)
    is_grid_battle = grid_size is not None
    grid_width = grid_size
    grid_height = grid_size

    team_a = data.get("team_a", [])
    team_b = data.get("team_b", [])
    if is_grid_battle and len(team_a) + len(team_b) > grid_width * grid_height:
        emit("action_error", {"message": f"격자 칸({grid_width}×{grid_height})보다 인원이 많습니다."})
        return

    _archive_battle_logs(room)
    try:
        room.game.start_battle(
            team_a, team_b,
            forced_first_team=forced_first_team,
            formula_overrides=formula_overrides,
            site_auto_defense=site_auto_defense,
            grid_width=grid_width, grid_height=grid_height,
            alternate_first_team=(room.battle_type == "pvp"),
        )
    except BattleError as e:
        emit("action_error", {"message": str(e)})
        return
    if room.game.battle is not None:
        room.game.battle._started_label = config.et_stamp()

    # 전투가 방금 막 만들어져서 팀이 정해졌으므로, 이미 접속해 있던 소켓들의 아군 회의
    # 채널 소속도 다시 계산해줍니다(전투 시작 전에는 팀이 없어서 못 넣었을 것이므로).
    for sid, info in CONNECTIONS.items():
        if info.get("room_id") == room.id:
            _sync_team_channel(room, sid, info.get("nickname"), info.get("role"))

    _apply_battle_rules(room, formula_overrides, grid_width, grid_height)
    _apply_action_counts(room)

    # 선후공은 이미 결정됐지만(room.game.start_battle 내부), 화면에는 "다이스 굴리는 중"
    # 서스펜스를 잠깐 보여준 뒤에 결과와 함께 라운드 제한시간을 시작시킵니다.
    socketio.emit("battle_starting", {}, room=room_channel(room.id, "all"))
    socketio.sleep(1.5)

    first_team_label = _first_team_display_name(room, room.game.battle)
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "GM",
        "role": "gm",
        "category": "operator",
        "text": f"전투가 시작됩니다. 선공 팀은 {first_team_label}입니다.\n제한시간 내 행동해 주세요.",
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))

    broadcast_state(room)


@socketio.on("roll_site_dice")
def on_roll_site_dice(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    battle = room.game.battle
    if battle is None:
        emit("action_error", {"message": "전투가 시작되지 않았습니다."})
        return
    if room.battle_type != "siege":
        emit("action_error", {"message": "공성전 방에서만 사용할 수 있습니다."})
        return
    value = random.randint(1, 3)
    room.site_dice_round_no = battle.round_no
    room.site_dice_value = value
    room.site_dice_used = 0
    text = f"전조 : 이번 라운드 거점과 {value}회 대치합니다."
    battle.log_event(text, tag="system")
    post_system_chat(room, text, nickname="전조")
    broadcast_state(room)


@socketio.on("telegraph_reveal")
def on_telegraph_reveal(data):
    """
    마스 레이드 전용 : GM이 '전조 출력'으로 찍어둔 격자 칸을 러너에게 공개합니다.
    공개된 칸은 모두의 화면에서 밝게 표시되며, 곧 그 칸에 무조건 피해가 발생한다는
    시각적 경고일 뿐입니다. 실제 피해 판정(공격 행동)은 별도로 이루어집니다.
    """
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    battle = room.game.battle
    if battle is None or battle.grid_width is None:
        emit("action_error", {"message": "격자 전투(공성전/마스 레이드)에서만 사용할 수 있습니다."})
        return
    cells = []
    for cell in data.get("cells", []):
        try:
            x, y = int(cell[0]), int(cell[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= x < battle.grid_width and 0 <= y < battle.grid_height:
            cells.append([x, y])
    room.telegraph_cells = cells
    room.telegraph_round_no = battle.round_no
    text = f"전조 공개 : {len(cells)}칸에 곧 재해가 발생합니다." if cells else "전조 공개 : 이번 라운드는 재해 구역이 없습니다."
    battle.log_event(text, tag="system")
    post_system_chat(room, text, nickname="전조")
    broadcast_state(room)


@socketio.on("telegraph_clear")
def on_telegraph_clear(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    room.telegraph_cells = []
    broadcast_state(room)


@socketio.on("set_room_name")
def on_set_room_name(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()[:30]
    room.name = name or room.id
    save_rooms()
    broadcast_state(room)


@socketio.on("set_music")
def on_set_music(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    music_type = data.get("type")
    if music_type == "youtube":
        video_id = extract_youtube_id(data.get("src", ""))
        if not video_id:
            emit("action_error", {"message": "유튜브 링크에서 영상 ID를 찾지 못했습니다."})
            return
        room.music = {"type": "youtube", "src": video_id, "title": (data.get("title") or "").strip()[:40], "started_at": time.time()}
    elif music_type == "mp3":
        src = (data.get("src") or "").strip()
        if not src:
            emit("action_error", {"message": "mp3 파일을 먼저 업로드해주세요."})
            return
        room.music = {"type": "mp3", "src": src, "title": (data.get("title") or "").strip()[:40], "started_at": time.time()}
    else:
        emit("action_error", {"message": "알 수 없는 음악 형식입니다."})
        return
    broadcast_state(room)


@socketio.on("set_music_title")
def on_set_music_title(data):
    """운영진 : 지금 재생 중인 곡의 '러너 화면 표시 이름'만 바꿉니다(재생 위치는 그대로)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    if not room.music:
        emit("action_error", {"message": "지금 재생 중인 배경음악이 없습니다."})
        return
    room.music = dict(room.music, title=((data or {}).get("title") or "").strip()[:40])
    broadcast_state(room)


@socketio.on("stop_music")
def on_stop_music(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    room.music = None
    broadcast_state(room)


ACTION_HANDLERS = {
    "attack": lambda battle, p: battle.perform_attack(p["attacker"], p["target"]),
    "self_defend": lambda battle, p: battle.perform_self_defend(p["name"]),
    # 방어 : 본인 지정이면 직접 방어, 아군 지정이면 대리 방어 (모든 직군)
    "defend": lambda battle, p: battle.perform_proxy_defend(p["tanker"], p.get("target") or p["tanker"]),
    # 수호 : 가디언 전용, 지정 아군 1인에게 단순 방어 부여
    "guard": lambda battle, p: battle.perform_guard(p["tanker"], p["target"]),
    "taunt": lambda battle, p: battle.perform_taunt(p["tanker"], p["target"]),
    "dodge": lambda battle, p: battle.perform_dodge(p["name"]),
    "heal": lambda battle, p: battle.perform_heal(p["healer"], p["target"]),
    "timeout": lambda battle, p: battle.perform_timeout(p["name"]),
    "timeout_unacted_runners": lambda battle, p: battle.perform_timeout_unacted_runners(all_teams=bool(p.get("all_teams"))),
    "flee": lambda battle, p: battle.perform_flee(p["name"]),
    "defense_settle": lambda battle, p: battle.perform_defense_settle(p["name"]),
    "move": lambda battle, p: battle.perform_move(p["name"], int(p["x"]), int(p["y"])),
    "command": lambda battle, p: battle.perform_command(p["guardian"], p["target"]),
    "swap": lambda battle, p: battle.perform_swap(p["medic"], p["target"]),
    "collapse": lambda battle, p: battle.perform_collapse(p["attacker"], p["target"]),
    "emission": lambda battle, p: battle.perform_emission(p["attacker"]),
    "shield": lambda battle, p: battle.perform_shield(p["name"], p["target"]),
    "polarize": lambda battle, p: battle.perform_polarize(p["name"]),
    "reflux": lambda battle, p: battle.perform_reflux(p["name"], p.get("targets", [])),
    "restore": lambda battle, p: battle.perform_restore(p["name"], p.get("target")),
    "advance_turn": lambda battle, p: battle.advance_turn(),
    "undo": lambda battle, p: battle.undo_last(),
    "declare_defer": lambda battle, p: battle.perform_declare_defer(p["name"]),
}

SITE_TURN_ACTIONS = ("attack", "heal", "defense_settle")

# 미행동자 안내 : 라운드 제한시간이 이만큼(초) 남았을 때 아직 행동하지 않은 캐릭터를 커맨드 창에 한 번 안내합니다.
# 운영진이 운영 페이지에서 바꿀 수 있고(0 = 끄기), 기본은 1분입니다. 모든 전투 방식에 같이 적용됩니다.
REMIND_CHOICES = (0, 30, 60, 120, 180, 300)
# 채팅 도배 방지 : (횟수, 초) — 이 시간 안에 이 횟수를 넘게 보내면 잠시 막아요. "off"면 끔(기본).
CHAT_LIMITS = {"off": None, "5/10": (5, 10), "8/10": (8, 10), "15/30": (15, 30), "3/5": (3, 5)}
_CHAT_HITS = {}


def chat_limit_key():
    k = SITE_SETTINGS.get("chat_limit", "off")
    return k if k in CHAT_LIMITS else "off"


def _chat_flood(sid):
    lim = CHAT_LIMITS[chat_limit_key()]
    if not lim:
        return False
    n, sec = lim
    now = time.time()
    hits = [t for t in _CHAT_HITS.get(sid, []) if now - t < sec]
    if len(hits) >= n:
        _CHAT_HITS[sid] = hits
        return True
    hits.append(now)
    _CHAT_HITS[sid] = hits
    if len(_CHAT_HITS) > 5000:
        _CHAT_HITS.clear()
    return False
REMIND_DEFAULT = 60


def remind_seconds():
    v = SITE_SETTINGS.get("remind_seconds", REMIND_DEFAULT)
    return v if v in REMIND_CHOICES else REMIND_DEFAULT


def _remind_label(sec):
    return f"{sec}초" if sec < 60 else f"{sec // 60}분"


def _post_mass_raid_reminder(room, battle, threshold):
    unacted = battle.unacted_members()
    if not unacted:
        return  # 모두 행동했으면 안내하지 않습니다.
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "system",
        "role": "system",
        "category": "system",
        "text": f"제한시간 {_remind_label(threshold)} 남았습니다. 미행동자 {', '.join(unacted)}",
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))


def _mass_raid_round_reminder_check(room):
    battle = room.game.battle
    if battle is None or battle.finished:
        return
    sync_round_timer(room)
    if room.round_deadline is None:
        return
    if room.reminders_round_no != battle.round_no:
        room.reminders_round_no = battle.round_no
        room.reminders_sent = set()
    remaining = room.round_deadline - time.time()
    threshold = remind_seconds()
    if threshold and 0 < remaining <= threshold and threshold not in room.reminders_sent:
        room.reminders_sent.add(threshold)
        _post_mass_raid_reminder(room, battle, threshold)


def _maybe_resolve_telegraph_damage(room, battle):
    """마스 레이드 전용 : BOSS(2팀)의 후공 페이즈가 시작되는 순간, 그때까지 공개돼 있던 전조
    칸에 아직 남아있는 러너(1팀) 전원에게 일괄로 피해를 입힙니다(battle.apply_telegraph_damage
    참고 - BOSS의 '일반공격' 수치를 크리티컬 없이 그대로 쓰고, 대상마다 자기 방어 상태에 따라
    최종 피해가 달라집니다). 라운드당 한 번만 발동합니다."""
    if room.battle_type != "mass_raid" or battle.grid_width is None or battle.finished:
        return
    if battle.round_first_team != "1팀" or battle.current_turn_team != "2팀":
        return
    if not room.telegraph_cells or room.telegraph_round_no != battle.round_no:
        return
    if room.telegraph_damage_round_no == battle.round_no:
        return  # 이번 라운드엔 이미 발동했습니다.
    room.telegraph_damage_round_no = battle.round_no

    attacker = next((c for c in battle.team_b if c.is_alive and c.boss_group), None)
    if attacker is None:
        attacker = next((c for c in battle.team_b if c.is_alive), None)
    if attacker is None:
        return
    battle.apply_telegraph_damage(attacker.name, room.telegraph_cells)


def _round_reminder_loop():
    """전투 중인 방들을 주기적으로 훑어보며, 라운드 제한시간이 운영진이 정한 만큼 남으면 미행동자를 안내합니다."""
    while True:
        socketio.sleep(5)
        for room in list(ROOMS.values()):
            try:
                _mass_raid_round_reminder_check(room)
            except Exception as e:
                print(f"[round_reminder_loop] room {room.id} error: {e}")


def _maybe_auto_advance_turn(room, battle):
    """PVP/공성전 : 이번 턴에 행동해야 할 팀원이 전원 행동을 마치면(can_advance_turn), 커맨드
    창에 안내를 남기고 GM이 "다음 턴"을 누르지 않아도 자동으로 턴을 넘깁니다. 메딕은
    battle.can_advance_turn()이 이미 후공 페이즈까지 자동으로 봐주므로(엔진 규칙) 여기서
    따로 처리할 필요가 없습니다 - 메딕이 실제로 행동(또는 후공 페이즈 도달)하기 전까지는
    can_advance_turn()이 False로 유지됩니다.
    마스 레이드는 이 자동 진행 대상이 아닙니다(별도의 시간 기반 안내를 사용합니다)."""
    if room.battle_type not in ("pvp", "siege"):
        return
    if battle.finished or not battle.can_advance_turn():
        return
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "system",
        "role": "system",
        "category": "system",
        "text": f"{battle.current_turn_team} 전원 행동 완료 — 다음 턴으로 넘어갑니다.",
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))
    try:
        battle.advance_turn()
    except BattleError:
        pass


def _maybe_relocate_boss(battle, actor_char):
    """마스 레이드 : BOSS(4부위) 중 한 부위가 행동을 마쳐서 그 결과 4부위 전원이 이번
    라운드 행동을 끝냈다면, 격자에 다른 빈 2x2 자리가 있으면 4부위를 통째로 그쪽으로
    옮깁니다("행동이 끝나면... 아무 위치나 4칸이 비어있으면 그쪽으로 이동" 요청).
    빈 자리가 없거나(또는 지금 자리가 이미 최선이면) 제자리에 그대로 둡니다."""
    if actor_char is None or not actor_char.boss_group or battle.grid_width is None:
        return
    siblings = [c for c in battle.team_a + battle.team_b if c.boss_group == actor_char.boss_group]
    if not siblings or not all((not c.is_alive) or c.has_acted for c in siblings):
        return

    nw = next((c for c in siblings if c.boss_section == "NW"), siblings[0])
    if nw.grid_pos is None:
        return
    current_anchor = tuple(nw.grid_pos)

    occupied = {
        tuple(c.grid_pos) for c in battle.team_a + battle.team_b
        if c.boss_group != actor_char.boss_group and c.is_alive and c.grid_pos
    }
    center = ((battle.grid_width - 1) / 2, (battle.grid_height - 1) / 2)
    anchor = _find_empty_2x2_anchor(battle.grid_width, battle.grid_height, occupied, near=center)
    if anchor is None or anchor == current_anchor:
        return

    for c in siblings:
        ox, oy = config.BOSS_SECTION_OFFSETS.get(c.boss_section, (0, 0))
        c.grid_pos = (anchor[0] + ox, anchor[1] + oy)
    group_label = next(
        (p for p in config.BOSS_NAME_PREFIXES if nw.name.startswith(p)), nw.name,
    )
    battle.log_event(f"{group_label} 이동 — {cell_label(*current_anchor)} → {cell_label(*anchor)}", tag="system")


@socketio.on("battle_action")
def on_battle_action(data):
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        emit("action_error", {"message": "방을 찾을 수 없습니다."})
        return
    battle = room.game.battle
    if battle is None:
        emit("action_error", {"message": "전투가 시작되지 않았습니다."})
        return
    action_type = data.get("type")
    handler = ACTION_HANDLERS.get(action_type)
    if handler is None:
        emit("action_error", {"message": f"알 수 없는 행동: {action_type}"})
        return

    control = resolve_control(room, info)

    if action_type in ("advance_turn", "undo", "timeout", "timeout_unacted_runners"):
        if control["scope"] != "all":
            emit("action_error", {"message": "이 행동은 운영진만 사용할 수 있습니다."})
            return
    elif control["scope"] == "none":
        emit("action_error", {"message": "조작 권한이 없습니다. 닉네임을 본인 캐릭터 이름으로 입장해주세요."})
        return
    elif control["scope"] == "character":
        actor_field = ACTOR_FIELD.get(action_type)
        payload_check = data.get("payload", {})
        if actor_field and payload_check.get(actor_field) != control["name"]:
            emit("action_error", {"message": f"{control['name']} 캐릭터만 조작할 수 있습니다."})
            return

    if room.pending_reveal is not None and action_type != "undo":
        emit("action_error", {"message": "먼저 이전 행동을 공개하거나 되돌려주세요."})
        return

    payload = data.get("payload", {})
    if action_type == "timeout_unacted_runners":
        # PVP는 두 팀 모두 러너라 지금 차례인 팀(어느 팀이든)의 미행동자를 넘깁니다.
        payload = {"all_teams": room.battle_type == "pvp"}

    # 공성전/레이드에서 GM이 거점(2팀) 캐릭터로 행동하면, 결과를 바로 공개하지 않고
    # 운영진 로그에만 미리 보여줍니다. 마음에 들면 "공개하기"로 러너에게 알리고,
    # 마음에 안 들면 "되돌리기"로 없던 일로 만들 수 있습니다.
    actor_field = ACTOR_FIELD.get(action_type)
    actor_name = payload.get(actor_field) if actor_field else None
    actor_char = battle.find_character(actor_name) if actor_name else None

    # 공성전 : 거점이 이번 라운드 행동(방어 정산/공격/힐)을 하려면 먼저 전조(거점 행동 다이스)를
    # 굴려야 합니다. 안 굴렸다면 굴리라고 안내하고 행동을 막습니다.
    if (
        room.battle_type == "siege"
        and actor_char is not None
        and actor_char.team == "B"
        and action_type in SITE_TURN_ACTIONS
        and room.site_dice_round_no != battle.round_no
    ):
        emit("action_error", {"message": "먼저 🎲 다이스 굴리기로 이번 라운드 거점 행동(전조)을 정해주세요."})
        return

    # 격자 전투(공성전/마스 레이드) : 러너가 이동하려면 먼저 GM이 이번 라운드 전조를
    # 출력해야 합니다 (공성전 = 거점 다이스, 마스 레이드 = 격자 칸 공개).
    if action_type == "move" and telegraph_pending(room, battle):
        emit("action_error", {"message": "먼저 GM이 이번 라운드 전조를 출력해야 이동할 수 있습니다."})
        return

    should_preview = (
        info["role"] == "gm"
        and room.battle_type == "siege"
        and actor_char is not None
        and actor_char.team == "B"
        and action_type not in ("advance_turn", "undo")
    )

    pub_len_before = len(battle.public_log)
    was_pending = room.pending_reveal is not None  # undo 중일 수도 있으므로 미리 기록

    try:
        handler(battle, payload)
    except BattleError as e:
        emit("action_error", {"message": str(e)})
        return

    if action_type == "undo":
        if was_pending:
            room.pending_reveal = None
            socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))
            return
        broadcast_state(room)
        return

    if should_preview:
        room.pending_reveal = {"actor": actor_char.name, "pub_len_before": pub_len_before, "action_type": action_type,
                               "payload": dict(payload)}
        socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))
        return

    # 공성전 : 거점(2팀) 캐릭터는 이번 라운드 다이스로 정해진 횟수만큼 반복 행동할 수 있습니다.
    if room.battle_type == "siege" and room.site_dice_round_no == battle.round_no and room.site_dice_value:
        if actor_char is not None and actor_char.team == "B":
            room.site_dice_used += 1
            remaining = room.site_dice_value - room.site_dice_used
            # 거점은 부위(2x2)가 나뉘어 있어도 '거점 하나'로 행동합니다 - 다이스 횟수를 거점 전체가
            # 함께 쓰고, 남은 횟수가 있으면 모든 부위가 다시 행동 가능, 다 쓰면 모든 부위가 행동 완료.
            _set_site_group_acted(battle, actor_char, acted=remaining <= 0)
            if remaining > 0:
                battle.log_event(f"거점 행동 게이지 (라운드 내 {remaining}회)", tag="system")
            else:
                battle.log_event("거점의 이번 라운드 행동이 모두 끝났습니다.", tag="system")

    emit_action_sfx(room, actor_char.name if actor_char else actor_name, action_type)
    emit_attack_lines(room, action_type, payload)
    _maybe_relocate_boss(battle, actor_char)
    _maybe_auto_advance_turn(room, battle)
    _maybe_resolve_telegraph_damage(room, battle)
    broadcast_state(room)


@socketio.on("reveal_pending_action")
def on_reveal_pending_action(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    battle = room.game.battle
    pending = room.pending_reveal
    if battle is None or pending is None:
        emit("action_error", {"message": "공개할 대기 중인 행동이 없습니다."})
        return

    new_lines = battle.public_log[pending["pub_len_before"]:]
    summary = " · ".join(l["text"] for l in new_lines if l.get("tag") != "hp") or "(결과 없음)"
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "적",
        "role": "system",
        "category": "system",
        "text": summary,
    }
    room.chat_log.append(_with_chat_id(entry))
    mark_runtime_dirty()
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))

    # 공성전 : 거점 다중 행동 소모는 "공개"가 확정된 시점에만 적용됩니다.
    # (미리보기만 하고 되돌린 굴림은 이번 라운드 행동 횟수를 소모하지 않습니다)
    emit_action_sfx(room, pending["actor"], pending.get("action_type"))
    emit_attack_lines(room, pending.get("action_type"), pending.get("payload") or {})
    if room.battle_type == "siege" and room.site_dice_round_no == battle.round_no and room.site_dice_value:
        actor_char = battle.find_character(pending["actor"])
        if actor_char is not None and actor_char.team == "B":
            room.site_dice_used += 1
            remaining = room.site_dice_value - room.site_dice_used
            # 거점은 부위(2x2)가 나뉘어 있어도 '거점 하나'로 행동합니다 - 다이스 횟수를 거점 전체가
            # 함께 쓰고, 남은 횟수가 있으면 모든 부위가 다시 행동 가능, 다 쓰면 모든 부위가 행동 완료.
            _set_site_group_acted(battle, actor_char, acted=remaining <= 0)
            if remaining > 0:
                battle.log_event(f"거점 행동 게이지 (라운드 내 {remaining}회)", tag="system")
            else:
                battle.log_event("거점의 이번 라운드 행동이 모두 끝났습니다.", tag="system")

    room.pending_reveal = None
    broadcast_state(room)


# ----------------------------------------------------------------------
# 상점 : 구매/사용(참가자), 상품·재화·소지품 관리(운영진)
# ----------------------------------------------------------------------


def _broadcast_all_rooms():
    """상품 목록/재화/소지품은 모든 방이 같이 쓰는 데이터라 모든 방에 다시 보내줍니다.
    아무도 접속해 있지 않은 방은 건너뜁니다(들어올 때 새 상태를 받으니까요)."""
    active = {info.get("room_id") for info in list(CONNECTIONS.values())}
    for r in list_rooms():
        if r.id in active:
            broadcast_state(r)


def _shop_context(data):
    """(room, info, 대상 캐릭터 이름) - 참가자는 본인만, 운영진은 data["name"]으로 아무 캐릭터나."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return None, None, None
    room = get_room(info["room_id"])
    if room is None:
        return None, None, None
    name = _mypage_target_name(room, info, data or {})
    if name is None:
        emit("action_error", {"message": "캐릭터로 로그인한 뒤에 상점을 이용할 수 있습니다."})
        return room, info, None
    return room, info, name


def _live_battle_char(room, name):
    """진행 중인(끝나지 않은) 전투에 이 캐릭터가 있으면 그 전투용 캐릭터를 돌려줍니다."""
    battle = room.game.battle
    if battle is None or battle.finished:
        return None
    return battle.find_character(name)


@socketio.on("shop_buy")
def on_shop_buy(data):
    room, info, name = _shop_context(data)
    if name is None:
        return
    shop = shop_mod.shared_shop()
    item = shop.get((data or {}).get("item_id"))
    if item is None:
        emit("action_error", {"message": "존재하지 않는 상품입니다."})
        return
    try:
        qty = max(1, min(99, int((data or {}).get("qty") or 1)))
    except (TypeError, ValueError):
        qty = 1
    db = room.game.db
    cost = item["price"] * qty
    have = shop_mod.get_points(db, name)
    if have < cost:
        emit("action_error", {"message": f"P가 부족합니다. (보유 {have}P / 필요 {cost}P)"})
        return
    shop_mod.set_points(db, name, have - cost)
    shop_mod.change_item_count(db, name, item["id"], qty)
    emit("shop_result", {"message": f"{item['name']} ×{qty} 구매 완료 (-{cost}P)"})
    _broadcast_all_rooms()


@socketio.on("shop_use")
def on_shop_use(data):
    data = data or {}
    room, info, name = _shop_context(data)
    if name is None:
        return
    shop = shop_mod.shared_shop()
    item = shop.get(data.get("item_id"))
    db = room.game.db
    if item is None or shop_mod.get_items(db, name).get(data.get("item_id"), 0) <= 0:
        emit("action_error", {"message": "보유하지 않은 아이템입니다."})
        return

    if item["effect"] == "role_change":
        emit("action_error", {"message": "포지션 변경권은 마이페이지의 포지션에서 원하는 포지션을 눌러 사용하세요."})
        return
    live = _live_battle_char(room, name)
    in_battle = live is not None
    if item["timing"] == "battle" and not in_battle:
        emit("action_error", {"message": f"{item['name']}은(는) 전투 중에만 사용할 수 있습니다."})
        return
    if item["timing"] == "prebattle" and in_battle:
        emit("action_error", {"message": f"{item['name']}은(는) 전투 전에만 사용할 수 있습니다."})
        return

    battle = room.game.battle
    effect = item["effect"]
    if effect == "heal":
        if not in_battle:
            emit("action_error", {"message": "체력 회복 아이템은 전투 중에만 효과가 있습니다."})
            return
        if not live.is_alive:
            emit("action_error", {"message": "전투에서 이탈한 캐릭터는 사용할 수 없습니다."})
            return
        amount = max(0, int(item["value"]))
        if live.current_hp >= live.max_hp and not live.pending_attacks:
            emit("action_error", {"message": "체력이 가득 차 있어서 사용할 수 없습니다."})
            return
        battle._push_history()
        hp_before = live.current_hp
        was_downed = live.status == live.STATUS_DOWNED
        queued = battle._apply_or_queue_heal(live, amount, item["name"])
        battle.log_event(f"{name} 물자 사용 : {item['name']}", tag="heal")
        if queued:
            battle.log_event(f"회복 {amount} (피해 정산 후 적용)", tag="heal")
        else:
            battle.log_event(f"회복 {amount}", tag="heal")
            battle.log_event(f"{name} HP {hp_before} → {live.current_hp}", tag="hp")
            if was_downed and live.status == live.STATUS_ALIVE:
                battle.log_event(f"{name} 위기를 넘기고 전투에 복귀했습니다!", tag="system")
        result_msg = f"{item['name']} 사용 : 회복 {amount}" + (" (피해 정산 후 적용)" if queued else "")
    elif effect == "stat_up":
        stat = data.get("stat")
        if stat not in config.STAT_KEYS:
            emit("action_error", {"message": "올릴 스탯을 골라주세요."})
            return
        entry = db.get(name)
        stats = dict(entry.get("stats") or {})
        stats[stat] = int(stats.get(stat, 0)) + int(item["value"])
        entry["stats"], _ = config.clamp_stats(stats)
        db.save()
        note = " (다음 전투부터 적용)" if in_battle else ""
        post_system_chat(room, f"🧪 {name} : {item['name']} 사용 → {stat} +{item['value']}{note}")
        result_msg = f"{item['name']} 사용 : {stat} +{item['value']}{note}"
    else:
        req = shop.add_request(room.id, name, item, data.get("memo"))
        memo = f" - \"{req['memo']}\"" if req["memo"] else ""
        post_system_chat(room, f"📦 {name} : {item['name']} 사용{memo} (운영진 처리 대기)")
        result_msg = f"{item['name']} 사용 요청을 운영진에게 보냈습니다."

    shop_mod.change_item_count(db, name, item["id"], -1)
    emit("shop_result", {"message": result_msg})
    _broadcast_all_rooms()


@socketio.on("shop_admin_item")
def on_shop_admin_item(data):
    """운영진 : 상품 추가/수정/삭제/순서 이동."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 상품을 관리할 수 있습니다."})
        return
    data = data or {}
    shop = shop_mod.shared_shop()
    action = data.get("action")
    if action == "add":
        shop.add_item(data.get("fields") or {})
    elif action == "update":
        if shop.update_item(data.get("item_id"), data.get("fields") or {}) is None:
            emit("action_error", {"message": "존재하지 않는 상품입니다."})
            return
    elif action == "delete":
        shop.delete_item(data.get("item_id"))
    elif action == "move":
        shop.move_item(data.get("item_id"), int(data.get("delta") or 0))
    else:
        return
    _broadcast_all_rooms()


@socketio.on("shop_admin_points")
def on_shop_admin_points(data):
    """운영진 : 캐릭터 재화(P) 지정(set) 또는 증감(delta)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 재화를 관리할 수 있습니다."})
        return
    data = data or {}
    db = room.game.db
    names = data.get("names") or ([data.get("name")] if data.get("name") else [])
    names = [n for n in names if db.exists(n)]
    if not names:
        emit("action_error", {"message": "존재하지 않는 캐릭터입니다."})
        return
    try:
        if "set" in data:
            for n in names:
                shop_mod.set_points(db, n, int(data["set"]))
        else:
            delta = int(data.get("delta") or 0)
            for n in names:
                shop_mod.set_points(db, n, shop_mod.get_points(db, n) + delta)
    except (TypeError, ValueError):
        emit("action_error", {"message": "숫자를 입력해주세요."})
        return
    _broadcast_all_rooms()


@socketio.on("shop_admin_give")
def on_shop_admin_give(data):
    """운영진 : 캐릭터 소지품 아이템 지급/회수 (delta 개수)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 소지품을 관리할 수 있습니다."})
        return
    data = data or {}
    db = room.game.db
    name = data.get("name")
    item = shop_mod.shared_shop().get(data.get("item_id"))
    if not db.exists(name) or item is None:
        emit("action_error", {"message": "캐릭터 또는 상품이 존재하지 않습니다."})
        return
    try:
        delta = int(data.get("delta") or 0)
    except (TypeError, ValueError):
        return
    shop_mod.change_item_count(db, name, item["id"], delta)
    _broadcast_all_rooms()


@socketio.on("shop_admin_request")
def on_shop_admin_request(data):
    """운영진 : '운영진 처리' 요청을 처리 완료/미처리로 표시."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        return
    data = data or {}
    if shop_mod.shared_shop().set_request_done(data.get("request_id"), data.get("done", True)):
        _broadcast_all_rooms()


# ----------------------------------------------------------------------
# 격자 지도 배경 이미지 (운영진 전용, 방마다 따로 저장)
# ----------------------------------------------------------------------
MAP_BG_DIR = os.path.join(_THIS_DIR, "static", "map_bg")
os.makedirs(MAP_BG_DIR, exist_ok=True)
MAP_BG_ALLOWED_EXTS = (".png", ".webp", ".gif", ".jpg", ".jpeg")
MAP_BG_MAX_BYTES = IMAGE_UPLOAD_MAX_BYTES
SCENE_MAX_BYTES = IMAGE_UPLOAD_MAX_BYTES
MAP_BG_DEFAULT = {"url": None, "mode": "frame", "dim": 40, "line": 22}


def _clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


@socketio.on("set_map_bg")
def on_set_map_bg(data):
    """운영진 : 배경 이미지 업로드/삭제와 표시 방식(범위/어둡기/격자선 진하기) 설정."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 지도 배경을 바꿀 수 있습니다."})
        return
    data = data or {}
    cfg = dict(MAP_BG_DEFAULT, **(room.map_bg or {}))
    if data.get("clear_image"):
        cfg["url"] = None
    blob = data.get("data")
    if blob is not None:
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in MAP_BG_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png/jpg/webp/gif 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > MAP_BG_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MAP_BG_DIR, filename), "wb") as f:
            f.write(blob)
        cfg["url"] = f"/static/map_bg/{filename}"
    if data.get("mode") in ("frame", "grid"):
        cfg["mode"] = data["mode"]
    if "dim" in data:
        cfg["dim"] = _clamp_int(data["dim"], 0, 90, cfg["dim"])
    if "line" in data:
        cfg["line"] = _clamp_int(data["line"], 0, 100, cfg["line"])
    if data.get("reset"):
        cfg = dict(MAP_BG_DEFAULT)
    room.map_bg = cfg
    save_rooms()
    broadcast_state(room)


@socketio.on("set_boss_image")
def on_set_boss_image(data):
    """운영진 : 2x2 몹 이미지(4칸이 한 세트) 업로드/삭제. key는 몹 이름(boss_group의 '#' 앞부분)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 몹 이미지를 바꿀 수 있습니다."})
        return
    data = data or {}
    key = (data.get("key") or "").strip()[:40]
    if not key:
        return
    images = dict(room.boss_images or {})
    if data.get("clear"):
        images.pop(key, None)
    else:
        blob = data.get("data")
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in MAP_BG_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png/jpg/webp/gif 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > MAP_BG_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"boss_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MAP_BG_DIR, filename), "wb") as f:
            f.write(blob)
        images[key] = f"/static/map_bg/{filename}"
    room.boss_images = images
    save_rooms()
    broadcast_state(room)


# ----------------------------------------------------------------------
# 공지사항 (운영진이 작성, 모든 방 공통)
# ----------------------------------------------------------------------
def _broadcast_notices():
    payload = {"notices": notices_mod.shared_board().payload()}
    for r in list_rooms():
        socketio.emit("notices", payload, room=room_channel(r.id, "all"))


@socketio.on("notice_save")
def on_notice_save(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 공지사항을 쓸 수 있습니다."})
        return
    data = data or {}
    info = CONNECTIONS.get(request.sid) or {}
    notice, is_new = notices_mod.shared_board().upsert(
        data.get("id"), data.get("title"), data.get("html"), data.get("pinned"), info.get("nickname") or "GM",
    )
    _broadcast_notices()
    emit("notice_saved", {"id": notice["id"]})
    if is_new:
        for r in list_rooms():
            post_system_chat(r, f"{notice['title']} : 새 공지사항이 업데이트 되었습니다.")


@socketio.on("notice_delete")
def on_notice_delete(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 공지사항을 지울 수 있습니다."})
        return
    if notices_mod.shared_board().delete((data or {}).get("id")):
        _broadcast_notices()


@socketio.on("set_default_sfx")
def on_set_default_sfx(data):
    """운영진 : 기본 효과음(공격/방어, 지휘/회복, 라운드 전환, 보스 타격) 파일 교체·음량 조절·초기화."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 기본 효과음을 바꿀 수 있습니다."})
        return
    data = data or {}
    kind = data.get("kind")
    if kind not in SFX_CONFIG:
        return
    if data.get("reset"):
        SFX_CONFIG[kind].update({"url": SFX_DEFAULTS[kind]["url"], "volume": SFX_DEFAULTS[kind]["volume"]})
    if "volume" in data:
        SFX_CONFIG[kind]["volume"] = _clamp_int(data["volume"], 0, 100, SFX_CONFIG[kind]["volume"])
    blob = data.get("data")
    if blob is not None:
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in SOUND_EFFECT_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "mp3/wav/ogg/m4a/aac 소리 파일만 올릴 수 있습니다."})
            return
        if len(blob) > SOUND_EFFECT_MAX_BYTES:
            emit("action_error", {"message": f"파일이 너무 큽니다 (최대 {AUDIO_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"sfx_{kind}_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(SOUND_EFFECT_DIR, filename), "wb") as f:
            f.write(blob)
        SFX_CONFIG[kind]["url"] = f"/static/sound_effects/{filename}"
    _save_sfx_config()
    for r in list_rooms():
        broadcast_state(r)


@socketio.on("set_track_bg")
def on_set_track_bg(data):
    """운영진 : 라운드 트랙 블럭 배경 이미지 업로드/삭제와 어둡기."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 라운드 트랙 배경을 바꿀 수 있습니다."})
        return
    data = data or {}
    cfg = dict({"url": None, "dim": 45}, **(room.track_bg or {}))
    if data.get("reset"):
        cfg = {"url": None, "dim": 45}
    blob = data.get("data")
    if blob is not None:
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in MAP_BG_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png/jpg/webp/gif 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > MAP_BG_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"track_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MAP_BG_DIR, filename), "wb") as f:
            f.write(blob)
        cfg["url"] = f"/static/map_bg/{filename}"
    if "dim" in data:
        cfg["dim"] = _clamp_int(data["dim"], 0, 90, cfg["dim"])
    room.track_bg = cfg
    save_rooms()
    broadcast_state(room)


# ----------------------------------------------------------------------
# 우체통 : 캐릭터끼리 편지 (모든 방 공용)
# ----------------------------------------------------------------------
def _mail_identity(sid):
    """이 접속의 우체통 이름. 운영진은 "운영진", 러너는 로그인한 캐릭터 이름, 그 외는 None."""
    info = CONNECTIONS.get(sid)
    if info is None:
        return None, False, None
    room = get_room(info["room_id"])
    if room is None:
        return None, False, None
    if _require_gm_or_guest_gm(sid) is not None:
        return mailbox_mod.GM_NAME, True, room
    nickname = (info.get("nickname") or "").strip()
    if nickname and nickname in room.game.db.characters:
        return nickname, False, room
    return None, False, room


def _mail_candidates(room):
    # BOSS/NOVA 같은 몹 이름은 편지 받는 사람에서 뺍니다.
    return sorted(n for n, d in room.game.db.characters.items() if (d or {}).get("role") and not config.is_boss_name(n))


def _mail_era_now():
    era = SITE_SETTINGS.get("mail_era")
    return era if era in mailbox_mod.ERA_INDEX else mailbox_mod.DEFAULT_ERA


def _mail_age_info(room, me):
    """편지 쓰기의 나이 안내 : 등록된 캐릭터들의 1차(空歷 514年) 나이 목록과 내 나이."""
    ages, mine = [], None
    for name, entry in room.game.db.characters.items():
        a = mailbox_mod.age_of(entry)  # 정하지 않았으면 기본 13세
        ages.append(a)
        if name == me:
            mine = a
    return {"ages": ages, "my_age": mine, "age_base": mailbox_mod.AGE_BASE_YEAR,
            "age_min": mailbox_mod.AGE_MIN, "age_max": mailbox_mod.AGE_MAX}


@socketio.on("mail_era_set")
def on_mail_era_set(data):
    """운영진 : 편지를 쓰는 지금 시기(리뉴얼 기간)를 정합니다."""
    me, is_gm, room = _mail_identity(request.sid)
    era = (data or {}).get("era")
    if not is_gm or era not in mailbox_mod.ERA_INDEX:
        return
    SITE_SETTINGS["mail_era"] = era
    safeio.write_json(SITE_SETTINGS_PATH, SITE_SETTINGS, indent=1)
    for sid in list(CONNECTIONS.keys()):
        _emit_mail_data(sid)


def _emit_mail_data(sid):
    me, is_gm, room = _mail_identity(sid)
    if room is None:
        return
    if me is None:
        # PLAY 룸(LOOP)의 TEST는 우체통을 미리 보기만 해요(빈 우체통 · 보내기 불가).
        info = CONNECTIONS.get(sid) or {}
        preview = room.battle_type == "play" and info.get("nickname") == loop_mod.TEST_ID
        socketio.emit("mail_data", {"me": loop_mod.TEST_ID if preview else None, "preview": preview, "inbox": [], "outbox": [], "unread": 0,
                                    "eras": mailbox_mod.eras_payload(), "era_now": _mail_era_now(),
                                    "roster": [] if room.battle_type == "play" else _mail_candidates(room)}, to=sid)
        return
    data = mailbox_mod.shared_mailbox().payload(me, is_gm)
    data["roster"] = _mail_candidates(room)
    data["era_now"] = _mail_era_now()
    data.update(_mail_age_info(room, me))
    data["is_gm"] = is_gm
    socketio.emit("mail_data", data, to=sid)


# ==================================================================
# PLAY 룸 : LOOP 러닝 시뮬레이션 (loop_game.py) — 캐릭터마다 자기 생애를 진행합니다.
# 체력 · 정신 변동은 고른 뒤에만 보냅니다. 출신 국가는 생애마다 무작위, 진영(使徒 / Void)은 캐릭터 정보의 진영 칸을 씁니다.
# ==================================================================
def _loop_identity(sid):
    """LOOP 기록 주인 : (기록 키, 화면 이름, 운영진 여부, 방).
    TEST는 여러 사람이 같이 쓰는 아이디라 기기(브라우저)마다 따로 저장합니다 — "TEST#기기번호".
    운영진도 기기마다 따로예요(시험 플레이용)."""
    info = CONNECTIONS.get(sid)
    room = get_room(info["room_id"]) if info else None
    if room is None:
        return None, None, False, None
    dev = info.get("loop_device") or ""
    if _require_gm_or_guest_gm(sid) is not None:
        return (f"{mailbox_mod.GM_NAME}#{dev}" if dev else mailbox_mod.GM_NAME), mailbox_mod.GM_NAME, True, room
    if (info.get("nickname") or "") == loop_mod.TEST_ID and dev:
        return f"{loop_mod.TEST_ID}#{dev}", loop_mod.TEST_ID, False, room
    return None, None, False, room


def _emit_loop_data(sid):
    key, me, is_gm, room = _loop_identity(sid)
    if room is None or room.battle_type != "play":
        return
    book = loop_mod.shared_book()
    data = book.view(key) if key else {"run": None, "lives": [], "loops": 0, "intro": [], "eras": []}
    data["me"] = me
    data["is_gm"] = is_gm
    socketio.emit("loop_data", data, to=sid)


def _loop_action(fn, *args):
    key, me, is_gm, room = _loop_identity(request.sid)
    if room is None or room.battle_type != "play":
        return
    if key is None:
        emit("loop_result", {"ok": False, "message": "TEST로 입장해야 플레이할 수 있어요."})
        return
    try:
        fn(key, *args)
    except loop_mod.LoopError as e:
        emit("loop_result", {"ok": False, "message": str(e)})
    _emit_loop_data(request.sid)


@socketio.on("loop_life")
def on_loop_life(data=None):
    """지난 운명 리플레이용 : 그 생애의 사건 기록 전체(본인 기기 기록만)."""
    key, me, is_gm, room = _loop_identity(request.sid)
    if room is None or room.battle_type != "play" or key is None:
        return
    try:
        i = int((data or {}).get("i"))
    except (TypeError, ValueError):
        return
    d = loop_mod.shared_book().life_detail(key, i)
    if d is not None:
        emit("loop_life", d)


@socketio.on("loop_state")
def on_loop_state(data=None):
    _emit_loop_data(request.sid)


@socketio.on("loop_start")
def on_loop_start(data):
    # 출신 국가는 생애마다 서버가 무작위로 정하고, 전쟁 때 진영은 국가를 따라가요(아르카디아 → 使徒, 노바 → Void).
    _loop_action(loop_mod.shared_book().start, str((data or {}).get("res") or ""))


# ── LOOP 편집(운영진) : 사건 · 규칙 · 문장. 체력 · 정신 변동이 들어 있어서 운영진에게만 보냅니다. ──
def _loop_admin_room():
    room = _require_gm_or_guest_gm(request.sid)
    if room is None or room.battle_type != "play":
        emit("loop_admin_result", {"ok": False, "message": "운영진만 편집할 수 있어요."})
        return None
    return room


@socketio.on("loop_admin_get")
def on_loop_admin_get(data=None):
    if _loop_admin_room() is None:
        return
    emit("loop_admin", loop_mod.content().payload())


@socketio.on("loop_admin_save")
def on_loop_admin_save(data):
    room = _loop_admin_room()
    if room is None:
        return
    try:
        loop_mod.content().save((data or {}).get("content"))
    except (loop_mod.LoopError, ValueError, TypeError, AttributeError) as e:
        emit("loop_admin_result", {"ok": False, "message": str(e) if isinstance(e, loop_mod.LoopError) else "내용 형식이 올바르지 않아요."})
        return
    emit("loop_admin", loop_mod.content().payload())
    emit("loop_admin_result", {"ok": True, "message": "저장했어요. 다음 사건부터 바로 반영돼요."})


@socketio.on("loop_admin_reset")
def on_loop_admin_reset(data=None):
    if _loop_admin_room() is None:
        return
    loop_mod.content().reset()
    emit("loop_admin", loop_mod.content().payload())
    emit("loop_admin_result", {"ok": True, "message": "기본 내용으로 되돌렸어요."})


@socketio.on("loop_choose")
def on_loop_choose(data):
    data = data or {}
    try:
        idx = int(data.get("idx"))
    except (TypeError, ValueError):
        idx = -1
    _loop_action(loop_mod.shared_book().choose, str(data.get("event") or ""), idx)


@socketio.on("loop_solve")
def on_loop_solve(data):
    data = data or {}
    _loop_action(loop_mod.shared_book().solve, str(data.get("event") or ""), str(data.get("kind") or ""))


@socketio.on("loop_begin")
def on_loop_begin(data=None):
    _loop_action(loop_mod.shared_book().begin)


@socketio.on("loop_resume")
def on_loop_resume(data=None):
    _loop_action(loop_mod.shared_book().resume)


@socketio.on("loop_next")
def on_loop_next(data=None):
    _loop_action(loop_mod.shared_book().next)


@socketio.on("loop_death")
def on_loop_death(data):
    mode = "loop" if (data or {}).get("mode") == "loop" else "end"
    _loop_action(loop_mod.shared_book().after_death, mode)


@socketio.on("loop_finish")
def on_loop_finish(data=None):
    _loop_action(loop_mod.shared_book().finish)


@socketio.on("loop_reset")
def on_loop_reset(data=None):
    _loop_action(loop_mod.shared_book().reset, bool((data or {}).get("force")))


@socketio.on("mail_list")
def on_mail_list(data=None):
    _emit_mail_data(request.sid)


@socketio.on("mail_send")
def on_mail_send(data):
    data = data or {}
    me, is_gm, room = _mail_identity(request.sid)
    if me is None:
        emit("mail_result", {"ok": False, "message": "캐릭터로 로그인해야 편지를 보낼 수 있어요."})
        return
    # 직접 고르기 : 여러 명에게 한 통씩(익명 불가, 나에게 보내기 가능) / 랜덤 : 1~5명에게(서로 다른 사람, 익명이 기본)
    is_random = bool(data.get("random"))
    if is_random:
        try:
            n = max(1, min(5, int(data.get("random_count") or 1)))
        except (TypeError, ValueError):
            n = 1
        targets, anonymous = [""] * n, bool(data.get("anonymous", True))
    else:
        raw = data.get("to")
        raw = raw if isinstance(raw, list) else [raw]
        targets = list(dict.fromkeys((t or "").strip() for t in raw if (t or "").strip()))[:30]
        anonymous = False
        if not targets:
            emit("mail_result", {"ok": False, "message": "받는 사람을 골라 주세요."})
            return
    raw_images = data.get("images") or []
    if not isinstance(raw_images, list) or len(raw_images) > mailbox_mod.MAX_IMAGES:
        emit("mail_result", {"ok": False, "message": f"이미지는 {mailbox_mod.MAX_IMAGES}장까지 붙일 수 있어요."})
        return
    blobs = []
    for img in raw_images:
        blob = (img or {}).get("data") if isinstance(img, dict) else None
        ext = _mail_image_ext(blob)
        if ext is None:
            emit("mail_result", {"ok": False, "message": "png · jpg · gif · webp 이미지만 붙일 수 있어요."})
            return
        if len(blob) > mailbox_mod.IMAGE_MAX_BYTES:
            emit("mail_result", {"ok": False, "message": f"이미지는 한 장에 {mailbox_mod.IMAGE_MAX_BYTES // (1024 * 1024)}MB까지 붙일 수 있어요."})
            return
        blobs.append((blob, ext))
    # 시기(리뉴얼 기간)는 운영진이 정한 지금 기간으로, 쓰는 사람은 연도만 고릅니다.
    era_now = _mail_era_now()
    # '연도 없음'을 고르면 시기 · 연도 없이 보냅니다(편지함에서는 '시기 없음'으로 묶여요).
    if data.get("no_year"):
        era_now = None
    if not (data.get("text") or "").strip() and not blobs:
        emit("mail_result", {"ok": False, "message": "편지 내용을 쓰거나 이미지를 붙여 주세요."})
        return
    # 보낼 수 있는지(쿨타임 · 받는 사람) 확인한 뒤에만 파일을 남기려고, 첫 통을 보낼 때 저장합니다.
    box = mailbox_mod.shared_mailbox()
    sent, images = [], []
    batch = uuid.uuid4().hex[:10] if len(targets) > 1 else None
    def _store_images():
        os.makedirs(mailbox_mod.IMAGE_DIR, exist_ok=True)
        for blob, ext in blobs:
            fn = f"{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}{ext}"
            with open(os.path.join(mailbox_mod.IMAGE_DIR, fn), "wb") as f:
                f.write(blob)
            images.append(url_for("static", filename=f"mail_images/{fn}"))
    try:
        for i, t in enumerate(targets):
            if i == 0:
                box.send(me, t, data.get("text"), anonymous=anonymous, random_pick=is_random,
                         candidates=_mail_candidates(room), check_cooldown=True, dry_run=True, era=era_now,
                         images=[ext for _, ext in blobs])
                _store_images()
            sent.append(box.send(me, t, data.get("text"), anonymous=anonymous, random_pick=is_random,
                                 candidates=_mail_candidates(room), check_cooldown=(i == 0), images=images,
                                 era=era_now, year=data.get("year"), batch=batch,
                                 exclude=[l["to"] for l in sent]))
    except mailbox_mod.MailError as e:
        if not sent:
            emit("mail_result", {"ok": False, "message": str(e)})
            return
    if is_random:
        msg = "랜덤으로 누군가에게 편지를 보냈어요." if len(sent) == 1 else f"랜덤으로 {len(sent)}명에게 편지를 보냈어요."
    elif len(sent) == 1:
        msg = "나에게 편지를 보냈어요." if sent[0]["to"] == me else f"{sent[0]['to']}에게 편지를 보냈어요."
    else:
        msg = f"{sent[0]['to']} 외 {len(sent) - 1}명에게 편지를 보냈어요."
    emit("mail_result", {"ok": True, "message": msg})
    _emit_mail_data(request.sid)
    # 받는 사람이 지금 접속해 있으면(어느 방이든) 바로 알려줍니다.
    for letter in sent:
        for sid, info in list(CONNECTIONS.items()):
            if sid != request.sid and (info.get("nickname") or "").strip() == letter["to"]:
                socketio.emit("mail_new", {"from": None if letter["anonymous"] else letter["from"]}, to=sid)
                _emit_mail_data(sid)


def _mail_image_ext(blob):
    """편지 첨부 이미지 : 파일 앞부분(시그니처)으로 종류를 확인합니다. 이미지가 아니면 None."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 12:
        return None
    head = bytes(blob[:12])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


@socketio.on("mail_read")
def on_mail_read(data):
    me, is_gm, room = _mail_identity(request.sid)
    if me and mailbox_mod.shared_mailbox().mark_read((data or {}).get("id"), me):
        _emit_mail_data(request.sid)


@socketio.on("mail_delete")
def on_mail_delete(data):
    me, is_gm, room = _mail_identity(request.sid)
    if me and mailbox_mod.shared_mailbox().delete((data or {}).get("id"), me, is_gm=is_gm):
        _emit_mail_data(request.sid)


# ----------------------------------------------------------------------
# 기숙사(마이룸) : 운영진이 관(6명)을 배치하고, 각자 자기 방을 도트 가구로 꾸밉니다 (모든 방 공용)
# ----------------------------------------------------------------------
DORM_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dorm_assets")
os.makedirs(DORM_ASSET_DIR, exist_ok=True)
DORM_ASSET_MAX_BYTES = IMAGE_UPLOAD_MAX_BYTES


# ----------------------------------------------------------------------
# 맵(일반 룸) : 장소 · 챕터 해금. 러너에게는 잠긴 장소·챕터 내용을 보내지 않으므로 접속마다 따로 보냅니다.
# ----------------------------------------------------------------------
WORLD_IMG_DIR = os.path.join(_THIS_DIR, "static", "world")
WORLD_IMG_MAX_BYTES = IMAGE_UPLOAD_MAX_BYTES


def _world_broadcast():
    w = world_mod.shared_world()
    gm_payload, pub_payload, play_payload = w.payload(True), w.payload(False), w.payload_play()
    for sid, info in list(CONNECTIONS.items()):
        room = get_room(info.get("room_id"))
        if room is not None and room.battle_type == "play":
            socketio.emit("world_data", play_payload, to=sid)
        else:
            socketio.emit("world_data", gm_payload if _require_gm_or_guest_gm(sid) is not None else pub_payload, to=sid)


@socketio.on("world_get")
def on_world_get(data=None):
    info = CONNECTIONS.get(request.sid)
    room = get_room(info["room_id"]) if info else None
    if room is not None and room.battle_type == "play":
        emit("world_data", world_mod.shared_world().payload_play())
        return
    emit("world_data", world_mod.shared_world().payload(_require_gm_or_guest_gm(request.sid) is not None))


@socketio.on("world_save")
def on_world_save(data):
    if _require_gm_or_guest_gm(request.sid) is None:
        emit("action_error", {"message": "운영진만 맵을 편집할 수 있습니다."})
        return
    world_mod.shared_world().set_all(data or {})
    emit("world_result", {"ok": True, "message": "맵이 저장되었습니다."})
    _world_broadcast()


@socketio.on("world_image")
def on_world_image(data):
    """운영진 : 장소 아이콘 그림 올리기 → 주소를 돌려줍니다(저장은 world_save로)."""
    if _require_gm_or_guest_gm(request.sid) is None:
        return
    data = data or {}
    blob = data.get("data")
    ext = os.path.splitext((data.get("filename") or "").lower())[1]
    if ext not in (".png", ".gif", ".webp", ".jpg", ".jpeg") or not isinstance(blob, (bytes, bytearray)):
        emit("world_result", {"ok": False, "message": "PNG · JPG · GIF · WEBP 이미지만 등록할 수 있습니다."})
        return
    if len(blob) > WORLD_IMG_MAX_BYTES:
        emit("world_result", {"ok": False, "message": f"{IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB 이하의 이미지만 등록할 수 있습니다."})
        return
    os.makedirs(WORLD_IMG_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(WORLD_IMG_DIR, filename), "wb") as f:
        f.write(blob)
    emit("world_image_result", {"ok": True, "url": f"/static/world/{filename}", "for": data.get("for")})


def _dorm_broadcast():
    socketio.emit("dorm_data", dorm_mod.shared_dorms().payload())


@socketio.on("dorm_get")
def on_dorm_get(data=None):
    me, is_gm, room = _mail_identity(request.sid)
    dorms = dorm_mod.shared_dorms()
    payload = dorms.payload()
    if room is not None:
        payload["roster"] = _mail_candidates(room)
    if is_gm:
        # 운영진 관리 화면 : 기간마다의 배치(다음 기간을 미리 짜 둘 수 있게)
        payload["period_halls"] = dorms.period_halls()
        payload["period_defaults"] = dorms.period_defaults()
    emit("dorm_data", payload)


@socketio.on("dorm_period_set")
def on_dorm_period_set(data):
    """운영진 : 지금 마이룸 기간을 바꿉니다(1차 기숙사 → 2차 캠프 → 3차 선실)."""
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm:
        emit("dorm_result", {"ok": False, "message": "운영진만 기간을 바꿀 수 있어요."})
        return
    dorms = dorm_mod.shared_dorms()
    try:
        dorms.set_current((data or {}).get("period"))
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    meta = dorms.period_meta(dorms.current)
    emit("dorm_result", {"ok": True, "message": f"지금 마이룸을 {meta['no']}차 {meta['name']}(으)로 바꿨어요."})
    _dorm_broadcast()
    _broadcast_all_rooms()  # 진영 표시(1·3차 Resonans / 2차 使徒·Void)가 기간을 따라갑니다
    on_dorm_get()


@socketio.on("dorm_default_save")
def on_dorm_default_save(data):
    """운영진 : 기간별 기본 방 꾸밈 저장(기숙사 · 캠프 · 선실이 서로 다르게 생긴 기본 방)."""
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm:
        emit("dorm_result", {"ok": False, "message": "운영진만 기본 방을 꾸밀 수 있어요."})
        return
    dorms = dorm_mod.shared_dorms()
    data = data or {}
    try:
        dorms.set_period_default(data.get("period"), data)
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    meta = dorms.period_meta(data.get("period"))
    emit("dorm_result", {"ok": True, "message": f"{meta['no']}차 {meta['name']} 기본 방을 저장했어요.", "default_saved": True})
    _dorm_broadcast()
    on_dorm_get()


@socketio.on("dorm_past_get")
def on_dorm_past_get(data=None):
    """지난 기간의 내 방 : 본인(로그인한 캐릭터)에게만 보냅니다. 다른 사람 이름을 물어도 내 것만 줍니다."""
    me, is_gm, room = _mail_identity(request.sid)
    if not me or is_gm:
        emit("dorm_past", {"owner": None, "rooms": []})
        return
    emit("dorm_past", {"owner": me, "rooms": dorm_mod.shared_dorms().past_rooms_of(me)})


@socketio.on("dorm_room_get")
def on_dorm_room_get(data):
    name = ((data or {}).get("name") or "").strip()
    if name:
        emit("dorm_room", dorm_mod.shared_dorms().room(name))


@socketio.on("dorm_room_save")
def on_dorm_room_save(data):
    data = data or {}
    owner = (data.get("owner") or "").strip()
    me, is_gm, room = _mail_identity(request.sid)
    if not owner or (me != owner and not is_gm):
        emit("dorm_result", {"ok": False, "message": "자기 방만 꾸밀 수 있어요."})
        return
    dorms = dorm_mod.shared_dorms()
    if dorms.hall_of(owner) is None:
        emit("dorm_result", {"ok": False, "message": "아직 마이룸이 배정되지 않았어요."})
        return
    saved = dorms.save_room(owner, data)
    emit("dorm_result", {"ok": True, "message": "방을 저장했어요."})
    socketio.emit("dorm_room", saved)
    _dorm_broadcast()


DORM_MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dorm_music")
os.makedirs(DORM_MUSIC_DIR, exist_ok=True)
DORM_MUSIC_MAX_BYTES = AUDIO_UPLOAD_MAX_BYTES


def _dorm_owner_only(owner):
    """방 음악·대사는 그 방 주인 본인만 바꿀 수 있습니다(운영진 대리 불가)."""
    me, is_gm, room = _mail_identity(request.sid)
    dorms = dorm_mod.shared_dorms()
    if not owner or me != owner or dorms.hall_of(owner) is None:
        emit("dorm_result", {"ok": False, "message": "자기 방에서만 바꿀 수 있어요."})
        return None
    return dorms


@socketio.on("dorm_music_upload")
def on_dorm_music_upload(data):
    data = data or {}
    owner = (data.get("owner") or "").strip()
    dorms = _dorm_owner_only(owner)
    if dorms is None:
        return
    blob = data.get("data")
    ext = os.path.splitext((data.get("filename") or "").lower())[1]
    if ext not in (".mp3", ".ogg", ".wav", ".m4a") or not isinstance(blob, (bytes, bytearray)):
        emit("dorm_result", {"ok": False, "message": "mp3·ogg·wav·m4a 음악 파일만 올릴 수 있어요."})
        return
    if len(blob) > DORM_MUSIC_MAX_BYTES:
        emit("dorm_result", {"ok": False, "message": f"음악 파일이 너무 커요 (최대 {AUDIO_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
        return
    filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(DORM_MUSIC_DIR, filename), "wb") as f:
        f.write(blob)
    title = os.path.splitext(data.get("filename") or "")[0].strip()[:60] or "음악"
    old = dorms.set_music(owner, {"url": f"/static/dorm_music/{filename}", "title": title})
    if old and (old.get("url") or "").startswith("/static/dorm_music/"):
        try:
            os.remove(os.path.join(DORM_MUSIC_DIR, os.path.basename(old["url"])))
        except OSError:
            pass
    emit("dorm_result", {"ok": True, "message": "방 음악을 등록했어요."})
    socketio.emit("dorm_room", dorms.room(owner))
    _dorm_broadcast()


@socketio.on("dorm_music_clear")
def on_dorm_music_clear(data):
    owner = ((data or {}).get("owner") or "").strip()
    dorms = _dorm_owner_only(owner)
    if dorms is None:
        return
    old = dorms.set_music(owner, None)
    if old and (old.get("url") or "").startswith("/static/dorm_music/"):
        try:
            os.remove(os.path.join(DORM_MUSIC_DIR, os.path.basename(old["url"])))
        except OSError:
            pass
    socketio.emit("dorm_room", dorms.room(owner))


@socketio.on("dorm_line_save")
def on_dorm_line_save(data):
    data = data or {}
    owner = (data.get("owner") or "").strip()
    dorms = _dorm_owner_only(owner)
    if dorms is None:
        return
    dorms.set_line(owner, data.get("text"))
    emit("dorm_result", {"ok": True, "message": "방 주인 대사를 바꿨어요."})
    socketio.emit("dorm_room", dorms.room(owner))


@socketio.on("dorm_hall_rename")
def on_dorm_hall_rename(data):
    data = data or {}
    me, is_gm, room = _mail_identity(request.sid)
    if me is None:
        emit("dorm_result", {"ok": False, "message": "캐릭터로 로그인해야 해요."})
        return
    try:
        dorm_mod.shared_dorms().rename_hall(data.get("id"), data.get("name"), me, is_gm)
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    emit("dorm_result", {"ok": True, "message": "관 이름을 바꿨어요."})
    _dorm_broadcast()


@socketio.on("dorm_guestbook_write")
def on_dorm_guestbook_write(data):
    data = data or {}
    owner = (data.get("owner") or "").strip()
    me, is_gm, room = _mail_identity(request.sid)
    if me is None:
        emit("dorm_result", {"ok": False, "message": "캐릭터로 로그인해야 방명록을 쓸 수 있어요."})
        return
    dorms = dorm_mod.shared_dorms()
    try:
        dorms.write_guestbook(owner, me, data.get("text"))
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    emit("dorm_result", {"ok": True, "message": "방명록을 남겼어요."})
    socketio.emit("dorm_room", dorms.room(owner))


@socketio.on("dorm_guestbook_delete")
def on_dorm_guestbook_delete(data):
    data = data or {}
    owner = (data.get("owner") or "").strip()
    me, is_gm, room = _mail_identity(request.sid)
    if me is None:
        return
    dorms = dorm_mod.shared_dorms()
    try:
        dorms.delete_guestbook(owner, data.get("author"), me, is_gm)
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    socketio.emit("dorm_room", dorms.room(owner))


@socketio.on("dorm_halls_save")
def on_dorm_halls_save(data):
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm:
        emit("dorm_result", {"ok": False, "message": "운영진만 마이룸을 배치할 수 있어요."})
        return
    dorms = dorm_mod.shared_dorms()
    period = (data or {}).get("period") or dorms.current
    dorms.set_halls((data or {}).get("halls"), set(_mail_candidates(room)), period)
    meta = dorms.period_meta(period)
    emit("dorm_result", {"ok": True, "message": f"{meta['no']}차 {meta['name']} 배치를 저장했어요."})
    _dorm_broadcast()
    on_dorm_get()


@socketio.on("dorm_asset_upload")
def on_dorm_asset_upload(data):
    """도트·그림 자료 올리기 : 운영진은 모든 종류(모두가 씀), 참가자는 가구 · 캐릭터 SD만(자기 방에서 씀)."""
    data = data or {}
    me, is_gm, room = _mail_identity(request.sid)
    category = data.get("category")
    if not is_gm:
        if not me:
            emit("dorm_result", {"ok": False, "message": "캐릭터로 로그인 후 이용할 수 있습니다."})
            return
        if category not in dorm_mod.USER_CATEGORIES:
            emit("dorm_result", {"ok": False, "message": "가구와 캐릭터 SD만 등록할 수 있습니다."})
            return
    blob = data.get("data")
    ext = os.path.splitext((data.get("filename") or "").lower())[1]
    if ext not in (".png", ".gif", ".webp") or not isinstance(blob, (bytes, bytearray)):
        emit("dorm_result", {"ok": False, "message": "png/gif/webp 이미지만 올릴 수 있어요."})
        return
    if len(blob) > DORM_ASSET_MAX_BYTES:
        emit("dorm_result", {"ok": False, "message": f"이미지가 너무 커요 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
        return
    filename = f"{uuid.uuid4().hex}{ext}"
    try:
        asset = dorm_mod.shared_dorms().add_asset(
            data.get("name"), category, f"/static/dorm_assets/{filename}", data.get("w"), data.get("h"),
            data.get("credit"), owner=None if is_gm else me, lines=data.get("lines"),
            scale=data.get("scale"), px=data.get("px", True) is not False)
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    with open(os.path.join(DORM_ASSET_DIR, filename), "wb") as f:
        f.write(blob)
    emit("dorm_result", {"ok": True, "message": "아이템이 등록되었습니다.", "asset_id": asset["id"]})
    _dorm_broadcast()


@socketio.on("dorm_asset_update")
def on_dorm_asset_update(data):
    """자료 이름 · 캐릭터 대사 고치기 : 운영진은 모든 자료, 참가자는 자기가 올린 자료만."""
    data = data or {}
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm and not me:
        return
    keys = ("name", "category", "w", "h", "credit", "lines") if is_gm else ("name", "lines")
    fields = {k: data[k] for k in keys if k in data}
    try:
        dorm_mod.shared_dorms().update_asset(data.get("id"), by=me, is_gm=is_gm, **fields)
    except dorm_mod.DormError as e:
        emit("dorm_result", {"ok": False, "message": str(e)})
        return
    emit("dorm_result", {"ok": True, "message": "저장되었습니다."})
    _dorm_broadcast()


@socketio.on("dorm_asset_delete")
def on_dorm_asset_delete(data):
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm and not me:
        return
    if dorm_mod.shared_dorms().delete_asset((data or {}).get("id"), by=me, is_gm=is_gm):
        emit("dorm_result", {"ok": True, "message": "아이템이 삭제되었습니다."})
        _dorm_broadcast()


@socketio.on("dorm_credits_save")
def on_dorm_credits_save(data):
    me, is_gm, room = _mail_identity(request.sid)
    if not is_gm:
        return
    dorm_mod.shared_dorms().set_credits((data or {}).get("credits"))
    emit("dorm_result", {"ok": True, "message": "출처를 저장했어요."})
    _dorm_broadcast()


SCENE_WEATHERS = ("none", "snow", "blizzard", "rain", "storm", "lightning", "fog", "sakura", "leaves", "dandelion",
                  "fireflies", "embers", "ash", "sand", "bloodrain", "meteors", "hail", "aurora", "godrays", "stars",
                  "water", "arrows", "smoke", "poison", "feathers", "arcane", "glitch")


@socketio.on("set_battle_thumb")
def on_set_battle_thumb(data):
    """운영진 : 룸 목록 카드에 보일 전투 썸네일(없으면 배경 · 맵 이미지를 써요)."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None or room.battle_type not in BATTLE_TYPES_SCHEDULED:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    data = data or {}
    if data.get("clear"):
        room.thumb = None
    else:
        blob = data.get("data")
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in MAP_BG_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png/apng/jpg/webp/gif 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > MAP_BG_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"thumb_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MAP_BG_DIR, filename), "wb") as f:
            f.write(blob)
        room.thumb = f"/static/map_bg/{filename}"
    save_rooms()
    broadcast_state(room)
    _broadcast_battle_lists()


@socketio.on("set_scene")
def on_set_scene(data):
    """운영진 : 화면 전체 배경 이미지(png/apng/gif/webp/jpg)와 날씨 효과."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 배경·날씨를 바꿀 수 있습니다."})
        return
    data = data or {}
    base = {"url": None, "dim": 40, "weather": "none", "amount": 2, "layer": "back"}
    cfg = dict(base, **(getattr(room, "scene", None) or {}))
    if data.get("reset_image"):
        cfg["url"] = None
    blob = data.get("data")
    if blob is not None:
        ext = os.path.splitext((data.get("filename") or "").lower())[1]
        if ext not in MAP_BG_ALLOWED_EXTS or not isinstance(blob, (bytes, bytearray)):
            emit("action_error", {"message": "png/apng/jpg/webp/gif 이미지만 올릴 수 있습니다."})
            return
        if len(blob) > SCENE_MAX_BYTES:
            emit("action_error", {"message": f"이미지가 너무 큽니다 (최대 {IMAGE_UPLOAD_MAX_BYTES // (1024 * 1024)}MB)."})
            return
        filename = f"scene_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(MAP_BG_DIR, filename), "wb") as f:
            f.write(blob)
        cfg["url"] = f"/static/map_bg/{filename}"
    if "dim" in data:
        cfg["dim"] = _clamp_int(data["dim"], 0, 90, cfg["dim"])
    if data.get("weather") in SCENE_WEATHERS:
        cfg["weather"] = data["weather"]
    if "amount" in data:
        cfg["amount"] = _clamp_int(data["amount"], 1, 3, cfg["amount"])
    if data.get("layer") in ("back", "front"):
        cfg["layer"] = data["layer"]
    room.scene = cfg
    save_rooms()
    broadcast_state(room)


CHAT_SEND_CAP = 200   # 상태를 보낼 때 함께 보내는 최근 채팅 수(더 예전 것은 '더보기'로 받아요)
CHAT_OLDER_PAGE = 200


@socketio.on("chat_older")
def on_chat_older(data):
    """채팅창 '이전 대화 더보기' : before(지금 보이는 가장 오래된 채팅 id) 앞의 대화를 한 번에 200개씩 보냅니다.
    공용 채팅 기록(room.chat_log)만 보내므로 아군 회의(팀 전용)는 들어가지 않습니다."""
    info = CONNECTIONS.get(request.sid)
    room = get_room(info["room_id"]) if info else None
    if room is None:
        return
    before = (data or {}).get("before")
    log = room.chat_log
    idx = next((i for i, e in enumerate(log) if e.get("id") == before), None)
    if idx is None:
        idx = max(0, len(log) - CHAT_SEND_CAP)
    start = max(0, idx - CHAT_OLDER_PAGE)
    emit("chat_older_result", {"entries": [_with_chat_id(e) for e in log[start:idx]], "has_more": start > 0})


@socketio.on("chat_delete")
def on_chat_delete(data):
    """운영진 : 채팅 메시지 한 줄 삭제. 모든 접속자 화면에서도 바로 지워집니다."""
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 메시지를 삭제할 수 있습니다."})
        return
    msg_id = (data or {}).get("id")
    if not msg_id:
        return
    before = len(room.chat_log)
    room.chat_log = [e for e in room.chat_log if e.get("id") != msg_id]
    if len(room.chat_log) != before:
        mark_runtime_dirty()
    socketio.emit("chat_deleted", {"id": msg_id}, room=room_channel(room.id, "all"))


def _backup_loop():
    """자동 백업 : 켤 때 한 번, 그 뒤로 backup.BACKUP_HOURS 시간마다 backups/에 zip으로."""
    while True:
        try:
            save_runtime()
            try:
                loop_mod.shared_book().flush()
            except Exception:
                pass
            path = backup_mod.make_backup()
            print(f"[backup] 저장했어요: {path}")
            if backup_mod.LAST.get("extra_ok") is False:
                errlog.record("server", f"백업 추가 폴더 복사 실패: {backup_mod.LAST.get('extra_err')}", where="backup")
        except Exception as e:
            print(f"[backup] 실패: {e}")
            errlog.record("server", f"백업 실패: {e}", where="backup", detail=traceback.format_exc())
        socketio.sleep(backup_mod.BACKUP_HOURS * 3600)


def _runtime_save_loop():
    """전투 진행 상태(HP/턴/로그/채팅/음악 등)를 3초마다 디스크에 저장합니다(바뀐 게 있을 때만)."""
    while True:
        socketio.sleep(3)
        try:
            save_runtime()
        except Exception as e:
            print(f"[runtime save] 실패: {e}")


# ----------------------------------------------------------------------
# 모의전투 데모 방 : 지금까지의 화면 디자인(지도 표시 · 전조 · 로그 · 스킬 컷인 · 채팅 카드)을
# 한눈에 볼 수 있도록, 가상의 러너와 NOVA로 마스 레이드를 1라운드 반 진행해 둔 방을 만듭니다.
# 데모 캐릭터는 이 방 전투 안에만 있고 캐릭터 목록(characters.json)에는 저장하지 않습니다.
# ----------------------------------------------------------------------
DEMO_ROOM_NAME = "모의전투 · 디자인 미리보기"
DEMO_SEED = 14  # 10라운드 동안 모든 표시(회피 성공 · 방어 크리티컬 · 다운/복귀/사망 …)가 한 번 이상 나오는 값

_DEMO_RUNNERS = [
    # 이름, 역할, 스킬, (체력, 공격, 방어, 이능, 정신, 민첩, 행운), 컷인 (모션, 제목, 대사, 본문)
    ("레아", "가디언", "차폐", (5, 2, 3, 3, 4, 2, 3), ("shutter", "PRISM WALL", "아무도 못 지나가.", "빛의 장벽이 아군을 감쌉니다.")),
    ("카이", "가디언", "편광", (5, 2, 3, 2, 3, 3, 2), ("impact", "POLARIZE", "전부 나한테 와.", "흩어진 공격이 한 점으로 모입니다.")),
    ("세린", "스트라이커", "붕괴", (3, 3, 1, 5, 3, 4, 4), ("slash", "COLLAPSE", "무너져라.", "공간이 갈라지며 두 번의 일격이 떨어집니다.")),
    ("도윤", "스트라이커", "방출", (3, 3, 1, 4, 3, 3, 3), ("burst", "EMISSION", "남김없이 태운다.", "모든 적에게 빛이 쏟아집니다.")),
    ("하루", "스트라이커", "붕괴", (3, 3, 2, 4, 2, 5, 5), ("glitch", "BREAK CODE", "버그는 지운다.", "")),
    ("미오", "메딕", "환류", (4, 1, 2, 3, 5, 2, 4), ("rise", "REFLUX", "흘러간 만큼 돌려줄게.", "생명이 아군에게 되돌아갑니다.")),
    ("유나", "메딕", "복원", (4, 1, 2, 3, 5, 3, 3), ("fade", "RESTORE", "다시 일어나.", "따뜻한 빛이 전장을 덮습니다.")),
    ("한결", "가디언", None, (5, 2, 3, 2, 3, 1, 2), None),
    ("리안", "스트라이커", None, (3, 3, 1, 3, 2, 5, 3), None),
    ("시온", "메딕", None, (4, 1, 2, 2, 4, 2, 3), None),
    ("이든", "스트라이커", None, (3, 3, 1, 3, 2, 3, 2), None),
    ("노아", "가디언", None, (4, 2, 3, 2, 3, 2, 1), None),
]
_DEMO_COLORS = ["#7aa2ff", "#b98cff", "#ff8fa3", "#ffb86b", "#6fe3c1", "#9ad0ff", "#f5d76e",
                "#c0c4cc", "#ff9e7a", "#8fdca8", "#d7a6ff", "#a0b4c8"]


class _DemoCharacterDB(CharacterDatabase):
    """데모 방 전용 캐릭터 목록 - 파일을 읽거나 쓰지 않습니다."""
    def __init__(self):
        self.path = None
        self.characters = {}

    def load(self):
        pass

    def save(self):
        pass


def _demo_character_db():
    db = _DemoCharacterDB()
    for i, (name, role, skill, st, fx) in enumerate(_DEMO_RUNNERS):
        entry = {"role": role, "stats": dict(zip(config.STAT_KEYS, st)), "color": _DEMO_COLORS[i % len(_DEMO_COLORS)]}
        if skill:
            entry["skill"] = skill
        if fx:
            motion, title, catch, body = fx
            entry.update({"skill_log_type": "text", "cutin_motion": motion, "skill_log_title": title,
                          "catchphrase": catch, "skill_log_text": body})
        db.characters[name] = entry
    db.characters["NOVA"] = {"role": "스트라이커", "stats": dict(zip(config.STAT_KEYS, (5, 3, 3, 5, 5, 2, 3)))}
    return db


def _demo_chat(room, nickname, text, category="player", role="guest"):
    _mirror_round_logs(room)  # 라운드 안내 채팅이 대화 사이 제자리에 들어가도록 먼저 옮깁니다
    entry = {"time": time.strftime("%H:%M:%S"), "nickname": nickname, "role": role, "category": category, "text": text}
    room.chat_log.append(_with_chat_id(entry))


def _demo_reveal_telegraph(room, battle, cells):
    _mirror_round_logs(room)
    room.telegraph_cells = [list(c) for c in cells]
    room.telegraph_round_no = battle.round_no
    text = f"전조 공개 : {len(cells)}칸에 곧 재해가 발생합니다." if cells else "전조 공개 : 이번 라운드는 재해 구역이 없습니다."
    battle.log_event(text, tag="system")
    post_system_chat(room, text, nickname="전조")


def _demo_act(room, battle, action_type, payload, problems):
    """battle_action 처리와 같은 순서로 행동 하나를 적용합니다(권한 확인만 생략)."""
    actor_field = ACTOR_FIELD.get(action_type)
    actor_name = payload.get(actor_field) if actor_field else None
    actor_char = battle.find_character(actor_name) if actor_name else None
    try:
        ACTION_HANDLERS[action_type](battle, payload)
    except BattleError as e:
        problems.append(f"{action_type} {payload}: {e}")
        return
    emit_action_sfx(room, actor_char.name if actor_char else actor_name, action_type)
    emit_attack_lines(room, action_type, payload)
    _maybe_relocate_boss(battle, actor_char)
    _maybe_resolve_telegraph_damage(room, battle)
    _mirror_round_logs(room)


def build_demo_room():
    """모의전투 데모 방을 새로 만들고, 행동을 미리 진행해 둔 뒤 방을 돌려줍니다."""
    room = create_room("mass_raid", name=DEMO_ROOM_NAME)
    formula_overrides = config.load_profile_overrides(room.battle_type)
    size = GRID_SIZES["mass_raid"]
    room.game.db = _demo_character_db()
    problems = []
    try:
        names = [r[0] for r in _DEMO_RUNNERS]
        room.game.start_battle(
            names, ["NOVA"], forced_first_team=Battle.TEAM_A, formula_overrides=formula_overrides,
            site_auto_defense=True, grid_width=size, grid_height=size,
        )
        battle = room.game.battle
        battle._started_label = config.et_stamp()
        _apply_battle_rules(room, formula_overrides, size, size)

        # 자리 : NOVA는 왼쪽 위에서 시작(1라운드 뒤 가운데로 이동 — 보스 이동 안내 확인용),
        # 러너는 주변에 흩어 두고 한 명은 지도 구석(가장자리 테두리 확인용)에.
        for c in battle.team_b:
            ox, oy = config.BOSS_SECTION_OFFSETS.get(c.boss_section, (0, 0))
            c.grid_pos = (2 + ox, 1 + oy)
        spots = {"레아": (5, 5), "카이": (8, 6), "세린": (4, 7), "도윤": (9, 9), "하루": (6, 9),
                 "미오": (3, 4), "유나": (10, 4), "한결": (5, 9), "리안": (8, 3), "시온": (2, 10),
                 "이든": (11, 10), "노아": (0, 13)}
        for c in battle.team_a:
            c.grid_pos = spots[c.name]

        # 장면용 상태 : 몇 명은 이미 다친 상태로 시작합니다(HP 막대 색 · 로그의 HP 변화 확인용).
        for name, ratio in (("하루", 0.5), ("노아", 0.05), ("이든", 0.4), ("세린", 0.7)):
            ch = battle.find_character(name)
            if ch is not None:
                ch.current_hp = max(1, int(ch.max_hp * ratio))

        _demo_chat(room, "GM", "모의전투를 시작합니다. 지도 · 로그 · 채팅의 표시를 확인하는 데모 방이에요.",
                   category="operator", role="gm")
        post_system_chat(room, "전투가 시작됩니다. 선공 팀은 러너 팀입니다.\n제한시간 내 행동해 주세요.", nickname="GM")

        # NOVA는 10라운드를 버티도록 체력을 넉넉히(부위별) 잡습니다.
        for c in battle.team_b:
            c.max_hp = c.current_hp = 2600
            battle.round_start_hp[c.name] = c.current_hp
        for c in battle.team_a:
            battle.round_start_hp[c.name] = c.current_hp

        rng = random.Random(DEMO_SEED)  # 데모는 매번 같은 흐름이 되도록 고정된 난수
        random.seed(DEMO_SEED)  # 전투 굴림(다이스 · 크리티컬)도 고정 — 끝나면 다시 무작위로 돌려 둡니다
        act = lambda t, p: _demo_act(room, battle, t, p, problems)
        alive = lambda team: [c for c in team if c.is_alive and c.status not in ("dead", "fled", "fleeing")]

        def boss_alive():
            return [c for c in battle.team_b if c.is_alive]

        def can_act(c):
            return c.is_alive and not c.has_acted and c.status not in ("dead", "fled", "fleeing")

        def try_move(c, prefer=None):
            if c.moved_this_round or not c.is_alive or c.grid_pos is None:
                return
            offs = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4) if (dx, dy) != (0, 0)]
            rng.shuffle(offs)
            if prefer:
                offs.sort(key=lambda o: -(o[0] * prefer[0] + o[1] * prefer[1]))
            for dx, dy in offs[:20]:
                x, y = c.grid_pos[0] + dx, c.grid_pos[1] + dy
                try:
                    battle.perform_move(c.name, x, y)
                    return
                except BattleError:
                    continue

        def boss_attack(part, target):
            """지휘로 묶여 있으면 그 가디언을 칩니다."""
            if part.commanded_by:
                g = battle.find_character(part.commanded_by)
                if g is not None and g.is_alive:
                    target = g
            act("attack", {"attacker": part.name, "target": target.name})

        def lowest(team):
            cands = [c for c in alive(team)]
            return min(cands, key=lambda c: c.current_hp / max(1, c.max_hp)) if cands else None

        def random_cells(n, avoid_center=True):
            cells = set()
            while len(cells) < n:
                x, y = rng.randrange(0, size), rng.randrange(0, size)
                if avoid_center and 5 <= x <= 8 and 5 <= y <= 8:
                    continue
                cells.add((x, y))
            return sorted(cells)

        def telegraph_for(rnd):
            if rnd == 4:
                return []  # 재해 구역 없는 라운드
            shapes = [
                [(x, 9) for x in range(3, 11)] + [(4, 10), (5, 10)],
                [(x, y) for x in (9, 10, 11) for y in (2, 3, 4)],
                [(2, y) for y in range(2, 12)],
                [],
                [(x, y) for x in range(0, 4) for y in range(10, 14)],
                random_cells(10),
                [(x, x) for x in range(0, 14) if not 5 <= x <= 8],
                [(x, 3) for x in range(0, 14)],
                random_cells(14),
                [(x, y) for x in range(9, 13) for y in range(8, 12)],
            ]
            return shapes[rnd - 1]

        chat_lines = {
            1: [("하루", "아래 줄 전조 떴어요, 빠질게요!")],
            3: [("세린", "붕괴 연속으로 갑니다 👍"), ("관전자", "와 컷인 멋있다")],
            2: [("카이", "편광 켰어요. 이번 턴은 저한테 다 몰려요.")],
            4: [("GM", "이번 라운드는 재해가 없습니다. 몰아서 공격하세요.")],
            5: [("시온", "자리 바꿔 줄게요!"), ("이든", "저 일단 빠질게요… 도주 시도!")],
            6: [("유나", "다들 체력 확인하세요, 복원 갑니다.")],
            7: [("하루", "체력이 바닥이에요…")],
            8: [("관전자", "NOVA 체력 많이 빠졌다")],
            9: [("레아", "차폐 한 번 더 씌울게요.")],
            10: [("GM", "마지막 라운드입니다. NOVA 행동을 지켜봐 주세요.")],
        }

        guardians = ["레아", "카이", "한결", "노아"]
        strikers = ["세린", "도윤", "하루", "리안", "이든"]
        medics = ["미오", "유나", "시온"]

        for rnd in range(1, 11):
            # ---- 선공 : 러너 ----
            _demo_reveal_telegraph(room, battle, telegraph_for(rnd))
            for who, text in chat_lines.get(rnd, []):
                if who == "GM":
                    _demo_chat(room, "GM", text, category="operator", role="gm")
                elif who == "관전자":
                    _demo_chat(room, who, text, category="spectator")
                else:
                    _demo_chat(room, who, text)
            tele = set(room.telegraph_cells and map(tuple, room.telegraph_cells) or [])
            # 전조 칸에 선 러너는 대부분 빠져나가고, 몇 명은 그대로 맞습니다(전조 발동 확인용).
            for c in alive(battle.team_a):
                if c.grid_pos and tuple(c.grid_pos) in tele and rng.random() < 0.7:
                    try_move(c)
            for c in rng.sample(alive(battle.team_a), k=min(3, len(alive(battle.team_a)))):
                try_move(c)

            bosses = boss_alive()
            pick_boss = lambda: rng.choice(bosses) if bosses else None
            for name in guardians:
                c = battle.find_character(name)
                if c is None or not can_act(c):
                    continue
                if name == "노아" and rnd in (2, 5, 8):
                    continue  # 시간 초과로 남겨 둡니다
                if name == "레아":
                    if rnd in (1, 5, 9):
                        act("shield", {"name": name, "target": rng.choice(["카이", "한결", "세린"])})
                    elif rnd in (3, 7):
                        act("defend", {"tanker": name, "target": "미오"})  # 대리 방어
                    else:
                        act("command", {"guardian": name, "target": pick_boss().name})
                elif name == "카이":
                    if rnd in (2, 9):
                        act("polarize", {"name": name})
                    elif rnd % 2:
                        act("command", {"guardian": name, "target": pick_boss().name})
                    else:
                        act("attack", {"attacker": name, "target": pick_boss().name})
                elif name == "한결":
                    if rnd % 3 == 1:
                        act("guard", {"tanker": name, "target": rng.choice([x.name for x in alive(battle.team_a) if x.name in ("시온", "유나", "하루", "세린")] or ["시온"])})
                    elif rnd % 3 == 2:
                        act("defend", {"tanker": name, "target": name})
                    else:
                        act("dodge", {"name": name})
                else:
                    act("attack", {"attacker": name, "target": pick_boss().name})
            for name in strikers:
                c = battle.find_character(name)
                if c is None or not can_act(c):
                    continue
                if name == "이든" and rnd == 5:
                    act("flee", {"name": name})
                elif name == "세린" and rnd in (2, 5, 8):
                    act("collapse", {"attacker": name, "target": pick_boss().name})
                elif name == "하루" and rnd in (3, 6, 9):
                    act("collapse", {"attacker": name, "target": pick_boss().name})
                elif name == "도윤" and rnd in (1, 4, 7, 10):
                    act("emission", {"attacker": name})
                elif name == "리안" and rnd in (2, 6):
                    act("dodge", {"name": name})
                else:
                    act("attack", {"attacker": name, "target": pick_boss().name})
            for name in medics:
                c = battle.find_character(name)
                if c is None or not can_act(c):
                    continue
                # 8라운드엔 하루를 치료하지 않습니다(사망 장면). 나머지는 가장 다친 사람부터.
                pool = [x for x in battle.team_a if not (rnd == 8 and x.name == "하루")]
                low = lowest(pool)
                # 4 · 8라운드엔 맞을 공격이 남아 있는 사람을 먼저 치료합니다("피해 정산 후 회복" 확인용).
                if rnd in (4, 8):
                    hurt = [x for x in alive(pool) if x.pending_attacks]
                    if hurt:
                        low = hurt[0]
                if name == "미오" and rnd % 3 == 1:
                    act("reflux", {"name": name, "targets": [x.name for x in rng.sample(alive(battle.team_a), k=3)]})
                elif name == "유나" and rnd % 3 == 0:
                    act("restore", {"name": name, "target": low.name if low else name})
                elif name == "시온" and rnd == 5:
                    act("swap", {"medic": name, "target": "노아"})
                else:
                    act("heal", {"healer": name, "target": low.name if low else name})
            # 남은 사람은 운영진이 시간 초과 처리
            if any(can_act(c) for c in battle.team_a):
                act("timeout_unacted_runners", {})
            act("advance_turn", {})
            _maybe_resolve_telegraph_damage(room, battle)

            # ---- 후공 : NOVA ----
            targets = alive(battle.team_a)
            parts = boss_alive()
            last = rnd == 10
            # 장면 연출 : 6라운드엔 노아가, 7라운드엔 하루가 크게 맞아 다음 라운드에 다운됩니다
            # (노아는 회복으로 복귀, 하루는 회복을 못 받아 라운드 끝에 사망). 편광(2~4 · 9~10라운드)이 없는 때로 잡습니다.
            forced_hits = {6: "노아", 7: "하루"}
            if rnd in forced_hits:
                victim = battle.find_character(forced_hits[rnd])
                if victim is not None and victim.is_alive:
                    victim.current_hp = 1
            hit_already = set()
            for i, part in enumerate(parts):
                if not targets:
                    break
                if last and i >= 2:
                    break  # 마지막 라운드는 두 부위만 행동한 채로 둡니다(공격선 · 미행동 샤인 확인용).
                if part.pending_attacks and rng.random() < 0.5:
                    act("defense_settle", {"name": part.name})
                if part.boss_section == "SE" and rnd % 3 == 0 and not part.commanded_by:
                    act("heal", {"healer": part.name, "target": part.name})
                else:
                    # 볼거리 대상 우선 : 장면 연출 대상 → 수호 · 대리 방어 받은 사람(방어 크리티컬) → 회피 태세(회피 성공) → 무작위
                    focus = [battle.find_character(forced_hits[rnd])] if rnd in forced_hits else []
                    focus += [c for c in targets if c.defense_grants and c.name not in ("레아", "카이", "한결", "노아")]
                    focus += [c for c in targets if c.dodging_this_round]
                    focus += [c for c in targets if c.interceptors]  # 대리 방어가 걸린 사람(대신 맞기 확인용)
                    focus = [c for c in focus if c is not None and c.is_alive and c.name not in hit_already]
                    g = battle.find_character(part.commanded_by) if part.commanded_by else None
                    tgt = g if (g is not None and g.is_alive) else (focus[0] if focus else rng.choice(targets))
                    hit_already.add(tgt.name)
                    boss_attack(part, tgt)
            if last:
                break
            if rnd == 9:
                # 장면 연출 : 편광 중인 카이가 다 못 막은 피해를 다음 라운드 시작에 아군이 나눠 받습니다.
                kai = battle.find_character("카이")
                if kai is not None and kai.is_alive:
                    kai.polarize_overflow += 48
            act("advance_turn", {})
            if rnd == 9:
                # 마지막 장면용 : 체력 막대가 여러 색으로 보이도록 몇 명은 다친 채로 시작합니다.
                for nm, ratio in (("하루", 0.32), ("도윤", 0.58), ("노아", 0.2), ("세린", 0.75), ("시온", 0.45)):
                    ch = battle.find_character(nm)
                    if ch is not None and ch.is_alive:
                        ch.current_hp = max(1, int(ch.max_hp * ratio))
                        battle.round_start_hp[ch.name] = ch.current_hp
        for c in battle.team_a + battle.team_b:
            if c.status == "dead":
                c.current_hp = 0
    finally:
        random.seed()
        # 이후 이 방에서 캐릭터를 고치거나 새 전투를 시작하면 평소처럼 공용 캐릭터 목록을 씁니다.
        room.game.db = shared_db()
    if problems:
        print("[demo room] 건너뛴 행동:\n  " + "\n  ".join(problems))
    sync_round_timer(room)
    mark_runtime_dirty()
    return room, problems


@app.route("/create_demo_room", methods=["POST"])
def create_demo_room_route():
    if not is_admin():
        abort(403)
    room, _ = build_demo_room()
    return redirect(url_for("guest_page", room_id=room.id, key=room.guest_key))


def _ensure_demo_room_once():
    """이 기능이 들어간 뒤 서버를 처음 켤 때 한 번만 데모 방을 만들어 둡니다(지워도 다시 생기지 않습니다)."""
    if SITE_SETTINGS.get("demo_room_created"):
        return
    try:
        build_demo_room()
    except Exception as e:
        print(f"[demo room] 만들지 못했습니다: {e}")
        return
    SITE_SETTINGS["demo_room_created"] = True
    try:
        safeio.write_json(SITE_SETTINGS_PATH, SITE_SETTINGS, indent=2)
    except OSError:
        pass


# ── LOOP 방은 웹에 공개 : 운영진이 아닌 접속은 LOOP에 필요한 소켓 이벤트만 쓸 수 있어요(+ 너무 잦은 요청은 버려요). ──
PLAY_PUBLIC_EVENTS = {"join", "client_error", "loop_state", "loop_life", "loop_start", "loop_choose", "loop_solve", "loop_begin", "loop_resume",
                      "loop_next", "loop_death", "loop_finish", "loop_reset", "world_get", "mail_list"}
_SID_HITS = {}


def _sid_flood(sid, limit=40, window=10.0):
    now = time.time()
    hits = [t for t in _SID_HITS.get(sid, []) if now - t < window]
    hits.append(now)
    _SID_HITS[sid] = hits
    if len(_SID_HITS) > 20000:
        _SID_HITS.clear()
    return len(hits) > limit


def _install_play_guard():
    handlers = socketio.server.handlers.get("/", {})
    for ev, h in list(handlers.items()):
        if ev in ("connect", "disconnect"):
            continue

        def make(ev, h):
            def guarded(sid, *args):
                info = CONNECTIONS.get(sid)
                room = get_room(info["room_id"]) if info else None
                if room is not None and room.battle_type == "play" and (info.get("nickname") or "").strip().lower() != "gm":
                    if ev not in PLAY_PUBLIC_EVENTS or _sid_flood(sid):
                        return None
                return h(sid, *args)
            return guarded
        handlers[ev] = make(ev, h)


_install_play_guard()


# ── 오류 기록 : 서버 오류(소켓 · 페이지)와 참가자 화면 오류를 logs/ 에 남기고, 운영진 방 설정에서 최근 오류를 봐요 ──
@socketio.on_error_default
def _socket_error(e):
    ev = ""
    try:
        ev = (request.event or {}).get("message", "")
    except Exception:
        pass
    errlog.record("server", f"{type(e).__name__}: {e}", where=f"socket:{ev}", detail=traceback.format_exc())
    try:
        emit("action_error", {"message": "처리 중 문제가 생겼어요. 잠시 뒤에 다시 해 주세요."})
    except Exception:
        pass


@app.errorhandler(500)
def _http_error(e):
    orig = getattr(e, "original_exception", None) or e
    errlog.record("server", f"{type(orig).__name__}: {orig}", where=f"http:{request.path}", detail=traceback.format_exc())
    return "서버에 문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.", 500


_CLIENT_ERR_HITS = {}


@socketio.on("client_error")
def on_client_error(data=None):
    """참가자 화면에서 난 스크립트 오류(메시지 · 위치만). 한 접속당 1분에 5건까지만 받아요."""
    now = time.time()
    hits = [t for t in _CLIENT_ERR_HITS.get(request.sid, []) if now - t < 60]
    if len(hits) >= 5:
        return
    hits.append(now)
    _CLIENT_ERR_HITS[request.sid] = hits
    d = data or {}
    info = CONNECTIONS.get(request.sid) or {}
    where = f"{info.get('room_id', '?')} · {str(d.get('src') or '')[-80:]}:{d.get('line') or ''}"
    errlog.record("client", str(d.get("message") or "")[:300], where=where, detail=str(d.get("stack") or "")[:2000])


_BACKUP_NOW_AT = [0.0]


@socketio.on("backup_status")
def on_backup_status(data=None):
    if _require_gm_or_guest_gm(request.sid) is None:
        return
    emit("backup_status", backup_mod.status())


@socketio.on("backup_now")
def on_backup_now(data=None):
    """운영진 : 지금 바로 백업(1분에 한 번까지)."""
    if _require_gm_or_guest_gm(request.sid) is None:
        return
    if time.time() - _BACKUP_NOW_AT[0] < 60:
        emit("action_error", {"message": "방금 백업했어요. 1분 뒤에 다시 해 주세요."})
        return
    _BACKUP_NOW_AT[0] = time.time()
    try:
        save_runtime()
        try:
            loop_mod.shared_book().flush()
        except Exception:
            pass
        backup_mod.make_backup()
        emit("shop_result", {"message": "백업했어요."})
    except Exception as e:
        errlog.record("server", f"백업 실패: {e}", where="backup", detail=traceback.format_exc())
        emit("action_error", {"message": "백업에 실패했어요. 최근 오류에서 확인해 주세요."})
    emit("backup_status", backup_mod.status())


@socketio.on("error_summary")
def on_error_summary(data=None):
    if _require_gm_or_guest_gm(request.sid) is None:
        return
    emit("error_summary", errlog.summary())


if __name__ == "__main__":
    errlog.startup()
    load_rooms()
    ensure_lounge()
    load_runtime()
    _ensure_demo_room_once()
    socketio.start_background_task(_round_reminder_loop)
    socketio.start_background_task(_runtime_save_loop)
    socketio.start_background_task(_backup_loop)
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
