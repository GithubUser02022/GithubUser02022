@echo off
chcp 936 >nul
cd /d "%~dp0"
echo ============================================
echo  ClassHub 依赖安装（只需做一次）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo 没找到 Python，请先到 https://www.python.org/downloads/ 安装，
    echo 安装时务必勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

echo 正在安装依赖，稍等……
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo 安装出错了，截图上面的红色报错再排查。
) else (
    echo.
    echo 完成！接下来双击 2_启动(静默^).bat 就能用。
)
echo.
pause
