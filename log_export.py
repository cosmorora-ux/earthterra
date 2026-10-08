# -*- coding: utf-8 -*-
"""
log_export.py
=============
운영진이 채팅 · 전투 로그를 HTML 파일 하나로 내려받을 수 있게 만들어 줍니다.
앱의 채팅창 · 로그창과 같은 모양(프로필, 이어 쓴 글 묶기, 행동 블록, 라운드 결과 표)으로 보이고,
파일만 열면 인터넷 없이도 보이도록 스타일 · 제목 폰트를 전부 안에 넣습니다.
"""

import base64
import html
import os
import re
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_GROUP_START = {"action", "defend", "taunt", "round", "wait"}
_TAG_ICON = {
    "action": "⚔", "damage": "⚔", "defend": "🛡", "defend_value": "🛡", "taunt": "🎯",
    "heal": "✚", "crit": "✦", "wait": "⏸", "hp": "❤",
}


def _e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _font_face():
    path = os.path.join(_THIS_DIR, "static", "fonts", "Baunk.ttf")
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return f'@font-face {{ font-family:"Baunk"; src:url(data:font/ttf;base64,{data}) format("truetype"); }}'
    except OSError:
        return ""


_CSS = """
:root { color-scheme: dark; --bg:#050505; --panel:#141416; --line:#262629; --card-border:#2a2a2e; --text:#f2f2f2; --muted:#8b8b90; --point:#5c86ff; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family:"42dot Sans","Pretendard","Malgun Gothic",-apple-system,sans-serif;
  letter-spacing:-0.01em; line-height:1.5; -webkit-font-smoothing:antialiased; }
.wrap { max-width:760px; margin:0 auto; padding:44px 20px 80px; }
h1 { font-family:"Baunk","42dot Sans",sans-serif; font-weight:400; font-size:30px; letter-spacing:.02em; margin:0 0 6px; }
.meta { color:var(--muted); font-size:14px; margin-bottom:22px; }
.tabs { position:sticky; top:0; z-index:5; display:flex; gap:2px; padding:10px 0 0; background:var(--bg); border-bottom:1px solid var(--line); margin-bottom:22px; }
.tabs a { color:var(--muted); text-decoration:none; padding:10px 14px; font-size:15px; font-weight:600; border-bottom:2px solid transparent; margin-bottom:-1px; }
.tabs a:hover { color:var(--text); }
section { margin-bottom:44px; scroll-margin-top:60px; }
section > h2 { font-size:17px; margin:0 0 12px; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px 20px; }
.empty { color:var(--muted); font-size:14px; }

/* 채팅 (앱 채팅창과 같은 모양) */
.msg { display:flex; gap:10px; margin-bottom:12px; align-items:flex-start; }
.msg.cont { margin-top:-8px; }
.msg.cont .av { visibility:hidden; height:0; }
.msg.cont .who { display:none; }
.av { width:38px; height:38px; border-radius:6px; flex-shrink:0; display:flex; align-items:center; justify-content:center;
  font-size:15px; font-weight:700; color:var(--ac); background:color-mix(in srgb, var(--ac) 16%, #0c0c0d);
  border:1px solid color-mix(in srgb, var(--ac) 35%, transparent); }
.av.star { background:none; border:none; color:var(--muted); font-size:18px; }
.body { flex:1; min-width:0; }
.who { line-height:1.3; margin-bottom:2px; }
.who b { font-weight:700; }
.who .time { color:var(--muted); font-size:13px; margin-left:6px; }
.who .tag { color:var(--muted); font-size:12px; margin-left:6px; }
.text { font-size:15px; line-height:1.55; white-space:pre-line; word-break:break-word; }
.msg.sys .text { color:var(--muted); }
.rh { display:flex; align-items:baseline; margin:0 0 8px; }
.rh .mk { width:22px; flex-shrink:0; color:var(--point); font-size:16px; }
.rh .main { font-family:"Baunk","42dot Sans",sans-serif; color:var(--point); font-size:18px; line-height:1.2; }
.rh .sub { color:var(--text); font-weight:700; font-size:15px; }
.rh.big { margin-top:16px; margin-bottom:2px; }

/* 전투 로그 (앱 로그창과 같은 모양) */
.battle-h { font-size:13px; color:var(--muted); font-weight:700; letter-spacing:.02em; margin:28px 0 10px; padding-bottom:8px; border-bottom:1px solid var(--line); }
.battle-h:first-child { margin-top:0; }
.ln { color:#c8cad0; font-size:15px; line-height:1.65; }
.ln .li { display:inline-block; width:20px; text-align:center; margin-right:4px; opacity:.85; }
.ln.system, .ln.wait { color:var(--muted); font-size:14px; }
.ln.crit { color:#fff; font-weight:700; }
.block { margin:8px 0; padding:6px 10px; border-left:3px solid var(--muted); border-radius:6px; background:rgba(255,255,255,.035); }
.block.atk { border-left-color:#ff6b5b; }
.block.def { border-left-color:#4a90ff; }
.block.heal { border-left-color:#ffd166; }
.block .ln:not(.head) { padding-left:14px; font-size:14.5px; }
.block .ln.head { color:#fff; font-weight:600; padding-bottom:2px; margin-bottom:2px; border-bottom:1px solid rgba(255,255,255,.08); }
.block .ln.head:last-child { border-bottom:none; padding-bottom:0; margin-bottom:0; }
.sum { margin:6px 0 12px; padding:8px 12px 10px; border:1px solid var(--card-border); border-radius:10px; background:rgba(255,255,255,.02); font-size:14px; }
.sum .team { font-size:12px; font-weight:700; color:var(--muted); margin:8px 0 2px; }
.sum .row { display:grid; grid-template-columns:minmax(0,1fr) 40px 16px 40px 60px; column-gap:6px; padding:4px 0; font-variant-numeric:tabular-nums; }
.sum .row + .row { border-top:1px solid rgba(255,255,255,.05); }
.sum .nm { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sum .nm em { font-style:normal; font-weight:400; color:var(--muted); font-size:12px; }
.sum .a { text-align:right; color:var(--muted); }
.sum .arr { text-align:center; font-size:12px; color:var(--muted); }
.sum .b { text-align:right; font-weight:700; }
.sum .d { text-align:right; color:var(--muted); }
.sum .d.up { color:#ff5a5a; font-weight:700; }
.sum .d.down { color:#4a8dff; font-weight:700; }
.sum .row.out { opacity:.55; }
"""


