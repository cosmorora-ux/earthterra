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
# 마이룸 기간 : 배치가 두 번 바뀌어 기간마다 테마가 다른 마이룸을 하나씩 가집니다.
# 기간마다 관 배치 · 방 꾸밈 · 방명록을 따로 저장하고(자료 · 출처는 공통), 운영진이 지금 기간을 고릅니다.
# 지난 기간의 방은 본인만 마이페이지에서 볼 수 있습니다(구경만).
PERIODS = [
    {"id": "p1", "no": 1, "name": "기숙사", "en": "Dorm", "unit": "관", "unit_en": "Hall"},
    {"id": "p2", "no": 2, "name": "캠프", "en": "Camp", "unit": "막사", "unit_en": "Barrack"},
    {"id": "p3", "no": 3, "name": "선실", "en": "Cabin", "unit": "구역", "unit_en": "Deck"},
]
PERIOD_IDS = [p["id"] for p in PERIODS]
MAX_ITEMS = 150
CATEGORIES = ("room", "surface", "furniture", "deco", "wall", "chara")
# 참가자가 직접 올릴 수 있는 종류(가구 · 캐릭터 SD)와 한 사람당 개수, 캐릭터 대사 제한
USER_CATEGORIES = ("furniture", "chara")
USER_ASSET_MAX = 40
LINES_MAX, LINE_LEN = 20, 80


