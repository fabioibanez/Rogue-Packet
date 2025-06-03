"""
Improved Log Server with Hybrid Approach - Real-time events + Pull-based logs
"""

import os
import json
import time
import threading
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from .constants import (
    LOGS_DIR, HTTP_OK, HTTP_NOT_FOUND, COMPLETION_ENDPOINT,
    COLOR_RESET, COLOR_BOLD, COLOR_RED, COLOR_GREEN,
    COLOR_YELLOW, COLOR_BLUE, COLOR_MAGENTA, COLOR_CYAN
)


class HybridLogHandler(BaseHTTPRequestHandler):
    """HTTP request handler with hybrid logging approach"""
    
    # Class variables for shared state
    logs_dir = LOGS_DIR
    completion_status = {}
    instance_states = {}
    instance_events = {}  # Store critical events
    run_name = None
    
    def log_message(self, format, *args):
        """Suppress default HTTP server access logs"""
        pass
    
    @classmethod
    def set_run_name(cls, run_name):
        """Set the run name and create log directories"""
        cls.run_name = run_name
        run_dir = os.path.join(cls.logs_dir, run_name)
        os.makedirs(run_dir, exist_ok=True)
        
        # Create events log file
        cls.events_log_path = os.path.join(run_dir, "events.log")
    
    @classmethod
    def update_instance_state(cls, instance_id, state):
        """Update instance state"""
        cls.instance_states[instance_id] = {
            'state': state,
            'timestamp': time.time()
        }
        cls.display_status()
    
    @classmethod
    def log_event(cls, instance_id, event_type, message):
        """Log a critical event"""
        timestamp = time.time()
        
        if instance_id not in cls.instance_events:
            cls.instance_events[instance_id] = []
        
        event = {
            'timestamp': timestamp,
            'type': event_type,
            'message': message
        }
        
        cls.instance_events[instance_id].append(event)
        
        # Write to events log file
        try:
            with open(cls.events_log_path, 'a') as f:
                log_line = f"[{datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}] {instance_id} | {event_type.upper()}: {message}\n"
                f.write(log_line)
                print(f"📢 {instance_id} | {event_type.upper()}: {message}")
        except Exception as e:
            print(f"⚠ Error writing event log: {e}")
    
    @classmethod
    def display_status(cls):
        """Display enhanced status with recent events"""
        print(f"\n=== BitTorrent Network Status ({cls.run_name}) ===")
        
        # Group by state
        states = {}
        for instance_id, info in cls.instance_states.items():
            state = info['state']
            if state not in states:
                states[state] = []
            states[state].append(instance_id)
        
        for state, instances in states.items():
            emoji = {
                'startup': '🔄',
                'core-run': '🚀', 
                'completed': '✅',
                'error': '❌'
            }.get(state, '❓')
            
            print(f"{emoji} {state.upper()}: {len(instances)} instances")
        
        # Show recent events (last 5)
        print(f"\n📢 Recent Events:")
        all_events = []
        for instance_id, events in cls.instance_events.items():
            for event in events[-2:]:  # Last 2 events per instance
                all_events.append((instance_id, event))
        
        # Sort by timestamp and show last 5
        all_events.sort(key=lambda x: x[1]['timestamp'], reverse=True)
        for instance_id, event in all_events[:5]:
            timestamp_str = datetime.fromtimestamp(event['timestamp']).strftime('%H:%M:%S')
            print(f"  [{timestamp_str}] {instance_id}: {event['message']}")
        
        total = len(cls.instance_states)
        completed = len(states.get('completed', []))
        print(f"\nTotal: {total} | Completed: {completed}")
        print("=" * 50)
    
    def do_POST(self):
        """Handle POST requests from EC2 instances"""
        if self.path == COMPLETION_ENDPOINT:
            self._handle_completion()
        elif self.path == '/state':
            self._handle_state_update()
        elif self.path == '/events':
            self._handle_events()
        else:
            self.send_response(HTTP_NOT_FOUND)
            self.end_headers()
    
    def _handle_events(self):
        """Handle critical event notifications"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            event_type = data.get('event')
            message = data.get('message')
            
            if instance_id and event_type and message:
                self.log_event(instance_id, event_type, message)
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_state_update(self):
        """Handle state updates from instances"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode())
            instance_id = data.get('instance_id')
            state = data.get('state')
            
            if instance_id and state:
                self.update_instance_state(instance_id, state)
                
        except json.JSONDecodeError:
            pass
        
        self.send_response(HTTP_OK)
        self.end_headers()
    
    def _handle_completion(self):
        """Handle completion notification from instances"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode())
        
        instance_id = data.get('instance_id')
        status = data.get('status')
        
        if instance_id:
            self.completion_status[instance_id] = status
            if status == "interrupted":
                self.update_instance_state(instance_id, "error")
            else:
                self.update_instance_state(instance_id, "completed")
        
        self.send_response(HTTP_OK)
        self.end_headers()


class HybridLogServer:
    """HTTP server wrapper with hybrid logging"""
    
    def __init__(self, port):
        self.port = port
        self.server = None
        self.handler = HybridLogHandler
    
    def start(self):
        """Start the HTTP server in a background thread"""
        self.server = HTTPServer(('0.0.0.0', self.port), self.handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        return self.handler
    
    def stop(self):
        """Stop the HTTP server"""
        if self.server:
            self.server.shutdown()


class EnhancedLogCollector:
    """Enhanced log collector with better error handling and features"""
    
    def __init__(self, run_name, logs_dir=LOGS_DIR):
        self.run_name = run_name
        self.logs_dir = logs_dir
        self.run_dir = os.path.join(logs_dir, run_name)
        os.makedirs(self.run_dir, exist_ok=True)
        
        self.instance_ips = {}
        self.log_port = 8081
        self.collection_thread = None
        self.stop_collection = threading.Event()
        self.collection_stats = {}
    
    def add_instance(self, instance_id, public_ip):
        """Add an instance to track for log collection"""
        self.instance_ips[instance_id] = public_ip
        self.collection_stats[instance_id] = {
            'startup_collected': False,
            'core_collected': False,
            'last_attempt': None,
            'attempt_count': 0
        }
        print(f"📍 Tracking logs for {instance_id} at {public_ip}")
    
    def fetch_health_status(self, instance_id, ip_address):
        """Get health status from instance"""
        try:
            url = f"http://{ip_address}:{self.log_port}/health"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None
    
    def fetch_logs_from_instance(self, instance_id, ip_address, log_type=None, lines='all'):
        """Fetch logs from a single instance with enhanced options"""
        stats = self.collection_stats[instance_id]
        stats['last_attempt'] = time.time()
        stats['attempt_count'] += 1
        
        try:
            log_types = [log_type] if log_type else ['startup', 'core-run']
            
            for lt in log_types:
                url = f"http://{ip_address}:{self.log_port}/logs/{lt}"
                if lines != 'all':
                    url += f"?lines={lines}"
                
                response = requests.get(url, timeout=10)
                if response.status_code == 200 and response.text.strip():
                    log_path = os.path.join(self.run_dir, f"{instance_id}_{lt}.log")
                    
                    with open(log_path, 'w') as f:
                        f.write(response.text)
                    
                    print(f"📝 Collected {lt} log from {instance_id} ({len(response.text)} chars)")
                    
                    if lt == 'startup':
                        stats['startup_collected'] = True
                    elif lt == 'core-run':
                        stats['core_collected'] = True
                    
        except requests.exceptions.RequestException as e:
            print(f"⚠ Failed to fetch logs from {instance_id} ({ip_address}): {e}")
        except Exception as e:
            print(f"⚠ Error processing logs from {instance_id}: {e}")
    
    def smart_log_collection(self):
        """Intelligent log collection based on instance state"""
        print(f"\n🧠 Smart log collection from {len(self.instance_ips)} instances...")
        
        for instance_id, ip_address in self.instance_ips.items():
            if self.stop_collection.is_set():
                break
            
            # Get health status to determine what logs to collect
            health = self.fetch_health_status(instance_id, ip_address)
            stats = self.collection_stats[instance_id]
            
            if health:
                state = health.get('state', 'unknown')
                
                # Collect startup logs if in core-run state and not yet collected
                if state in ['core-run', 'completed'] and not stats['startup_collected']:
                    self.fetch_logs_from_instance(instance_id, ip_address, 'startup')
                
                # Collect core logs if completed and not yet collected
                if state == 'completed' and not stats['core_collected']:
                    self.fetch_logs_from_instance(instance_id, ip_address, 'core-run')
                
                # For running instances, get tail of current logs
                elif state == 'core-run':
                    self.fetch_logs_from_instance(instance_id, ip_address, 'core-run', lines='50')
            else:
                # Instance not responding, try to get whatever we can
                self.fetch_logs_from_instance(instance_id, ip_address)
    
    def start_smart_collection(self, interval=30):
        """Start intelligent log collection"""
        def collection_loop():
            while not self.stop_collection.is_set():
                if self.instance_ips:
                    self.smart_log_collection()
                self.stop_collection.wait(interval)
        
        self.collection_thread = threading.Thread(target=collection_loop)
        self.collection_thread.daemon = True
        self.collection_thread.start()
        print(f"🧠 Started smart log collection (every {interval}s)")
    
    def final_log_collection(self):
        """Comprehensive final log collection"""
        print(f"\n📋 Final comprehensive log collection...")
        
        for instance_id, ip_address in self.instance_ips.items():
            print(f"🔍 Final collection from {instance_id}...")
            
            # Try to get all logs one final time
            self.fetch_logs_from_instance(instance_id, ip_address, 'startup')
            self.fetch_logs_from_instance(instance_id, ip_address, 'core-run')
            
            # Get combined logs as well
            try:
                url = f"http://{ip_address}:{self.log_port}/logs/all"
                response = requests.get(url, timeout=15)
                if response.status_code == 200 and response.text.strip():
                    log_path = os.path.join(self.run_dir, f"{instance_id}_combined.log")
                    with open(log_path, 'w') as f:
                        f.write(response.text)
                    print(f"📝 Collected combined log from {instance_id}")
            except:
                pass
        
        # Print collection summary
        print(f"\n📊 Collection Summary:")
        for instance_id, stats in self.collection_stats.items():
            startup = "✅" if stats['startup_collected'] else "❌"
            core = "✅" if stats['core_collected'] else "❌"
            print(f"  {instance_id}: Startup {startup} | Core {core} | Attempts: {stats['attempt_count']}")
        
        print("✅ Final log collection completed")
    
    def stop_log_collection(self):
        """Stop the log collection thread"""
        if self.collection_thread and self.collection_thread.is_alive():
            print("🛑 Stopping log collection...")
            self.stop_collection.set()
            self.collection_thread.join(timeout=5)
            print("✅ Log collection stopped")