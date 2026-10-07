#!/usr/bin/env bash
# PaperPull - one-shot setup (macOS / Linux)
#
# Builds one Python environment, gui/.venv, that the control panel and every
# app share, with every app's requirements and the shared core installed in
# it. Every app asks for the same few packages, so one environment holds them
# all, where a venv in each app folder took about 400 MB apiece. An app that
# already has a .venv of its own keeps running on it, and this leaves it
# alone. This takes a few minutes the first time. No browser is downloaded
# here. Any Chromium-based browser already installed can be used, and if none
# is found, login offers the download then.
set -uo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo " PaperPull - one-shot setup"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    echo "Install it from https://www.python.org/downloads/ or with Homebrew:"
    echo "    brew install python"
    exit 1
fi
echo "Using Python: $(python3 --version) at $(command -v python3)"
echo

# Every requirements file goes to one pip call, gathered as the positional
# parameters rather than an array, since macOS still ships bash 3.2, where
# an EMPTY array trips "unbound variable" under set -u. The panel's own file
# comes first, so the list is never empty. The names of the apps that keep
# a .venv of their own are a plain string for the same reason.
set -- -r gui/requirements.txt
count=0
own=""
for app in apps/*/; do
    [ -f "${app}requirements.txt" ] || continue
    set -- "$@" -r "${app}requirements.txt"
    count=$((count + 1))
    if [ -x "${app}.venv/bin/python" ]; then
        own="$own $(basename "$app")"
    fi
done

failed=""
PY=gui/.venv/bin/python
if [ -x "$PY" ]; then
    echo "Reusing gui/.venv"
else
    echo "Creating gui/.venv"
    python3 -m venv gui/.venv || failed=1
fi
if [ -n "$failed" ] || [ ! -x "$PY" ]; then
    echo "** Creating gui/.venv failed, see the message above."
    failed=1
else
    "$PY" -m pip install -q --upgrade pip
    echo "Installing what the panel and $count apps need"
    if ! "$PY" -m pip install -q "$@"; then
        echo "** Installing the requirements failed, see pip's message above."
        failed=1
    fi

    # The shared core. A checkout installs it from source, a copy shipped
    # without the source carries a wheel.
    wheel=""
    for found in core/paperpull_core-*.whl; do
        if [ -f "$found" ]; then wheel="$found"; fi
    done
    if [ -f core/pyproject.toml ]; then
        set -- -e ./core
    elif [ -n "$wheel" ]; then
        set -- "$wheel"
    else
        set --
    fi
    if [ $# -eq 0 ]; then
        echo "** Neither core/pyproject.toml nor a core wheel is here, so the core cannot be installed."
        failed=1
    elif ! "$PY" -m pip install -q "$@"; then
        echo "** Installing the shared core failed, see pip's message above."
        failed=1
    fi
fi

chmod +x apps/*/*.command gui/*.command 2>/dev/null || true

echo
if [ -z "$failed" ]; then
    echo "All set. The control panel and $count apps share one environment, gui/.venv."
    echo "Next: open an app folder and run ./login.command,"
    echo "or start the control panel with gui/run_gui.command"
else
    echo "** Setup did not finish. Fix what is said above, then run this again."
fi
if [ -n "$own" ]; then
    echo
    echo "These apps keep the .venv of their own that they already have, and run"
    echo "on it. Delete one to have that app use gui/.venv and free its space."
    echo " $own"
fi
if [ -n "$failed" ]; then
    exit 1
fi
