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
from rooms import (
    create_room, get_room, delete_room, list_rooms, load_rooms, save_rooms,
    ROOMS, BATTLE_TYPE_LABELS, BATTLE_TYPE_DEFAULTS, GRID_SIZES,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-only-change-me"
# html(templates)을 고치면 서버를 다시 켜지 않아도 브라우저 새로고침(F5)만으로 바로 반영됩니다.
app.config["TEMPLATES_AUTO_RELOAD"] = True
socketio = SocketIO(app, async_mode="threading")

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
SOUND_EFFECT_MAX_BYTES = 5 * 1024 * 1024

# socket id -> {"room_id", "role", "nickname"}
CONNECTIONS = {}

# 참가자(guest) 링크에서 닉네임을 "GM"으로 입력해 전체 조작 권한("all")을 얻으려면
# 이 비밀번호가 필요합니다. 운영진(gm) 링크 자체는 gm_key만으로 이미 전체 권한을 가지므로
# 영향받지 않습니다.
GM_GUEST_PASSWORD = "Nexus**0010"

# 전투 로그(public_log/operator_log)는 방 하나가 몇 시간씩 이어지면 수천 줄까지 쌓일 수
# 있습니다 - 매 행동마다 상태를 통째로 재전송하는 구조라, 로그를 자르지 않으면 세션이
# 길어질수록 매 행동의 전송량이 계속 불어납니다(다인원·장시간일수록 체감 지연이 커짐).
# 그래서 실제 배열은 자르지 않고(되돌리기/로그 복사가 인덱스를 그대로 쓰므로) 전송량만
# 최근 이 줄 수로 제한합니다.
LOG_SEND_CAP = 300


@app.after_request
def add_no_cache_headers(response):
    """개발 중 수정한 화면이 브라우저 캐시에 걸려 옛 버전이 보이는 걸 방지합니다."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


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
    rooms_view = [
        {
            "id": room.id,
            "name": room.name,
            "battle_type": room.battle_type,
            "battle_type_label": BATTLE_TYPE_LABELS.get(room.battle_type, room.battle_type),
            "gm_url": url_for("gm_page", room_id=room.id, key=room.gm_key, _external=True),
            "guest_url": url_for("guest_page", room_id=room.id, key=room.guest_key, _external=True),
            "gm_key": room.gm_key,
        }
        for room in list_rooms()
    ]
    return render_template("index.html", rooms=rooms_view, battle_type_labels=BATTLE_TYPE_LABELS)


@app.route("/yacht")
def yacht_page():
    return render_template("yacht.html")


@app.route("/create_room", methods=["POST"])
def create_room_route():
    battle_type = request.form.get("battle_type", "pvp")
    room_name = request.form.get("room_name", "")
    room = create_room(battle_type, name=room_name)
    return redirect(url_for("gm_page", room_id=room.id, key=room.gm_key))


@app.route("/delete_room", methods=["POST"])
def delete_room_route():
    room_id = request.form.get("room_id", "")
    key = request.form.get("key", "")
    room = get_room(room_id)
    if room is not None and key == room.gm_key:
        delete_room(room_id)
    return redirect(url_for("index"))


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
    if room is None or key not in (room.gm_key, room.guest_key):
        return jsonify({"error": "권한이 없습니다."}), 403
    if not name or not room.game.db.exists(name):
        return jsonify({"error": "존재하지 않는 캐릭터입니다."}), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "파일이 없습니다."}), 400
    ext = os.path.splitext(f.filename.lower())[1]
    if ext not in AVATAR_ALLOWED_EXTS:
        return jsonify({"error": "투명도를 지원하는 png/webp/gif 이미지만 업로드할 수 있습니다."}), 400

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
    if room is None or key not in (room.gm_key, room.guest_key):
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
        "avatar_url": data.get("avatar_url"),
        "sound_effect": data.get("sound_effect"),
        "sound_effect_volume": data.get("sound_effect_volume"),
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
    pub_log = battle.public_log if battle else []
    payload = {
        "room_id": room.id,
        "room_name": room.name,
        "battle": battle_payload,
        # 세션이 길어지면(다인원 장시간) 로그가 수천 줄까지 쌓일 수 있어서, 매번 전체를 다
        # 보내면 매 행동마다 전송량이 계속 불어납니다. 최근 LOG_SEND_CAP줄만 보내고
        # log_total(누적 총 줄 수)을 같이 보내서, 클라이언트가 "새로 추가된 부분"만 골라
        # 표시할 수 있게 합니다(battle.public_log 자체는 되돌리기/로그 복사 기능이 인덱스를
        # 그대로 쓰므로 서버 메모리에서는 자르지 않습니다).
        "log": pub_log[-LOG_SEND_CAP:],
        "log_total": len(pub_log),
        "chat": room.chat_log[-200:],
        "chat_tabs": room.chat_tabs_enabled,
        "chat_tab_labels": room.chat_tab_labels,
        "roster": room.game.db.all_names_by_position(),
        "userinfo_hidden": list(room.userinfo_hidden),
        "online_characters": sorted(_online_character_names(room)),
        # 채팅창에서 말한 사람의 프로필 이미지/닉네임 색상을 보여주기 위한 정보(전투 참여 여부와 무관).
        "roster_profiles": {
            name: {"color": data.get("color"), "avatar_url": data.get("avatar_url")}
            for name, data in room.game.db.characters.items()
            if data.get("color") or data.get("avatar_url")
        },
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
    op_log = battle.operator_log if battle else []
    payload["operator_log"] = op_log[-LOG_SEND_CAP:]
    payload["operator_log_total"] = len(op_log)
    payload["can_undo"] = battle.can_undo() if battle else False
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
    battle_key = id(battle)
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
            room.chat_log.append(entry)
            socketio.emit("chat_message", entry, room=room_channel(room.id, "all"))
    battle._chat_mirrored_len = len(log)


def broadcast_state(room):
    _mirror_round_logs(room)
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
    _sync_team_channel(room, request.sid, nickname, role)

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
    room.chat_log.append(entry)
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
        emit("action_error", {"message": "캐릭터로 입장한 뒤에만 색상을 바꿀 수 있습니다."})
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
        emit("action_error", {"message": "캐릭터로 입장한 뒤에만 표기 이름을 바꿀 수 있습니다."})
        return
    raid_display_name = (data.get("raid_display_name") or "").strip()[:10] or None
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
        emit("action_error", {"message": "캐릭터로 입장한 뒤에만 음량을 조절할 수 있습니다."})
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
    """참가자가 자신의 스킬 로그 표시 방식(텍스트/이미지)과 텍스트 내용을 지정합니다(마이페이지)."""
    info = CONNECTIONS.get(request.sid)
    if info is None:
        emit("action_error", {"message": "먼저 입장해주세요."})
        return
    room = get_room(info["room_id"])
    if room is None:
        return
    name = _mypage_target_name(room, info, data)
    if name is None:
        emit("action_error", {"message": "캐릭터로 입장한 뒤에만 설정할 수 있습니다."})
        return
    log_type = data.get("skill_log_type") if data.get("skill_log_type") in ("text", "image") else "text"
    log_text = (data.get("skill_log_text") or "").strip()[:300]
    existing = room.game.db.get(name) or {}
    room.game.db.add_or_update(
        name, existing.get("role", config.DEFAULT_ROLE), existing.get("stats", {}),
        color=existing.get("color"), skill=existing.get("skill"),
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=log_type, skill_log_text=log_text or None,
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
    )
    battle = room.game.battle
    if battle is not None:
        live = battle.find_character(name)
        if live is not None:
            live.skill_log_type = log_type
            live.skill_log_text = log_text
    broadcast_state(room)


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
    warns = room.game.db.add_or_update(
        name, role, stats, color=existing.get("color"), skill=skill,
        raid_display_name=existing.get("raid_display_name"), inventory=existing.get("inventory"),
        skill_log_type=existing.get("skill_log_type"), skill_log_text=existing.get("skill_log_text"),
avatar_url=existing.get("avatar_url"), sound_effect=existing.get("sound_effect"),
sound_effect_volume=existing.get("sound_effect_volume"),
    )

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
            alternate_first_team=(room.battle_type == "pvp"),
        )
    except BattleError as e:
        emit("action_error", {"message": str(e)})
        return

    # 전투가 방금 막 만들어져서 팀이 정해졌으므로, 이미 접속해 있던 소켓들의 아군 회의
    # 채널 소속도 다시 계산해줍니다(전투 시작 전에는 팀이 없어서 못 넣었을 것이므로).
    for sid, info in CONNECTIONS.items():
        if info.get("room_id") == room.id:
            _sync_team_channel(room, sid, info.get("nickname"), info.get("role"))

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
                c.forced_actions = [
                    config.ACTION_ATTACK, config.ACTION_GUARD, config.ACTION_DEFEND, config.ACTION_COMMAND,
                ] + config.COMMON_ACTIONS

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
    room.telegraph_damage_round_no = None
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
        "text": f"전투가 시작됩니다. 선공 팀은 {first_team_label}입니다.\n제한시간 내 행동해 주세요.",
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
    save_rooms()
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
    # 방어 : 본인 지정이면 직접 방어, 아군 지정이면 대리 방어 (모든 직군)
    "defend": lambda battle, p: battle.perform_proxy_defend(p["tanker"], p.get("target") or p["tanker"]),
    # 수호 : 가디언 전용, 지정 아군 1인에게 단순 방어 부여
    "guard": lambda battle, p: battle.perform_guard(p["tanker"], p["target"]),
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
    "declare_defer": lambda battle, p: battle.perform_declare_defer(p["name"]),
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
    group_label = next(
        (p for p in config.BOSS_NAME_PREFIXES if nw.name.startswith(p)), nw.name,
    )
    battle.log_event(f"{group_label} 전원 행동 완료 — 새로운 자리로 이동했습니다.", tag="system")


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
    _maybe_resolve_telegraph_damage(room, battle)
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
    load_rooms()
    socketio.start_background_task(_round_reminder_loop)
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
