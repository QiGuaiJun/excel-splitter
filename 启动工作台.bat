@echo off
cd /d %~dp0
title Excel Splitter Workbench

rem ---- find a usable Python (prefer the py launcher) ----
set "PYCMD="
py -3 --version >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
    echo.
    echo [ERROR] Python was not found on this computer.
    echo Please install Python 3.9+ from https://www.python.org
    echo and tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

rem ---- install dependencies on first run ----
%PYCMD% -c "import flask, pandas, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo First run: installing dependencies, please wait...
    %PYCMD% -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   Workbench is starting... the browser will open shortly.
echo   Keep THIS window open; close it to stop the workbench.
echo ============================================================
%PYCMD% app.py
pause
