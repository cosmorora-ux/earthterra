# -*- coding: utf-8 -*-
"""
models.py
=========
전투에 사용되는 기본 객체(Character)와 행동(Skill)을 정의합니다.
실제 수치 계산은 전부 config.py 의 함수에 위임합니다.
"""

import config


class Character:
    """전투에 참여하는 캐릭터 한 명을 표현합니다."""

    STATUS_ALIVE = "alive"
    STATUS_DOWNED = "downed"    # HP 0이지만 아직 완전한 사망으로 확정되지 않은 상태
    STATUS_FLEEING = "fleeing"  # 도주를 시도했지만 아직 상대의 다음 턴을 넘기지 못한 상태
    STATUS_DEAD = "dead"
    STATUS_FLED = "fled"        # 도주에 완전히 성공한 상태

    def __init__(self, name: str, role: str, stats: dict, color: str = None, formula_overrides: dict = None):
        self.name = name
        self.role = role if role in config.ROLES else config.DEFAULT_ROLE
        # 스탯은 항상 STAT_KEYS 순서/형태 + 최대치 범위로 정규화해서 저장합니다.
        clamped, _ = config.clamp_stats(stats)
        self.stats = clamped
        self.color = color or None  # "#RRGGBB" 형태의 구분용 색상 (선택)
        self.formula_overrides = formula_overrides  # 이 캐릭터가 속한 전투 유형(점령전 등)의 수식 override

        self.max_hp = config.calculate_max_hp(self.stats, overrides=self.formula_overrides)
        self.current_hp = self.max_hp
        # None이면 역할(role) 기준 기본 행동 목록을 사용합니다. 리스트를 지정하면 그 행동만
        # 허용됩니다(예: 점령전 거점은 역할과 무관하게 "공격"/"힐"만) - Skill.can_use도 이 값을 따릅니다.
        self.forced_actions = None

        self.team = None   # "A" 또는 "B" - 전투 시작 시 Battle이 설정
        self.slot = None   # "A"/"B"/"C" - 팀 내 자리(선택적으로 사용)

        self.status = self.STATUS_ALIVE
        self.has_acted = False            # 이번 라운드에 행동을 완료했는지 여부
        self.defended_this_round = False  # 이번 라운드에 한 번이라도 방어를 받았는지 여부 (표시용)
        # 이번 라운드에 이 캐릭터에게 부여된 능동 방어 목록(부여자 Character, 부여된 순서).
        # 공격을 받을 때마다 맨 앞(먼저 걸린 것)부터 하나씩 소모됩니다. (요청 13)
        self.defense_grants = []
        self.protecting_ally = None       # 탱커가 '방어'로 자신이 아닌 아군을 지정했을 때 그 아군 이름
        self.dodging_this_round = False   # 이번 라운드에 회피를 선언했는지 여부(딜러 전용)
        self.pending_attacks = []         # 아직 정산되지 않은 공격(피해 보류) 목록
        self.fleeing_watch_key = None     # 도주 시도 중, 이 팀 키("A"/"B")의 턴이 끝나면 도주가 확정됩니다.

        # 매스 레이드(격자) 전용. can_move가 True인 전투에서만 의미가 있습니다.
        self.grid_pos = None          # (x, y) 또는 None(격자를 쓰지 않는 전투)
        self.can_move = False          # 이 전투가 격자 이동을 지원하는지
        self.moved_this_round = False  # 이번 라운드에 이미 이동을 사용했는지 (행동 전에 한 번만 가능)

    # ------------------------------------------------------------------
    @property
    def is_alive(self) -> bool:
        """전투에 여전히 참여 중인지 여부 (다운/도주시도 포함). 완전히 사망/도주 완료한 경우만 False."""
        return self.status in (self.STATUS_ALIVE, self.STATUS_DOWNED, self.STATUS_FLEEING)

    @property
    def is_downed(self) -> bool:
        return self.status == self.STATUS_DOWNED

    @property
    def stat_total(self) -> int:
        return config.stat_total(self.stats)

    def take_damage(self, amount: int):
        self.current_hp = max(0, self.current_hp - amount)
        if self.current_hp <= 0:
            self.current_hp = 0
            if self.status in (self.STATUS_ALIVE, self.STATUS_FLEEING):
                # 이번 라운드에 이미 행동을 마쳤다면(도주 시도자는 항상 그러합니다) 더 이상의
                # 기회가 없으므로 즉시 사망 처리하고, 아직 행동 전이라면 '다운' 상태로 두어
                # 자신의 턴(방어/힐 등)을 보장합니다. (완전한 사망 확정은 팀 전체의 라운드
                # 행동이 끝난 뒤 이루어집니다)
                self.status = self.STATUS_DEAD if self.has_acted else self.STATUS_DOWNED

    def heal(self, amount: int):
        if self.status not in (self.STATUS_ALIVE, self.STATUS_DOWNED, self.STATUS_FLEEING):
            return
        self.current_hp = min(self.max_hp, self.current_hp + amount)
        if self.status == self.STATUS_DOWNED and self.current_hp > 0:
            self.status = self.STATUS_ALIVE  # 다운 상태에서 회복되어 다시 전투 가능

    def reset_for_new_round(self):
        """새 라운드 시작 시 행동 여부 / 방어·회피 상태를 초기화합니다."""
        if self.status == self.STATUS_FLEEING:
            # 도주 시도 결과가 아직 확정되지 않았다면, 그 결과가 나올 때까지 상태를 건드리지 않습니다.
            return
        self.has_acted = False
        self.defended_this_round = False
        self.defense_grants = []
        self.protecting_ally = None
        self.dodging_this_round = False
        self.pending_attacks = []
        self.moved_this_round = False

    def hp_ratio(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return self.current_hp / self.max_hp

    def available_actions(self):
        """이 캐릭터가 이번 라운드에 사용할 수 있는 행동 목록(역할 전용 + 공통)"""
        if self.forced_actions is not None:
            base = list(self.forced_actions)
        else:
            base = list(config.ROLE_ACTIONS.get(self.role, [])) + list(config.COMMON_ACTIONS)
        if self.can_move and not self.moved_this_round:
            base = [config.ACTION_MOVE] + base
        return base

    def acts_on_any_turn(self) -> bool:
        """이 캐릭터가 자신의 팀 턴이 아니어도 행동할 수 있는지 여부 (예: 힐러)"""
        return self.role in config.FREE_TURN_ROLES

    def to_dict(self):
        """데이터베이스 저장용 딕셔너리로 변환합니다."""
        d = {"role": self.role, "stats": dict(self.stats)}
        if self.color:
            d["color"] = self.color
        return d

    def __repr__(self):
        return f"<Character {self.name} ({self.role}) HP {self.current_hp}/{self.max_hp} [{self.status}]>"


# ==========================================================================
# Skill 클래스들
# ==========================================================================
class Skill:
    """
    전투 행동(스킬)의 기본 클래스입니다.
    실제 수치 계산은 config.py의 함수를 사용합니다.
    """

    name = "스킬"
    allowed_roles = None  # None 이면 모든 역할이 사용 가능

    def can_use(self, actor: Character):
        """이 스킬을 사용할 수 있는지 검사합니다. 반환값: (가능여부:bool, 실패사유:str)"""
        if actor.status == Character.STATUS_DEAD:
            return False, "사망한 캐릭터는 행동할 수 없습니다."
        if actor.status in (Character.STATUS_FLED, Character.STATUS_FLEEING):
            return False, "도주(시도) 중인 캐릭터는 행동할 수 없습니다."
        if actor.has_acted:
            return False, "이미 행동한 캐릭터입니다."
        if actor.forced_actions is not None:
            if self.name not in actor.forced_actions:
                return False, f"이 캐릭터는 {self.name}을(를) 사용할 수 없습니다."
            return True, ""
        if self.allowed_roles is not None and actor.role not in self.allowed_roles:
            role_text = "/".join(self.allowed_roles)
            return False, f"{role_text}만 {self.name}을(를) 사용할 수 있습니다."
        return True, ""


class AttackSkill(Skill):
    name = "공격"
    allowed_roles = None  # 모든 역할이 공격 가능 (탱커 포함)

    def roll(self, actor: Character, overrides: dict = None):
        """공격 굴림만 수행합니다. (대상에게 즉시 적용할지 보류할지는 Battle이 결정)"""
        return config.roll_attack(actor.stats, role=actor.role, overrides=overrides)

    @staticmethod
    def resolve(atk: dict, target: Character, overrides: dict = None, auto_defense: bool = False):
        """
        공격 판정 결과(atk)를 대상에게 실제로 적용합니다.
        회피(딜러 회피/도주 중 강제 회피) -> 방어(능동 계층 소모/무방비) -> 최종 피해 순으로 처리합니다.
        방어는 부여된 순서대로 한 겹씩(FIFO) 소모됩니다. (요청 13)
        도주 시도 중(STATUS_FLEEING)에는 무방비로 취급되며 회피 확률이 1.5배 적용됩니다. (요청 11)
        auto_defense=True(점령전 거점 전용)면 방어 선언 여부와 무관하게 공격 1회당 항상
        능동 방어 1회(1~30 다이스)가 자동으로 발생합니다.
        반환값 dict: dodged, dfs(있다면), damage, hp_before, hp_after
        """
        hp_before = target.current_hp
        is_fleeing = target.status == Character.STATUS_FLEEING

        if target.dodging_this_round or is_fleeing:
            dodge = config.roll_dodge(target.stats, multiplier=1.5 if is_fleeing else 1.0, overrides=overrides)
            if dodge["success"]:
                return {
                    "dodged": True, "dodge": dodge, "dfs": None, "damage": 0,
                    "hp_before": hp_before, "hp_after": hp_before,
                }
        else:
            dodge = None

        if auto_defense and not is_fleeing:
            dfs = config.roll_site_auto_defense(target.stats, overrides=overrides)
        else:
            if is_fleeing:
                # 도주 시도 중에는 걸려있던 방어와 무관하게 무방비로 취급합니다.
                grantor, active = target, False
            elif target.defense_grants:
                grantor = target.defense_grants.pop(0)  # 먼저 걸린 방어부터 소모
                active = True
            else:
                grantor, active = target, False

            dfs = config.roll_defense(
                target.stats, active=active,
                grantor_stats=grantor.stats, grantor_role=grantor.role, grantor_name=grantor.name,
                overrides=overrides,
            )
        damage = config.calculate_final_damage(atk["total"], dfs["total"], overrides=overrides)
        target.take_damage(damage)
        hp_after = target.current_hp

        return {
            "dodged": False, "dodge": dodge, "dfs": dfs, "damage": damage,
            "hp_before": hp_before, "hp_after": hp_after,
        }


class SelfDefendSkill(Skill):
    name = "본인방어"
    allowed_roles = [config.ROLE_DEALER, config.ROLE_HEALER]

    def execute(self, actor: Character):
        actor.defended_this_round = True
        actor.defense_grants.append(actor)
        return {}


class DefendSkill(Skill):
    """탱커 전용 '방어' - 본인 또는 아군 1명(택1)에게 능동 방어를 부여합니다. 어그로 효과는 없습니다."""
    name = "방어"
    allowed_roles = [config.ROLE_TANKER]

    def execute(self, actor: Character, target: Character):
        target.defended_this_round = True
        target.defense_grants.append(actor)  # 방어를 부여한 사람은 항상 이 탱커(actor) 자신입니다.
        actor.protecting_ally = target.name if target is not actor else None
        return {}


class TauntSkill(Skill):
    """
    탱커 전용 '공격유도' - 어그로를 걸 대상(본인 또는 아군)을 지정합니다.
    대상이 본인이면 상대의 다음 공격을 자신에게 유도함과 동시에 스스로에게 능동 방어도 부여됩니다.
    """
    name = "공격유도"
    allowed_roles = [config.ROLE_TANKER]

    def execute(self, actor: Character, target: Character):
        if target is actor:
            actor.defended_this_round = True
            actor.defense_grants.append(actor)
        return {}


class DodgeSkill(Skill):
    """딜러 전용 '회피' - 행운/민첩 기반으로 다음 피격을 완전히 회피할 확률을 얻습니다."""
    name = "회피"
    allowed_roles = [config.ROLE_DEALER]

    def execute(self, actor: Character):
        actor.dodging_this_round = True
        return {}


class HealSkill(Skill):
    name = "힐"
    allowed_roles = [config.ROLE_HEALER]

    def execute(self, actor: Character, target: Character, overrides: dict = None):
        heal = config.roll_heal(actor.stats, role=actor.role, overrides=overrides)
        hp_before = target.current_hp
        target.heal(heal["total"])
        hp_after = target.current_hp
        return {"heal": heal, "hp_before": hp_before, "hp_after": hp_after}


class TimeoutSkill(Skill):
    name = "시간초과"
    allowed_roles = None

    def execute(self, actor: Character):
        return {}


class DefenseSettleSkill(Skill):
    """
    점령전 거점 전용 - 보류된 공격만 정산합니다(forced_actions로만 부여되며, 일반 캐릭터의
    행동 목록에는 나타나지 않습니다). 정식 '행동'으로 소모되지 않으므로(has_acted를 건드리지
    않음) 정산 후에도 이어서 공격/힐을 할 수 있습니다.
    """
    name = "방어 정산"
    allowed_roles = []  # forced_actions가 없는 일반 캐릭터는 아무도 사용할 수 없습니다.

    def execute(self, actor: Character):
        return {}


class FleeSkill(Skill):
    """
    도주를 '시도'합니다. 즉시 전장을 벗어나는 것이 아니라, 상대의 다음 턴 동안 무방비 +
    1.5배 회피 확률로 버텨야 하며, 그 턴을 살아서 넘겨야만 완전한 도주(STATUS_FLED)로 확정됩니다.
    실제 확정 처리(watch key 설정 등)는 Battle이 담당합니다.
    """
    name = "도주"
    allowed_roles = None

    def execute(self, actor: Character):
        actor.status = Character.STATUS_FLEEING
        return {}
