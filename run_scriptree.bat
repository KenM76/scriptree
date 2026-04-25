@echo off
:: ScripTree launcher
:: Usage:
::   run_scriptree.bat
::   run_scriptree.bat path\to\tool.scriptree
::   run_scriptree.bat path\to\tree.scriptreetree -configuration standalone
::
:: Search order for Python:
::   1. <ScripTree>\lib\python\pythonw.exe   (portable install)
::   2. pythonw.exe on PATH
::   3. python.exe on PATH
:: If none of those exist, prompts the user via PowerShell to either
:: install a portable Python into lib\python\ (recommended), open the
:: python.org download page, or cancel.

setlocal

:: ── 1. Portable Python under lib\python\ ─────────────────────────────
if exist "%~dp0lib\python\pythonw.exe" (
    set "PY=%~dp0lib\python\pythonw.exe"
    goto :launch
)
if exist "%~dp0lib\python\python.exe" (
    set "PY=%~dp0lib\python\python.exe"
    goto :launch
)

:: ── 2. pythonw.exe on PATH ───────────────────────────────────────────
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW (
    set "PY=%PYW%"
    goto :launch
)

:: ── 3. python.exe on PATH ────────────────────────────────────────────
for %%P in (python.exe) do set "PYC=%%~$PATH:P"
if defined PYC (
    set "PY=%PYC%"
    goto :launch
)

:: ── 4. No Python found — prompt the user ─────────────────────────────
echo No Python interpreter found. Launching install prompt...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$choice = (New-Object -ComObject WScript.Shell).Popup('No Python 3 was found on this machine. ScripTree needs Python 3.11 or later.`n`nYes  = Install a portable Python into lib\python\ (recommended)`nNo   = Open python.org download page in your browser`nCancel = Quit', 0, 'ScripTree - Python required', 35); switch ($choice) { 6 { exit 10 } 7 { exit 20 } default { exit 30 } }"
set "RC=%errorlevel%"

if "%RC%"=="10" goto :install_portable
if "%RC%"=="20" goto :open_browser
goto :end

:install_portable
echo.
echo Installing portable Python into "%~dp0lib\python\"...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\install_python.ps1" "%~dp0"
if errorlevel 1 (
    echo.
    echo install_python.ps1 failed. Check the output above for details.
    pause
    goto :end
)
:: Re-launch ourselves now that lib\python\ is populated.
echo.
echo Portable Python installed. Re-launching ScripTree...
call "%~dp0run_scriptree.bat" %*
goto :end

:open_browser
start "" "https://www.python.org/downloads/"
goto :end

:launch
:: PYW is the windowed (no-console) Python; PY may be a console one.
:: When PY ends in pythonw.exe we use `start ""` to detach (so the
:: cmd window doesn't linger). For console python.exe we run inline.
echo %PY% | findstr /i "pythonw.exe" >nul
if not errorlevel 1 (
    start "" "%PY%" "%~dp0run_scriptree.py" %*
) else (
    "%PY%" "%~dp0run_scriptree.py" %*
)
goto :end

:end
endlocal
