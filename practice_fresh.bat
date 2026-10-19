@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 실제 데이터를 지금 상태로 다시 복사한 뒤 연습 서버를 켜요
python practice.py --fresh
pause
