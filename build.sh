#!/bin/bash
#
current_host=$(hostname)
#
if [ "$current_host" == "arial" ]; then
    TS=$(date +"%Y%M%d-%H%M")
    rm -rf .git
    rm .gitignore
    rm job.yaml
    rm NOTES.txt
    sudo docker build -t schlachet/bosch-monitor:${TS} .
    sudo docker push schlachet/bosch-monitor:${TS}
    echo "Timestamp: ${TS}"
else
    echo "Host mismatch. No action taken."
fi
