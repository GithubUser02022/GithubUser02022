@echo off
chcp 936 >nul
cd /d "%~dp0"
echo ============================================
echo  ClassHub 打包成 EXE
echo ============================================
echo.
echo 打包形态：
echo   1 = 单文件版（一个 exe，启动略慢，杀软误报率高）
echo   2 = 文件夹版（一个文件夹里一堆 dll，启动快，误报率低）[推荐]
echo.
set MODE=2
set /p MODE=选 1 还是 2（直接回车用 2）：

echo.
echo 1/3 安装打包依赖……
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo 2/3 生成图标……
python make_icon.py

echo 3/3 开始打包（1-3 分钟，别关窗口）……
if "%MODE%"=="1" (
    python -m PyInstaller --noconfirm --clean --onefile --noupx --windowed ^
        --name ClassHub --icon icon.ico --hidden-import win32timezone ^
        --hidden-import chub_shell ClassHub.py
) else (
    python -m PyInstaller --noconfirm --clean --onedir --noupx --windowed ^
        --name ClassHub --icon icon.ico --hidden-import win32timezone ^
        --hidden-import chub_shell ClassHub.py
)

if errorlevel 1 (
    echo.
    echo 打包失败，看上面的报错。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo 复制源码到 dist（这样设置里的"源码"页才有东西可看）
echo ============================================
set "SRCDIR=dist\源码"
if "%MODE%"=="2" set "SRCDIR=dist\ClassHub\源码"
if not exist "%SRCDIR%" mkdir "%SRCDIR%"
copy /y *.py "%SRCDIR%\" >nul
copy /y 使用说明.md "%SRCDIR%\" >nul
copy /y requirements.txt "%SRCDIR%\" >nul
echo   已复制到 %SRCDIR%\
echo   共复制 %CD% 下的 .py / .md / .txt
echo.
echo 好了！
if "%MODE%"=="1" (
    echo   单文件版：dist\ClassHub.exe
    echo   拷走时只拷这一个 exe 就行。
    echo   源码目录：dist\源码\
) else (
    echo   文件夹版：dist\ClassHub\ClassHub.exe
    echo   拷走时把整个 ClassHub 文件夹一起拷，少一个文件都跑不起来。
    echo   源码目录：dist\ClassHub\源码\
)
echo.
echo 配置和日志会生成在 exe 的同一个文件夹里（config.json / sync.log）。
echo 源码在「源码」子文件夹里，设置窗口 -^> 帮助 -^> 源码 可以直接看。
if "%MODE%"=="2" start "" explorer "%~dp0dist"
echo.
pause
