#!/bin/bash
# Launcher for panel services (no virtualenv). Ensures deps before start.

set -eu

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

log_file="${script_dir}/panel.log"
python_bin="$(command -v python3)"

ensure_deps() {
    if ! "$python_bin" - <<'PY' >/dev/null 2>&1; then
try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    raise SystemExit(1)
PY
    then
        echo "$(date -Iseconds) installing Python dependencies" >>"$log_file"
        "$python_bin" -m pip install --upgrade --quiet pip setuptools wheel >>"$log_file" 2>&1 || true
        if [ -f "requirements.txt" ]; then
            "$python_bin" -m pip install --quiet -r requirements.txt >>"$log_file" 2>&1
        fi
    fi
}

start_app() {
    local script="$1"
    shift
    local label="$script"
    local -a env_vars=("$@")

    while true; do
        echo "$(date -Iseconds) ${label} launch initiated." >>"$log_file"
        if [ "${#env_vars[@]}" -gt 0 ]; then
            env "${env_vars[@]}" "$python_bin" "$script" >>"$log_file" 2>&1
        else
            "$python_bin" "$script" >>"$log_file" 2>&1
        fi
        echo "$(date -Iseconds) ${label} crashed, relaunching in 3s." >>"$log_file"
        sleep 3
    done
}

ensure_deps

start_app "app.py" HOST=0.0.0.0 PORT=8080 &
start_app "app_q.py" HOST=0.0.0.0 PORT=5000 &

wait
