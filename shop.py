# -*- coding: utf-8 -*-
"""
shop.py
=======
상점 : 상품 목록(이름/가격/설명/이미지/효과)과 '운영진 처리 요청' 기록을 관리합니다.
캐릭터별 재화(P)와 보유 아이템은 캐릭터 DB(characters.json)의 "points"/"items" 필드에 저장됩니다.

상품 목록은 모든 방이 함께 쓰며 shop.json에 저장됩니다(서버 컴퓨터별 실데이터라 git에 올리지 않음).
파일이 없으면 기본 상품 7종으로 시작합니다.
"""

import json
import os
import time
import uuid

import config

SHOP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.json")

# 아이템 효과 종류
EFFECT_LABELS = {
    "heal": "체력 회복",        # value만큼 즉시 회복(보류된 공격이 있으면 피해 정산 직후)
    "stat_up": "스탯 증가",     # 사용할 때 고른 스탯 +value (캐릭터 등록 정보에 영구 반영)
    "request": "운영진 처리",   # 사용하면 운영진에게 처리 요청이 올라가고, 운영진이 직접 반영
    "role_change": "포지션 변경",  # 마이페이지 포지션에서 원하는 포지션을 누르면 1개 차감하고 즉시 변경
}
# 사용 가능 시점
TIMING_LABELS = {
    "any": "전투 전·중",
    "prebattle": "전투 전",
    "battle": "전투 중",
}

DEFAULT_ITEMS = [
    {"name": "회복 포션", "price": 100, "effect": "heal", "value": 50, "timing": "battle",
     "desc": "사용 즉시 체력을 회복합니다."},
    {"name": "스탯 강화제", "price": 300, "effect": "stat_up", "value": 1, "timing": "prebattle",
     "desc": "원하는 스탯 하나를 영구히 +1 합니다."},
    {"name": "포지션 변경권", "price": 500, "effect": "role_change", "value": 0, "timing": "prebattle",
     "desc": "포지션(가디언/스트라이커/메딕)을 변경합니다. 마이페이지의 포지션에서 원하는 포지션을 누르세요."},
    {"name": "스킬 변경권", "price": 500, "effect": "request", "value": 0, "timing": "prebattle",
     "desc": "보유 스킬을 변경합니다. 운영진이 처리합니다."},
    {"name": "스테이터스 변경권", "price": 500, "effect": "request", "value": 0, "timing": "prebattle",
     "desc": "스탯 분배를 다시 합니다. 운영진이 처리합니다."},
    {"name": "이동/사거리 조절권", "price": 200, "effect": "request", "value": 0, "timing": "battle",
     "desc": "이번 전투의 이동/사거리를 조절합니다. 운영진이 처리합니다."},
    {"name": "ReRoll권", "price": 150, "effect": "request", "value": 0, "timing": "battle",
     "desc": "다이스를 1회 다시 굴립니다. 운영진이 처리합니다."},
]

MAX_REQUESTS_KEPT = 300


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _clean_item(raw: dict, base: dict = None) -> dict:
    item = dict(base or {})
    if "name" in raw:
        item["name"] = (str(raw.get("name") or "").strip() or "이름 없음")[:30]
    if "price" in raw:
        try:
            item["price"] = max(0, int(raw.get("price") or 0))
        except (TypeError, ValueError):
            pass
    if "desc" in raw:
        item["desc"] = str(raw.get("desc") or "").strip()[:200]
    if "effect" in raw and raw.get("effect") in EFFECT_LABELS:
        item["effect"] = raw["effect"]
    if "value" in raw:
        try:
            item["value"] = int(raw.get("value") or 0)
        except (TypeError, ValueError):
            pass
    if "timing" in raw and raw.get("timing") in TIMING_LABELS:
        item["timing"] = raw["timing"]
    if "icon_url" in raw:
        item["icon_url"] = raw.get("icon_url") or None
    item.setdefault("name", "이름 없음")
    item.setdefault("price", 0)
    item.setdefault("desc", "")
    item.setdefault("effect", "request")
    item.setdefault("value", 0)
    item.setdefault("timing", "any")
    item.setdefault("icon_url", None)
    return item


