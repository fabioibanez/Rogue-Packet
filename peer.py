# peer.py

import time
from typing import Optional

__author__ = 'alexisgallepe'

import socket
import struct
import bitstring
from pubsub import pub
import logging
import message
import time
import math

class PeerStats:
    def __init__(self, time_window: float = 20.0):
        self.bytes_uploaded = 0
        self.bytes_downloaded = 0
        self.last_upload_time = time.monotonic()
        self.last_download_time = time.monotonic()
        
        self.time_window = time_window  # in seconds
        self.dictionary_of_bytes_received_with_time: dict[float, int] = {}

    def update_upload(self, bytes_sent: int) -> None:
        self.bytes_uploaded += bytes_sent
        self.last_upload_time = time.monotonic()

    def update_download(self, bytes_received: int) -> None:
        self.bytes_downloaded += bytes_received
        self.dictionary_of_bytes_received_with_time[time.monotonic()] = bytes_received

    def calculate_download_rate(self) -> float:
        '''
        This will be called when deciding which peer to unchoke
        '''
        now = time.monotonic()
        weighted_sum = 0
        total_weight = 0
        for t, x in self.dictionary_of_bytes_received_with_time.items():
            dt = now - t
            w = math.exp(-dt / self.time_window)
            weighted_sum += x * w
            total_weight += w
        # this + 1 is a hack that adds an artificial datapoint now
        return weighted_sum / (total_weight + 1)

    def get_upload_ratio(self) -> float:
        if self.bytes_downloaded == 0:
            return float('inf')
        return self.bytes_uploaded / self.bytes_downloaded

##################
##################
##################

