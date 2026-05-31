@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

rem Keep this file ASCII-only. Some Windows cmd setups misread UTF-8
rem batch files with Chinese text and then execute broken fragments.
set "ROOT=%~dp0"
set "RUNTIME=%ROOT%runtime"
set "LOCK=%RUNTIME%\novel_pipeline.bat.lock"
set "PYLOCK=%RUNTIME%\novel_pipeline.lock"
set "PYEXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe"

if not exist "%RUNTIME%" mkdir "%RUNTIME%"

if not exist "%PYEXE%" (
  set "PYEXE=python"
)

if /I "%~1"=="--check" (
  echo BAT_OK
  echo ROOT=%ROOT%
  echo PYEXE=%PYEXE%
  exit /b 0
)

if exist "%LOCK%" (
  del "%LOCK%" >nul 2>nul
  echo [INFO] Cleared stale batch lock from previous run.
)

echo started %DATE% %TIME% > "%LOCK%"

pushd "%ROOT%"
if errorlevel 1 (
  echo [ERROR] Cannot enter workspace:
  echo %ROOT%
  del "%LOCK%" >nul 2>nul
  pause
  exit /b 1
)

echo.
echo === Novel pipeline starting ===
echo Workspace: %CD%
echo Config: config\models.json
echo Run config: config\run.json
echo Output: article folder under workspace
echo.
set "COUNT=50"
set /p COUNT=How many chapters this run? default 50 (press Enter for overnight):
if "%COUNT%"=="" set "COUNT=50"
for /f "delims=0123456789" %%A in ("%COUNT%") do set "COUNT=50"
if %COUNT% LSS 1 set "COUNT=1"

echo This run will write %COUNT% chapter(s).
echo Press p to request pause/resume, q to request stop.
echo.

if exist "%PYEXE%" (
  call "%PYEXE%" "scripts\run_pipeline.py" --config "config\run.json" --count %COUNT%
  set "CODE=%ERRORLEVEL%"
) else (
  py -3 "scripts\run_pipeline.py" --config "config\run.json" --count %COUNT%
  set "CODE=%ERRORLEVEL%"
)

popd
del "%LOCK%" >nul 2>nul

echo.
if "%CODE%"=="0" (
  echo === Done ===
  echo Read chapters in the article output folder under the workspace.
) else (
  echo === Failed, exit code %CODE% ===
  echo Check config\models.json provider/model/base_url/api_key.
)
echo.
pause
exit /b %CODE%
