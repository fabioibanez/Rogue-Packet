#!/usr/bin/env python3
"""
BitTorrent Network Deployment - Main Entry Point

This script deploys BitTorrent networks across multiple AWS regions
for testing peer-to-peer file sharing at scale.
"""

import sys
from .deployer import BitTorrentDeployer
from .constants import COLOR_YELLOW, COLOR_RED, COLOR_RESET


def main():
    """Main entry point for BitTorrent network deployment"""
    try:
        deployer = BitTorrentDeployer()
        result = deployer.run()
        
        if result:
            print(f"\n🎉 Deployment completed successfully!")
            print(f"✅ {len(result)} instances completed")
            return 0
        else:
            print(f"\n⚠ Deployment completed with issues")
            return 1
            
    except KeyboardInterrupt:
        print(f"\n{COLOR_YELLOW}🛑 Interrupted by user{COLOR_RESET}")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        print(f"\n{COLOR_RED}💥 Fatal error: {e}{COLOR_RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())