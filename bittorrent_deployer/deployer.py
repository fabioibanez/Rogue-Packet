"""Main Deployment Orchestrator for BitTorrent Network"""

import os
import time
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .aws_manager import AWSManager
from .log_server import LogServer, LogHandler
from .utils import get_public_ip, generate_run_name
from .constants import (
    DEFAULT_CONFIG_PATH, LOGS_DIR, COMPLETION_CHECK_INTERVAL, ROLE_SEEDER, ROLE_LEECHER,
    COLOR_RESET, COLOR_BOLD, COLOR_RED, COLOR_GREEN, COLOR_YELLOW, COLOR_BLUE, 
    COLOR_MAGENTA, COLOR_CYAN
)


class BitTorrentDeployer:
    """Main deployment orchestrator for BitTorrent network testing"""
    
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        """Initialize the BitTorrent network deployer"""
        self.config = Config(config_path)
        self.aws_manager = AWSManager(self.config.get_aws_config())
        self.log_server = LogServer(self.config.get_controller_port())
        self.controller_ip = get_public_ip()
        self.region_instances = {}
        self.total_instance_count = 0
        self.cleanup_in_progress = False
        self.handler = None
        
        self.run_name = generate_run_name()
        LogHandler.set_run_name(self.run_name)
        
        for region in self.config.get_regions():
            self.total_instance_count += region['seeders'] + region['leechers']
        
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle keyboard interrupt (Ctrl+C) gracefully"""
        if self.cleanup_in_progress:
            print(f"\n{COLOR_RED}💀 Force terminating...{COLOR_RESET}")
            sys.exit(1)
        
        print(f"\n{COLOR_YELLOW}🛑 Starting graceful cleanup...{COLOR_RESET}")
        self.cleanup_in_progress = True
        self._emergency_cleanup()
        sys.exit(0)
    
    def _emergency_cleanup(self):
        """Emergency cleanup when interrupted"""
        print(f"{COLOR_YELLOW}🚨 Emergency cleanup initiated{COLOR_RESET}")
        
        try:
            if self.handler:
                print(f"{COLOR_CYAN}📡 Collecting available logs...{COLOR_RESET}")
                time.sleep(2)
                
                run_dir = os.path.join(LOGS_DIR, self.run_name)
                if os.path.exists(run_dir):
                    for file in os.listdir(run_dir):
                        if file.endswith('.log'):
                            file_path = os.path.join(run_dir, file)
                            file_size = os.path.getsize(file_path)
                            print(f"{COLOR_GREEN}📝 {file} ({file_size} bytes){COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during log collection: {e}{COLOR_RESET}")
        
        try:
            for region_name, instance_ids in self.region_instances.items():
                if instance_ids:
                    print(f"{COLOR_YELLOW}🔥 Terminating {len(instance_ids)} instances in {region_name}...{COLOR_RESET}")
                    try:
                        self.aws_manager.terminate_instances(region_name, instance_ids)
                        print(f"{COLOR_GREEN}✓ Terminated instances in {region_name}{COLOR_RESET}")
                    except Exception as e:
                        print(f"{COLOR_RED}✗ Error terminating instances in {region_name}: {e}{COLOR_RESET}")
                        
            if self.log_server:
                self.log_server.stop()
                print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
                
        except Exception as e:
            print(f"{COLOR_RED}⚠ Error during instance cleanup: {e}{COLOR_RESET}")
        
        print(f"\n{COLOR_YELLOW}🛑 Emergency cleanup completed{COLOR_RESET}")
        print(f"{COLOR_BLUE}📁 Logs saved in: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
    
    def _lookup_and_validate_amis(self):
        """Look up and validate AMIs for all regions"""
        print(f"\n{COLOR_BOLD}=== AMI Lookup ==={COLOR_RESET}")
        
        region_ami_map = {}
        all_regions = [region['name'] for region in self.config.get_regions()]
        
        for region_name in all_regions:
            print(f"🔍 Looking up Ubuntu 22.04 AMI for {region_name}...")
            
            ami_info, error = self.aws_manager.get_latest_ubuntu_ami(region_name)
            
            if ami_info:
                print(f"  {COLOR_GREEN}✓ Found AMI: {ami_info['ami_id']}{COLOR_RESET}")
                region_ami_map[region_name] = ami_info['ami_id']
            else:
                print(f"  {COLOR_RED}✗ AMI lookup failed: {error}{COLOR_RESET}")
                return None, f"AMI lookup failed for {region_name}: {error}"
        
        print(f"{COLOR_GREEN}✅ All AMIs found across {len(all_regions)} regions{COLOR_RESET}")
        return region_ami_map, None
    
    def deploy_region(self, region_config, torrent_url, seed_fileurl, ami_id):
        """Deploy instances in a single region"""
        region_name = region_config['name']
        instance_ids = []
        
        for i in range(region_config['seeders']):
            instance_id = f"{region_name}-{ROLE_SEEDER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                seed_fileurl,
                ROLE_SEEDER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id)
            instance_ids.append(ec2_id)
        
        for i in range(region_config['leechers']):
            instance_id = f"{region_name}-{ROLE_LEECHER}-{i}"
            user_data = self.aws_manager.generate_user_data(
                self.config.get_bittorrent_config()['github_repo'],
                torrent_url,
                seed_fileurl,
                ROLE_LEECHER,
                self.controller_ip,
                self.config.get_controller_port(),
                instance_id
            )
            
            ec2_id = self.aws_manager.launch_instance(region_name, user_data, ami_id)
            instance_ids.append(ec2_id)
        
        return region_name, instance_ids
    
    def wait_for_completion(self, handler, timeout_minutes):
        """Wait for all instances to complete"""
        timeout = time.time() + (timeout_minutes * 60)
        
        while time.time() < timeout:
            if self.cleanup_in_progress:
                return False
            if len(handler.completion_status) >= self.total_instance_count:
                return True
            time.sleep(COMPLETION_CHECK_INTERVAL)
        
        return False
    
    def run(self):
        """Run the complete BitTorrent network deployment"""
        try:
            print(f"{COLOR_BOLD}{COLOR_MAGENTA}🚀 BitTorrent Network Deployment{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Run: {self.run_name}{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_BLUE}💾 Logs: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            print(f"{COLOR_YELLOW}💡 Press Ctrl+C for graceful cleanup{COLOR_RESET}")
            
            region_ami_map, ami_error = self._lookup_and_validate_amis()
            if ami_error:
                print(f"\n{COLOR_RED}💥 AMI validation failed: {ami_error}{COLOR_RESET}")
                return {}
            
            self.handler = self.log_server.start()
            print(f"\n{COLOR_GREEN}🌐 Log server started on port {self.config.get_controller_port()}{COLOR_RESET}")
            print(f"{COLOR_GREEN}🌍 Controller IP: {self.controller_ip}{COLOR_RESET}")
            
            torrent_url = self.config.get_bittorrent_config()['torrent_url']
            seed_fileurl = self.config.get_bittorrent_config()['seed_fileurl']
            github_repo = self.config.get_bittorrent_config()['github_repo']
            
            print(f"\n{COLOR_BOLD}=== Configuration ==={COLOR_RESET}")
            print(f"📂 Repo: {github_repo}")
            print(f"📁 Torrent: {torrent_url}")
            print(f"🌱 Seed: {seed_fileurl}")
            
            print(f"\n{COLOR_BOLD}=== Deployment Plan ==={COLOR_RESET}")
            for region in self.config.get_regions():
                ami_id = region_ami_map[region['name']]
                print(f"🌍 {region['name']}: {COLOR_GREEN}{region['seeders']} seeders{COLOR_RESET}, {COLOR_BLUE}{region['leechers']} leechers{COLOR_RESET}")
            print(f"📊 Total: {COLOR_BOLD}{self.total_instance_count}{COLOR_RESET} instances")
            
            print(f"\n{COLOR_BOLD}=== Launching Instances ==={COLOR_RESET}")
            with ThreadPoolExecutor() as executor:
                futures = []
                
                for region in self.config.get_regions():
                    ami_id = region_ami_map[region['name']]
                    futures.append(
                        executor.submit(
                            self.deploy_region,
                            region,
                            torrent_url,
                            seed_fileurl,
                            ami_id
                        )
                    )
                
                for future in futures:
                    if self.cleanup_in_progress:
                        break
                    region_name, instance_ids = future.result()
                    self.region_instances[region_name] = instance_ids
                    print(f"{COLOR_GREEN}✓ Launched {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            if self.cleanup_in_progress:
                return {}
                
            print(f"{COLOR_GREEN}✅ Deployed {self.total_instance_count} instances across {len(self.config.get_regions())} regions{COLOR_RESET}")
            
            print(f"\n{COLOR_BOLD}=== Monitoring Deployment ==={COLOR_RESET}")
            print("📊 Two phases: startup → core-run")
            print(f"⏱️  Timeout: {self.config.get_timeout_minutes()} minutes")
            print("=" * 50)
            
            LogHandler.display_simple_status()
            
            completed = self.wait_for_completion(self.handler, self.config.get_timeout_minutes())
            
            if self.cleanup_in_progress:
                return {}
            
            if completed:
                print(f"\n{COLOR_GREEN}✅ All instances completed{COLOR_RESET}")
            else:
                print(f"\n{COLOR_YELLOW}⚠ Timeout reached{COLOR_RESET}")
            
            LogHandler.display_simple_status()
            
            print(f"\n{COLOR_BOLD}=== Log Summary ==={COLOR_RESET}")
            run_dir = os.path.join(LOGS_DIR, self.run_name)
            
            for phase in ['startup', 'core-run']:
                phase_dir = os.path.join(run_dir, phase)
                if os.path.exists(phase_dir):
                    print(f"\n{COLOR_CYAN}📁 {phase.upper()}:{COLOR_RESET}")
                    for log_file in os.listdir(phase_dir):
                        if log_file.endswith('.log'):
                            log_path = os.path.join(phase_dir, log_file)
                            file_size = os.path.getsize(log_path)
                            print(f"  📝 {log_path} ({file_size} bytes)")
            
            if self.handler.completion_status:
                print(f"\n{COLOR_BOLD}=== Final Status ==={COLOR_RESET}")
                for instance_id, status in self.handler.completion_status.items():
                    print(f"✅ {instance_id}: {status}")
            
            print(f"\n{COLOR_BOLD}=== Cleanup ==={COLOR_RESET}")
            for region_name, instance_ids in self.region_instances.items():
                self.aws_manager.terminate_instances(region_name, instance_ids)
                print(f"{COLOR_GREEN}✓ Terminated {len(instance_ids)} instances in {region_name}{COLOR_RESET}")
            
            self.log_server.stop()
            print(f"{COLOR_GREEN}✓ Log server stopped{COLOR_RESET}")
            
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🎉 BitTorrent network test completed!{COLOR_RESET}")
            print(f"{COLOR_BOLD}{COLOR_YELLOW}📁 Logs: {LOGS_DIR}/{self.run_name}/{COLOR_RESET}")
            
            return self.handler.completion_status
            
        except KeyboardInterrupt:
            self._emergency_cleanup()
            sys.exit(0)
        except Exception as e:
            print(f"\n{COLOR_RED}💥 Unexpected error: {e}{COLOR_RESET}")
            if not self.cleanup_in_progress:
                self._emergency_cleanup()
            raise