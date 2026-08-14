# -*- coding: utf-8 -*-
"""
database.py
===========
캐릭터 데이터베이스를 관리합니다.

- 운영자가 붙여넣은 텍스트를 자동으로 파싱하여 캐릭터를 등록합니다.
- 등록된 데이터는 characters.json 파일에 자동으로 저장되며,
  프로그램을 다시 실행해도 그대로 불러와집니다.
- 캐릭터 수정 / 삭제 기능을 제공합니다.
- 스탯은 config.STAT_CAPS 범위(체력/이능/정신/민첩/행운 최대 5, 공격/방어 최대 3)로
  자동 보정됩니다.

붙여넣기 형식 예시
-------------------
    메이
    체력 2
    공격 3
    방어 1
    이능 3
    정신 2
    민첩 3
    행운 2
    리온
    체력 3
    공격 1
    방어 3
    이능 1
    정신 3
    민첩 1
    행운 2

* "역할 탱커" / "역할 딜러" / "역할 힐러" 줄을 추가하면 역할도 함께 등록됩니다.
  (역할 줄이 없으면 기본값 config.DEFAULT_ROLE 로 등록되며, 이후 데이터베이스
   화면에서 언제든 수정할 수 있습니다.)
"""

import json
import os
import re

import config

# characters.json은 이 파일(database.py)과 같은 폴더에 생성됩니다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters.json")


