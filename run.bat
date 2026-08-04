@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "APP_DIR=%~dp0"
set "PYTHONHOME="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
call "%APP_DIR%start_app.bat" --check
if errorlevel 1 exit /b %ERRORLEVEL%
set "PYTHONPATH=%APP_DIR%src"

if "%~1"=="" (
  echo Usage: run.bat select-candidates --store "Shopee-..." --count 1
  exit /b 0
)

if exist "%APP_DIR%.venv\Scripts\python.exe" (
  "%APP_DIR%.venv\Scripts\python.exe" -X utf8 -m shopee_listing_app %*
) else if exist "%APP_DIR%.runtime\python.exe" (
  "%APP_DIR%.runtime\python.exe" -X utf8 -m shopee_listing_app %*
) else (
  py -3 -X utf8 -m shopee_listing_app %*
)
exit /b %ERRORLEVEL%
