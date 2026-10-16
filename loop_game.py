# -*- coding: utf-8 -*-
"""
loop_game.py
============
PLAY 룸 「LOOP : 생존 시뮬레이션」 진행 상태.

- 캐릭터마다 지금 생애(run) 하나와 지난 생애 기록(lives)을 가집니다. 모든 PLAY 룸이 같은 기록을 씁니다.
- 체력과 정신은 각각 시작값에서 출발해 0~최대 사이를 오갑니다. 체력이 0이면 사망, 정신이 0이면 정신 붕괴입니다.
- 출신 국가(아르카디아 / 노바)는 생애마다 무작위로 정해지고, 공명 여부와 함께 기득권 · 비기득권이 갈립니다.
- 진영(使徒 / Void)은 전쟁 때의 포지션이고 서로 적입니다(캐릭터 정보의 진영 칸).
- 균열 압력(지구의 반발) : 문명을 밀어붙이는 선택으로 쌓이고, 쌓인 만큼 재난(자정작용)이 잦아집니다.
- 시대 I → V 순서로 사건이 이어지고, 마지막 시대의 사건을 모두 견디면 '전쟁 이후' 엔딩입니다.
- 죽으면 '생애 종료'(기록만 남김) 또는 '루프 진입'(VI. 회귀 → IV. 전쟁 → V. 종전으로 다시)을 고릅니다.
- 체력 · 정신 변동은 고른 뒤에만 알려 줍니다(고르기 전 화면에는 선택지 문장만 보냅니다).

사건 · 규칙 · 문장(내용)은 운영진이 편집 페이지에서 고칠 수 있고 loop_content.json에 저장됩니다.
파일이 없으면 loop_events.py의 기본값을 씁니다. 진행 기록은 loop_runs.json(둘 다 git 밖 실데이터).
"""

import copy
import json
import os
import random
import re
import threading
import time

import safeio
from loop_events import default_content, HISTORY, OLD_HISTORY

_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_PATH = os.path.join(_DIR, "loop_runs.json")
CONTENT_PATH = os.path.join(_DIR, "loop_content.json")
HP_MIN = 0
MAX_LIVES = 30            # 캐릭터마다 남기는 지난 생애 수
RESONANCE = ("res", "non")
KINDS = ("life", "war", "plague", "purge", "loop")       # 사건 종류(체력으로 죽을 때 사망 문장을 고름)
DEATH_KINDS = KINDS + ("mind",)
STATS = ("hp", "mind")
# 자원 : 재산 · 지능은 쓰면 줄어드는 자원(전쟁 전 사건 '해결'), 재능(= 노바의 '기술')은 선택지 조건으로 쓰는 능력치.
RESOURCES = ("wealth", "intel", "talent")
SPENDABLE = ("wealth", "intel")
# 균열 압력(지구의 반발) : 문명을 밀어붙이는 선택으로 쌓이고, 쌓인 만큼 재난(자정작용)이 잦아져요.
STRAIN = "strain"
GAINABLE = RESOURCES + (STRAIN,)
# 루프를 넘어가도 남는 태그(나머지 기억은 흐려집니다)
LOOP_KEEP_TAGS = {"LOOP_CONTACT", "LOOP_NOTES", "LOOP_ALLY", "TRUTH", "FRACTURE_SEEN", "LEFT_BEHIND", "KILLED", "SAVED_ONE"}

# 출신 국가 : 아르카디아에서는 공명자가 기득권, 노바에서는 비공명자가 기득권.
TEST_ID = "TEST"  # PLAY 룸 공용 아이디. 기록은 기기마다 따로("TEST#기기번호")


def clean_device_id(v):
    """브라우저가 만든 기기 번호 : 영문 · 숫자 8~40자만."""
    v = str(v or "")
    return v if 8 <= len(v) <= 40 and re.fullmatch(r"[A-Za-z0-9]+", v) else ""


COUNTRIES = {"arcadia": "아르카디아", "nova": "노바"}
# 진영 : 전쟁 때의 포지션. 서로 적입니다. 출신 국가를 따라가요(아르카디아 → 使徒, 노바 → Void).
FACTIONS = ("使徒", "Void")
COUNTRY_FACTION = {"arcadia": "使徒", "nova": "Void"}


class LoopError(Exception):
    pass


# ══════════════════════════════════════════════════════════════
# 내용(사건 · 규칙 · 문장) : 운영진 편집 → 검사 → 저장
# ══════════════════════════════════════════════════════════════
def _s(v, n=2000):
    return str(v if v is not None else "").strip()[:n]


def _lines(v, n=40):
    """문단 목록 : 문자열이면 줄 단위로 자르고, 빈 줄은 뺍니다."""
    if isinstance(v, str):
        v = v.split("\n")
    return [_s(x, 1000) for x in (v or []) if _s(x, 1000)][:n]


def _int(v, lo, hi, d):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return d


def _tags(v):
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    out = []
    for t in v or []:
        t = _s(t, 40).upper().replace(" ", "_")
        if t and t not in out:
            out.append(t)
    return out[:20]


