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
from typing import List, Optional, TypeAlias

import pieces_manager
import torrent
import peer_choking_logger

__author__ = 'alexisgallepe'

import select
from threading import Thread
from pubsub import pub
import logging
import message
import peer
from peer import Peer 
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

        # NOTE: who has given me the most data, these are the regular peers that are unchoked
        self.unchoked_regular_peers : List[peer.Peer] = []  # List of regular unchoked peers
        # NOTE: this is the peer that we unchoke optimistically
        self.unchoked_optimistic_peer: Optional[peer.Peer] = None

        self.torrent: torrent.Torrent = torrent  # Torrent metadata
        self.pieces_manager: pieces_manager.PiecesManager = pieces_manager  # Manages pieces/blocks
        
        self.peers_by_piece: PeersByPiece = [[] for _ in range(pieces_manager.number_of_pieces)]
        self.is_active: bool = True  # Controls the main thread loop
        self.k_minus_1 = 3

        # Initialize the choking logger
        self.choking_logger = peer_choking_logger.PeerChokingLogger()

        # Events
        pub.subscribe(self.peer_requests_piece, 'PeersManager.PeerRequestsPiece')
        pub.subscribe(self.update_peers_bitfield, 'PeersManager.UpdatePeersBitfield')

        # added for HAVE message sending
        pub.subscribe(self.broadcast_have, 'PeersManager.BroadcastHave')

    def broadcast_have(self, piece_index: int) -> None:
        have_message = message.Have(piece_index).to_bytes()

        # Send the HAVE message to all peers, including those that are not interested
        # maybe they will be interested later
        for peer in self.peers:
            if peer.healthy:
                peer.send_to_peer(have_message)
                logging.info("Sent HAVE message for piece index {} to peer: {}".format(piece_index, peer.ip))


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
        return sorted(range(len(self.peers_by_piece)), key=lambda idx: len(self.peers_by_piece[idx]))


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

        server = socket.create_server(("0.0.0.0", 8000), reuse_port=True)
        server.setblocking(False)

        while self.is_active:
            try:
                conn, (ip, port) = server.accept()
                peer = Peer(int(self.torrent.number_of_pieces), ip, port, conn)
                self.add_peers([peer])
            except BlockingIOError:
                pass

            read = [peer.socket for peer in self.peers]
            read_list, _, _ = select.select(read, [], [], 1)

            for sock in read_list:
                peer: 'peer.Peer' = self.get_peer_by_socket(sock)
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

    def _update_unchoked_regular_peers(self) -> None:
        prev_unchoked = self.unchoked_regular_peers.copy()
        peers_sorted_by_download_rate = sorted(self.peers, key=lambda peer: peer.stats.calculate_download_rate(), reverse=True) 
        peers_sorted_by_download_rate = list(filter(lambda peer: peer.am_interested(), peers_sorted_by_download_rate))
        logging.info("\033[1;36m[Unchoke] Sorted peers by download_rate_ema: %s\033[0m", [(p.ip, p.stats.calculate_download_rate()) for p in peers_sorted_by_download_rate])
        self.unchoked_regular_peers = peers_sorted_by_download_rate[:self.k_minus_1] 
        logging.info("\033[1;36m[Unchoke] New unchoked_regular_peers: %s\033[0m", [p.ip for p in self.unchoked_regular_peers])
        logging.info("\033[1;36m[Unchoke] Previous unchoked_regular_peers: %s\033[0m", [p.ip for p in prev_unchoked])
        to_choke = [peer for peer in prev_unchoked if peer not in self.unchoked_regular_peers]
        logging.info("\033[1;36m[Unchoke] Peers to choke: %s\033[0m", [p.ip for p in to_choke])
        for peer in to_choke:
            if not peer.am_choking():
                peer.send_to_peer(message.Choke().to_bytes())
                logging.info("\033[1;36mChoked peer : %s\033[0m" % peer.ip)
                self.choking_logger.log_regular_choke(peer)
        for peer in self.unchoked_regular_peers:
            if peer.am_choking():
                peer.send_to_peer(message.UnChoke().to_bytes())
                logging.info("\033[1;36mUnchoked peer : %s\033[0m" % peer.ip)
                self.choking_logger.log_regular_unchoke(peer)
    
    def _update_unchoked_optimistic_peers(self) -> None:
        if self.unchoked_optimistic_peer is not None:
            self.unchoked_optimistic_peer.send_to_peer(message.Choke().to_bytes())
            logging.info("\033[1;35m[Optimistic unchoking] Choke the old peer : %s\033[0m" % self.unchoked_optimistic_peer.ip)
            self.choking_logger.log_optimistic_choke(self.unchoked_optimistic_peer)
        _interested_in: List[peer.Peer] = list(filter(lambda peer: peer.am_interested(), self.peers))
        if not _interested_in:
            logging.info("\033[1;35m[Optimistic unchoking] No interested peers\033[0m")
            return
        _already_unchoked: List[peer.Peer] = self.unchoked_regular_peers
        eligible_for_optimistic_unchoking: List[peer.Peer] = list(set(_interested_in) - set(_already_unchoked))
        logging.info("\033[1;35m[Optimistic unchoking] Eligible peers: %s\033[0m", [p.ip for p in eligible_for_optimistic_unchoking])
        if not eligible_for_optimistic_unchoking:
            logging.info("\033[1;35m[Optimistic unchoking] No eligible peers to unchoke\033[0m")
            return
        lucky_peer = random.choice(eligible_for_optimistic_unchoking)
        lucky_peer.send_to_peer(message.UnChoke().to_bytes())
        self.unchoked_optimistic_peer = lucky_peer
        logging.info("\033[1;35m[Optimistic unchoking] Unchoked peer : %s\033[0m" % lucky_peer.ip)
        self.choking_logger.log_optimistic_unchoke(lucky_peer)
