# -*- coding: utf-8 -*-
"""
config.py
=========
전투와 관련된 모든 수치와 계산 공식을 이 파일에서 관리합니다.

설계 철학 (반드시 유지)
------------------------
- 정신  : 다이스의 "최소치"를 보장 (안정성). 기준치(정신 × MENTAL_FLOOR_MULTIPLIER) 이하로
          나온 다이스는 재굴림됩니다.
- 이능  : 다이스의 "최대치(면수)"를 늘림 (폭발력).
- 공격/방어 : 각 행동(공격/방어)의 "직업 특화" 보조치 - 기본 다이스에 더해집니다.
- 민첩/행운 : 치명타(크리티컬) 확률과 배율을 담당합니다.

이 파일 값들은 프로그램 실행 중 "캐릭터 데이터베이스" 화면의
"⚙ 전투 수식 설정 (운영진 전용)" 버튼을 통해서도 수정할 수 있습니다.
그렇게 수정한 값은 formulas.json 에 저장되어, 프로그램을 껐다 켜도 유지됩니다.
(직접 이 파일의 숫자를 고쳐도 동일하게 동작합니다)
"""

import os
import json
import random

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_OVERRIDE_PATH = os.path.join(_THIS_DIR, "formulas.json")           # 기본(PVP) 수식 - 전역
_PROFILES_PATH = os.path.join(_THIS_DIR, "formula_profiles.json")   # 점령전/레이드 전용 수식


def get_value(key, overrides: dict = None):
    """
    수식 상수 하나를 가져옵니다. overrides(전투 유형별 저장값)에 해당 키가 있으면 그 값을,
    없으면 이 파일의 기본(전역) 값을 반환합니다.
    """
    if overrides and key in overrides:
        return overrides[key]
    return globals()[key]


# ----------------------------------------------------------------------
# 0. 캐릭터 역할 / 스탯 이름 / 스탯 최대치
# ----------------------------------------------------------------------
# 역할 이름은 가디언/스트라이커/메딕으로 통일합니다 (예전 탱커/딜러/힐러 명칭은 더 이상 쓰지 않습니다).
# 역할 자체의 정체성(포지션)은 그대로이며, 이 상수들의 "이름"만 바뀐 것입니다 - 그래서 치명타
# 포지션 판정(role == ROLE_DEALER 등) 같은 기존 로직은 전부 그대로 동작합니다.
# 다만 "행동 목록"은 전투 유형에 따라 달라집니다: 기본(PVP/점령전/레이드)에서는 아래 ROLE_ACTIONS의
# 원래(옛 탱커/딜러/힐러) 행동 그대로이고, 마스 레이드에서만 MASS_RAID_ROLE_ACTIONS로 교체됩니다.
ROLE_TANKER = "가디언"
ROLE_DEALER = "스트라이커"
ROLE_HEALER = "메딕"
ROLES = [ROLE_TANKER, ROLE_DEALER, ROLE_HEALER]
# 캐릭터 데이터베이스 목록을 이 순서(포지션순)로 정렬합니다.
ROLE_ORDER = [ROLE_TANKER, ROLE_DEALER, ROLE_HEALER]

# 붙여넣기 등록 시 역할이 명시되지 않았을 때 사용할 기본 역할
DEFAULT_ROLE = ROLE_DEALER

# 데이터베이스 / 파싱 / UI에서 공용으로 사용하는 스탯 이름 목록
STAT_KEYS = ["체력", "공격", "방어", "이능", "정신", "민첩", "행운"]

# 더미 캐릭터를 무작위로 생성할 때 사용하는 기본 범위 힌트일 뿐, 더 이상 강제 상한은 아닙니다.
STAT_CAPS = {
    "체력": 5, "공격": 3, "방어": 3, "이능": 5, "정신": 5, "민첩": 5, "행운": 5,
}
STAT_MIN = 0


def clamp_stats(stats: dict):
    """스탯 값을 0 이상으로만 보정합니다. (최대치 제한은 없습니다) 반환값: (보정된 dict, 경고 리스트)"""
    clamped = {}
    warnings = []
    for key in STAT_KEYS:
        raw = int(stats.get(key, 0))
        fixed = max(STAT_MIN, raw)
        if fixed != raw:
            warnings.append(f"'{key}' 값 {raw} → {fixed}(으)로 자동 조정되었습니다.")
        clamped[key] = fixed
    return clamped, warnings


def stat_total(stats: dict) -> int:
    return sum(int(stats.get(k, 0)) for k in STAT_KEYS)


# ----------------------------------------------------------------------
# 1. 역할별 사용 가능한 행동
#    기본(PVP/점령전/레이드) - ROLE_ACTIONS. 옛 탱커/딜러/힐러 시절과 완전히 동일한 행동입니다.
#    - 공격 : 모든 역할 가능 (가디언 포함)
#    - 방어 : 가디언 전용. 본인 또는 아군 1명(택1)을 지정해 그 대상에게 능동 방어를 부여합니다.
#             (어그로 효과는 없습니다)
#    - 공격유도 : 가디언 전용. 어그로를 걸 대상(본인 또는 아군)을 지정합니다. 대상이 본인이면
#                 추가로 능동 방어도 함께 부여됩니다.
#    - 본인방어 : 스트라이커/메딕 전용. 자기 자신에게만 능동 방어를 부여합니다.
#    - 회피 : 스트라이커 전용. 행운/민첩 기반으로 다음 피격을 완전히 회피할 확률을 얻습니다.
#    - 힐 : 메딕 전용.
#    - 시간초과 / 도주 : 전원 공통.
#
#    마스 레이드 전용 - MASS_RAID_ROLE_ACTIONS. 격자 전투에 맞춰 행동 목록이 재구성됩니다
#    (같은 역할이라도 전투 유형에 따라 쓸 수 있는 행동이 다릅니다).
#    - 스트라이커 : 공격, 회피.
#    - 가디언 : 방어(자신 포함 지정 1인에게 능동 방어 부여 - 기본 '방어'와 동일한 단순 방어),
#               지휘(지정 아군 1인에게 어그로 1회 부여. 방어 효과는 없습니다 - 기본 '공격유도'와
#               달리 본인을 지정해도 추가 방어가 붙지 않습니다).
#    - 메딕 : 회복(힐과 동일), 배치(지정 아군 1인과 본인의 위치(칸)를 교환).
# ----------------------------------------------------------------------
ACTION_ATTACK = "공격"
ACTION_SELF_DEFEND = "본인방어"
ACTION_DEFEND = "방어"
ACTION_TAUNT = "공격유도"
ACTION_HEAL = "힐"
ACTION_DODGE = "회피"
ACTION_TIMEOUT = "시간초과"
ACTION_FLEE = "도주"
ACTION_DEFENSE_SETTLE = "방어 정산"  # 점령전 거점 전용 - 보류된 공격을 정산만 하고, 이후 공격/힐을 이어서 할 수 있습니다.
ACTION_MOVE = "이동"  # 마스 레이드(격자) 전용 - 이번 라운드 행동 전에 먼저 선언합니다. has_acted를 소모하지 않습니다.
ACTION_COMMAND = "지휘"  # 가디언 전용(마스 레이드) - 공격유도와 같은 어그로 강제이지만, 방어 부여 효과는 없습니다.
ACTION_SWAP = "배치"  # 메딕 전용(마스 레이드) - 지정 아군 1인과 본인의 위치(칸)를 교환합니다. 사정거리 제한 없음.

