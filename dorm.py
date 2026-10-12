# -*- coding: utf-8 -*-
"""
dorm.py
=======
기숙사(마이룸) : 운영진이 "관"을 만들고 한 관에 6명까지 캐릭터를 배치합니다.
각 캐릭터는 자기 방(아이소메트릭 방 그림) 위에 도트 소품을 자유롭게 놓아 꾸밀 수 있고,
다른 사람 방은 구경만 할 수 있습니다.

- 기본 자료 : static/dorm_default/manifest.json 에 적힌 방·벽지·가구·소품(운영진이 준 PSD와 도트 묶음에서 뽑음).
- 운영진이 올린 자료 : static/dorm_assets/ 에 저장되고, 자료마다 출처(제작자·라이선스·주소)를 붙입니다.
  출처는 기숙사 화면의 "출처" 창에 모두 표시됩니다.
- 위치는 방 그림의 픽셀 좌표(왼쪽 위 기준)로 저장합니다. 겹침 순서는 아래쪽에 있을수록 앞입니다.
- 모든 방에서 같은 기숙사를 씁니다(캐릭터 DB가 공용이라서). dorms.json에 저장됩니다.
"""

import json
import os
import threading
import time
import uuid

DORMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dorms.json")
HALL_SIZE = 6
MAX_ITEMS = 150
CATEGORIES = ("room", "surface", "furniture", "deco", "wall")

# 기본 자료 : static/dorm_default/manifest.json (받은 도트 묶음에서 뽑은 방·벽지·가구·소품과 출처)
_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dorm_default", "manifest.json")
try:
    with open(_MANIFEST, "r", encoding="utf-8") as _f:
        _m = json.load(_f)
except (OSError, ValueError):
    _m = {"assets": [], "credits": []}
BUILTIN_ASSETS = [dict(a, builtin=True) for a in _m.get("assets", [])]
SEED_CREDITS = _m.get("credits", [])
DEFAULT_BASE = next((a["id"] for a in BUILTIN_ASSETS if a["category"] == "room"), None)
_BUILTIN_BY_ID = {a["id"]: a for a in BUILTIN_ASSETS}


class DormError(Exception):
    pass


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
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
        # 예전(칸 방식) 자료는 새 방식과 맞지 않아 버립니다.
        self.assets = [a for a in d.get("assets", []) if a.get("category") in CATEGORIES and a.get("px")]
        self.credits = d.get("credits", [])
        # 받은 도트 묶음의 출처는 처음 한 번 넣어 두고, 이후로는 운영진이 고치거나 지울 수 있습니다.
        seeded = set(d.get("seeded", []))
        for c in SEED_CREDITS:
            if c["id"] not in seeded:
                if not any(x["id"] == c["id"] for x in self.credits):
                    self.credits.append(dict(c))
                seeded.add(c["id"])
        self.seeded = sorted(seeded)
        self.rooms = {k: v for k, v in (d.get("rooms") or {}).items() if v.get("v") == 2}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"halls": self.halls, "assets": self.assets, "credits": self.credits, "rooms": self.rooms,
                       "seeded": self.seeded},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- 조회 ----
    def all_assets(self):
        return BUILTIN_ASSETS + self.assets

    def all_credits(self):
        return self.credits

    def asset(self, asset_id):
        return _BUILTIN_BY_ID.get(asset_id) or next((a for a in self.assets if a["id"] == asset_id), None)

    def hall_of(self, name):
        for h in self.halls:
            if name in h.get("slots", []):
                return h
        return None

    def payload(self):
        # 관 목록·마이페이지에서 작은 미리보기로 그릴 수 있게, 배정된 방들의 꾸밈 정보도 같이 보냅니다.
        names = [n for h in self.halls for n in h.get("slots", []) if n]
        return {"halls": self.halls, "assets": self.all_assets(), "credits": self.all_credits(),
                "hall_size": HALL_SIZE, "default_base": DEFAULT_BASE, "rooms": {n: self.room(n) for n in names}}

    def room(self, name):
        r = self.rooms.get(name) or {}
        return {"owner": name, "base": r.get("base") or DEFAULT_BASE, "wall": r.get("wall"), "floor": r.get("floor"),
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
    def _credit_ok(self, cid):
        return cid if any(c["id"] == cid for c in self.all_credits()) else None

    def add_asset(self, name, category, url, w, h, credit_id):
        if category not in CATEGORIES:
            raise DormError("종류가 올바르지 않습니다.")
        asset = {"id": uuid.uuid4().hex[:10], "name": (name or "").strip()[:30] or "이름 없음", "category": category,
                 "url": url, "w": _clamp(w, 1, 2000, 16), "h": _clamp(h, 1, 2000, 16), "px": True,
                 "credit": self._credit_ok(credit_id)}
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
                    if "credit" in fields:
                        a["credit"] = self._credit_ok(fields["credit"])
                    self.save()
                    return a
        raise DormError("기본 자료는 바꿀 수 없어요.")

    def delete_asset(self, asset_id):
        with self.lock:
            self.assets = [a for a in self.assets if a["id"] != asset_id]
            for r in self.rooms.values():
                r["items"] = [i for i in r.get("items", []) if i.get("a") != asset_id]
                if r.get("base") == asset_id:
                    r["base"] = None
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
            ids = {c["id"] for c in self.credits}
            for a in self.assets:
                if a.get("credit") not in ids:
                    a["credit"] = None
            self.save()

    # ---- 방 꾸미기 ----
    def save_room(self, owner, data):
        base = self.asset(data.get("base"))
        if not base or base["category"] != "room":
            base = self.asset(DEFAULT_BASE)
        # 방 그림도 기본 배율(s)이 있어 실제 크기 = 그림 크기 × s 입니다. 위치는 이 크기 기준 좌표입니다.
        bw, bh = base["w"] * base.get("s", 1), base["h"] * base.get("s", 1)
        items = []
        for it in (data.get("items") or [])[:MAX_ITEMS]:
            a = self.asset(it.get("a"))
            if not a or a["category"] == "room":
                continue
            try:
                z = max(0.25, min(4.0, round(float(it.get("z") or a.get("s", 1)) * 4) / 4))
            except (TypeError, ValueError):
                z = a.get("s", 1)
            w, h = a["w"] * z, a["h"] * z
            x = _clamp(it.get("x"), -w // 2, bw - w // 2, 0)
            y = _clamp(it.get("y"), -h // 2, bh - h // 2, 0)
            items.append({"a": a["id"], "x": x, "y": y, "f": bool(it.get("f")), "z": z})
        # 벽지·바닥(방에 딱 맞춰 까는 것) : 자리(slot)가 맞는 자료만 받습니다.
        def slot_asset(key, slot):
            a = self.asset(data.get(key))
            return a["id"] if a and a.get("slot") == slot else None
        with self.lock:
            self.rooms[owner] = {"v": 2, "base": base["id"], "wall": slot_asset("wall", "wall"),
                                 "floor": slot_asset("floor", "floor"), "items": items, "updated": time.time()}
            self.save()
        return self.room(owner)


_DORMS = None


def shared_dorms() -> Dorms:
    global _DORMS
    if _DORMS is None:
        _DORMS = Dorms()
    return _DORMS
