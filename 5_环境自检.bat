@echo off
chcp 936 >nul
cd /d "%~dp0"
python ClassHub.py --check
echo.
pause
