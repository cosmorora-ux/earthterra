# -*- coding: utf-8 -*-
"""
loop_game.py
============
PLAY 룸 「LOOP : 생존 시뮬레이션」 진행 상태.

- 캐릭터마다 지금 생애(run) 하나와 지난 생애 기록(lives)을 가집니다. 모든 PLAY 룸이 같은 기록을 씁니다.
- 체력과 정신은 각각 5로 시작해 0~5 사이를 오갑니다. 체력이 0이면 사망, 정신이 0이면 정신 붕괴입니다.
- 출신 국가(아르카디아 / 노바)와 공명 여부로 기득권 · 비기득권이 갈리고, 시대 I · II 사건이 달라집니다.
- 진영(使徒 / Void)은 전쟁 때의 포지션이고 서로 적입니다.
- 시대 I → V 순서로 사건이 이어지고, V의 사건을 모두 견디면 '전쟁 이후' 엔딩입니다.
- 죽으면 '생애 종료'(기록만 남김) 또는 '루프 진입'(VI. 회귀 → IV. 전쟁 → V. 종전으로 다시)을 고릅니다.
- 체력 · 정신 변동은 고른 뒤에만 알려 줍니다(고르기 전 화면에는 선택지 문장만 보냅니다).
loop_runs.json에 저장됩니다(서버 컴퓨터별 실데이터라 git에 올리지 않음).
"""

import json
import os
import random
import threading
import time

import safeio
from loop_events import ERAS, EVENTS, MOOD, MOOD_MIND, DEATH, ENDING, INTRO, ERA_RISK, RISK_TEXT, LUCK_TEXT

RUNS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop_runs.json")
HP_START, HP_MAX, HP_MIN = 5, 5, 0
MIND_START, MIND_MAX = 5, 5   # 정신 : 0이 되면 무너집니다(정신 붕괴)
MAX_LIVES = 30            # 캐릭터마다 남기는 지난 생애 수
RESONANCE = ("res", "non")
EVENT_BY_ID = {e["id"]: e for e in EVENTS}
FIRST_LIFE_ERAS = [1, 2, 3, 4, 5]
LOOP_LIFE_ERAS = [6, 4, 5]
# 루프를 넘어가도 남는 태그(나머지 기억은 흐려집니다)
LOOP_KEEP_TAGS = {"LOOP_CONTACT", "LOOP_NOTES", "LOOP_ALLY", "TRUTH", "FRACTURE_SEEN", "LEFT_BEHIND", "KILLED", "SAVED_ONE"}


class LoopError(Exception):
    pass


# 출신 국가 : 아르카디아에서는 공명자가 기득권, 노바에서는 비공명자가 기득권.
COUNTRIES = {"arcadia": "아르카디아", "nova": "노바"}
# 진영 : 전쟁 때의 포지션. 서로 적입니다.
FACTIONS = ("使徒", "Void")


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


def _mood(v, table=MOOD):
    for limit, lines in table:
        if v >= limit:
            return lines
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
    return True


