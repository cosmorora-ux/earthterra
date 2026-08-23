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

import os
import random
import re
import time
import uuid

from flask import Flask, request, render_template, redirect, url_for, abort, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit

import config
from battle import Battle, BattleError
from rooms import create_room, get_room, ROOMS, BATTLE_TYPE_LABELS, BATTLE_TYPE_DEFAULTS, GRID_SIZES

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-only-change-me"
socketio = SocketIO(app, async_mode="threading")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(_THIS_DIR, "static", "music")
os.makedirs(MUSIC_DIR, exist_ok=True)

# socket id -> {"room_id", "role", "nickname"}
CONNECTIONS = {}

# 참가자(guest) 링크에서 닉네임을 "GM"으로 입력해 전체 조작 권한("all")을 얻으려면
# 이 비밀번호가 필요합니다. 운영진(gm) 링크 자체는 gm_key만으로 이미 전체 권한을 가지므로
# 영향받지 않습니다.
GM_GUEST_PASSWORD = "Nexus**0010"


@app.after_request
def add_no_cache_headers(response):
    """개발 중 수정한 화면이 브라우저 캐시에 걸려 옛 버전이 보이는 걸 방지합니다."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


def room_channel(room_id: str, suffix: str) -> str:
    return f"{room_id}:{suffix}"


def post_system_chat(room, text: str, nickname: str = "system"):
    """채팅 로그에 타임스탬프가 찍힌 시스템 메시지를 남기고 전체에게 전송합니다."""
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": nickname,
        "role": "system",
        "category": "system",
        "text": text,
    }
    room.chat_log.append(entry)
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))


# ----------------------------------------------------------------------
# 페이지 라우트
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create_room", methods=["POST"])
def create_room_route():
    battle_type = request.form.get("battle_type", "pvp")
    room = create_room(battle_type)
    return redirect(url_for("gm_page", room_id=room.id, key=room.gm_key))


@app.route("/room/<room_id>/gm")
def gm_page(room_id):
    room = get_room(room_id)
    if room is None:
        abort(404)
    key = request.args.get("key", "")
    if key != room.gm_key:
        abort(403)
    guest_url = url_for("guest_page", room_id=room_id, key=room.guest_key, _external=True)
    default_team_a, default_team_b = BATTLE_TYPE_DEFAULTS.get(room.battle_type, (3, 3))
    return render_template(
        "gm.html", room_id=room_id, key=key, guest_url=guest_url,
        battle_type=room.battle_type,
        battle_type_label=BATTLE_TYPE_LABELS.get(room.battle_type, "PVP"),
        default_team_a=default_team_a, default_team_b=default_team_b,
        grid_size=GRID_SIZES.get(room.battle_type, 0),
    )


@app.route("/room/<room_id>")
def guest_page(room_id):
    room = get_room(room_id)
    if room is None:
        abort(404)
    key = request.args.get("key", "")
    if key != room.guest_key:
        abort(403)
    return render_template(
        "guest.html", room_id=room_id, key=key,
        battle_type=room.battle_type,
        battle_type_label=BATTLE_TYPE_LABELS.get(room.battle_type, "PVP"),
        grid_size=GRID_SIZES.get(room.battle_type, 0),
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
    if room is None or key != room.gm_key:
        return jsonify({"error": "권한이 없습니다."}), 403

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "파일이 없습니다."}), 400
    if not f.filename.lower().endswith(".mp3"):
        return jsonify({"error": "mp3 파일만 업로드할 수 있습니다."}), 400

    filename = f"{uuid.uuid4().hex}.mp3"
    f.save(os.path.join(MUSIC_DIR, filename))
    return jsonify({"url": url_for("static", filename=f"music/{filename}")})


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
        "defended_this_round": c.defended_this_round,
        "dodging_this_round": c.dodging_this_round,
        "protecting_ally": c.protecting_ally,
        "pending_attacks": len(c.pending_attacks),
        "stats": dict(c.stats),
        "stat_total": c.stat_total,
        "available_actions": c.available_actions(),
        "grid_pos": list(c.grid_pos) if c.grid_pos else None,
        "moved_this_round": c.moved_this_round,
        "move_range": config.calculate_move_range(c.stats, overrides=c.formula_overrides) if c.can_move else None,
        "skill": c.skill,
        "shield_hp": c.shield_hp,
        "defense_count": len(c.defense_grants),
        "polarize_active": c.polarize_active,
        "has_leech_buff": c.leech_buff_expires_round is not None,
        "boss_group": c.boss_group,
        "boss_section": c.boss_section,
    }


def _first_team_display_name(room, battle):
    """전투 시작 안내 메시지용 - 선공 팀을 화면에 쓰는 이름으로 바꿉니다.
    PVP는 카드가 위/아래 줄로 고정 표시되므로 어느 줄인지도 함께 알려줍니다."""
    is_team_a = battle.round_first_team == Battle.TEAM_A
    if room.battle_type == "pvp":
        return f"{battle.round_first_team}({'윗줄' if is_team_a else '아랫줄'})"
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
    }


def telegraph_pending(room, battle):
    """
    이번 라운드에 GM이 아직 전조(점령전 다이스 굴리기 / 마스 레이드 칸 공개)를 출력하지
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


