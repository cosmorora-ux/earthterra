@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 연습 서버를 켜요 (주소: http://localhost:5001 , 끄기: Ctrl + C)
python practice.py %*
pause