# 메딕 전용 표시명 - 스트라이커의 "본인방어"/"힐"과 동일한 행동이지만 메딕 화면에는 이 이름으로
# 보여줍니다. "방어"는 가디언의 능동 방어 부여 행동(ACTION_DEFEND)과 글자는 같지만 서로 다른
# 행동이라, 클라이언트가 행동자 직군(메딕 vs 가디언)으로 구분해서 처리합니다.
ACTION_SELF_DEFEND_MEDIC = "방어"
ACTION_HEAL_MEDIC = "회복"

ROLE_ACTIONS = {
    ROLE_TANKER: [ACTION_ATTACK, ACTION_DEFEND, ACTION_TAUNT],
    ROLE_DEALER: [ACTION_ATTACK, ACTION_SELF_DEFEND, ACTION_DODGE],
    ROLE_HEALER: [ACTION_ATTACK, ACTION_SELF_DEFEND, ACTION_HEAL],
}
# 마스 레이드에서만 위 ROLE_ACTIONS 대신 적용되는 역할별 행동 목록 (webapp.py가
# forced_actions로 덮어씁니다 - 여기 없는 COMMON_ACTIONS(시간초과/도주)는 webapp.py에서 함께 붙여줍니다).
MASS_RAID_ROLE_ACTIONS = {
    ROLE_TANKER: [ACTION_DEFEND, ACTION_COMMAND],
    ROLE_DEALER: [ACTION_ATTACK, ACTION_DODGE],
    ROLE_HEALER: [ACTION_HEAL, ACTION_SWAP],
}
COMMON_ACTIONS = [ACTION_TIMEOUT, ACTION_FLEE]  # 모든 역할이 사용 가능

# ----------------------------------------------------------------------
# 1.5 마스 레이드 전용 스킬 - 역할당 2종 중 1개를 캐릭터 생성 시 선택합니다.
#     행동 버튼에는 "스킬" 대신 스킬 고유 이름(【 】 안 2글자)이 그대로 표시됩니다.
# ----------------------------------------------------------------------
SKILL_COLLAPSE = "붕괴"    # 스트라이커 - 단일 공격 : 다이스 ×3, 2회 공격, 최소 1회 크리티컬 보장
SKILL_EMISSION = "방출"    # 스트라이커 - 광역 공격 : 다이스 ×2, 생존한 모든 적에게 개별로 2회 공격
SKILL_SHIELD = "차폐"      # 가디언 - 보호막 : 전투 시작 시 본인에게 영구 보호막, 사용 시 지정 아군에게 임시 보호막+방어
SKILL_POLARIZE = "편광"    # 가디언 - 광역 방어 : 아군 전원의 피해를 본인에게 집중(3턴)
SKILL_REFLUX = "환류"      # 메딕 - HP 흡수 : 본인 회복 + 메딕 전원 회복 + 지정 아군 3인에게 흡수 버프
SKILL_RESTORE = "복원"     # 메딕 - 광역 회복 : 모든 아군 회복 + 지정 아군 1인 추가 회복

SKILL_OPTIONS = {
    ROLE_TANKER: [SKILL_SHIELD, SKILL_POLARIZE],
    ROLE_DEALER: [SKILL_COLLAPSE, SKILL_EMISSION],
    ROLE_HEALER: [SKILL_REFLUX, SKILL_RESTORE],
}
ALL_SKILLS = [SKILL_COLLAPSE, SKILL_EMISSION, SKILL_SHIELD, SKILL_POLARIZE, SKILL_REFLUX, SKILL_RESTORE]

# 붕괴/방출 : 기본 공격 다이스 개수(ATTACK_DICE_COUNT)에 곱하는 배율
SKILL_COLLAPSE_DICE_MULT = 3
SKILL_EMISSION_DICE_MULT = 2

# 차폐 : 전투 시작 시 본인에게 붙는 영구 보호막(데미지로만 소모되며 시간 만료가 없습니다)
SKILL_SHIELD_INITIAL = 150
# 차폐 : 사용(행동)할 때마다 대상에게 붙는 임시 보호막량 - 본인 지정 시에는 2배
SKILL_SHIELD_GRANT_ALLY = 50
SKILL_SHIELD_GRANT_SELF = 100
# 차폐로 부여한 임시 보호막의 지속 라운드 수 (데미지로 다 안 깎여도 이 라운드가 지나면 사라집니다)
SKILL_SHIELD_GRANT_DURATION = 3

# 편광 : 지속 라운드 수. 이 기간 동안 같은 팀에 대한 모든 공격이 편광 사용자에게 집중되며,
# 편광 사용자는 이 효과로는 죽지 않고(최소 1hp) 못 막은 만큼은 다음 라운드 시작 시 무조건
# 생존 아군 전원에게 1/n씩 나눠서 가산됩니다.
SKILL_POLARIZE_DURATION = 3

