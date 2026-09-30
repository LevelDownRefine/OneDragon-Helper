@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "base=%~dp0"

:: 管理员提权（透传命令行参数）
fltmc >nul 2>&1 || (
    echo 正在请求管理员权限...
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c ""%~f0""' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c ""%~f0"" %*' -Verb RunAs"
    )
    exit /b
)

:: 加载环境
set "env_script=%base%env.bat"
if exist "%env_script%" (
    echo [INFO] 加载环境: %env_script%
    call "%env_script%"
) else (
    echo [WARN] 未找到 env.bat，使用当前环境
)

:: uv sync 已把 GUI 与后端安装为可编辑包，无需拼接 PYTHONPATH。
python -m gui.launcher %*

endlocal
