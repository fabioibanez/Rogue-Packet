#     #!/usr/bin/env python
#     # -*- coding: utf-8 -*-

"""
# TODO: Things we need to do to modify this repository:

1. Proportional Share
> Status Quo: The current implementation picks a random peer at random and asks them for data.

# TODO
"""

from pprint import pprint
import sys
from block import State

__author__ = 'alexisgallepe'

import time
import peers_manager
import pieces_manager
import torrent
import tracker
import logging
import os
import message


SLEEP_FOR_NO_UNCHOKED: int = 1

class Run(object):
    percentage_completed = -1
    last_log_line = ""

    def __init__(self):
        try:
            torrent_file = sys.argv[1]
        except IndexError:
            logging.error("No torrent file provided!")
            sys.exit(0)
        
        # Declares a torrent object for the particular torrent file specified by the user
        self.torrent: torrent.Torrent = torrent.Torrent().load_from_path(path=torrent_file)
        # Declares a tracker object
        self.tracker: tracker.Tracker = tracker.Tracker(self.torrent)
        
        self.pieces_manager: pieces_manager.PiecesManager = pieces_manager.PiecesManager(torrent=self.torrent)
        # NOTE: `peers_manager.PeersManager` is actually inherited from `threading.Thread`
        self.peers_manager: peers_manager.PeersManager = peers_manager.PeersManager(torrent=self.torrent,
                                                                                    pieces_manager=self.pieces_manager)

        self.peers_manager.start()  # This starts the peer manager thread:
        logging.info("PeersManager Started")
        logging.info("PiecesManager Started")

    def start(self):
        # Get all the peers from the trackers (which was embedded in the `announce_list` field of the  torrent file
        # provided by the user via a CLI option)
        
        peers_dict: dict = self.tracker.get_peers_from_trackers()
        
        # Tell the peers_manager who our peers are
        # A peer is anyone we have an open TCP connection with
        # so this will ultimately `be many more connections than we actually download from 
        self.peers_manager.add_peers(peers_dict.values())

        # While we haven't finished downloading the file
        while not self.pieces_manager.all_pieces_completed():
            # if there's no one can give us data then we wait
            if not self.peers_manager.has_unchoked_peers():
                time.sleep(SLEEP_FOR_NO_UNCHOKED)
                logging.info("No unchocked peers")
                continue
            
            # At this point, we have peers that can help us out / aka give us data
            
            # We go through every piece for the torrent file (based on what was inside the torrent file provided by the user)
            for piece in self.pieces_manager.pieces:
                # TODO: Unsure of this?
                index = piece.piece_index

                # If we have all the blocks for this piece, we can skip it
                # and move on to the next piece
                if self.pieces_manager.pieces[index].is_full:
                    continue
                
                # If we're here, we DON"T have all the blocks for this piece
                # We need to ask a peer for a block of this piece
                peer = self.peers_manager.get_random_peer_having_piece(index)
                # If we didn't find any such peer that has the piece, we try again
                if not peer:
                    continue
                
                # If I request a block from someone and I haven't received it from them,
                # they're fucking lackadaisical and I don't want to be their friend anymore
                self.pieces_manager.pieces[index].update_block_status()
                
                # Gets an empty block for the piece
                data = self.pieces_manager.pieces[index].get_empty_block()
                if not data:
                    continue

                piece_index, block_offset, block_length = data
                piece_data = message.Request(piece_index, block_offset, block_length).to_bytes()
                peer.send_to_peer(piece_data)

            self.display_progression()

            time.sleep(0.1)

        logging.info("File(s) downloaded successfully.")
        self.display_progression()

        self._exit_threads()

    def display_progression(self):
        new_progression = 0

        for i in range(self.pieces_manager.number_of_pieces):
            for j in range(self.pieces_manager.pieces[i].number_of_blocks):
                if self.pieces_manager.pieces[i].blocks[j].state == State.FULL:
                    new_progression += len(self.pieces_manager.pieces[i].blocks[j].data)

        if new_progression == self.percentage_completed:
            return

        number_of_peers = self.peers_manager.unchoked_peers_count()
        percentage_completed = float((float(new_progression) / self.torrent.total_length) * 100)

        current_log_line = "Connected peers: {} - {}% completed | {}/{} pieces".format(number_of_peers,
                                                                                         round(percentage_completed, 2),
                                                                                         self.pieces_manager.complete_pieces,
                                                                                         self.pieces_manager.number_of_pieces)
        if current_log_line != self.last_log_line:
            print(current_log_line)

        self.last_log_line = current_log_line
        self.percentage_completed = new_progression

    def _exit_threads(self):
        self.peers_manager.is_active = False
        os._exit(0)


if __name__ == '__main__':
    # Usage: clear && time python main.py <torrent_file>
    
    logging.basicConfig(level=logging.DEBUG)

    # Initializes the run object
    run = Run()
    run.start()
