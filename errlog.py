# -*- coding: utf-8 -*-
"""
errlog.py
=========
오류 기록 : 서버에서 난 오류와 참가자 화면(브라우저)에서 난 오류를 날짜별 파일(logs/errors_YYYY-MM-DD.log)에
한 줄씩 남기고, 운영진 방 설정에서 최근 오류를 볼 수 있게 요약해 줍니다.

- 파일은 14일치만 남기고 오래된 건 지워요(logs/ 폴더는 git에 올리지 않아요).
- 비밀번호 · 키 같은 값은 남기지 않아요(오류 문장과 위치만).
"""
import collections
import json
import os
import threading
import time

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
KEEP_DAYS = 14
MAX_LEN = 600

_lock = threading.Lock()
_recent = collections.deque(maxlen=300)   # 최근 기록(서버를 다시 켜면 오늘 파일에서 다시 읽어요)


def _path(day=None):
    return os.path.join(_DIR, f"errors_{day or time.strftime('%Y-%m-%d')}.log")


def _clip(v, n=MAX_LEN):
    v = str(v if v is not None else "")
    return v if len(v) <= n else v[:n] + "…"


def record(kind, message, where="", detail=""):
    """kind : server(서버) / client(참가자 화면)."""
    item = {"at": time.time(), "kind": _clip(kind, 20), "message": _clip(message), "where": _clip(where, 200), "detail": _clip(detail, 4000)}
    with _lock:
        _recent.append(item)
        try:
            os.makedirs(_DIR, exist_ok=True)
            with open(_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return item


def summary(hours=24, limit=8):
    since = time.time() - hours * 3600
    with _lock:
        items = [x for x in _recent if x["at"] >= since]
    by_kind = collections.Counter(x["kind"] for x in items)
    recent = [{k: x[k] for k in ("at", "kind", "message", "where")} for x in reversed(items[-limit:])]
    return {"count": len(items), "server": by_kind.get("server", 0), "client": by_kind.get("client", 0), "recent": recent, "hours": hours}


def startup():
    """오래된 파일 정리 + 오늘 기록 다시 읽기."""
    try:
        os.makedirs(_DIR, exist_ok=True)
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(_DIR):
            p = os.path.join(_DIR, name)
            if name.startswith("errors_") and os.path.getmtime(p) < cutoff:
                os.remove(p)
        for day in (time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)), time.strftime("%Y-%m-%d")):
            if os.path.exists(_path(day)):
                with open(_path(day), "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            _recent.append(json.loads(line))
                        except ValueError:
                            pass
    except OSError:
        pass
