# -*- coding: utf-8 -*-
"""
dorm.py
=======
기숙사(마이룸) : 운영진이 "관"을 만들고 한 관에 6명까지 캐릭터를 배치합니다.
각 캐릭터는 자기 방을 도트 가구로 꾸밀 수 있고, 다른 사람 방은 구경만 할 수 있습니다.

- 가구·바닥·벽 이미지(도트 자료)는 운영진이 올리고, 자료마다 출처(제작자·라이선스·주소)를 붙입니다.
  출처는 기숙사 화면의 "출처" 창에 모두 표시됩니다.
- 모든 방에서 같은 기숙사를 씁니다(캐릭터 DB가 공용이라서). dorms.json에 저장됩니다.
"""

import json
import os
import threading
import time
import uuid

DORMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dorms.json")
HALL_SIZE = 6
ROOM_W, ROOM_H = 12, 9      # 방 크기(칸). 위 2줄은 벽입니다.
WALL_ROWS = 2
TILE = 16                   # 도트 한 칸 = 16px
MAX_ITEMS = 120
CATEGORIES = ("furniture", "deco", "wall", "floor", "wallpaper")


class DormError(Exception):
    pass


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


class Dorms:
    def __init__(self, path=DORMS_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.halls, self.assets, self.credits, self.rooms = [], [], [], {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        self.halls = d.get("halls", [])
        self.assets = d.get("assets", [])
        self.credits = d.get("credits", [])
        self.rooms = d.get("rooms", {})

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"halls": self.halls, "assets": self.assets, "credits": self.credits, "rooms": self.rooms},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- 조회 ----
    def hall_of(self, name):
        for h in self.halls:
            if name in h.get("slots", []):
                return h
        return None

    def payload(self):
        return {"halls": self.halls, "assets": self.assets, "credits": self.credits,
                "room_w": ROOM_W, "room_h": ROOM_H, "wall_rows": WALL_ROWS, "tile": TILE, "hall_size": HALL_SIZE}

    def room(self, name):
        r = self.rooms.get(name) or {}
        return {"owner": name, "floor": r.get("floor"), "wallpaper": r.get("wallpaper"),
                "items": r.get("items", []), "updated": r.get("updated")}

    # ---- 운영진 : 관 배치 ----
    def set_halls(self, halls, valid_names):
        clean, used = [], set()
        for h in (halls or [])[:50]:
            name = str(h.get("name") or "").strip()[:30] or "이름 없는 관"
            slots = []
            for s in (h.get("slots") or [])[:HALL_SIZE]:
                s = (s or "").strip()
                if s and s in valid_names and s not in used:
                    used.add(s)
                    slots.append(s)
                else:
                    slots.append(None)
            slots += [None] * (HALL_SIZE - len(slots))
            clean.append({"id": str(h.get("id") or uuid.uuid4().hex[:8])[:16], "name": name, "slots": slots})
        with self.lock:
            self.halls = clean
            self.save()

    # ---- 운영진 : 자료·출처 ----
    def add_asset(self, name, category, url, w, h, credit_id):
        if category not in CATEGORIES:
            raise DormError("종류가 올바르지 않습니다.")
        asset = {"id": uuid.uuid4().hex[:10], "name": (name or "").strip()[:30] or "이름 없음", "category": category,
                 "url": url, "w": _clamp(w, 1, ROOM_W, 1), "h": _clamp(h, 1, ROOM_H, 1),
                 "credit": credit_id if any(c["id"] == credit_id for c in self.credits) else None}
        with self.lock:
            self.assets.append(asset)
            self.save()
        return asset

    def update_asset(self, asset_id, **fields):
        with self.lock:
            for a in self.assets:
                if a["id"] == asset_id:
                    if "name" in fields:
                        a["name"] = (fields["name"] or "").strip()[:30] or a["name"]
                    if fields.get("category") in CATEGORIES:
                        a["category"] = fields["category"]
                    if "w" in fields:
                        a["w"] = _clamp(fields["w"], 1, ROOM_W, a["w"])
                    if "h" in fields:
                        a["h"] = _clamp(fields["h"], 1, ROOM_H, a["h"])
                    if "credit" in fields:
                        a["credit"] = fields["credit"] if any(c["id"] == fields["credit"] for c in self.credits) else None
                    self.save()
                    return a
        raise DormError("자료를 찾을 수 없습니다.")

    def delete_asset(self, asset_id):
        with self.lock:
            self.assets = [a for a in self.assets if a["id"] != asset_id]
            for r in self.rooms.values():
                r["items"] = [i for i in r.get("items", []) if i.get("a") != asset_id]
                if r.get("floor") == asset_id:
                    r["floor"] = None
                if r.get("wallpaper") == asset_id:
                    r["wallpaper"] = None
            self.save()

    def set_credits(self, credits):
        clean = []
        for c in (credits or [])[:100]:
            title = str(c.get("title") or "").strip()[:80]
            if not title:
                continue
            clean.append({"id": str(c.get("id") or uuid.uuid4().hex[:8])[:16], "title": title,
                          "author": str(c.get("author") or "").strip()[:60],
                          "license": str(c.get("license") or "").strip()[:40],
                          "url": str(c.get("url") or "").strip()[:300]})
        with self.lock:
            self.credits = clean
            ids = {c["id"] for c in clean}
            for a in self.assets:
                if a.get("credit") not in ids:
                    a["credit"] = None
            self.save()

    # ---- 방 꾸미기 ----
    def save_room(self, owner, data):
        by_id = {a["id"]: a for a in self.assets}
        items = []
        for it in (data.get("items") or [])[:MAX_ITEMS]:
            a = by_id.get(it.get("a"))
            if not a or a["category"] in ("floor", "wallpaper"):
                continue
            x = _clamp(it.get("x"), 0, ROOM_W - a["w"], 0)
            y = _clamp(it.get("y"), 0, ROOM_H - a["h"], 0)
            items.append({"a": a["id"], "x": x, "y": y, "f": bool(it.get("f"))})
        floor = data.get("floor") if by_id.get(data.get("floor"), {}).get("category") == "floor" else None
        wallpaper = data.get("wallpaper") if by_id.get(data.get("wallpaper"), {}).get("category") == "wallpaper" else None
        with self.lock:
            self.rooms[owner] = {"floor": floor, "wallpaper": wallpaper, "items": items, "updated": time.time()}
            self.save()
        return self.room(owner)


_DORMS = None


def shared_dorms() -> Dorms:
    global _DORMS
    if _DORMS is None:
        _DORMS = Dorms()
    return _DORMS
