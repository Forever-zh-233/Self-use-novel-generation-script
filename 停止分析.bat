@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem ASCII-only (see note in the full-analyst bat). Request a graceful stop of
rem the running analyst/chapter pipeline. It stops at the next batch boundary;
rem everything already landed is kept, re-running continues. This only drops a
rem marker file; it does not kill any process.

set "ROOT=%~dp0"
set "RUNTIME=%ROOT%runtime"
if not exist "%RUNTIME%" mkdir "%RUNTIME%"

echo stop requested %DATE% %TIME% > "%RUNTIME%\stop.request"
echo.
echo Stop requested -^> runtime\stop.request
echo The run stops after the current batch; landed batches are all kept.
echo Re-run the full-analyst bat to continue from there.
echo.
echo (To cancel the stop: delete runtime\stop.request manually.)
echo.
pause
exit /b 0
