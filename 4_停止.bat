@echo off
chcp 936 >nul
taskkill /im ClassHub.exe /f /t >nul 2>nul
taskkill /im pythonw.exe /fi "WINDOWTITLE eq ClassHub*" /f >nul 2>nul
echo ÒÑ·¢ËÍ½áÊøÃüÁî¡£
pause
