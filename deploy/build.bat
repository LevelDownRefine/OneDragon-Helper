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

REM UPX：两个 spec 里都已设 upx=True，但需本机存在 upx 才生效（此前一直是空转，
REM 产物完全没压缩）。用环境变量 UPX_DIR 指向 upx.exe 所在目录；未指定则交给
REM PyInstaller 从 PATH 查找。两种都找不到时不报错，只是产物退回未压缩档。
set "UPX_OPT="
if defined UPX_DIR (
    if exist "%UPX_DIR%\upx.exe" (
        set "UPX_OPT=--upx-dir "%UPX_DIR%""
    ) else (
        echo [WARN] UPX_DIR 下没有 upx.exe，本次不压缩: %UPX_DIR%
    )
)

echo ============================================
echo   OneDragon-Helper 打包脚本
echo ============================================
echo.

REM 清理上一轮产物，避免 PyInstaller COLLECT 步骤因旧目录残留而失败。
REM build/ 也必须一并清掉：PyInstaller 的 --clean 会自己删 build/<name>/localpycs，
REM 那一批文件数量多，在带批量删除确认的环境下会把构建卡死（报错而非真实失败）。
REM 用 cmd 原生 rmdir 先清空，--clean 就无旧文件可删。
if exist "%~dp0dist" rmdir /S /Q "%~dp0dist"
if exist "%~dp0build" rmdir /S /Q "%~dp0build"

echo [1/6] 构建 GUI 主程序 (onedir)...
%PY% --noconfirm --clean %UPX_OPT% "OneDragon-Helper.spec"
if errorlevel 1 (
    echo [ERROR] GUI 构建失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [2/6] 构建 Runner (onefile)...
REM 不加 --clean：它会连带清空 PyInstaller 的 bincache，而上一步 GUI 刚重建过，
REM 再清一次是重复劳动（且缓存条目多，易触发批量删除的安全确认而中断构建）。
%PY% --noconfirm %UPX_OPT% "OneDragon-Helper-Runner.spec"
if errorlevel 1 (
    echo [ERROR] Runner 构建失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [3/6] 构建独立更新器 (onefile)...
%PY% --noconfirm %UPX_OPT% "OneDragon-Helper-Updater.spec"
if errorlevel 1 (
    echo [ERROR] 更新器构建失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [4/6] 整合：将 Runner 拷入 GUI 目录...
set "GUI_DIR=%~dp0dist\OneDragon-Helper"
set "RUNNER_EXE=%~dp0dist\OneDragon-Helper-Runner.exe"
if not exist "%RUNNER_EXE%" (
    echo [ERROR] 未找到 Runner exe: %RUNNER_EXE%
    if not defined CI pause
    exit /b 1
)
copy /Y "%RUNNER_EXE%" "%GUI_DIR%\"
if errorlevel 1 (
    echo [ERROR] 拷贝 Runner 失败
    if not defined CI pause
    exit /b 1
)

copy /Y "%~dp0dist\OneDragon-Helper-Updater.exe" "%GUI_DIR%\"
if errorlevel 1 exit /b 1
del /Q "%~dp0dist\OneDragon-Helper-Updater.exe"

REM onefile 构建在 dist/ 顶层生成的 Runner 已拷入 GUI 目录，删除顶层冗余残留，
REM 避免发布包重复携带（节省 ~21M）。Runner 真实位置：<GUI_DIR>\OneDragon-Helper-Runner.exe
if exist "%RUNNER_EXE%" del /Q "%RUNNER_EXE%"

echo.
echo [5/6] 准备发布资源与版本信息...
set "CFG_PY=%VENV_PY%"
if not exist "%CFG_PY%" set "CFG_PY=python"
REM 只拷贝 Git 跟踪的模板、内置资源与 QML；用户配置由程序首启生成。
"%CFG_PY%" "%~dp0..\tools\release_package.py" prepare --package "%GUI_DIR%"
if errorlevel 1 (
    echo [ERROR] 准备发布包失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [6/6] 在临时副本验证打包产物...
REM 测试产生的配置、日志与缓存都留在临时副本，发布目录不执行程序。
"%CFG_PY%" "%~dp0..\tools\release_package.py" test --package "%GUI_DIR%"
if errorlevel 1 (
    echo [ERROR] exe 集成测试失败
    if not defined CI pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   输出目录: %GUI_DIR%
echo   - OneDragon-Helper.exe        (GUI 主程序)
echo   - OneDragon-Helper-Runner.exe  (脚本运行器)
echo   - OneDragon-Helper-Updater.exe (独立更新器)
echo   - update-manifest.json        (程序文件清单)
echo   - config\                      (配置模板与声明)
echo   - assets\                      (资源目录)
echo   - version.json                (构建版本)
echo   - README.md                    (项目说明)
echo ============================================
echo.
if not defined CI pause
