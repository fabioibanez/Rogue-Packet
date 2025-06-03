#!/bin/bash
# EC2 User Data Script for BitTorrent Network Deployment
# This script will have variables substituted by the Python deployer

# Capture all output to startup log (without debug command echoing)
exec > >(tee -a /tmp/startup.log) 2>&1

# Function to update VM state locally and notify controller (isolated from debug logging)
update_vm_state() {
    ( # Run in subshell to isolate from any debug logging
        set +x  # Disable debug logging for this function
        local state="$1"
        echo "$state" > /tmp/vm_state.txt
        curl -s -X POST -H "Content-Type: application/json" \
            -d '{"instance_id": "{{INSTANCE_ID}}", "state": "'"$state"'", "timestamp": '$(date +%s)'}' \
            http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/state >/dev/null 2>&1 || true
    ) 2>/dev/null
}

# Function to send log chunks to controller (simplified and working)
send_log_chunk() {
    local phase="$1"
    local log_file="$2"
    
    if [ -f "$log_file" ] && [ -s "$log_file" ]; then
        # Get last 50 lines and send them
        local log_content=$(tail -n 50 "$log_file" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')
        
        # Send to controller
        curl -s -X POST -H "Content-Type: application/json" \
            -d "{\"instance_id\": \"{{INSTANCE_ID}}\", \"phase\": \"$phase\", \"log_chunk\": \"$log_content\", \"timestamp\": $(date +%s)}" \
            http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/stream >/dev/null 2>&1 || true
            
        echo "Sent $phase log chunk to controller ($(wc -l < "$log_file") total lines)"
    else
        echo "Log file $log_file does not exist or is empty"
    fi
}

# Function to stream logs periodically (simplified and working)
start_log_streaming() {
    local phase="$1"
    local log_file="$2"
    
    echo "=== Starting log streaming for $phase phase ==="
    echo "Monitoring file: $log_file"
    echo "Current VM state: $(cat /tmp/vm_state.txt 2>/dev/null || echo 'unknown')"
    
    (
        # Stream logs every 10 seconds while in the specified phase
        while [ "$(cat /tmp/vm_state.txt 2>/dev/null || echo unknown)" = "$phase" ]; do
            echo "[$phase] Checking for logs to stream..."
            if [ -f "$log_file" ]; then
                echo "[$phase] Found log file, sending chunk..."
                send_log_chunk "$phase" "$log_file"
            else
                echo "[$phase] Log file $log_file not found yet"
            fi
            sleep 10
        done
        echo "[$phase] Log streaming stopped - phase changed from $phase"
    ) &
    
    echo "Started background log streaming for $phase (monitoring $log_file)"
}

# Function to send final logs on exit (isolated from debug logging)
send_final_logs() {
    ( # Run in subshell to isolate from debug logging
        set +x  # Disable debug logging
        echo "=== Sending final logs to controller ==="
        update_vm_state "error"
        
        # Stop any running log streaming
        pkill -f "send_log_chunk" 2>/dev/null || true
        sleep 1
        
        # Send startup logs if they exist
        if [ -f /tmp/startup.log ]; then
            curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=startup" -F "logfile=@/tmp/startup.log" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs || true
        fi
        
        # Send core-run logs if they exist
        if [ -f {{LOG_FILE_PATH}} ]; then
            curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=core-run" -F "logfile=@{{LOG_FILE_PATH}}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs || true
        fi
        
        curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id": "{{INSTANCE_ID}}", "status": "interrupted"}' http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion || true
    ) 2>/dev/null
}

# Set up trap to send logs on any exit
trap 'send_final_logs' EXIT TERM INT

echo "=== Starting instance setup for {{INSTANCE_ID}} ==="
echo "Role: {{ROLE}}"
echo "Torrent URL: {{TORRENT_URL}}"
echo "Controller: {{CONTROLLER_IP}}:{{CONTROLLER_PORT}}"
echo "Timestamp: $(date)"

# Set initial state and add some test content to startup log
update_vm_state "startup"

# Add some test entries to startup log to make sure streaming works
echo "=== STARTUP LOG TEST ENTRIES ===" 
echo "Instance {{INSTANCE_ID}} started at $(date)"
echo "This is a test log entry for startup phase"
echo "Startup log should be streaming to controller"
echo "=== END TEST ENTRIES ==="

# Test the send_log_chunk function immediately
echo "=== Testing log streaming function ==="
echo "Startup log file size before test: $(wc -l < /tmp/startup.log) lines"
send_log_chunk "startup" "/tmp/startup.log"

echo "=== System Update ==="
apt-get update
echo "System update completed with exit code: $?"

echo "=== Installing System Packages ==="
apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev
echo "System packages installed with exit code: $?"

echo "=== Python and pip versions ==="
python3 --version
pip3 --version

echo "=== Cloning Repository ==="
git clone -b feat/distribed {{GITHUB_REPO}} {{BITTORRENT_PROJECT_DIR}}
echo "Git clone completed with exit code: $?"

cd {{BITTORRENT_PROJECT_DIR}}
echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

echo "=== Installing Python Dependencies ==="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --verbose --timeout 300
PIP_EXIT_CODE=$?
echo "pip install completed with exit code: $PIP_EXIT_CODE"

if [ $PIP_EXIT_CODE -ne 0 ]; then
    echo "ERROR: pip install failed!"
    update_vm_state "error"
    exit 1
fi

# Create necessary directories
mkdir -p {{TORRENT_TEMP_DIR}}
mkdir -p {{SEED_TEMP_DIR}}

echo "=== Downloading torrent file ==="
curl -L -o {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} {{TORRENT_URL}}
CURL_EXIT_CODE=$?
echo "curl completed with exit code: $CURL_EXIT_CODE"

# Role-specific setup
if [ "{{ROLE}}" == "seeder" ]; then
    echo "=== Seeder Setup: Downloading actual file ==="
    curl -L -o {{SEED_TEMP_DIR}}/{{SEED_FILENAME}} {{SEED_FILEURL}}
    SEED_CURL_EXIT_CODE=$?
    echo "Seed file download completed with exit code: $SEED_CURL_EXIT_CODE"
    
    if [ $SEED_CURL_EXIT_CODE -ne 0 ]; then
        echo "ERROR: Failed to download seed file!"
        update_vm_state "error"
        exit 1
    fi
else
    echo "=== Leecher Setup: No seed file needed ==="
fi

export BITTORRENT_ROLE="{{ROLE}}"
export INSTANCE_ID="{{INSTANCE_ID}}"
echo "{{INSTANCE_ID}}" > /tmp/instance_id.txt

# Start STARTUP phase log streaming only
echo "=== Starting STARTUP phase log streaming ==="
echo "Startup log file: /tmp/startup.log"
echo "Startup log exists: $([ -f /tmp/startup.log ] && echo 'YES' || echo 'NO')"
echo "Startup log size: $([ -f /tmp/startup.log ] && wc -l < /tmp/startup.log || echo '0') lines"
start_log_streaming "startup" "/tmp/startup.log"

# Give startup log streaming a moment to initialize
sleep 2

echo "=== Startup Complete - Transitioning to BitTorrent Core ==="
echo "==============================================="
echo "STARTUP PHASE COMPLETE - NO MORE STARTUP LOGS"
echo "==============================================="

# Send final startup logs with debug info
echo "=== Sending final startup log chunk ==="
echo "Final startup log size: $(wc -l < /tmp/startup.log) lines"
send_log_chunk "startup" "/tmp/startup.log"

# IMPORTANT: Stop all startup log streaming before moving to core-run
echo "=== Stopping startup log streaming ==="
pkill -f "send_log_chunk.*startup" 2>/dev/null || true
sleep 3  # Give time for processes to stop and final logs to be sent

# Ensure startup phase is completely finished
sync  # Force any pending writes to disk

# Transition to core-run phase
update_vm_state "core-run"

echo "============================================="
echo "CORE-RUN PHASE STARTING - BITTORRENT LOGS ONLY"
echo "============================================="

# Create the BitTorrent log file with initial content
echo "=== Creating BitTorrent log file ==="
echo "BitTorrent log file: {{LOG_FILE_PATH}}"
mkdir -p $(dirname {{LOG_FILE_PATH}})
echo "========================================" > {{LOG_FILE_PATH}}
echo "BITTORRENT LOG STARTED" >> {{LOG_FILE_PATH}}
echo "Instance: {{INSTANCE_ID}}" >> {{LOG_FILE_PATH}}
echo "Role: {{ROLE}}" >> {{LOG_FILE_PATH}}
echo "Timestamp: $(date)" >> {{LOG_FILE_PATH}}
echo "========================================" >> {{LOG_FILE_PATH}}

echo "Created BitTorrent log file: $([ -f {{LOG_FILE_PATH}} ] && echo 'YES' || echo 'NO')"
echo "Initial BitTorrent log size: $(wc -l < {{LOG_FILE_PATH}}) lines"

# Start CORE-RUN phase log streaming
echo "=== Starting CORE-RUN phase log streaming ==="  
start_log_streaming "core-run" "{{LOG_FILE_PATH}}"

# Give core-run log streaming a moment to initialize  
sleep 2

if [ "{{ROLE}}" == "seeder" ]; then
    echo "============================================="
    echo "STARTING BITTORRENT CLIENT AS SEEDER"
    echo "Command: python3 -m main -s {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}"
    echo "============================================="
    
    # Add clear marker to BitTorrent log file
    echo "========================================" >> {{LOG_FILE_PATH}}
    echo "BITTORRENT CLIENT STARTING AS SEEDER" >> {{LOG_FILE_PATH}}
    echo "Command: python3 -m main -s {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}" >> {{LOG_FILE_PATH}}
    echo "Working Directory: $(pwd)" >> {{LOG_FILE_PATH}}
    echo "Timestamp: $(date)" >> {{LOG_FILE_PATH}}
    echo "========================================" >> {{LOG_FILE_PATH}}
    
    echo "=== Running BitTorrent seeder ==="
    python3 -m main -s {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} >> {{LOG_FILE_PATH}} 2>&1
else
    echo "============================================="
    echo "STARTING BITTORRENT CLIENT AS LEECHER"
    echo "Command: python3 -m main {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}"
    echo "============================================="
    
    # Add clear marker to BitTorrent log file
    echo "========================================" >> {{LOG_FILE_PATH}}
    echo "BITTORRENT CLIENT STARTING AS LEECHER" >> {{LOG_FILE_PATH}}
    echo "Command: python3 -m main {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}" >> {{LOG_FILE_PATH}}
    echo "Working Directory: $(pwd)" >> {{LOG_FILE_PATH}}
    echo "Timestamp: $(date)" >> {{LOG_FILE_PATH}}
    echo "========================================" >> {{LOG_FILE_PATH}}
    
    echo "=== Running BitTorrent leecher ==="
    python3 -m main {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} >> {{LOG_FILE_PATH}} 2>&1
fi

echo "=== BitTorrent client execution finished ==="
echo "Final BitTorrent log size: $(wc -l < {{LOG_FILE_PATH}}) lines"

BITTORRENT_EXIT_CODE=$?

# Add completion marker to BitTorrent log file
echo "========================================" >> {{LOG_FILE_PATH}}
echo "BITTORRENT CLIENT COMPLETED" >> {{LOG_FILE_PATH}}
echo "Exit Code: $BITTORRENT_EXIT_CODE" >> {{LOG_FILE_PATH}}
echo "Timestamp: $(date)" >> {{LOG_FILE_PATH}}
echo "========================================" >> {{LOG_FILE_PATH}}

echo "============================================="
echo "BITTORRENT CLIENT COMPLETED WITH EXIT CODE: $BITTORRENT_EXIT_CODE"
echo "============================================="

echo "=== BitTorrent client finished ==="
update_vm_state "completed"

# Stop CORE-RUN log streaming
echo "=== Stopping ALL log streaming ==="
pkill -f "send_log_chunk" 2>/dev/null || true
sleep 2  # Give time for processes to stop

echo "=== Sending final logs to controller ==="
# Send final startup logs (isolated from debug logging)
( set +x; curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=startup" -F "logfile=@/tmp/startup.log" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs 2>/dev/null || true )

# Send final core-run logs (isolated from debug logging)  
( set +x; curl -s -X POST -F "instance_id={{INSTANCE_ID}}" -F "phase=core-run" -F "logfile=@{{LOG_FILE_PATH}}" http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/logs 2>/dev/null || true )

( set +x; curl -s -X POST -H "Content-Type: application/json" -d '{"instance_id": "{{INSTANCE_ID}}", "status": "complete"}' http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion 2>/dev/null || true )

echo "=== Instance setup completed ==="

# Remove the trap since we're exiting normally
trap - EXIT TERM INT

shutdown -h now