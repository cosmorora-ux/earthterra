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
import safeio
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
    def __init__(self, allowed=None):
        super().__init__(convert_charrefs=True)
        self.allowed = allowed or ALLOWED_TAGS
        self.out = []
        self.stack = []
        self.skip_depth = 0  # <script>/<style> 안의 내용은 통째로 버립니다.

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "iframe", "object", "embed"):
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in self.allowed:
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
        if self.skip_depth or tag not in self.allowed or tag in VOID_TAGS:
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


def sanitize_html(raw: str, allowed=None, max_len: int = MAX_HTML_LEN) -> str:
    p = _Sanitizer(allowed)
    p.feed(raw or "")
    p.close()
    return p.result()[:max_len]


def plain_text(raw_html: str) -> str:
    """태그를 뺀 순수 글자만(길이 검사용)."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw_html or ""))


# 처음부터 올려 두는 고정 공지(한 번만 올라가요 : 운영진이 고치거나 지워도 다시 생기지 않아요).
# 순서는 목록 위에서부터 1번 · 2번.
SEED_NOTICES = [
    ("license_v1", "제작 도구 · 사용 소스 안내", """
<p>이 사이트는 운영진이 직접 기획하고, 개발 과정의 일부에 AI 도구를 활용해 만들었습니다. 사용한 도구와 외부 자료는 각자의 이용 약관과 라이선스를 지키며 사용하고 있습니다.</p>
<h3>AI 사용 안내</h3>
<ul>
<li><b>Claude (Anthropic)</b> : 화면 · 서버 코드 작성과 수정에 활용했습니다. Anthropic의 이용 약관과 사용 정책을 지키며 사용하며, 약관에 따라 결과물에 대한 권리는 운영진에게 있습니다.</li>
<li>세계관 · 설정 · 시나리오의 기획과 최종 결정은 운영진이 합니다. AI가 만든 결과물은 운영진이 검토하고 고친 뒤에 반영합니다.</li>
</ul>
<h3>사용 소스 · 라이선스</h3>
<ul>
<li><b>Flask</b> — BSD-3-Clause</li>
<li><b>Flask-SocketIO · python-socketio</b> — MIT</li>
<li><b>Socket.IO 클라이언트</b> 4.7.5 — MIT</li>
<li><b>Font Awesome Free</b> 6.7.2 — 아이콘 CC BY 4.0 · 글꼴 SIL OFL 1.1 · 코드 MIT (fontawesome.com)</li>
<li><b>42dot Sans</b> 글꼴 — SIL Open Font License 1.1 (Google Fonts)</li>
<li><b>Pretendard</b> 글꼴 1.3.9 — SIL Open Font License 1.1 (orioncactus)</li>
<li><b>Baunk</b> 글꼴 (영문 제목) — 출처 · 라이선스 : 운영진 기입</li>
<li>카드 반짝이 질감 이미지 · 기본 효과음 — 출처 · 라이선스 : 운영진 기입</li>
<li>마이룸 도트 자료 — 자료마다 제작자 · 라이선스를 마이룸의 <b>출처</b> 창에 적어 두었습니다.</li>
</ul>
<p>저작권 · 라이선스 관련 문의나 표기 누락은 운영진에게 알려 주시면 바로 고치겠습니다.</p>
"""),
    ("rating_v1", "웹게임 등급분류(심의) 안내", """
<p>이 사이트는 <b>등급분류(심의) 대상이 아닌 비영리 커뮤니티 창작물</b>입니다.</p>
<ul>
<li>개인 · 동호회가 <b>비영리</b>로 만들고 운영합니다. 참가비 · 유료 결제 · 광고가 없습니다.</li>
<li>게임 안의 포인트 · 아이템은 이 사이트 안에서만 쓰이며, <b>현금이나 상품으로 바꿀 수 없습니다.</b> 개인 간 현금 거래도 금지합니다.</li>
<li>「게임산업진흥에 관한 법률」 시행령은 개인 · 동호회가 비영리 목적으로 만들어 공개하는 게임물을 등급분류 대상에서 제외하고 있어, 별도의 등급분류를 받지 않았습니다.</li>
<li>운영 방식이 바뀌어 유료화 · 광고 · 상업적 유통이 생기면, 그 전에 관련 법령에 따른 등급분류를 먼저 받겠습니다.</li>
</ul>
<p>관련 문의는 운영진에게 남겨 주세요.</p>
"""),
]


class NoticeBoard:
    def __init__(self, path: str = NOTICES_PATH):
        self.path = path
        self.notices = []  # 최신 글이 앞에 오도록 정렬된 목록
        self.seeded = []
        self.load()
        self.seed()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.notices = d.get("notices", [])
                    self.seeded = d.get("seeded", [])
            except (json.JSONDecodeError, OSError):
                self.notices = []

    def seed(self):
        """SEED_NOTICES 중 아직 올린 적 없는 것만 고정 공지로 올립니다(위에서부터 1번 · 2번 순서)."""
        todo = [x for x in SEED_NOTICES if x[0] not in self.seeded]
        if not todo:
            return
        now = time.time()
        for i, (key, title, body) in enumerate(SEED_NOTICES):
            if key not in [k for k, _, _ in todo]:
                continue
            t = now - i   # 앞 공지가 더 '최신' → 목록 위쪽
            self.notices.insert(0, {"id": uuid.uuid4().hex[:10], "title": title, "html": sanitize_html(body), "pinned": True,
                                    "author": "운영진", "created_at": t, "updated_at": t})
            self.seeded.append(key)
        self.save()

    def save(self):
        safeio.write_json(self.path, {"notices": self.notices, "seeded": self.seeded}, indent=2)

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
