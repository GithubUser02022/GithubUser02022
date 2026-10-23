@echo off
chcp 936 >nul
cd /d "%~dp0"
start "" pythonw.exe "%~dp0ClassHub.py"
