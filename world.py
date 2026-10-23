# -*- coding: utf-8 -*-
"""
world.py
========
일반 룸의 '맵' 탭 : 세계 지도의 장소(이름 · 한 줄 소개 · 설명 · 정보 칸 · 아이콘 그림)와
스토리 챕터(제목 · 요약), 그리고 지금 몇 챕터까지 해금됐는지를 저장합니다.
모든 방이 같은 맵을 씁니다. world.json에 저장됩니다(서버 컴퓨터별 실데이터라 git에 올리지 않음).

- 장소마다 '열리는 챕터'가 있어서, 그 챕터가 해금되기 전에는 러너 화면에 이름·설명이 가려집니다.
  (스포일러 방지 : 가린 내용은 서버가 아예 보내지 않습니다. 운영진은 전부 봅니다.)
"""

import json
import safeio
import os
import threading
import uuid

from world_zones import ZONE_DEFAULTS
from world_story import DEFAULT_GRAPH, STORY_VERSION, OLD_STORY_IDS

WORLD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world.json")
MAX_PLACES, MAX_CHAPTERS, MAX_INFO = 40, 60, 8
# 챕터 노드 그림(챕터 화면 위쪽) : 카드(글 · 그림)와 카드끼리 잇는 선
MAX_NODES, MAX_EDGES, GRAPH_SPAN = 80, 160, 4000
NODE_KINDS = ("text", "image", "timeline")
MAX_ITEMS, ITEM_HEAD, ITEM_TEXT = 20, 40, 600
NODE_ACCENTS = ("point", "violet", "blue", "green", "pink", "red", "amber", "gray")
SIDES = ("l", "r", "t", "b")
ZONES = 4  # 장소마다 1~4구역 카드


ZONE_DESC_MAX, ZONE_LINES_MAX, ZONE_LINE_LEN = 4000, 20, 120


def _default_zones():
    return [{"title": "", "image": None, "desc": "", "info": [], "ref": "", "lines": []} for i in range(ZONES)]


def _clean_lines(rows):
    out = []
    for r in (rows if isinstance(rows, list) else str(rows or "").split("\n")):
        t = _s(r, ZONE_LINE_LEN)
        if t:
            out.append(t)
        if len(out) >= ZONE_LINES_MAX:
            break
    return out


def _img_ok(img):
    return img if img and str(img).startswith(("/static/world/", "/static/world_default/")) else None


def _clean_info(rows, n):
    return [{"k": _s(i.get("k"), 20), "v": _s(i.get("v"), 80)}
            for i in (rows or [])[:n] if _s(i.get("k"), 20) or _s(i.get("v"), 80)]


def _clean_zones(zones):
    out = []
    for i in range(ZONES):
        z = (zones or [])[i] if i < len(zones or []) else {}
        out.append({"title": _s(z.get("title"), 30), "image": _img_ok(z.get("image")),
                    "desc": _text(z.get("desc"), ZONE_DESC_MAX), "info": _clean_info(z.get("info"), 4),
                    "ref": _s(z.get("ref"), 200), "lines": _clean_lines(z.get("lines"))})
    return out

# 예전 기본 구역 설명 : 운영진이 고치지 않은 채 남아 있으면 새 기본 내용으로 바꿉니다.
OLD_ZONE_DESCS = {'수업과 행정이 이루어지는 아카데미의 중심 건물입니다.', '학생들이 생활하는 기숙사 건물입니다. 관별 6인실로 운영됩니다.', '두 국가의 기록과 서적이 함께 보관된 장소입니다.', '공화국 의회와 광장이 있는 수도의 중심지입니다.', '국경 가까이 자리한 작은 마을들입니다.', '공화국의 기술 연구소가 모여 있는 구역입니다.', '공장과 연구 시설이 늘어선 연방의 생산 기지입니다.', '연방 의회와 주요 관청이 모여 있는 연방의 중심부입니다.', '대외 교역을 담당하는 항구와 창고가 모인 지역입니다.', '각 주의 상인이 모여드는 시장과 항구가 있는 지역입니다.', '노바 공화국과 맞닿은 경계를 지키는 군사 시설입니다.', '실습과 모의 전투가 열리는 야외 훈련 시설입니다.'}

