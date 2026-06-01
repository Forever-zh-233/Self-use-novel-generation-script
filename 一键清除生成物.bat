@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem One-click cleanup: delete all chapter-level generated content.
rem Does NOT touch: config, prompts, source text, outlines, scripts, settings.

set "ROOT=%~dp0"
set "PYEXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"

if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo ============================================
echo   WARNING: This will delete ALL chapter
echo   generated content (articles, scores,
echo   beats, ledger snapshots, runtime state).
echo.
echo   Config, prompts, outlines, source text,
echo   and scripts will NOT be touched.
echo ============================================
echo.

set /p CONFIRM=Type YES to confirm cleanup:
if /I not "%CONFIRM%"=="YES" (
  echo Cancelled.
  pause
  exit /b 0
)

echo.
echo Running cleanup...
"%PYEXE%" "%ROOT%scripts\clean_chapter_artifacts.py"
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
  echo === Cleanup complete ===
) else (
  echo === Cleanup failed, exit code %CODE% ===
)
pause
exit /b %CODE%