# 환류 : 본인 회복량 (최대 HP 대비 %)
SKILL_REFLUX_SELF_HEAL_PCT = 50
# 환류 : 지정 아군 3인에게 부여하는 흡수 버프의 지속 라운드 수 / 인원수
SKILL_REFLUX_BUFF_DURATION = 3
SKILL_REFLUX_BUFF_TARGET_COUNT = 3
# 환류 흡수 버프 : 다이스 면수 = 행운 × 이 배율. 굴린 값을 3등분해서 하/중/상 등급을 매깁니다.
# (행운 0이면 다이스를 굴리지 않고 항상 '하' 등급으로 처리합니다)
SKILL_REFLUX_BUFF_DICE_PER_LUCK = 3
# 흡수 버프 등급별 회복량 (등급 판정 시점의 본인 최대 HP 대비 %)
SKILL_REFLUX_BUFF_PCT_LOW = 10
SKILL_REFLUX_BUFF_PCT_MID = 20
SKILL_REFLUX_BUFF_PCT_HIGH = 30

# 복원 : 지정 아군 1인에게 추가로 붙는 회복 보너스 (%)
SKILL_RESTORE_BONUS_PCT = 50


# 힐러는 "후공 페이즈"(이번 라운드에서 순서상 나중에 행동하는 팀의 차례)라면,
# 설령 자기 팀 턴이 아니더라도 라운드당 1회의 행동을 사용할 수 있습니다.
# (예: 우리 팀이 선공이었다면, 힐러는 상대의 후공 페이즈 때 반응하듯 힐을 쓸 수 있습니다)
FREE_TURN_ROLES = [ROLE_HEALER]


# ----------------------------------------------------------------------
# 2. 최대 HP 계산
#    최대 HP = HP_BASE + 체력 × HP_PER_VIT   (체력 0 = 150, 체력 5 = 225)
# ----------------------------------------------------------------------
HP_BASE = 150
HP_PER_VIT = 15


def calculate_max_hp(stats: dict, overrides: dict = None) -> int:
    return get_value("HP_BASE", overrides) + int(stats.get("체력", 0)) * get_value("HP_PER_VIT", overrides)


# ----------------------------------------------------------------------
# 3. 공통 기본 다이스 공식 (공격/방어/힐 전부 이 공식을 기반으로 합니다)
#    - 다이스 면수(최대치) = BASE_DICE_SIDES + 이능 × ABILITY_BONUS   → 이능 = 폭발력
#    - 재굴림 기준치 = 정신 × MENTAL_FLOOR_MULTIPLIER                → 정신 = 안정성
#      (다이스 눈이 이 기준치 이하로 나오면 딱 한 번 다시 굴립니다)
# ----------------------------------------------------------------------
BASE_DICE_SIDES = 15
ABILITY_BONUS = 2
MENTAL_FLOOR_MULTIPLIER = 3


def _roll_core_dice(stats: dict, dice_count: int, overrides: dict = None) -> dict:
    """정신=재굴림 기준치, 이능=다이스 최대치(면수)를 반영하는 공용 기본 다이스 굴림."""
    ability = int(stats.get("이능", 0))
    mental = int(stats.get("정신", 0))
    sides = get_value("BASE_DICE_SIDES", overrides) + ability * get_value("ABILITY_BONUS", overrides)
    threshold = mental * get_value("MENTAL_FLOOR_MULTIPLIER", overrides)

    first_rolls, final_rolls, rerolled = [], [], []
    for _ in range(dice_count):
        r = random.randint(1, sides)
        first_rolls.append(r)
        if r <= threshold:
            r2 = random.randint(1, sides)  # 기준치 이하면 한 번 다시 굴리고, 더 높은 값을 채택합니다.
            r = max(r, r2)
            rerolled.append(True)
        else:
            rerolled.append(False)
        final_rolls.append(r)

    return {
        "sides": sides, "mental_threshold": threshold, "dice_count": dice_count,
        "first_rolls": first_rolls, "final_rolls": final_rolls, "rerolled": rerolled,
        "subtotal": sum(final_rolls),
    }


# ----------------------------------------------------------------------
# 4. 공격 계산 (딜러 특화)
#    공격 총합 = 기본 다이스 + 공격 × ATTACK_STAT_MULTIPLIER (직업 특화 보조치)
#    치명타 확률(%) = BASE_CRIT_CHANCE + 행운 × LUCK_CRIT_CHANCE_MULT(주 요인) + 정신 × MENTAL_CRIT_CHANCE_MULT(부 요인)
#    치명타 배율   = BASE_CRIT_DMG + 민첩 × AGI_CRIT_DMG(주 요인) + 이능 × ABILITY_CRIT_DMG(부 요인)
#    (치명타는 딜러가 공격할 때만 발생합니다)
# ----------------------------------------------------------------------
ATTACK_DICE_COUNT = 3
# 스트라이커(딜러)가 아닌 사람이 공격할 때는 기본 다이스를 이 개수만큼만 굴립니다
# (역할 없는 몹/거점도 포함 - 딜러만 정직업 화력을 다 씁니다).
ATTACK_DICE_COUNT_NON_DEALER = 2
ATTACK_STAT_MULTIPLIER = 12

BASE_CRIT_CHANCE = 15
LUCK_CRIT_CHANCE_MULT = 6
MENTAL_CRIT_CHANCE_MULT = 2

BASE_CRIT_DMG = 1.15
AGI_CRIT_DMG = 0.06
ABILITY_CRIT_DMG = 0.02


