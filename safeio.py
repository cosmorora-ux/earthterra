"""
JSON 저장 공용 함수 : 여러 사람이 동시에 저장해도 파일이 깨지지 않게 합니다.
- 저장은 한 번에 하나씩(잠금)
- 임시 파일에 다 쓴 뒤 바꿔 끼우기(저장 도중 꺼져도 원래 파일은 그대로)
- 다른 요청이 같은 자료를 고치는 중이라 직렬화가 실패하면 잠깐 뒤 다시 시도
- Windows에서 백신 등이 파일을 잠깐 잡고 있어 바꿔 끼우기가 실패하면 잠깐 뒤 다시 시도
"""
import json
import os
import threading
import time

_LOCK = threading.RLock()


def write_json(path, data, indent=2):
    with _LOCK:
        text = None
        for attempt in range(5):
            try:
                text = json.dumps(data, ensure_ascii=False, indent=indent)
                break
            except RuntimeError:  # dictionary changed size during iteration
                time.sleep(0.02)
        if text is None:
            text = json.dumps(data, ensure_ascii=False, indent=indent)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)


def write_bytes(path, blob):
    with _LOCK:
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)
