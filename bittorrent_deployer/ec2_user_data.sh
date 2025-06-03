#!/bin/bash
exec > /tmp/log 2>&1
apt-get update && apt-get install -y git python3 python3-pip curl
git clone -b feat/distribed {{GITHUB_REPO}} /tmp/bt && cd /tmp/bt
python3 -m pip install --upgrade pip && python3 -m pip install -r requirements.txt
mkdir -p {{TORRENT_TEMP_DIR}} {{SEED_TEMP_DIR}}
curl -L -o {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} {{TORRENT_URL}}
[ "{{ROLE}}" = "seeder" ] && curl -L -o {{SEED_TEMP_DIR}}/{{SEED_FILENAME}} {{SEED_FILEURL}}
export BITTORRENT_ROLE="{{ROLE}}" INSTANCE_ID="{{INSTANCE_ID}}"
echo "startup" > /tmp/state
curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id":"{{INSTANCE_ID}}","state":"startup"}' http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/state
(while [ "$(cat /tmp/state)" = "startup" ]; do [ -f /tmp/log ] && curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id":"{{INSTANCE_ID}}","phase":"startup","log_chunk":"'$(tail -n 10 /tmp/log | tr '\n' ' ')'"}'  http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/stream; sleep 15; done) &
echo "=== Setup complete ===" >> /tmp/log
echo "core-run" > /tmp/state
curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id":"{{INSTANCE_ID}}","state":"core-run"}' http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/state
echo "Starting BitTorrent {{ROLE}}" > {{LOG_FILE_PATH}}
(while [ "$(cat /tmp/state)" = "core-run" ]; do [ -f {{LOG_FILE_PATH}} ] && curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id":"{{INSTANCE_ID}}","phase":"core-run","log_chunk":"'$(tail -n 10 {{LOG_FILE_PATH}} | tr '\n' ' ')'"}'  http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/stream; sleep 15; done) &
[ "{{ROLE}}" = "seeder" ] && python3 -m main -s {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} >> {{LOG_FILE_PATH}} 2>&1 || python3 -m main {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} >> {{LOG_FILE_PATH}} 2>&1
echo "completed" > /tmp/state
curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=startup" -F "logfile=@/tmp/log" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs
curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=core-run" -F "logfile=@{{LOG_FILE_PATH}}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs
curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id":"{{INSTANCE_ID}}","status":"complete"}' http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion
shutdown -h now