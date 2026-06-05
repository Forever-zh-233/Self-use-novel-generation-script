@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem Open the read-only analyst monitor on an already-running analysis.
rem Pure filesystem reader: it never touches the analyst process.

set "ROOT=%~dp0"
set "PYEXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
set "PYTHONIOENCODING=utf-8"
if not exist "%PYEXE%" set "PYEXE=python"

"%PYEXE%" "%ROOT%scripts\analyst_monitor.py"
pause
exit /b 0
