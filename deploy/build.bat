@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 检测 Python 解释器：优先项目 venv 的 python.exe（确保依赖与开发环境一致），
REM 找不到 venv 时回退到 uv run（需注意 uv 是否在 PATH 中）。
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    set "PY=%VENV_PY% -m PyInstaller"
) else (
    set "PY=uv run pyinstaller"
)

echo ============================================
echo   OneDragon-Helper 打包脚本
echo ============================================
echo.

REM 清理上一轮产物，避免 PyInstaller COLLECT 步骤因旧目录残留而失败
if exist "%~dp0dist" rmdir /S /Q "%~dp0dist"

echo [1/4] 构建 GUI 主程序 (onedir)...
%PY% --noconfirm --clean "OneDragon-Helper.spec"
if errorlevel 1 (
    echo [ERROR] GUI 构建失败
    pause
    exit /b 1
)

echo.
echo [2/4] 构建 Runner (onefile)...
%PY% --noconfirm --clean "OneDragon-Helper-Runner.spec"
if errorlevel 1 (
    echo [ERROR] Runner 构建失败
    pause
    exit /b 1
)

echo.
echo [3/4] 整合：将 Runner 拷入 GUI 目录...
set "GUI_DIR=%~dp0dist\OneDragon-Helper"
set "RUNNER_EXE=%~dp0dist\OneDragon-Helper-Runner.exe"
if not exist "%RUNNER_EXE%" (
    echo [ERROR] 未找到 Runner exe: %RUNNER_EXE%
    pause
    exit /b 1
)
copy /Y "%RUNNER_EXE%" "%GUI_DIR%\"
if errorlevel 1 (
    echo [ERROR] 拷贝 Runner 失败
    pause
    exit /b 1
)

echo.
echo [4/4] 拷贝 config 模板和 assets 到 exe 同级目录...
set "SRC_CONFIG=%~dp0..\config"
set "SRC_ASSETS=%~dp0..\assets"
set "DST_CONFIG=%GUI_DIR%\config"
set "DST_ASSETS=%GUI_DIR%\assets"

xcopy /E /I /Y "%SRC_CONFIG%" "%DST_CONFIG%" >nul
if errorlevel 1 (
    echo [ERROR] 拷贝 config 失败
    pause
    exit /b 1
)
xcopy /E /I /Y "%SRC_ASSETS%" "%DST_ASSETS%" >nul
if errorlevel 1 (
    echo [ERROR] 拷贝 assets 失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   输出目录: %GUI_DIR%
echo   - OneDragon-Helper.exe        (GUI 主程序)
echo   - OneDragon-Helper-Runner.exe  (脚本运行器)
echo   - config\                      (配置目录)
echo   - assets\                      (资源目录)
echo ============================================
echo.
pause
