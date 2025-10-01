#!/bin/bash
# /opt/panel/run.sh

cd /opt/panel
log_file="panel.log"

start_app() {
    local script="$1"
    shift
    local label="$script"
    while true; do
        echo "$(date) ${label} launch initiated." >>"$log_file"
        if [ "$#" -gt 0 ]; then
            env "$@" /usr/bin/python3 "$script" >>"$log_file" 2>&1
        else
            /usr/bin/python3 "$script" >>"$log_file" 2>&1
        fi
        relaunch_time=$(date -d '+3 seconds' '+%Y-%m-%d %H:%M:%S')
        echo "$(date) ${label} crashed, relaunch scheduled at ${relaunch_time}." >>"$log_file"
        sleep 3
    done
}

start_app "app.py" PORT=8080 &
start_app "app_q.py" APP_Q_PORT=5000 &

wait
