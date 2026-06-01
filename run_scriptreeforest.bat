@echo off
:: ScripTreeForest launcher (cell + ring shell)
:: Usage:
::   run_scriptreeforest.bat
::   run_scriptreeforest.bat path\to\layout.scriptreering
::   run_scriptreeforest.bat --register-autostart-user path\to\layout.scriptreering
::
:: Mirrors run_scriptree.bat's Python search logic so a portable
:: install works the same way for both the editor and the cell shell.
:: Microsoft Store python stubs are filtered out automatically (they
:: are 0-byte App Execution Aliases that open the Store and exit —
:: picking one would silently kill the launch with no visible error).

setlocal EnableDelayedExpansion

:: Bytecode-write guard -- see docs\LLM\no_bytecode_policy.md.
:: Prevents Python from writing ``__pycache__\*.pyc`` files.  Mandatory
:: when ScripTree lives in a Dropbox / OneDrive / Google Drive folder
:: (uncached .pyc writes trigger sync storms).  The launcher .py files
:: also set ``sys.dont_write_bytecode = True`` as belt-and-suspenders.
set PYTHONDONTWRITEBYTECODE=1

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

:: -- 4. pythonw.exe / python.exe on PATH (filter Store stub) ---------
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW (
    echo !PYW! | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PY=!PYW!"
        goto :launch
    )
    set "PYW="
)
for %%P in (python.exe) do set "PYC=%%~$PATH:P"
if defined PYC (
    echo !PYC! | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PY=!PYC!"
        goto :launch
    )
    set "PYC="
)

:: -- 5. No real Python found — offer to auto-install one ------------
if exist "%~dp0lib\install_python.ps1" (
    echo.
    echo ======================================================================
    echo   ScripTreeForest needs Python 3 to run, and none was found on this PC.
    echo ======================================================================
    echo.
    echo I can download a portable Python ^(about 25 MB^) into:
    echo     %~dp0lib\python\
    echo so this folder becomes fully self-contained — no system
    echo install needed.  Requires internet access right now;
    echo afterwards everything works offline.
    echo.
    set /p ANSWER="Download portable Python now? [Y/n] "
    if /i "!ANSWER!"=="" set "ANSWER=Y"
    if /i "!ANSWER!"=="Y" (
        echo.
        echo Running lib\install_python.ps1 ...
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lib\install_python.ps1" -ScripTreeHome "%~dp0."
        if exist "%~dp0lib\python\pythonw.exe" (
            set "PY=%~dp0lib\python\pythonw.exe"
            goto :launch
        )
        if exist "%~dp0lib\python\python.exe" (
            set "PY=%~dp0lib\python\python.exe"
            goto :launch
        )
        echo.
        echo install_python.ps1 finished but no python.exe ended up at:
        echo     %~dp0lib\python\
        echo Falling through to manual instructions below.
        echo.
    )
)

:: -- 5b. Manual fallback instructions --------------------------------
echo.
echo ======================================================================
echo   ScripTreeForest needs Python 3 to run, and none was found on this PC.
echo ======================================================================
echo.
echo To fix this:
echo   1. In your web browser, open:
echo          https://www.python.org/downloads/windows/
echo   2. Download "Windows embeddable package ^(64-bit^)" ^(a small ZIP^).
echo   3. Right-click the ZIP and choose "Extract All...".
echo   4. Move the extracted contents INTO this folder:
echo          %~dp0lib\python\
echo      so that this file ends up at:
echo          %~dp0lib\python\python.exe
echo   5. Double-click run_scriptreeforest.bat again.
echo.
echo Note: the Microsoft Store "python.exe" stub does NOT count — it's a
echo 0-byte alias that opens the Store and exits.  Install the real
echo interpreter from python.org rather than the Store stub.
echo.
pause
goto :end

:launch
echo %PY% | findstr /i "pythonw.exe" >nul
if not errorlevel 1 (
    start "" "%PY%" "%~dp0run_scriptreeforest.py" %*
) else (
    "%PY%" "%~dp0run_scriptreeforest.py" %*
)
goto :end

:end
endlocal
