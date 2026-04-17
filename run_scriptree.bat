@echo off
:: ScripTree launcher
:: Usage:
::   run_scriptree.bat
::   run_scriptree.bat path\to\tool.scriptree
::   run_scriptree.bat path\to\tree.scriptreetree -configuration standalone

python "%~dp0run_scriptree.py" %*