# 처음(world.json이 없을 때) 보여줄 기본 맵 : 운영진이 편집에서 고쳐 쓰면 됩니다.
DEFAULT_WORLD = {
    "unlocked": 1,
    "chapters": [
        {"id": "ch1", "title": "입학", "summary": "넥서스 아카데미의 새 학기가 시작됩니다. 챕터 요약은 편집에서 바꿀 수 있습니다."},
        {"id": "ch2", "title": "두 국가", "summary": "챕터 요약을 입력해 주세요."},
        {"id": "ch3", "title": "경계 너머", "summary": "챕터 요약을 입력해 주세요."},
    ],
    "places": [
        {"zones": ZONE_DEFAULTS["arcadia"], "id": "arcadia", "name": "아르카디아 연방", "en": "ARCADIA", "sub": "연방국", "chapter": 0,
         "image": "/static/world_default/arcadia.svg",
         "desc": "여러 주(州)가 하나로 모인 연방 국가입니다. 상징색은 노랑입니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "체제", "v": "연방제"}, {"k": "상징색", "v": "노랑"}, {"k": "수도", "v": "-"}, {"k": "특징", "v": "-"}]},
        {"zones": ZONE_DEFAULTS["nexus"], "id": "nexus", "name": "넥서스 아카데미", "en": "NEXUS", "sub": "아카데미", "chapter": 0,
         "image": "/static/world_default/nexus.svg",
         "desc": "아르카디아 연방과 노바 공화국 사이에 자리한 학교입니다. 두 국가의 학생들이 함께 지냅니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "구분", "v": "교육 기관"}, {"k": "위치", "v": "두 국가의 경계"}, {"k": "기숙사", "v": "관별 6인실"}, {"k": "특징", "v": "-"}]},
        {"zones": ZONE_DEFAULTS["nova"], "id": "nova", "name": "노바 공화국", "en": "NOVA", "sub": "공화국", "chapter": 0,
         "image": "/static/world_default/nova.svg",
         "desc": "시민이 대표를 뽑아 다스리는 공화국입니다. 상징색은 파랑입니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "체제", "v": "공화제"}, {"k": "상징색", "v": "파랑"}, {"k": "수도", "v": "-"}, {"k": "특징", "v": "-"}]},
        {"id": "border", "name": "경계 지대", "en": "THE BORDERLANDS", "sub": "미개척 구역", "chapter": 2, "image": None,
         "desc": "두 국가 사이의 아직 알려지지 않은 땅입니다.", "info": []},
    ],
}


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def clean_graph(data, n_chapters):
    """노드 그림 정리 : 노드(종류 · 글 · 그림 · 위치 · 너비 · 공개 챕터)와 선(노드 id · 면 · 면 위 위치)."""
    nodes, ids = [], set()
    for nd in ((data or {}).get("nodes") or [])[:MAX_NODES]:
        if not isinstance(nd, dict):
            continue
        nid = _s(nd.get("id"), 16) or uuid.uuid4().hex[:8]
        if nid in ids:
            continue
        ids.add(nid)
        kind = nd.get("kind") if nd.get("kind") in NODE_KINDS else "text"
        items = []
        if kind == "timeline":   # 타임라인 카드 : 한 카드 안의 단계들(머리 · 글)
            for it in (nd.get("items") or [])[:MAX_ITEMS]:
                if isinstance(it, dict) and (_s(it.get("head"), ITEM_HEAD) or _text(it.get("text"), ITEM_TEXT)):
                    items.append({"head": _s(it.get("head"), ITEM_HEAD), "text": _text(it.get("text"), ITEM_TEXT)})
        nodes.append({"id": nid, "kind": kind, "items": items, "label": _s(nd.get("label"), 30), "tag": _s(nd.get("tag"), 30),
                      "title": _s(nd.get("title"), 40), "text": _text(nd.get("text"), 600), "image": _img_ok(nd.get("image")),
                      "x": round(_num(nd.get("x"), 0, GRAPH_SPAN, 40)), "y": round(_num(nd.get("y"), 0, GRAPH_SPAN, 40)),
                      "w": round(_num(nd.get("w"), 140, 520, 260)),
                      "accent": nd.get("accent") if nd.get("accent") in NODE_ACCENTS else "point",
                      "chapter": int(_num(nd.get("chapter"), 0, n_chapters, 0))})
    edges, seen = [], set()
    for e in ((data or {}).get("edges") or [])[:MAX_EDGES]:
        if not isinstance(e, dict) or e.get("a") not in ids or e.get("b") not in ids or e.get("a") == e.get("b"):
            continue
        ed = {"a": e["a"], "as": e.get("as") if e.get("as") in SIDES else "r", "at": round(_num(e.get("at"), 0, 1, .5), 3),
              "b": e["b"], "bs": e.get("bs") if e.get("bs") in SIDES else "l", "bt": round(_num(e.get("bt"), 0, 1, .5), 3)}
        key = (ed["a"], ed["as"], ed["at"], ed["b"], ed["bs"], ed["bt"])
        if key not in seen:
            seen.add(key)
            edges.append(ed)
    return {"nodes": nodes, "edges": edges}


def _s(v, n):
    return " ".join(str(v or "").split())[:n]


def _text(v, n):
    return str(v or "").replace("\r", "").strip()[:n]


class World:
    def __init__(self, path=WORLD_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.places, self.chapters, self.unlocked = [], [], 0
        self.graph = {"nodes": [], "edges": []}
        self.story_seeded = False
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = None
        if d is None:  # 아직 저장한 적이 없으면 기본 맵
            d = json.loads(json.dumps(DEFAULT_WORLD))
        self.places = d.get("places", [])
        migrated = False
        short_en = {"ARCADIA FEDERATION": "ARCADIA", "NOVA REPUBLIC": "NOVA", "NEXUS ACADEMY": "NEXUS"}   # 맵 글자가 너무 길어 줄였어요
        for p in self.places:
            if p.get("en") in short_en:
                p["en"] = short_en[p["en"]]
                migrated = True
            if p.get("id") == "nexus" and p.get("sub") == "학교":
                p["sub"] = "아카데미"
                migrated = True
        for p in self.places:  # 구역이 없던 예전 장소에도 1~4구역 자리를 만들고, 새 칸(참고 · 한 줄 문구)을 채웁니다
            p["zones"] = _clean_zones(p.get("zones"))
            new = ZONE_DEFAULTS.get(p.get("id"))
            if not new:
                continue
            for i, z in enumerate(p["zones"]):
                # 운영진이 손대지 않은 예전 기본 구역(또는 빈 구역)만 새 기본 내용으로 바꿉니다(올린 그림은 유지)
                if z["desc"] in OLD_ZONE_DESCS or (not z["desc"] and not z["title"]):
                    p["zones"][i] = dict(json.loads(json.dumps(new[i])), image=z.get("image"))
                    migrated = True
        self.chapters = d.get("chapters", [])
        self.unlocked = int(d.get("unlocked") or 0)
        self.graph = clean_graph(d.get("graph"), len(self.chapters))
        seeded = d.get("story_seeded")
        self.story_seeded = int(seeded) if seeded else 0   # 예전 True = 1판
        if self.story_seeded < STORY_VERSION:
            # 노드 그림이 비었거나 손대지 않은 예전 기본 스토리면 새 기본 스토리로(운영진이 만든 노드는 그대로)
            ids = {n["id"] for n in self.graph["nodes"]}
            if not ids or (self.story_seeded and ids in OLD_STORY_IDS):
                self.graph = clean_graph(DEFAULT_GRAPH, len(self.chapters))
            self.story_seeded = STORY_VERSION
            migrated = True
        if migrated and os.path.exists(self.path):
            self.save()

    def save(self):
        safeio.write_json(self.path, {"places": self.places, "chapters": self.chapters, "unlocked": self.unlocked,
                                        "graph": self.graph, "story_seeded": self.story_seeded}, indent=1)

    # ---- 운영진 : 통째로 저장 ----
    def set_all(self, data):
        chapters = []
        for c in (data.get("chapters") or [])[:MAX_CHAPTERS]:
            title = _s(c.get("title"), 40)
            if not title:
                continue
            chapters.append({"id": _s(c.get("id"), 16) or uuid.uuid4().hex[:8], "title": title,
                             "summary": _text(c.get("summary"), 600)})
        places = []
        for p in (data.get("places") or [])[:MAX_PLACES]:
            name = _s(p.get("name"), 30)
            if not name:
                continue
            info = [{"k": _s(i.get("k"), 20), "v": _s(i.get("v"), 80)}
                    for i in (p.get("info") or [])[:MAX_INFO] if _s(i.get("k"), 20) or _s(i.get("v"), 80)]
            img = p.get("image") or None
            if img and not str(img).startswith(("/static/world/", "/static/world_default/")):
                img = None
            try:
                ch = max(0, min(len(chapters), int(p.get("chapter") or 0)))
            except (TypeError, ValueError):
                ch = 0
            places.append({"zones": _clean_zones(p.get("zones")), "id": _s(p.get("id"), 16) or uuid.uuid4().hex[:8], "name": name,
                           "en": _s(p.get("en"), 30), "sub": _s(p.get("sub"), 30),
                           "desc": _text(p.get("desc"), 1200), "info": info, "image": img, "chapter": ch})
        try:
            unlocked = max(0, min(len(chapters), int(data.get("unlocked") or 0)))
        except (TypeError, ValueError):
            unlocked = self.unlocked
        with self.lock:
            self.chapters, self.places, self.unlocked = chapters, places, unlocked
            self.graph = clean_graph(self.graph, len(chapters))   # 챕터 수가 줄면 노드 공개 시점도 맞춰요
            self.save()

    def reset_graph(self):
        """운영진 : 노드 그림을 기본 스토리로 되돌려요."""
        self.set_graph(DEFAULT_GRAPH)

    def set_graph(self, data):
        with self.lock:
            self.graph = clean_graph(data, len(self.chapters))
            self.save()

    # ---- 화면에 보낼 내용 (러너에게는 잠긴 것을 가림) ----
    def payload(self, is_gm=False):
        n = self.unlocked
        if is_gm:
            return {"chapters": self.chapters, "places": self.places, "unlocked": n, "gm": True, "graph": self.graph}
        chapters = [c if i < n else {"id": c["id"], "locked": True} for i, c in enumerate(self.chapters)]
        places = [p if p.get("chapter", 0) <= n else {"id": p["id"], "locked": True, "chapter": p.get("chapter", 0)}
                  for p in self.places]
        # 아직 공개 전인 노드는 자리만(내용은 보내지 않아요)
        nodes = [nd if nd.get("chapter", 0) <= n else {"id": nd["id"], "kind": "text", "x": nd["x"], "y": nd["y"], "w": nd["w"], "accent": nd.get("accent"), "locked": True}
                 for nd in self.graph["nodes"]]
        return {"chapters": chapters, "places": places, "unlocked": n, "gm": False,
                "graph": {"nodes": nodes, "edges": self.graph["edges"]}}

    def payload_play(self):
        """PLAY 룸(LOOP)용 맵 : 챕터는 보이지 않고, 학교는 잠겨 있어요. 편집도 없습니다(운영진 포함)."""
        n = self.unlocked
        school = lambda p: p.get("id") == "nexus" or "학교" in (p.get("sub") or "")
        def view(p):
            if school(p):   # 학교 : 아이콘 · 이름은 보이고, 장소 안(설명 · 구역)만 해금 전
                return {"id": p["id"], "name": p.get("name"), "en": p.get("en"), "sub": p.get("sub"), "image": p.get("image"),
                        "locked": True, "sealed": True, "chapter": 0}
            if p.get("chapter", 0) > n:
                return {"id": p["id"], "locked": True, "chapter": 0}
            return dict(p, chapter=0)
        places = [view(p) for p in self.places]
        return {"chapters": [], "places": places, "unlocked": n, "gm": False}


_WORLD = None


def shared_world() -> World:
    global _WORLD
    if _WORLD is None:
        _WORLD = World()
    return _WORLD
