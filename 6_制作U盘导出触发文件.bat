@echo off
chcp 936 >nul
title 在 U 盘上放导出触发文件
cd /d "%~dp0"

echo ============================================
echo   在 U 盘根目录放一个隐藏的触发文件
echo   插上这个 U 盘，ClassHub 就会把课件文件夹
echo   拷进 U 盘（需要先在托盘菜单里勾上
echo   「U 盘导出」）
echo ============================================
echo.

set /p DRIVE=U 盘盘符（比如 E ，不要冒号）：
if "%DRIVE%"=="" goto :eof

set DRIVE=%DRIVE:~0,1%
if not exist %DRIVE%:\ (
    echo [错误] %DRIVE%: 不存在，检查一下盘符
    pause
    exit /b 1
)

set /p VAL=触发内容（直接回车用 1）：
if "%VAL%"=="" set VAL=1

echo %VAL%> "%DRIVE%:\f"
attrib +h "%DRIVE%:\f"

echo.
echo 完成：%DRIVE%:\f  （内容 "%VAL%"，已设为隐藏）
echo 拔掉再插一次就会触发导出。
echo 想取消：attrib -h %DRIVE%:\f ^&^& del %DRIVE%:\f
echo.
pause