def roll_attack(stats: dict, role: str = None, overrides: dict = None) -> dict:
    """공격 굴림을 수행합니다. 운영자 로그에 다이스 수식을 그대로 노출하기 위해 세부 항목을 모두 담습니다."""
    dice_count_key = "ATTACK_DICE_COUNT" if role == ROLE_DEALER else "ATTACK_DICE_COUNT_NON_DEALER"
    core = _roll_core_dice(stats, get_value(dice_count_key, overrides), overrides)
    atk_val = int(stats.get("공격", 0))
    luck = int(stats.get("행운", 0))
    agi = int(stats.get("민첩", 0))
    ability = int(stats.get("이능", 0))
    mental = int(stats.get("정신", 0))

    stat_mult = get_value("ATTACK_STAT_MULTIPLIER", overrides)
    atk_bonus = atk_val * stat_mult
    subtotal = core["subtotal"] + atk_bonus

    # role이 None이면 포지션이 없는 존재(점령전 거점 / 마스 레이드 적군)이므로 항상 치명타 판정 대상입니다.
    position_match = (role is None) or (role == ROLE_DEALER)
    if position_match:
        crit_chance = (get_value("BASE_CRIT_CHANCE", overrides)
                       + luck * get_value("LUCK_CRIT_CHANCE_MULT", overrides)
                       + mental * get_value("MENTAL_CRIT_CHANCE_MULT", overrides))
        is_crit = random.randint(1, 100) <= crit_chance
    else:
        crit_chance, is_crit = 0, False
    crit_mult = (get_value("BASE_CRIT_DMG", overrides)
                 + agi * get_value("AGI_CRIT_DMG", overrides)
                 + ability * get_value("ABILITY_CRIT_DMG", overrides))
    total = round(subtotal * crit_mult) if is_crit else subtotal

    return {
        "dice_sides": core["sides"], "dice_count": core["dice_count"],
        "mental_threshold": core["mental_threshold"],
        "first_rolls": core["first_rolls"], "final_rolls": core["final_rolls"], "rerolled": core["rerolled"],
        "dice_subtotal": core["subtotal"],
        "stat_val": atk_val, "stat_mult": stat_mult, "stat_bonus": atk_bonus,
        "subtotal": subtotal, "is_crit": is_crit, "position_match": position_match,
        "crit_chance": crit_chance, "crit_mult": round(crit_mult, 3),
        "total": total,
    }


# ----------------------------------------------------------------------
# 5. 방어 계산 (탱커 특화)
#    - 방어를 받지 못한 상태(수동/무방비) : 대상 자신의 방어 스탯만 반영 (다이스 없음, 치명타 불가)
#      → 방어 총합 = 방어 × PASSIVE_DEFENSE_STAT_MULTIPLIER
#    - 방어를 받은 상태(능동)는 항상 위의 "수동 방어(대상 본인 기준)"를 기본 바닥값으로 깔고,
#      그 위에 "방어를 부여한 사람(본인이거나 탱커)"의 능동 방어 계층을 더합니다.
#        방어 총합 = 대상 본인의 수동 방어 + [부여자의 기본 다이스 + 부여자의 방어 × DEFENSE_STAT_MULTIPLIER]
#      즉, 탱커가 아군에게 '방어'를 부여했다면 그 아군은 "본인의 수동 방어 + 탱커의 능동 방어"를
#      함께 받습니다. 치명타(치명적 방어)는 이 능동 계층에서만, 그리고 부여자가 탱커일 때만 발생합니다.
#    치명타 확률(%) = DEFENSE_CRIT_BASE_CHANCE + 부여자 행운×배율(주 요인) + 부여자 정신×배율(부 요인)
#    치명타 배율   = DEFENSE_CRIT_BASE_MULT + 부여자 민첩×배율(주 요인) + 부여자 이능×배율(부 요인)
#    (공격 크리티컬과 동일한 구조: 행운/민첩이 주 요인, 정신/이능이 부 요인입니다)
# ----------------------------------------------------------------------
DEFENSE_DICE_COUNT = 2
DEFENSE_STAT_MULTIPLIER = 15
PASSIVE_DEFENSE_STAT_MULTIPLIER = 4

DEFENSE_CRIT_BASE_CHANCE = 15
DEFENSE_CRIT_LUCK_MULT = 6
DEFENSE_CRIT_MENTAL_MULT = 3

DEFENSE_CRIT_BASE_MULT = 1.3
DEFENSE_CRIT_AGI_MULT = 0.08
DEFENSE_CRIT_ABILITY_MULT = 0.03


def roll_defense(target_stats: dict, active: bool, grantor_stats: dict = None,
                  grantor_role: str = None, grantor_name: str = None, overrides: dict = None) -> dict:
    """
    방어 굴림을 수행합니다.
    target_stats  : 방어하는(공격받는) 당사자의 스탯 (항상 본인의 수동 방어 바닥값 계산에 사용)
    active        : 이번 라운드에 능동 방어를 받았는지 여부
    grantor_stats/grantor_role : 그 능동 방어를 "부여한" 사람의 스탯/역할.
                                  본인방어라면 target 자신과 동일하며, 탱커가 타인에게 부여했다면
                                  그 탱커의 스탯/역할이 들어옵니다. (요청 10 반영)
    """
    passive_mult = get_value("PASSIVE_DEFENSE_STAT_MULTIPLIER", overrides)
    target_def_val = int(target_stats.get("방어", 0))
    passive_component = target_def_val * passive_mult

    if not active:
        return {
            "active": False, "passive_component": passive_component, "active_component": 0,
            "grantor_name": None, "sides": None, "dice_count": 0, "mental_threshold": None,
            "first_rolls": [], "final_rolls": [], "rerolled": [],
            "stat_val": target_def_val, "stat_mult": passive_mult,
            "is_crit": False, "position_match": False, "crit_chance": 0, "crit_mult": 1.0,
            "total": passive_component,
        }

    g_stats = grantor_stats if grantor_stats is not None else target_stats
    core = _roll_core_dice(g_stats, get_value("DEFENSE_DICE_COUNT", overrides), overrides)
    stat_mult = get_value("DEFENSE_STAT_MULTIPLIER", overrides)
    g_def_val = int(g_stats.get("방어", 0))
    active_bonus = g_def_val * stat_mult
    active_subtotal = core["subtotal"] + active_bonus

    position_match = (grantor_role == ROLE_TANKER)
    g_luck = int(g_stats.get("행운", 0))
    g_mental = int(g_stats.get("정신", 0))
    g_agi = int(g_stats.get("민첩", 0))
    g_ability = int(g_stats.get("이능", 0))
    if position_match:
        crit_chance = (get_value("DEFENSE_CRIT_BASE_CHANCE", overrides)
                       + g_luck * get_value("DEFENSE_CRIT_LUCK_MULT", overrides)
                       + g_mental * get_value("DEFENSE_CRIT_MENTAL_MULT", overrides))
        is_crit = random.randint(1, 100) <= crit_chance
    else:
        crit_chance, is_crit = 0, False
    crit_mult = (get_value("DEFENSE_CRIT_BASE_MULT", overrides)
                 + g_agi * get_value("DEFENSE_CRIT_AGI_MULT", overrides)
                 + g_ability * get_value("DEFENSE_CRIT_ABILITY_MULT", overrides))
    active_component = round(active_subtotal * crit_mult) if is_crit else active_subtotal

    total = passive_component + active_component

    return {
        "active": True, "passive_component": passive_component, "active_component": active_component,
        "active_subtotal": active_subtotal,
        "grantor_name": grantor_name, "sides": core["sides"], "dice_count": core["dice_count"],
        "mental_threshold": core["mental_threshold"],
        "first_rolls": core["first_rolls"], "final_rolls": core["final_rolls"], "rerolled": core["rerolled"],
        "stat_val": g_def_val, "stat_mult": stat_mult,
        "is_crit": is_crit, "position_match": position_match,
        "crit_chance": crit_chance, "crit_mult": round(crit_mult, 3),
        "total": total,
    }


