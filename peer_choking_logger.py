import csv
import time
from datetime import datetime
from typing import List, Optional, Dict
import peer
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path

class PeerChokingLogger:
    def __init__(self, log_file: str = "peer_choking_logs.csv"):
        self.log_file = log_file
        # Dictionary to track cumulative stats per peer IP
        self.peer_stats: Dict[str, Dict[str, int]] = {}
        self._initialize_csv()

    def _initialize_csv(self):
        """Initialize the CSV file with headers if it doesn't exist"""
        try:
            with open(self.log_file, 'x', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'event_type',  # 'regular_unchoke', 'regular_choke', 'optimistic_unchoke', 'optimistic_choke'
                    'peer_ip',
                    'download_rate_ema',
                    'is_interested',
                    'total_regular_unchokes',
                    'total_optimistic_unchokes',
                    'total_unchokes'
                ])
        except FileExistsError:
            pass  # File already exists, no need to initialize

    def _get_or_create_peer_stats(self, peer_ip: str) -> Dict[str, int]:
        """Get or create stats for a peer IP"""
        if peer_ip not in self.peer_stats:
            self.peer_stats[peer_ip] = {
                'regular_unchokes': 0,
                'optimistic_unchokes': 0
            }
        return self.peer_stats[peer_ip]

    def _update_peer_stats(self, event_type: str, peer_ip: str):
        """Update cumulative stats for a peer"""
        stats = self._get_or_create_peer_stats(peer_ip)
        if event_type == 'regular_unchoke':
            stats['regular_unchokes'] += 1
        elif event_type == 'optimistic_unchoke':
            stats['optimistic_unchokes'] += 1

    def _create_scatterplots(self):
        """Create scatterplots of download rates vs unchoke counts"""
        try:
            # Read the CSV file
            df = pd.read_csv(self.log_file)
            
            # Convert timestamp to datetime and sort by timestamp
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Get unique peers for coloring
            unique_peers = df['peer_ip'].unique()
            colors = plt.cm.rainbow(np.linspace(0, 1, len(unique_peers)))
            peer_color_map = dict(zip(unique_peers, colors))
            
            # Create figure with 3 subplots
            fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))
            
            # Plot 1: Rate vs Total Unchokes
            for peer_ip in unique_peers:
                peer_data = df[df['peer_ip'] == peer_ip].sort_values('timestamp')
                ax1.plot(peer_data['download_rate_ema'], 
                        peer_data['total_unchokes'],
                        color=peer_color_map[peer_ip],
                        alpha=0.3)  # Line connecting points
                ax1.scatter(peer_data['download_rate_ema'], 
                          peer_data['total_unchokes'],
                          color=peer_color_map[peer_ip],
                          label=peer_ip,
                          alpha=0.6)
            ax1.set_title('Download Rate vs Total Unchokes')
            ax1.set_xlabel('Download Rate EMA')
            ax1.set_ylabel('Total Unchokes')
            
            # Plot 2: Rate vs Regular Unchokes
            for peer_ip in unique_peers:
                peer_data = df[df['peer_ip'] == peer_ip].sort_values('timestamp')
                ax2.plot(peer_data['download_rate_ema'], 
                        peer_data['total_regular_unchokes'],
                        color=peer_color_map[peer_ip],
                        alpha=0.3)  # Line connecting points
                ax2.scatter(peer_data['download_rate_ema'], 
                          peer_data['total_regular_unchokes'],
                          color=peer_color_map[peer_ip],
                          label=peer_ip,
                          alpha=0.6)
            ax2.set_title('Download Rate vs Regular Unchokes')
            ax2.set_xlabel('Download Rate EMA')
            ax2.set_ylabel('Regular Unchokes')
            
            # Plot 3: Rate vs Optimistic Unchokes
            for peer_ip in unique_peers:
                peer_data = df[df['peer_ip'] == peer_ip].sort_values('timestamp')
                ax3.plot(peer_data['download_rate_ema'], 
                        peer_data['total_optimistic_unchokes'],
                        color=peer_color_map[peer_ip],
                        alpha=0.3)  # Line connecting points
                ax3.scatter(peer_data['download_rate_ema'], 
                          peer_data['total_optimistic_unchokes'],
                          color=peer_color_map[peer_ip],
                          label=peer_ip,
                          alpha=0.6)
            ax3.set_title('Download Rate vs Optimistic Unchokes')
            ax3.set_xlabel('Download Rate EMA')
            ax3.set_ylabel('Optimistic Unchokes')
            
            # Add legend to the last plot
            ax3.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            
            # Adjust layout and save
            plt.tight_layout()
            plt.savefig('peer_choking_plots.png', bbox_inches='tight', dpi=300)
            plt.close()
            
        except Exception as e:
            print(f"Error creating plots: {e}")

    def log_regular_unchoke(self, peer: peer.Peer):
        self._update_peer_stats('regular_unchoke', peer.ip)
        self._log_event('regular_unchoke', peer)

    def log_regular_choke(self, peer: peer.Peer):
        self._log_event('regular_choke', peer)

    def log_optimistic_unchoke(self, peer: peer.Peer):
        self._update_peer_stats('optimistic_unchoke', peer.ip)
        self._log_event('optimistic_unchoke', peer)

    def log_optimistic_choke(self, peer: peer.Peer):
        self._log_event('optimistic_choke', peer)

    def _log_event(self, event_type: str, peer: peer.Peer):
        stats = self._get_or_create_peer_stats(peer.ip)
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                event_type,
                peer.ip,
                peer.stats.download_rate_ema,
                peer.am_interested(),
                stats['regular_unchokes'],
                stats['optimistic_unchokes'],
                stats['regular_unchokes'] + stats['optimistic_unchokes']
            ])
        
        # Create plots after each update
        self._create_scatterplots()