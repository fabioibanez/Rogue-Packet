# pieces_manager.py

__author__ = 'alexisgallepe'

from dataclasses import dataclass
import logging
import time
from typing import TypeAlias
from bitstring import BitArray
from message import BitField, Interested, NotInterested, PieceMessage, Request
from peer import Peer
from piece import Piece, PieceFileInfo
from pubsub import pub
from torrent import Torrent

REQUEST_TIMEOUT: float = 2.0

@dataclass(frozen=True)
class OutstandingRequest:
    piece_index: int
    piece_offset: int
    timestamp: float

    def expired(self, msg: PieceMessage | None = None) -> bool:
        if time.monotonic() - self.timestamp > REQUEST_TIMEOUT:
            return True
        if msg is not None and msg.piece_index == self.piece_index and msg.piece_offset == self.piece_offset:
            return True
        return False

class PiecesManager:
    def __init__(self, torrent: Torrent):
        self.torrent = torrent
        self.bitfield = BitArray(self.torrent.number_of_pieces)
        self.pieces = self._generate_pieces()
        self._outstanding_requests: list[OutstandingRequest] = []

        file_info = self._generate_file_info()
        for info in file_info:
            self.pieces[info.piece_index].file_info.append(info)

        self._read_from_disk()

        # events
        pub.subscribe(self.send_bitfield, 'PiecesManager.SendBitfield')
        pub.subscribe(self.peer_sent_piece, 'PiecesManager.PieceArrived')
        pub.subscribe(self.peer_requests_piece, 'PiecesManager.PieceRequested')
        pub.subscribe(self.update_peers_bitfield, 'PiecesManager.UpdatePeersBitfield')

    def log_request(self, request: Request) -> None:
        self._outstanding_requests.append(OutstandingRequest(request.piece_index, request.piece_offset, time.monotonic()))

    @property
    def outstanding_requests(self) -> int:
        return sum(1 for req in self._outstanding_requests if not req.expired())

    def send_bitfield(self, peer: Peer) -> None:
        peer.send_to_peer(BitField(self.bitfield))

    def peer_sent_piece(self, msg: PieceMessage, peer: Peer) -> None:
        if not peer.am_interested():
            return

        if self.pieces[msg.piece_index].is_full:
            return
        
        peer.stats.update_download(len(msg.block))

        # Remove any expired requests
        self._outstanding_requests = [req for req in self._outstanding_requests if not req.expired(msg)]

        piece = self.pieces[msg.piece_index]
        piece.set_block(msg.piece_offset, msg.block)
        if piece.try_commit():
            self.bitfield[piece.piece_index] = 1
            piece.write_to_disk()
            pub.sendMessage('PeersManager.BroadcastHave', piece_index=piece.piece_index, bitfield=self.bitfield)

    def peer_requests_piece(self, request: Request, peer: Peer) -> None:
        # If we've completed all pieces, we'll give data to anyone who requests it!
        # Otherwise, we will deny upload to peers that we are choking
        if not self.all_pieces_completed() and peer.am_choking():
            return
        
        piece = self.pieces[request.piece_index]
        if not piece.is_full: return
        block = piece.get_block(request.piece_offset, request.block_length)

        peer.send_to_peer(PieceMessage(request.block_length, request.piece_index, request.piece_offset, block))
        peer.stats.update_upload(len(block))
        logging.info(f"Sent piece index {request.piece_index} (bytes {request.piece_offset}-{request.piece_offset + request.block_length}) to peer {peer}")

    def update_peers_bitfield(
        self, 
        peer: Peer, 
        piece_index: int | None = None, 
        bitfield: BitArray | None = None
    ) -> None:
        """
        Called when a peer updates their bit field, either via a `bitfield` or `have` message.

        @param peer             The peer whose bitfield should be updated
        @param piece_index      Optionally, the index of the piece that the peer received
        @param bit_field        Optionally, the bit_field of the peer
        """

        if piece_index is not None:
            peers_list = self.pieces[piece_index].peers
            if peer not in peers_list:
                peers_list.append(peer)

            # If a peer has something we don't, tell them we're interested
            if self.bitfield[piece_index] == 0 and not peer.am_interested():
                peer.send_to_peer(Interested())
        
        if bitfield is not None:
            bitfield = bitfield[:len(self.bitfield)]
            peer.bitfield = bitfield
            for piece_index in range(len(bitfield)):
                if bitfield[piece_index] == 1:
                    self.update_peers_bitfield(peer, piece_index=piece_index)
    
    def enumerate_piece_indices_rarest_first(self) -> list[int]:
        """
        Enumerates the indices of pieces in rarest first order.

        This will return pieces which no known peers have.
        In other words, piece indices whose piece has a peer count of 0 will be returned.
        """
        return sorted(range(len(self.pieces)), key=lambda idx: len(self.pieces[idx].peers))

    def all_pieces_completed(self) -> bool:
        for piece in self.pieces:
            if not piece.is_full:
                return False
        return True
    
    @property
    def number_of_pieces(self) -> int:
        return self.torrent.number_of_pieces

    @property 
    def complete_pieces(self) -> int:
        return sum(1 for piece in self.pieces if piece.is_full)

    def _generate_pieces(self) -> list[Piece]:
        pieces = []
        last_piece = self.number_of_pieces - 1

        for i in range(self.number_of_pieces):
            start = i * 20
            end = start + 20

            if i == last_piece:
                piece_length = self.torrent.total_length - (self.number_of_pieces - 1) * self.torrent.piece_length
                pieces.append(Piece(i, piece_length, self.torrent.pieces[start:end]))
            else:
                pieces.append(Piece(i, self.torrent.piece_length, self.torrent.pieces[start:end]))

        return pieces

    def _generate_file_info(self) -> list[PieceFileInfo]:
        infos: list[PieceFileInfo] = []
        piece_offset = 0
        piece_size_used = 0

        for f in self.torrent.files:
            current_size_file = f.length
            file_offset = 0

            while current_size_file > 0:
                piece_index = int(piece_offset / self.torrent.piece_length)
                piece_size = self.pieces[piece_index].piece_size - piece_size_used

                if current_size_file - piece_size < 0:
                    file = PieceFileInfo(
                        piece_index=piece_index,
                        length=current_size_file,
                        file_offset=file_offset,
                        piece_offset=piece_size_used,
                        path=f.path
                    )
                    piece_offset += current_size_file
                    file_offset += current_size_file
                    piece_size_used += current_size_file
                    current_size_file = 0

                else:
                    current_size_file -= piece_size
                    file = PieceFileInfo(
                        piece_index=piece_index,
                        length=piece_size,
                        file_offset=file_offset,
                        piece_offset=piece_size_used,
                        path=f.path
                    )
                    piece_offset += piece_size
                    file_offset += piece_size
                    piece_size_used = 0

                infos.append(file)
        return infos

    def _read_from_disk(self) -> None:
        """Load and verify existing files to check which pieces are already complete."""
        for piece in self.pieces:
            if piece.is_full:
                continue

            # Read all blocks for this piece from disk
            piece_data = b''
            for info in sorted(piece.file_info, key=lambda x: x.piece_offset):
                try:
                    with open(info.path, 'rb') as f:
                        f.seek(info.file_offset)
                        data = f.read(info.length)
                        if len(data) == info.length:
                            piece_data += data
                        else:
                            break
                except (IOError, FileNotFoundError):
                    break
            else:
                offset = 0
                for block in piece.blocks:
                    piece.set_block(offset, piece_data[offset:offset + block.block_size])
                    offset += block.block_size
                
                if piece.try_commit():
                    self.bitfield[piece.piece_index] = 1
    
    
