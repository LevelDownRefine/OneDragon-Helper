:: 获取当前脚本所在目录
set "base=%~dp0"
:: 拼接目标脚本路径
set "env_script=%base%OneDragon-ScriptChainer\.venv\Scripts\activate.bat"
:: 执行目标脚本
call "%env_script%"

set http_proxy=http://127.0.0.1:7890
set https_proxy=http://127.0.0.1:7890