def roll_site_auto_defense(target_stats: dict, overrides: dict = None) -> dict:
    """
    점령전 거점 / 마스 레이드 적군 전용 자동 방어입니다. 공격 1회당 무조건 능동 방어 1회가 발생하며
    (방어 선언/능동 방어 계층 유무와 무관), 기본 다이스 공식 대신 1~30 고정 범위로 굴립니다.
    치명타는 발생하지 않습니다.
    """
    passive_mult = get_value("PASSIVE_DEFENSE_STAT_MULTIPLIER", overrides)
    def_val = int(target_stats.get("방어", 0))
    passive_component = def_val * passive_mult

    roll = random.randint(1, 30)
    stat_mult = get_value("DEFENSE_STAT_MULTIPLIER", overrides)
    active_bonus = def_val * stat_mult
    active_component = roll + active_bonus

    total = passive_component + active_component

    return {
        "active": True, "auto": True, "roll": roll,
        "passive_component": passive_component, "active_component": active_component,
        "grantor_name": None, "stat_val": def_val, "stat_mult": stat_mult,
        "is_crit": False, "position_match": False,
        "crit_chance": 0, "crit_mult": 1.0,
        "total": total,
    }


# ----------------------------------------------------------------------
# 6. 회피 계산 (딜러 전용, 민첩/행운 기반)
#    회피 확률(%) = DODGE_BASE_CHANCE + 행운 × DODGE_LUCK_MULTIPLIER + 민첩 × DODGE_AGI_MULTIPLIER
#    성공 시 해당 공격의 피해를 0으로 만듭니다.
# ----------------------------------------------------------------------
DODGE_BASE_CHANCE = 15
DODGE_LUCK_MULTIPLIER = 4
DODGE_AGI_MULTIPLIER = 4


def roll_dodge(stats: dict, multiplier: float = 1.0, overrides: dict = None) -> dict:
    """
    multiplier는 기존 밸런스에 영향을 주지 않는 선택적 배율입니다(기본값 1.0 = 기존과 동일).
    도주 시도 중 회피 확률을 올리는 등 특수 상황에서만 1.0이 아닌 값을 넘깁니다.
    """
    luck = int(stats.get("행운", 0))
    agi = int(stats.get("민첩", 0))
    base_chance = (get_value("DODGE_BASE_CHANCE", overrides)
                   + luck * get_value("DODGE_LUCK_MULTIPLIER", overrides)
                   + agi * get_value("DODGE_AGI_MULTIPLIER", overrides))
    chance = min(100, round(base_chance * multiplier))
    success = random.randint(1, 100) <= chance
    return {"chance": chance, "success": success}


# ----------------------------------------------------------------------
# 7. 최종 피해 계산
# ----------------------------------------------------------------------
MIN_DAMAGE = 1


def calculate_final_damage(attack_total: int, defense_total: int, overrides: dict = None) -> int:
    return max(get_value("MIN_DAMAGE", overrides), attack_total - defense_total)


# ----------------------------------------------------------------------
# 8. 힐(회복) 계산 (힐러 특화)
#    회복량 = 기본 다이스 합 × HEAL_OUTPUT_MULTIPLIER (별도의 스탯 곱연산 이중 보정은 없습니다)
#    치명타 확률(%) = HEAL_CRIT_BASE_CHANCE + 행운×배율(주 요인) + 정신×배율(부 요인)
#    치명타 배율   = HEAL_CRIT_BASE_MULT + 민첩×배율(주 요인) + 이능×배율(부 요인)
# ----------------------------------------------------------------------
HEAL_DICE_COUNT = 2
HEAL_OUTPUT_MULTIPLIER = 1.8

HEAL_CRIT_BASE_CHANCE = 15
HEAL_CRIT_LUCK_MULT = 6
HEAL_CRIT_MENTAL_MULT = 3

HEAL_CRIT_BASE_MULT = 1.3
HEAL_CRIT_AGI_MULT = 0.08
HEAL_CRIT_ABILITY_MULT = 0.03


