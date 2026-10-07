@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo  PaperPull - one-shot setup
echo  Builds one Python environment, gui\.venv, that the control
echo  panel and every app share, with the shared core in it.
echo  This can take a few minutes the first time.
echo ============================================================
echo.

rem --- locate Python 3 ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
  echo Python 3 was not found. Install it from https://www.python.org/downloads/
  echo Be sure to check "Add Python to PATH" during install.
  pause & exit /b 1
)

rem --- what every app needs, for one pip call ---
rem Every app asks for the same few packages, so one environment holds them
rem all, where a venv in each app folder took about 400 MB apiece. An app
rem that already has a .venv of its own keeps running on it, and this leaves
rem it alone.
set "REQS=-r gui\requirements.txt"
set "OWN="
set /a COUNT=0
for /d %%A in (apps\*) do (
  if exist "%%A\requirements.txt" (
    set "REQS=!REQS! -r %%A\requirements.txt"
    set /a COUNT+=1
    if exist "%%A\.venv\Scripts\python.exe" set "OWN=!OWN! %%~nxA"
  )
)

rem --- the one environment, the panel's own ---
set "FAILED="
set "PY=gui\.venv\Scripts\python.exe"
if exist "%PY%" (
  echo Reusing gui\.venv
) else (
  echo Creating gui\.venv
  %PYEXE% -m venv gui\.venv || set "FAILED=1"
)
if not exist "%PY%" set "FAILED=1"
if defined FAILED (
  echo ** Creating gui\.venv failed, see the message above.
  goto done
)
"%PY%" -m pip install -q --upgrade pip
echo Installing what the panel and !COUNT! apps need
"%PY%" -m pip install -q !REQS! || (
  echo ** Installing the requirements failed, see pip's message above.
  set "FAILED=1"
)

rem  The shared core. Every app imports paperpull_core, so without this
rem  step each one dies at startup with ModuleNotFoundError. A repo
rem  checkout installs it from source, a copy shipped without the source
rem  carries a wheel.
set "CORE="
if exist "core\pyproject.toml" (
  set "CORE=-e .\core"
) else (
  for %%W in ("core\paperpull_core-*.whl") do set "CORE=%%W"
)
if not defined CORE (
  echo ** Neither core\pyproject.toml nor a core wheel is here, so the core cannot be installed.
  set "FAILED=1"
  goto done
)
"%PY%" -m pip install -q !CORE! || (
  echo ** Installing the shared core failed, see pip's message above.
  set "FAILED=1"
)

:done
echo.
if defined FAILED (
  echo ** Setup did not finish. Fix what is said above, then run this again.
) else (
  echo All set. The control panel and !COUNT! apps share one environment, gui\.venv.
)
if defined OWN (
  echo.
  echo These apps run on a .venv of their own, which setup-all leaves as it
  echo is. Run an app's own setup.bat to bring its .venv up to date, or delete
  echo the .venv to have that app use gui\.venv and free its space.
  echo  !OWN!
)
echo.
echo Next:
echo   * Launch the control panel:  gui\run_gui.bat
echo   * Or one app directly:       apps\amex\login.bat  (sign in)  ^&  paperpull amex pilot
echo.
echo   Each app needs its own config.json first - copy config.example.json
echo   next to it and edit the paths. UKG also needs your employer's
echo   base_url set in that file.
echo.
pause
