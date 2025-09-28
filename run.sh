#!/bin/bash
# /opt/panel/run.sh

cd /opt/panel
log_file="panel.log"

# Reboot the machine once each midnight to keep the system fresh.
(
    last_reboot_day=""
    while true; do
        current_day=$(date +%F)
        current_time=$(date +%H%M)
        if [ "$current_time" = "0000" ] && [ "$current_day" != "$last_reboot_day" ]; then
            echo "$(date) Scheduled midnight reboot initiated." >>"$log_file"
            sudo reboot
            last_reboot_day="$current_day"
        fi
        sleep 60
    done
) &

while true; do
    /usr/bin/python3 app.py >>"$log_file" 2>&1
    echo "$(date) app.py crashed, restarting..." >>"$log_file"
    sleep 3
done
