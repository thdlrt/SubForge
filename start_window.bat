@echo off
setlocal

cd /d "%~dp0"
title AiText - Window Launcher

set "CONDA_BAT="

if defined AITEXT_CONDA_BAT if exist "%AITEXT_CONDA_BAT%" set "CONDA_BAT=%AITEXT_CONDA_BAT%"

if not defined CONDA_BAT if exist "%UserProfile%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%UserProfile%\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%UserProfile%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%UserProfile%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "C:\ProgramData\miniconda3\condabin\conda.bat" set "CONDA_BAT=C:\ProgramData\miniconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "C:\ProgramData\anaconda3\condabin\conda.bat" set "CONDA_BAT=C:\ProgramData\anaconda3\condabin\conda.bat"

if not defined CONDA_BAT (
    echo [ERROR] 未找到 conda.bat。
    echo 请先安装 Conda，或设置环境变量 AITEXT_CONDA_BAT 指向 conda.bat。
    pause
    exit /b 1
)

call "%CONDA_BAT%" activate aiText
if errorlevel 1 (
    echo [ERROR] 激活 Conda 环境 aiText 失败。
    echo 请确认该环境已创建，或修改脚本中的环境名。
    pause
    exit /b 1
)

python -c "import webview" 1>nul 2>nul
if errorlevel 1 (
    echo [ERROR] 当前环境缺少 pywebview，无法使用窗口模式。
    echo 请执行: pip install pywebview
    pause
    exit /b 1
)

if defined AITEXT_DRY_RUN (
    echo [OK] dry run success
    echo [OK] conda: %CONDA_BAT%
    echo [OK] cwd: %CD%
    exit /b 0
)

python app.py --window %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] 启动失败，退出码: %EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%