def _when_ok(when, run):
    if "tag" in when and when["tag"] not in run["tags"]:
        return False
    if "hp_lte" in when and run["hp"] > when["hp_lte"]:
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
    def start(self, name, res, country="", faction=""):
        if res not in RESONANCE:
            raise LoopError("공명 여부를 골라 주세요.")
        if country not in COUNTRIES:
            raise LoopError("출신 국가를 골라 주세요.")
        with self.lock:
            e = self._entry(name)
            if e["run"] and e["run"]["status"] not in ("ended",):
                raise LoopError("이미 진행 중인 생애가 있어요.")
            e["run"] = self._new_run(res, loop_no=0, eras=FIRST_LIFE_ERAS, life_no=len(e["lives"]) + 1)
            e["run"]["country"] = country
            e["run"]["faction"] = faction if faction in FACTIONS else ""
            self._next_event(e["run"])
            self.save()

    def _new_run(self, res, loop_no, eras, life_no, tags=(), memory=None):
        return {"res": res, "hp": HP_START, "mind": MIND_START, "eras": list(eras), "era_i": 0, "step": 0, "tags": list(tags),
                "seen": [], "log": [], "event": None, "status": "event", "result": None, "death": None,
                "loop_no": loop_no, "life_no": life_no, "memory": memory, "started": time.time(), "count": 0}

    def _pick(self, run, era):
        seen = set(run["seen"])
        pool = [ev for ev in EVENTS if ev["era"] == era and ev["id"] not in seen and _cond_ok(ev, run)]
        if run["step"] == 0:
            fixed = [ev for ev in pool if ev.get("fixed") == "open"]
            if fixed:
                return random.choice(fixed)
        pool = [ev for ev in pool if ev.get("fixed") != "open"] or pool
        return random.choice(pool) if pool else None

    def _next_event(self, run):
        """다음 사건을 고릅니다. 시대가 끝났거나 고를 사건이 없으면 다음 시대로, 마지막 시대가 끝나면 엔딩."""
        while run["era_i"] < len(run["eras"]):
            era = run["eras"][run["era_i"]]
            if run["step"] < ERAS[era]["len"]:
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

    def choose(self, name, event_id, idx):
        with self.lock:
            run = self._entry(name)["run"]
            if not run or run["status"] != "event" or run["event"] != event_id:
                raise LoopError("지금 고를 수 있는 사건이 아니에요. 화면을 새로 불러올게요.")
            ev = EVENT_BY_ID[event_id]
            if not isinstance(idx, int) or not 0 <= idx < len(ev["choices"]):
                raise LoopError("선택지를 다시 골라 주세요.")
            ch = ev["choices"][idx]
            before, mbefore = run["hp"], run.get("mind", MIND_START)
            run["hp"] = max(HP_MIN, min(HP_MAX, before + ch["hp"]))
            run["mind"] = max(0, min(MIND_MAX, mbefore + ch.get("mind", 0)))
            for t in ch.get("tags", []):
                if t not in run["tags"]:
                    run["tags"].append(t)
            text = [_fmt(t, run) for t in ch["result"].split("\n")]
            for x in ev.get("extra", []):
                if x.get("at") == "result" and x.get("choice") == idx and _when_ok(x.get("when", {}), run):
                    text += [_fmt(t, run) for t in x["text"]]
            # 시대의 위험 / 행운 : 선택과 상관없이 덮치는 일(위험 문장마다 체력 또는 정신). 이미 쓰러진 경우는 건너뜁니다.
            twist = None
            if run["hp"] > HP_MIN and run["mind"] > 0:
                risk, luck = ERA_RISK.get(ev["era"], (0, 0))
                roll = random.random()
                if roll < risk:
                    stat, line = random.choice(RISK_TEXT.get(ev["era"]) or [("hp", "예기치 못한 일이 겹쳤다.")])
                    run[stat] = max(0, run[stat] - 1)
                    twist = {"kind": "risk", "stat": stat, "text": line}
                elif roll < risk + luck:
                    room = [k for k, mx in (("hp", HP_MAX), ("mind", MIND_MAX)) if run[k] < mx]
                    if room:
                        stat = min(room, key=lambda k: run[k])   # 더 모자란 쪽을 채워요
                        run[stat] += 1
                        twist = {"kind": "luck", "stat": stat, "text": random.choice(LUCK_TEXT[stat])}
            dh, dm = run["hp"] - before, run["mind"] - mbefore
            run["result"] = {"choice": idx, "delta": dh, "dmind": dm, "twist": twist, "text": text}
            run["log"].append({"id": ev["id"], "title": ev["title"], "era": ev["era"], "choice": _fmt(ch["label"], run),
                               "delta": dh, "dmind": dm, "hp": run["hp"], "mind": run["mind"]})
            run["step"] += 1
            run["count"] += 1
            if run["hp"] <= HP_MIN or run["mind"] <= 0:
                run["status"] = "dead"
                kind = ev.get("kind", "life") if run["hp"] <= HP_MIN else "mind"
                if "LOOP_CONTACT" in run["tags"] or run["loop_no"] > 0:
                    kind = "loop" if kind == "life" or (kind != "mind" and random.random() < 0.5) else kind
                run["death"] = {"kind": kind if kind in DEATH else "life", "at": ev["title"], "era": ev["era"]}
            else:
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
        e["lives"].insert(0, {"life_no": run["life_no"], "loop_no": run["loop_no"], "res": run["res"], "country": run.get("country", ""), "outcome": outcome,
                              "count": run["count"], "era": era_last, "hp": run["hp"], "mind": run.get("mind"),
                              "death": run.get("death"), "log": run["log"], "ended": time.time()})
        del e["lives"][MAX_LIVES:]

    def after_death(self, name, mode):
        with self.lock:
            e = self._entry(name)
            run = e["run"]
            if not run or run["status"] != "dead":
                raise LoopError("지금은 고를 수 없어요.")
            self._archive(e, run, "dead")
            if mode == "loop":
                e["loops"] = e.get("loops", 0) + 1
                tags = [t for t in run["tags"] if t in LOOP_KEEP_TAGS] + ["LOOP_CONTACT"]
                memory = run["death"]["at"] if run.get("death") else None
                e["run"] = self._new_run(run["res"], loop_no=run["loop_no"] + 1, eras=LOOP_LIFE_ERAS,
                                         life_no=run["life_no"], tags=sorted(set(tags)), memory=memory)
                e["run"]["country"] = run.get("country", "")
                e["run"]["faction"] = run.get("faction", "")
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
            self._archive(e, run, "survived")
            run["status"] = "ended"
            run["outcome"] = "survived"
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
    def _era_view(era):
        x = ERAS[era]
        return {"id": era, "no": x["no"], "name": x["name"], "period": x["period"], "level": x["level"]}

    def _event_view(self, run):
        ev = EVENT_BY_ID[run["event"]]
        story = list(ev["story"])
        for x in ev.get("extra", []):
            if x.get("at") == "story" and _when_ok(x.get("when", {}), run):
                story += x["text"]
        story = [_fmt(t, run) for t in story]
        # 체력 변동은 고른 뒤에만 : 고르기 전에는 선택지 문장만 보냅니다.
        choices = [{"label": _fmt(c["label"], run)} for c in ev["choices"]]
        if run["result"] is not None:
            choices[run["result"]["choice"]]["picked"] = True
        return {"id": ev["id"], "title": ev["title"], "era": self._era_view(ev["era"]), "story": story, "choices": choices}

    def view(self, name):
        with self.lock:
            e = self._entry(name) if name in self.data else {"run": None, "lives": [], "loops": 0}
            run = e["run"]
            out = {"intro": INTRO, "hp_max": HP_MAX, "hp_start": HP_START, "mind_max": MIND_MAX, "loops": e.get("loops", 0),
                   "lives": [{**{k: l.get(k) for k in ("life_no", "loop_no", "res", "country", "outcome", "count", "era", "hp", "mind", "death", "log", "ended")}} for l in e["lives"][:MAX_LIVES]],
                   "eras": [self._era_view(i) for i in sorted(ERAS)], "run": None}
            if not run:
                return out
            r = {"status": run["status"], "hp": run["hp"], "mind": run.get("mind", MIND_START), "res": run["res"], "country": run.get("country", ""), "faction": run.get("faction", ""), "privileged": privileged(run), "loop_no": run["loop_no"], "life_no": run["life_no"],
                 "count": run["count"], "log": run["log"], "mood": _mood(run["hp"]), "mood_mind": _mood(run.get("mind", MIND_START), MOOD_MIND), "eras": run["eras"], "memory": run.get("memory")}
            era_now = run["eras"][min(run["era_i"], len(run["eras"]) - 1)]
            r["era"] = self._era_view(era_now)
            r["era_step"] = run["step"]
            r["era_len"] = ERAS[era_now]["len"]
            if run["status"] in ("event", "result", "dead") and run["event"]:
                r["event"] = self._event_view(run)
            if run["result"] is not None and run["status"] in ("result", "dead"):
                r["result"] = {k: run["result"].get(k) for k in ("choice", "delta", "dmind", "twist", "text")}
            if run["status"] == "dead" and run.get("death"):
                d = DEATH[run["death"]["kind"]]
                r["death"] = {"title": d["title"], "text": d["text"], "at": run["death"]["at"], "kind": run["death"]["kind"]}
            if run["status"] == "ending" or (run["status"] == "ended" and run.get("outcome") == "survived"):
                x = ENDING["loop" if run["loop_no"] else "first"]
                r["ending"] = {"title": x["title"], "text": x["text"]}
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
