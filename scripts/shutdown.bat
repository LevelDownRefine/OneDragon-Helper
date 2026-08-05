﻿@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "SENTINEL=%TEMP%\odh_shutdown_armed.tmp"

REM 子进程入口：由顶层 start 拉起，在可见控制台窗口里跑倒计时。
if /i "%~1"=="countdown" goto :countdown

REM 顶层入口：可能被脚本链以无窗口方式（CREATE_NO_WINDOW）拉起，
REM 因此用 start 再开一个可见控制台窗口承担倒计时与取消入口。
REM 只有倒计时正常结束才会武装「关机哨兵」，父进程据此才真正关机；
REM 关掉倒计时窗口或按 [C] 都不会写哨兵，于是本进程退出即代表取消。
if exist "%SENTINEL%" del /q "%SENTINEL%" >nul 2>&1
echo 正在弹出关机倒计时窗口（关闭该窗口即可取消关机）...
start "" /wait "%~f0" countdown
if exist "%SENTINEL%" (
    del /q "%SENTINEL%" >nul 2>&1
    shutdown /s /f /t 0
) else (
    echo 已取消关机。
    timeout /t 3 >nul
)
goto :eof

:countdown
set "SEC=30"
:loop
cls
echo ============================================
echo   电脑将在 %SEC% 秒后关机
echo   按 [C] 立即取消，或关闭本窗口取消
echo ============================================
choice /c sc /n /t 1 /d s >nul
if errorlevel 2 (
    echo 已取消，窗口即将关闭。
    timeout /t 2 >nul
    exit /b 1
)
set /a SEC-=1
if %SEC% leq 0 (
    REM 倒计时正常结束才武装关机；关窗 / 按 C 不会走到这里。
    echo armed > "%SENTINEL%"
    exit /b 0
)
goto loop
