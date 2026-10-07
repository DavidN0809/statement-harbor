@echo off
cd /d "%~dp0"
rem  login.bat          -> your account (config.json, port 9239)
rem  login.bat spouse   -> config.spouse.json (own folders, profile, port)
if "%~1"=="" (set "CFG=") else (set "CFG=--config config.%~1.json")
echo ============================================================
echo  Paylocity Pay Statements - sign in
echo ============================================================
if not "%~1"=="" echo Account: %~1
echo.
echo A normal browser window opens at access.paylocity.com. Then:
echo   1. Sign in the way your company does - a Paylocity username and password,
echo      or your company's single sign-on. Either is fine: this tool never
echo      sees your credentials and never touches the sign-in itself.
echo   2. Complete any MFA / verification prompt yourself.
echo   3. Open your Pay / Pay Statements area and confirm you can see them.
echo   4. LEAVE THAT BROWSER WINDOW OPEN - do not close it.
echo.
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
"%PY%" paylocity_docs.py --open-browser %CFG%
echo.
pause
