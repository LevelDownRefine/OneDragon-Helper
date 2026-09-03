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

echo [1/5] 构建 GUI 主程序 (onedir)...
%PY% --noconfirm --clean "OneDragon-Helper.spec"
if errorlevel 1 (
    echo [ERROR] GUI 构建失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [2/5] 构建 Runner (onefile)...
%PY% --noconfirm --clean "OneDragon-Helper-Runner.spec"
if errorlevel 1 (
    echo [ERROR] Runner 构建失败
    if not defined CI pause
    exit /b 1
)

echo.
echo [3/5] 整合：将 Runner 拷入 GUI 目录...
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

REM onefile 构建在 dist/ 顶层生成的 Runner 已拷入 GUI 目录，删除顶层冗余残留，
REM 避免发布包重复携带（节省 ~21M）。Runner 真实位置：<GUI_DIR>\OneDragon-Helper-Runner.exe
if exist "%RUNNER_EXE%" del /Q "%RUNNER_EXE%"

echo.
echo [4/5] 拷贝 config 模板、assets 到 exe 同级目录...
set "SRC_CONFIG=%~dp0..\config"
set "SRC_ASSETS=%~dp0..\assets"
set "DST_CONFIG=%GUI_DIR%\config"
set "DST_ASSETS=%GUI_DIR%\assets"

REM 整体拷贝 config（含共享资源：dungeon_list.yml / weekly_timeouts.yml / script_chain / BGI_User 等）
xcopy /E /I /Y "%SRC_CONFIG%" "%DST_CONFIG%" >nul
if errorlevel 1 (
    echo [ERROR] 拷贝 config 失败
    if not defined CI pause
    exit /b 1
)
REM 安全：绝不要把开发机的个人配置打进包（config.yml / config.yml.bak 含账号、路径等私密，
REM gui_state.json 是本地 UI 状态）。源文件保持不动，仅从打包产物中清除。
if exist "%DST_CONFIG%\config.yml" del /Q "%DST_CONFIG%\config.yml"
if exist "%DST_CONFIG%\config.yml.bak" del /Q "%DST_CONFIG%\config.yml.bak"
if exist "%DST_CONFIG%\gui_state.json" del /Q "%DST_CONFIG%\gui_state.json"
REM 改用模板生成干净的默认 config.yml（不含任何个人信息），打包产物开箱即用
copy /Y "%SRC_CONFIG%\config.example.yml" "%DST_CONFIG%\config.yml" >nul
if errorlevel 1 (
    echo [ERROR] 生成默认 config.yml 失败
    if not defined CI pause
    exit /b 1
)
xcopy /E /I /Y "%SRC_ASSETS%" "%DST_ASSETS%" >nul
if errorlevel 1 (
    echo [ERROR] 拷贝 assets 失败
    if not defined CI pause
    exit /b 1
)
REM QML 界面文件：GUI 已迁移到 QML（launcher.py 用 QQmlApplicationEngine 加载
REM src/gui/qml/main.qml，且 main.qml 以相对 source 引用其余 .qml）。冻结模式下
REM resolve_script_path 按 exe 同级目录解析，故必须随包发布到 <exedir>/src/gui/qml/，
REM 否则启动即 assert 崩溃。
set "SRC_QML=%~dp0..\src\gui\qml"
set "DST_QML=%GUI_DIR%\src\gui\qml"
xcopy /E /I /Y "%SRC_QML%" "%DST_QML%" >nul
if errorlevel 1 (
    echo [ERROR] 拷贝 QML 失败
    if not defined CI pause
    exit /b 1
)
REM 用户脚本（如 wait_until_0410 等待到每日重置）的能力已由 launcher 的「定时计划」
REM 内置（运行前阻塞到目标时刻，默认 04:10），无需再随包发布松散脚本文件。

echo.
echo [5/5] 验证打包产物 exe（CI 下失败即阻断构建；本地手动运行仅提示，不阻断）...
pushd "%~dp0.."
REM 只测与打包产物相关的 exe 集成测试（tests/exe/test_*_exe.py：Runner + GUI），源码单测由 CI 覆盖。
REM 经 python -m 从仓库根运行（上方 pushd 使 cwd=仓库根，已在 sys.path，可 import src.*）；
REM 自动在 deploy/dist 找到刚打好的 exe。需以管理员运行，否则因 uac_admin manifest 整文件 skip。
if exist "%VENV_PY%" (
    "%VENV_PY%" -m unittest discover -s tests -p "test_*_exe.py"
) else (
    uv run python -m unittest discover -s tests -p "test_*_exe.py"
)
REM exe 测试失败需在 CI 阻断构建（errorlevel 1 → exit /b 1）；本地手动运行仍保持非阻断（仅提示）。
if errorlevel 1 (
    echo [ERROR] exe 集成测试失败
    if not defined CI ( pause ) else ( exit /b 1 )
)
popd

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
if not defined CI pause
