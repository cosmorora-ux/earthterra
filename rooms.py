# -*- coding: utf-8 -*-
"""
rooms.py
========
방(room) 단위 상태 관리. 방 하나 = GameManager(캐릭터 DB + 전투) 하나 + 채팅 로그 하나.
운영진 링크(gm_key)와 참가자 링크(guest_key)를 따로 발급해서 역할을 구분합니다.
"""

import secrets
import time

from battle import GameManager

ROOMS = {}

BATTLE_TYPE_LABELS = {
    "pvp": "PVP (러너 vs 러너)",
    "siege": "점령전 (GM vs 러너)",
    "raid": "레이드 (GM vs 러너 다인)",
    "mass_raid": "마스 레이드 (격자 이동)",
}
# 전투 유형별 팀 인원 기본값 : (1팀/러너팀 기본 인원, 2팀/GM팀 기본 인원)
BATTLE_TYPE_DEFAULTS = {
    "pvp": (3, 3),
    "siege": (5, 1),
    "raid": (15, 1),
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


def create_room(battle_type: str = "pvp") -> RoomState:
    room_id = secrets.token_urlsafe(4)
    while room_id in ROOMS:
        room_id = secrets.token_urlsafe(4)
    room = RoomState(room_id, battle_type)
    ROOMS[room_id] = room
    return room


def get_room(room_id: str):
    return ROOMS.get(room_id)
