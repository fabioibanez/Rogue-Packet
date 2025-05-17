# peers_manager.py

'''
every 10 seconds we go through the list of peers and 
select the top-k peers that have given us the most data
(highest download rate to me) those are the people that 
I unchoke

requires you to send a message to the peer to unchoke
keep track of choke/unchoke set
'''

import random
from typing import Iterable, TypeAlias

from bitstring import BitArray

from pieces_manager import PiecesManager
from torrent import Torrent
from peer_choking_logger import PeerChokingLogger
from message import Message, Handshake, KeepAlive, Choke, UnChoke, Interested, NotInterested, Have, BitField, Request, Piece, Cancel, Port
from peer import Peer

__author__ = 'alexisgallepe'

import select
from threading import Thread
from pubsub import pub
import logging
import errno
import socket

##################
##################
##################

PeersByPiece: TypeAlias = list[list[Peer]]
"""
Each element of this list is a list of peers who are known to have the piece with that index.
For example, `peersByPiece[0]` is all the peers who have piece 0
"""

K_MINUS_1 = 3

##################
##################
##################

class PeersManager(Thread):    
    def __init__(self, torrent: Torrent,
                 pieces_manager: PiecesManager) -> None:
        Thread.__init__(self)
        self.peers: list[Peer] = []  # List of connected peers

        # NOTE: who has given me the most data, these are the regular peers that are unchoked
        self.unchoked_peers: list[Peer] = []  # List of regular unchoked peers
        # NOTE: this is the peer that we unchoke optimistically
        self.unchoked_optimistic_peer: Peer | None = None

        self.torrent = torrent  # Torrent metadata
        self.pieces_manager = pieces_manager  # Manages pieces/blocks
        
        self.peers_by_piece: PeersByPiece = [[] for _ in range(pieces_manager.number_of_pieces)]
        self.is_active: bool = True  # Controls the main thread loop

        # Initialize the choking logger
        self.choking_logger = PeerChokingLogger()

        # Events
        pub.subscribe(self.peer_requests_piece, 'PeersManager.PeerRequestsPiece')
        pub.subscribe(self.update_peers_bitfield, 'PeersManager.UpdatePeersBitfield')

        # added for HAVE message sending
        pub.subscribe(self.broadcast_have, 'PeersManager.BroadcastHave')

    def broadcast_have(self, piece_index: int) -> None:
        have_message = Have(piece_index)

        # Send the HAVE message to all peers, including those that are not interested
        # maybe they will be interested later
        for peer in self.peers:
            if peer.healthy:
                peer.send_to_peer(have_message)
                logging.info("Sent HAVE message for piece index {} to peer: {}".format(piece_index, peer.ip))

    def peer_requests_piece(self, request: Request | None = None, peer: Peer | None = None) -> None:
        if not request or not peer:
            logging.error("empty request/peer message")
        if peer.am_choking():
            return

        piece_index: int = request.piece_index
        block_offset: int = request.block_offset
        block_length: int = request.block_length

        block = self.pieces_manager.get_block(piece_index, block_offset, block_length)
        if block:
            peer.send_to_peer(Piece(piece_index, block_offset, block_length, block))
            # TODO: keep track of the amount of data sent to each peer
            logging.info("Sent piece index {} to peer : {}".format(request.piece_index, peer.ip))

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
            peers_list = self.peers_by_piece[piece_index]
            if peer not in peers_list:
                peers_list.append(peer)
        
        if bitfield is not None:
            for piece_index in range(len(bitfield)):
                if bitfield[piece_index] == 1:
                    self.update_peers_bitfield(peer, piece_index=piece_index)

    def enumerate_piece_indices_rarest_first(self) -> list[int]:
        """
        Enumerates the indices of pieces in rarest first order.

        This will return pieces which no known peers have.
        In other words, piece indices whose piece has a peer count of 0 will be returned.
        """
        return sorted(range(len(self.peers_by_piece)), key=lambda idx: len(self.peers_by_piece[idx]))

    def get_random_peer_having_piece(self, index) -> Peer | None:
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
        server = socket.create_server(("0.0.0.0", 8000))
        server.setblocking(False)

        while self.is_active:
            try:
                conn, (ip, port) = server.accept()
                peer = Peer(int(self.torrent.number_of_pieces), ip, port)
                if peer.connect(conn): self.add_peers([peer])
            except BlockingIOError:
                pass

            read = [peer.socket for peer in self.peers]
            read_list, _, _ = select.select(read, [], [], 1)

            for sock in read_list:
                peer = self.get_peer_by_socket(sock)
                if not peer.healthy:
                    self.remove_peer(peer)
                    continue

                try:
                    payload: bytes = self._read_from_socket(sock)
                except Exception as e:
                    logging.error("Recv failed %s" % e.__str__())
                    self.remove_peer(peer)
                    continue

                peer.read_buffer += payload

                for message in peer.get_messages():
                    self._process_new_message(message, peer)

    def _do_handshake(self, peer: Peer) -> bool:
        try:
            peer.send_to_peer(Handshake(self.torrent.info_hash))
            logging.info("new peer added : %s" % peer.ip)
            return True

        except Exception:
            logging.exception("Error when sending Handshake message")

        return False

    def add_peers(self, peers: Iterable[Peer]) -> None:
        for peer in peers:
            if self._do_handshake(peer):
                self.peers.append(peer)
            else:
                print("Error handshaking with peer {peer}")

    def remove_peer(self, peer: Peer) -> None:
        try:
            peer.socket.close()
        except Exception:
            logging.exception("")

        if peer in self.peers: self.peers.remove(peer)
        if peer in self.unchoked_peers: self.unchoked_peers.remove(peer)
        if self.unchoked_optimistic_peer == peer: self.unchoked_optimistic_peer = None
        
        for peers in self.peers_by_piece:
            if peer in peers: peers.remove(peer)

    def get_peer_by_socket(self, sock: socket.socket) -> Peer:
        for peer in self.peers:
            if sock == peer.socket:
                return peer

        raise Exception("Peer not present in peer_list")

    def _process_new_message(self, new_message: Message, peer: Peer) -> None:
        if isinstance(new_message, Handshake) or isinstance(new_message, KeepAlive):
            logging.error("Handshake or KeepALive should have already been handled")

        elif isinstance(new_message, Choke):
            peer.handle_choke()

        elif isinstance(new_message, UnChoke):
            peer.handle_unchoke()

        elif isinstance(new_message, Interested):
            peer.handle_interested()

        elif isinstance(new_message, NotInterested):
            peer.handle_not_interested()

        elif isinstance(new_message, Have):
            peer.handle_have(new_message)

        elif isinstance(new_message, BitField):
            peer.handle_bitfield(new_message)

        elif isinstance(new_message, Request):
            peer.handle_request(new_message)

        elif isinstance(new_message, Piece):
            peer.handle_piece(new_message)

        elif isinstance(new_message, Cancel):
            peer.handle_cancel()

        elif isinstance(new_message, Port):
            peer.handle_port_request()

        else:
            logging.error("Unknown message")

    def _update_unchoked_regular_peers(self) -> None:
        prev_unchoked = self.unchoked_peers.copy()
        peers_sorted_by_download_rate = sorted(self.peers, key=lambda peer: peer.stats.calculate_download_rate(), reverse=True) 
        peers_sorted_by_download_rate = list(filter(lambda peer: peer.am_interested(), peers_sorted_by_download_rate))
        logging.info("\033[1;36m[Unchoke] Sorted peers by download_rate_ema: %s\033[0m", [(p.ip, p.stats.calculate_download_rate()) for p in peers_sorted_by_download_rate])
        self.unchoked_peers = peers_sorted_by_download_rate[:K_MINUS_1] 
        logging.info("\033[1;36m[Unchoke] New unchoked_regular_peers: %s\033[0m", [p.ip for p in self.unchoked_peers])
        logging.info("\033[1;36m[Unchoke] Previous unchoked_regular_peers: %s\033[0m", [p.ip for p in prev_unchoked])
        to_choke = [peer for peer in prev_unchoked if peer not in self.unchoked_peers]
        logging.info("\033[1;36m[Unchoke] Peers to choke: %s\033[0m", [p.ip for p in to_choke])
        for peer in to_choke:
            if not peer.am_choking():
                peer.send_to_peer(Choke())
                logging.info("\033[1;36mChoked peer : %s\033[0m" % peer.ip)
                self.choking_logger.log_regular_choke(peer)
        for peer in self.unchoked_peers:
            if peer.am_choking():
                peer.send_to_peer(UnChoke())
                logging.info("\033[1;36mUnchoked peer : %s\033[0m" % peer.ip)
                self.choking_logger.log_regular_unchoke(peer)
    
    def _update_unchoked_optimistic_peers(self) -> None:
        if self.unchoked_optimistic_peer is not None:
            self.unchoked_optimistic_peer.send_to_peer(Choke())
            logging.info("\033[1;35m[Optimistic unchoking] Choke the old peer : %s\033[0m" % self.unchoked_optimistic_peer.ip)
            self.choking_logger.log_optimistic_choke(self.unchoked_optimistic_peer)
        _interested_in = list(filter(lambda peer: peer.am_interested(), self.peers))
        if not _interested_in:
            logging.info("\033[1;35m[Optimistic unchoking] No interested peers\033[0m")
            return
        _already_unchoked: list[Peer] = self.unchoked_peers
        eligible_for_optimistic_unchoking: list[Peer] = list(set(_interested_in) - set(_already_unchoked))
        logging.info("\033[1;35m[Optimistic unchoking] Eligible peers: %s\033[0m", [p.ip for p in eligible_for_optimistic_unchoking])
        if not eligible_for_optimistic_unchoking:
            logging.info("\033[1;35m[Optimistic unchoking] No eligible peers to unchoke\033[0m")
            return
        lucky_peer = random.choice(eligible_for_optimistic_unchoking)
        lucky_peer.send_to_peer(UnChoke())
        self.unchoked_optimistic_peer = lucky_peer
        logging.info("\033[1;35m[Optimistic unchoking] Unchoked peer : %s\033[0m" % lucky_peer.ip)
        self.choking_logger.log_optimistic_unchoke(lucky_peer)
