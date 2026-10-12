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
.wrap { max-width:780px; margin:0 auto; padding:40px 20px 80px; }
/* 머리 : 영문 제목(Baunk) + 방 이름 + 정보 칩 */
.hero { position:relative; overflow:hidden; border-radius:20px; border:1px solid rgba(255,255,255,.07); padding:26px 26px 22px; margin-bottom:18px;
  background: radial-gradient(120% 140% at 100% 0%, rgba(92,134,255,.16) 0%, rgba(92,134,255,0) 55%), #121215; }
.hero .kicker { font-family:"Baunk","42dot Sans",sans-serif; font-size:24px; line-height:1; letter-spacing:.02em; color:#fff; }
.hero h1 { font-size:26px; font-weight:800; letter-spacing:-0.02em; margin:14px 0 14px; line-height:1.25; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { display:inline-flex; align-items:center; gap:6px; padding:5px 11px; border-radius:999px; background:rgba(255,255,255,.06); color:#c9c9ce; font-size:12.5px; font-weight:500; }
.chip.pt { background:rgba(92,134,255,.16); color:#c9d6ff; font-weight:700; }
.chip svg { width:12px; height:12px; opacity:.75; }
/* 탭 : 누른 탭의 기록만 보입니다 */
.tabs { position:sticky; top:0; z-index:5; display:flex; gap:4px; padding:6px; margin:0 0 18px; border-radius:14px;
  background:rgba(18,18,21,.92); border:1px solid rgba(255,255,255,.07); -webkit-backdrop-filter:blur(8px); backdrop-filter:blur(8px); }
.tabs a { flex:1; text-align:center; color:var(--muted); text-decoration:none; padding:9px 10px; font-size:14px; font-weight:600; border-radius:10px; white-space:nowrap; }
.tabs a .n { font-size:11.5px; font-weight:600; opacity:.6; margin-left:4px; font-variant-numeric:tabular-nums; }
.tabs a:hover { color:var(--text); background:rgba(255,255,255,.04); }
.tabs a.on { color:#fff; background:rgba(255,255,255,.09); }
section { margin-bottom:44px; scroll-margin-top:80px; }
.js section { display:none; }
.js section.on { display:block; }
section > h2 { font-size:15px; color:var(--muted); font-weight:600; margin:0 0 10px 4px; }
.js section > h2 { display:none; }
.panel { background:var(--panel); border:1px solid rgba(255,255,255,.07); border-radius:16px; padding:18px 20px; }
.foot { text-align:center; color:#55555c; font-size:12px; margin-top:28px; }
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


_ICON_CLOCK = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.2"/>'
               '<path d="M8 4.6V8l2.3 1.5" stroke-linecap="round"/></svg>')
_ICON_CHAT = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">'
              '<path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>')

_TAB_JS = """
document.documentElement.classList.add('js');
(function () {
  var tabs = document.querySelectorAll('.tabs a'), secs = document.querySelectorAll('section');
  function show(id) {
    var found = false;
    secs.forEach(function (s) { var on = s.id === id; s.classList.toggle('on', on); if (on) found = true; });
    if (!found && secs[0]) { id = secs[0].id; secs[0].classList.add('on'); }
    tabs.forEach(function (a) { a.classList.toggle('on', a.getAttribute('href') === '#' + id); });
  }
  tabs.forEach(function (a) { a.addEventListener('click', function (e) { e.preventDefault(); var id = a.getAttribute('href').slice(1);
    show(id); history.replaceState(null, '', '#' + id); window.scrollTo({ top: 0 }); }); });
  show((location.hash || '').slice(1));
})();
"""


def build_export_html(room_name, battle_type_label, chat_log, team_chat_log, battles, colors=None, include_operator=True):
    """battles : [{"label", "public_log", "operator_log", "teams": {이름: "A"|"B"}}, ...] (오래된 것 → 최근 것)
    include_operator : False면(러너가 내려받을 때) 운영진 로그 탭을 넣지 않습니다."""
    colors = colors or {}
    now = time.strftime("%Y-%m-%d %H:%M")

    def chat_count(entries):
        return sum(1 for e in entries if (e.get("category") or "") not in ("presence", "round", "system"))

    # 아군 회의는 팀끼리만 보는 대화라 파일에는 넣지 않습니다.
    sections = [("chat", "채팅", _chat_html(chat_log, colors), chat_count(chat_log))]

    def battles_html(key):
        if not battles:
            return '<div class="empty">기록이 없어요.</div>'
        return "".join(f'<div class="battle-h">{_e(b["label"])}</div>{_log_html(b.get(key), b.get("teams") or {})}'
                       for b in reversed(battles))

    sections.append(("battle", "전투 로그", battles_html("public_log"), None))
    if include_operator:
        sections.append(("operator", "운영진 로그", battles_html("operator_log"), None))
    tabs = "".join(f'<a href="#{k}">{t}{f"<span class=n>{n}</span>" if n else ""}</a>' for k, t, _, n in sections)
    body = "".join(f'<section id="{k}"><h2>{t}</h2><div class="panel">{h}</div></section>' for k, t, h, _ in sections)
    chips = (f'<span class="chip pt">{_e(battle_type_label)}</span>'
             f'<span class="chip">{_ICON_CLOCK}{now} 저장</span>'
             f'<span class="chip">{_ICON_CHAT}채팅 {chat_count(chat_log)}개</span>')
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(room_name)} 로그</title><style>{_font_face()}{_CSS}</style></head><body><div class="wrap">'
            f'<header class="hero"><div class="kicker">Battle Log</div><h1>{_e(room_name)}</h1><div class="chips">{chips}</div></header>'
            f'<nav class="tabs">{tabs}</nav>{body}<div class="foot">earthterra · {now}</div></div>'
            f'<script>{_TAB_JS}</script></body></html>')
