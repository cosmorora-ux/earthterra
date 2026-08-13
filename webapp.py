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
from flask_socketio import SocketIO, join_room, emit

import config
from battle import Battle, BattleError
from rooms import create_room, get_room, BATTLE_TYPE_LABELS, BATTLE_TYPE_DEFAULTS, MASS_RAID_GRID_SIZE

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-only-change-me"
socketio = SocketIO(app, async_mode="threading")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
MUSIC_DIR = os.path.join(_THIS_DIR, "static", "music")
os.makedirs(MUSIC_DIR, exist_ok=True)

# socket id -> {"room_id", "role", "nickname"}
CONNECTIONS = {}


@app.after_request
def add_no_cache_headers(response):
    """개발 중 수정한 화면이 브라우저 캐시에 걸려 옛 버전이 보이는 걸 방지합니다."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


def room_channel(room_id: str, suffix: str) -> str:
    return f"{room_id}:{suffix}"


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
        battle_type_label=BATTLE_TYPE_LABELS.get(room.battle_type, "PVP"),
    )


_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|live/|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


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
        "role": c.role,
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
    }


def sync_round_timer(room):
    """라운드가 바뀔 때마다 제한시간 마감 시각을 새로 계산합니다. (모든 접속자가 같은 마감 시각을 봄)"""
    battle = room.game.battle
    if battle is None:
        room.round_deadline = None
        room.last_round_no = None
        return
    if room.last_round_no != battle.round_no or room.round_deadline is None:
        room.last_round_no = battle.round_no
        room.round_deadline = time.time() + config.ROUND_TIME_LIMIT_SECONDS


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
        "forced_target": battle.forced_target.name if battle.forced_target else None,
        "forced_target_team": battle.forced_target_team,
        "forced_target_count": battle.forced_target_count,
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
        battle_payload["round_limit_seconds"] = config.ROUND_TIME_LIMIT_SECONDS
    return {
        "room_id": room.id,
        "battle": battle_payload,
        "log": battle.public_log if battle else [],
        "chat": room.chat_log[-200:],
        "roster": room.game.db.all_names_by_position(),
        "music": room.music,
        "server_now": time.time(),
    }


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
    if room.battle_type == "siege":
        battle = room.game.battle
        payload["site_dice"] = {
            "round_no": room.site_dice_round_no,
            "value": room.site_dice_value,
            "used": room.site_dice_used,
            "stale": battle is not None and room.site_dice_round_no != battle.round_no,
        }
    return payload


def broadcast_state(room):
    socketio.emit("public_state", build_public_state(room), room=room_channel(room.id, "all"))
    socketio.emit("gm_state", build_gm_state(room), room=room_channel(room.id, "gm"))


def _require_gm(sid):
    info = CONNECTIONS.get(sid)
    if info is None or info["role"] != "gm":
        return None
    return get_room(info["room_id"])


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

    CONNECTIONS[request.sid] = {"room_id": room_id, "role": role, "nickname": nickname}
    join_room(room_channel(room_id, "all"))
    if role == "gm":
        join_room(room_channel(room_id, "gm"))

    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "system",
        "role": "system",
        "category": "system",
        "text": f"{nickname}님이 입장했습니다 ({'운영진' if role == 'gm' else '참가자'})",
    }
    room.chat_log.append(entry)
    socketio.emit("chat_message", entry, room=room_channel(room_id, "all"))

    emit("joined", {"role": role, "room_id": room_id})
    if role == "gm":
        emit("gm_state", build_gm_state(room))
    else:
        emit("public_state", build_public_state(room))


@socketio.on("disconnect")
def on_disconnect():
    info = CONNECTIONS.pop(request.sid, None)
    if info is None:
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": "system",
        "role": "system",
        "category": "system",
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
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "nickname": info["nickname"],
        "role": info["role"],
        "category": category,
        "text": text[:500],
    }
    room.chat_log.append(entry)
    socketio.emit("chat_message", entry, room=room_channel(info["room_id"], "all"))


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
    warns = room.game.db.add_or_update(name, role, stats)

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
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "운영진만 전투 수식을 열람할 수 있습니다."})
        return
    emit("formulas", {"battle_type": room.battle_type, "fields": _formula_fields_payload(room.battle_type)})


@socketio.on("save_formulas")
def on_save_formulas(data):
    room = _require_gm(request.sid)
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


def assign_mass_raid_positions(battle, width, height):
    """몹(2팀)은 격자 중앙 부근에 뭉쳐서, 러너(1팀)는 나머지 칸에 무작위로 배치합니다."""
    cells = [(x, y) for x in range(width) for y in range(height)]
    center = ((width - 1) / 2, (height - 1) / 2)
    cells.sort(key=lambda c: (c[0] - center[0]) ** 2 + (c[1] - center[1]) ** 2)

    used = set()
    for c in battle.team_b:
        pos = cells[len(used)]
        c.grid_pos = pos
        used.add(pos)

    remaining = [c for c in cells if c not in used]
    random.shuffle(remaining)
    for i, c in enumerate(battle.team_a):
        c.grid_pos = remaining[i]


@socketio.on("start_battle")
def on_start_battle(data):
    room = _require_gm(request.sid)
    if room is None:
        emit("action_error", {"message": "권한이 없습니다."})
        return
    forced_first_team = Battle.TEAM_A if room.battle_type == "siege" else None
    formula_overrides = config.load_profile_overrides(room.battle_type)
    site_auto_defense = room.battle_type == "siege"
    is_mass_raid = room.battle_type == "mass_raid"
    grid_width = MASS_RAID_GRID_SIZE if is_mass_raid else None
    grid_height = MASS_RAID_GRID_SIZE if is_mass_raid else None

    team_a = data.get("team_a", [])
    team_b = data.get("team_b", [])
    if is_mass_raid and len(team_a) + len(team_b) > grid_width * grid_height:
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

    # 점령전 : 거점(2팀)은 방어가 자동이라 역할과 무관하게 "방어 정산"/"공격"/"힐"만 직접 선택합니다.
    if room.battle_type == "siege":
        for c in room.game.battle.team_b:
            c.forced_actions = [config.ACTION_DEFENSE_SETTLE, config.ACTION_ATTACK, config.ACTION_HEAL]

    # 매스 레이드 : 중앙에 몹을 두고 러너를 나머지 칸에 무작위 배치, 전원 이동 가능.
    if is_mass_raid:
        assign_mass_raid_positions(room.game.battle, grid_width, grid_height)
        for c in room.game.battle.team_a + room.game.battle.team_b:
            c.can_move = True

    room.site_dice_round_no = None
    room.site_dice_value = None
    room.site_dice_used = 0
    room.pending_reveal = None
    broadcast_state(room)


@socketio.on("roll_site_dice")
def on_roll_site_dice(data):
    room = _require_gm(request.sid)
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
    battle.log_event(f"🔮 전조 : 이번 라운드 거점은 {value}회 행동합니다.", tag="system")
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
    "flee": lambda battle, p: battle.perform_flee(p["name"]),
    "defense_settle": lambda battle, p: battle.perform_defense_settle(p["name"]),
    "move": lambda battle, p: battle.perform_move(p["name"], int(p["x"]), int(p["y"])),
    "advance_turn": lambda battle, p: battle.advance_turn(),
    "undo": lambda battle, p: battle.undo_last(),
}

SITE_TURN_ACTIONS = ("attack", "heal", "defense_settle")


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

    if action_type in ("advance_turn", "undo", "timeout"):
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

    should_preview = (
        info["role"] == "gm"
        and room.battle_type in ("siege", "raid")
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
        "nickname": "🔮 적",
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
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
