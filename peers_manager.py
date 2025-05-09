# peers_manager.py

import random
from typing import Generator, List, Optional, TypeAlias

import pieces_manager
import torrent

__author__ = 'alexisgallepe'

import select
from threading import Thread
from pubsub import pub
import logging
import message
import peer
import errno
import socket

from bitstring import BitArray

##################
##################
##################

PeersByPiece: TypeAlias = List[List[peer.Peer]]
"""
Each element of this list is a list of peers who are known to have the piece with that index.
For example, `peersByPiece[0]` is all the peers who have piece 0
"""

##################
##################
##################

class PeersManager(Thread):    
    def __init__(self, torrent: torrent.Torrent,
                 pieces_manager: pieces_manager.PiecesManager) -> None:
        Thread.__init__(self)
        self.peers: List[peer.Peer] = []  # List of connected peers
        self.torrent: torrent.Torrent = torrent  # Torrent metadata
        self.pieces_manager: pieces_manager.PiecesManager = pieces_manager  # Manages pieces/blocks
        
        self.peers_by_piece: PeersByPiece = [[] for _ in range(pieces_manager.number_of_pieces)]
        self.is_active: bool = True  # Controls the main thread loop

        # Events
        pub.subscribe(self.peer_requests_piece, 'PeersManager.PeerRequestsPiece')
        pub.subscribe(self.update_peers_bitfield, 'PeersManager.UpdatePeersBitfield')

    # NOTE: I'm not going to tell peers out of my own volition what pieces I have,
    # but I will respond to their requests for pieces.
    def peer_requests_piece(self, request: Optional[message.Request] = None, peer: Optional[peer.Peer] = None) -> None:
        if not request or not peer:
            logging.error("empty request/peer message")
        if peer.am_choking():
            return

        piece_index: int = request.piece_index
        block_offset: int = request.block_offset
        block_length: int = request.block_length

        block: Optional[bytes] = self.pieces_manager.get_block(piece_index, block_offset, block_length)
        if block:
            piece: bytes = message.Piece(piece_index, block_offset, block_length, block).to_bytes()
            peer.send_to_peer(piece)
            # TODO: keep track of the amount of data sent to each peer
            logging.info("Sent piece index {} to peer : {}".format(request.piece_index, peer.ip))

    def update_peers_bitfield(
        self, 
        peer: peer.Peer, 
        piece_index: Optional[int] = None, 
        bit_field: Optional[BitArray] = None
    ) -> None:
        """
        Called when a peer updates their bit field, either via a `bitfield` or `have` message.

        @param peer             The peer whose bitfield should be updated
        @param piece_index      Optionally, the index of the piece that the peer received
        @param bit_field        Optionally, the bit_field of the peer
        """

        if piece_index is not None:
            peers_list = self.peers_by_piece[piece_index]
            if peer not in peers_list:
                peers_list.append(peer)
        
        if bit_field is not None:
            for piece_index in range(len(bit_field)):
                if bit_field[piece_index] == 1:
                    self.update_peers_bitfield(peer, piece_index=piece_index)

    def enumerate_piece_indices_rarest_first(self) -> List[int]:
        """
        Enumerates the indices of pieces in rarest first order.

        This will return pieces which no known peers have.
        In other words, piece indices whose piece has a peer count of 0 will be returned.
        """
        peer_counts = [[idx, len(peers)] for idx, peers in enumerate(self.peers_by_piece)]
        peer_counts = sorted(peer_counts, key=lambda elem: elem[1])
        return [idx for idx, _ in peer_counts]


    def get_random_peer_having_piece(self, index):
        ready_peers = []

        for peer in self.peers:
            if peer.is_eligible() and peer.is_unchoked() and peer.am_interested() and peer.has_piece(index):
                ready_peers.append(peer)

        # TODO: Select peer in ready list that has had highest historical upload bandwidth to us

        return random.choice(ready_peers) if ready_peers else None

    def has_unchoked_peers(self) -> bool:
        for peer in self.peers:
            if peer.is_unchoked():
                return True
        return False

    def unchoked_peers_count(self) -> int:
        cpt: int = 0
        for peer in self.peers:
            if peer.is_unchoked(): 
                cpt += 1
        return cpt


    @staticmethod
    def _read_from_socket(sock: socket.socket) -> bytes:
        data: bytes = b''

        while True:
            try:
                buff: bytes = sock.recv(4096)
                if len(buff) <= 0:
                    break

                data += buff
            except socket.error as e:
                err: int = e.args[0]
                if err != errno.EAGAIN or err != errno.EWOULDBLOCK:
                    logging.debug("Wrong errno {}".format(err))
                break
            except Exception:
                logging.exception("Recv failed")
                break

        return data

    def run(self) -> None:
        while self.is_active:
            read = [peer.socket for peer in self.peers]
            read_list, _, _ = select.select(read, [], [], 1)

            for socket in read_list:
                peer: 'peer.Peer' = self.get_peer_by_socket(socket)
                if not peer.healthy:
                    self.remove_peer(peer)
                    continue

                try:
                    payload: bytes = self._read_from_socket(socket)
                except Exception as e:
                    logging.error("Recv failed %s" % e.__str__())
                    self.remove_peer(peer)
                    continue

                peer.read_buffer += payload

                for message in peer.get_messages():
                    self._process_new_message(message, peer)

    def _do_handshake(self, peer: peer.Peer) -> bool:
        try:
            handshake: message.Handshake = message.Handshake(self.torrent.info_hash)
            peer.send_to_peer(handshake.to_bytes())
            logging.info("new peer added : %s" % peer.ip)
            return True

        except Exception:
            logging.exception("Error when sending Handshake message")

        return False

    def add_peers(self, peers: List[peer.Peer]) -> None:
        for peer in peers:
            if self._do_handshake(peer):
                self.peers.append(peer)
            else:
                print("Error _do_handshake")

    def remove_peer(self, peer: peer.Peer) -> None:
        if peer in self.peers:
            try:
                peer.socket.close()
            except Exception:
                logging.exception("")

            self.peers.remove(peer)

        # TODO: Hmmmmm is it really this
        #for rarest_piece in self.rarest_pieces.rarest_pieces:
        #    if peer in rarest_piece["peers"]:
        #        rarest_piece["peers"].remove(peer)

    def get_peer_by_socket(self, socket: socket.socket) -> peer.Peer:
        for peer in self.peers:
            if socket == peer.socket:
                return peer

        raise Exception("Peer not present in peer_list")

    def _process_new_message(self, new_message: message.Message, peer: peer.Peer) -> None:
        if isinstance(new_message, message.Handshake) or isinstance(new_message, message.KeepAlive):
            logging.error("Handshake or KeepALive should have already been handled")

        elif isinstance(new_message, message.Choke):
            peer.handle_choke()

        elif isinstance(new_message, message.UnChoke):
            peer.handle_unchoke()

        elif isinstance(new_message, message.Interested):
            peer.handle_interested()

        elif isinstance(new_message, message.NotInterested):
            peer.handle_not_interested()

        elif isinstance(new_message, message.Have):
            peer.handle_have(new_message)

        elif isinstance(new_message, message.BitField):
            peer.handle_bitfield(new_message)

        elif isinstance(new_message, message.Request):
            peer.handle_request(new_message)

        elif isinstance(new_message, message.Piece):
            peer.handle_piece(new_message)

        elif isinstance(new_message, message.Cancel):
            peer.handle_cancel()

        elif isinstance(new_message, message.Port):
            peer.handle_port_request()

        else:
            logging.error("Unknown message")
