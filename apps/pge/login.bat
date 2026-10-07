@echo off
setlocal
cd /d "%~dp0"

set CFG=
if not "%~1"=="" set CFG=--config config.%~1.json

rem This app's own Python when setup.bat made one. Otherwise, in a
rem checkout, the one setup-all.bat made for every app in gui\.venv, once
rem it holds what an app needs.
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto run
set "PY=..\..\gui\.venv\Scripts\python.exe"
if not exist "%PY%" goto notsetup
"%PY%" -c "import importlib.util as u, sys; sys.exit(not all(map(u.find_spec, ['paperpull_core', 'playwright', 'pypdf'])))" >nul 2>&1
if not errorlevel 1 goto run
:notsetup
if exist "..\..\setup-all.bat" (
  echo This app is not set up yet. Run setup-all.bat in the PaperPull folder first.
) else (
  echo This app is not set up yet - run setup.bat first.
)
echo.
pause
exit /b 1

:run
echo ============================================================
echo PG^&E Documents - sign in
echo ============================================================
echo A normal Chromium window will open. Then:
echo 1. Sign in to PG^&E (do all 2FA / device approval yourself)
echo 2. Go to Billing and payments (your statement history)
echo 3. LEAVE THAT BROWSER WINDOW OPEN - do not close it
echo.

"%PY%" pge_docs.py --open-browser %CFG%
pause
