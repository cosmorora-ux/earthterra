# -*- coding: utf-8 -*-
"""
연습 서버
=========
실제 서버(5000번)와 완전히 따로 도는 연습용 서버를 5001번으로 켭니다.
새 기능을 미리 써 보거나, 전투 · 편지 · LOOP를 마음껏 눌러 봐도 실제 데이터는 그대로예요.

    python practice.py           연습 서버 켜기(코드는 늘 지금 것으로 맞춰요)
    python practice.py --fresh   실제 데이터를 지금 상태로 다시 복사해 온 뒤 켜기

- 연습 폴더 : 이 폴더 옆의 earthterra_practice (처음 켤 때 실제 데이터를 한 번 복사해 와요)
- 주소 : http://localhost:5001  (화면 위쪽에 '연습 서버' 표시가 붙어요)
- 연습 서버는 자동 백업을 하지 않고, 운영진 비밀번호는 실제 서버와 같아요.
- 끄기 : 이 창에서 Ctrl + C
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(os.path.dirname(ROOT), os.path.basename(ROOT) + "_practice")
PORT = os.environ.get("PRACTICE_PORT", "5001")

sys.path.insert(0, ROOT)
import backup  # noqa: E402  (실데이터 목록을 같이 써요)

# 연습 서버로 복사하지 않는 것 : 서명 키(로그인이 섞이지 않게) · 백업 설정
SKIP_DATA = {"secret_key.txt"}


def code_files():
    try:
        out = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True, encoding="utf-8")
        return [f for f in out.splitlines() if f]
    except Exception:
        files = []
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "backups", "logs", "__pycache__")]
            for n in names:
                files.append(os.path.relpath(os.path.join(base, n), ROOT))
        return files


def copy(rel):
    src, dst = os.path.join(ROOT, rel), os.path.join(DEST, rel)
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def main():
    if os.path.exists(os.path.join(ROOT, "practice.txt")):
        print("[연습] 여기는 이미 연습 폴더예요. 실제 서버 폴더에서 실행해 주세요.")
        return 1
    fresh = "--fresh" in sys.argv[1:] or not os.path.isdir(DEST)
    data = set(backup.DATA_FILES)
    os.makedirs(DEST, exist_ok=True)
    # 1) 코드 : 늘 지금 것으로(실데이터 파일은 건너뜀)
    for rel in code_files():
        if rel not in data and not rel.startswith("backups/"):
            copy(rel)
    # 2) 실데이터 : 처음이거나 --fresh일 때만 지금 상태로 복사
    if fresh:
        print("[연습] 실제 데이터를 복사하는 중…")
        for rel in backup.DATA_FILES:
            if rel in SKIP_DATA:
                continue
            p = os.path.join(DEST, rel)
            if os.path.isfile(p):
                os.remove(p)
            copy(rel)
        for d in backup.DATA_DIRS:
            src = os.path.join(ROOT, d)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(DEST, d), dirs_exist_ok=True)
    with open(os.path.join(DEST, "practice.txt"), "w", encoding="utf-8") as f:
        f.write("이 폴더는 연습 서버예요. 실제 서버 폴더가 아니에요.\n")
    print(f"[연습] 폴더 : {DEST}")
    print(f"[연습] 주소 : http://localhost:{PORT}   (끄기 : Ctrl + C)")
    env = dict(os.environ, PORT=PORT, EARTHTERRA_PRACTICE="1", PYTHONIOENCODING="utf-8")
    try:
        return subprocess.call([sys.executable, "webapp.py"], cwd=DEST, env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
