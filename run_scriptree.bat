@echo off
:: ScripTree launcher
:: Usage:
::   run_scriptree.bat
::   run_scriptree.bat path\to\tool.scriptree
::   run_scriptree.bat path\to\tree.scriptreetree -configuration standalone
::
:: Uses pythonw.exe when available (no console window, looks like a
:: proper GUI app). Falls back to python.exe if pythonw is missing —
:: e.g. on an embedded Python that ships only python.exe. If you need
:: to see stdout/stderr (debugging, prompts), call run_scriptree.py
:: directly with `python run_scriptree.py`.

setlocal

:: Prefer pythonw.exe (windowed). It's a sibling of python.exe on
:: standard Windows installs, including the launcher's chosen python.
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW (
    start "" "%PYW%" "%~dp0run_scriptree.py" %*
) else (
    python "%~dp0run_scriptree.py" %*
)
