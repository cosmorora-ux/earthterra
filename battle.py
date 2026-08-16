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
    DodgeSkill, HealSkill, TimeoutSkill, FleeSkill, DefenseSettleSkill,
    CommandSkill, SwapSkill,
    CollapseSkill, EmissionSkill, ShieldSkill, PolarizeSkill, RefluxSkill, RestoreSkill,
)
from database import CharacterDatabase
import config


class BattleError(Exception):
    """전투 규칙 위반 시 발생하는 예외입니다. GUI에서는 이 메시지를 복사 가능한 팝업으로 표시합니다."""
    pass


def cell_label(x: int, y: int) -> str:
    """격자 좌표를 체스판/스프레드시트 표기처럼 '알파벳+숫자'로 변환합니다. (예: (0,0) -> A1)"""
    col = ""
    n = x
    while True:
        col = chr(65 + (n % 26)) + col
        n = n // 26 - 1
        if n < 0:
            break
    return f"{col}{y + 1}"


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

    def __init__(self, team_a: list, team_b: list, forced_first_team: str = None,
                 formula_overrides: dict = None, site_auto_defense: bool = False,
                 grid_width: int = None, grid_height: int = None):
        self.team_a = team_a
        self.team_b = team_b
        for c in team_a:
            c.team = "A"
        for c in team_b:
            c.team = "B"

        self.formula_overrides = formula_overrides  # 이 전투(방 전투 유형)에 적용되는 수식 override
        # 마스 레이드 전용 격자 크기. None이면 이 전투는 격자를 사용하지 않습니다.
        self.grid_width = grid_width
        self.grid_height = grid_height
        # 점령전 전용 : 2팀(거점) 캐릭터는 공격을 받을 때마다 방어 선언 여부와 무관하게
        # 항상 능동 방어 1회가 자동으로 발생합니다.
        self.site_auto_defense = site_auto_defense

        self.operator_log = []  # [{"text":..., "tag":...}, ...] 운영진용 (수식 전체 노출)
        self.public_log = []    # [{"text":..., "tag":...}, ...] 러너 공유용 (결과만)
        self.history = []       # 되돌리기(undo)용 스냅샷 스택
        self._round_summarized = False

        # PVP 전용 규칙 : 같은 라운드에 한 대상을 3명 전부가 몰아서 공격할 수 없고, 최대 2명까지만
        # 공격할 수 있습니다(집중 공격 제한). 점령전/마스 레이드는 다인원이 거점·몹을 공격하는 게
        # 핵심 메커닉이라 이 제한을 적용하지 않습니다(site_auto_defense로 구분).
        self._attacks_on_target_this_round = {}

        if forced_first_team is not None:
            first_team = forced_first_team
            explain_lines = [(f"[규칙] {first_team}이 항상 선공입니다.", "system")]
        else:
            first_team, explain_lines = decide_first_team(team_a, team_b)

        self.round_no = 1
        self.round_first_team = first_team
        self.current_turn_team = first_team

        # 공격유도/지휘(어그로) 상태 - "공격하는 팀"별로 독립적으로 유지됩니다. 양 팀이 각자
        # 어그로를 걸면 서로 다른 강제 지목이 동시에 존재할 수 있습니다(한쪽이 걸었다고 다른 쪽
        # 효과가 사라지지 않음). 라운드 경계와 무관하게 유지됨.
        # {team_label: {"target": Character, "count": int, "grantor": Character}}
        self.forced_targets = {}
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
        self.defense_settle_skill = DefenseSettleSkill()
        self.command_skill = CommandSkill()
        self.swap_skill = SwapSkill()
        self.collapse_skill = CollapseSkill()
        self.emission_skill = EmissionSkill()
        self.shield_skill = ShieldSkill()
        self.polarize_skill = PolarizeSkill()
        self.reflux_skill = RefluxSkill()
        self.restore_skill = RestoreSkill()

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
    def _log_entry(self, text: str, tag: str, role: str = None):
        entry = {"text": text, "tag": tag}
        if role:
            entry["role"] = role  # 크리티컬로 강조할 때만 채워짐 - 클라이언트가 직군별 색상을 입힙니다.
        return entry

    def _log(self, text: str, tag: str = "normal", role: str = None):
        """운영자 로그 + 러너 공유 로그에 동일하게 기록합니다."""
        self.operator_log.append(self._log_entry(text, tag, role))
        self.public_log.append(self._log_entry(text, tag, role))

    def log_event(self, text: str, tag: str = "system"):
        """외부(웹 서버 등)에서 전투 규칙 관련 안내를 로그에 남기기 위한 공개 메서드입니다."""
        self._log(text, tag=tag)

    def _log_operator_only(self, text: str, tag: str = "normal", role: str = None):
        self.operator_log.append(self._log_entry(text, tag, role))

    def _log_public_only(self, text: str, tag: str = "normal", role: str = None):
        self.public_log.append(self._log_entry(text, tag, role))

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

    # ------------------------------------------------------------------
    # 공격유도/지휘(어그로) 강제 지목 - 팀별로 독립적인 상태를 다룹니다.
    # ------------------------------------------------------------------
    def _forced_for(self, team_label: str):
        """team_label 팀이 지금 강제로 공격해야 하는 대상 정보. 대상이 죽었으면 자동 해제합니다."""
        forced = self.forced_targets.get(team_label)
        if forced is not None and not forced["target"].is_alive:
            del self.forced_targets[team_label]
            return None
        return forced

    def _register_forced_target(self, grantor: Character, target: Character, forced_team: str) -> int:
        """grantor가 target에게 어그로를 걸어, forced_team의 다음 공격을 강제합니다.
        같은 대상에게 다시 걸면 남은 강제 횟수가 누적되고, 다른 대상으로 걸면 그 팀 몫만 교체됩니다
        (다른 팀에 걸려 있는 강제 지목에는 영향을 주지 않습니다)."""
        existing = self.forced_targets.get(forced_team)
        if existing is not None and existing["target"] is target:
            existing["count"] += 1
        else:
            self.forced_targets[forced_team] = {"target": target, "count": 1, "grantor": grantor}
        return self.forced_targets[forced_team]["count"]

    def _consume_forced_target(self, attacker_team_label: str, log_text: str):
        """attacker_team_label 팀이 강제 대상을 공격해서 강제 횟수를 1 소모합니다."""
        forced = self.forced_targets.get(attacker_team_label)
        if forced is None:
            return
        self._forced_turn_had_attack = True
        forced["count"] -= 1
        self._log(log_text.format(count=forced["count"]), tag="system")
        if forced["count"] <= 0:
            del self.forced_targets[attacker_team_label]

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
                "protecting_ally": c.protecting_ally,
                "dodging_this_round": c.dodging_this_round,
                "pending_attacks": copy.deepcopy(c.pending_attacks),
                "fleeing_watch_key": c.fleeing_watch_key,
                "grid_pos": c.grid_pos,
                "moved_this_round": c.moved_this_round,
                "shield_permanent": c.shield_permanent,
                "shield_temp": c.shield_temp,
                "shield_temp_expires_round": c.shield_temp_expires_round,
                "polarize_active": c.polarize_active,
                "polarize_expires_round": c.polarize_expires_round,
                "polarize_overflow": c.polarize_overflow,
                "polarize_ally_count": c.polarize_ally_count,
                "leech_buff_expires_round": c.leech_buff_expires_round,
            }
        return {
            "round_no": self.round_no,
            "round_first_team": self.round_first_team,
            "current_turn_team": self.current_turn_team,
            "finished": self.finished,
            "winner": self.winner,
            "forced_targets": {
                team: {"target": f["target"].name, "count": f["count"], "grantor": f["grantor"].name}
                for team, f in self.forced_targets.items()
            },
            "forced_turn_had_attack": self._forced_turn_had_attack,
            "round_start_hp": dict(self.round_start_hp),
            "round_summarized": self._round_summarized,
            "attacks_on_target_this_round": dict(self._attacks_on_target_this_round),
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
        self.forced_targets = {
            team: {
                "target": self.find_character(f["target"]),
                "count": f["count"],
                "grantor": self.find_character(f["grantor"]),
            }
            for team, f in snap.get("forced_targets", {}).items()
        }
        self._forced_turn_had_attack = snap["forced_turn_had_attack"]
        self.round_start_hp = dict(snap["round_start_hp"])
        self._round_summarized = snap["round_summarized"]
        self._attacks_on_target_this_round = dict(snap.get("attacks_on_target_this_round", {}))
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
            c.grid_pos = cs["grid_pos"]
            c.moved_this_round = cs["moved_this_round"]
            c.shield_permanent = cs["shield_permanent"]
            c.shield_temp = cs["shield_temp"]
            c.shield_temp_expires_round = cs["shield_temp_expires_round"]
            c.polarize_active = cs["polarize_active"]
            c.polarize_expires_round = cs["polarize_expires_round"]
            c.polarize_overflow = cs["polarize_overflow"]
            c.polarize_ally_count = cs["polarize_ally_count"]
            c.leech_buff_expires_round = cs["leech_buff_expires_round"]
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
        elif dfs.get("auto"):
            self._log_operator_only(
                f"거점 자동 방어(1~30 굴림) : 다이스 {dfs['roll']} + 방어{dfs['stat_val']}×{dfs['stat_mult']} "
                f"= 능동계층 {dfs['active_component']} (+ 수동 바닥값 {dfs['passive_component']}) → 총 {dfs['total']}",
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
        elif dfs.get("auto"):
            pass  # 거점/적 자동 방어는 치명타가 발생하지 않는 규칙이므로 별도 안내가 필요 없습니다.
        elif dfs["active"] and not dfs["position_match"]:
            self._log_operator_only(
                f"(방어를 부여한 사람이 탱커가 아니므로 방어 크리티컬이 발생하지 않습니다)", tag="formula",
            )

        # 요청 12 : 방어 값(총합)은 러너 공유 로그에도 표시합니다. 크리티컬이면 방어를 부여한
        # 캐릭터의 직군 색으로 강조합니다.
        if dfs["is_crit"]:
            grantor = self.find_character(dfs.get("grantor_name"))
            self._log_public_only(
                f"방어 값 {dfs['total']}", tag="defend", role=grantor.role if grantor else None,
            )
        else:
            self._log_public_only(f"방어 값 {dfs['total']}", tag="defend")

        self._log(f"피해량 {result['damage']}", tag="damage")
        self._log(f"{target.name} HP {result['hp_before']} → {result['hp_after']}", tag="hp")

        if target.status == Character.STATUS_DOWNED:
            self._log(
                f"{target.name} 다운! (팀 전체가 이번 라운드 행동을 마쳐야 생사가 확정됩니다)",
                tag="system",
            )
        elif target.status == Character.STATUS_DEAD:
            self._log(f"{target.name} 사망", tag="system")

    def _auto_defense_for(self, target: Character) -> bool:
        """점령전 거점(2팀) 대상이면 방어 선언 여부와 무관하게 항상 능동 방어가 자동 발생합니다."""
        return self.site_auto_defense and target.team == "B"

    def _redirect_for_polarize(self, target: Character) -> Character:
        """편광(가디언 스킬)이 활성화된 아군이 있으면 공격 대상을 그쪽으로 강제 리다이렉트합니다."""
        if target.polarize_active:
            return target
        polarizer = next(
            (c for c in self.team_members(self.team_label_of(target)) if c.polarize_active and c.is_alive),
            None,
        )
        if polarizer is not None:
            self._log(f"🛡 편광 : {target.name}에게 향한 피해가 {polarizer.name}에게 집중됩니다.", tag="system")
            return polarizer
        return target

    def _maybe_trigger_leech(self, actor: Character):
        """환류(메딕 스킬) 흡수 버프 보유자가 공격/방어/힐을 사용하면 자동으로 발동됩니다."""
        if actor.leech_buff_expires_round is None or self.round_no > actor.leech_buff_expires_round:
            return
        luck = int(actor.stats.get("행운", 0))
        if luck <= 0:
            pct = config.SKILL_REFLUX_BUFF_PCT_LOW
            roll_desc = "행운 0 - 고정"
        else:
            sides = luck * config.SKILL_REFLUX_BUFF_DICE_PER_LUCK
            roll = random.randint(1, sides)
            if roll <= luck:
                pct = config.SKILL_REFLUX_BUFF_PCT_LOW
            elif roll <= luck * 2:
                pct = config.SKILL_REFLUX_BUFF_PCT_MID
            else:
                pct = config.SKILL_REFLUX_BUFF_PCT_HIGH
            roll_desc = f"1d{sides} 굴림 {roll}"
        heal_amount = round(actor.max_hp * pct / 100)
        hp_before = actor.current_hp
        actor.heal(heal_amount)
        self._log_operator_only(
            f"🩸 환류 흡수 판정 : {actor.name} 행운{luck} → {roll_desc} → {pct}% 회복",
            tag="formula",
        )
        self._log(f"🩸 {actor.name} 환류 흡수 회복 {heal_amount} ({hp_before}→{actor.current_hp})", tag="heal")

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
            result = AttackSkill.resolve(
                entry["atk"], actor,
                overrides=self.formula_overrides, auto_defense=self._auto_defense_for(actor),
                defense_stat_mult=entry.get("defense_stat_mult", 1.0),
            )
            self._log_attack_resolution(actor, result)

    # ------------------------------------------------------------------
    # 행동 : 방어 정산 (점령전 거점 전용) - 보류된 공격만 정산하고, 이어서 공격/힐을 할 수 있습니다.
    # ------------------------------------------------------------------
    def perform_defense_settle(self, name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.defense_settle_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)
        if not actor.pending_attacks:
            raise BattleError("정산할 보류 공격이 없습니다.")

        self._push_history()
        self._log(f"{actor.name} 방어 정산", tag="action")
        self._resolve_pending_attacks(actor)
        # 실제 '행동'으로 소모되지 않으므로 has_acted는 그대로 둡니다 (이어서 공격/힐 가능).
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 이동 (마스 레이드 격자 전용) - 라운드당 한 번만, has_acted를 소모하지 않습니다.
    # 행동(공격/힐 등) 전후 순서는 자유입니다 - 아군은 보통 이동 후 행동하고, 적군은 행동 후
    # 이동하는 편이지만 서버는 어느 쪽이든 허용하고 "이동은 한 번만"만 강제합니다.
    # ------------------------------------------------------------------
    def perform_move(self, name: str, x: int, y: int):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        if not actor.is_alive:
            raise BattleError("지금은 이동할 수 없는 상태입니다.")
        if not actor.can_move or actor.grid_pos is None:
            raise BattleError("이 전투는 격자 이동을 지원하지 않습니다.")
        if actor.moved_this_round:
            raise BattleError("이번 라운드에 이미 이동했습니다.")
        if self.grid_width is None or not (0 <= x < self.grid_width) or not (0 <= y < self.grid_height):
            raise BattleError("격자 범위를 벗어났습니다.")

        cur_x, cur_y = actor.grid_pos
        if (x, y) == (cur_x, cur_y):
            raise BattleError("이미 그 칸에 있습니다.")

        move_range = config.calculate_move_range(actor.stats, overrides=self.formula_overrides)
        agi = int(actor.stats.get("민첩", 0))
        if not config.is_within_move_shape(x - cur_x, y - cur_y, move_range, agi):
            shape_desc = f"십자 {move_range}칸" + (" + 주변 8칸" if agi > 0 else " (민첩 0 - 대각선 불가)")
            raise BattleError(f"이동 가능 범위({shape_desc})를 벗어났습니다.")

        occupied = any(
            c is not actor and c.is_alive and c.grid_pos == (x, y)
            for c in self.team_a + self.team_b
        )
        if occupied:
            raise BattleError("이미 다른 캐릭터가 있는 칸입니다.")

        self._push_history()
        actor.grid_pos = (x, y)
        actor.moved_this_round = True
        self._log(f"{actor.name} 이동 {cell_label(cur_x, cur_y)} → {cell_label(x, y)}", tag="action")

    # ------------------------------------------------------------------
    # 행동 : 배치 (메딕 전용) - 지정 아군 1인과 본인의 위치(칸)를 교환합니다. 정식 행동이므로
    # has_acted를 소모합니다 (이동과 달리 라운드당 1회 행동에 포함됩니다).
    # ------------------------------------------------------------------
    def perform_swap(self, name: str, target_name: str):
        actor = self.find_character(name)
        target = self.find_character(target_name)
        if actor is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.swap_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)
        if actor.grid_pos is None or target.grid_pos is None:
            raise BattleError("이 전투는 격자 이동을 지원하지 않습니다.")
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")
        if target.team != actor.team:
            raise BattleError("배치 대상은 같은 팀의 캐릭터여야 합니다.")
        if target is actor:
            raise BattleError("본인과는 위치를 교환할 수 없습니다.")

        self._push_history()
        self._resolve_pending_attacks(actor)
        actor_pos, target_pos = actor.grid_pos, target.grid_pos
        self.swap_skill.execute(actor, target)
        actor.has_acted = True

        self._log(
            f"{actor.name} 배치 : {target.name}과(와) 위치 교환 "
            f"({cell_label(*actor_pos)} ↔ {cell_label(*target_pos)})",
            tag="action",
        )
        self._check_finish()

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
        if target.team == attacker.team:
            raise BattleError("아군은 공격할 수 없습니다.")

        attacker_team_label = self.team_label_of(attacker)
        forced = self._forced_for(attacker_team_label)
        if forced is not None and target is not forced["target"]:
            raise BattleError(
                "현재 공격유도/지휘 효과가 적용 중입니다.\n"
                f"이번 공격은 반드시 {forced['target'].name}을(를) 대상으로 해야 합니다. "
                f"(남은 강제 횟수 {forced['count']}회)"
            )

        if not self.site_auto_defense:
            focus_count = self._attacks_on_target_this_round.get(target.name, 0)
            if focus_count >= 2:
                raise BattleError(
                    f"{target.name}은(는) 이번 라운드에 이미 2명에게 공격받았습니다. "
                    "한 대상은 라운드당 최대 2명까지만 공격할 수 있습니다."
                )
            self._attacks_on_target_this_round[target.name] = focus_count + 1

        self._push_history()

        # 공격자 자신에게 걸려있던 보류 피해를 먼저 정산합니다.
        self._resolve_pending_attacks(attacker)

        atk = self.attack_skill.roll(attacker, overrides=self.formula_overrides)
        attacker.has_acted = True

        self._log(f"{attacker.name} 공격 → {target.name}", tag="action")
        # 요청 1 : 공격 수치는 정산(HP 반영) 여부와 무관하게 즉시 알 수 있어야 합니다.
        # 크리티컬 안내는 수치보다 먼저 보이도록 하고, 크리티컬이 뜬 수치는 공격자 직군 색으로 강조합니다.
        if atk["is_crit"]:
            self._log_public_only("크리티컬!", tag="crit")
            self._log(f"공격 수치 {atk['total']}", tag="damage", role=attacker.role)
        else:
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
        elif not atk["position_match"]:
            self._log_operator_only(
                f"({attacker.name}은(는) 딜러가 아니므로 크리티컬이 발생하지 않습니다)", tag="formula",
            )

        # 편광(가디언 스킬)이 활성화된 아군이 있으면 실제 피해는 그쪽으로 집중됩니다.
        resolved_target = self._redirect_for_polarize(target)
        def_mult = resolved_target.polarize_ally_count if resolved_target.polarize_active else 1.0

        if resolved_target.has_acted:
            # 대상이 이미 이번 라운드 행동을 마쳤다면 더 기다릴 필요가 없으므로 즉시 정산합니다.
            result = AttackSkill.resolve(
                atk, resolved_target,
                overrides=self.formula_overrides, auto_defense=self._auto_defense_for(resolved_target),
                defense_stat_mult=def_mult,
            )
            self._log_attack_resolution(resolved_target, result)
        else:
            # 대상이 아직 이번 라운드 행동 전이라면 피해를 보류하고, 대상의 턴에 정산합니다.
            resolved_target.pending_attacks.append({
                "attacker_name": attacker.name, "atk": atk, "defense_stat_mult": def_mult,
            })

        self._maybe_trigger_leech(attacker)

        if forced is not None:
            self._consume_forced_target(
                attacker_team_label, "공격 대상 변경 (공격유도/지휘 효과, 남은 강제 횟수 {count}회)",
            )

        self._check_finish()
        return atk

    # ------------------------------------------------------------------
    # 스킬 : 붕괴 (스트라이커 전용) - 단일 적에게 다이스 ×3 배율로 2회 공격, 최소 1회 크리티컬 보장.
    # ------------------------------------------------------------------
    def perform_collapse(self, attacker_name: str, target_name: str):
        attacker = self.find_character(attacker_name)
        target = self.find_character(target_name)
        if attacker is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(attacker)

        ok, reason = self.collapse_skill.can_use(attacker)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")
        if target.team == attacker.team:
            raise BattleError("아군은 공격할 수 없습니다.")

        attacker_team_label = self.team_label_of(attacker)
        forced = self._forced_for(attacker_team_label)
        if forced is not None and target is not forced["target"]:
            raise BattleError(
                "현재 공격유도/지휘 효과가 적용 중입니다.\n"
                f"이번 공격은 반드시 {forced['target'].name}을(를) 대상으로 해야 합니다. "
                f"(남은 강제 횟수 {forced['count']}회)"
            )

        self._push_history()
        self._resolve_pending_attacks(attacker)

        base_count = config.get_value("ATTACK_DICE_COUNT", self.formula_overrides)
        merged = dict(self.formula_overrides or {})
        merged["ATTACK_DICE_COUNT"] = base_count * config.SKILL_COLLAPSE_DICE_MULT
        hits = [self.attack_skill.roll(attacker, overrides=merged) for _ in range(2)]
        forced_crit_applied = False
        if not any(h["is_crit"] for h in hits):
            hits[1]["is_crit"] = True
            hits[1]["total"] = round(hits[1]["subtotal"] * hits[1]["crit_mult"])
            forced_crit_applied = True
        attacker.has_acted = True

        self._log(
            f"{attacker.name} 【붕괴】 → {target.name} (다이스 ×{config.SKILL_COLLAPSE_DICE_MULT}, 2회 공격)",
            tag="action",
        )

        resolved_target = self._redirect_for_polarize(target)
        def_mult = resolved_target.polarize_ally_count if resolved_target.polarize_active else 1.0

        for i, atk in enumerate(hits, 1):
            note = " (강제 크리티컬 적용)" if forced_crit_applied and i == 2 else ""
            if atk["is_crit"]:
                self._log_public_only("크리티컬!", tag="crit")
                self._log(f"[붕괴 {i}/2] 공격 수치 {atk['total']}{note}", tag="damage", role=attacker.role)
            else:
                self._log(f"[붕괴 {i}/2] 공격 수치 {atk['total']}{note}", tag="damage")
            if resolved_target.has_acted:
                result = AttackSkill.resolve(
                    atk, resolved_target, overrides=self.formula_overrides,
                    auto_defense=self._auto_defense_for(resolved_target), defense_stat_mult=def_mult,
                )
                self._log_attack_resolution(resolved_target, result)
            else:
                resolved_target.pending_attacks.append({
                    "attacker_name": attacker.name, "atk": atk, "defense_stat_mult": def_mult,
                })

        self._maybe_trigger_leech(attacker)

        if forced is not None:
            self._consume_forced_target(
                attacker_team_label, "공격 대상 변경 (공격유도/지휘 효과, 남은 강제 횟수 {count}회)",
            )

        self._check_finish()

    # ------------------------------------------------------------------
    # 스킬 : 방출 (스트라이커 전용) - 다이스 ×2 배율로 생존한 모든 적에게 개별로 2회씩 공격.
    # ------------------------------------------------------------------
    def perform_emission(self, attacker_name: str):
        attacker = self.find_character(attacker_name)
        if attacker is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(attacker)

        ok, reason = self.emission_skill.can_use(attacker)
        if not ok:
            raise BattleError(reason)

        enemy_label = self.enemy_team_label(self.team_label_of(attacker))
        enemies = [c for c in self.team_members(enemy_label) if c.is_alive]
        if not enemies:
            raise BattleError("공격할 적이 없습니다.")

        attacker_team_label = self.team_label_of(attacker)
        # 방출은 광역 공격이라 강제 대상도 어차피 맞으므로, 대상 지정 자체는 막지 않습니다.
        forced = self._forced_for(attacker_team_label)

        self._push_history()
        self._resolve_pending_attacks(attacker)

        base_count = config.get_value("ATTACK_DICE_COUNT", self.formula_overrides)
        merged = dict(self.formula_overrides or {})
        merged["ATTACK_DICE_COUNT"] = base_count * config.SKILL_EMISSION_DICE_MULT
        attacker.has_acted = True

        self._log(
            f"{attacker.name} 【방출】 → 적 전원({len(enemies)}명) "
            f"(다이스 ×{config.SKILL_EMISSION_DICE_MULT}, 각 2회 공격)",
            tag="action",
        )

        for enemy in enemies:
            resolved_target = self._redirect_for_polarize(enemy)
            def_mult = resolved_target.polarize_ally_count if resolved_target.polarize_active else 1.0
            for i in range(1, 3):
                atk = self.attack_skill.roll(attacker, overrides=merged)
                if atk["is_crit"]:
                    self._log_public_only("크리티컬!", tag="crit")
                    self._log(f"[방출 → {enemy.name} {i}/2] 공격 수치 {atk['total']}", tag="damage", role=attacker.role)
                else:
                    self._log(f"[방출 → {enemy.name} {i}/2] 공격 수치 {atk['total']}", tag="damage")
                if resolved_target.has_acted:
                    result = AttackSkill.resolve(
                        atk, resolved_target, overrides=self.formula_overrides,
                        auto_defense=self._auto_defense_for(resolved_target), defense_stat_mult=def_mult,
                    )
                    self._log_attack_resolution(resolved_target, result)
                else:
                    resolved_target.pending_attacks.append({
                        "attacker_name": attacker.name, "atk": atk, "defense_stat_mult": def_mult,
                    })

        self._maybe_trigger_leech(attacker)

        if forced is not None:
            self._consume_forced_target(
                attacker_team_label,
                "강제 대상도 방출 범위에 포함됨 (공격유도/지휘 효과, 남은 강제 횟수 {count}회)",
            )

        self._check_finish()

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
        self._maybe_trigger_leech(tanker)
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
        count = self._register_forced_target(tanker, target, enemy_label)

        if target is tanker:
            self._log(f"{tanker.name} 공격유도 (본인) - 능동 방어도 함께 부여됩니다", tag="taunt")
        else:
            self._log(f"{tanker.name} 공격유도 → {target.name}", tag="taunt")
        self._log(
            f"→ {enemy_label}의 다음 공격 {count}회가 {target.name}을(를) 대상으로 강제됩니다.",
            tag="system",
        )
        self._check_finish()

    # ------------------------------------------------------------------
    # 행동 : 지휘 (가디언 전용) - 공격유도와 동일한 어그로 강제이지만, 방어 부여 효과는 없습니다.
    # ------------------------------------------------------------------
    def perform_command(self, guardian_name: str, target_name: str):
        guardian = self.find_character(guardian_name)
        target = self.find_character(target_name)
        if guardian is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(guardian)

        ok, reason = self.command_skill.can_use(guardian)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")
        if target.team != guardian.team:
            raise BattleError("지휘 대상은 같은 팀의 캐릭터여야 합니다.")

        self._push_history()
        self.command_skill.execute(guardian, target)
        self._resolve_pending_attacks(guardian)
        guardian.has_acted = True

        enemy_label = self.enemy_team_label(self.team_label_of(guardian))
        count = self._register_forced_target(guardian, target, enemy_label)

        if target is guardian:
            self._log(f"{guardian.name} 지휘 (본인) - 능동 방어도 함께 부여됩니다", tag="taunt")
        else:
            self._log(f"{guardian.name} 지휘 → {target.name} (능동 방어도 함께 부여됩니다)", tag="taunt")
        self._log(
            f"→ {enemy_label}의 다음 공격 {count}회가 {target.name}을(를) 대상으로 강제됩니다.",
            tag="system",
        )
        self._check_finish()

    # ------------------------------------------------------------------
    # 스킬 : 차폐 (가디언 전용) - 지정 아군(본인 포함) 1인에게 임시 보호막 + 능동 방어를 부여합니다.
    # ------------------------------------------------------------------
    def perform_shield(self, name: str, target_name: str):
        actor = self.find_character(name)
        target = self.find_character(target_name)
        if actor is None or target is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.shield_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)
        if not target.is_alive:
            raise BattleError("대상이 존재하지 않습니다.")
        if target.team != actor.team:
            raise BattleError("차폐 대상은 같은 팀의 캐릭터여야 합니다.")

        self._push_history()
        self._resolve_pending_attacks(actor)
        result = self.shield_skill.execute(actor, target)
        target.shield_temp_expires_round = self.round_no + config.SKILL_SHIELD_GRANT_DURATION
        actor.has_acted = True

        if target is actor:
            self._log(f"{actor.name} 【차폐】(본인) : 보호막 +{result['amount']}, 능동 방어 부여", tag="defend")
        else:
            self._log(f"{actor.name} 【차폐】 → {target.name} : 보호막 +{result['amount']}, 능동 방어 부여", tag="defend")
        self._maybe_trigger_leech(actor)
        self._check_finish()

    # ------------------------------------------------------------------
    # 스킬 : 편광 (가디언 전용) - 활성화 시 일정 기간 같은 팀에 대한 모든 공격이 본인에게 집중됩니다.
    # ------------------------------------------------------------------
    def perform_polarize(self, name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor)

        ok, reason = self.polarize_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        self._push_history()
        self._resolve_pending_attacks(actor)
        self.polarize_skill.execute(actor)

        allies = [c for c in self.team_members(self.team_label_of(actor)) if c.is_alive]
        actor.polarize_active = True
        actor.polarize_expires_round = self.round_no + config.SKILL_POLARIZE_DURATION
        actor.polarize_ally_count = max(1, len(allies))
        actor.has_acted = True

        self._log(
            f"{actor.name} 【편광】 : {config.SKILL_POLARIZE_DURATION}턴간 아군 전원의 피해를 집중시킵니다 "
            f"(방어력 ×{actor.polarize_ally_count}, 이 효과로는 죽지 않습니다).",
            tag="defend",
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
        if target.team != healer.team:
            raise BattleError("적군은 회복시킬 수 없습니다.")

        self._push_history()
        self._resolve_pending_attacks(healer)

        target_was_downed = target.status == Character.STATUS_DOWNED
        result = self.heal_skill.execute(healer, target, overrides=self.formula_overrides)
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

        if heal["is_crit"]:
            self._log(f"회복 {heal['total']}", tag="heal", role=healer.role)
        else:
            self._log(f"회복 {heal['total']}", tag="heal")
        self._log(f"{target.name} HP {result['hp_before']} → {result['hp_after']}", tag="hp")

        if target_was_downed and target.status == Character.STATUS_ALIVE:
            self._log(f"{target.name} 위기를 넘기고 전투에 복귀했습니다!", tag="system")

        self._maybe_trigger_leech(healer)
        self._check_finish()

    # ------------------------------------------------------------------
    # 스킬 : 환류 (메딕 전용) - 본인 회복 + 메딕 직군 아군 전원 회복 + 지정 아군 3인에게 흡수 버프.
    # ------------------------------------------------------------------
    def perform_reflux(self, name: str, target_names: list):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor, allow_free_turn=True)

        ok, reason = self.reflux_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        targets = []
        seen = set()
        for tn in target_names or []:
            t = self.find_character(tn)
            if t is None or not t.is_alive:
                raise BattleError("대상이 존재하지 않습니다.")
            if t.team != actor.team:
                raise BattleError("환류 대상은 같은 팀의 캐릭터여야 합니다.")
            if t.name in seen:
                raise BattleError("같은 대상을 중복 지정할 수 없습니다.")
            seen.add(t.name)
            targets.append(t)
        if len(targets) != config.SKILL_REFLUX_BUFF_TARGET_COUNT:
            raise BattleError(f"환류는 아군 정확히 {config.SKILL_REFLUX_BUFF_TARGET_COUNT}명을 지정해야 합니다.")

        self._push_history()
        self._resolve_pending_attacks(actor)

        # 1) 본인 회복
        self_heal = round(actor.max_hp * config.SKILL_REFLUX_SELF_HEAL_PCT / 100)
        hp_before = actor.current_hp
        actor.heal(self_heal)
        self._log(
            f"{actor.name} 【환류】 본인 회복 {self_heal} ({hp_before}→{actor.current_hp})", tag="heal",
        )

        # 2) 메딕 직군 아군 전원에게 1다이스 광역 회복
        medics = [
            c for c in self.team_members(self.team_label_of(actor))
            if c.is_alive and c.role == config.ROLE_HEALER
        ]
        merged = dict(self.formula_overrides or {})
        merged["HEAL_DICE_COUNT"] = 1
        for medic in medics:
            heal = config.roll_heal(actor.stats, role=actor.role, overrides=merged)
            hp_before = medic.current_hp
            medic.heal(heal["total"])
            self._log(
                f"[환류 - 메딕 회복] {medic.name} +{heal['total']} ({hp_before}→{medic.current_hp})", tag="heal",
            )

        # 3) 지정 아군 3인에게 3턴 흡수 버프 부여
        for t in targets:
            t.leech_buff_expires_round = self.round_no + config.SKILL_REFLUX_BUFF_DURATION
        self._log(
            f"{actor.name} 【환류】 흡수 버프 부여 → {', '.join(t.name for t in targets)} "
            f"({config.SKILL_REFLUX_BUFF_DURATION}턴)",
            tag="defend",
        )

        actor.has_acted = True
        self._maybe_trigger_leech(actor)
        self._check_finish()

    # ------------------------------------------------------------------
    # 스킬 : 복원 (메딕 전용) - 모든 아군에게 회복 판정, 지정 아군 1인은 추가 회복 보너스.
    # ------------------------------------------------------------------
    def perform_restore(self, name: str, target_name: str):
        actor = self.find_character(name)
        if actor is None:
            raise BattleError("대상이 존재하지 않습니다.")
        self._check_actor_turn(actor, allow_free_turn=True)

        ok, reason = self.restore_skill.can_use(actor)
        if not ok:
            raise BattleError(reason)

        bonus_target = None
        if target_name:
            bonus_target = self.find_character(target_name)
            if bonus_target is None or not bonus_target.is_alive:
                raise BattleError("대상이 존재하지 않습니다.")
            if bonus_target.team != actor.team:
                raise BattleError("복원 보너스 대상은 같은 팀의 캐릭터여야 합니다.")

        self._push_history()
        self._resolve_pending_attacks(actor)

        allies = [c for c in self.team_members(self.team_label_of(actor)) if c.is_alive]
        merged = dict(self.formula_overrides or {})
        merged["HEAL_DICE_COUNT"] = 1
        self._log(f"{actor.name} 【복원】 → 아군 전원({len(allies)}명) 회복", tag="heal")
        for ally in allies:
            heal = config.roll_heal(actor.stats, role=actor.role, overrides=merged)
            total = heal["total"]
            if bonus_target is not None and ally is bonus_target:
                total = round(total * (1 + config.SKILL_RESTORE_BONUS_PCT / 100))
            hp_before = ally.current_hp
            ally.heal(total)
            bonus_note = f" (+{config.SKILL_RESTORE_BONUS_PCT}% 보너스)" if ally is bonus_target else ""
            self._log(f"[복원] {ally.name} +{total}{bonus_note} ({hp_before}→{ally.current_hp})", tag="heal")

        actor.has_acted = True
        self._maybe_trigger_leech(actor)
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

    def perform_timeout_unacted_runners(self):
        """
        1팀(러너)이면서 아직 행동하지 않아 턴 진행을 막고 있는 캐릭터를 일괄로 시간 초과 처리합니다.
        (운영진이 응답 없는 러너를 한 번에 넘기기 위한 기능)
        """
        names = [name for name in self.unacted_members() if name in {c.name for c in self.team_a}]
        for name in names:
            self.perform_timeout(name)

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
        공격유도/지휘 대상팀의 턴이 끝나는데, 그 팀이 이번 턴에 단 한 번도 공격을 사용하지 않았다면
        그 팀에 걸려있던 강제 지목만 해제됩니다 (다른 팀에 걸린 강제 지목은 독립적이라 영향 없음).
        """
        forced = self.forced_targets.get(self.current_turn_team)
        if forced is not None and not self._forced_turn_had_attack:
            self._log(
                f"⚠ 공격유도/지휘 효과가 해제되었습니다 ({self.current_turn_team}이(가) 이번 턴에 "
                f"공격을 사용하지 않았습니다).",
                tag="system",
            )
            del self.forced_targets[self.current_turn_team]
        self._forced_turn_had_attack = False

    def _log_aggro_reminder_if_needed(self, team_about_to_act: str):
        """
        공격유도/지휘 효과가 아직 남아있고, 지금 턴을 받는 팀이 그 강제 대상을 공격해야 하는 팀이라면
        라운드/턴 개시 문구보다 먼저 안내합니다. (라운드 경계를 넘어서도 유지됩니다)
        """
        forced = self._forced_for(team_about_to_act)
        if forced is not None:
            self._forced_turn_had_attack = False  # 이번 턴에는 아직 공격을 사용하지 않았습니다.
            self._log(
                f"⚠ 공격유도/지휘 효과가 남아있습니다 : {team_about_to_act}의 다음 공격 "
                f"{forced['count']}회는 반드시 {forced['target'].name}을(를) 대상으로 해야 합니다.",
                tag="system",
            )

    def _start_new_round(self):
        self.round_no += 1
        self.round_first_team = self.enemy_team_label(self.round_first_team)
        self.current_turn_team = self.round_first_team
        self._attacks_on_target_this_round = {}

        for c in self.team_a + self.team_b:
            c.reset_for_new_round()

        # 요청 16 : 공격유도/지휘로 부여된 능동 방어는 그 어그로가 아직 소모되지 않은 만큼
        # 라운드 경계를 넘어서도 함께 유지되어야 합니다. reset_for_new_round()가 방어 계층을
        # 비우므로, 남아있는 강제 횟수만큼 다시 채워 넣습니다. (양 팀에 걸린 강제 지목 모두 해당)
        for forced in self.forced_targets.values():
            if forced["count"] > 0:
                forced["target"].defended_this_round = True
                forced["target"].defense_grants = [forced["grantor"]] * forced["count"]

        # 차폐(가디언) 임시 보호막 만료 처리 (전투 시작 시 붙는 영구 보호막은 만료되지 않습니다)
        for c in self.team_a + self.team_b:
            if c.shield_temp_expires_round is not None and self.round_no > c.shield_temp_expires_round:
                c.shield_temp = 0
                c.shield_temp_expires_round = None

        # 편광(가디언) : 못 막은 피해(오버플로)는 적의 행동과 무관하게 이번 라운드 시작 시
        # 무조건 생존 아군 전체에게 1/n씩 나눠서 가산됩니다.
        for c in self.team_a + self.team_b:
            if c.polarize_overflow > 0:
                survivors = [m for m in self.team_members(self.team_label_of(c)) if m.is_alive]
                n = c.polarize_ally_count or max(1, len(survivors))
                share = round(c.polarize_overflow / n) if n else 0
                if share > 0 and survivors:
                    self._log(
                        f"⚡ 편광 : {c.name}이(가) 못 막은 피해 {c.polarize_overflow}가 "
                        f"생존 아군 {len(survivors)}명에게 각 {share}씩 가산됩니다.",
                        tag="system",
                    )
                    for m in survivors:
                        m.take_damage(share)
                c.polarize_overflow = 0
            if c.polarize_active and c.polarize_expires_round is not None and self.round_no > c.polarize_expires_round:
                c.polarize_active = False
                c.polarize_expires_round = None
                c.polarize_ally_count = 0
                self._log(f"🛡 {c.name}의 편광 효과가 종료되었습니다.", tag="system")

        # 환류(메딕) 흡수 버프 만료 정리
        for c in self.team_a + self.team_b:
            if c.leech_buff_expires_round is not None and self.round_no > c.leech_buff_expires_round:
                c.leech_buff_expires_round = None

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
    def build_character(self, name: str, formula_overrides: dict = None) -> Character:
        """데이터베이스에서 이름으로 캐릭터를 찾아 전투용 Character 인스턴스를 생성합니다."""
        data = self.db.get(name)
        if data is None:
            raise BattleError("존재하지 않는 캐릭터입니다.")
        return Character(
            name, data["role"], data["stats"], data.get("color"),
            formula_overrides=formula_overrides, skill=data.get("skill"),
        )

    def build_team(self, names: list, formula_overrides: dict = None) -> list:
        """이름 리스트(3개)로 팀(Character 리스트)을 생성합니다."""
        team = []
        for name in names:
            name = (name or "").strip()
            if not name:
                raise BattleError("캐릭터 이름을 모두 입력해주세요.")
            team.append(self.build_character(name, formula_overrides=formula_overrides))
        return team

    def start_battle(self, team_a_names: list, team_b_names: list, forced_first_team: str = None,
                      formula_overrides: dict = None, site_auto_defense: bool = False,
                      grid_width: int = None, grid_height: int = None) -> Battle:
        """
        선공 팀은 기본적으로 민첩 합산을 기준으로 Battle이 자동으로 결정합니다.
        forced_first_team을 지정하면(예: 점령전의 "거점은 항상 후공" 규칙) 그 팀이 무조건 선공이 됩니다.
        formula_overrides는 이 전투에 적용할 전투 유형별 수식(없으면 전역 기본값을 그대로 씁니다).
        site_auto_defense=True면 2팀은 공격을 받을 때마다 항상 자동으로 능동 방어합니다(점령전 거점 규칙).
        grid_width/grid_height를 지정하면 마스 레이드용 격자 전투가 됩니다.
        """
        team_a = self.build_team(team_a_names, formula_overrides=formula_overrides)
        team_b = self.build_team(team_b_names, formula_overrides=formula_overrides)
        self.battle = Battle(
            team_a, team_b, forced_first_team=forced_first_team,
            formula_overrides=formula_overrides, site_auto_defense=site_auto_defense,
            grid_width=grid_width, grid_height=grid_height,
        )
        return self.battle
