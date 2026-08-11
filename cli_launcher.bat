@echo off
chcp 65001 >nul
setlocal EnableExtensions

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

:: 1. 生成脚本链配置（默认 config/script_chain/today.yml，仅含当天运行脚本）
python -m src.launcher --generate-chain
if errorlevel 1 (
    echo [ERROR] 脚本链配置生成失败，已中止
    exit /b 1
)

:: 2. 运行脚本链（阻塞直至整条链结束）
python -m src.launcher --run-chain "%base%config\script_chain\today.yml"
set "run_code=%errorlevel%"

echo [INFO] 脚本链运行结束，退出码: %run_code%
endlocal & exit /b %run_code%
