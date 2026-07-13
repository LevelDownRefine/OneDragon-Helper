@echo off
chcp 65001 >nul
setlocal

:: 检测是否已管理员身份，没有就自动提权
fltmc >nul 2>&1 || (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process cmd -ArgumentList '/c ""%~f0""' -Verb RunAs"
    exit
)

:: 获取当前脚本所在目录
set "base=%~dp0"

:: 加载环境（venv + 代理）
set "env_script=%base%env.bat"
if exist "%env_script%" (
    echo [INFO] 加载环境: %env_script%
    call "%env_script%"
) else (
    echo [WARN] 未找到 env.bat，使用当前环境
)

:: 启动 GUI
python "%base%src\gui_launcher.py"

endlocal