@echo off
:: ScripTreeRing launcher (cell + ring shell)
:: Usage:
::   run_scriptreering.bat
::   run_scriptreering.bat path\to\layout.scriptreering
::   run_scriptreering.bat --register-autostart-user path\to\layout.scriptreering
::
:: Mirrors run_scriptree.bat's Python search logic so a portable
:: install works the same way for both the editor and the cell shell.
:: When Python is missing the user gets the same friendly install
:: instructions; the only difference is the .py target at the end.

setlocal EnableDelayedExpansion

:: -- 1. Portable Python under lib\python\ ----------------------------
if exist "%~dp0lib\python\pythonw.exe" (
    set "PY=%~dp0lib\python\pythonw.exe"
    goto :launch
)
if exist "%~dp0lib\python\python.exe" (
    set "PY=%~dp0lib\python\python.exe"
    goto :launch
)

:: -- 2. Embeddable zip dropped one folder deep -----------------------
for /d %%D in ("%~dp0lib\python\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: -- 3. Embeddable zip dropped next to lib\ --------------------------
for /d %%D in ("%~dp0lib\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: -- 4. pythonw.exe / python.exe on PATH -----------------------------
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

:: -- 5. No Python found ----------------------------------------------
echo.
echo ======================================================================
echo   ScripTreeRing needs Python 3 to run, and none was found on this PC.
echo ======================================================================
echo.
echo To fix this:
echo   1. In your web browser, open:
echo          https://www.python.org/downloads/windows/
echo   2. Download "Windows embeddable package (64-bit)" (a small ZIP).
echo   3. Right-click the ZIP and choose "Extract All...".
echo   4. Move the extracted contents INTO this folder:
echo          %~dp0lib\python\
echo      so that this file ends up at:
echo          %~dp0lib\python\python.exe
echo   5. Double-click run_scriptreering.bat again.
echo.
pause
goto :end

:launch
echo %PY% | findstr /i "pythonw.exe" >nul
if not errorlevel 1 (
    start "" "%PY%" "%~dp0run_scriptreering.py" %*
) else (
    "%PY%" "%~dp0run_scriptreering.py" %*
)
goto :end

:end
endlocal
