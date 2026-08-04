@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "APP_DIR=%~dp0"
set "PYTHONPATH=%APP_DIR%src"
set "PYTHONHOME="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE="
set "PYTHON_ARGS="

call :choose_python
if not defined PYTHON_EXE (
  echo No existing Python runtime was found. Preparing a project-local runtime...
  call "%APP_DIR%setup_env.bat"
  call :choose_python
)
if not defined PYTHON_EXE (
  call :write_failure "No supported Python 3.10+ runtime was found after automatic setup."
  echo Python runtime setup failed. Review the error above and the latest logs\web_gui_error_*.log file.
  exit /b 1
)

echo Using Python: %PYTHON_EXE% %PYTHON_ARGS%
if /I "%~1"=="--check" (
  call "%PYTHON_EXE%" %PYTHON_ARGS% -X utf8 -c "import encodings; import shopee_listing_app; print('encodings OK'); print('shopee_listing_app OK')"
  if errorlevel 1 (
    call :write_failure "Launcher import check failed with Python: %PYTHON_EXE% %PYTHON_ARGS%"
    exit /b 1
  )
  call "%PYTHON_EXE%" %PYTHON_ARGS% -X utf8 -m shopee_listing_app.web_gui --check
  exit /b %ERRORLEVEL%
)

call "%PYTHON_EXE%" %PYTHON_ARGS% -X utf8 -m shopee_listing_app.web_gui
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
  call :write_failure "Web GUI exited with code %APP_EXIT% using Python: %PYTHON_EXE% %PYTHON_ARGS%"
  echo The GUI failed to start. Share the latest logs\web_gui_error_*.log file when requesting support.
  pause
)
exit /b %APP_EXIT%

:choose_python
if exist "%APP_DIR%.venv\Scripts\python.exe" call :try_path "%APP_DIR%.venv\Scripts\python.exe"
if defined PYTHON_EXE exit /b 0
if exist "%APP_DIR%.runtime\python.exe" call :try_path "%APP_DIR%.runtime\python.exe"
if defined PYTHON_EXE exit /b 0
if defined SHOPEE_LISTING_PYTHON call :try_path "%SHOPEE_LISTING_PYTHON%"
if defined PYTHON_EXE exit /b 0
call :try_py
if defined PYTHON_EXE exit /b 0
call :try_system_python
exit /b 0

:try_path
set "CANDIDATE=%~1"
set "ACTUAL_PATH="
if not exist "%CANDIDATE%" exit /b 0
for /f "usebackq delims=" %%P in (`"%CANDIDATE%" -c "import sys; print(sys.executable)" 2^>nul`) do set "ACTUAL_PATH=%%P"
echo %ACTUAL_PATH% | findstr /I /C:"WXWork" /C:"WeComAgent" /C:"企业微信" >nul && exit /b 0
"%CANDIDATE%" -c "import encodings" >nul 2>&1 || exit /b 0
set "PYTHON_EXE=%CANDIDATE%"
set "PYTHON_ARGS="
exit /b 0

:try_py
py -3 -c "import encodings" >nul 2>&1 || exit /b 0
set "ACTUAL_PATH="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do set "ACTUAL_PATH=%%P"
echo %ACTUAL_PATH% | findstr /I /C:"WXWork" /C:"WeComAgent" /C:"企业微信" >nul && exit /b 0
set "PYTHON_EXE=py"
set "PYTHON_ARGS=-3"
exit /b 0

:try_system_python
python -c "import encodings" >nul 2>&1 || exit /b 0
set "ACTUAL_PATH="
for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "ACTUAL_PATH=%%P"
echo %ACTUAL_PATH% | findstr /I /C:"WXWork" /C:"WeComAgent" /C:"企业微信" >nul && exit /b 0
set "PYTHON_EXE=python"
set "PYTHON_ARGS="
exit /b 0

:write_failure
if not exist "%APP_DIR%logs" mkdir "%APP_DIR%logs"
set "LOG_FILE=%APP_DIR%logs\web_gui_error_%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log"
set "LOG_FILE=%LOG_FILE: =0%"
(
  echo %~1
  echo Python executable: %PYTHON_EXE% %PYTHON_ARGS%
  echo PYTHONHOME cleared before launch.
) > "%LOG_FILE%"
exit /b 0
