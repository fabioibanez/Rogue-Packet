# torrent.py

from dataclasses import dataclass
import math

from helpers import print_torrent

__author__ = 'alexisgallepe'

import hashlib
import time
from bcoding import bencode, bdecode
import logging
import os

@dataclass(frozen=True)
class TorrentFile:
    path: str
    """ The relative path of this file """
    length: int
    """ The total length of the file in bytes """

class Torrent(object):
    def __init__(self):
        self.torrent_file: dict[str, any] = {}
        self.total_length: int = 0
        self.piece_length: int = 0
        self.pieces: bytes = b''
        self.info_hash: bytes = b''
        self.peer_id: bytes = b''
        self.announce_list: list[list[str]] = []
        self.files: list[TorrentFile] = []
        self.number_of_pieces: int = 0

    def load_from_path(self, path: str) -> 'Torrent':        
        with open(path, 'rb') as file:
            contents = bdecode(file)

        self.torrent_file = contents
        print_torrent(self.torrent_file)
        
        self.piece_length = self.torrent_file['info']['piece length']
        self.pieces = self.torrent_file['info']['pieces']
        raw_info_hash = bencode(self.torrent_file['info'])
        self.info_hash = hashlib.sha1(raw_info_hash).digest()
        self.peer_id = self.generate_peer_id()
        self.announce_list = self.get_trakers()
        self.init_files()
        self.number_of_pieces = math.ceil(self.total_length / self.piece_length)
        logging.debug(self.announce_list)
        logging.debug(self.files)

        assert(self.total_length > 0)
        assert(len(self.files) > 0)

        return self

    def init_files(self) -> None:
        root = self.torrent_file['info']['name']

        if 'files' in self.torrent_file['info']:
            if not os.path.exists(root):
                os.mkdir(root, 0o0766 )

            for file in self.torrent_file['info']['files']:
                path_file = os.path.join(root, *file["path"])

                if not os.path.exists(os.path.dirname(path_file)):
                    os.makedirs(os.path.dirname(path_file))

                self.files.append(TorrentFile(path_file, file["length"]))
                self.total_length += file["length"]

        else:
            self.files.append(TorrentFile(root, self.torrent_file['info']['length']))
            self.total_length = self.torrent_file['info']['length']

    def get_trakers(self) -> list[list[str]]:
        if 'announce-list' in self.torrent_file:
            return self.torrent_file['announce-list']
        else:
            return [[self.torrent_file['announce']]]

    def generate_peer_id(self) -> bytes:
        seed = str(time.time())
        return hashlib.sha1(seed.encode('utf-8')).digest()
