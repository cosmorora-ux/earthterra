@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 자동 점검을 시작해요...
python tests\run_tests.py
echo.
pause
