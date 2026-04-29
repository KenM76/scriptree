@echo off
:: ScripTree launcher
:: Usage:
::   run_scriptree.bat
::   run_scriptree.bat path\to\tool.scriptree
::   run_scriptree.bat path\to\tree.scriptreetree -configuration standalone
::
:: Search order for Python:
::   1. <ScripTree>\lib\python\pythonw.exe / python.exe       (portable)
::   2. <ScripTree>\lib\python\python-*-embed-*\python.exe    (extracted
::      embeddable zip dropped one folder deep — common mistake; we
::      pick it up automatically)
::   3. <ScripTree>\lib\python-*-embed-*\python.exe           (extracted
::      embeddable zip dropped next to lib\ instead of inside lib\python\)
::   4. pythonw.exe / python.exe on PATH
::
:: If none of those exist, prints clear manual-install instructions and
:: pauses so the user can read them before the window closes.

setlocal EnableDelayedExpansion

:: ── 1. Portable Python under lib\python\ ─────────────────────────────
if exist "%~dp0lib\python\pythonw.exe" (
    set "PY=%~dp0lib\python\pythonw.exe"
    goto :launch
)
if exist "%~dp0lib\python\python.exe" (
    set "PY=%~dp0lib\python\python.exe"
    goto :launch
)

:: ── 2. Embeddable zip extracted into lib\python\python-*-embed-*\ ───
::    e.g. user did "Extract All..." into lib\python\ and got
::         lib\python\python-3.13.0-embed-amd64\python.exe
for /d %%D in ("%~dp0lib\python\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: ── 3. Embeddable zip extracted next to lib\ (lib\python-*-embed-*\) ─
for /d %%D in ("%~dp0lib\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: ── 4. pythonw.exe / python.exe on PATH ─────────────────────────────
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW (
    set "PY=%PYW%"
    goto :launch
)
for %%P in (python.exe) do set "PYC=%%~$PATH:P"
if defined PYC (
    set "PY=%PYC%"
    goto :launch
)

:: ── 5. No Python found — print clear manual instructions and pause ──
echo.
echo ======================================================================
echo   ScripTree needs Python 3 to run, and none was found on this PC.
echo ======================================================================
echo.
echo To fix this:
echo.
echo   1. In your web browser, open:
echo          https://www.python.org/downloads/windows/
echo.
echo   2. Scroll to the latest stable Python 3 (3.11 or newer).
echo.
echo   3. Under that version, download the file labeled:
echo          "Windows embeddable package (64-bit)"
echo      (it's a small ZIP, about 10 MB).
echo.
echo   4. Right-click the downloaded ZIP and choose "Extract All...".
echo.
echo   5. Move the extracted files INTO this folder:
echo          %~dp0lib\python\
echo.
echo      so that this file ends up at:
echo          %~dp0lib\python\python.exe
echo.
echo   6. Double-click run_scriptree.bat again.
echo.
echo ----------------------------------------------------------------------
echo  Common mistake — nested extra folder
echo ----------------------------------------------------------------------
echo  If after extracting you see an extra folder layer like:
echo          lib\python\python-3.13.0-embed-amd64\python.exe
echo  or:
echo          lib\python-3.13.0-embed-amd64\python.exe
echo  ScripTree v0.1.15+ will FIND those automatically — just try
echo  running this .bat again. Otherwise, move the contents of the inner
echo  folder up one level so python.exe sits directly at:
echo          lib\python\python.exe
echo ----------------------------------------------------------------------
echo.
pause
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