class Shop:
    def __init__(self, path: str = SHOP_PATH):
        self.path = path
        self.items = []      # [{id, name, price, desc, effect, value, timing, icon_url}, ...] (표시 순서대로)
        self.requests = []   # [{id, time, room_id, character, item_id, item_name, memo, done}, ...]
        self.load()

    def load(self):
        data = None
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = None
        if data is None:
            self.items = [dict(_clean_item(it), id=_new_id()) for it in DEFAULT_ITEMS]
            self.requests = []
            self.save()
            return
        self.items = [dict(_clean_item(it), id=it.get("id") or _new_id()) for it in data.get("items", [])]
        self.requests = data.get("requests", [])
        # 예전 shop.json의 '포지션 변경권'(운영진 처리)을 마이페이지에서 바로 쓰는 방식으로 바꿉니다.
        migrated = False
        for it in self.items:
            if it["name"] == "포지션 변경권" and it["effect"] == "request":
                it["effect"] = "role_change"
                it["desc"] = "포지션(가디언/스트라이커/메딕)을 변경합니다. 마이페이지의 포지션에서 원하는 포지션을 누르세요."
                migrated = True
        if migrated:
            self.save()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": self.items, "requests": self.requests}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------------- 상품 ----------------
    def get(self, item_id: str):
        return next((it for it in self.items if it["id"] == item_id), None)

    def add_item(self, raw: dict = None) -> dict:
        item = dict(_clean_item(raw or {"name": "새 상품", "price": 100}), id=_new_id())
        self.items.append(item)
        self.save()
        return item

    def update_item(self, item_id: str, raw: dict):
        item = self.get(item_id)
        if item is None:
            return None
        item.update(_clean_item(raw, base=item))
        self.save()
        return item

    def delete_item(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [it for it in self.items if it["id"] != item_id]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def move_item(self, item_id: str, delta: int) -> bool:
        idx = next((i for i, it in enumerate(self.items) if it["id"] == item_id), None)
        if idx is None:
            return False
        new_idx = max(0, min(len(self.items) - 1, idx + delta))
        if new_idx == idx:
            return False
        self.items.insert(new_idx, self.items.pop(idx))
        self.save()
        return True

    # ---------------- 운영진 처리 요청 ----------------
    def add_request(self, room_id: str, character: str, item: dict, memo: str) -> dict:
        req = {
            "id": _new_id(),
            "time": time.strftime("%m-%d %H:%M"),
            "room_id": room_id,
            "character": character,
            "item_id": item["id"],
            "item_name": item["name"],
            "memo": (memo or "").strip()[:200],
            "done": False,
        }
        self.requests.append(req)
        if len(self.requests) > MAX_REQUESTS_KEPT:
            self.requests = self.requests[-MAX_REQUESTS_KEPT:]
        self.save()
        return req

    def set_request_done(self, req_id: str, done: bool = True) -> bool:
        for r in self.requests:
            if r["id"] == req_id:
                r["done"] = bool(done)
                self.save()
                return True
        return False

    def public_payload(self) -> dict:
        return {
            "items": self.items,
            "effect_labels": EFFECT_LABELS,
            "timing_labels": TIMING_LABELS,
            "stat_keys": list(config.STAT_KEYS),
        }


_SHARED_SHOP = None


def shared_shop() -> Shop:
    global _SHARED_SHOP
    if _SHARED_SHOP is None:
        _SHARED_SHOP = Shop()
    return _SHARED_SHOP


# ----------------------------------------------------------------------
# 캐릭터 재화/소지 아이템 (characters.json 항목에 저장)
# ----------------------------------------------------------------------
def get_points(db, name: str) -> int:
    return int((db.get(name) or {}).get("points") or 0)


def set_points(db, name: str, points: int):
    entry = db.get(name)
    if entry is None:
        return
    entry["points"] = max(0, int(points))
    db.save()


def get_items(db, name: str) -> dict:
    return dict((db.get(name) or {}).get("items") or {})


def change_item_count(db, name: str, item_id: str, delta: int) -> int:
    entry = db.get(name)
    if entry is None:
        return 0
    items = dict(entry.get("items") or {})
    count = max(0, int(items.get(item_id, 0)) + int(delta))
    if count:
        items[item_id] = count
    else:
        items.pop(item_id, None)
    entry["items"] = items
    db.save()
    return count
