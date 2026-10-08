# -*- coding: utf-8 -*-
"""
log_export.py
=============
운영진이 채팅 · 전투 로그를 HTML 파일 하나로 내려받을 수 있게 만들어 줍니다.
파일만 열면 인터넷 없이도 보이도록 스타일을 전부 안에 넣습니다.
"""

import html
import time

_TAG_CLASS = {
    "round": "round", "action": "act", "defend": "act", "taunt": "act", "wait": "wait",
    "system": "sys", "summary": "sum", "hp": "hp", "crit": "crit",
}

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#050505; color:#f2f2f2; font-family:"42dot Sans","Pretendard","Malgun Gothic",-apple-system,sans-serif;
  letter-spacing:-0.01em; line-height:1.55; }
.wrap { max-width:860px; margin:0 auto; padding:40px 20px 80px; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:-0.02em; }
.meta { color:#8b8b90; font-size:14px; margin-bottom:22px; }
.tabs { position:sticky; top:0; z-index:5; display:flex; gap:4px; flex-wrap:wrap; padding:10px 0; background:#050505; border-bottom:1px solid #262629; margin-bottom:18px; }
.tabs a { color:#8b8b90; text-decoration:none; padding:7px 14px; border-radius:8px; font-size:14px; font-weight:600; }
.tabs a:hover { color:#f2f2f2; background:#17171a; }
section { margin-bottom:40px; }
section > h2 { font-size:18px; margin:0 0 12px; padding-top:8px; }
.box { background:#141416; border:1px solid #262629; border-radius:14px; padding:16px 18px; }
.empty { color:#8b8b90; font-size:14px; }
.chat { display:flex; gap:10px; padding:5px 0; font-size:15px; }
.chat .t { color:#6b6b70; font-size:12px; width:62px; flex-shrink:0; padding-top:3px; font-variant-numeric:tabular-nums; }
.chat .n { font-weight:700; margin-right:8px; }
.chat .c { color:#8b8b90; font-size:12px; margin-right:6px; }
.chat.sys .x { color:#8b8b90; }
.chat .x { white-space:pre-wrap; word-break:break-word; }
.chat.round { padding:14px 0 4px; }
.chat.round .x { color:#5c86ff; font-weight:700; font-size:16px; }
.battle-h { font-size:14px; color:#8b8b90; margin:22px 0 8px; font-weight:700; }
.battle-h:first-child { margin-top:0; }
.ln { padding:2px 0 2px 18px; font-size:14.5px; color:#c8cad0; white-space:pre-wrap; word-break:break-word; }
.ln.round { padding:16px 0 4px; color:#5c86ff; font-weight:700; font-size:16px; }
.ln.act { padding-left:0; padding-top:8px; color:#fff; font-weight:600; }
.ln.wait { padding-left:0; padding-top:8px; color:#8b8b90; }
.ln.sys { color:#8b8b90; }
.ln.crit { color:#fff; font-weight:700; }
.ln.hp { color:#d8d8dc; }
.ln.sum { font-variant-numeric:tabular-nums; }
"""


def _e(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def _chat_html(entries, team_names=None):
    if not entries:
        return '<div class="empty">기록이 없어요.</div>'
    out = []
    for e in entries:
        cat = e.get("category") or ""
        text = _e(e.get("text"))
        if cat == "round":
            text = _e((e.get("text") or "").replace("▶ ", "", 1))
            out.append(f'<div class="chat round"><span class="t">{_e(e.get("time"))}</span><span class="x">{text}</span></div>')
            continue
        label = ""
        if cat == "spectator":
            label = '<span class="c">[관전]</span>'
        elif cat == "team":
            label = f'<span class="c">[{"1팀" if e.get("team") == "A" else "2팀"} 회의]</span>'
        cls = "sys" if cat == "system" else ""
        out.append(f'<div class="chat {cls}"><span class="t">{_e(e.get("time"))}</span>'
                   f'<div>{label}<span class="n">{_e(e.get("nickname"))}</span><span class="x">{text}</span></div></div>')
    return "".join(out)


def _log_html(lines):
    if not lines:
        return '<div class="empty">기록이 없어요.</div>'
    def text_of(l):
        t = l.get("text") or ""
        return t.replace("▶ ", "", 1) if l.get("tag") == "round" else t
    return "".join(
        f'<div class="ln {_TAG_CLASS.get(l.get("tag"), "")}">{_e(text_of(l))}</div>'
        for l in lines if l.get("tag") != "arrow"
    )


def build_export_html(room_name, battle_type_label, chat_log, team_chat_log, battles):
    """battles : [{"label": str, "public_log": [...], "operator_log": [...]}, ...] (오래된 것 → 최근 것)"""
    now = time.strftime("%Y-%m-%d %H:%M")
    sections = [("chat", "채팅", _chat_html(chat_log))]
    if team_chat_log:
        sections.append(("team", "아군 회의", _chat_html(team_chat_log)))

    def battles_html(key):
        if not battles:
            return '<div class="empty">기록이 없어요.</div>'
        return "".join(f'<div class="battle-h">{_e(b["label"])}</div>{_log_html(b.get(key) or [])}' for b in battles)

    sections.append(("battle", "전투 로그", battles_html("public_log")))
    sections.append(("operator", "운영진 로그", battles_html("operator_log")))
    tabs = "".join(f'<a href="#{k}">{t}</a>' for k, t, _ in sections)
    body = "".join(f'<section id="{k}"><h2>{t}</h2><div class="box">{h}</div></section>' for k, t, h in sections)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(room_name)} 로그</title><style>{_CSS}</style></head><body><div class="wrap">'
            f'<h1>{_e(room_name)} 로그</h1><div class="meta">{_e(battle_type_label)} · {now} 저장</div>'
            f'<nav class="tabs">{tabs}</nav>{body}</div></body></html>')