def _clean_lines(lines):
    if isinstance(lines, str):
        lines = lines.split("\n")
    out = []
    for ln in (lines or [])[:LINES_MAX]:
        ln = " ".join(str(ln or "").split())[:LINE_LEN]
        if ln:
            out.append(ln)
    return out

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
# 좌우만 다른 같은 그림은 하나만 남겼습니다. 지운 자료 id → 남긴 자료(+ 좌우 반전 여부). 예전에 놓아 둔 소품은 이걸로 바꿔 그대로 보입니다.
ASSET_ALIASES = _m.get("aliases", {})


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
        self.assets, self.credits = [], []
        self.periods = {pid: {"halls": [], "rooms": {}, "guestbooks": {}, "default": None} for pid in PERIOD_IDS}
        self.current = PERIOD_IDS[0]
        self.load()

    # 지금 기간의 관 · 방 · 방명록 (예전 코드가 그대로 지금 기간을 다루도록 속성으로 둡니다)
    @property
    def halls(self):
        return self.periods[self.current]["halls"]

    @halls.setter
    def halls(self, v):
        self.periods[self.current]["halls"] = v

    @property
    def rooms(self):
        return self.periods[self.current]["rooms"]

    @rooms.setter
    def rooms(self, v):
        self.periods[self.current]["rooms"] = v

    @property
    def guestbooks(self):
        return self.periods[self.current]["guestbooks"]

    @guestbooks.setter
    def guestbooks(self, v):
        self.periods[self.current]["guestbooks"] = v

    def period_meta(self, pid):
        meta = next((p for p in PERIODS if p["id"] == pid), PERIODS[0])
        cur_no = next(p["no"] for p in PERIODS if p["id"] == self.current)
        status = "current" if meta["no"] == cur_no else ("past" if meta["no"] < cur_no else "future")
        return dict(meta, status=status)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
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
        # 기간별 저장. 예전 파일(기간 없이 halls/rooms/guestbooks만 있던 것)은 1차(기숙사)로 옮깁니다.
        periods = d.get("periods")
        if not isinstance(periods, dict):
            periods = {PERIOD_IDS[0]: {"halls": d.get("halls", []), "rooms": d.get("rooms") or {},
                                       "guestbooks": d.get("guestbooks", {})}}
        for pid in PERIOD_IDS:
            p = periods.get(pid) or {}
            self.periods[pid] = {
                "halls": p.get("halls", []),
                "rooms": {k: v for k, v in (p.get("rooms") or {}).items() if v.get("v") == 2},
                # 방명록 : {방 주인: [{"author", "text", "at"}, ...]} - 한 방에 한 사람당 한 개
                "guestbooks": p.get("guestbooks", {}),
                # 기간의 기본 방(운영진이 꾸밈) : 아직 꾸미지 않은 방은 이 모양으로 보입니다. 없으면 빈 기본 방.
                "default": p.get("default") if isinstance(p.get("default"), dict) else None,
            }
        self.current = d.get("current") if d.get("current") in PERIOD_IDS else PERIOD_IDS[0]
        if self._apply_aliases():
            self.save()

    def _apply_aliases(self):
        """지운(좌우 중복) 기본 자료를 쓰던 방을 남긴 자료 + 좌우 반전으로 바꿉니다. 바뀐 게 있으면 True."""
        changed = False
        for r in (r for p in self.periods.values() for r in p["rooms"].values()):
            for it in r.get("items", []):
                al = ASSET_ALIASES.get(it.get("a"))
                if al:
                    it["a"] = al["to"]
                    if al.get("flip"):
                        it["f"] = not it.get("f")
                    changed = True
            for key in ("base", "wall", "floor"):
                al = ASSET_ALIASES.get(r.get(key))
                if al:
                    r[key] = al["to"]
                    changed = True
        return changed

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"current": self.current, "periods": self.periods, "assets": self.assets, "credits": self.credits,
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
                "hall_size": HALL_SIZE, "default_base": DEFAULT_BASE, "rooms": {n: self.room(n) for n in names},
                "period": self.period_meta(self.current), "periods": [self.period_meta(p) for p in PERIOD_IDS]}

    def room(self, name, period=None):
        pdata = self.periods[period] if period in self.periods else self.periods[self.current]
        r = pdata["rooms"].get(name) or {}
        gb = pdata["guestbooks"]
        # 한 번도 꾸미지 않은 방(저장한 적 없음)은 그 기간의 기본 방 모양으로 보여줍니다.
        lay = r if r.get("updated") else (pdata.get("default") or {})
        return {"owner": name, "base": lay.get("base") or DEFAULT_BASE, "wall": lay.get("wall"), "floor": lay.get("floor"),
                "items": [dict(i) for i in lay.get("items", [])], "updated": r.get("updated"),
                # 마지막으로 바뀐 때(꾸밈 · 음악 · 대사 · 방명록) : 기숙사 목록의 New! 표시에 씁니다.
                "activity": max([r.get("updated") or 0, r.get("touched") or 0]
                                + [e.get("at", 0) for e in gb.get(name, [])]),
                "music": r.get("music"), "line": r.get("line") or "",
                "guestbook": sorted(gb.get(name, []), key=lambda e: -e.get("at", 0))}

    # ---- 기간 ----
    def set_current(self, pid):
        if pid not in PERIOD_IDS:
            raise DormError("알 수 없는 기간이에요.")
        with self.lock:
            self.current = pid
            self.save()

    def set_period_default(self, pid, data):
        """운영진 : 기간의 기본 방 꾸밈. 아직 꾸미지 않은 사람의 방이 이 모양으로 보입니다."""
        if pid not in PERIOD_IDS:
            raise DormError("알 수 없는 기간이에요.")
        lay = self._clean_layout(data or {})
        with self.lock:
            self.periods[pid]["default"] = lay
            self.save()
        return lay

    def period_default(self, pid):
        d = self.periods.get(pid, {}).get("default") or {}
        return {"base": d.get("base") or DEFAULT_BASE, "wall": d.get("wall"), "floor": d.get("floor"),
                "items": [dict(i) for i in d.get("items", [])]}

    def period_defaults(self):
        return {pid: self.period_default(pid) for pid in PERIOD_IDS}

    def period_halls(self):
        """운영진 관리 화면 : 기간마다의 배치(다음 기간을 미리 짜 둘 수 있게)."""
        return {pid: self.periods[pid]["halls"] for pid in PERIOD_IDS}

    def past_rooms_of(self, owner):
        """owner가 지난 기간에 배정됐던 방들(본인 마이페이지에서만 보여줌)."""
        cur_no = self.period_meta(self.current)["no"]
        out = []
        for meta in PERIODS:
            if meta["no"] >= cur_no:
                continue
            hall = next((h for h in self.periods[meta["id"]]["halls"] if owner in h.get("slots", [])), None)
            if hall is None:
                continue
            out.append({"period": self.period_meta(meta["id"]), "hall": hall.get("name"), "room": self.room(owner, meta["id"])})
        return out

    # ---- 관 이름 (그 관에 사는 사람 또는 운영진) ----
    def rename_hall(self, hall_id, name, by, is_gm=False):
        name = (name or "").strip()[:30]
        if not name:
            raise DormError(f"{self.period_meta(self.current)['unit']} 이름을 적어 주세요.")
        with self.lock:
            for h in self.halls:
                if h["id"] == hall_id:
                    if not is_gm and by not in h.get("slots", []):
                        raise DormError(f"자기 {self.period_meta(self.current)['unit']} 이름만 바꿀 수 있어요.")
                    h["name"] = name
                    self.save()
                    return h
        raise DormError("찾을 수 없어요.")

    # ---- 방 음악 · 방 주인 대사 (방 주인만) ----
    def _room_rec(self, owner):
        r = self.rooms.get(owner)
        if not r:
            r = self.rooms[owner] = {"v": 2, "base": DEFAULT_BASE, "wall": None, "floor": None, "items": []}
        return r

    def set_music(self, owner, music):
        with self.lock:
            r = self._room_rec(owner)
            old = r.get("music")
            r["music"] = music
            r["touched"] = time.time()
            self.save()
        return old

    def set_line(self, owner, text):
        text = (text or "").strip()[:80]
        with self.lock:
            r = self._room_rec(owner)
            r["line"] = text
            r["touched"] = time.time()
            self.save()

    # ---- 방명록 ----
    def write_guestbook(self, owner, author, text):
        text = (text or "").strip()
        if not text:
            raise DormError("방명록 내용을 써 주세요.")
        if len(text) > 300:
            raise DormError("방명록은 300자까지 쓸 수 있어요.")
        if self.hall_of(owner) is None:
            raise DormError("배정되지 않은 방이에요.")
        with self.lock:
            book = self.guestbooks.setdefault(owner, [])
            mine = next((e for e in book if e["author"] == author), None)
            if mine:   # 한 사람당 한 개 : 이미 있으면 고쳐 씁니다.
                mine.update({"text": text, "at": time.time(), "edited": True})
            else:
                book.append({"author": author, "text": text, "at": time.time()})
            self.save()

    def delete_guestbook(self, owner, author, by, is_gm=False):
        if by != author and by != owner and not is_gm:
            raise DormError("자기 글이나 자기 방 글만 지울 수 있어요.")
        with self.lock:
            book = self.guestbooks.get(owner, [])
            self.guestbooks[owner] = [e for e in book if e["author"] != author]
            self.save()

    # ---- 운영진 : 관 배치 ----
    def set_halls(self, halls, valid_names, period=None):
        clean, used = [], set()
        for h in (halls or [])[:50]:
            name = str(h.get("name") or "").strip()[:30] or "이름 없음"
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
            self.periods[period if period in self.periods else self.current]["halls"] = clean
            self.save()

    # ---- 운영진 : 자료·출처 ----
    def _credit_ok(self, cid):
        return cid if any(c["id"] == cid for c in self.all_credits()) else None

    def add_asset(self, name, category, url, w, h, credit_id, owner=None, lines=None, scale=None, px=True):
        if category not in CATEGORIES:
            raise DormError("종류가 올바르지 않습니다.")
        asset = {"id": uuid.uuid4().hex[:10], "name": (name or "").strip()[:30] or "이름 없음", "category": category,
                 "url": url, "w": _clamp(w, 1, 2000, 16), "h": _clamp(h, 1, 2000, 16), "px": True,
                 "credit": self._credit_ok(credit_id)}
        # 참가자가 올린 자료 : 올린 사람(owner) 표시, 매끈한 그림은 도트처럼 각지게 그리지 않음(smooth), 기본 배율(s)
        if owner:
            asset["owner"] = owner
        if not px:
            asset["smooth"] = True
        if scale:
            try:
                asset["s"] = max(0.02, min(4.0, round(float(scale), 3)))
            except (TypeError, ValueError):
                pass
        if category == "chara":
            asset["lines"] = _clean_lines(lines)
        with self.lock:
            if owner and sum(1 for a in self.assets if a.get("owner") == owner) >= USER_ASSET_MAX:
                raise DormError(f"아이템은 1인당 최대 {USER_ASSET_MAX}개까지 등록할 수 있습니다.")
            self.assets.append(asset)
            self.save()
        return asset

    def update_asset(self, asset_id, by=None, is_gm=True, **fields):
        with self.lock:
            for a in self.assets:
                if a["id"] == asset_id:
                    if not is_gm and a.get("owner") != by:
                        raise DormError("본인이 등록한 아이템만 수정할 수 있습니다.")
                    if "lines" in fields and a.get("category") == "chara":
                        a["lines"] = _clean_lines(fields["lines"])
                    if "name" in fields:
                        a["name"] = (fields["name"] or "").strip()[:30] or a["name"]
                    if fields.get("category") in CATEGORIES:
                        a["category"] = fields["category"]
                    if "credit" in fields:
                        a["credit"] = self._credit_ok(fields["credit"])
                    self.save()
                    return a
        raise DormError("기본 자료는 바꿀 수 없어요.")

    def delete_asset(self, asset_id, by=None, is_gm=True):
        with self.lock:
            target = next((a for a in self.assets if a["id"] == asset_id), None)
            if target is None or (not is_gm and target.get("owner") != by):
                return False
            self.assets = [a for a in self.assets if a["id"] != asset_id]
            for r in self.rooms.values():
                r["items"] = [i for i in r.get("items", []) if i.get("a") != asset_id]
                if r.get("base") == asset_id:
                    r["base"] = None
            self.save()
        return True

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
    def _clean_layout(self, data):
        """방 꾸밈(바탕 · 벽지 · 바닥 · 소품)을 검사해 저장할 모양으로 정리합니다(방 저장 · 기간 기본 방 공용)."""
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
                z = float(it.get("z") or a.get("s", 1))
                # 도트는 0.25배 단위, 참가자가 올린 원본 그림(smooth)은 큰 그림을 작게 놓으므로 세밀하게
                z = (max(0.02, min(4.0, round(z, 3))) if a.get("smooth")
                     else max(0.25, min(4.0, round(z * 4) / 4)))
            except (TypeError, ValueError):
                z = a.get("s", 1)
            w, h = a["w"] * z, a["h"] * z
            x = _clamp(it.get("x"), -w // 2, bw - w // 2, 0)
            y = _clamp(it.get("y"), -h // 2, bh - h // 2, 0)
            rec = {"a": a["id"], "x": x, "y": y, "f": bool(it.get("f")), "z": z}
            # 겹침 순서(앞/뒤로 보내기) : 정해 준 소품만 o 값을 가집니다. 없으면 바닥 쪽(아래)일수록 앞에 그립니다.
            if it.get("o") is not None:
                try:
                    rec["o"] = max(-10000, min(10000, int(it.get("o"))))
                except (TypeError, ValueError):
                    pass
            items.append(rec)
        # 캐릭터 SD는 방에 하나만 : 여러 개면 마지막에 놓은 것만 남깁니다.
        charas = [i for i, rec in enumerate(items) if (self.asset(rec["a"]) or {}).get("category") == "chara"]
        if len(charas) > 1:
            drop = set(charas[:-1])
            items = [rec for i, rec in enumerate(items) if i not in drop]
        # 벽지·바닥(방에 딱 맞춰 까는 것) : 자리(slot)가 맞는 자료만 받습니다.
        def slot_asset(key, slot):
            a = self.asset(data.get(key))
            return a["id"] if a and a.get("slot") == slot else None
        return {"base": base["id"], "wall": slot_asset("wall", "wall"), "floor": slot_asset("floor", "floor"), "items": items}

    def save_room(self, owner, data):
        lay = self._clean_layout(data)
        with self.lock:
            old = self.rooms.get(owner) or {}
            self.rooms[owner] = dict(lay, v=2, updated=time.time(), music=old.get("music"), line=old.get("line", ""))
            self.save()
        return self.room(owner)


_DORMS = None


def shared_dorms() -> Dorms:
    global _DORMS
    if _DORMS is None:
        _DORMS = Dorms()
    return _DORMS
