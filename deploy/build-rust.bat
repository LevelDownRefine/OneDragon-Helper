@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONUTF8=1"
pushd "%~dp0.." || exit /b 1
if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    "%VIRTUAL_ENV%\Scripts\python.exe" tools\build_rust.py %*
    goto result
)
uv run --frozen python tools\build_rust.py %*
:result
set "rust_exit=%ERRORLEVEL%"
if not "%rust_exit%"=="0" echo Rust 发布构建失败，请查看上方错误。
if not defined CI pause
popd
exit /b %rust_exit%
