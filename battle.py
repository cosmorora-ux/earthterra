# -*- coding: utf-8 -*-
"""
battle.py
=========
Battle 클래스
    한 판의 전투(팀 구성 / 라운드 / 턴 / 로그 / 규칙 검증)를 관리합니다.
GameManager 클래스
    캐릭터 데이터베이스와 Battle을 아울러 프로그램 전체 흐름을 관리합니다.

핵심 규칙 요약
--------------
- 딜러/탱커/힐러 모두 공격 가능. 치명타는 "본인 포지션다운 행동"일 때만 발생합니다.
- 탱커의 '방어'는 본인 또는 아군 1명에게 능동 방어를 부여합니다 (어그로 없음).
- 탱커의 '공격유도'는 자기 자신에게 어그로를 걸어 상대의 다음 공격을 강제합니다 (방어 효과 없음).
- 딜러의 '회피'는 행운/민첩 기반으로 다음 피격을 완전히 무효화할 확률을 얻습니다.
- 힐러는 공격 선행조건 없이, 그리고 자신의 팀 턴이 아니어도(상대 턴 중에도) 라운드당 1회 행동할 수 있습니다.
- 아직 이번 라운드에 행동하지 않은 대상을 공격하면 피해가 즉시 적용되지 않고 "보류"되며,
  대상이 자신의 턴에 방어/회피/힐 등으로 대응한 뒤 그 결과를 반영해 정산됩니다.
- HP가 0이 되어도 즉시 사망하지 않고 '다운' 상태가 되며, 다운된 캐릭터가 속한 팀 전체가
  이번 라운드 행동을 마쳐야 비로소 생사가 확정됩니다.

로그는 두 종류로 나뉩니다.
    operator_log : 운영진용. 다이스/스탯/확률 등 모든 수식이 노출됩니다.
    public_log   : 러너 공유용. 결과값만 간단히 보여줍니다.
"""

import random
import copy

from models import (
    Character, AttackSkill, SelfDefendSkill, DefendSkill, TauntSkill,
    DodgeSkill, HealSkill, TimeoutSkill, FleeSkill,
)
from database import CharacterDatabase
import config


class BattleError(Exception):
    """전투 규칙 위반 시 발생하는 예외입니다. GUI에서는 이 메시지를 복사 가능한 팝업으로 표시합니다."""
    pass


def decide_first_team(team_a, team_b):
    """
    민첩 합산을 기준으로 선공 팀을 자동 결정합니다.
    동점일 경우 각 팀 대표로 1d100을 굴려 더 높은 쪽이 선공입니다.
    반환값: (first_team_label, [(text, tag), ...])
    """
    agi_a = sum(c.stats.get("민첩", 0) for c in team_a)
    agi_b = sum(c.stats.get("민첩", 0) for c in team_b)

    lines = [(f"[선공 결정] 1팀 민첩 합산 {agi_a}  vs  2팀 민첩 합산 {agi_b}", "system")]

    if agi_a > agi_b:
        first = Battle.TEAM_A
        lines.append((f"→ 민첩 합산이 더 높은 1팀이 선공입니다.", "system"))
    elif agi_b > agi_a:
        first = Battle.TEAM_B
        lines.append((f"→ 민첩 합산이 더 높은 2팀이 선공입니다.", "system"))
    else:
        roll_a = random.randint(1, 100)
        roll_b = random.randint(1, 100)
        lines.append((f"민첩 합산 동점! 1d100 굴림 → 1팀 {roll_a}  vs  2팀 {roll_b}", "system"))
        if roll_a >= roll_b:
            first = Battle.TEAM_A
            lines.append(("→ 주사위 결과, 1팀이 선공입니다.", "system"))
        else:
            first = Battle.TEAM_B
            lines.append(("→ 주사위 결과, 2팀이 선공입니다.", "system"))

    return first, lines


