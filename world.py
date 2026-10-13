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
import os
import threading
import uuid

WORLD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world.json")
MAX_PLACES, MAX_CHAPTERS, MAX_INFO = 40, 60, 8
ZONES = 4  # 장소마다 1~4구역 카드


def _default_zones():
    return [{"title": "", "image": None, "desc": "", "info": []} for i in range(ZONES)]


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
                    "desc": _text(z.get("desc"), 600), "info": _clean_info(z.get("info"), 4)})
    return out

# 처음(world.json이 없을 때) 보여줄 기본 맵 : 운영진이 편집에서 고쳐 쓰면 됩니다.
DEFAULT_WORLD = {
    "unlocked": 1,
    "chapters": [
        {"id": "ch1", "title": "입학", "summary": "넥서스 아카데미의 새 학기가 시작됩니다. 챕터 요약은 편집에서 바꿀 수 있습니다."},
        {"id": "ch2", "title": "두 국가", "summary": "챕터 요약을 입력해 주세요."},
        {"id": "ch3", "title": "경계 너머", "summary": "챕터 요약을 입력해 주세요."},
    ],
    "places": [
        {"zones": [{"title": "중앙 행정구", "image": None, "desc": "연방 의회와 주요 관청이 모여 있는 연방의 중심부입니다.", "info": [{"k": "구분", "v": "행정"}, {"k": "치안", "v": "높음"}]}, {"title": "상업 지구", "image": None, "desc": "각 주의 상인이 모여드는 시장과 항구가 있는 지역입니다.", "info": [{"k": "구분", "v": "상업"}, {"k": "유동 인구", "v": "많음"}]}, {"title": "산업 지대", "image": None, "desc": "공장과 연구 시설이 늘어선 연방의 생산 기지입니다.", "info": [{"k": "구분", "v": "산업"}, {"k": "출입", "v": "허가 필요"}]}, {"title": "국경 요새", "image": None, "desc": "노바 공화국과 맞닿은 경계를 지키는 군사 시설입니다.", "info": [{"k": "구분", "v": "군사"}, {"k": "치안", "v": "통제"}]}], "id": "arcadia", "name": "아르카디아 연방", "en": "ARCADIA FEDERATION", "sub": "연방국", "chapter": 0,
         "image": "/static/world_default/arcadia.svg",
         "desc": "여러 주(州)가 하나로 모인 연방 국가입니다. 상징색은 노랑입니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "체제", "v": "연방제"}, {"k": "상징색", "v": "노랑"}, {"k": "수도", "v": "-"}, {"k": "특징", "v": "-"}]},
        {"zones": [{"title": "본관", "image": None, "desc": "수업과 행정이 이루어지는 아카데미의 중심 건물입니다.", "info": [{"k": "구분", "v": "교육"}, {"k": "개방", "v": "수업 시간"}]}, {"title": "기숙사동", "image": None, "desc": "학생들이 생활하는 기숙사 건물입니다. 관별 6인실로 운영됩니다.", "info": [{"k": "구분", "v": "생활"}, {"k": "통금", "v": "22:00"}]}, {"title": "훈련장", "image": None, "desc": "실습과 모의 전투가 열리는 야외 훈련 시설입니다.", "info": [{"k": "구분", "v": "실습"}, {"k": "사용", "v": "예약제"}]}, {"title": "도서관", "image": None, "desc": "두 국가의 기록과 서적이 함께 보관된 장소입니다.", "info": [{"k": "구분", "v": "학습"}, {"k": "개방", "v": "상시"}]}], "id": "nexus", "name": "넥서스 아카데미", "en": "NEXUS ACADEMY", "sub": "학교", "chapter": 0,
         "image": "/static/world_default/nexus.svg",
         "desc": "아르카디아 연방과 노바 공화국 사이에 자리한 학교입니다. 두 국가의 학생들이 함께 지냅니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "구분", "v": "교육 기관"}, {"k": "위치", "v": "두 국가의 경계"}, {"k": "기숙사", "v": "관별 6인실"}, {"k": "특징", "v": "-"}]},
        {"zones": [{"title": "수도 중심가", "image": None, "desc": "공화국 의회와 광장이 있는 수도의 중심지입니다.", "info": [{"k": "구분", "v": "행정"}, {"k": "치안", "v": "높음"}]}, {"title": "항만 지구", "image": None, "desc": "대외 교역을 담당하는 항구와 창고가 모인 지역입니다.", "info": [{"k": "구분", "v": "교역"}, {"k": "유동 인구", "v": "많음"}]}, {"title": "연구 단지", "image": None, "desc": "공화국의 기술 연구소가 모여 있는 구역입니다.", "info": [{"k": "구분", "v": "연구"}, {"k": "출입", "v": "허가 필요"}]}, {"title": "변방 마을", "image": None, "desc": "국경 가까이 자리한 작은 마을들입니다.", "info": [{"k": "구분", "v": "거주"}, {"k": "치안", "v": "보통"}]}], "id": "nova", "name": "노바 공화국", "en": "NOVA REPUBLIC", "sub": "공화국", "chapter": 0,
         "image": "/static/world_default/nova.svg",
         "desc": "시민이 대표를 뽑아 다스리는 공화국입니다. 상징색은 파랑입니다.\n장소 설명은 편집에서 바꿀 수 있습니다.",
         "info": [{"k": "체제", "v": "공화제"}, {"k": "상징색", "v": "파랑"}, {"k": "수도", "v": "-"}, {"k": "특징", "v": "-"}]},
        {"id": "border", "name": "경계 지대", "en": "THE BORDERLANDS", "sub": "미개척 구역", "chapter": 2, "image": None,
         "desc": "두 국가 사이의 아직 알려지지 않은 땅입니다.", "info": []},
    ],
}


def _s(v, n):
    return " ".join(str(v or "").split())[:n]


def _text(v, n):
    return str(v or "").replace("\r", "").strip()[:n]


class World:
    def __init__(self, path=WORLD_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.places, self.chapters, self.unlocked = [], [], 0
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
        for p in self.places:  # 구역이 없던 예전 장소에도 1~4구역 자리를 만듭니다
            if len(p.get("zones") or []) != ZONES:
                p["zones"] = _clean_zones(p.get("zones"))
        self.chapters = d.get("chapters", [])
        self.unlocked = int(d.get("unlocked") or 0)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"places": self.places, "chapters": self.chapters, "unlocked": self.unlocked},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

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
            self.save()

    # ---- 화면에 보낼 내용 (러너에게는 잠긴 것을 가림) ----
    def payload(self, is_gm=False):
        n = self.unlocked
        if is_gm:
            return {"chapters": self.chapters, "places": self.places, "unlocked": n, "gm": True}
        chapters = [c if i < n else {"id": c["id"], "locked": True} for i, c in enumerate(self.chapters)]
        places = [p if p.get("chapter", 0) <= n else {"id": p["id"], "locked": True, "chapter": p.get("chapter", 0)}
                  for p in self.places]
        return {"chapters": chapters, "places": places, "unlocked": n, "gm": False}


_WORLD = None


def shared_world() -> World:
    global _WORLD
    if _WORLD is None:
        _WORLD = World()
    return _WORLD
