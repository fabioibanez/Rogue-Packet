# pieces_manager.py

__author__ = 'alexisgallepe'

from piece import Piece, PieceFileInfo
from bitstring import BitArray
from pubsub import pub
from torrent import Torrent

class PiecesManager:
    bitfield: BitArray

    def __init__(self, torrent: Torrent):
        self.torrent = torrent
        self.number_of_pieces = torrent.number_of_pieces
        self.bitfield = BitArray(self.number_of_pieces)
        self.pieces = self._generate_pieces()
        self.complete_pieces: int = 0

        file_info = self._generate_file_info()
        for info in file_info:
            self.pieces[info.piece_index].file_info.append(info)

        # events
        pub.subscribe(self.receive_block_piece, 'PiecesManager.Piece')
        # NOTE: Once a piece is completed, we update the bitfield
        # to indicate that the piece is completed
        pub.subscribe(self.update_bitfield, 'PiecesManager.PieceCompleted')

    def update_bitfield(self, piece_index: int) -> None:
        self.bitfield[piece_index] = 1

    def receive_block_piece(self, piece: tuple[int, int, bytes]) -> None:
        piece_index, piece_offset, piece_data = piece

        if self.pieces[piece_index].is_full:
            return

        self.pieces[piece_index].set_block(piece_offset, piece_data)

        if self.pieces[piece_index].are_all_blocks_full():
            if self.pieces[piece_index].set_to_full():
                self.complete_pieces +=1

    def get_block(self, piece_index: int, block_offset: int, block_length: int) -> bytes | None:
        for piece in self.pieces:
            if piece_index == piece.piece_index:
                if piece.is_full:
                    return piece.get_block(block_offset, block_length)
                else:
                    break

        return None

    def all_pieces_completed(self) -> bool:
        for piece in self.pieces:
            if not piece.is_full:
                return False

        return True

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
