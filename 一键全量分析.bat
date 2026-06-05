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
set "ANALYST=%RUNTIME%\analyst"
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
echo   * Auto-rerun: if you edited any analyst prompt, the content hash
echo     changes and ALL stale batches are re-run automatically.
echo   * Graceful stop: double-click the stop bat in this folder.
echo ============================================================
echo.

choice /c YN /n /m "Start the full analyst run? (Y/N) "
if errorlevel 2 (
  echo Cancelled.
  pause
  exit /b 0
)

:MENU
echo.
echo Run mode:
echo   [R] Resume        - keep valid artifacts, re-run only changed/missing
echo                       (normal; respects prompt-hash auto-rerun)
echo   [C] Clean ALL     - delete the whole analyst folder, re-run everything
echo   --- debug: delete one stage and force it to recompute ---
echo   [M] redo MAP      - delete map batches + ALL downstream (merge/reduce/
echo                       structure); full rebuild, full token cost
echo   [P] redo PROSE    - delete merge cache + reduce output, keep MAP;
echo                       re-run the prose REDUCE (the 8 technique cards)
echo   [S] redo STRUCT   - delete the structure report, keep MAP;
echo                       re-run only the structure REDUCE (calibration)
echo.
choice /c RCMPS /n /m "Choose ([R]esume/[C]lean/[M]ap/[P]rose/[S]truct): "
set "SEL=%ERRORLEVEL%"
if "%SEL%"=="5" goto DEL_STRUCT
if "%SEL%"=="4" goto DEL_PROSE
if "%SEL%"=="3" goto DEL_MAP
if "%SEL%"=="2" goto CLEAN_ALL
goto AFTER_MODE

:CLEAN_ALL
echo.
echo You chose CLEAN ALL. This deletes runtime\analyst\ entirely.
choice /c YN /n /m "Are you sure? This cannot be undone. (Y/N) "
if errorlevel 2 goto MENU
echo Deleting runtime\analyst\ ...
rmdir /s /q "%ANALYST%" >nul 2>nul
echo Done. Starting a full clean re-run.
goto AFTER_MODE

:DEL_MAP
echo.
echo You chose redo MAP. This deletes map batches AND all downstream
echo products (merge cache, reduce output, structure report), because
echo everything is derived from MAP. Full rebuild, full token cost.
choice /c YN /n /m "Are you sure? (Y/N) "
if errorlevel 2 goto MENU
echo Deleting MAP batches and downstream products ...
del "%ANALYST%\map_*.md" >nul 2>nul
del "%ANALYST%\merge_L*.md" >nul 2>nul
del "%ANALYST%\_reduce_output.md" >nul 2>nul
del "%ANALYST%\_structure_calibration.md" >nul 2>nul
echo Done. Starting a full rebuild.
goto AFTER_MODE

:DEL_PROSE
echo.
echo You chose redo PROSE. This deletes the merge cache and reduce
echo output but KEEPS the MAP batches, so only the prose REDUCE
echo (the 8 technique cards) is recomputed. Cheap; good for tuning
echo analyst_reduce.md / analyst_merge.md. The 8 chunk files are
echo overwritten on re-run.
choice /c YN /n /m "Are you sure? (Y/N) "
if errorlevel 2 goto MENU
echo Deleting merge cache + reduce output ...
del "%ANALYST%\merge_L*.md" >nul 2>nul
del "%ANALYST%\_reduce_output.md" >nul 2>nul
echo Done. MAP kept; prose REDUCE will recompute.
goto AFTER_MODE

:DEL_STRUCT
echo.
echo You chose redo STRUCT. This deletes the structure calibration
echo report but KEEPS the MAP batches, so only the structure REDUCE
echo is recomputed. Cheap; good for tuning analyst_structure_reduce.md.
choice /c YN /n /m "Are you sure? (Y/N) "
if errorlevel 2 goto MENU
echo Deleting structure report ...
del "%ANALYST%\_structure_calibration.md" >nul 2>nul
echo Done. MAP kept; structure REDUCE will recompute.
goto AFTER_MODE

:AFTER_MODE
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
