@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem Keep this file ASCII-only. On a Chinese-locale Windows, cmd reads the .bat
rem bytes in the OEM codepage and chops UTF-8 Chinese into fragments that get
rem executed as bogus commands. The console (python output) is still UTF-8.
rem
rem One-click FULL ANALYST run (--analyst): one-time full-text scan of the
rem source novel. Burns a lot of tokens. Resumable: kill / shutdown any time,
rem re-run and it continues from the last landed batch (atomic write + fingerprint).

set "ROOT=%~dp0"
set "RUNTIME=%ROOT%runtime"
set "PYEXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"
set "PYTHONIOENCODING=utf-8"

if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo ============================================================
echo   FULL ANALYST RUN  (--analyst)
echo   One-time full-text scan: prose chunks + structure report.
echo ------------------------------------------------------------
echo   * Token-heavy: MAP input ~2.48M tok, 41 batches.
echo   * Resumable: close window / shutdown any time, re-run to continue.
echo   * Graceful stop: double-click the stop bat in this folder.
echo ============================================================
echo.

choice /c YN /n /m "Start the full analyst run? (Y/N) "
if errorlevel 2 (
  echo Cancelled.
  pause
  exit /b 0
)

rem Clear any leftover stop/pause markers so a fresh run is not blocked.
del "%RUNTIME%\stop.request" >nul 2>nul
del "%RUNTIME%\pause.request" >nul 2>nul

rem Auto-open the read-only monitor in a new window (it never touches the run).
start "Analyst Monitor" cmd /k ""%PYEXE%" "%ROOT%scripts\analyst_monitor.py""

pushd "%ROOT%"
echo.
echo === Analyst started ===  %DATE% %TIME%
echo (Progress is in the new "Analyst Monitor" window; this is the raw log.)
echo.

"%PYEXE%" "scripts\run_pipeline.py" --config "config\run.json" --analyst
set "CODE=%ERRORLEVEL%"

popd
echo.
if "%CODE%"=="0" (
  echo === Analyst finished ===
  echo Prose chunks written to chunks\
  echo Structure report: runtime\analyst\_structure_calibration.md
  echo   ^<- read it manually, then hand-calibrate the planner prompts.
) else (
  echo === Interrupted / failed, exit code %CODE% ===
  echo Re-run this bat to continue from the last landed batch.
)
echo.
pause
exit /b %CODE%
