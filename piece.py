# piece.py

__author__ = 'alexisgallepe'

from dataclasses import dataclass
import hashlib
import math
import time
import logging

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from peer import Peer

BLOCK_SIZE = 2 ** 14

class BlockState(Enum):
    FREE = 0
    PENDING = 1
    FULL = 2

class Block():
    def __init__(self, state: BlockState = BlockState.FREE, block_size: int = BLOCK_SIZE, data: bytes = b'', last_seen: float = 0):
        self.state: BlockState = state
        self.block_size: int = block_size
        self.data: bytes = data
        self.last_seen: float = last_seen

    def __str__(self):
        return "%s - %d - %d - %d" % (self.state, self.block_size, len(self.data), self.last_seen)

@dataclass(frozen=True)
class PieceFileInfo:
    """
    Describes what section of a file that a section of a piece belongs to.
    A piece can have multiple of these (e.g. multiple files span across the length of one piece)
    """

    piece_index: int
    """ The index of the corresponding piece within the torrent """

    length: int
    """ The length of the region in bytes """

    file_offset: int
    """ The byte index of the beginning of this region in its containing file """

    piece_offset: int
    """ The byte index of the beginning of this region in its containing piece """

    path: str
    """ The relative path of the corresponding file within the torrent """


class Piece(object):
    def __init__(self, piece_index: int, piece_size: int, piece_hash: bytes):
        self.piece_index = piece_index
        self.piece_size = piece_size
        self.piece_hash = piece_hash
        self.is_full: bool = False
        self.file_info: list[PieceFileInfo] = []
        self.raw_data: bytes = b''
        self.number_of_blocks: int = int(math.ceil(float(piece_size) / BLOCK_SIZE))
        self.blocks: list[Block] = []
        self.peers: list['Peer'] = [] # Peers who have this piece

        self._init_blocks()

    # if block is pending for too long : set it free
    def update_block_status(self):
        for i, block in enumerate(self.blocks):
            if block.state == BlockState.PENDING and (time.time() - block.last_seen) > 5:
                self.blocks[i] = Block()

    def set_block(self, piece_offset: int, data: bytes):
        block_index = piece_offset // BLOCK_SIZE
        block = self.blocks[block_index]
        if block.state == BlockState.FULL: return
        if len(data) != block.block_size: return
        block.data = data
        block.state = BlockState.FULL

    def get_block(self, block_offset: int, block_length: int) -> bytes:
        return self.raw_data[block_offset:block_length]

    def get_empty_block(self):
        if self.is_full:
            return None

        for block_index, block in enumerate(self.blocks):
            if block.state == BlockState.FREE:
                self.blocks[block_index].state = BlockState.PENDING
                self.blocks[block_index].last_seen = time.time()
                return self.piece_index, block_index * BLOCK_SIZE, block.block_size

        return None

    def try_commit(self) -> bool:
        """
        Attempts to commit the piece on disk if it is complete.
        This will verify the piece's hash and set the piece as full if it is valid.
        If the hash is invalid, the piece will be reset.

        @return: True if the piece was committed, False otherwise
        """
        if any(block.state != BlockState.FULL for block in self.blocks):
            return False

        data = self._merge_blocks()
        if not len(data) == self.piece_size:
            return False

        if not self._valid_blocks(data):
            self._init_blocks()
            return False

        self.is_full = True
        self.raw_data = data
            
        return True

    def _init_blocks(self) -> None:
        self.blocks = []

        if self.number_of_blocks > 1:
            for _ in range(self.number_of_blocks):
                self.blocks.append(Block())

            # Last block of last piece, the special block
            if (self.piece_size % BLOCK_SIZE) > 0:
                self.blocks[self.number_of_blocks - 1].block_size = self.piece_size % BLOCK_SIZE

        else:
            self.blocks.append(Block(block_size=int(self.piece_size)))

    def write_to_disk(self) -> None:
        for info in self.file_info:
            try:
                f = open(info.path, 'r+b')  # Already existing file
            except IOError:
                f = open(info.path, 'wb')  # New file
            except Exception:
                logging.exception("Can't write to file")
                return

            f.seek(info.file_offset)
            f.write(self.raw_data[info.piece_offset:info.piece_offset + info.length])
            f.close()

    def _merge_blocks(self) -> bytes:
        buf = b''

        for block in self.blocks:
            buf += block.data

        return buf

    def _valid_blocks(self, piece_raw_data: bytes) -> bool:
        hashed_piece_raw_data = hashlib.sha1(piece_raw_data).digest()

        if hashed_piece_raw_data == self.piece_hash:
            return True

        logging.warning("Error Piece Hash")
        logging.debug("{} : {}".format(hashed_piece_raw_data, self.piece_hash))
        return False