def roll_heal(stats: dict, role: str = None, overrides: dict = None) -> dict:
    core = _roll_core_dice(stats, get_value("HEAL_DICE_COUNT", overrides), overrides)
    base_total = round(core["subtotal"] * get_value("HEAL_OUTPUT_MULTIPLIER", overrides))

    # role이 None이면 포지션이 없는 존재(점령전 거점 / 마스 레이드 적군)이므로 항상 치명타 판정 대상입니다.
    position_match = (role is None) or (role == ROLE_HEALER)
    luck = int(stats.get("행운", 0))
    mental = int(stats.get("정신", 0))
    agi = int(stats.get("민첩", 0))
    ability = int(stats.get("이능", 0))
    if position_match:
        crit_chance = (get_value("HEAL_CRIT_BASE_CHANCE", overrides)
                       + luck * get_value("HEAL_CRIT_LUCK_MULT", overrides)
                       + mental * get_value("HEAL_CRIT_MENTAL_MULT", overrides))
        is_crit = random.randint(1, 100) <= crit_chance
    else:
        crit_chance, is_crit = 0, False
    crit_mult = (get_value("HEAL_CRIT_BASE_MULT", overrides)
                 + agi * get_value("HEAL_CRIT_AGI_MULT", overrides)
                 + ability * get_value("HEAL_CRIT_ABILITY_MULT", overrides))
    total = round(base_total * crit_mult) if is_crit else base_total

    return {
        "dice_sides": core["sides"], "dice_count": core["dice_count"],
        "mental_threshold": core["mental_threshold"],
        "first_rolls": core["first_rolls"], "final_rolls": core["final_rolls"], "rerolled": core["rerolled"],
        "base_total": base_total, "dice_subtotal": core["subtotal"],
        "is_crit": is_crit, "position_match": position_match,
        "crit_chance": crit_chance, "crit_mult": round(crit_mult, 3),
        "total": total,
    }


# ----------------------------------------------------------------------
# 9. 라운드 제한시간
# ----------------------------------------------------------------------
ROUND_TIME_LIMIT_SECONDS = 300  # 5분


# ----------------------------------------------------------------------
# 9.5. 격자 이동 (마스 레이드 전용)
#      이동 가능 칸수 = AGILITY_MOVE_BASE + 민첩 × AGILITY_MOVE_PER_POINT  (기본: 민첩 0~5 → 1~6칸)
# ----------------------------------------------------------------------
AGILITY_MOVE_BASE = 1
AGILITY_MOVE_PER_POINT = 1


def calculate_move_range(stats: dict, overrides: dict = None) -> int:
    """
    민첩 0이어도 십자로 최소 1칸은 움직일 수 있도록 최소값 1을 보장합니다.
    (민첩 0 - 십자4칸, 민첩 1 - 네모8칸, 민첩 2 - 십자8칸+네모8칸, 민첩 3 - 십자12칸+네모8칸 …)
    """
    agi = int(stats.get("민첩", 0))
    raw = get_value("AGILITY_MOVE_BASE", overrides) + agi * get_value("AGILITY_MOVE_PER_POINT", overrides)
    return max(1, raw)


def is_within_move_shape(dx: int, dy: int, move_range: int, agility: int = 0) -> bool:
    """
    이동 가능 모양 = 십자(상하좌우로 move_range칸) + 본인을 두르는 대각선 포함 8칸.
    단, 민첩이 0이면 대각선/8칸 보너스 없이 십자로만 이동할 수 있습니다.
    """
    is_cross = (dx == 0 and abs(dy) <= move_range) or (dy == 0 and abs(dx) <= move_range)
    if agility <= 0:
        return is_cross
    is_adjacent = abs(dx) <= 1 and abs(dy) <= 1
    return is_cross or is_adjacent


# ----------------------------------------------------------------------
# 9.6. "BOSS" 다부위 캐릭터 (격자 전투 - 점령전/마스 레이드 공용)
#      이름이 BOSS_NAME_PREFIXES 중 하나로 "시작하는"(뒤에 뭐가 더 붙어도 무방) 캐릭터는
#      전투 시작 시 4부위(북동/북서/남동/남서)로 나뉘어 격자 2x2 칸을 함께 차지합니다.
#      - 팀 명단에 그런 이름이 한 줄만 있으면: 그 한 줄을 4번 조회해서 부위 4개를 자동 생성.
#      - 팀 명단에 그런 이름이 정확히 네 줄 있으면: 그 네 줄을 각각 한 부위씩으로 그룹지어
#        하나의 BOSS로 취급(원래 이름은 그대로 유지 - 이미 서로 다르므로 개명 불필요).
#      부위마다 체력/행동은 독립적이지만, 이동은 한 덩이로 취급되어 전원 행동 완료 시
#      자동으로 빈 2x2 자리를 찾아 다 같이 옮겨갑니다. (GameManager.build_team 참고)
# ----------------------------------------------------------------------
BOSS_NAME = "BOSS"  # 하위 호환용 - "이름이 정확히 BOSS인지"가 아니라 아래 프리픽스 검사를 씁니다.
BOSS_NAME_PREFIXES = ["BOSS", "NOVA"]
BOSS_SECTIONS = ["NW", "NE", "SW", "SE"]
# 부위 앵커(북서 칸) 기준 상대 좌표
BOSS_SECTION_OFFSETS = {"NW": (0, 0), "NE": (1, 0), "SW": (0, 1), "SE": (1, 1)}
BOSS_SECTION_LABELS_KO = {"NW": "북서", "NE": "북동", "SW": "남서", "SE": "남동"}


def is_boss_name(name: str) -> bool:
    """이름이 BOSS 취급 접두어(BOSS_NAME_PREFIXES)로 시작하면 True. 뒤에 무엇이 더
    붙어도(공백/숫자/한글 등) 무방합니다 - 예: "BOSS", "NOVA 1구역" 모두 True."""
    return any((name or "").startswith(p) for p in BOSS_NAME_PREFIXES)


