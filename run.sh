#!/bin/bash
# /opt/panel2/run.sh

cd /opt/panel
log_file="panel.log"

while true; do
    /usr/bin/python3 app.py >>panel.log 2>&1
    /usr/bin/python3 app_q.py >>panel.log 2>&1
    echo "$(date) app.py crashed, restarting..." >>panel.log
    sleep 30
done

start_app "app.py" PORT=8080
start_app "app_q.py" PORT=5000
