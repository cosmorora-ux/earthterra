# -*- coding: utf-8 -*-
"""
notices.py
==========
공지사항 : 운영진이 쓰고(글자 크기/굵게/기울임 등 서식 포함) 모든 방의 참가자가 읽습니다.
notices.json에 저장됩니다(서버 컴퓨터별 실데이터라 git에 올리지 않음).

본문은 HTML이라, 저장하기 전에 허용된 태그/속성만 남기도록 정리(sanitize)합니다.
(스크립트·이벤트 속성·외부 iframe 등은 모두 제거)
"""

import html
import json
import os
import re
import time
import uuid
from html.parser import HTMLParser

NOTICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notices.json")
MAX_NOTICES = 100
MAX_HTML_LEN = 40000
MAX_TITLE_LEN = 80

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "s", "strike", "span", "font", "br", "p", "div",
    "ul", "ol", "li", "a", "h1", "h2", "h3", "blockquote", "hr", "sub", "sup",
}
VOID_TAGS = {"br", "hr"}
ALLOWED_STYLE_PROPS = {
    "color", "background-color", "font-size", "font-weight", "font-style",
    "text-decoration", "text-decoration-line", "text-align",
}
_SAFE_STYLE_VALUE = re.compile(r"^[#a-zA-Z0-9\s.,%()\-]+$")


def _clean_style(style: str) -> str:
    out = []
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop, val = prop.strip().lower(), val.strip()
        if prop in ALLOWED_STYLE_PROPS and _SAFE_STYLE_VALUE.match(val) and "url" not in val.lower():
            out.append(f"{prop}: {val}")
    return "; ".join(out)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip_depth = 0  # <script>/<style> 안의 내용은 통째로 버립니다.

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "iframe", "object", "embed"):
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED_TAGS:
            return
        kept = []
        for name, value in attrs:
            name = (name or "").lower()
            value = value or ""
            if name == "style":
                v = _clean_style(value)
                if v:
                    kept.append(("style", v))
            elif tag == "font" and name == "size" and value.strip().isdigit():
                kept.append(("size", str(max(1, min(7, int(value.strip()))))))
            elif tag == "font" and name == "color" and _SAFE_STYLE_VALUE.match(value):
                kept.append(("color", value))
            elif tag == "a" and name == "href" and re.match(r"^https?://", value.strip(), re.I):
                kept.append(("href", value.strip()))
            elif name == "align" and value.lower() in ("left", "center", "right", "justify"):
                kept.append(("align", value.lower()))
        if tag == "a":
            kept += [("target", "_blank"), ("rel", "noopener noreferrer")]
        attr_txt = "".join(f' {n}="{html.escape(v, quote=True)}"' for n, v in kept)
        self.out.append(f"<{tag}{attr_txt}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "iframe", "object", "embed"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in self.stack:
            # 짝이 맞지 않게 닫힌 태그도 안전하게 정리합니다.
            while self.stack:
                t = self.stack.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(raw: str) -> str:
    p = _Sanitizer()
    p.feed(raw or "")
    p.close()
    return p.result()[:MAX_HTML_LEN]


class NoticeBoard:
    def __init__(self, path: str = NOTICES_PATH):
        self.path = path
        self.notices = []  # 최신 글이 앞에 오도록 정렬된 목록
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.notices = json.load(f).get("notices", [])
            except (json.JSONDecodeError, OSError):
                self.notices = []

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"notices": self.notices}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def upsert(self, notice_id, title: str, body_html: str, pinned: bool, author: str):
        title = (title or "").strip()[:MAX_TITLE_LEN] or "제목 없음"
        body = sanitize_html(body_html)
        now = time.time()
        existing = next((n for n in self.notices if n["id"] == notice_id), None) if notice_id else None
        if existing:
            existing.update({"title": title, "html": body, "pinned": bool(pinned), "updated_at": now})
            notice = existing
        else:
            notice = {
                "id": uuid.uuid4().hex[:10], "title": title, "html": body, "pinned": bool(pinned),
                "author": author, "created_at": now, "updated_at": now,
            }
            self.notices.insert(0, notice)
            del self.notices[MAX_NOTICES:]
        self.save()
        return notice, existing is None

    def delete(self, notice_id) -> bool:
        before = len(self.notices)
        self.notices = [n for n in self.notices if n["id"] != notice_id]
        if len(self.notices) != before:
            self.save()
            return True
        return False

    def payload(self) -> list:
        # 고정 공지 먼저, 그다음 최신순
        return sorted(self.notices, key=lambda n: (not n.get("pinned"), -n.get("created_at", 0)))


_BOARD = None


def shared_board() -> NoticeBoard:
    global _BOARD
    if _BOARD is None:
        _BOARD = NoticeBoard()
    return _BOARD
