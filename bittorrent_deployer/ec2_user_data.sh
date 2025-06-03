#!/bin/bash
exec > >(tee -a /tmp/startup.log) 2>&1

update_vm_state() {
  (set +x; echo "$1" > /tmp/vm_state.txt
  curl -s -X POST -H "Content-Type: application/json" -d "{\"instance_id\":\"{{INSTANCE_ID}}\",\"state\":\"$1\",\"timestamp\":$(date +%s)}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/state >/dev/null) 2>/dev/null
}

send_log_chunk() {
  [ -s "$2" ] || return
  local content=$(tail -n 50 "$2" | sed 's/"/\\"/g' | tr '\n' '\\n')
  curl -s -X POST -H "Content-Type: application/json" -d "{\"instance_id\":\"{{INSTANCE_ID}}\",\"phase\":\"$1\",\"log_chunk\":\"$content\",\"timestamp\":$(date +%s)}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/stream >/dev/null
}

start_log_streaming() {
  (while [ "$(cat /tmp/vm_state.txt 2>/dev/null)" = "$1" ]; do send_log_chunk "$1" "$2"; sleep 10; done) &
}

send_final_logs() {
  (set +x
  update_vm_state "error"
  pkill -f "send_log_chunk" 2>/dev/null
  sleep 1
  for phase in startup core-run; do
    file="/tmp/startup.log"
    [ "$phase" = "core-run" ] && file="{{LOG_FILE_PATH}}"
    [ -f "$file" ] && curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=$phase" -F "logfile=@$file" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs
  done
  curl -s -X POST -H "Content-Type: application/json" -d "{\"instance_id\":\"{{INSTANCE_ID}}\",\"status\":\"interrupted\"}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion) 2>/dev/null
}

trap 'send_final_logs' EXIT TERM INT

echo "=== Instance {{INSTANCE_ID}} ==="
update_vm_state "startup"

apt-get update && apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev
python3 --version && pip3 --version

git clone -b feat/distribed {{GITHUB_REPO}} {{BITTORRENT_PROJECT_DIR}}
cd {{BITTORRENT_PROJECT_DIR}}
python3 -m pip install --upgrade pip && python3 -m pip install -r requirements.txt --timeout 300 || { update_vm_state error; exit 1; }

mkdir -p {{TORRENT_TEMP_DIR}} {{SEED_TEMP_DIR}}
curl -L -o {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} {{TORRENT_URL}} || { update_vm_state error; exit 1; }

if [ "{{ROLE}}" = "seeder" ]; then
  curl -L -o {{SEED_TEMP_DIR}}/{{SEED_FILENAME}} {{SEED_FILEURL}} || { update_vm_state error; exit 1; }
fi

export BITTORRENT_ROLE="{{ROLE}}" INSTANCE_ID="{{INSTANCE_ID}}"
echo "{{INSTANCE_ID}}" > /tmp/instance_id.txt

start_log_streaming startup /tmp/startup.log
sleep 2
send_log_chunk startup /tmp/startup.log
pkill -f "send_log_chunk.*startup" 2>/dev/null
sync
update_vm_state core-run

mkdir -p $(dirname {{LOG_FILE_PATH}})
echo -e "BITTORRENT LOG STARTED\nInstance: {{INSTANCE_ID}}\nRole: {{ROLE}}\n$(date)" > {{LOG_FILE_PATH}}
start_log_streaming core-run {{LOG_FILE_PATH}}
sleep 2

CMD="python3 -m main"
[ "{{ROLE}}" = "seeder" ] && CMD+=" -s"
CMD+=" {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}"
echo "$CMD" >> {{LOG_FILE_PATH}}
$CMD >> {{LOG_FILE_PATH}} 2>&1
EXIT_CODE=$?

echo -e "BITTORRENT CLIENT COMPLETED\nExit Code: $EXIT_CODE\n$(date)" >> {{LOG_FILE_PATH}}
update_vm_state completed
pkill -f "send_log_chunk" 2>/dev/null
sleep 2

for phase in startup core-run; do
  file="/tmp/startup.log"
  [ "$phase" = "core-run" ] && file="{{LOG_FILE_PATH}}"
  [ -f "$file" ] && curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=$phase" -F "logfile=@$file" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs
done

curl -s -X POST -H "Content-Type: application/json" -d "{\"instance_id\":\"{{INSTANCE_ID}}\",\"status\":\"complete\"}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion

trap - EXIT TERM INT
shutdown -h now