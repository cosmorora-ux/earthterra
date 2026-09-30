# -*- coding: utf-8 -*-
"""
rooms.py
========
방(room) 단위 상태 관리. 방 하나 = GameManager(캐릭터 DB + 전투) 하나 + 채팅 로그 하나.
운영진 링크(gm_key)와 참가자 링크(guest_key)를 따로 발급해서 역할을 구분합니다.
"""

import json
import os
import secrets
import time

from battle import GameManager

ROOMS = {}

# 방 자체(이름/전투 유형/키 등)를 디스크에 저장해서 서버를 껐다 켜도 링크가 그대로
# 유지되게 합니다. 전투 진행 상태(HP/턴/로그 등)는 저장하지 않습니다 - 서버가 재시작되면
# 그 방은 "전투 시작 전" 상태로 돌아가고, 운영진이 다시 "전투 시작"을 누르면 됩니다.
ROOMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rooms.json")

# RoomState의 필드 중 이 목록만 rooms.json에 저장/복원합니다.
_PERSISTED_FIELDS = [
    "name", "battle_type", "gm_key", "guest_key", "created_at",
    "chat_tabs_enabled", "chat_tab_labels",
]

BATTLE_TYPE_LABELS = {
    "pvp": "PVP",
    "siege": "점령전",
    "mass_raid": "마스 레이드",
}
# 전투 유형별 팀 인원 기본값 : (1팀/러너팀 기본 인원, 2팀/GM팀 기본 인원)
BATTLE_TYPE_DEFAULTS = {
    "pvp": (3, 3),
    "siege": (5, 1),
    "mass_raid": (30, 5),
}
# 마스 레이드 격자 크기 (가로, 세로)
MASS_RAID_GRID_SIZE = 14
# 점령전 격자 크기 (가로, 세로) - 점령전도 마스 레이드처럼 격자 이동을 사용합니다.
SIEGE_GRID_SIZE = 10
# 격자 이동을 사용하는 전투 유형과 그 격자 크기
GRID_SIZES = {
    "siege": SIEGE_GRID_SIZE,
    "mass_raid": MASS_RAID_GRID_SIZE,
}


