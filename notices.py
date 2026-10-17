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
# 순서는 목록 위에서부터 1번 · 2번 · 3번.
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
    ("loop_guide_v2", "LOOP 이용 안내 · 시뮬레이터 하는 법", """
<p><b>LOOP</b>는 한 사람의 생애를 사건 하나하나 골라 가며 살아 보는 러닝 시뮬레이션입니다. 누구나 웹에서 바로 해 볼 수 있어요.</p>
<h3>들어가기</h3>
<ul>
<li>로그인 창에 <b>TEST</b>라고 입력하면 들어갈 수 있습니다. (공용 아이디라 비밀번호는 없어요.)</li>
<li>모두 같은 TEST로 들어오지만 <b>진행 기록은 기기(브라우저)마다 따로</b> 저장됩니다. 다른 사람의 화면이나 기록과 섞이지 않아요.</li>
</ul>
<h3>하는 법</h3>
<ul>
<li><b>운명 시작</b> : 모두 <b>공명자(Resonant)</b>로 플레이합니다. 태어날 국가(아르카디아 · 노바)는 무작위로 정해집니다.</li>
<li><b>프롤로그</b> : 서력의 역사와 탄생(출신 · 집안 · 문명관)을 읽고 <b>삶을 시작한다</b>를 누르세요.</li>
<li><b>사건</b> : 사건마다 선택지 A · B · C 중 하나를 고릅니다. 체력 · 정신이 얼마나 바뀌는지는 <b>고른 뒤에만</b> 알 수 있어요.</li>
<li><b>체력</b>이 0이 되면 사망, <b>정신</b>이 0이 되면 정신 붕괴로 생애가 끝납니다. 재산 · 지능 · 재능은 선택지 조건이나 위기 해결에 쓰입니다.</li>
<li>시대 I부터 차례로 사건이 이어지고, 마지막 시대까지 견디면 생존 엔딩입니다.</li>
<li>생애가 끝나면 <b>기록 남기기</b>로 끝내거나, 열려 있다면 <b>루프 진입</b>으로 기억 일부를 안고 평행 세계에서 다시 시작할 수 있어요.</li>
<li>기록을 남긴 뒤에는 <b>새 운명 (Loop)</b>으로 다음 생애를 시작합니다. 다음 생애도 높은 확률로 같은 국가에서 태어나요.</li>
</ul>
<h3>기록 보기</h3>
<ul>
<li><b>Log</b>(지나온 사건)에 이번 생애의 사건이 쌓입니다. 사건을 누르면 그때의 내용을 다시 볼 수 있어요. (보기만 가능하고 되돌리지는 않습니다.)</li>
<li>맨 위 <b>지난 운명</b>을 누르면 그 생애가 끝났을 때의 카드를 다시 볼 수 있습니다. 지난 생애는 최근 30개까지 남아요.</li>
</ul>
<h3>새로 시작</h3>
<ul>
<li>Log 위쪽의 <b>새로 시작</b>을 누르면 지금 생애를 <b>기록 없이 버리고</b> 처음부터 다시 시작합니다. 되돌릴 수 없으니 주의해 주세요.</li>
<li>이미 남긴 지난 운명 기록은 새로 시작해도 지워지지 않습니다.</li>
</ul>
<h3>PC · 휴대폰</h3>
<ul>
<li><b>PC</b> : 가운데에 이야기와 선택지, 오른쪽에 Log가 함께 보입니다. 위쪽 상태판(체력 · 정신 · 자원)은 처음부터 펼쳐져 있어요.</li>
<li><b>휴대폰</b> : 세로 화면 전용입니다(가로로 돌리면 세로로 돌려 달라는 안내가 떠요). 화면을 <b>왼쪽으로 밀면 Log</b>, 오른쪽으로 밀면 다시 이야기 화면입니다. 상태판은 처음에 접혀 있고 <b>펼치기</b>로 열 수 있어요.</li>
<li>기록은 기기마다 따로라 <b>PC에서 하던 생애를 휴대폰에서 이어 할 수는 없습니다.</b> 같은 기기 · 같은 브라우저에서 이어 주세요.</li>
<li>브라우저의 방문 기록 · 사이트 데이터를 지우거나 시크릿 창을 쓰면 그 기기의 진행 기록을 다시 찾을 수 없어요.</li>
</ul>
<h3>공개 범위</h3>
<ul>
<li>웹에 공개된 곳은 <b>LOOP 방뿐</b>입니다. 다른 방(커뮤니티 · 전투 등)은 초대받은 참가자만 들어갈 수 있는 비공개 공간이에요.</li>
<li>LOOP 방에서는 다른 참가자의 목록 · 프로필 · 대화가 보이지 않고, 나의 진행 기록도 다른 사람에게 보이지 않습니다.</li>
<li>이름 · 연락처 같은 개인정보는 받지 않습니다. 진행 기록은 기기 번호(브라우저가 만든 무작위 값)로만 구분해 저장해요.</li>
</ul>
"""),
]
# 내용을 고친 고정 공지 : 예전 판이 이미 올라가 있으면 새 글을 더 올리지 않고 그 글(같은 제목)의 본문만 바꿔요.
SEED_REPLACES = {"loop_guide_v2": "loop_guide_v1"}


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
        for key, title, body in SEED_NOTICES:
            old = SEED_REPLACES.get(key)
            if key in self.seeded or not old or old not in self.seeded:
                continue
            for n in self.notices:
                if n.get("title") == title:
                    n["html"] = sanitize_html(body)
            self.seeded.append(key)
            self.save()
        todo = [x for x in SEED_NOTICES if x[0] not in self.seeded]
        if not todo:
            return
        now = time.time()
        # 나중에 추가된 고정 공지는 이미 올라간 고정 공지 아래(뒷번호)로 들어가요.
        old = [n.get("created_at", now) for n in self.notices if n.get("pinned")] if self.seeded else []
        if old:
            now = min(old) - len(SEED_NOTICES)
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