class Peer(object):
    def __init__(self, number_of_pieces, ip, port=6881, conn: socket.socket | None = None):
        self.last_call = 0.0
        self.has_handshaked = False
        self.healthy = False
        self.read_buffer = b''
        self.socket = conn
        self.ip = ip
        self.port = port
        self.number_of_pieces = number_of_pieces
        self.bit_field = bitstring.BitArray(number_of_pieces)
        self.state = {
            # NOTE: i am choking them
            'am_choking': True,
            'am_interested': False,
            # NOTE: they are choking us
            'peer_choking': True,
            'peer_interested': False,
        }
        self.stats = PeerStats()

    def __hash__(self):
        # Changed to return an integer hash value for proper optimistic unchoking
        return hash((self.ip, self.port))

    def connect(self):
        try:
            self.socket = socket.create_connection((self.ip, self.port), timeout=2)
            self.socket.setblocking(False)
            logging.debug("Connected to peer ip: {} - port: {}".format(self.ip, self.port))
            self.healthy = True

        except Exception as e:
            print("Failed to connect to peer (ip: %s - port: %s - %s)" % (self.ip, self.port, e.__str__()))
            return False

        return True

    def send_to_peer(self, msg):
        try:
            # TODO: rolling average for self.throughput
            self.socket.send(msg)
            self.last_call = time.time()
        except Exception as e:
            self.healthy = False
            logging.error("Failed to send to peer : %s" % e.__str__())

    def is_eligible(self):
        now = time.time()
        return (now - self.last_call) > 0.2

    def has_piece(self, index):
        return self.bit_field[index]

    def am_choking(self):
        return self.state['am_choking']

    def am_unchoking(self):
        return not self.am_choking()

    # They are choking us (they don't send us data)
    def is_choking(self):
        return self.state['peer_choking']

    # This means that they are not choking us (aka they are sending us data)
    def is_unchoked(self):
        return not self.is_choking()

    def is_interested(self):
        return self.state['peer_interested']

    # We are interested in them (we want to download data from them)
    # becuase they have pieces we don't have (probably based on bitfields)
    def am_interested(self):
        return self.state['am_interested']

    def handle_choke(self):
        logging.debug('handle_choke - %s' % self.ip)
        self.state['peer_choking'] = True

    def handle_unchoke(self):
        logging.debug('handle_unchoke - %s' % self.ip)
        self.state['peer_choking'] = False

    def handle_interested(self):
        logging.debug('handle_interested - %s' % self.ip)
        self.state['peer_interested'] = True

        if self.am_choking():
            unchoke = message.UnChoke().to_bytes()
            self.send_to_peer(unchoke)

    def handle_not_interested(self):
        logging.debug('handle_not_interested - %s' % self.ip)
        self.state['peer_interested'] = False

    def handle_have(self, have):
        """
        :type have: message.Have

        This method is called when a remote peer sends a message indicating that they have a
        particular piece.
        """
        logging.debug('handle_have - ip: %s - piece: %s' % (self.ip, have.piece_index))
        self.bit_field[have.piece_index] = True

        # NOTE: Piece Revelation
        # This is a peer telling us that they have a piece we don't have
        # We need to update our bitfield to reflect this

        # If they are choking us (aka we're not getting data from them),
        # and we are not interested in them
        if self.is_choking() and not self.state['am_interested']:
            interested = message.Interested().to_bytes()
            self.send_to_peer(interested)
            self.state['am_interested'] = True

        pub.sendMessage('PeersManager.UpdatePeersBitfield', peer=self, piece_index=have.piece_index)

    def handle_bitfield(self, bitfield):
        """
        :type bitfield: message.BitField
        """
        logging.debug('handle_bitfield - %s - %s' % (self.ip, bitfield.bitfield))
        self.bit_field = bitfield.bitfield

        if self.is_choking() and not self.state['am_interested']:
            interested = message.Interested().to_bytes()
            self.send_to_peer(interested)
            self.state['am_interested'] = True

        pub.sendMessage('PeersManager.UpdatePeersBitfield', peer=self, bit_field=self.bit_field)

    def handle_request(self, request: message.Request):
        """
        :type request: message.Request
        """
        logging.debug('handle_request - %s' % self.ip)
        if self.is_interested() and self.is_unchoked():
            pub.sendMessage('PiecesManager.PeerRequestsPiece', request=request, peer=self)
            # NOTE: by shounak, track upload when sending pieces
            self.update_upload_stats(len(request.to_bytes()))

    def handle_piece(self, message: message.Piece):
        """
        :type message: message.Piece
        """
        pub.sendMessage('PiecesManager.Piece', piece=(message.piece_index, message.block_offset, message.block))
        # NOTE: by shounak, track download when receiving pieces
        self.update_download_stats(len(message.block))

    def handle_cancel(self):
        logging.debug('handle_cancel - %s' % self.ip)

    def handle_port_request(self):
        logging.debug('handle_port_request - %s' % self.ip)

    def _handle_handshake(self):
        try:
            handshake_message = message.Handshake.from_bytes(self.read_buffer)
            self.has_handshaked = True
            self.read_buffer = self.read_buffer[handshake_message.total_length:]
            logging.debug('handle_handshake - %s' % self.ip)
            return True

        except Exception:
            logging.exception("First message should always be a handshake message")
            self.healthy = False

        return False

    def _handle_keep_alive(self):
        try:
            keep_alive = message.KeepAlive.from_bytes(self.read_buffer)
            logging.debug('handle_keep_alive - %s' % self.ip)
        except message.WrongMessageException:
            return False
        except Exception:
            logging.exception("Error KeepALive, (need at least 4 bytes : {})".format(len(self.read_buffer)))
            return False

        self.read_buffer = self.read_buffer[keep_alive.total_length:]
        return True

    def get_messages(self):
        while len(self.read_buffer) > 4 and self.healthy:
            if (not self.has_handshaked and self._handle_handshake()) or self._handle_keep_alive():
                continue

            payload_length, = struct.unpack(">I", self.read_buffer[:4])
            total_length = payload_length + 4

            if len(self.read_buffer) < total_length:
                break
            else:
                payload = self.read_buffer[:total_length]
                self.read_buffer = self.read_buffer[total_length:]

            try:
                received_message = message.MessageDispatcher(payload).dispatch()
                if received_message:
                    yield received_message
            except message.WrongMessageException as e:
                logging.exception(e.__str__())

    def update_upload_stats(self, bytes_sent: int) -> None:
        self.stats.update_upload(bytes_sent)

    def update_download_stats(self, bytes_received: int) -> None:
        self.stats.update_download(bytes_received)

    def get_upload_ratio(self) -> float:
        return self.stats.get_upload_ratio()