class RoomState:
    def __init__(self, room_id: str, battle_type: str = "pvp"):
        self.id = room_id
        self.name = room_id  # 화면에 표시되는 방 이름 - GM이 바꾸기 전까지는 방 ID와 같습니다.
        self.gm_key = secrets.token_urlsafe(8)
        self.guest_key = secrets.token_urlsafe(8)
        self.game = GameManager()
        self.chat_log = []  # [{"time","nickname","role","text"}, ...]
        self.created_at = time.time()
        self.round_deadline = None   # 현재 라운드의 제한시간이 끝나는 epoch 시각
        self.last_round_no = None    # round_deadline을 언제 다시 계산해야 하는지 판단하는 기준
        self.battle_type = battle_type if battle_type in BATTLE_TYPE_LABELS else "pvp"

        # 점령전(siege) 전용 : "거점" 팀(2팀/GM팀)이 이번 라운드에 몇 회 행동할 수 있는지.
        self.site_dice_round_no = None   # 이 굴림이 적용되는 라운드 번호
        self.site_dice_value = None      # 이번 라운드 거점 행동 허용 횟수 (1~3)
        self.site_dice_used = 0          # 이번 라운드에 이미 사용한 행동 횟수

        # 점령전/레이드 전용 : GM(거점/보스)의 행동을 러너에게 공개하기 전에 미리보기 상태로 잡아둡니다.
        # None이 아니면 "공개 대기 중"이며, 참가자에게는 아직 아무것도 전송되지 않은 상태입니다.
        self.pending_reveal = None  # {"actor": 이름, "pub_len_before": int} 또는 None

        # 배경음악. None이면 재생 안 함.
        # {"type": "youtube"|"mp3", "src": 유튜브 영상ID 또는 mp3 URL, "title": str, "started_at": epoch}
        # started_at 기준으로 모든 접속자가 같은 재생 위치로 맞춰서(동기화) 재생합니다.
        self.music = None

        # 마스 레이드 전용 : GM이 "전조 출력"으로 미리 찍어 러너에게 공개한 격자 칸 목록.
        # 이 칸에 곧(공격 행동과는 별개로) 무조건 피해가 발생한다는 시각적 경고입니다.
        # [[x, y], ...] 또는 공개 전/해제 상태면 빈 리스트.
        self.telegraph_cells = []
        self.telegraph_round_no = None  # 마스 레이드 : 이번 라운드에 전조를 공개했는지 (라운드 번호로 기록)
        # BOSS(2팀)의 후공 페이즈가 시작될 때 전조 피해를 라운드당 한 번만 발동시키기 위한 기록.
        self.telegraph_damage_round_no = None

        # 마스 레이드 전용 : 라운드 제한시간이 5분/2분/1분 남았을 때 미행동자 안내를 한 번씩만
        # 보내기 위한 추적 상태. 라운드가 바뀌면 reminders_sent를 비웁니다.
        self.reminders_round_no = None
        self.reminders_sent = set()  # 이번 라운드에 이미 보낸 임계값(초) 집합, 예: {300, 120}

        # 전투 시작 전 "무작위 배치" 미리보기 - {"team_a": [이름...], "team_b": [이름...]} 또는 None.
        # 전투가 실제로 시작되면(room.game.battle이 생기면) 더 이상 쓰이지 않습니다.
        self.preview_teams = None

        # 참가자 화면 채팅창에 어떤 탭을 보여줄지(운영진이 설정). 아군 회의는 로그인한
        # 캐릭터의 소속 팀에게만 보이는 채팅입니다(webapp._sync_team_channel 참고).
        self.chat_tabs_enabled = {"player": True, "spectator": True, "entry": True, "team": True}
        # 탭 이름도 운영진이 바꿀 수 있습니다(기능 자체는 그대로라 부가설명은 클라이언트에
        # 고정 텍스트로 둡니다 - 채팅 탭 설정 팝업 참고).
        self.chat_tab_labels = {"player": "참여 인원만", "spectator": "관전 인원만", "entry": "입장 기록", "team": "아군 회의"}


def create_room(battle_type: str = "pvp", name: str = None) -> RoomState:
    room_id = secrets.token_urlsafe(4)
    while room_id in ROOMS:
        room_id = secrets.token_urlsafe(4)
    room = RoomState(room_id, battle_type)
    name = (name or "").strip()[:30]
    if name:
        room.name = name
    ROOMS[room_id] = room
    save_rooms()
    return room


def delete_room(room_id: str) -> bool:
    if room_id not in ROOMS:
        return False
    del ROOMS[room_id]
    save_rooms()
    return True


def get_room(room_id: str):
    return ROOMS.get(room_id)


def list_rooms():
    """방 목록 화면에 표시할 순서 - 만든 순서대로."""
    return sorted(ROOMS.values(), key=lambda r: r.created_at)


def save_rooms():
    """현재 ROOMS의 영구 필드만 rooms.json에 저장합니다(전투 진행 상태는 저장 안 함)."""
    data = {
        room_id: {field: getattr(room, field) for field in _PERSISTED_FIELDS}
        for room_id, room in ROOMS.items()
    }
    tmp_path = ROOMS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, ROOMS_FILE)  # 저장 도중 서버가 죽어도 파일이 반쯤 쓰인 채로 깨지지 않도록.


def load_rooms():
    """서버 시작 시 rooms.json을 읽어 방을 복원합니다(전투는 항상 '시작 전' 상태로 복원)."""
    if not os.path.exists(ROOMS_FILE):
        return
    try:
        with open(ROOMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    for room_id, fields in data.items():
        room = RoomState(room_id, fields.get("battle_type", "pvp"))
        for field in _PERSISTED_FIELDS:
            if field in fields:
                setattr(room, field, fields[field])
        ROOMS[room_id] = room
