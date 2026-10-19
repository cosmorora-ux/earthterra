# -*- coding: utf-8 -*-
"""
backup.py
=========
자동 백업 : 서버 컴퓨터에만 있는 실데이터(캐릭터 · 편지 · 공지 · 마이룸 · LOOP 기록 · 올린 그림/소리 등)를
정해진 시간마다 zip 하나로 묶어 backups/ 폴더에 보관합니다(최근 N개만 남김).

- 서버를 켤 때 한 번, 그 뒤로 BACKUP_HOURS 시간마다 만듭니다.
- 다른 곳(클라우드 드라이브 폴더 등)에도 한 벌 더 두려면 backup_dir.txt 첫 줄에 그 폴더 경로를 적어 두세요.
  (예: C:\\Users\\이름\\OneDrive\\earthterra_backup) — 그 폴더에도 같은 zip을 복사합니다.
- 복원 : 서버를 끈 뒤 zip을 프로젝트 폴더에 그대로 풀면 됩니다(같은 이름의 파일을 덮어씁니다).
"""

import os
import shutil
import time
import zipfile

_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(_DIR, "backups")
BACKUP_HOURS = 6        # 몇 시간마다
KEEP = 20               # 최근 몇 개를 남길지(6시간마다면 약 5일치)

# 실데이터 파일(없으면 건너뜀)
DATA_FILES = [
    "characters.json", "formulas.json", "formula_profiles.json", "rooms.json", "room_runtime.pkl",
    "shop.json", "notices.json", "sfx.json", "letters.json", "dorms.json", "site_settings.json",
    "world.json", "loop_runs.json", "loop_content.json", "gm_password.txt", "secret_key.txt",
]
# 운영 중에 올린 파일 폴더
DATA_DIRS = [
    "static/avatars", "static/sound_effects", "static/mail_images", "static/dorm_assets", "static/dorm_music",
    "static/shop_icons", "static/map_bg", "static/world", "static/music", "static/skill_fx",
]


LAST = {"extra_ok": None, "extra_err": ""}   # 이번 실행에서 마지막 추가 폴더 복사 결과


def _extra_dir():
    try:
        with open(os.path.join(_DIR, "backup_dir.txt"), "r", encoding="utf-8") as f:
            p = f.readline().strip().strip('"')
            return p or None
    except OSError:
        return None


def make_backup():
    """zip 하나를 만들고 경로를 돌려줍니다. 실패해도 서버는 계속 돌아가요."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = time.strftime("earthterra_%Y%m%d_%H%M%S.zip")
    path = os.path.join(BACKUP_DIR, name)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in DATA_FILES:
            p = os.path.join(_DIR, f)
            if os.path.isfile(p):
                z.write(p, f)
        for d in DATA_DIRS:
            root = os.path.join(_DIR, d)
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for fn in files:
                    full = os.path.join(dp, fn)
                    z.write(full, os.path.relpath(full, _DIR))
    os.replace(tmp, path)
    # 오래된 것 정리
    olds = sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("earthterra_") and x.endswith(".zip"))
    for x in olds[:-KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, x))
        except OSError:
            pass
    # 다른 곳에도 한 벌
    extra = _extra_dir()
    if extra:
        try:
            os.makedirs(extra, exist_ok=True)
            shutil.copy2(path, os.path.join(extra, name))
            ex = sorted(x for x in os.listdir(extra) if x.startswith("earthterra_") and x.endswith(".zip"))
            for x in ex[:-KEEP]:
                os.remove(os.path.join(extra, x))
            LAST.update(extra_ok=True, extra_err="")
        except OSError as e:
            LAST.update(extra_ok=False, extra_err=str(e)[:200])
            print(f"[backup] 추가 폴더 복사 실패: {e}")
    return path


def status():
    """운영진 방 설정 '백업' 카드 : 마지막 백업 시각 · 크기 · 보관 개수 · 다른 곳 복사 상태."""
    try:
        zips = sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("earthterra_") and x.endswith(".zip"))
    except OSError:
        zips = []
    last = zips[-1] if zips else None
    out = {"count": len(zips), "keep": KEEP, "hours": BACKUP_HOURS, "last_at": None, "last_size": 0,
           "extra_dir": _extra_dir(), "extra_ok": LAST["extra_ok"], "extra_err": LAST["extra_err"]}
    if last:
        p = os.path.join(BACKUP_DIR, last)
        out["last_at"] = os.path.getmtime(p)
        out["last_size"] = os.path.getsize(p)
    if out["extra_dir"] and out["extra_ok"] is None:
        out["extra_ok"] = os.path.isdir(out["extra_dir"])
    return out
