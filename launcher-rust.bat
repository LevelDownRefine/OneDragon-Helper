@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONUTF8=1"
pushd "%~dp0" || exit /b 1

set "rust_python="
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" set "rust_python=%VIRTUAL_ENV%\Scripts\python.exe"
if defined rust_python goto run
set "rust_search=%CD%"

:find_venv
if exist "%rust_search%\.venv\Scripts\python.exe" (
    set "rust_python=%rust_search%\.venv\Scripts\python.exe"
    goto run
)
for %%I in ("%rust_search%\..") do set "rust_parent=%%~fI"
if "%rust_parent%"=="%rust_search%" goto use_path
set "rust_search=%rust_parent%"
goto find_venv

:use_path
where python >nul 2>&1 || goto missing_python
set "rust_python=python"

:run
if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
"%rust_python%" tools\run_rust_gui.py %*
set "rust_exit=%ERRORLEVEL%"
if not "%rust_exit%"=="0" (
    echo.
    echo Rust GUI 启动失败，请检查上方错误。首次启动需要 Rust、MSVC 和项目 Python 依赖。
    pause
)
popd
exit /b %rust_exit%

:missing_python
echo 未找到 Python。请先运行 uv sync 安装项目环境。
pause
popd
exit /b 1