class Battle:
    TEAM_A = "1팀"
    TEAM_B = "2팀"

    def __init__(self, team_a: list, team_b: list):
        self.team_a = team_a
        self.team_b = team_b
        for c in team_a:
            c.team = "A"
        for c in team_b:
            c.team = "B"

        self.operator_log = []  # [{"text":..., "tag":...}, ...] 운영진용 (수식 전체 노출)
        self.public_log = []    # [{"text":..., "tag":...}, ...] 러너 공유용 (결과만)
        self.history = []       # 되돌리기(undo)용 스냅샷 스택
        self._round_summarized = False

        first_team, explain_lines = decide_first_team(team_a, team_b)

        self.round_no = 1
        self.round_first_team = first_team
        self.current_turn_team = first_team

        # 공격유도(어그로) 상태 - 상대의 다음 공격 N회를 강제할 대상 (라운드 경계와 무관하게 유지됨)
        self.forced_target = None       # 강제 지목된 캐릭터 (Character)
        self.forced_target_team = None  # 이 강제 지목을 적용받는 "공격하는 팀"
        self.forced_target_count = 0    # 아직 소모되지 않은 강제 공격 횟수
        self._forced_turn_had_attack = False  # 강제 대상팀이 이번 턴(세그먼트)에 공격을 사용했는지

        self.finished = False
        self.winner = None

        self.attack_skill = AttackSkill()
        self.self_defend_skill = SelfDefendSkill()
        self.defend_skill = DefendSkill()
        self.taunt_skill = TauntSkill()
        self.dodge_skill = DodgeSkill()
        self.heal_skill = HealSkill()
        self.timeout_skill = TimeoutSkill()
        self.flee_skill = FleeSkill()

        for text, tag in explain_lines:
            self._log(text, tag=tag)

        self.round_start_hp = {c.name: c.current_hp for c in self.team_a + self.team_b}

        # "로그 복사 시 해당 턴의 로그만 복사" 기능을 위한, 현재 턴 로그 구간의 시작 인덱스.
        self.turn_op_start = len(self.operator_log)
        self.turn_pub_start = len(self.public_log)

        self._log(f"Round {self.round_no}", tag="round")
        self._log(f"▶ 선공 단계 : {self.round_first_team}", tag="round")

    # ------------------------------------------------------------------
    # 로그 유틸리티
    # ------------------------------------------------------------------
    def _log(self, text: str, tag: str = "normal"):
        """운영자 로그 + 러너 공유 로그에 동일하게 기록합니다."""
        self.operator_log.append({"text": text, "tag": tag})
        self.public_log.append({"text": text, "tag": tag})

    def _log_operator_only(self, text: str, tag: str = "normal"):
        self.operator_log.append({"text": text, "tag": tag})

    def _log_public_only(self, text: str, tag: str = "normal"):
        self.public_log.append({"text": text, "tag": tag})

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------
    def team_members(self, team_label: str):
        return self.team_a if team_label == self.TEAM_A else self.team_b

    def enemy_team_label(self, team_label: str):
        return self.TEAM_B if team_label == self.TEAM_A else self.TEAM_A

    def team_label_of(self, character: Character):
        return self.TEAM_A if character.team == "A" else self.TEAM_B

    def find_character(self, name: str):
        if not name:
            return None
        for c in self.team_a + self.team_b:
            if c.name == name:
                return c
        return None

    def is_team_alive(self, team_label: str):
        return any(c.is_alive for c in self.team_members(team_label))

    def current_turn_label(self) -> str:
        """상단에 크게 표시할 현재 턴 문자열"""
        is_first = self.current_turn_team == self.round_first_team
        order_text = "선공" if is_first else "후공"
        return f"Round {self.round_no}   {self.current_turn_team} {order_text}"

    def _team_key(self, team_label: str):
        return "A" if team_label == self.TEAM_A else "B"

    def _check_actor_turn(self, actor: Character, allow_free_turn: bool = False):
        """
        지금 이 캐릭터가 행동할 수 있는 타이밍인지 검사합니다.
        자기 팀의 턴이면 언제나 가능합니다.
        allow_free_turn=True 인 경우에 한해(=힐 행동에서만), 힐러(FREE_TURN_ROLES)는
        이번 라운드가 "후공 페이즈"에 들어섰다면 자기 팀 턴이 아니어도 행동할 수 있습니다.
        (힐러라도 공격/방어/시간초과/도주 등 힐 이외의 행동은 이 예외가 적용되지 않고,
        반드시 자기 팀 턴에만 사용할 수 있습니다)
        """
        if actor.team == self._team_key(self.current_turn_team):
            return
        is_second_phase = self.current_turn_team != self.round_first_team
        if allow_free_turn and actor.acts_on_any_turn() and is_second_phase:
            return
        raise BattleError("지금은 해당 캐릭터의 턴이 아닙니다.")

    # ------------------------------------------------------------------
    # 되돌리기 (undo) : 잘못 실행된 행동을 취소하고 재행동 기회를 부여합니다.
    # ------------------------------------------------------------------
    def _snapshot(self):
        chars = {}
        for c in self.team_a + self.team_b:
            chars[c.name] = {
                "current_hp": c.current_hp,
                "status": c.status,
                "has_acted": c.has_acted,
                "defended_this_round": c.defended_this_round,
                "defense_grants": [g.name for g in c.defense_grants],
                "aggro_defense_credits": c.aggro_defense_credits,
                "protecting_ally": c.protecting_ally,
                "dodging_this_round": c.dodging_this_round,
                "pending_attacks": copy.deepcopy(c.pending_attacks),
                "fleeing_watch_key": c.fleeing_watch_key,
            }
        return {
            "round_no": self.round_no,
            "round_first_team": self.round_first_team,
            "current_turn_team": self.current_turn_team,
            "finished": self.finished,
            "winner": self.winner,
            "forced_target": self.forced_target.name if self.forced_target else None,
            "forced_target_team": self.forced_target_team,
            "forced_target_count": self.forced_target_count,
            "forced_turn_had_attack": self._forced_turn_had_attack,
            "round_start_hp": dict(self.round_start_hp),
            "round_summarized": self._round_summarized,
            "chars": chars,
            "op_len": len(self.operator_log),
            "pub_len": len(self.public_log),
            "turn_op_start": self.turn_op_start,
            "turn_pub_start": self.turn_pub_start,
        }

    def _push_history(self):
        self.history.append(self._snapshot())
        if len(self.history) > 100:
            self.history.pop(0)

    def can_undo(self) -> bool:
        return len(self.history) > 0

    def undo_last(self):
        """가장 최근 행동(또는 턴 전환)을 취소하고, 그 행동 이전 상태로 되돌립니다."""
        if not self.history:
            raise BattleError("취소할 행동이 없습니다.")
        snap = self.history.pop()

        self.round_no = snap["round_no"]
        self.round_first_team = snap["round_first_team"]
        self.current_turn_team = snap["current_turn_team"]
        self.finished = snap["finished"]
        self.winner = snap["winner"]
        self.forced_target = self.find_character(snap["forced_target"])
        self.forced_target_team = snap["forced_target_team"]
        self.forced_target_count = snap["forced_target_count"]
        self._forced_turn_had_attack = snap["forced_turn_had_attack"]
        self.round_start_hp = dict(snap["round_start_hp"])
        self._round_summarized = snap["round_summarized"]
        self.turn_op_start = snap["turn_op_start"]
        self.turn_pub_start = snap["turn_pub_start"]

        for c in self.team_a + self.team_b:
            cs = snap["chars"][c.name]
            c.current_hp = cs["current_hp"]
            c.status = cs["status"]
            c.has_acted = cs["has_acted"]
            c.defended_this_round = cs["defended_this_round"]
            c.protecting_ally = cs["protecting_ally"]
            c.dodging_this_round = cs["dodging_this_round"]
            c.pending_attacks = copy.deepcopy(cs["pending_attacks"])
            c.fleeing_watch_key = cs["fleeing_watch_key"]
            c.aggro_defense_credits = cs["aggro_defense_credits"]
        for c in self.team_a + self.team_b:
            grant_names = snap["chars"][c.name]["defense_grants"]
            c.defense_grants = [self.find_character(n) for n in grant_names if self.find_character(n)]

        del self.operator_log[snap["op_len"]:]
        del self.public_log[snap["pub_len"]:]

    # ------------------------------------------------------------------
    # 공격 판정/정산 공용 로직
    # ------------------------------------------------------------------
    def _log_attack_resolution(self, target: Character, result: dict):
        """공격 결과(회피/방어/피해)를 로그에 기록합니다. (즉시 정산/보류 정산 공용)"""
        if result["dodged"]:
            self._log(
                f"{target.name} 회피 성공! (확률 {result['dodge']['chance']}%) - 피해 없음",
                tag="heal",
            )
            return

        dfs = result["dfs"]
        if not dfs["active"]:
            self._log_operator_only(
                f"방어 굴림(무방비/수동 방어) : 방어{dfs['stat_val']}×{dfs['stat_mult']} = {dfs['total']} (다이스 없음)",
                tag="formula",
            )
        else:
            grantor_desc = (
                f"{dfs['grantor_name']}이(가) 부여" if dfs['grantor_name'] != target.name else "본인"
            )
            self._log_operator_only(
                f"방어 굴림(능동 방어 - {grantor_desc}) : "
                f"수동 바닥값 {dfs['passive_component']} + "
                f"[다이스 {dfs['final_rolls']}(1차 {dfs['first_rolls']}) 합 "
                f"{sum(dfs['final_rolls'])} + 방어{dfs['stat_val']}×{dfs['stat_mult']}] "
                f"= 능동계층 {dfs['active_component']}  →  총 {dfs['total']}",
                tag="formula",
            )
        if dfs["is_crit"]:
            self._log_operator_only(
                f"→ 방어 크리티컬! (확률 {dfs['crit_chance']}%) ×{dfs['crit_mult']} = {dfs['total']}",
                tag="crit",
            )
            self._log_public_only("상대 방어 크리티컬!", tag="crit")
        elif dfs["active"] and not dfs["position_match"]:
            self._log_operator_only(
                f"(방어를 부여한 사람이 탱커가 아니므로 방어 크리티컬이 발생하지 않습니다)", tag="formula",
            )

        # 요청 12 : 방어 값(총합)은 러너 공유 로그에도 표시합니다. (단, 무방비/수동 방어는 제외)
        if dfs["active"]:
            self._log_public_only(f"방어 값 {dfs['total']}", tag="defend")

        self._log(f"피해량 {result['damage']}", tag="damage")
        self._log(f"{target.name} HP", tag="hp")
        self._log(f"{result['hp_before']} → {result['hp_after']}", tag="hp")

        if target.status == Character.STATUS_DOWNED:
            self._log(
                f"{target.name} 다운! (팀 전체가 이번 라운드 행동을 마쳐야 생사가 확정됩니다)",
                tag="system",
            )
        elif target.status == Character.STATUS_DEAD:
            self._log(f"{target.name} 사망", tag="system")

    def _resolve_pending_attacks(self, actor: Character):
        """
        actor 자신에게 걸려있던 '보류된 공격'을 정산합니다.
        actor가 이번 라운드 자신의 행동(방어/회피 등)을 선언한 직후, 다른 효과를 적용하기 전에 호출됩니다.
        """
        if not actor.pending_attacks:
            return
        pending = actor.pending_attacks
        actor.pending_attacks = []
        for entry in pending:
            self._log(f"[피해 정산] {entry['attacker_name']} → {actor.name}", tag="action")
            result = AttackSkill.resolve(entry["atk"], actor)
            self._log_attack_resolution(actor, result)

    # ------------------------------------------------------------------
    # 행동 : 공격 (모든 역할 가능)
    # ------------------------------------------------------------------
    def perform_attack(self, attacker_name: str, target_name: str):
        attacker = self.find_character(attacker_name)
        target = self.find_character(target_name)

        if attacker is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(attacker)

        ok, reason = self.attack_skill.can_use(attacker)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")

        # 강제 대상이 죽거나 도주해 더 이상 유효하지 않다면 정리합니다.
        if self.forced_target is not None and not self.forced_target.is_alive:
            self.forced_target = None
            self.forced_target_team = None
            self.forced_target_count = 0

        attacker_team_label = self.team_label_of(attacker)
        forced_active = (
            self.forced_target is not None
            and self.forced_target_team == attacker_team_label
        )
        if forced_active and target is not self.forced_target:
            raise BattleError(
                "현재 공격유도 효과가 적용 중입니다.\n"
                f"이번 공격은 반드시 {self.forced_target.name}을(를) 대상으로 해야 합니다. "
                f"(남은 강제 횟수 {self.forced_target_count}회)"
            )

        self._push_history()

        # 공격자 자신에게 걸려있던 보류 피해를 먼저 정산합니다.
        self._resolve_pending_attacks(attacker)

        atk = self.attack_skill.roll(attacker)
        attacker.has_acted = True

        self._log(f"{attacker.name} 공격 → {target.name}", tag="action")
        # 요청 1 : 공격 수치는 정산(HP 반영) 여부와 무관하게 즉시 알 수 있어야 합니다.
        self._log(f"공격 수치 {atk['total']}", tag="damage")
        self._log_operator_only(
            f"공격 굴림 : 다이스(1~{atk['dice_sides']}, {atk['dice_count']}개, "
            f"재굴림 기준치 {atk['mental_threshold']} 이하) "
            f"1차 {atk['first_rolls']} → 최종 {atk['final_rolls']} 합계 {atk['dice_subtotal']} "
            f"+ 공격{atk['stat_val']}×{atk['stat_mult']} = {atk['subtotal']}",
            tag="formula",
        )
        if atk["is_crit"]:
            self._log_operator_only(
                f"→ 크리티컬! (확률 {atk['crit_chance']}%) ×{atk['crit_mult']} = {atk['total']}",
                tag="crit",
            )
            self._log_public_only("크리티컬!", tag="crit")
        elif not atk["position_match"]:
            self._log_operator_only(
                f"({attacker.name}은(는) 딜러가 아니므로 크리티컬이 발생하지 않습니다)", tag="formula",
            )

        if target.has_acted:
            # 대상이 이미 이번 라운드 행동을 마쳤다면 더 기다릴 필요가 없으므로 즉시 정산합니다.
            result = AttackSkill.resolve(atk, target)
            self._log_attack_resolution(target, result)
        else:
            # 대상이 아직 이번 라운드 행동 전이라면 피해를 보류하고, 대상의 턴에 정산합니다.
            target.pending_attacks.append({"attacker_name": attacker.name, "atk": atk})
            self._log(
                f"{target.name} 판정 대기중 (피격자의 행동 대응 후 피해값이 정산됩니다)", tag="system",
            )

        if forced_active:
            self._forced_turn_had_attack = True
            self.forced_target_count -= 1
            self._log(
                f"공격 대상 변경 (공격유도 효과, 남은 강제 횟수 {self.forced_target_count}회)", tag="system",
            )
            if self.forced_target_count <= 0:
                self.forced_target = None
                self.forced_target_team = None
                self.forced_target_count = 0

        self._check_finish()
        return atk

    # ------------------------------------------------------------------
    # 행동 : 본인방어 (딜러 / 힐러)
    # ------------------------------------------------------------------
    def perform_self_defend(self, name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.self_defend_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        self._push_history()
        self.self_defend_skill.execute(actor)
        self._resolve_pending_attacks(actor)
        actor.has_acted = True

        self._log(f"{actor.name} 본인방어", tag="defend")
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 방어 (탱커 전용) - 본인 또는 아군 1명(택1)에게 능동 방어를 부여합니다.
    # ------------------------------------------------------------------
    def perform_defend(self, tanker_name: str, target_name: str):
        tanker = self.find_character(tanker_name)
        target = self.find_character(target_name)

        if tanker is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(tanker)

        ok, reason = self.defend_skill.can_use(tanker)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")

        self._push_history()
        self.defend_skill.execute(tanker, target)
        self._resolve_pending_attacks(tanker)
        tanker.has_acted = True

        if target is tanker:
            self._log(f"{tanker.name} 방어 (본인)", tag="defend")
        else:
            self._log(f"{tanker.name} 방어 → {target.name} (능동 방어 부여)", tag="defend")
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 공격유도 (탱커 전용) - 어그로를 걸 대상(본인/아군)을 지정합니다.
    # ------------------------------------------------------------------
    def perform_taunt(self, tanker_name: str, target_name: str):
        tanker = self.find_character(tanker_name)
        target = self.find_character(target_name)
        if tanker is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(tanker)

        ok, reason = self.taunt_skill.can_use(tanker)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")
        if target.team != tanker.team:
            raise BattleError("공격유도 대상은 같은 팀의 캐릭터여야 합니다.")

        self._push_history()
        self.taunt_skill.execute(tanker, target)
        self._resolve_pending_attacks(tanker)
        tanker.has_acted = True

        enemy_label = self.enemy_team_label(self.team_label_of(tanker))
        if self.forced_target is target:
            self.forced_target_count += 1  # 같은 대상에게 다시 걸면 강제 횟수가 누적됩니다.
        else:
            self.forced_target = target
            self.forced_target_team = enemy_label
            self.forced_target_count = 1

        if target is tanker:
            self._log(f"{tanker.name} 공격유도 (본인) - 능동 방어 크레딧도 함께 부여됩니다", tag="taunt")
        else:
            self._log(f"{tanker.name} 공격유도 → {target.name} (능동 방어 크레딧 부여)", tag="taunt")
        self._log(
            f"→ {enemy_label}의 다음 공격 {self.forced_target_count}회가 {target.name}을(를) 대상으로 강제됩니다.",
            tag="system",
        )
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 회피 (딜러 전용)
    # ------------------------------------------------------------------
    def perform_dodge(self, name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.dodge_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        self._push_history()
        self.dodge_skill.execute(actor)
        self._resolve_pending_attacks(actor)
        actor.has_acted = True

        self._log(f"{actor.name} 회피 태세", tag="action")
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 힐 (힐러 전용) - 공격 선행조건 없음. 어느 팀 턴이든 사용 가능(라운드 1회).
    # ------------------------------------------------------------------
    def perform_heal(self, healer_name: str, target_name: str):
        healer = self.find_character(healer_name)
        target = self.find_character(target_name)

        if healer is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(healer, allow_free_turn=True)

        ok, reason = self.heal_skill.can_use(healer)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("사망한 캐릭터는 회복 대상이 될 수 없습니다.")

        self._push_history()
        self._resolve_pending_attacks(healer)

        target_was_downed = target.status == Character.STATUS_DOWNED
        result = self.heal_skill.execute(healer, target)
        healer.has_acted = True

        heal = result["heal"]
        self._log(f"{healer.name} 힐 → {target.name}", tag="action")
        self._log_operator_only(
            f"힐 굴림 : 다이스(1~{heal['dice_sides']}, {heal['dice_count']}개, "
            f"재굴림 기준치 {heal['mental_threshold']} 이하) "
            f"1차 {heal['first_rolls']} → 최종 {heal['final_rolls']} 합계 {heal['dice_subtotal']} "
            f"× 배율{config.HEAL_OUTPUT_MULTIPLIER} = {heal['base_total']}",
            tag="formula",
        )
        if heal["is_crit"]:
            self._log_operator_only(
                f"→ 크리티컬! (확률 {heal['crit_chance']}%) ×{heal['crit_mult']} = {heal['total']}",
                tag="crit",
            )
            self._log_public_only("크리티컬!", tag="crit")
        elif not heal["position_match"]:
            self._log_operator_only(
                f"({healer.name}은(는) 힐러가 아니므로 크리티컬이 발생하지 않습니다)", tag="formula",
            )

        self._log(f"회복 {heal['total']}", tag="heal")
        self._log(f"{target.name} HP", tag="hp")
        self._log(f"{result['hp_before']} → {result['hp_after']}", tag="hp")

        if target_was_downed and target.status == Character.STATUS_ALIVE:
            self._log(f"{target.name} 위기를 넘기고 전투에 복귀했습니다!", tag="system")

        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 시간 초과 / 도주 (전원 공통)
    # ------------------------------------------------------------------
    def perform_timeout(self, name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.timeout_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        self._push_history()
        self.timeout_skill.execute(actor)
        self._resolve_pending_attacks(actor)
        actor.has_acted = True
        self._log(f"{actor.name} 시간 초과", tag="system")
        self._check_finish()

    def perform_flee(self, name: str):
        """
        도주를 '시도'합니다. 즉시 전장을 벗어나는 것이 아니라, 상대의 다음 턴 동안 무방비 +
        회피 확률 1.5배로 버텨야 하며, 그 턴을 살아서 넘겨야만 완전한 도주로 확정됩니다.
        """
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.flee_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        self._push_history()
        self._resolve_pending_attacks(actor)
        self.flee_skill.execute(actor)
        actor.has_acted = True

        watch_key = "B" if actor.team == "A" else "A"
        actor.fleeing_watch_key = watch_key
        watch_label = self.TEAM_B if watch_key == "B" else self.TEAM_A

        self._log(
            f"{actor.name} 도주 시도 ({watch_label}의 다음 턴 동안 무방비 상태 + 회피 확률 1.5배 - "
            f"생존해야 완전히 이탈합니다)",
            tag="system",
        )
        self._check_finish()

    # ------------------------------------------------------------------
    # 턴 진행
    # ------------------------------------------------------------------
    def _blocking_members(self):
        """
        지금 '다음 턴'으로 넘어가는 것을 막고 있는(아직 행동해야 하는) 캐릭터 목록을 반환합니다.
        라운드가 끝나는 시점(후공 팀 턴이 끝날 때)이 아니라면, 힐러는 아직 행동하지 않았더라도
        막지 않습니다(후공 페이즈까지 기다릴 수 있으므로). 라운드가 진짜로 끝나는 시점에는
        상대팀에 남아있는 힐러의 미행동도 함께 확인합니다.
        """
        is_ending_round = self.current_turn_team != self.round_first_team
        is_first_phase = not is_ending_round

        members = list(self.team_members(self.current_turn_team))
        if is_ending_round:
            other_team = self.enemy_team_label(self.current_turn_team)
            members += [c for c in self.team_members(other_team) if c.acts_on_any_turn()]

        blocking = []
        for c in members:
            if not c.is_alive or c.has_acted:
                continue
            if is_first_phase and c.acts_on_any_turn():
                continue  # 힐러는 후공 페이즈까지 기다릴 수 있으므로 지금은 막지 않습니다.
            blocking.append(c)
        return blocking

    def can_advance_turn(self) -> bool:
        return len(self._blocking_members()) == 0

    def unacted_members(self):
        return [c.name for c in self._blocking_members()]

    def _finalize_team_downed(self, team_label: str):
        """
        다운 상태 캐릭터 중 "이미 자신의 행동(마지막 기회)을 사용한" 캐릭터의 생사를 확정합니다.
        아직 행동하지 않은 채 다운 상태인 캐릭터(예: 후공 페이즈를 기다리는 힐러)는 건너뛰고,
        나중에(그 캐릭터가 실제로 행동한 뒤) 확정됩니다.
        """
        for c in self.team_members(team_label):
            if c.status == Character.STATUS_DOWNED and c.has_acted:
                if c.current_hp > 0:
                    c.status = Character.STATUS_ALIVE
                    self._log(f"{c.name} 위기를 넘겼습니다", tag="system")
                else:
                    c.status = Character.STATUS_DEAD
                    self._log(f"{c.name} 사망 (팀의 라운드 행동이 모두 끝났습니다)", tag="system")

    def _finalize_fleeing(self, ending_team_key: str):
        """
        도주를 시도했던 캐릭터 중, 지금 턴이 끝나는 팀이 그 '감시 대상팀'과 일치하면
        (즉, 상대의 다음 턴을 무사히 넘겼다면) 도주를 완전히 확정합니다.
        """
        for c in self.team_a + self.team_b:
            if c.status == Character.STATUS_FLEEING and c.fleeing_watch_key == ending_team_key:
                c.status = Character.STATUS_FLED
                c.fleeing_watch_key = None
                self._log(f"{c.name} 도주 성공! 전장에서 완전히 벗어났습니다.", tag="system")

    def advance_turn(self):
        if self.finished:
            raise BattleError("전투가 이미 종료되었습니다.")
        if not self.can_advance_turn():
            names = ", ".join(self.unacted_members())
            raise BattleError(f"아직 행동하지 않은 캐릭터가 있습니다.\n({names})")

        self._push_history()

        self._check_aggro_release()
        self._finalize_fleeing(self._team_key(self.current_turn_team))

        is_ending_round = self.current_turn_team != self.round_first_team
        if is_ending_round:
            # 라운드가 완전히 끝나는 시점이므로 양 팀 모두의 다운 상태를 최종 확정합니다.
            self._finalize_team_downed(self.TEAM_A)
            self._finalize_team_downed(self.TEAM_B)
        else:
            self._finalize_team_downed(self.current_turn_team)

        self._check_finish()
        if self.finished:
            return

        self._log("↓", tag="arrow")

        if is_ending_round:
            self._log_round_summary()
            self._start_new_round()
        else:
            self.current_turn_team = self.enemy_team_label(self.current_turn_team)
            self.turn_op_start = len(self.operator_log)
            self.turn_pub_start = len(self.public_log)
            self._log_aggro_reminder_if_needed(self.current_turn_team)
            self._log(f"▶ 후공 단계 : {self.current_turn_team}", tag="round")

    def _check_aggro_release(self):
        """
        공격유도 대상팀의 턴이 끝나는데, 그 팀이 이번 턴에 단 한 번도 공격을 사용하지 않았다면
        공격유도 효과가 자동으로 해제됩니다. (요청 10)
        """
        if (
            self.forced_target is not None
            and self.forced_target_team == self.current_turn_team
            and not self._forced_turn_had_attack
        ):
            self._log(
                f"⚠ 공격유도 효과가 해제되었습니다 ({self.current_turn_team}이(가) 이번 턴에 "
                f"공격을 사용하지 않았습니다).",
                tag="system",
            )
            self.forced_target = None
            self.forced_target_team = None
            self.forced_target_count = 0
        self._forced_turn_had_attack = False

    def _log_aggro_reminder_if_needed(self, team_about_to_act: str):
        """
        공격유도 효과가 아직 남아있고, 지금 턴을 받는 팀이 그 강제 대상을 공격해야 하는 팀이라면
        라운드/턴 개시 문구보다 먼저 안내합니다. (라운드 경계를 넘어서도 유지됩니다)
        """
        if (
            self.forced_target is not None
            and self.forced_target.is_alive
            and self.forced_target_team == team_about_to_act
        ):
            self._forced_turn_had_attack = False  # 이번 턴에는 아직 공격을 사용하지 않았습니다.
            self._log(
                f"⚠ 공격유도 효과가 남아있습니다 : {team_about_to_act}의 다음 공격 "
                f"{self.forced_target_count}회는 반드시 {self.forced_target.name}을(를) 대상으로 해야 합니다.",
                tag="system",
            )

    def _start_new_round(self):
        self.round_no += 1
        self.round_first_team = self.enemy_team_label(self.round_first_team)
        self.current_turn_team = self.round_first_team

        for c in self.team_a + self.team_b:
            c.reset_for_new_round()
        # 참고 : 공격유도(본인)로 생긴 능동 방어 크레딧(aggro_defense_credits)은
        # reset_for_new_round()의 영향을 받지 않고, 실제로 소모될 때까지 그 자체로
        # 라운드 경계를 넘어 유지됩니다. 어그로 횟수(forced_target_count)와는 완전히
        # 별개의 자원이므로 여기서 서로 동기화하지 않습니다.

        self._round_summarized = False
        self.round_start_hp = {c.name: c.current_hp for c in self.team_a + self.team_b}

        self.turn_op_start = len(self.operator_log)
        self.turn_pub_start = len(self.public_log)
        self._log_aggro_reminder_if_needed(self.current_turn_team)
        self._log(f"Round {self.round_no}", tag="round")
        self._log(f"▶ 선공 단계 : {self.round_first_team}", tag="round")

    # ------------------------------------------------------------------
    # 라운드 요약 / 종료 판정
    # ------------------------------------------------------------------
    def _log_round_summary(self):
        if self._round_summarized:
            return
        self._round_summarized = True
        self._log(f"▶ 최종 결과 (Round {self.round_no})", tag="round")
        self._log("시작 체력 → 종료 체력", tag="system")
        for c in self.team_a + self.team_b:
            start = self.round_start_hp.get(c.name, c.current_hp)
            state = ""
            if c.status == Character.STATUS_DEAD:
                state = " (사망)"
            elif c.status == Character.STATUS_FLED:
                state = " (도주)"
            self._log(f"{c.name}  {start} → {c.current_hp}{state}", tag="summary")

    def _check_finish(self):
        a_alive = self.is_team_alive(self.TEAM_A)
        b_alive = self.is_team_alive(self.TEAM_B)
        if not a_alive or not b_alive:
            self.finished = True
            if a_alive and not b_alive:
                self.winner = self.TEAM_A
            elif b_alive and not a_alive:
                self.winner = self.TEAM_B
            else:
                self.winner = None  # 양 팀 동시 전멸 -> 무승부
            self._log_round_summary()
            self._log("전투 종료", tag="round")
            self._log(f"승리 팀 : {self.winner}" if self.winner else "무승부", tag="round")


class GameManager:
    """
    프로그램 전체 흐름(캐릭터 데이터베이스, 팀 편성, 전투 생성)을 관리하는
    최상위 클래스입니다. GUI는 이 클래스를 통해서만 데이터에 접근합니다.
    """

    def __init__(self):
        self.db = CharacterDatabase()
        self.battle = None

    # ------------------------------------------------------------------
    def build_character(self, name: str) -> Character:
        """데이터베이스에서 이름으로 캐릭터를 찾아 전투용 Character 인스턴스를 생성합니다."""
        data = self.db.get(name)
        if data is None:
            raise BattleError("존재하지 않는 캐릭터입니다.")
        return Character(name, data["role"], data["stats"], data.get("color"))

    def build_team(self, names: list) -> list:
        """이름 리스트(3개)로 팀(Character 리스트)을 생성합니다."""
        team = []
        for name in names:
            name = (name or "").strip()
            if not name:
                raise BattleError("캐릭터 이름을 모두 입력해주세요.")
            team.append(self.build_character(name))
        return team

    def start_battle(self, team_a_names: list, team_b_names: list) -> Battle:
        """선공 팀은 민첩 합산을 기준으로 Battle이 자동으로 결정합니다."""
        team_a = self.build_team(team_a_names)
        team_b = self.build_team(team_b_names)
        self.battle = Battle(team_a, team_b)
        return self.battle