def build_public_state(room):
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
    payload = {
        "room_id": room.id,
        "room_name": room.name,
        "battle": battle_payload,
        "log": battle.public_log if battle else [],
        "chat": room.chat_log[-200:],
        "roster": room.game.db.all_names_by_position(),
        "music": room.music,
        "telegraph_cells": room.telegraph_cells,
        "preview_teams": preview_teams,
        "server_now": time.time(),
    }
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
    payload = build_public_state(room)
    payload["operator_log"] = battle.operator_log if battle else []
    payload["can_undo"] = battle.can_undo() if battle else False
    payload["roster_detail"] = [
        {"name": name, **room.game.db.get(name)}
        for name in room.game.db.all_names_by_position()
    ]
    payload["pending_reveal"] = room.pending_reveal
    return payload


def broadcast_state(room):
    socketio.emit("public_state", build_public_state(room), room=room_channel(room.id, "all"))
    socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))


def _require_gm(sid):
    info = CONNECTIONS.get(sid)
    if info is None or info["role"] != "gm":
        return None
    return get_room(info["room_id"])


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

    if key == room.gm_key:
        role = "gm"
    elif key == room.guest_key:
        role = "guest"
    else:
        emit("error", {"message": "잘못된 접속 키입니다."})
        return

    # 참가자 링크로 닉네임을 "GM"으로 입력해 전체 조작 권한을 얻으려면 비밀번호가 맞아야 합니다.
    if role == "guest" and nickname.lower() == "gm":
        if (data.get("gm_password") or "") != GM_GUEST_PASSWORD:
            emit("error", {"message": "비밀번호가 올바르지 않습니다."})
            return

    previous = CONNECTIONS.get(request.sid)
    previous_nickname = previous["nickname"] if previous else None

    CONNECTIONS[request.sid] = {"room_id": room_id, "role": role, "nickname": nickname}
    join_room(room_channel(room_id, "all"))
    # 참가자 링크에서 닉네임 "GM"으로 (비밀번호 인증까지 마치고) 입장한 경우도 운영진 로그/수식이
    # 필요하므로 gm 채널에 넣어줍니다. 다른 이름으로 재입장(로그아웃 포함)하면 다시 빠집니다.
    if role == "gm" or nickname.lower() == "gm":
        join_room(room_channel(room_id, "gm"))
    elif role == "guest":
        leave_room(room_channel(room_id, "gm"))

    # 익명(조용히 관전만 하는 접속)은 입장/퇴장 알림을 남기지 않습니다 - 로그인한 이름만 표시합니다.
    # 아바타 동그라미를 눌러 로그아웃하면(이름 있음 → 익명으로 재입장) 퇴장 알림을 남깁니다.
    if previous_nickname and previous_nickname != "익명" and nickname == "익명":
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "nickname": "system",
            "role": "system",
            "category": "presence",
            "text": f"{previous_nickname}님이 퇴장했습니다",
        }
        room.chat_log.append(entry)
        socketio.emit("chat_message", entry, room=room_channel(room_id, "all"))
    elif nickname != "익명":
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "nickname": "system",
            "role": "system",
            "category": "presence",
            "text": f"{nickname}님이 입장했습니다 ({'운영진' if role == 'gm' else '참가자'})",
        }
        room.chat_log.append(entry)
        socketio.emit("chat_message", entry, room=room_channel(room_id, "all"))

    emit("joined", {"role": role, "room_id": room_id})
    emit("public_state", build_public_state(room))
    if role == "gm" or nickname.lower() == "gm":
        emit("gm_state", build_gm_state(room))