def _fmt_time(t):
    """'HH:MM:SS' → '오후 3:07' (앱 채팅과 같은 표시, 초 없음)"""
    parts = (t or "").split(":")
    try:
        h = int(parts[0])
    except (ValueError, IndexError):
        return _e(t)
    m = parts[1] if len(parts) > 1 else "00"
    return f"{'오전' if h < 12 else '오후'} {h % 12 or 12}:{m}"


def _secs(t):
    try:
        p = [int(x) for x in (t or "").split(":")]
        return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)
    except (ValueError, IndexError):
        return None


def _round_head(text):
    t = (text or "").strip()
    if re.match(r"^round\s*\d+", t, re.I):
        return f'<div class="rh big"><span class="mk">✶</span><span class="main">{_e(t)}</span></div>'
    return f'<div class="rh"><span class="mk"></span><span class="sub">{_e(t.replace("▶ ", "", 1))}</span></div>'


def _chat_html(entries, colors):
    rows, prev_who, prev_t = [], None, None
    for e in entries:
        cat = e.get("category") or ""
        if cat == "presence" or re.search(r"님이 (입장|퇴장)했습니다", e.get("text") or ""):
            continue
        if cat == "round":
            rows.append(_round_head(e.get("text")))
            prev_who = None
            continue
        name = e.get("nickname") or ""
        who = f"{name}|{cat}|{e.get('team') or ''}"
        t = _secs(e.get("time"))
        cont = who == prev_who and t is not None and prev_t is not None and 0 <= t - prev_t <= 180
        prev_who, prev_t = who, t
        is_star = e.get("role") in ("system", "gm") or name.strip().lower() == "gm"
        color = colors.get(name) or "#5a5a62"
        if is_star:
            av = '<div class="av star">✶</div>'
        else:
            av = f'<div class="av" style="--ac:{_e(color)}">{_e((name.strip() or "?")[0])}</div>'
        tag = ""
        if cat == "spectator":
            tag = '<span class="tag">관전</span>'
        elif cat == "team":
            tag = f'<span class="tag">{"1팀" if e.get("team") == "A" else "2팀"} 회의</span>'
        name_style = f' style="color:{_e(colors[name])}"' if (not is_star and colors.get(name)) else ""
        rows.append(
            f'<div class="msg{" cont" if cont else ""}{" sys" if cat == "system" else ""}">{av}<div class="body">'
            f'<div class="who"><b{name_style}>{_e(name)}</b>{tag}<span class="time">{_fmt_time(e.get("time"))}</span></div>'
            f'<div class="text">{_e(e.get("text"))}</div></div></div>'
        )
    return "".join(rows) or '<div class="empty">기록이 없어요.</div>'


