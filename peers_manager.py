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
from typing import Iterable

from bitstring import BitArray


from pieces_manager import PiecesManager
from torrent import Torrent
from peer_choking_logger import PeerChokingLogger
from message import Message, Handshake, KeepAlive, Choke, UnChoke, Interested, NotInterested, Have, BitField, Request, PieceMessage, Cancel, Port
from peer import Peer

__author__ = 'alexisgallepe'

import select
from threading import Thread
from pubsub import pub
import logging
import errno
import socket


K_MINUS_1 = 3
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
        self.is_active: bool = True  # Controls the main thread loop

        # Initialize the choking logger
        self.choking_logger = PeerChokingLogger()

        # Events
        pub.subscribe(self.broadcast_have, 'PeersManager.BroadcastHave')

    @property
    def max_collective_download_rate(self) -> float:
        unchoked_peers = [peer for peer in self.peers if peer.is_unchoked()]
        return sum(peer.stats.calculate_download_rate() for peer in unchoked_peers)

    def confirm_send_to_peer(self, peer: peer.Peer) -> bool:
        # We only send a packet to a peer with probability:
        # (peer.download_rate / max_collective_download_rate)
        denom = self.max_collective_download_rate
        # NOTE: design decision, if 0 then just send since there's not proportional share
        if denom == 0:
            logging.info("\033[1;33m[Proportional Share] No download rate yet, sending to peer: %s\033[0m", peer.ip)
            return True
        
        peer_rate = peer.stats.calculate_download_rate()
        probability = peer_rate / denom
        should_send = random.uniform(0, 1) < probability
        
        logging.info("\033[1;33m[Proportional Share] Peer: %s, Rate: %.2f, Total Rate: %.2f, Probability: %.2f, Send: %s\033[0m",
                    peer.ip, peer_rate, denom, probability, should_send)
        
        return should_send

    def broadcast_have(self, piece_index: int, bitfield: BitArray) -> None:
        have_message = Have(piece_index)

        # Send the HAVE message to all peers, including those that are not interested
        # maybe they will be interested later
        for peer in self.peers:
            if not peer.healthy: continue
            peer.send_to_peer(have_message)
            logging.info("Sent HAVE message for piece index {} to peer: {}".format(piece_index, peer.ip))
            
            # If after completing a piece, the peer no longer has anything to offer, send a NOT INTERESTED message
            if peer.am_interested() and sum(~bitfield & peer.bitfield) == 0:
                peer.send_to_peer(NotInterested())
                
    def get_random_peer_having_piece(self, piece_index: int) -> Peer | None:
        ready_peers = []

        for peer in self.peers:
            if not peer.healthy: continue
            if peer.is_eligible() and peer.is_unchoked() and peer.am_interested() and peer.has_piece(piece_index):
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
                peer = Peer(self.torrent.number_of_pieces, ip, port)

                if any(peer.ip == ip for peer in self.peers):
                    logging.info(f"Got redundant incoming connection from {ip}:{port}... closing.")
                    conn.close()
                elif peer.connect(conn): 
                    self.add_peers([peer])
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
        # Remove unhealthy peers (clean out the trash)
        unhealthies = [peer for peer in peers if not peer.healthy]
        for peer in unhealthies:
            self.remove_peer(peer)

        for peer in peers:

            # Send handshake to peer
            if not self._do_handshake(peer):
                logging.error(f"Error handshaking with peer {peer.ip}")
                self.remove_peer(peer)
                continue

            # Ask pieces manager to send bitfield to this peer
            pub.sendMessage('PiecesManager.SendBitfield', peer=peer)

            self.peers.append(peer)


    def remove_peer(self, peer: Peer) -> None:
        try:
            peer.socket.close()
        except Exception:
            logging.exception("")

        if peer in self.peers: self.peers.remove(peer)
        if peer in self.unchoked_peers: self.unchoked_peers.remove(peer)
        if self.unchoked_optimistic_peer == peer: self.unchoked_optimistic_peer = None

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

        elif isinstance(new_message, PieceMessage):
            peer.handle_piece(new_message)

        elif isinstance(new_message, Cancel):
            peer.handle_cancel()

        elif isinstance(new_message, Port):
            peer.handle_port_request()

        else:
            logging.error("Unknown message")

    def update_unchoked_regular_peers(self, seed_mode: bool = False) -> None:
        prev_unchoked = self.unchoked_peers.copy()

        if not seed_mode:
            sorted_peers = sorted(self.peers, key=lambda peer: peer.stats.calculate_download_rate(), reverse=True) 
            sorted_peers = [peer for peer in sorted_peers if peer.am_interested()]
        else:
            sorted_peers = sorted(self.peers, key=lambda peer: peer.stats.calculate_upload_rate(), reverse=True)
        
        self.unchoked_peers = sorted_peers[:K_MINUS_1]

        to_choke = [peer for peer in prev_unchoked if peer not in self.unchoked_peers]

        for peer in to_choke:
            if not peer.am_choking():
                peer.send_to_peer(Choke())
                self.choking_logger.log_regular_choke(peer)

        for peer in self.unchoked_peers:
            if peer.am_choking():
                peer.send_to_peer(UnChoke())
                self.choking_logger.log_regular_unchoke(peer)
    
    def update_unchoked_optimistic_peers(self) -> None:
        eligible_peers = [peer for peer in self.peers if peer.is_interested() and peer.am_choking()]
        if not eligible_peers:
            logging.info("\033[1;35m[Optimistic unchoking] No eligible peers\033[0m")
            return
        
        # Choke the old optimistically unchoked peer
        if self.unchoked_optimistic_peer is not None:
            self.unchoked_optimistic_peer.send_to_peer(Choke())
            self.choking_logger.log_optimistic_choke(self.unchoked_optimistic_peer)
        
        lucky_peer = random.choice(eligible_peers)
        lucky_peer.send_to_peer(UnChoke())
        self.unchoked_optimistic_peer = lucky_peer
        
        self.choking_logger.log_optimistic_unchoke(lucky_peer)
