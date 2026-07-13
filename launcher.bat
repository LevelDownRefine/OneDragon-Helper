@echo off
chcp 65001 >nul
setlocal

:: 管理员提权
fltmc >nul 2>&1 || (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process cmd -ArgumentList '/c ""%~f0""' -Verb RunAs"
    exit
)

set "base=%~dp0"
:: 将项目根目录加入Python模块搜索路径，才能使用 python -m
set "PYTHONPATH=%base%;%PYTHONPATH%"

:: 加载环境
set "env_script=%base%env.bat"
if exist "%env_script%" (
    echo [INFO] 加载环境: %env_script%
    call "%env_script%"
) else (
    echo [WARN] 未找到 env.bat，使用当前环境
)

:: 模块启动，等价 src/gui_launcher.py → 模块名 src.gui_launcher
python -m src.gui_launcher

endlocal