@socketio.on("disconnect")
def on_disconnect():
    info = CONNECTIONS.pop(request.sid, None)
    if info is None:
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    if info["nickname"] != "익명":
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "nickname": "system",
            "role": "system",
            "category": "presence",
            "text": f"{info['nickname']}님이 퇴장했습니다",
        }
        room.chat_log.append(entry)
        socketio.emit("chat_message", entry, room=room_channel(info["room_id"], "all"))


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

    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": nickname,
        "role": role,
        "category": category,
        "text": text[:500],
    }
    room.chat_log.append(entry)
    socketio.emit("chat_message", entry, room=room_channel(info["room_id"], "all"))


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
    control = resolve_control(room, info)
    if control["scope"] != "character":
        emit("action_error", {"message": "캐릭터로 입장한 뒤에만 색상을 바꿀 수 있습니다."})
        return
    name = control["name"]
    color = (data.get("color") or "").strip()
    if not _HEX_COLOR_RE.match(color):
        emit("action_error", {"message": "색상 형식이 올바르지 않습니다."})
        return
    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=color, skill=existing.get("skill"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.color = color
    broadcast_state(room)


# ----------------------------------------------------------------------
# 소켓 이벤트 : 운영진 전용 행동
# ----------------------------------------------------------------------
@socketio.on("register_characters")
def on_register_characters(data):
    room = _require_gm(request.sid)
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
    room = _require_gm(request.sid)
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
    room = _require_gm(request.sid)
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
    warns = room.game.db.add_or_update(name, role, stats, color=existing.get("color"), skill=skill)

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
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()
    room.game.db.delete(name)
    broadcast_state(room)


def _formula_fields_payload(battle_type: str = "pvp"):
    profile_overrides = config.load_profile_overrides(battle_type)
    return [
        {
            "key": f["key"],
            "label": f["label"],
            "desc": f["desc"],
            "type": "float" if f["type"] is float else "int",
            "value": profile_overrides.get(f["key"], config.get_formula_value(f["key"])),
        }
        for f in config.FORMULA_FIELDS
    ]


@socketio.on("get_formulas")
def on_get_formulas(data):
    room = _require_gm_or_guest_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 전투 수식을 열람할 수 있습니다."})
        return
    emit("formulas", {"battle_type": room.battle_type, "fields": _formula_fields_payload(room.battle_type)})


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
    emit("formulas", {"battle_type": room.battle_type, "fields": _formula_fields_payload(room.battle_type)})


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
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    room.preview_teams = {
        "team_a": data.get("team_a", []),
        "team_b": data.get("team_b", []),
    }
    broadcast_state(room)


@socketio.on("start_battle")
def on_start_battle(data):
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    forced_first_team = Battle.TEAM_A if room.battle_type == "siege" else None
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

    try:
        room.game.start_battle(
            team_a, team_b,
            forced_first_team=forced_first_team,
            formula_overrides=formula_overrides,
            site_auto_defense=site_auto_defense,
            grid_width=grid_width, grid_height=grid_height,
        )
    except BattleError as e:
        emit("action_error", {"message": str(e)})
        return

    # 점령전 거점 / 마스 레이드 적군(2팀) : 방어가 자동이라 역할과 무관하게 "방어 정산"/"공격"/"힐"만
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
                c.shield_permanent = config.SKILL_SHIELD_INITIAL

    # PVP/점령전 가디언 : 어그로 강제 행동을 마스 레이드의 '지휘'와 같은 이름으로 통일합니다
    # (기존 '공격유도'는 본인 지정 시 능동 방어가 함께 붙는 차이만 있을 뿐 같은 어그로 강제
    # 메커닉이라, 웹 버전에서는 이름과 동작을 '지휘'(CommandSkill) 하나로 합칩니다).
    # 레거시 데스크톱 버전(gui.py)은 이 오버라이드를 거치지 않으므로 기존 '공격유도' 그대로입니다.
    if room.battle_type != "mass_raid":
        for c in room.game.battle.team_a + room.game.battle.team_b:
            if c.role == config.ROLE_TANKER:
                c.forced_actions = [config.ACTION_ATTACK, config.ACTION_DEFEND, config.ACTION_COMMAND] + config.COMMON_ACTIONS

    # 격자 전투(마스 레이드/점령전) : 중앙에 몹(거점)을 두고 러너를 나머지 칸에 무작위 배치, 전원 이동 가능.
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
    room.preview_teams = None

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
        "text": f"전투가 시작됩니다. 선공 팀은 {first_team_label}입니다. 제한시간 내 행동해 주세요.",
    }
    room.chat_log.append(entry)
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
        emit("action_error", {"message": "점령전 방에서만 사용할 수 있습니다."})
        return
    value = random.randint(1, 3)
    room.site_dice_round_no = battle.round_no
    room.site_dice_value = value
    room.site_dice_used = 0
    text = f"🔮 전조 : 이번 라운드 거점은 {value}회 행동합니다."
    battle.log_event(text, tag="system")
    post_system_chat(room, text, nickname="🔮 전조")
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
        emit("action_error", {"message": "격자 전투(점령전/마스 레이드)에서만 사용할 수 있습니다."})
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
    text = f"🔮 전조 공개 : {len(cells)}칸에 곧 피해가 발생합니다."
    battle.log_event(text, tag="system")
    post_system_chat(room, text, nickname="🔮 전조")
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
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    name = (data.get("name") or "").strip()[:30]
    room.name = name or room.id
    broadcast_state(room)


