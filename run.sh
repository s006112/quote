#!/bin/bash
# /opt/panel/run.sh

cd /opt/panel
log_file="panel.log"

# Reboot the machine twice each day at 03:00 and 15:00 to keep the system fresh.
(
    last_reboot_marker=""
    while true; do
        current_day=$(date +%F)
        current_time=$(date +%H%M)
        if { [ "$current_time" = "0300" ] || [ "$current_time" = "1500" ]; } && [ "$last_reboot_marker" != "${current_day}-${current_time}" ]; then
            echo "$(date) Scheduled ${current_time} reboot initiated." >>"$log_file"
            sudo reboot
            last_reboot_marker="${current_day}-${current_time}"
        fi
        sleep 60
    done
) &

while true; do
    echo "$(date) app.py launch initiated." >>"$log_file"
    /usr/bin/python3 app.py >>"$log_file" 2>&1
    relaunch_time=$(date -d '+3 seconds' '+%Y-%m-%d %H:%M:%S')
    echo "$(date) app.py crashed, relaunch scheduled at ${relaunch_time}." >>"$log_file"
    sleep 3
done
