:: 工作树可复用父目录环境；已有激活环境优先。
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\activate.bat" goto proxy
set "odh_env_search=%~dp0"

:find_env
if exist "%odh_env_search%\.venv\Scripts\activate.bat" (
    call "%odh_env_search%\.venv\Scripts\activate.bat"
    goto proxy
)
for %%I in ("%odh_env_search%\..") do set "odh_env_parent=%%~fI"
if "%odh_env_parent%"=="%odh_env_search%" goto proxy
set "odh_env_search=%odh_env_parent%"
goto find_env

:proxy
set "odh_env_search="
set "odh_env_parent="

set http_proxy=http://127.0.0.1:7890
set https_proxy=http://127.0.0.1:7890
