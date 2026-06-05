@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem Keep this file ASCII-only.
set "ROOT=%~dp0"
set "PYEXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
set "PYTHONIOENCODING=utf-8"

if not exist "%PYEXE%" set "PYEXE=py"

pushd "%ROOT%"
if errorlevel 1 (
  echo [ERROR] Cannot enter workspace: %ROOT%
  pause
  exit /b 1
)

echo.
echo === Consistency Scan ===
echo Workspace: %CD%
echo.

rem If called with arguments (y / clean / --map etc.), pass them straight through.
rem If no arguments, Python will show its own interactive menu and handle input.
if "%~1"=="" (
  "%PYEXE%" scripts\consistency\scan.py
) else (
  "%PYEXE%" scripts\consistency\scan.py %*
)

echo.
popd
pause
