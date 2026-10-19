# -*- coding: utf-8 -*-
"""
자동 점검 실행기
================
실제 데이터(방 · 편지 · 기록 등)를 건드리지 않도록, git에 올라간 코드만 임시 폴더에 복사해서
그 안에서 점검을 돌립니다. 끝나면 임시 폴더는 지워져요.

    python tests/run_tests.py

모두 통과하면 마지막 줄에 OK, 하나라도 실패하면 FAILED와 실패한 항목이 나와요.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tracked_files():
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8")
        return [f for f in out.splitlines() if f]
    except Exception:
        # git이 없으면 코드 파일만 직접 골라요
        files = []
        for base, dirs, names in os.walk(ROOT):
            if any(p in base for p in (".git", "backups", "__pycache__", "static")):
                continue
            for n in names:
                if n.endswith((".py", ".html")) or n in ("characters.json", "formulas.json", "formula_profiles.json"):
                    files.append(os.path.relpath(os.path.join(base, n), ROOT))
        return files


def main():
    tmp = tempfile.mkdtemp(prefix="earthterra_test_")
    try:
        for rel in tracked_files():
            if rel.startswith("static/"):
                continue
            src, dst = os.path.join(ROOT, rel), os.path.join(tmp, rel)
            if not os.path.isfile(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        # 점검 파일은 git에 올리기 전이어도 늘 최신 것으로
        shutil.copytree(os.path.join(ROOT, "tests"), os.path.join(tmp, "tests"), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        # 점검에 쓰는 것들 : 정적 파일은 읽기만 하므로 연결만, 운영진 비밀번호는 점검용 값
        try:
            os.symlink(os.path.join(ROOT, "static"), os.path.join(tmp, "static"))
        except (OSError, NotImplementedError):
            shutil.copytree(os.path.join(ROOT, "static"), os.path.join(tmp, "static"))
        with open(os.path.join(tmp, "gm_password.txt"), "w", encoding="utf-8") as f:
            f.write("test-pw-1234\n")
        env = dict(os.environ, EARTHTERRA_TEST="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=tmp, env=env)
        return r.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