# ----------------------------------------------------------------------
# 10. 운영자가 GUI에서 직접 수정할 수 있는 "전투 수식" 항목 정의
#     (key는 위에 정의된 전역 변수명과 반드시 일치해야 합니다)
# ----------------------------------------------------------------------
# 전투 수식 설정 화면에서 항목을 묶어 보여주기 위한 카테고리 (직군/역할 기준).
# 순서가 곧 화면에 탭이 표시되는 순서입니다.
FORMULA_CATEGORIES = [
    {"key": "common", "label": "공통", "desc": "체력과 기본 다이스 등, 모든 행동에 공통으로 쓰이는 값"},
    {"key": "attack", "label": "공격 · 회피", "desc": "스트라이커의 공격/치명타, 회피 관련 값"},
    {"key": "defense", "label": "방어", "desc": "가디언의 능동 방어/치명타 관련 값"},
    {"key": "heal", "label": "힐", "desc": "메딕의 회복/치명타 관련 값"},
    {"key": "flow", "label": "전투 진행", "desc": "제한시간, 마스 레이드 이동 등 전투 진행 관련 값"},
]

FORMULA_FIELDS = [
    {"key": "HP_BASE", "label": "최대 HP 기본값", "desc": "최대 HP = 기본값 + 체력 × 체력 1당 HP 증가량", "type": int, "category": "common"},
    {"key": "HP_PER_VIT", "label": "체력 1당 HP 증가량", "desc": "최대 HP = 기본값 + 체력 × 이 값", "type": int, "category": "common"},

    {"key": "BASE_DICE_SIDES", "label": "기본 다이스 면수",
     "desc": "공격/방어/힐 공통 기본값입니다. 다이스 면수 = 기본 면수 + 이능 × 이능당 증가량 (이능 = 폭발력)", "type": int, "category": "common"},
    {"key": "ABILITY_BONUS", "label": "이능 1당 다이스 면수 증가",
     "desc": "다이스 면수 = 기본 면수 + 이능 × 이 값", "type": int, "category": "common"},
    {"key": "MENTAL_FLOOR_MULTIPLIER", "label": "정신 1당 재굴림 기준치",
     "desc": "재굴림 기준치 = 정신 × 이 값. 다이스가 기준치 이하로 나오면 한 번 다시 굴려 더 높은 값을 채택합니다 (정신 = 안정성)",
     "type": int, "category": "common"},
    {"key": "MIN_DAMAGE", "label": "최소 피해량", "desc": "최종 피해 = max(이 값, 공격 총합 − 방어 총합). 방어가 아무리 높아도 이 값 밑으로는 안 내려갑니다",
     "type": int, "category": "common"},

    {"key": "ATTACK_DICE_COUNT", "label": "공격 다이스 개수 (스트라이커)", "desc": "스트라이커가 공격할 때 기본 다이스를 굴리는 횟수", "type": int, "category": "attack"},
    {"key": "ATTACK_DICE_COUNT_NON_DEALER", "label": "공격 다이스 개수 (스트라이커 외)",
     "desc": "가디언/메딕/몹·거점처럼 스트라이커가 아닌 캐릭터가 공격할 때 기본 다이스를 굴리는 횟수", "type": int, "category": "attack"},
    {"key": "ATTACK_STAT_MULTIPLIER", "label": "공격 스탯 배율",
     "desc": "공격 총합 = 기본 다이스 합 + 공격 스탯 × 이 배율", "type": int, "category": "attack"},
    {"key": "BASE_CRIT_CHANCE", "label": "공격 치명타 기본 확률(%)",
     "desc": "치명타 확률 = 기본 확률 + 행운 × 배율(주 요인) + 정신 × 배율(부 요인). 스트라이커에게만 발생합니다", "type": int, "category": "attack"},
    {"key": "LUCK_CRIT_CHANCE_MULT", "label": "공격 치명타 행운 배율 (주 요인)", "desc": "치명타 확률에 더해지는 행운 배율", "type": int, "category": "attack"},
    {"key": "MENTAL_CRIT_CHANCE_MULT", "label": "공격 치명타 정신 배율 (부 요인)", "desc": "치명타 확률에 더해지는 정신 배율", "type": int, "category": "attack"},
    {"key": "BASE_CRIT_DMG", "label": "공격 치명타 기본 배율",
     "desc": "치명타 배율 = 기본 배율 + 민첩 × 배율(주 요인) + 이능 × 배율(부 요인)", "type": float, "category": "attack"},
    {"key": "AGI_CRIT_DMG", "label": "공격 치명타 민첩 배율 (주 요인)", "desc": "치명타 배율에 더해지는 민첩 가중치", "type": float, "category": "attack"},
    {"key": "ABILITY_CRIT_DMG", "label": "공격 치명타 이능 배율 (부 요인)", "desc": "치명타 배율에 더해지는 이능 가중치", "type": float, "category": "attack"},
    {"key": "DODGE_BASE_CHANCE", "label": "회피 기본 확률(%)", "desc": "회피 확률 = 기본 확률 + 행운 × 배율 + 민첩 × 배율. 스트라이커 전용 행동입니다", "type": int, "category": "attack"},
    {"key": "DODGE_LUCK_MULTIPLIER", "label": "회피 행운 배율", "desc": "회피 확률에 더해지는 행운 배율", "type": int, "category": "attack"},
    {"key": "DODGE_AGI_MULTIPLIER", "label": "회피 민첩 배율", "desc": "회피 확률에 더해지는 민첩 배율", "type": int, "category": "attack"},

    {"key": "DEFENSE_DICE_COUNT", "label": "방어 다이스 개수", "desc": "능동 방어를 부여한 사람 기준으로 굴리는 다이스 개수", "type": int, "category": "defense"},
    {"key": "DEFENSE_STAT_MULTIPLIER", "label": "능동 방어 스탯 배율",
     "desc": "능동 방어 계층 = 부여자 기본 다이스 합 + 부여자 방어 스탯 × 이 배율", "type": int, "category": "defense"},
    {"key": "PASSIVE_DEFENSE_STAT_MULTIPLIER", "label": "수동 방어 스탯 배율",
     "desc": "방어를 아무도 안 걸어줬을 때도 항상 적용되는 바닥값입니다. 본인 방어 스탯 × 이 배율 (다이스 없음)", "type": int, "category": "defense"},
    {"key": "DEFENSE_CRIT_BASE_CHANCE", "label": "방어 치명타 기본 확률(%)",
     "desc": "치명타 확률 = 기본 확률 + 부여자 행운 × 배율(주 요인) + 부여자 정신 × 배율(부 요인). 방어를 부여한 사람이 가디언일 때만 발생합니다", "type": int, "category": "defense"},
    {"key": "DEFENSE_CRIT_LUCK_MULT", "label": "방어 치명타 행운 배율 (부여자, 주 요인)", "desc": "방어 치명타 확률에 더해지는 부여자 행운 배율", "type": int, "category": "defense"},
    {"key": "DEFENSE_CRIT_MENTAL_MULT", "label": "방어 치명타 정신 배율 (부여자, 부 요인)", "desc": "방어 치명타 확률에 더해지는 부여자 정신 배율", "type": int, "category": "defense"},
    {"key": "DEFENSE_CRIT_BASE_MULT", "label": "방어 치명타 기본 배율",
     "desc": "치명타 배율 = 기본 배율 + 부여자 민첩 × 배율(주 요인) + 부여자 이능 × 배율(부 요인)", "type": float, "category": "defense"},
    {"key": "DEFENSE_CRIT_AGI_MULT", "label": "방어 치명타 민첩 배율 (부여자, 주 요인)", "desc": "방어 치명타 배율에 더해지는 부여자 민첩 가중치", "type": float, "category": "defense"},
    {"key": "DEFENSE_CRIT_ABILITY_MULT", "label": "방어 치명타 이능 배율 (부여자, 부 요인)", "desc": "방어 치명타 배율에 더해지는 부여자 이능 가중치", "type": float, "category": "defense"},

    {"key": "HEAL_DICE_COUNT", "label": "힐 다이스 개수", "desc": "힐을 사용할 때 기본 다이스를 굴리는 횟수", "type": int, "category": "heal"},
    {"key": "HEAL_OUTPUT_MULTIPLIER", "label": "힐 최종 배율",
     "desc": "회복량 = 기본 다이스 합 × 이 배율. 힐러 전체의 회복력을 한 번에 조정할 때 씁니다", "type": float, "category": "heal"},
    {"key": "HEAL_CRIT_BASE_CHANCE", "label": "힐 치명타 기본 확률(%)",
     "desc": "치명타 확률 = 기본 확률 + 행운 × 배율(주 요인) + 정신 × 배율(부 요인). 메딕에게만 발생합니다", "type": int, "category": "heal"},
    {"key": "HEAL_CRIT_LUCK_MULT", "label": "힐 치명타 행운 배율 (주 요인)", "desc": "힐 치명타 확률에 더해지는 행운 배율", "type": int, "category": "heal"},
    {"key": "HEAL_CRIT_MENTAL_MULT", "label": "힐 치명타 정신 배율 (부 요인)", "desc": "힐 치명타 확률에 더해지는 정신 배율", "type": int, "category": "heal"},
    {"key": "HEAL_CRIT_BASE_MULT", "label": "힐 치명타 기본 배율",
     "desc": "치명타 배율 = 기본 배율 + 민첩 × 배율(주 요인) + 이능 × 배율(부 요인)", "type": float, "category": "heal"},
    {"key": "HEAL_CRIT_AGI_MULT", "label": "힐 치명타 민첩 배율 (주 요인)", "desc": "힐 치명타 배율에 더해지는 민첩 가중치", "type": float, "category": "heal"},
    {"key": "HEAL_CRIT_ABILITY_MULT", "label": "힐 치명타 이능 배율 (부 요인)", "desc": "힐 치명타 배율에 더해지는 이능 가중치", "type": float, "category": "heal"},

    {"key": "ROUND_TIME_LIMIT_SECONDS", "label": "라운드 제한시간(초)", "desc": "매 라운드마다 행동을 선언해야 하는 제한시간", "type": int, "category": "flow"},
    {"key": "AGILITY_MOVE_BASE", "label": "이동 가능 칸수 기본값 (마스 레이드)",
     "desc": "이동 칸수 = 기본값 + 민첩 × 민첩 1당 증가량", "type": int, "category": "flow"},
    {"key": "AGILITY_MOVE_PER_POINT", "label": "민첩 1당 이동 칸수 증가 (마스 레이드)",
     "desc": "이동 칸수 = 기본값 + 민첩 × 이 값", "type": int, "category": "flow"},
]


