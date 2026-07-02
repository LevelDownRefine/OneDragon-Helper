@echo off
chcp 65001
:: 检测是否已管理员身份，没有就自动提权
fltmc >nul 2>&1 || (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process cmd -ArgumentList '/c ""%~f0""' -Verb RunAs"
    exit
)

:: 获取当前脚本所在目录
set "base=%~dp0"
:: 拼接目标脚本路径
set "env_script=%base%OneDragon-ScriptChainer\.venv\Scripts\activate.bat"


if not exist "%env_script%" (
    echo 找不到 script/env.bat
    pause
    exit /b
)

:: 调用执行，执行后返回本脚本上下文
call "%env_script%"
call python %base%launcher.py