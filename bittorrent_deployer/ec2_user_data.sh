#!/bin/bash

# Simple logging setup - all output goes to local files
STARTUP_LOG="/tmp/startup.log"
CORE_LOG="/tmp/bittorrent.log"
LOG_SERVER_PORT=8081

# Redirect all output to startup log initially
exec > >(tee -a $STARTUP_LOG) 2>&1

echo "=== Instance {{INSTANCE_ID}} | Role: {{ROLE}} started at $(date) ==="

# Simple state update function
update_vm_state() {
  echo "$1" > /tmp/vm_state.txt
  curl -s -X POST -H "Content-Type: application/json" \
    -d '{"instance_id": "{{INSTANCE_ID}}", "state": "'"$1"'", "timestamp": '$(date +%s)'}' \
    http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/state >/dev/null 2>&1 || true
}

# Start simple HTTP server for log serving
start_log_server() {
  echo "Starting log server on port $LOG_SERVER_PORT..."
  
  python3 -c "
import http.server
import socketserver
import os

class LogHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/logs/startup':
            self.serve_log('/tmp/startup.log')
        elif self.path == '/logs/core-run':
            self.serve_log('/tmp/bittorrent.log')
        elif self.path == '/logs/all':
            self.serve_combined_logs()
        elif self.path == '/health':
            self.serve_health()
        else:
            self.send_error(404, 'Endpoint not found')
    
    def serve_log(self, log_file):
        try:
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    content = f.read()
                
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content.encode())
            else:
                self.send_error(404, 'Log file not found')
        except Exception as e:
            self.send_error(500, f'Error reading log: {str(e)}')
    
    def serve_combined_logs(self):
        try:
            logs = []
            for log_file, name in [('/tmp/startup.log', 'STARTUP'), ('/tmp/bittorrent.log', 'CORE-RUN')]:
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        logs.append(f'=== {name} LOG ===')
                        logs.append(f.read())
                        logs.append('')
            
            content = '\n'.join(logs)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(content.encode())
        except Exception as e:
            self.send_error(500, f'Error combining logs: {str(e)}')
    
    def serve_health(self):
        try:
            import json
            status = {
                'instance_id': '{{INSTANCE_ID}}',
                'role': '{{ROLE}}',
                'state': open('/tmp/vm_state.txt', 'r').read().strip() if os.path.exists('/tmp/vm_state.txt') else 'unknown',
                'uptime': open('/proc/uptime', 'r').read().split()[0]
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        except Exception as e:
            self.send_error(500, f'Error getting health: {str(e)}')

with socketserver.TCPServer(('0.0.0.0', $LOG_SERVER_PORT), LogHandler) as httpd:
    httpd.serve_forever()
" &
  
  LOG_SERVER_PID=$!
  echo "Log server started with PID: $LOG_SERVER_PID"
}

# Cleanup function
cleanup() {
  echo "=== Cleanup initiated ==="
  update_vm_state "error"
  
  # Kill log server
  if [ ! -z "$LOG_SERVER_PID" ]; then
    kill $LOG_SERVER_PID 2>/dev/null || true
  fi
  
  # Send completion status
  curl -s -X POST -H "Content-Type: application/json" \
    -d '{"instance_id": "{{INSTANCE_ID}}", "status": "interrupted"}' \
    http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion || true
}

trap 'cleanup' EXIT TERM INT

# Update state and start log server
update_vm_state "startup"
start_log_server

echo "=== STARTUP PHASE ==="

# System updates
echo "Updating system packages..."
apt-get update || { echo "Failed to update packages"; exit 1; }

echo "Installing required packages..."
apt-get install -y git python3 python3-pip python3-dev python3-venv build-essential libssl-dev libffi-dev || {
  echo "Failed to install packages"
  exit 1
}

echo "Checking Python installation..."
python3 --version
pip3 --version

# Clone repository
echo "Cloning repository..."
git clone -b feat/distribed {{GITHUB_REPO}} {{BITTORRENT_PROJECT_DIR}} || {
  echo "Failed to clone repository"
  exit 1
}

cd {{BITTORRENT_PROJECT_DIR}}

# Install Python dependencies
echo "Installing Python dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --timeout 300 --verbose || {
  echo "Failed to install Python dependencies"
  exit 1
}

# Download files
echo "Creating directories and downloading files..."
mkdir -p {{TORRENT_TEMP_DIR}} {{SEED_TEMP_DIR}}

echo "Downloading torrent file..."
curl -L -o {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}} {{TORRENT_URL}} || {
  echo "Failed to download torrent file"
  exit 1
}

if [ "{{ROLE}}" = "seeder" ]; then
  echo "Downloading seed file..."
  curl -L -o {{SEED_TEMP_DIR}}/{{SEED_FILENAME}} {{SEED_FILEURL}} || {
    echo "Failed to download seed file"
    exit 1
  }
fi

# Environment setup
export BITTORRENT_ROLE="{{ROLE}}"
export INSTANCE_ID="{{INSTANCE_ID}}"
echo "{{INSTANCE_ID}}" > /tmp/instance_id.txt

echo "=== STARTUP COMPLETED, BEGINNING CORE RUN ==="
sync
update_vm_state "core-run"

# Switch logging to core run file
exec > >(tee -a $CORE_LOG) 2>&1

echo "========================================"
echo "BITTORRENT CORE LOG STARTED"
echo "Instance: {{INSTANCE_ID}} | Role: {{ROLE}} | $(date)"
echo "========================================"

# Build BitTorrent command
CMD="python3 -m main"
if [ "{{ROLE}}" = "seeder" ]; then
  CMD="$CMD -s"
fi
CMD="$CMD {{TORRENT_TEMP_DIR}}/{{TORRENT_FILENAME}}"

echo "Starting BitTorrent client with command: $CMD"
echo "Working directory: $(pwd)"
echo "Environment variables:"
echo "  BITTORRENT_ROLE=$BITTORRENT_ROLE"
echo "  INSTANCE_ID=$INSTANCE_ID"

# Run the BitTorrent client
eval "$CMD"
EXIT_CODE=$?

echo "========================================"
echo "BITTORRENT CLIENT COMPLETED"
echo "Exit Code: $EXIT_CODE"
echo "Completed at: $(date)"
echo "========================================"

# Update final state
update_vm_state "completed"

# Send completion notification
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"instance_id": "{{INSTANCE_ID}}", "status": "complete"}' \
  http://{{CONTROLLER_IP}}:{{CONTROLLER_PORT}}/completion || true

echo "Keeping log server running for 60 seconds to allow final log collection..."
sleep 60

# Clean shutdown
echo "Shutting down instance..."
trap - EXIT TERM INT
shutdown -h now