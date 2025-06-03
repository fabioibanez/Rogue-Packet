"""
BitTorrent Network Deployment Package

This package provides tools for deploying BitTorrent networks across multiple AWS regions
for testing peer-to-peer file sharing at scale.
"""

from .config import Config
from .deployer import BitTorrentDeployer

__version__ = "1.0.0"
__author__ = "BitTorrent Network Testing Team"
__all__ = ['Config', 'BitTorrentDeployer']