def clean_content(c):
    """편집 페이지에서 온 내용을 검사해서 게임이 쓸 수 있는 모양으로 다듬습니다. 잘못된 곳이 있으면 LoopError."""
    if not isinstance(c, dict):
        raise LoopError("내용 형식이 올바르지 않아요.")
    d = default_content()
    r = c.get("rules") or {}
    rules = {"hp_max": _int(r.get("hp_max"), 1, 20, 5), "mind_max": _int(r.get("mind_max"), 1, 20, 5)}
    rules["hp_start"] = _int(r.get("hp_start"), 1, rules["hp_max"], rules["hp_max"])
    rules["mind_start"] = _int(r.get("mind_start"), 1, rules["mind_max"], rules["mind_max"])

    eras = []
    for x in (c.get("eras") or [])[:12]:
        eid = _int(x.get("id"), 1, 99, 0)
        if not eid or any(e["id"] == eid for e in eras):
            continue
        eras.append({"id": eid, "no": _s(x.get("no"), 8) or str(eid), "name": _s(x.get("name"), 40) or f"시대 {eid}",
                     "period": _s(x.get("period"), 40), "level": _s(x.get("level"), 20), "len": _int(x.get("len"), 1, 30, 3),
                     "risk": max(0.0, min(1.0, float(x.get("risk") or 0))), "luck": max(0.0, min(1.0, float(x.get("luck") or 0))),
                     "risk_text": [{"stat": t.get("stat") if t.get("stat") in STATS else "hp", "text": _s(t.get("text"), 500)}
                                   for t in (x.get("risk_text") or []) if isinstance(t, dict) and _s(t.get("text"))][:20]})
        if eras[-1]["risk"] + eras[-1]["luck"] > 1:
            raise LoopError(f"{eras[-1]['no']} 시대 : 위험 + 행운 확률은 100%를 넘을 수 없어요.")
    if not eras:
        raise LoopError("시대가 하나 이상 있어야 해요.")
    era_ids = {e["id"] for e in eras}
    rr = r.get("res") or {}
    dr = d["rules"]["res"]
    res_max = _int(rr.get("max"), 1, 10, dr["max"])
    start = {}
    for cc in COUNTRIES:
        start[cc] = {}
        for pv in ("priv", "non"):
            start[cc][pv] = {}
            for k in RESOURCES:
                v = (((rr.get("start") or {}).get(cc) or {}).get(pv) or {}).get(k) or dr["start"][cc][pv][k]
                lo, hi = _int(v[0], 0, res_max, 0), _int(v[1], 0, res_max, 0)
                start[cc][pv][k] = [min(lo, hi), max(lo, hi)]
    cost = {cc: {k: _int(((rr.get("cost") or {}).get(cc) or {}).get(k), 0, 10, dr["cost"][cc][k]) for k in SPENDABLE} for cc in COUNTRIES}
    rules["res"] = {"max": res_max, "start": start, "cost": cost, "solve_eras": [_int(x, 1, 99, 0) for x in (rr.get("solve_eras") or []) if _int(x, 1, 99, 0)]}
    sr, ds = r.get("strain") or {}, d["rules"]["strain"]

    def _f(v, lo, hi, dv):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return dv
    rules["strain"] = {"max": _int(sr.get("max"), 1, 20, ds["max"]), "per": _f(sr.get("per"), 0, 0.2, ds["per"]),
                       "loop_keep": _f(sr.get("loop_keep"), 0, 1, ds["loop_keep"])}
    chapters = []
    for i, ch in enumerate((r.get("chapters") or d["rules"]["chapters"])[:10]):
        if not isinstance(ch, dict):
            continue
        chapters.append({"id": i, "name": _s(ch.get("name"), 30) or f"{i}단계", "sub": _s(ch.get("sub"), 60),
                         "eras": [x for x in (_int(e, 1, 99, 0) for e in (ch.get("eras") or [])) if x in era_ids],
                         "loop": bool(ch.get("loop"))})
    if not chapters:
        chapters = copy.deepcopy(d["rules"]["chapters"])
    rules["chapters"] = chapters
    rules["release"] = _int(r.get("release"), 0, len(chapters) - 1, 0)
    for key in ("first_life", "loop_life"):
        seq = [_int(x, 1, 99, 0) for x in (r.get(key) or [])]
        seq = [x for x in seq if x in era_ids][:12]
        if not seq:
            raise LoopError("첫 생애 · 루프 생애의 시대 순서를 정해 주세요.")
        rules[key] = seq

    events, ids = [], set()
    for ev in (c.get("events") or [])[:400]:
        eid = _s(ev.get("id"), 12)
        title = _s(ev.get("title"), 60)
        if not eid or not title:
            raise LoopError("사건마다 번호와 제목이 있어야 해요.")
        if eid in ids:
            raise LoopError(f"사건 번호 {eid}가 두 번 있어요.")
        ids.add(eid)
        era = _int(ev.get("era"), 1, 99, 0)
        if era not in era_ids:
            raise LoopError(f"EVENT {eid} : 없는 시대예요.")
        cond_in = ev.get("cond") or {}
        cond = {}
        if cond_in.get("res") in RESONANCE:
            cond["res"] = cond_in["res"]
        if cond_in.get("country") in COUNTRIES:
            cond["country"] = cond_in["country"]
        if _tags(cond_in.get("tags")):
            cond["tags"] = _tags(cond_in.get("tags"))
        if _tags(cond_in.get("no_tags")):
            cond["no_tags"] = _tags(cond_in.get("no_tags"))
        if _int(cond_in.get("loops"), 0, 99, 0):
            cond["loops"] = _int(cond_in.get("loops"), 0, 99, 0)
        mins = {k: _int((cond_in.get("min") or {}).get(k), 0, 20, 0) for k in GAINABLE}
        mins = {k: v for k, v in mins.items() if v}
        if mins:
            cond["min"] = mins
        story = _lines(ev.get("story"))
        draft = bool(ev.get("draft"))
        if not story and not draft:
            raise LoopError(f"EVENT {eid} : 상황 서술을 써 주세요. (아직 작업 중이면 '작업 중'을 켜 두세요)")
        choices = []
        for i, ch in enumerate((ev.get("choices") or [])[:3]):
            label = _s(ch.get("label"), 200)
            if not label and not draft:
                raise LoopError(f"EVENT {eid} : 선택지 {'ABC'[i]} 문장을 써 주세요. (아직 작업 중이면 '작업 중'을 켜 두세요)")
            item = {"label": label, "hp": _int(ch.get("hp"), -3, 3, 0), "mind": _int(ch.get("mind"), -3, 3, 0),
                    "result": "\n".join(_lines(ch.get("result"), 10)), "tags": _tags(ch.get("tags"))}
            need = {k: _int((ch.get("need") or {}).get(k), 0, 10, 0) for k in RESOURCES}
            gain = {k: _int((ch.get("gain") or {}).get(k), -5, 5, 0) for k in GAINABLE}
            if any(need.values()):
                item["need"] = {k: v for k, v in need.items() if v}
            if any(gain.values()):
                item["gain"] = {k: v for k, v in gain.items() if v}
            choices.append(item)
        if len(choices) != 3:
            raise LoopError(f"EVENT {eid} : 선택지는 3개여야 해요.")
        extra = []
        for x in (ev.get("extra") or [])[:10]:
            w = x.get("when") or {}
            when = {}
            if w.get("tag"):
                when["tag"] = _tags([w["tag"]])[0] if _tags([w["tag"]]) else ""
            if w.get("hp_lte") not in (None, ""):
                when["hp_lte"] = _int(w["hp_lte"], 0, 20, 1)
            if w.get("mind_lte") not in (None, ""):
                when["mind_lte"] = _int(w["mind_lte"], 0, 20, 1)
            if w.get("loops") not in (None, ""):
                when["loops"] = _int(w["loops"], 0, 99, 1)
            text = _lines(x.get("text"), 10)
            if not text:
                continue
            at = "result" if x.get("at") == "result" else "story"
            item = {"when": when, "at": at, "text": text}
            if at == "result":
                item["choice"] = _int(x.get("choice"), 0, 2, 0)
            extra.append(item)
        item = {"id": eid, "era": era, "title": title, "kind": ev.get("kind") if ev.get("kind") in KINDS else "life",
                "story": story, "choices": choices}
        if ev.get("chapter") not in (None, "", -1):
            item["chapter"] = _int(ev.get("chapter"), 0, 9, 0)
        if _s(ev.get("note"), 3000):
            item["note"] = _s(ev.get("note"), 3000)      # 운영진 작업 메모(플레이어에게는 안 보여요)
        if ev.get("draft"):
            item["draft"] = True                         # 작업 중 : 플레이에 나오지 않아요
        if cond:
            item["cond"] = cond
        if ev.get("fixed") == "open":
            item["fixed"] = "open"
        if extra:
            item["extra"] = extra
        events.append(item)
    if not events:
        raise LoopError("사건이 하나 이상 있어야 해요.")

    t, dt = c.get("texts") or {}, d["texts"]

    def mood(v, dv):
        rows = [{"min": _int(x.get("min"), 0, 20, 0), "text": _lines(x.get("text"), 5)} for x in (v or []) if isinstance(x, dict)]
        rows = [x for x in rows if x["text"]]
        return sorted(rows, key=lambda x: -x["min"]) or dv

    def titled(v, dv):
        out = {}
        for k, dx in dv.items():
            x = (v or {}).get(k) or {}
            out[k] = {"title": _s(x.get("title"), 60) or dx["title"], "text": _lines(x.get("text"), 20) or dx["text"]}
        return out

    texts = {"intro": _lines(t.get("intro"), 12) or dt["intro"],
             "mood_hp": mood(t.get("mood_hp"), dt["mood_hp"]), "mood_mind": mood(t.get("mood_mind"), dt["mood_mind"]),
             "death": titled(t.get("death"), dt["death"]), "ending": titled(t.get("ending"), dt["ending"]),
             "luck": {k: _lines((t.get("luck") or {}).get(k), 20) or dt["luck"][k] for k in STATS},
             "solve": {k: _lines((t.get("solve") or {}).get(k), 20) or dt["solve"][k] for k in SPENDABLE},
             "purge": _lines(t.get("purge"), 30) or dt["purge"],
             "history": _lines(t.get("history"), 30) or dt["history"],
             "birth": {k: _s((t.get("birth") or {}).get(k), 300) or dv for k, dv in dt["birth"].items()}}
    views = []
    for v in (t.get("views") or [])[:20]:
        if not isinstance(v, dict):
            continue
        vid = _s(v.get("id"), 20) or f"v{len(views) + 1}"
        name = _s(v.get("name"), 20)
        text = _lines(v.get("text"), 10)
        if not name or not text or any(x["id"] == vid for x in views):
            continue
        country = v.get("country") if v.get("country") in COUNTRIES else ""   # 비우면 두 나라 모두
        views.append({"id": vid, "name": name, "tag": (_tags([v.get("tag")]) or [""])[0], "country": country, "text": text})
    texts["views"] = views or dt["views"]
    return {"rules": rules, "eras": eras, "events": events, "texts": texts}