@socketio.on("set_music")
def on_set_music(data):
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    music_type = data.get("type")
    if music_type == "youtube":
        video_id = extract_youtube_id(data.get("src", ""))
        if not video_id:
            emit("action_error", {"message": "유튜브 링크에서 영상 ID를 찾지 못했습니다."})
            return
        room.music = {"type": "youtube", "src": video_id, "title": data.get("title", ""), "started_at": time.time()}
    elif music_type == "mp3":
        src = (data.get("src") or "").strip()
        if not src:
            emit("action_error", {"message": "mp3 파일을 먼저 업로드해주세요."})
            return
        room.music = {"type": "mp3", "src": src, "title": data.get("title", ""), "started_at": time.time()}
    else:
        emit("action_error", {"message": "알 수 없는 음악 형식입니다."})
        return
    broadcast_state(room)


@socketio.on("stop_music")
def on_stop_music(data):
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    room.music = None
    broadcast_state(room)


ACTION_HANDLERS = {
    "attack": lambda battle, p: battle.perform_attack(p["attacker"], p["target"]),
    "self_defend": lambda battle, p: battle.perform_self_defend(p["name"]),
    "defend": lambda battle, p: battle.perform_defend(p["tanker"], p["target"]),
    "taunt": lambda battle, p: battle.perform_taunt(p["tanker"], p["target"]),
    "dodge": lambda battle, p: battle.perform_dodge(p["name"]),
    "heal": lambda battle, p: battle.perform_heal(p["healer"], p["target"]),
    "timeout": lambda battle, p: battle.perform_timeout(p["name"]),
    "timeout_unacted_runners": lambda battle, p: battle.perform_timeout_unacted_runners(),
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
}

SITE_TURN_ACTIONS = ("attack", "heal", "defense_settle")

# 마스 레이드 전용 : 라운드 제한시간이 이만큼(초) 남았을 때 미행동자 안내를 커맨드 창에 남깁니다.
MASS_RAID_REMINDER_THRESHOLDS = (300, 120, 60)  # 5분 / 2분 / 1분


def _post_mass_raid_reminder(room, battle, threshold):
    unacted = battle.unacted_members()
    living = [c for c in battle.team_a + battle.team_b if c.is_alive]
    acted_count = len(living) - len(unacted)
    minutes = threshold // 60
    names = ", ".join(unacted) if unacted else "없음"
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "system",
        "role": "system",
        "category": "system",
        "text": f"제한시간 {minutes}분 남았습니다 ({acted_count}/{len(living)}명 행동 완료) · 미완료: {names}",
    }
    room.chat_log.append(entry)
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
    for threshold in MASS_RAID_REMINDER_THRESHOLDS:
        if remaining <= threshold and threshold not in room.reminders_sent:
            room.reminders_sent.add(threshold)
            _post_mass_raid_reminder(room, battle, threshold)


