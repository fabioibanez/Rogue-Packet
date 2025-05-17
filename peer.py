# peer.py

import time

from bitstring import BitArray

from piece import Piece

__author__ = 'alexisgallepe'

import socket
import struct
from pubsub import pub
import logging
from message import Choke, Handshake, Interested, KeepAlive, Message, MessageDispatcher, NotInterested, Request, UnChoke, WrongMessageException
import time
import math


def ema(series: dict[float, int], time_window: float) -> float:
    now = time.monotonic()
    weighted_sum = 0
    total_weight = 0
    for t, x in series.items():
        dt = now - t
        w = math.exp(-dt / time_window)
        weighted_sum += x * w
        total_weight += w
    # this + 1 is a hack that adds an artificial datapoint now
    return weighted_sum / (total_weight + 1)
class PeerStats:
    def __init__(self, time_window: float = 20.0):
        self.bytes_uploaded: int = 0
        self.bytes_downloaded: int = 0
        
        self.time_window = time_window  # in seconds
        self.bytes_received_over_time: dict[float, int] = {}
        self.bytes_sent_over_time: dict[float, int] = {}

    def update_upload(self, bytes_sent: int) -> None:
        """
        Indicate that we sent `bytes_sent` bytes to the peer.
        """
        self.bytes_uploaded += bytes_sent
        self.bytes_sent_over_time[time.monotonic()] = bytes_sent

    def update_download(self, bytes_received: int) -> None:
        """
        Indicate that we received `bytes_received` bytes from the peer.
        """
        self.bytes_downloaded += bytes_received
        self.bytes_received_over_time[time.monotonic()] = bytes_received

    def calculate_download_rate(self) -> float:
        """
        Determines the rate at which we are downloading data from the peer.
        """
        return ema(self.bytes_received_over_time, self.time_window)
    
    def calculate_upload_rate(self) -> float:
        """
        Determines the rate at which we are uploading data to the peer.
        """
        return ema(self.bytes_sent_over_time, self.time_window)


##################
##################
##################

class Peer(object):
    def __init__(self, number_of_pieces: int, ip: str, port: int=6881):
        self.last_call = 0.0
        self.has_handshaked = False
        self.healthy = False
        self.read_buffer: bytes = b''
        self.socket: socket.socket = None
        self.ip = ip
        self.port = port
        self.number_of_pieces = number_of_pieces
        self.bitfield = BitArray(self.number_of_pieces)
        self.state = {
            'am_choking': True,                 # Are we choking the peer?
            'am_interested': False,             # Are we interested in the peer?
            'peer_choking': True,               # Is the peer choking us?
            'peer_interested': False,           # Is the peer interested in us?
        }
        self.stats = PeerStats()

    def __hash__(self):
        return hash((self.ip, self.port))

    def connect(self, conn: socket.socket | None = None):
        if conn is not None:
            self.socket = conn
        else:
            try:
                self.socket = socket.create_connection((self.ip, self.port), timeout=2)
                logging.debug("Connected to peer ip: {} - port: {}".format(self.ip, self.port))

            except Exception as e:
                print("Failed to connect to peer (ip: %s - port: %s - %s)" % (self.ip, self.port, e.__str__()))
                return False

        self.socket.setblocking(False)
        self.healthy = True
        return True

    def send_to_peer(self, msg: Message):
        try:
            encoded = msg.to_bytes()
            self.socket.send(encoded)
            self.last_call = time.time()
        except Exception as e:
            self.healthy = False
            logging.error("Failed to send to peer : %s" % e.__str__())
            return
        
        if isinstance(msg, UnChoke): self.state['am_choking'] = False
        if isinstance(msg, Choke): self.state['am_choking'] = True
        if isinstance(msg, Interested): self.state['am_interested'] = True
        if isinstance(msg, NotInterested): self.state['am_interested'] = False

    def is_eligible(self):
        now = time.time()
        return (now - self.last_call) > 0.2

    def has_piece(self, index):
        return self.bitfield[index]

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
        self.bitfield[have.piece_index] = True

        # NOTE: Piece Revelation
        # This is a peer telling us that they have a piece we don't have
        # We need to update our bitfield to reflect this

        # If they are choking us (aka we're not getting data from them),
        # and we are not interested in them
        if self.is_choking() and not self.state['am_interested']:
            self.send_to_peer(Interested())
            self.state['am_interested'] = True

        pub.sendMessage('PeersManager.UpdatePeersBitfield', peer=self, piece_index=have.piece_index)

    def handle_bitfield(self, bitfield):
        """
        :type bitfield: message.BitField
        """
        logging.debug('handle_bitfield - %s - %s' % (self.ip, bitfield.bitfield))
        self.bitfield = bitfield.bitfield

        if self.is_choking() and not self.state['am_interested']:
            interested = Interested()
            self.send_to_peer(interested)
            self.state['am_interested'] = True

        pub.sendMessage('PeersManager.UpdatePeersBitfield', peer=self, bitfield=self.bitfield)

    def handle_request(self, request: Request):
        """
        :type request: message.Request
        """
        logging.debug('handle_request - %s' % self.ip)
        pub.sendMessage('PiecesManager.PieceRequested', request=request, peer=self)
            

    def handle_piece(self, message: Piece): 
        """
        :type message: message.Piece
        """
        pub.sendMessage('PiecesManager.PieceArrived', piece=message, peer=self)

    def handle_cancel(self):
        logging.debug('handle_cancel - %s' % self.ip)

    def handle_port_request(self):
        logging.debug('handle_port_request - %s' % self.ip)

    def _handle_handshake(self):
        try:
            handshake_message = Handshake.from_bytes(self.read_buffer)
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
            keep_alive = KeepAlive.from_bytes(self.read_buffer)
            logging.debug('handle_keep_alive - %s' % self.ip)
        except WrongMessageException:
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
                received_message = MessageDispatcher(payload).dispatch()
                if received_message:
                    yield received_message
            except WrongMessageException as e:
                logging.exception(e.__str__())

    def __repr__(self):
        state = ""
        if self.am_choking(): state += "C"
        if self.am_interested(): state += "I"
        if self.is_choking(): state += "c"
        if self.is_interested(): state += "i"
        return f"Peer(ip={self.ip}, state={state})"
    
    def __str__(self):
        return repr(self)