class CharacterDatabase:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        # 구조: { 이름: {"role": "탱커", "stats": {"체력":2, ...}} }
        self.characters = {}
        self.load()

    # ------------------------------------------------------------------
    # 파일 입출력 (JSON 자동 저장/불러오기)
    # ------------------------------------------------------------------
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.characters = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.characters = {}
        else:
            self.characters = {}

    def save(self):
        """현재 데이터베이스 상태를 characters.json 에 자동 저장합니다."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.characters, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 붙여넣기 텍스트 파싱
    # ------------------------------------------------------------------
    _STAT_LINE_RE = re.compile(r"^\s*(체력|공격|방어|이능|정신|민첩|행운)\s+(-?\d+)\s*$")
    _ROLE_LINE_RE = re.compile(r"^\s*역할\s*[:：]?\s*(탱커|딜러|힐러|스트라이커|가디언|메딕)\s*$")
    _COLOR_LINE_RE = re.compile(r"^\s*색상\s*[:：]?\s*(#[0-9a-fA-F]{6})\s*$")

    def parse_bulk_text(self, text: str):
        """
        운영자가 붙여넣은 텍스트를 파싱하여 캐릭터 여러 명을 한 번에 등록합니다.
        스탯 줄도, 역할/색상 줄도 아닌 줄은 새로운 캐릭터의 '이름'으로 간주합니다.

        반환값: (등록된 이름 리스트, 오류/경고 메시지 리스트)
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]

        registered = []
        errors = []

        current_name = None
        current_stats = {}
        current_role = None
        current_color = None

        def flush():
            nonlocal current_name, current_stats, current_role, current_color
            if current_name is None:
                return
            if len(current_stats) == 0:
                errors.append(f"'{current_name}'에 대한 스탯 정보를 찾을 수 없습니다.")
            else:
                role = current_role if current_role else config.DEFAULT_ROLE
                raw_stats = {k: current_stats.get(k, 0) for k in config.STAT_KEYS}
                clamped, warns = config.clamp_stats(raw_stats)
                for w in warns:
                    errors.append(f"'{current_name}' - {w}")
                entry = {"role": role, "stats": clamped}
                if current_color:
                    entry["color"] = current_color
                self.characters[current_name] = entry
                registered.append(current_name)
            current_name = None
            current_stats = {}
            current_role = None
            current_color = None

        for line in lines:
            stat_match = self._STAT_LINE_RE.match(line)
            role_match = self._ROLE_LINE_RE.match(line)
            color_match = self._COLOR_LINE_RE.match(line)

            if stat_match:
                if current_name is None:
                    errors.append(f"이름 없이 스탯 줄이 입력되었습니다: '{line}'")
                    continue
                stat_name, value = stat_match.group(1), int(stat_match.group(2))
                current_stats[stat_name] = value
            elif role_match:
                current_role = role_match.group(1)
            elif color_match:
                current_color = color_match.group(1)
            else:
                # 스탯/역할/색상 줄이 아니면 새 캐릭터 이름의 시작으로 간주합니다.
                flush()
                current_name = line

        flush()  # 마지막 캐릭터 저장

        if registered:
            self.save()  # characters.json 에 자동 저장

        return registered, errors

    # ------------------------------------------------------------------
    # CRUD (추가/수정/삭제/조회)
    # ------------------------------------------------------------------
    def add_or_update(self, name: str, role: str, stats: dict, color: str = None):
        """캐릭터를 새로 추가하거나, 이미 있으면 정보를 수정합니다. 스탯은 자동으로 캡 적용됩니다."""
        clamped, warns = config.clamp_stats(stats)
        entry = {"role": role, "stats": clamped}
        if color:
            entry["color"] = color
        self.characters[name] = entry
        self.save()
        return warns

    def delete(self, name: str):
        if name in self.characters:
            del self.characters[name]
            self.save()

    def delete_many(self, names: list):
        """선택된 여러 캐릭터를 한 번에 삭제합니다."""
        removed = []
        for name in names:
            if name in self.characters:
                del self.characters[name]
                removed.append(name)
        if removed:
            self.save()
        return removed

    def delete_all(self):
        """등록된 캐릭터를 전부 삭제합니다."""
        count = len(self.characters)
        self.characters = {}
        self.save()
        return count

    def get(self, name: str):
        return self.characters.get(name)

    def exists(self, name: str) -> bool:
        return name in self.characters

    def all_names(self):
        """이름 가나다순 정렬 (검색/드롭다운용)"""
        return sorted(self.characters.keys())

    def all_names_by_position(self):
        """포지션순(탱커 → 딜러 → 힐러) 정렬, 같은 포지션 내에서는 이름순"""
        def sort_key(name):
            role = self.characters[name].get("role", config.DEFAULT_ROLE)
            role_idx = config.ROLE_ORDER.index(role) if role in config.ROLE_ORDER else len(config.ROLE_ORDER)
            return (role_idx, name)
        return sorted(self.characters.keys(), key=sort_key)

    # ------------------------------------------------------------------
    # 더미 데이터 생성
    # ------------------------------------------------------------------
    def generate_dummy_characters(self, count: int, name_prefix: str = "extra",
                                    roles: list = None, stat_range: tuple = None):
        """
        테스트/연습용 더미 캐릭터를 자동 생성합니다.
        name_prefix + 번호 형태로 이름을 붙이며, 기존 이름과 겹치지 않도록 번호를 이어서 매깁니다.
        roles가 주어지면 그 목록에서 순환 배정하고, 없으면 무작위 배정합니다.
        stat_range가 주어지면 (최소, 최대) 범위 안에서 무작위 배분하고, 없으면 0~각 스탯 최대치 사이에서
        무작위로 자유 배분합니다.
        반환값: 새로 생성된 이름 리스트
        """
        import random as _random

        # 기존 "prefix + 숫자" 이름들과 겹치지 않도록 다음 번호를 찾습니다.
        existing_nums = []
        for existing in self.characters.keys():
            if existing.startswith(name_prefix):
                suffix = existing[len(name_prefix):]
                if suffix.isdigit():
                    existing_nums.append(int(suffix))
        next_num = (max(existing_nums) + 1) if existing_nums else 1

        role_cycle = roles if roles else None
        created = []
        for i in range(count):
            name = f"{name_prefix}{next_num + i}"
            role = role_cycle[i % len(role_cycle)] if role_cycle else _random.choice(config.ROLES)
            stats = {}
            for key in config.STAT_KEYS:
                cap = config.STAT_CAPS.get(key, 5)
                if stat_range:
                    lo, hi = stat_range
                    stats[key] = _random.randint(max(0, lo), min(cap, hi))
                else:
                    stats[key] = _random.randint(0, cap)  # 자유 배분(스탯 각각 독립적으로 무작위)
            self.characters[name] = {"role": role, "stats": stats}
            created.append(name)

        if created:
            self.save()
        return created
