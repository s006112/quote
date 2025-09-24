# /opt/panel/run.sh
#!/bin/bash
cd /opt/panel
while true; do
    /usr/bin/python3 app.py >>panel.log 2>&1
    echo "$(date) app.py crashed, restarting..." >>panel.log
    sleep 3
done
