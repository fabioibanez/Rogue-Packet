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
from typing import List, Optional, Any, Type
from dataclasses import dataclass

import pieces_manager
import torrent

__author__ = 'alexisgallepe'

import select
from threading import Thread
from pubsub import pub
import rarest_piece
import logging
import message
import peer
import errno
import socket

##################
##################
##################

@dataclass
class PiecePeerInfo:
    """Information about which peers have a specific piece"""
    peer_count: int         # Number of peers that have this piece
    peers: List[peer.Peer]  # List of peers that have this piece

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
        self.rarest_pieces: rarest_piece.RarestPieces = rarest_piece.RarestPieces(pieces_manager)
        
        # self.pieces_by_peer is a list where each element is [count, [peers]]:
        # count is the number of peers that have the piece (this starts as)
        # [peers] is a list of peers that have the piece
        self.pieces_by_peer: List[PiecePeerInfo] = [PiecePeerInfo(0, []) for _ in range(pieces_manager.number_of_pieces)]
        self.is_active: bool = True  # Controls the main thread loop
        self.k_minus_1 = 3

        # Events
        pub.subscribe(self.peer_requests_piece, 'PeersManager.PeerRequestsPiece')
        # NOTE: This event is not actually used in their implementation
        pub.subscribe(self.peers_bitfield, 'PeersManager.updatePeersBitfield')

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

    def peers_bitfield(self, bitfield: Optional[Any] = None) -> None:
        for i in range(len(self.pieces_by_peer)):
            # Check if the peer has this piece (bitfield[i] == 1)
            peer_has_piece: bool = bitfield[i] == 1
            
            # Check if this peer is not already in our list of peers that have this piece
            peer_not_tracked: bool = peer not in self.pieces_by_peer[i].peers
            
            # Check if we're already tracking peers for this piece (count > 0)
            piece_has_peers: bool = self.pieces_by_peer[i].peer_count > 0
            
            if peer_has_piece and peer_not_tracked and piece_has_peers:
                self.pieces_by_peer[i].peers.append(peer)
                self.pieces_by_peer[i].peer_count = len(self.pieces_by_peer[i].peers)

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

    def _update_unchoked_regular_peers(self) -> None:
        # This is who is currently unchoked and we are sending data to
        prev_unchoked = self.unchoked_regular_peers.copy()
 
        # get the peers that we want to send data to
        peers_sorted_by_download_rate = sorted(self.peers, key=lambda peer: peer.stats.download_rate_ema, reverse=True) 
        peers_sorted_by_download_rate = list(filter(lambda peer: peer.am_interested(), peers_sorted_by_download_rate))
        self.unchoked_regular_peers = peers_sorted_by_download_rate[:self.k_minus_1] 
        
        # get peers who we WERE sending data to but are not in the new list
        to_choke = [peer for peer in prev_unchoked if peer not in self.unchoked_regular_peers]
        
        # choke those that are not in the new list
        for peer in to_choke:
            # if we are unchoking them, we choke them
            if not peer.am_choking():
                peer.send_to_peer(message.Choke().to_bytes())
                peer.state['am_interested'] = False
                logging.info("Choked peer : %s" % peer.ip)
        
        # unchoke those that are in the new list
        for peer in self.unchoked_regular_peers:
            # if we are choking them, we unchoke them
            if peer.am_choking():
                peer.send_to_peer(message.UnChoke().to_bytes())
                peer.state['am_interested'] = True
                logging.info("Unchoked peer : %s" % peer.ip)
    
    def _update_unchoked_optimistic_peers(self) -> None:
        # Unchoke the peer that was lucky the last time
        if self.unchoked_optimistic_peer is not None:
            self.unchoked_optimistic_peer.send_to_peer(message.Choke().to_bytes())
            logging.info("[Optimistic unchoking] Choke the old peer : %s" % self.unchoked_optimistic_peer.ip)
        
        # Get all the peers that we're interested in
        _interested_in: List[peer.Peer] = list(filter(lambda peer: peer.am_interested(), self.peers))
        # Get all the peers that we've already unchoked
        _already_unchoked: List[peer.Peer] = self.unchoked_regular_peers
        # Based on the above two lists, get all the peers that are eligible for optimistic unchoking
        eligible_for_optimistic_unchoking: List[peer.Peer] = list(set(_interested_in) - set(_already_unchoked))
        
        # Randomly select one of the peers that are eligible for optimistic unchoking, to unchoke
        (lucky_peer := random.choice(eligible_for_optimistic_unchoking)).send_to_peer(message.UnChoke().to_bytes())
        logging.info("[Optimistic unchoking] Unchoked peer : %s" % lucky_peer.ip)