from abc import ABC, abstractmethod
import random
from typing import Dict, List, Optional

import peer
from typeguard import typechecked


class PeerSelector(ABC):
    """Abstract base class for peer selection strategies"""
    
    @staticmethod
    @typechecked
    def get_ready_peers(peers: List[peer.Peer], piece_index: int) -> List[peer.Peer]:
        assert piece_index >= 0, f"Piece index must be a non-negative integer"
        
        return [p for p in peers
                if p.is_eligible() and
                p.is_unchoked() and
                p.am_interested() and
                p.has_piece(piece_index)]
    
    @abstractmethod
    def select_peer(self, peers: List[peer.Peer], piece_index: int) -> Optional[peer.Peer]:
        """Select a peer from the given list that has the specified piece"""
        pass


class RandomSelectionStrategy(PeerSelector):
    """Simple random peer selection strategy"""
    def select_peer(self, peers: List[peer.Peer], piece_index: int) -> Optional[peer.Peer]:
        ready_peers = PeerSelector.get_ready_peers(peers, piece_index)
        if not ready_peers:
            return None
        return random.choice(ready_peers)

# btw this isn't actually the proportional share strategy mentioned in the paper.
class RandomProportionalShareStrategy(PeerSelector):
    """Proportional share matching peer selection strategy"""
    def select_peer(self, peers: List[peer.Peer], piece_index: int) -> Optional[peer.Peer]:
        ready_peers = PeerSelector.get_ready_peers(peers, piece_index)
        if not ready_peers:
            return None

        ratios = []
        for p in ready_peers:
            ratio = p.get_upload_ratio()
            if ratio == float('inf'):
                return RandomSelectionStrategy().select_peer(ready_peers, piece_index)
            ratios.append(ratio)

        total_ratio = sum(ratios)
        if total_ratio == 0:
            return RandomSelectionStrategy().select_peer(ready_peers, piece_index)

        probabilities = [r / total_ratio for r in ratios]
        return random.choices(ready_peers, weights=probabilities, k=1)[0]

    @classmethod
    def get_name(cls) -> str:
        return "proportional-random"

class AuctionProportionalShareStrategy(PeerSelector):
    """Auction-based proportional share matching peer selection strategy"""
    def select_peer(self, peers: List[peer.Peer], piece_index: int) -> Optional[peer.Peer]:
        ready_peers = PeerSelector.get_ready_peers(peers, piece_index)
        if not ready_peers:
            return None
        
        raise NotImplementedError("Auction-based proportional share matching peer selection strategy not implemented")

##################
##################
##################

MAPPING_PEER_SELECTION_METHODS: Dict[str, PeerSelector] = {
    'random': RandomSelectionStrategy(),
    'proportional-random': RandomProportionalShareStrategy(),
    'auction-proportional': AuctionProportionalShareStrategy()
}