def get_formula_value(key):
    return globals().get(key)


def save_formula_overrides(values: dict):
    for field in FORMULA_FIELDS:
        key = field["key"]
        if key in values:
            try:
                globals()[key] = field["type"](values[key])
            except (TypeError, ValueError):
                pass

    data = {field["key"]: globals()[field["key"]] for field in FORMULA_FIELDS}
    with open(_OVERRIDE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _apply_saved_overrides():
    if os.path.exists(_OVERRIDE_PATH):
        try:
            with open(_OVERRIDE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for field in FORMULA_FIELDS:
                key = field["key"]
                if key in data:
                    globals()[key] = field["type"](data[key])
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass


_apply_saved_overrides()


# ----------------------------------------------------------------------
# 11. 전투 유형(점령전/레이드 등)별 수식 프로필
#     PVP는 위의 전역 기본값(formulas.json)을 그대로 씁니다. 점령전/레이드처럼
#     별도 프로필을 지정한 값이 있으면 그 값이 기본값을 덮어씁니다(get_value 참고).
# ----------------------------------------------------------------------
def _load_profiles_file() -> dict:
    if os.path.exists(_PROFILES_PATH):
        try:
            with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_profile_overrides(profile: str) -> dict:
    """저장된 특정 전투 유형의 수식 override 값을 dict로 반환합니다. 없으면 빈 dict."""
    if not profile or profile == "pvp":
        return {}
    return _load_profiles_file().get(profile, {})


def save_profile_overrides(profile: str, values: dict) -> dict:
    """values를 이 전투 유형 프로필에 저장하고, 저장된 전체 override dict를 반환합니다."""
    data = _load_profiles_file()
    current = dict(data.get(profile, {}))
    for field in FORMULA_FIELDS:
        key = field["key"]
        if key in values:
            try:
                current[key] = field["type"](values[key])
            except (TypeError, ValueError):
                pass
    data[profile] = current
    with open(_PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return current
