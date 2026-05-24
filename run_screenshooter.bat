@echo off
REM ScripTree headless screenshooter launcher.
REM
REM With no arguments: opens the screenshooter's GUI form via the
REM V1 editor, so a double-click gets you a labeled form with
REM dropdowns and file pickers for every option. Friendly entry point.
REM
REM With arguments: passes them straight through to screenshooter.py
REM for headless / batch use. Examples:
REM
REM   run_screenshooter.bat cell my-tool.scriptree --out cell.png
REM   run_screenshooter.bat editor my-tree.scriptreetree --out e.png --width 1200 --height 780
REM   run_screenshooter.bat --batch ScripTreeApps/MyApp --out screenshots/
REM
REM Mirrors the same Python search logic as run_scriptree.bat /
REM run_scriptreering.bat / run_scriptreeforest.bat so a portable
REM install (with lib\python\ vendored) works without a system
REM Python install.

setlocal EnableDelayedExpansion

REM -- GUI-form mode (no args) -- delegate to the V1 editor on the
REM bundled screenshooter.scriptree front-end so a double-click
REM produces a labeled form instead of a CLI help dump.
if "%~1"=="" (
    if exist "%~dp0run_scriptree.bat" (
        if exist "%~dp0ScripTreeApps\ScripTreeManagement\screenshooter.scriptree" (
            call "%~dp0run_scriptree.bat" "%~dp0ScripTreeApps\ScripTreeManagement\screenshooter.scriptree"
            goto :end
        )
    )
)

REM -- 1. Portable Python under lib\python\ ----------------------------
if exist "%~dp0lib\python\pythonw.exe" (
    set "PY=%~dp0lib\python\pythonw.exe"
    goto :launch
)
if exist "%~dp0lib\python\python.exe" (
    set "PY=%~dp0lib\python\python.exe"
    goto :launch
)

REM -- 2. Embeddable zip dropped one folder deep -----------------------
for /d %%D in ("%~dp0lib\python\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

REM -- 3. Embeddable zip dropped next to lib\ --------------------------
for /d %%D in ("%~dp0lib\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

REM -- 4. python.exe on PATH (filter Microsoft Store stub) -------------
for %%P in (python.exe) do set "PYC=%%~$PATH:P"
if defined PYC (
    echo !PYC! | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PY=!PYC!"
        goto :launch
    )
    set "PYC="
)

REM -- 5. No Python found ----------------------------------------------
echo.
echo ======================================================================
echo   screenshooter needs Python 3 to run, and none was found on this PC.
echo ======================================================================
echo.
echo Install Python from https://www.python.org/downloads/windows/
echo (the real interpreter, not the Microsoft Store stub) and re-run
echo this script. Or double-click run_scriptreeforest.bat once first
echo and let it download a portable Python into lib\python\ -- the
echo shells and the screenshooter share the same vendored interpreter.
echo.
pause
goto :end

:launch
"%PY%" "%~dp0screenshooter.py" %*
goto :end

:end
endlocal
