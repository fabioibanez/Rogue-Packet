"""
An alternative to tracker.Tracker that implements the same public interface
but operates on the local filesystem. This is used when simulating the network.
"""

from datetime import datetime, timedelta
import os
import fasteners
import json
from typing import List
from pydantic import BaseModel
import logging

from peer import Peer
from torrent import Torrent
from tracker import MAX_PEERS_CONNECTED


lock = fasteners.InterProcessLock("./mock_tracker.lock")


class MockLeecher(BaseModel):
    ip: str
    port: int
    expires: datetime

    def is_expired(self) -> bool:
        return datetime.now() > self.expires

class MockTracker:
    def __init__(self, 
        torrent: Torrent,
        tracker_file: os.PathLike, 
        local_ip: str, 
        local_port: int = 8000,
        expiry_seconds: int = 60 * 30
    ):
        self.torrent = torrent
        self.tracker_file = tracker_file
        self.local_ip = local_ip
        self.local_port = local_port
        self.expiry_seconds = expiry_seconds

    def _load(self) -> List[MockLeecher]:
        try:
            with open(self.tracker_file, 'r') as f:
                data = json.load(f)
                return [MockLeecher.model_validate(item) for item in data]
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            return []

    def _save(self, leechers: List[MockLeecher]) -> None:
        with open(self.tracker_file, 'w') as f:
            json.dump(
                [leecher.model_dump() for leecher in leechers],
                f,
                indent=2,
                default=str  # Handles datetime serialization
            )

    def _is_valid(self, leecher: MockLeecher, existing_peers: list[Peer] = []):
        if leecher.is_expired(): return False
        if leecher.ip == self.local_ip and leecher.port == self.local_port: return False
        if any(leecher.ip == p.ip and leecher.port == p.port for p in existing_peers): return False
        return True

    def get_peers_from_trackers(self, existing_peers: list[Peer] = []):
        with lock:
            leechers = self._load()

            # Get clients we have not seen before
            # These will be the peers we try to connect to and return 
            new_leechers = [l for l in leechers if self._is_valid(l, existing_peers)]

            # Get clients excluding ourselves and then add ourselves
            # This will be what we save back to the file
            leechers = [l for l in leechers if self._is_valid(l)]
            leechers.append(MockLeecher(
                ip=self.local_ip, 
                port=self.local_port, 
                expires=datetime.now() + timedelta(seconds=self.expiry_seconds)
            ))

            self._save(leechers)

        new_peers: List[Peer] = []
        for leecher in new_leechers:
            if len(new_peers) + len(existing_peers) >= MAX_PEERS_CONNECTED:
                break
                
            new_peer = Peer(int(self.torrent.number_of_pieces), leecher.ip, leecher.port)
            if not new_peer.connect():
                logging.info(f"Failed to connect to peer {leecher.ip}:{leecher.port}")
                continue
            new_peers.append(new_peer)
            logging.info(f'Connected to {len(new_peers)}/{MAX_PEERS_CONNECTED} peers')

        return new_peers
