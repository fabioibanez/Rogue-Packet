#!/usr/bin/env python3
"""
BitTorrent Network Deployment - Main Entry Point

This script deploys BitTorrent networks across multiple AWS regions
for testing peer-to-peer file sharing at scale.
"""

import sys
import argparse
from .deployer import BitTorrentDeployer
from .constants import COLOR_YELLOW, COLOR_RED, COLOR_RESET, DEFAULT_CONFIG_PATH


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Deploy BitTorrent networks across multiple AWS regions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m bittorrent_deployer.main
  python -m bittorrent_deployer.main --config my_config.yaml
  python -m bittorrent_deployer.main -c /path/to/config.yaml
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        default=DEFAULT_CONFIG_PATH,
        help=f'Path to configuration YAML file (default: {DEFAULT_CONFIG_PATH})'
    )
    
    return parser.parse_args()


def main():
    """Main entry point for BitTorrent network deployment"""
    try:
        args = parse_args()
        
        print(f"Using config file: {args.config}")
        
        deployer = BitTorrentDeployer(config_path=args.config)
        result = deployer.run()
        
        if result:
            print(f"\n🎉 Deployment completed successfully!")
            print(f"✅ {len(result)} instances completed")
            return 0
        else:
            print(f"\n⚠ Deployment completed with issues")
            return 1
            
    except FileNotFoundError as e:
        print(f"\n{COLOR_RED}💥 Config file not found: {e}{COLOR_RESET}")
        print(f"Make sure the config file exists at the specified path")
        return 2
    except KeyboardInterrupt:
        print(f"\n{COLOR_YELLOW}🛑 Interrupted by user{COLOR_RESET}")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        print(f"\n{COLOR_RED}💥 Fatal error: {e}{COLOR_RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())