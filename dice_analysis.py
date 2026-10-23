# -*- coding: utf-8 -*-
"""
dice_analysis.py
================
운영진 '성능 분석' 탭 : 캐릭터마다 실제 전투와 같은 굴림 함수(config.roll_attack · roll_defense · roll_heal)를
여러 번 굴려 보고, 다이스 값이 어느 정도로 나오는지(평균 · 범위 · 치명타 · 분포)를 정리합니다.
이 방 전투 유형의 수식 값(프로필)을 그대로 씁니다. 아이템 · 버프 같은 전투 중 변화는 넣지 않아요.
수식이 담긴 결과라 운영진에게만 보냅니다.
"""

import math
import random

import config

SAMPLES = 1500   # 캐릭터마다 굴려 보는 횟수(많을수록 정확하지만 느려요)
BINS = 14


def _summary(values):
    v = sorted(values)
    n = len(v)
    q = lambda p: v[min(n - 1, max(0, int(round(p * (n - 1)))))]
    return {"min": v[0], "max": v[-1], "avg": round(sum(v) / n, 1), "p10": q(.1), "p50": q(.5), "p90": q(.9)}


def _hist(values, lo, hi, bins=BINS):
    """lo~hi를 bins칸으로 나눠 칸마다 몇 %가 나왔는지(막대 그래프용)."""
    if hi <= lo:
        return {"lo": lo, "hi": hi, "bars": [100.0]}
    w = (hi - lo) / bins
    counts = [0] * bins
    for x in values:
        counts[min(bins - 1, int((x - lo) / w))] += 1
    n = len(values)
    return {"lo": lo, "hi": hi, "bars": [round(c * 100 / n, 1) for c in counts]}


def _sample(fn, n):
    out, crit = [], 0
    for _ in range(n):
        r = fn()
        out.append(r["total"])
        crit += 1 if r.get("is_crit") else 0
    return out, round(crit * 100 / n, 1)


def reroll_effect(stats, overrides=None):
    """정신 재굴림 효과(정확한 계산) : 다이스 하나가 기준치 이하로 나와 다시 굴릴 확률,
    다시 굴림이 없을 때와 있을 때 다이스 하나의 평균, 그리고 중간값."""
    ability = int(stats.get("이능", 0))
    mental = int(stats.get("정신", 0))
    S = int(config.get_value("BASE_DICE_SIDES", overrides) + ability * config.get_value("ABILITY_BONUS", overrides))
    T = mental * config.get_value("MENTAL_FLOOR_MULTIPLIER", overrides)
    T = int(T) if float(T).is_integer() else round(T, 2)
    k = max(1, int(config.get_value("MENTAL_REROLL_COUNT", overrides)))
    # 다이스 하나의 최종 값 분포 : r > T면 그대로, r <= T면 max(r, k번 굴린 값)
    p = [0.0] * (S + 1)
    for r in range(1, S + 1):
        if r > T:
            p[r] += 1 / S
        else:
            for v in range(1, S + 1):   # max(r, k번 중 최대)가 v일 확률
                if v < r:
                    continue
                cdf = lambda x: (min(max(x, 0), S) / S) ** k
                pv = cdf(v) if v == r else cdf(v) - cdf(v - 1)
                p[v] += pv / S
    avg = sum(v * p[v] for v in range(1, S + 1))
    acc, med = 0.0, S
    for v in range(1, S + 1):
        acc += p[v]
        if acc >= .5:
            med = v
            break
    return {"sides": S, "threshold": T, "rerolls": k, "chance": round(min(T, S) / S * 100, 1),
            "plain_avg": round((S + 1) / 2, 2), "avg": round(avg, 2), "median": med,
            "plain_median": (S + 1) // 2 if S % 2 else S // 2, "gain": round(avg - (S + 1) / 2, 2)}


def analyze_one(name, entry, overrides=None, n=SAMPLES, rng_seed=None):
    if rng_seed is not None:
        random.seed(rng_seed)
    stats = dict((entry or {}).get("stats") or {})
    role = (entry or {}).get("role") or None
    atk_vals, atk_crit = _sample(lambda: config.roll_attack(stats, role=role, overrides=overrides), n)
    dfn_vals, dfn_crit = _sample(lambda: config.roll_defense(stats, True, grantor_stats=stats, grantor_role=role, overrides=overrides), n)
    heal_vals, heal_crit = _sample(lambda: config.roll_heal(stats, role=role, overrides=overrides), n)
    one_atk = config.roll_attack(stats, role=role, overrides=overrides)
    one_heal = config.roll_heal(stats, role=role, overrides=overrides)
    passive = config.roll_defense(stats, False, overrides=overrides)["total"]
    dodge = config.roll_dodge(stats, overrides=overrides)["chance"]
    res = {
        "name": name, "role": role or "", "mob": bool((entry or {}).get("mob")), "stats": stats,
        "hp": config.calculate_max_hp(stats, overrides=overrides),
        "move": config.calculate_move_range(stats, overrides=overrides),
        "dice": {"sides": one_atk["dice_sides"], "atk_count": one_atk["dice_count"], "heal_count": one_heal["dice_count"],
                 "def_count": int(config.get_value("DEFENSE_DICE_COUNT", overrides)),
                 "reroll_at": one_atk["mental_threshold"]},
        "atk": dict(_summary(atk_vals), crit=atk_crit, crit_mult=one_atk["crit_mult"], crit_on=one_atk["position_match"]),
        "def": dict(_summary(dfn_vals), crit=dfn_crit, passive=passive),
        "heal": dict(_summary(heal_vals), crit=heal_crit, crit_on=one_heal["position_match"]),
        "dodge": dodge,
        "reroll": reroll_effect(stats, overrides),
    }
    res["atk"]["hist"] = _hist(atk_vals, res["atk"]["min"], res["atk"]["max"])
    res["def"]["hist"] = _hist(dfn_vals, res["def"]["min"], res["def"]["max"])
    res["heal"]["hist"] = _hist(heal_vals, res["heal"]["min"], res["heal"]["max"])
    return res


def matchup(att_entry, tgt_entry, overrides=None, n=SAMPLES):
    """공격자가 대상을 칠 때 : 대상이 방어 안 함(수동) · 스스로 방어(능동)일 때 평균 피해와 쓰러뜨리는 데 드는 타수."""
    a_stats, a_role = dict(att_entry.get("stats") or {}), att_entry.get("role") or None
    t_stats, t_role = dict(tgt_entry.get("stats") or {}), tgt_entry.get("role") or None
    hp = config.calculate_max_hp(t_stats, overrides=overrides)
    out = {"hp": hp}
    for key, active in (("passive", False), ("active", True)):
        dmg = []
        for _ in range(n):
            a = config.roll_attack(a_stats, role=a_role, overrides=overrides)["total"]
            d = config.roll_defense(t_stats, active, grantor_stats=t_stats, grantor_role=t_role, overrides=overrides)["total"]
            dmg.append(config.calculate_final_damage(a, d, overrides=overrides))
        s = _summary(dmg)
        s["hits"] = math.ceil(hp / s["avg"]) if s["avg"] > 0 else None
        out[key] = s
    out["dodge"] = config.roll_dodge(t_stats, overrides=overrides)["chance"]
    return out
