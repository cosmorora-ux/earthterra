# -*- coding: utf-8 -*-
"""
mailbox.py
==========
우체통 : 캐릭터끼리 편지를 주고받습니다. 받는 사람을 직접 고르거나, 랜덤으로 보낼 수 있고,
익명으로 보낼 수도 있습니다. 모든 방에서 같은 우체통을 씁니다(캐릭터 DB가 공용이라서).
letters.json에 저장됩니다(서버 컴퓨터별 실데이터라 git에 올리지 않음).

- 익명 편지 : 받는 사람 화면에는 보낸 사람이 "익명"으로만 보입니다(운영진은 볼 수 있음).
- 랜덤 편지 : 보낸 사람 화면에는 받는 사람이 공개되지 않습니다(운영진은 볼 수 있음).
- 지우기 : 받은 사람/보낸 사람이 각자 자기 목록에서만 지웁니다. 둘 다 지우면 완전히 삭제됩니다.
"""

import json
import safeio
import os
import random
import threading
import time
import uuid

LETTERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "letters.json")
MAX_TEXT_LEN = 2000
MAX_LETTERS = 5000
# 첨부 이미지 : 편지 한 통에 4장까지, 장당 5MB. 파일 이름은 추측할 수 없는 무작위 이름이라 받는 사람만 주소를 알아요.
MAX_IMAGES = 4
IMAGE_MAX_BYTES = 5 * 1024 * 1024
# 편지의 시기(작중 연도, 空歷) : 대분류를 먼저 고르고, 리뉴얼 기간만 그 안에서 연도를 고릅니다.
# (id, 이름, 첫 해, 마지막 해) — 러닝 기간은 연도가 하나로 정해져 있어요. 순서 = 작중 시간 순서.
ERAS = [
    ("r1", "1차 러닝", 514, 514),
    ("n12", "1~2차 리뉴얼", 514, 524),
    ("r2", "2차 러닝", 524, 524),
    ("n23", "2~3차 리뉴얼", 500, 524),
    ("r3", "3차 기간", 524, 524),
]
ERA_INDEX = {e[0]: i for i, e in enumerate(ERAS)}


def clean_era(era, year):
    """(era id, 연도) 확인 : 모르는 대분류면 None, 러닝 기간은 연도를 그 기간 연도로 고정합니다."""
    if era not in ERA_INDEX:
        return None, None
    _, _, lo, hi = ERAS[ERA_INDEX[era]]
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = lo
    return era, max(lo, min(hi, year))


def eras_payload():
    return [{"id": i, "name": n, "from": lo, "to": hi} for i, n, lo, hi in ERAS]


IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "mail_images")
SEND_COOLDOWN = 3.0  # 같은 사람이 연달아 보내는 간격(초)
GM_NAME = "운영진"


class MailError(Exception):
    pass


class Mailbox:
    def __init__(self, path=LETTERS_PATH):
        self.path = path
        self.letters = []
        self.lock = threading.Lock()
        self._last_send = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.letters = json.load(f).get("letters", [])
        except (OSError, ValueError):
            self.letters = []

    def save(self):
        safeio.write_json(self.path, {"letters": self.letters}, indent=1)

    def send(self, sender, to, text, anonymous=False, random_pick=False, candidates=(), check_cooldown=True, images=(), dry_run=False, era=None, year=None):
        text = (text or "").strip()
        images = list(images or [])[:MAX_IMAGES]
        if not text and not images:
            raise MailError("편지 내용을 쓰거나 이미지를 붙여 주세요.")
        if len(text) > MAX_TEXT_LEN:
            raise MailError(f"편지는 {MAX_TEXT_LEN}자까지 쓸 수 있어요.")
        with self.lock:
            now = time.time()
            if check_cooldown and now - self._last_send.get(sender, 0) < SEND_COOLDOWN:
                raise MailError("조금 있다가 다시 보내 주세요.")
            if random_pick:
                pool = [c for c in candidates if c != sender]
                if not pool:
                    raise MailError("편지를 받을 수 있는 캐릭터가 없어요.")
                to = random.choice(pool)
            elif not to or to not in candidates:
                raise MailError("받는 사람을 찾을 수 없어요.")
            if to == sender:
                raise MailError("자기 자신에게는 보낼 수 없어요.")
            if dry_run:  # 보낼 수 있는지만 확인(첨부 이미지를 저장하기 전에)
                return None
            letter = {
                "id": uuid.uuid4().hex[:12], "from": sender, "to": to, "text": text,
                "anonymous": bool(anonymous), "random": bool(random_pick),
                "at": now, "read": False, "hide_to": False, "hide_from": False,
            }
            if images:
                letter["images"] = images
            era, year = clean_era(era, year)
            if era:
                letter["era"], letter["year"] = era, year
            self.letters.append(letter)
            dropped = self.letters[:-MAX_LETTERS]
            del self.letters[:-MAX_LETTERS]
            self._forget_images(dropped)
            self._last_send[sender] = now
            self.save()
            return letter

    def mark_read(self, letter_id, name):
        with self.lock:
            for l in self.letters:
                if l["id"] == letter_id and l["to"] == name and not l["read"]:
                    l["read"] = True
                    self.save()
                    return True
        return False

    def delete(self, letter_id, name, is_gm=False):
        with self.lock:
            for l in self.letters:
                if l["id"] != letter_id:
                    continue
                if is_gm and l["to"] != name and l["from"] != name:
                    l["hide_to"] = l["hide_from"] = True
                if l["to"] == name:
                    l["hide_to"] = True
                if l["from"] == name:
                    l["hide_from"] = True
                gone = [x for x in self.letters if x["hide_to"] and x["hide_from"]]
                self.letters = [x for x in self.letters if not (x["hide_to"] and x["hide_from"])]
                self._forget_images(gone)
                self.save()
                return True
        return False

    def _forget_images(self, removed):
        """양쪽 다 지워 사라진 편지의 첨부 이미지를, 다른 편지(여러 명에게 보낸 같은 편지)가 더 쓰지 않으면 지웁니다."""
        urls = {u for l in removed for u in l.get("images", [])}
        if not urls:
            return
        still = {u for l in self.letters for u in l.get("images", [])}
        for u in urls - still:
            name = os.path.basename(u)
            try:
                os.remove(os.path.join(IMAGE_DIR, name))
            except OSError:
                pass

    # ---- 화면에 보낼 목록 (익명/랜덤은 보는 사람에 따라 가립니다) ----
    @staticmethod
    def _view(l, me, is_gm):
        v = {"id": l["id"], "text": l["text"], "at": l["at"], "read": l["read"],
             "anonymous": l["anonymous"], "random": l["random"], "images": l.get("images", []),
             "era": l.get("era"), "year": l.get("year")}
        v["from"] = l["from"] if (is_gm or not l["anonymous"] or l["from"] == me) else None
        v["to"] = l["to"] if (is_gm or not l["random"] or l["to"] == me) else None
        return v

    def payload(self, me, is_gm=False):
        inbox = [self._view(l, me, is_gm) for l in self.letters if l["to"] == me and not l["hide_to"]]
        outbox = [self._view(l, me, is_gm) for l in self.letters if l["from"] == me and not l["hide_from"]]
        data = {"me": me, "inbox": inbox[::-1], "outbox": outbox[::-1], "eras": eras_payload(),
                "unread": sum(1 for l in inbox if not l["read"])}
        if is_gm:
            data["all"] = [self._view(l, me, True) for l in self.letters][::-1][:500]
        return data


_BOX = None


def shared_mailbox() -> Mailbox:
    global _BOX
    if _BOX is None:
        _BOX = Mailbox()
    return _BOX
