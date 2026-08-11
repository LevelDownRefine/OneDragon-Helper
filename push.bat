@echo off
chcp 65001 >nul
setlocal EnableExtensions

:: 用法：push.bat "commit_info"（commit_info 为 git commit 的 -m 消息）
if "%~1"=="" (
    echo [ERROR] 用法: push.bat "commit_info"
    echo         commit_info 为 git commit 的 -m 消息
    exit /b 1
)
set "commit_info=%~1"

set "base=%~dp0"
:: 加载环境
set "env_script=%base%env.bat"
if exist "%env_script%" (
    echo [INFO] 加载环境: %env_script%
    call "%env_script%"
) else (
    echo [WARN] 未找到 env.bat，使用当前环境
)

:: 1. 格式化代码
echo [INFO] 格式化代码: ruff format .
ruff format .
if errorlevel 1 (
    echo [ERROR] ruff format 失败，已中止
    exit /b 1
)

:: 2. 暂存全部改动（含 ruff format 产生的修改）
echo [INFO] 暂存全部改动: git add -A
git add -A
if errorlevel 1 (
    echo [ERROR] git add 失败，已中止
    exit /b 1
)

:: 3. 提交
echo [INFO] 提交: git commit -m "%commit_info%"
git commit -m "%commit_info%"
if errorlevel 1 (
    echo [ERROR] git commit 失败（可能没有改动），已中止
    exit /b 1
)

:: 4. 推送
echo [INFO] 推送: git push
git push
set "push_code=%errorlevel%"
if not "%push_code%"=="0" (
    echo [ERROR] git push 失败，退出码: %push_code%
)

endlocal & exit /b %push_code%
