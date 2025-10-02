#!/bin/bash
# /opt/panel2/run.sh

cd /opt/panel || exit 1
log_file="panel.log"

run_app() {
    local script=$1
    while true; do
        /usr/bin/python3 "$script" >>"$log_file" 2>&1
        echo "$(date) $script crashed, restarting..." >>"$log_file"
        sleep 30
    done
}

run_app app.py &
run_app app_q.py &

wait -n
