#!/bin/bash
# Launcher for panel services. Works with cron @reboot entry.

set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

log_file="${script_dir}/panel.log"

start_app() {
    local script="$1"
    shift
    local label="$script"
    local -a env_vars=("$@")

    while true; do
        echo "$(date -Iseconds) ${label} launch initiated." >>"$log_file"
        if [ "${#env_vars[@]}" -gt 0 ]; then
            env "${env_vars[@]}" /usr/bin/python3 "$script" >>"$log_file" 2>&1
        else
            /usr/bin/python3 "$script" >>"$log_file" 2>&1
        fi
        echo "$(date -Iseconds) ${label} crashed, relaunching in 3s." >>"$log_file"
        sleep 3
    done
}

start_app "app.py" HOST=0.0.0.0 PORT=8080 &
start_app "app_q.py" HOST=0.0.0.0 PORT=5000 &

wait
