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
::   4. pythonw.exe / python.exe on PATH (Microsoft Store stubs in
::      %LocalAppData%\Microsoft\WindowsApps\ are filtered OUT — they
::      are 0-byte App Execution Aliases that just open the Store and
::      would silently kill the launch with no visible error).
::
:: If none of those exist, offers to download a portable Python
:: (lib\install_python.ps1) and falls through to clear manual
:: instructions if the user declines.

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

:: -- 2. Embeddable zip extracted into lib\python\python-*-embed-*\ --
for /d %%D in ("%~dp0lib\python\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: -- 3. Embeddable zip extracted next to lib\ (lib\python-*-embed-*\) -
for /d %%D in ("%~dp0lib\python-*-embed-*") do (
    if exist "%%D\python.exe" (
        set "PY=%%D\python.exe"
        goto :launch
    )
)

:: -- 4. pythonw.exe / python.exe on PATH (filter Store stub) ---------
::    The Microsoft Store python alias at
::      %LocalAppData%\Microsoft\WindowsApps\python*.exe
::    is a 0-byte reparse point that opens the Store and exits.  If
::    we picked it up, "start" would detach immediately and the user
::    would see nothing more than a terminal flash.  Skip it.
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
::    The portable build ships lib\install_python.ps1 which downloads
::    the python.org embeddable zip + pip + vendored deps in one go.
::    Requires PowerShell 5.1+ (Windows 10+) and an internet
::    connection right now; afterwards the install is fully offline.
if exist "%~dp0lib\install_python.ps1" (
    echo.
    echo ======================================================================
    echo   ScripTree needs Python 3 to run, and none was found on this PC.
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
echo   ScripTree needs Python 3 to run, and none was found on this PC.
echo ======================================================================
echo.
echo To fix this:
echo.
echo   1. In your web browser, open:
echo          https://www.python.org/downloads/windows/
echo.
echo   2. Scroll to the latest stable Python 3 ^(3.11 or newer^).
echo.
echo   3. Under that version, download the file labeled:
echo          "Windows embeddable package ^(64-bit^)"
echo      ^(it's a small ZIP, about 10 MB^).
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
echo  Note: the Microsoft Store "python.exe" stub does NOT count — it's a
echo  0-byte alias that opens the Store and exits.  ScripTree filters
echo  it out automatically; if you want a system-wide Python, install
echo  the real interpreter from python.org rather than the Store stub.
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
