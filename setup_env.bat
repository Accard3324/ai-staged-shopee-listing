@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "APP_DIR=%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "BOOTSTRAP="

if exist "%APP_DIR%.venv\Scripts\python.exe" (
  "%APP_DIR%.venv\Scripts\python.exe" -c "import encodings" >nul 2>&1 && exit /b 0
)
if exist "%APP_DIR%.runtime\python.exe" (
  "%APP_DIR%.runtime\python.exe" -c "import encodings; import shopee_listing_app" >nul 2>&1 && exit /b 0
)

call :try_bootstrap py -3
if not defined BOOTSTRAP call :try_bootstrap python
if defined BOOTSTRAP (
  %BOOTSTRAP% -m venv "%APP_DIR%.venv"
  if errorlevel 1 exit /b 1
  "%APP_DIR%.venv\Scripts\python.exe" -c "import encodings" || exit /b 1
  echo Project virtual environment created: %APP_DIR%.venv
  exit /b 0
)

echo No supported system Python was found. Installing project-local portable Python 3.12.10...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%scripts\setup_portable_python.ps1"
if errorlevel 1 exit /b 1
echo Project-local portable Python created: %APP_DIR%.runtime\python.exe
exit /b 0

:try_bootstrap
set "COMMAND=%~1"
set "ARGS=%~2"
set "ACTUAL_PATH="
for /f "usebackq delims=" %%P in (`%COMMAND% %ARGS% -c "import sys; print(sys.executable)" 2^>nul`) do set "ACTUAL_PATH=%%P"
if not defined ACTUAL_PATH exit /b 0
echo %ACTUAL_PATH% | findstr /I /C:"WXWork" /C:"WeComAgent" /C:"企业微信" >nul && exit /b 0
%COMMAND% %ARGS% -c "import encodings" >nul 2>&1 || exit /b 0
set "BOOTSTRAP=%COMMAND% %ARGS%"
exit /b 0