class Content:
    """지금 쓰는 내용. 저장하면 바로 다음 사건부터 반영됩니다."""

    def __init__(self, path=CONTENT_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.custom = False
        self.set(self._load())

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # 예전에 저장한 '순응' 문명관(아르카디아 4구역 이야기)은 아르카디아 전용으로 옮깁니다.
            for v in ((raw.get("texts") or {}).get("views") or []) if isinstance(raw, dict) else []:
                if isinstance(v, dict) and v.get("id") == "earth" and "country" not in v:
                    v["country"] = "arcadia"
            c = clean_content(raw)
            if c["texts"].get("history") == OLD_HISTORY:
                c["texts"]["history"] = list(HISTORY)
            self.custom = True
            return c
        except (OSError, json.JSONDecodeError, LoopError, ValueError, TypeError, AttributeError):
            self.custom = False
            return clean_content(default_content())

    def set(self, c):
        with self.lock:
            self.c = c
            self.rules = c["rules"]
            self.eras = {e["id"]: e for e in c["eras"]}
            self.events = c["events"]
            self.by_id = {e["id"]: e for e in c["events"]}
            self.texts = c["texts"]

    def save(self, raw):
        c = clean_content(raw)
        with self.lock:
            safeio.write_json(self.path, c, indent=1)
            self.custom = True
            self.set(c)
        return c

    def reset(self):
        with self.lock:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.custom = False
            self.set(clean_content(default_content()))

    def payload(self):
        """편집 페이지용 전체 내용(운영진에게만 보냅니다 — 체력 · 정신 변동이 들어 있어요)."""
        with self.lock:
            return {"content": copy.deepcopy(self.c), "custom": self.custom, "kinds": list(KINDS), "death_kinds": list(DEATH_KINDS)}

    def res_rules(self):
        return self.rules.get("res") or default_content()["rules"]["res"]

    def strain_rules(self):
        return self.rules.get("strain") or default_content()["rules"]["strain"]

    # ── 공개 챕터 ──
    def release(self):
        return self.rules.get("release", 0)

    def era_chapter(self, era):
        for ch in self.rules.get("chapters", []):
            if era in ch["eras"]:
                return ch["id"]
        return 0

    def event_chapter(self, ev):
        return ev["chapter"] if "chapter" in ev else self.era_chapter(ev["era"])

    def era_open(self, era):
        return self.era_chapter(era) <= self.release()

    def event_open(self, ev):
        return not ev.get("draft") and self.event_chapter(ev) <= self.release()

    def loop_open(self):
        loops = [ch["id"] for ch in self.rules.get("chapters", []) if ch.get("loop")]
        return not loops or min(loops) <= self.release()


_CONTENT = None


def content() -> Content:
    global _CONTENT
    if _CONTENT is None:
        _CONTENT = Content()
    return _CONTENT


# ══════════════════════════════════════════════════════════════
# 진행
# ══════════════════════════════════════════════════════════════
def privileged(run):
    """이번 생애의 당신이 그 나라의 기득권인지."""
    c, res = run.get("country"), run.get("res")
    return (c == "arcadia" and res == "res") or (c == "nova" and res == "non")


def _fmt(text, run):
    """이야기 속 {조국} · {이웃} · {적} 자리를 채웁니다."""
    c = run.get("country") or ""
    home = COUNTRIES.get(c, "조국")
    other = COUNTRIES["nova" if c == "arcadia" else "arcadia"] if c in COUNTRIES else "이웃 나라"
    f = run.get("faction") or ""
    enemy = (FACTIONS[1] if f == FACTIONS[0] else FACTIONS[0]) if f in FACTIONS else "적"
    return text.replace("{조국}", home).replace("{이웃}", other).replace("{적}", enemy)


def _mood(v, rows):
    for x in rows:
        if v >= x["min"]:
            return x["text"]
    return []


def _cond_ok(ev, run):
    c = ev.get("cond") or {}
    if c.get("res") and c["res"] != run["res"]:
        return False
    if c.get("country") and c["country"] != run.get("country"):
        return False
    tags = set(run["tags"])
    if c.get("tags") and not tags.intersection(c["tags"]):
        return False
    if c.get("no_tags") and tags.intersection(c["no_tags"]):
        return False
    if c.get("loops") and run["loop_no"] < c["loops"]:
        return False
    for k, v in (c.get("min") or {}).items():
        if run.get(k, 0) < v:
            return False
    return True


def _talent_name(run):
    """재능과 기술은 같은 능력치 : 아르카디아에서는 '재능', 노바에서는 '기술'."""
    return "기술" if run.get("country") == "nova" else "재능"


RES_NAME = {"wealth": "재산", "intel": "지능", "strain": "균열 압력"}


def _res_name(k, run):
    return _talent_name(run) if k == "talent" else RES_NAME[k]


def _when_ok(when, run):
    if when.get("tag") and when["tag"] not in run["tags"]:
        return False
    if "hp_lte" in when and run["hp"] > when["hp_lte"]:
        return False
    if "mind_lte" in when and run.get("mind", 0) > when["mind_lte"]:
        return False
    if "loops" in when and run["loop_no"] < when["loops"]:
        return False
    return True


class LoopBook:
    def __init__(self, path=RUNS_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.data = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.data = d if isinstance(d, dict) else {}
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        safeio.write_json(self.path, self.data, indent=1)

    def _entry(self, name):
        return self.data.setdefault(name, {"run": None, "lives": [], "loops": 0})

    # ── 진행 ──────────────────────────────────────────────
    def start(self, name, res, faction="", country=None):
        """새 생애. 출신 국가는 생애마다 무작위(시험용으로만 country를 넘깁니다)."""
        if res not in RESONANCE:
            raise LoopError("공명 여부를 골라 주세요.")
        with self.lock:
            e = self._entry(name)
            if e["run"] and e["run"]["status"] not in ("ended",):
                raise LoopError("이미 진행 중인 생애가 있어요.")
            e["run"] = self._new_run(res, loop_no=0, eras=content().rules["first_life"], life_no=len(e["lives"]) + 1)
            e["run"]["country"] = country if country in COUNTRIES else random.choice(list(COUNTRIES))
            e["run"]["faction"] = COUNTRY_FACTION[e["run"]["country"]]
            st = content().res_rules()["start"][e["run"]["country"]]["priv" if privileged(e["run"]) else "non"]
            for k in RESOURCES:
                e["run"][k] = random.randint(st[k][0], st[k][1])
            e["run"][STRAIN] = 0
            views = content().texts["views"]
            view = random.choice([v for v in views if v.get("country", "") in ("", e["run"]["country"])] or views)
            e["run"]["view"] = view["id"]
            if view.get("tag"):
                e["run"]["tags"].append(view["tag"])
            e["run"]["status"] = "prologue"   # 역사 · 탄생 나레이션을 먼저 보여 주고, '삶을 시작한다'를 누르면 첫 사건
            self.save()

    def _new_run(self, res, loop_no, eras, life_no, tags=(), memory=None):
        r = content().rules
        return {"res": res, "hp": r["hp_start"], "mind": r["mind_start"], "eras": list(eras), "era_i": 0, "step": 0, "tags": list(tags),
                "seen": [], "log": [], "event": None, "status": "event", "result": None, "death": None,
                "loop_no": loop_no, "life_no": life_no, "memory": memory, "started": time.time(), "count": 0}

    def _pick(self, run, era):
        seen = set(run["seen"])
        C = content()
        pool = [ev for ev in C.events if ev["era"] == era and ev["id"] not in seen and C.event_open(ev) and _cond_ok(ev, run)]
        if run["step"] == 0:
            fixed = [ev for ev in pool if ev.get("fixed") == "open"]
            if fixed:
                return random.choice(fixed)
        pool = [ev for ev in pool if ev.get("fixed") != "open"] or pool
        return random.choice(pool) if pool else None

    def _next_event(self, run):
        """다음 사건을 고릅니다. 시대가 끝났거나 고를 사건이 없으면 다음 시대로, 마지막 시대가 끝나면 엔딩."""
        C = content()
        eras = C.eras
        run["paused"] = False
        while run["era_i"] < len(run["eras"]):
            era = run["eras"][run["era_i"]]
            if era in eras and not C.era_open(era):
                # 아직 공개되지 않은 시대 : 여기서 잠시 멈춤 엔딩(다음 패치가 열리면 이어서 살 수 있어요)
                run["event"] = None
                run["status"] = "ending"
                run["paused"] = True
                return
            if era in eras and run["step"] < eras[era]["len"]:
                ev = self._pick(run, era)
                if ev:
                    run["event"] = ev["id"]
                    run["seen"].append(ev["id"])
                    run["status"] = "event"
                    run["result"] = None
                    return
            run["era_i"] += 1
            run["step"] = 0
        run["event"] = None
        run["status"] = "ending"

    def _repair(self, run):
        """운영진이 진행 중인 사건을 지웠거나 시대를 바꿨으면, 고르기 전 상태의 사건만 새로 뽑아 줍니다."""
        if run and run["status"] == "event" and run["event"] not in content().by_id:
            if run["event"] in run["seen"]:
                run["seen"].remove(run["event"])
            self._next_event(run)
            return True
        return False

    def choose(self, name, event_id, idx):
        with self.lock:
            run = self._entry(name)["run"]
            if self._repair(run):
                self.save()
                raise LoopError("운영진이 사건을 고쳐서 새 사건을 불러왔어요.")
            if not run or run["status"] != "event" or run["event"] != event_id:
                raise LoopError("지금 고를 수 있는 사건이 아니에요. 화면을 새로 불러올게요.")
            C = content()
            ev = C.by_id[event_id]
            if not isinstance(idx, int) or not 0 <= idx < len(ev["choices"]):
                raise LoopError("선택지를 다시 골라 주세요.")
            ch = ev["choices"][idx]
            for k, v in (ch.get("need") or {}).items():
                if run.get(k, 0) < v:
                    raise LoopError(f"{_res_name(k, run)}이(가) {v} 이상이어야 고를 수 있어요.")
            rmax, smax = C.res_rules()["max"], C.strain_rules()["max"]
            gained = {}
            for k, v in (ch.get("gain") or {}).items():
                b = run.get(k, 0)
                run[k] = max(0, min(smax if k == STRAIN else rmax, b + v))
                if run[k] != b:
                    gained[k] = run[k] - b
            hp_max, mind_max = C.rules["hp_max"], C.rules["mind_max"]
            before, mbefore = run["hp"], run.get("mind", C.rules["mind_start"])
            run["hp"] = max(HP_MIN, min(hp_max, before + ch["hp"]))
            run["mind"] = max(0, min(mind_max, mbefore + ch.get("mind", 0)))
            for t in ch.get("tags", []):
                if t not in run["tags"]:
                    run["tags"].append(t)
            text = [_fmt(t, run) for t in ch["result"].split("\n") if t.strip()]
            for x in ev.get("extra", []):
                if x.get("at") == "result" and x.get("choice") == idx and _when_ok(x.get("when", {}), run):
                    text += [_fmt(t, run) for t in x["text"]]
            # 시대의 위험 / 행운 : 선택과 상관없이 덮치는 일(위험 문장마다 체력 또는 정신). 이미 쓰러진 경우는 건너뜁니다.
            twist = None
            era = C.eras.get(ev["era"]) or {}
            if run["hp"] > HP_MIN and run["mind"] > 0:
                roll = random.random()
                purge = min(0.6, run.get(STRAIN, 0) * C.strain_rules()["per"])   # 지구의 반발 : 쌓인 압력만큼 재난이 더 잦아요
                if roll < purge:
                    run["hp"] = max(0, run["hp"] - 1)
                    twist = {"kind": "purge", "stat": "hp", "text": _fmt(random.choice(C.texts["purge"]), run)}
                    roll = 2  # 재난이 왔으면 시대의 위험 · 행운은 건너뜁니다
                else:
                    roll = (roll - purge) / max(1e-9, 1 - purge)
                if roll < era.get("risk", 0):
                    rt = random.choice(era.get("risk_text") or [{"stat": "hp", "text": "예기치 못한 일이 겹쳤다."}])
                    run[rt["stat"]] = max(0, run[rt["stat"]] - 1)
                    twist = {"kind": "risk", "stat": rt["stat"], "text": _fmt(rt["text"], run)}
                elif roll < era.get("risk", 0) + era.get("luck", 0):
                    room = [k for k, mx in (("hp", hp_max), ("mind", mind_max)) if run[k] < mx]
                    if room:
                        stat = min(room, key=lambda k: run[k])   # 더 모자란 쪽을 채워요
                        run[stat] += 1
                        twist = {"kind": "luck", "stat": stat, "text": _fmt(random.choice(C.texts["luck"][stat]), run)}
            dh, dm = run["hp"] - before, run["mind"] - mbefore
            run["result"] = {"choice": idx, "delta": dh, "dmind": dm, "twist": twist, "text": text, "gain": gained,
                             "title": ev["title"], "label": _fmt(ch["label"], run)}
            run["log"].append({"id": ev["id"], "title": ev["title"], "era": ev["era"], "choice": _fmt(ch["label"], run),
                               "delta": dh, "dmind": dm, "gain": gained, "hp": run["hp"], "mind": run["mind"]})
            run["step"] += 1
            run["count"] += 1
            if run["hp"] <= HP_MIN or run["mind"] <= 0:
                run["status"] = "dead"
                kind = ev.get("kind", "life") if run["hp"] <= HP_MIN else "mind"
                if ("LOOP_CONTACT" in run["tags"] or run["loop_no"] > 0) and C.loop_open():
                    kind = "loop" if kind == "life" or (kind != "mind" and random.random() < 0.5) else kind
                run["death"] = {"kind": kind if kind in DEATH_KINDS else "life", "at": ev["title"], "era": ev["era"]}
            else:
                run["status"] = "result"
            self.save()

    def resume(self, name):
        """잠시 멈춤 엔딩에서, 다음 챕터가 공개되었으면 그 자리에서 이어서 살기."""
        with self.lock:
            run = self._entry(name)["run"]
            if not run or run["status"] != "ending" or not run.get("paused"):
                raise LoopError("이어서 살 수 있는 생애가 아니에요.")
            era = run["eras"][run["era_i"]] if run["era_i"] < len(run["eras"]) else None
            if era is None or not content().era_open(era):
                raise LoopError("다음 이야기는 아직 공개되지 않았어요.")
            self._next_event(run)
            self.save()

    def begin(self, name):
        """프롤로그를 다 읽고 첫 사건으로."""
        with self.lock:
            run = self._entry(name)["run"]
            if not run or run["status"] != "prologue":
                raise LoopError("지금은 시작할 수 없어요.")
            self._next_event(run)
            self.save()

    def solve_costs(self, run, ev=None):
        """이 사건을 재산 · 지능으로 '해결'할 수 있으면 {자원: 값}. 전쟁 전 시대에서만, 값이 0이면 그 자원은 못 써요."""
        C = content()
        ev = ev or C.by_id.get(run.get("event"))
        rr = C.res_rules()
        if not ev or ev["era"] not in rr.get("solve_eras", []) or run.get("country") not in rr["cost"]:
            return {}
        return {k: v for k, v in rr["cost"][run["country"]].items() if v > 0}

    def solve(self, name, event_id, kind):
        """재산 · 지능을 써서 사건을 해결 : 체력 · 정신 변화 없이, 시대의 위험도 피해서 넘어갑니다."""
        with self.lock:
            run = self._entry(name)["run"]
            if not run or run["status"] != "event" or run["event"] != event_id:
                raise LoopError("지금 해결할 수 있는 사건이 아니에요. 화면을 새로 불러올게요.")
            C = content()
            ev = C.by_id.get(event_id)
            costs = self.solve_costs(run, ev)
            if kind not in costs:
                raise LoopError("이 사건은 그렇게 해결할 수 없어요.")
            cost = costs[kind]
            if run.get(kind, 0) < cost:
                raise LoopError(f"{RES_NAME[kind]}이(가) 모자라요.")
            run[kind] -= cost
            text = [_fmt(random.choice(C.texts["solve"][kind]), run)]
            label = f"{RES_NAME[kind]} {cost}을(를) 써서 해결했다."
            run["result"] = {"choice": -1, "solved": kind, "cost": cost, "delta": 0, "dmind": 0, "twist": None, "text": text,
                             "gain": {kind: -cost}, "title": ev["title"], "label": label}
            run["log"].append({"id": ev["id"], "title": ev["title"], "era": ev["era"], "choice": label, "solved": kind,
                               "delta": 0, "dmind": 0, "gain": {kind: -cost}, "hp": run["hp"], "mind": run["mind"]})
            run["step"] += 1
            run["count"] += 1
            run["status"] = "result"
            self.save()

    def next(self, name):
        with self.lock:
            run = self._entry(name)["run"]
            if not run or run["status"] != "result":
                raise LoopError("다음 사건으로 넘어갈 수 없어요.")
            self._next_event(run)
            self.save()

    def _archive(self, e, run, outcome):
        era_last = run["log"][-1]["era"] if run["log"] else run["eras"][0]
        e["lives"].insert(0, {"life_no": run["life_no"], "loop_no": run["loop_no"], "res": run["res"], "country": run.get("country", ""), "view": run.get("view"), "outcome": outcome,
                              "count": run["count"], "era": era_last, "hp": run["hp"], "mind": run.get("mind"),
                              "death": run.get("death"), "log": run["log"], "ended": time.time()})
        del e["lives"][MAX_LIVES:]

    def after_death(self, name, mode):
        with self.lock:
            e = self._entry(name)
            run = e["run"]
            if not run or run["status"] != "dead":
                raise LoopError("지금은 고를 수 없어요.")
            if mode == "loop" and not content().loop_open():
                raise LoopError("루프는 아직 공개되지 않았어요.")
            self._archive(e, run, "dead")
            if mode == "loop":
                e["loops"] = e.get("loops", 0) + 1
                tags = [t for t in run["tags"] if t in LOOP_KEEP_TAGS] + ["LOOP_CONTACT"]
                memory = run["death"]["at"] if run.get("death") else None
                e["run"] = self._new_run(run["res"], loop_no=run["loop_no"] + 1, eras=content().rules["loop_life"],
                                         life_no=run["life_no"], tags=sorted(set(tags)), memory=memory)
                e["run"]["country"] = run.get("country", "")
                e["run"]["faction"] = run.get("faction", "")
                for k in RESOURCES:
                    e["run"][k] = run.get(k, 0)
                e["run"][STRAIN] = int(run.get(STRAIN, 0) * content().strain_rules()["loop_keep"])
                e["run"]["view"] = run.get("view")
                self._next_event(e["run"])
            else:
                run["status"] = "ended"
                run["outcome"] = "dead"
            self.save()

    def finish(self, name):
        """엔딩을 본 뒤 생애를 마칩니다(기록으로 남김)."""
        with self.lock:
            e = self._entry(name)
            run = e["run"]
            if not run or run["status"] != "ending":
                raise LoopError("아직 엔딩에 도달하지 않았어요.")
            self._archive(e, run, "paused" if run.get("paused") else "survived")
            run["status"] = "ended"
            run["outcome"] = "paused" if run.get("paused") else "survived"
            self.save()

    def reset(self, name):
        """새 생애 : 끝난 생애를 치우고 시작 화면으로."""
        with self.lock:
            e = self._entry(name)
            if e["run"] and e["run"]["status"] not in ("ended",):
                raise LoopError("진행 중인 생애는 끝까지 가야 해요.")
            e["run"] = None
            self.save()

    def gm_clear(self, name):
        with self.lock:
            if name in self.data:
                self.data[name]["run"] = None
                self.save()

    # ── 화면에 보낼 자료 ─────────────────────────────────────
    @staticmethod
    def _birth_lines(run):
        """탄생 나레이션 : 출신 국가 · 공명 여부 · 기득권 · 자원으로 짜 맞춥니다."""
        b = content().texts["birth"]
        out = [b.get(run.get("country"), "")]
        out.append(b[("res" if run["res"] == "res" else "non") + ("_priv" if privileged(run) else "_non")])
        w, i, t = run.get("wealth", 0), run.get("intel", 0), run.get("talent", 0)
        home = "집은 넉넉했다." if w >= 2 else "집은 그럭저럭 먹고살 만했다." if w == 1 else "집은 가난했다."
        mind = "또래보다 셈이 빠르고 눈치가 밝은 아이였다." if i >= 2 else "평범하게 영리한 아이였다." if i == 1 else "책보다 몸이 먼저 움직이는 아이였다."
        tal = _talent_name(run)
        hand = f"{tal}은 일찍부터 남달랐다." if t >= 2 else f"{tal}은 아직 드러나지 않았다." if t == 1 else f"{tal}이라 부를 만한 것은 없었다."
        out.append(f"{home} 당신은 {mind} {hand}")
        return [_fmt(x, run) for x in out if x]

    @staticmethod
    def _era_view(era):
        x = content().eras.get(era) or {"no": str(era), "name": "", "period": "", "level": ""}
        return {"id": era, "no": x["no"], "name": x["name"], "period": x["period"], "level": x["level"]}

    def _event_view(self, run):
        ev = content().by_id.get(run["event"])
        if ev is None:
            # 고른 뒤에 운영진이 그 사건을 지웠으면 결과에 남겨 둔 제목 · 선택만 보여 줍니다.
            r = run.get("result") or {}
            return {"id": run["event"], "title": r.get("title", ""), "era": self._era_view(run["eras"][min(run["era_i"], len(run["eras"]) - 1)]),
                    "story": [], "choices": [{"label": r.get("label", ""), "picked": True}] * 3}
        story = list(ev["story"])
        for x in ev.get("extra", []):
            if x.get("at") == "story" and _when_ok(x.get("when", {}), run):
                story += x["text"]
        story = [_fmt(t, run) for t in story]
        # 체력 변동은 고른 뒤에만 : 고르기 전에는 선택지 문장만 보냅니다.
        choices = []
        for c in ev["choices"]:
            item = {"label": _fmt(c["label"], run)}
            if c.get("need"):
                item["need"] = [{"k": k, "name": _res_name(k, run), "v": v, "ok": run.get(k, 0) >= v} for k, v in c["need"].items()]
            choices.append(item)
        if run["result"] is not None and 0 <= run["result"].get("choice", -1) < len(choices):
            choices[run["result"]["choice"]]["picked"] = True
        return {"id": ev["id"], "title": ev["title"], "era": self._era_view(ev["era"]), "story": story, "choices": choices}

    def view(self, name):
        with self.lock:
            C = content()
            e = self._entry(name) if name in self.data else {"run": None, "lives": [], "loops": 0}
            run = e["run"]
            if self._repair(run):
                self.save()
            out = {"intro": C.texts["intro"], "hp_max": C.rules["hp_max"], "mind_max": C.rules["mind_max"], "loops": e.get("loops", 0),
                   "lives": [{k: l.get(k) for k in ("life_no", "loop_no", "res", "country", "outcome", "count", "era", "hp", "mind", "death", "log", "ended")} for l in e["lives"][:MAX_LIVES]],
                   "eras": [self._era_view(i) for i in C.eras], "run": None}
            if not run:
                return out
            r = {"status": run["status"], "hp": run["hp"], "mind": run.get("mind", C.rules["mind_start"]), "res": run["res"],
                 "country": run.get("country", ""), "faction": run.get("faction", ""), "privileged": privileged(run),
                 "loop_no": run["loop_no"], "life_no": run["life_no"], "count": run["count"], "log": run["log"],
                 "mood": _mood(run["hp"], C.texts["mood_hp"]), "mood_mind": _mood(run.get("mind", 0), C.texts["mood_mind"]),
                 "eras": run["eras"], "memory": run.get("memory"),
                 "assets": {k: run.get(k, 0) for k in RESOURCES}, "res_max": C.res_rules()["max"], "talent_name": _talent_name(run),
                 "strain": run.get(STRAIN, 0), "strain_max": C.strain_rules()["max"]}
            view = next((v for v in C.texts["views"] if v["id"] == run.get("view")), None)
            if view:
                r["view"] = {"name": view["name"]}
            if run["status"] == "prologue":
                r["prologue"] = {"history": C.texts["history"], "birth": self._birth_lines(run), "view": view["text"] if view else []}
            era_now = run["eras"][min(run["era_i"], len(run["eras"]) - 1)]
            r["era"] = self._era_view(era_now)
            r["era_step"] = run["step"]
            r["era_len"] = (C.eras.get(era_now) or {}).get("len", 1)
            if run["status"] in ("event", "result", "dead") and run["event"]:
                r["event"] = self._event_view(run)
            if run["result"] is not None and run["status"] in ("result", "dead"):
                r["result"] = {k: run["result"].get(k) for k in ("choice", "delta", "dmind", "twist", "text", "gain", "solved", "cost")}
            if run["status"] == "event":
                r["solve"] = [{"k": k, "name": RES_NAME[k], "cost": v, "ok": run.get(k, 0) >= v} for k, v in self.solve_costs(run).items()]
            if run["status"] == "dead" and run.get("death"):
                d = C.texts["death"].get(run["death"]["kind"]) or C.texts["death"]["life"]
                r["death"] = {"title": d["title"], "text": d["text"], "at": run["death"]["at"], "kind": run["death"]["kind"]}
            if run["status"] == "ending" or (run["status"] == "ended" and run.get("outcome") in ("survived", "paused")):
                key = "pause" if run.get("paused") or run.get("outcome") == "paused" else "loop" if run["loop_no"] else "first"
                x = C.texts["ending"].get(key) or C.texts["ending"]["first"]
                r["ending"] = {"title": x["title"], "text": x["text"], "paused": key == "pause"}
                if run["status"] == "ending" and run.get("paused"):
                    era = run["eras"][run["era_i"]] if run["era_i"] < len(run["eras"]) else None
                    r["can_resume"] = bool(era and C.era_open(era))
            r["loop_open"] = C.loop_open()
            r["closed_eras"] = [e for e in run["eras"] if not C.era_open(e)]
            if run["status"] == "ended":
                r["outcome"] = run.get("outcome")
            out["run"] = r
            return out


_BOOK = None


def shared_book() -> LoopBook:
    global _BOOK
    if _BOOK is None:
        _BOOK = LoopBook()
    return _BOOK