def _round_reminder_loop():
    """마스 레이드 방들을 주기적으로 훑어보며 제한시간 임계값(5분/2분/1분) 안내를 보냅니다."""
    while True:
        socketio.sleep(5)
        for room in list(ROOMS.values()):
            if room.battle_type != "mass_raid":
                continue
            try:
                _mass_raid_round_reminder_check(room)
            except Exception as e:
                print(f"[round_reminder_loop] room {room.id} error: {e}")


def _maybe_auto_advance_turn(room, battle):
    """PVP/점령전 : 이번 턴에 행동해야 할 팀원이 전원 행동을 마치면(can_advance_turn), 커맨드
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
        "text": f"{battle.current_turn_team} 전원 행동 완료 — 자동으로 다음 턴으로 넘어갑니다.",
    }
    room.chat_log.append(entry)
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
    battle.log_event("BOSS 전원 행동 완료 — 새로운 자리로 이동했습니다.", tag="system")


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

    # 점령전/레이드에서 GM이 거점(2팀) 캐릭터로 행동하면, 결과를 바로 공개하지 않고
    # 운영진 로그에만 미리 보여줍니다. 마음에 들면 "공개하기"로 러너에게 알리고,
    # 마음에 안 들면 "되돌리기"로 없던 일로 만들 수 있습니다.
    actor_field = ACTOR_FIELD.get(action_type)
    actor_name = payload.get(actor_field) if actor_field else None
    actor_char = battle.find_character(actor_name) if actor_name else None

    # 점령전 : 거점이 이번 라운드 행동(방어 정산/공격/힐)을 하려면 먼저 전조(거점 행동 다이스)를
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

    # 격자 전투(점령전/마스 레이드) : 러너가 이동하려면 먼저 GM이 이번 라운드 전조를
    # 출력해야 합니다 (점령전 = 거점 다이스, 마스 레이드 = 격자 칸 공개).
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
        room.pending_reveal = {"actor": actor_char.name, "pub_len_before": pub_len_before}
        socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))
        return

    # 점령전 : 거점(2팀) 캐릭터는 이번 라운드 다이스로 정해진 횟수만큼 반복 행동할 수 있습니다.
    if room.battle_type == "siege" and room.site_dice_round_no == battle.round_no and room.site_dice_value:
        if actor_char is not None and actor_char.team == "B":
            room.site_dice_used += 1
            remaining = room.site_dice_value - room.site_dice_used
            if remaining > 0:
                actor_char.has_acted = False
                battle.log_event(f"거점 추가 행동 가능 (이번 라운드 남은 횟수 {remaining}회)", tag="system")
            else:
                battle.log_event("거점의 이번 라운드 행동이 모두 끝났습니다.", tag="system")

    _maybe_relocate_boss(battle, actor_char)
    _maybe_auto_advance_turn(room, battle)
    broadcast_state(room)


@socketio.on("reveal_pending_action")
def on_reveal_pending_action(data):
    room = _require_gm(request.sid)
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
    room.chat_log.append(entry)
    socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))

    # 점령전 : 거점 다중 행동 소모는 "공개"가 확정된 시점에만 적용됩니다.
    # (미리보기만 하고 되돌린 굴림은 이번 라운드 행동 횟수를 소모하지 않습니다)
    if room.battle_type == "siege" and room.site_dice_round_no == battle.round_no and room.site_dice_value:
        actor_char = battle.find_character(pending["actor"])
        if actor_char is not None and actor_char.team == "B":
            room.site_dice_used += 1
            remaining = room.site_dice_value - room.site_dice_used
            if remaining > 0:
                actor_char.has_acted = False
                battle.log_event(f"거점 추가 행동 가능 (이번 라운드 남은 횟수 {remaining}회)", tag="system")
            else:
                battle.log_event("거점의 이번 라운드 행동이 모두 끝났습니다.", tag="system")

    room.pending_reveal = None
    broadcast_state(room)


if __name__ == "__main__":
    socketio.start_background_task(_round_reminder_loop)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
