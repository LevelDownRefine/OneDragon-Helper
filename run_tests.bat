@echo off
chcp 65001 >nul
setlocal

:: 获取脚本所在目录
set "base=%~dp0"

:: 加载环境（venv + 代理）
set "env_script=%base%env.bat"
if exist "%env_script%" (
    echo [INFO] 加载环境: %env_script%
    call "%env_script%"
) else (
    echo [WARN] 未找到 env.bat，使用当前环境
)

:: 编译检查
echo.
echo [INFO] 编译检查...
python -m compileall -q -x "\.venv|\.git|__pycache__" "%base%src"
if %errorlevel% neq 0 (
    echo [FAIL] 编译失败
    exit /b 1
)

:: 运行测试（PYTHONPATH 确保 src/ 可被导入）
echo.
echo [INFO] 运行测试...
set "PYTHONPATH=%base%src"
python -m unittest discover -s "%base%tests" -p "test*.py"
if %errorlevel% neq 0 (
    echo [FAIL] 测试未通过
    exit /b 1
)

echo.
echo [OK] 全部通过
endlocal