def _action_class(head):
    if head.get("tag") == "defend":
        return "def"
    if head.get("tag") != "action":
        return ""
    t = head.get("text") or ""
    if t.startswith("["):
        return ""
    if "공격" in t or "【붕괴】" in t or "【방출】" in t:
        return "atk"
    if "힐" in t:
        return "heal"
    if "방어" in t or "회피" in t:
        return "def"
    return ""


def _line(l, head=False, no_icon=False):
    icon = "" if no_icon else _TAG_ICON.get(l.get("tag"), "")
    icon_html = f'<span class="li">{icon}</span>' if icon else ""
    cls = l.get("tag") or ""
    return f'<div class="ln {cls}{" head" if head else ""}">{icon_html}{_e(l.get("text"))}</div>'


def _summary_html(section, team_of):
    rows = []
    for l in section[1:]:
        m = l.get("tag") == "summary" and re.match(r"^(.+?)\s+(\d+)\s*→\s*(\d+)(?:\s*\((.+)\))?\s*$", l.get("text") or "")
        if m:
            rows.append((m.group(1).strip(), int(m.group(2)), int(m.group(3)), m.group(4) or ""))
    if not rows:
        return "".join(_line(l) for l in section)

    def row(r):
        name, a, b, state = r
        d = b - a
        dtxt = f"▲{d}" if d > 0 else (f"▼{-d}" if d < 0 else "–")
        dcls = "up" if d > 0 else ("down" if d < 0 else "")
        st = f" <em>{_e(state)}</em>" if state else ""
        return (f'<div class="row{" out" if state else ""}"><span class="nm">{_e(name)}{st}</span>'
                f'<span class="a">{a}</span><span class="arr">→</span><span class="b">{b}</span><span class="d {dcls}">{dtxt}</span></div>')

    a_rows = [r for r in rows if team_of.get(r[0]) != "B"]
    b_rows = [r for r in rows if team_of.get(r[0]) == "B"]
    body = ""
    if a_rows:
        body += '<div class="team">Team 1</div>' + "".join(row(r) for r in a_rows)
    if b_rows:
        body += '<div class="team">Team 2</div>' + "".join(row(r) for r in b_rows)
    return _round_head(section[0].get("text")) + f'<div class="sum">{body}</div>'


def _log_html(lines, team_of):
    lines = [l for l in (lines or []) if l.get("tag") != "arrow"]
    if not lines:
        return '<div class="empty">기록이 없어요.</div>'
    sections, cur = [], []
    for l in lines:
        if l.get("tag") in _GROUP_START and cur:
            sections.append(cur)
            cur = []
        cur.append(l)
    if cur:
        sections.append(cur)
    out = []
    for sec in sections:
        head = sec[0]
        if head.get("tag") == "round":
            if "최종 결과" in (head.get("text") or ""):
                out.append(_summary_html(sec, team_of))
            else:
                out.append(_round_head(head.get("text")) + "".join(_line(l) for l in sec[1:]))
            continue
        if head.get("tag") not in _GROUP_START:
            out.append("".join(_line(l) for l in sec))
            continue
        cls = _action_class(head)
        inner = "".join(_line(l, head=(i == 0), no_icon=(i == 0 and len(sec) > 1)) for i, l in enumerate(sec))
        out.append(f'<div class="block {cls}">{inner}</div>')
    return "".join(out)


def build_export_html(room_name, battle_type_label, chat_log, team_chat_log, battles, colors=None):
    """battles : [{"label", "public_log", "operator_log", "teams": {이름: "A"|"B"}}, ...] (오래된 것 → 최근 것)"""
    colors = colors or {}
    now = time.strftime("%Y-%m-%d %H:%M")
    sections = [("chat", "채팅", _chat_html(chat_log, colors))]
    if team_chat_log:
        sections.append(("team", "아군 회의", _chat_html(team_chat_log, colors)))

    def battles_html(key):
        if not battles:
            return '<div class="empty">기록이 없어요.</div>'
        return "".join(f'<div class="battle-h">{_e(b["label"])}</div>{_log_html(b.get(key), b.get("teams") or {})}'
                       for b in reversed(battles))

    sections.append(("battle", "전투 로그", battles_html("public_log")))
    sections.append(("operator", "운영진 로그", battles_html("operator_log")))
    tabs = "".join(f'<a href="#{k}">{t}</a>' for k, t, _ in sections)
    body = "".join(f'<section id="{k}"><h2>{t}</h2><div class="panel">{h}</div></section>' for k, t, h in sections)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(room_name)} 로그</title><style>{_font_face()}{_CSS}</style></head><body><div class="wrap">'
            f'<h1>{_e(room_name)}</h1><div class="meta">{_e(battle_type_label)} · {now} 저장</div>'
            f'<nav class="tabs">{tabs}</nav>{body}</div></body></html>')
