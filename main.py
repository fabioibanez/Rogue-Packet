# main.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
# TODO: Things we need to do to modify this repository:

1. Proportional Share
> Status Quo: The current implementation picks a random peer at random and asks them for data.

# TODO
"""

import argparse
from block import State
from helpers import cleanup_torrent_download, plot_dirsize_overtime
import os
import threading

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
NO_PROGRESS_YET_SENTINEL: int = -1
n_secs_regular_unchoking: int = 10
n_secs_optimistic_unchoking: int = 30

class Run(object):
    percentage_completed = NO_PROGRESS_YET_SENTINEL
    last_log_line = ""
    plot_stop_event = threading.Event()

    def __init__(self):
        parser = argparse.ArgumentParser(description='BitTorrent client')
        parser.add_argument('torrent_file', help='Path to the torrent file')
        parser.add_argument('-v', '--verbose', action='store_true',
                          help='Enable verbose logging for peer selection')
        parser.add_argument('-d', '--deletetorrent', action='store_true',
                          help='Delete any existing, previous torrent folder for your specified torrent target. Speeds up testing.')
        args = parser.parse_args()
        self.args = args
        
        # Declares a torrent object for the particular torrent file specified by the user
        if args.deletetorrent:
            cleanup_torrent_download(torrent_file=args.torrent_file)
        self.torrent: torrent.Torrent = torrent.Torrent().load_from_path(path=args.torrent_file)
        
        
        # Declares a tracker object
        self.tracker: tracker.Tracker = tracker.Tracker(self.torrent)
        
        self.pieces_manager: pieces_manager.PiecesManager = pieces_manager.PiecesManager(torrent=self.torrent)
        # NOTE: `peers_manager.PeersManager` is actually inherited from `threading.Thread`
        self.peers_manager: peers_manager.PeersManager = peers_manager.PeersManager(
            torrent=self.torrent,
            pieces_manager=self.pieces_manager
        )
        self.verbose = args.verbose


        self.peers_manager.start()  # This starts the peer manager thread:
        self._start_plot_thread()
        
        logging.info("PeersManager Started")
        logging.info("PiecesManager Started")

    def _start_plot_thread(self) -> None:
        """Start the plot thread if a matching directory is found"""
        # Extract directory name from torrent path
        torrent_name = os.path.splitext(os.path.basename(self.args.torrent_file))[0]
        torrent_dir = torrent_name
        
        if os.path.isdir(torrent_dir):
            logging.info(f"\033[1;32mStarted plotting directory size for: {torrent_dir}\033[0m")
            plot_thread = threading.Thread(
                target=plot_dirsize_overtime,
                args=(torrent_dir, self.plot_stop_event, f"{torrent_dir}.png"),
                daemon=True
            )
            plot_thread.start()
            logging.info(f"\033[1;32mStarted plotting directory size for: {torrent_dir}\033[0m")

    def start(self):
        # Get all the peers from the trackers (which was embedded in the `announce_list` field of the  torrent file
        # provided by the user via a CLI option)
        
        peers_dict: dict = self.tracker.get_peers_from_trackers()
        
        # Tell the peers_manager who our peers are
        # A peer is anyone we have an open TCP connection with
        # so this will ultimately `be many more connections than we actually download from 
        self.peers_manager.add_peers(peers_dict.values())
        
        prev_time_regular_unchoking = time.monotonic()
        prev_time_optimistic_unchoking = time.monotonic()

        # While we haven't finished downloading the file
        while not self.pieces_manager.all_pieces_completed(): 
            # if there's no one can give us data then we wait and infinitely loop
            if not self.peers_manager.has_unchoked_peers():
                time.sleep(SLEEP_FOR_NO_UNCHOKED)
                if self.verbose:
                    logging.info("\033[1;31m[NO UNCHOKED] We're looking for an unchoked peer with desirable pieces, but we found no one yet.\033[0m")
                continue
            
            # At this point, we have peers that can help us out / aka give us data (that are unchoked)
            if self.verbose:
                logging.info("\033[1;32m[FOUND UNCHOKED] Found unchoked peers with pieces that we need\033[0m")
            
            # We go through every piece for the torrent file (based on what was inside the torrent file provided by the user)
            for index in self.peers_manager.enumerate_piece_indices_rarest_first():
                
                # If we have all the blocks for this piece, we can skip it
                # and move on to the next piece
                if self.pieces_manager.pieces[index].is_full:
                    continue
                
                # updates the unchoked peers state in the PeersManager and sends the unchoke message to the peers
                delta_regular_unchoking: float = time.monotonic() - prev_time_regular_unchoking
                if delta_regular_unchoking >= n_secs_regular_unchoking:
                    self.peers_manager._update_unchoked_regular_peers()        
                    prev_time_regular_unchoking = time.monotonic()
                
                # updates the optimistic unchoked peers state in the PeersManager and sends the unchoke message to the peers
                delta_optimistic_unchoking: float = time.monotonic() - prev_time_optimistic_unchoking
                if delta_optimistic_unchoking >= n_secs_optimistic_unchoking:
                    self.peers_manager._update_unchoked_optimistic_peers()
                    prev_time_optimistic_unchoking = time.monotonic()
                
                # If we're here, we DON"T have all the blocks for this piece
                # We need to ask a peer for a block of this piece
                peer: 'peer.Peer' = self.peers_manager.get_random_peer_having_piece(index)

                # If we didn't find any such peer that has the piece, we try again
                if not peer:
                    if self.verbose:
                        print(f"[DOWNLOAD - {index}] No peer found for piece", end="")
                    continue
                else:
                    if self.verbose:
                        print(f"[DOWNLOAD - {index}] Peer found.", end="")
                
                # If I request a block from someone and I haven't received it from them,
                # they're fucking lackadaisical and I don't want to be their friend anymore
                self.pieces_manager.pieces[index].update_block_status()
                
                # Gets an empty block for the piece
                data = self.pieces_manager.pieces[index].get_empty_block()
                if not data:
                    continue

                piece_index, block_offset, block_length = data
                piece_data = message.Request(piece_index, block_offset, block_length).to_bytes()
                # NOTE: requesting a block from a peer
                peer.send_to_peer(piece_data)

            self.display_progression()

            time.sleep(0.1)

        logging.info("File(s) downloaded successfully.")
        self.display_progression()

        self._exit_threads()

    def display_progression(self):
        """
        Displays the current download progress in a human-readable format.
        
        This method:
        1. Calculates total bytes downloaded by counting completed blocks
        2. Only updates display if progress has changed since last check
        3. Shows:
           - Number of connected peers that are unchoked (actively sharing)
           - Percentage of total file downloaded
           - Number of complete pieces vs total pieces
        
        Format:
        "Connected peers: X active peer - Y% completed | Z/N pieces"
        """
        
        # This is the total number of bytes downloaded by us for our specific torrent file
        new_progression = 0

        # forall pieces, forall blocks, if the block is full, add the length of the block to the total progression int
        for i in range(self.pieces_manager.number_of_pieces):
            for j in range(self.pieces_manager.pieces[i].number_of_blocks):
                if self.pieces_manager.pieces[i].blocks[j].state == State.FULL:
                    new_progression += len(self.pieces_manager.pieces[i].blocks[j].data)

        # If the new progression is the same as the last one, we don't update the display
        if new_progression == self.percentage_completed:
            return

        # Gets the number of peers that are unchoked (which is the number of peers that are actively sharing data with us)
        number_of_peers = self.peers_manager.unchoked_peers_count()
        percentage_completed = float((float(new_progression) / self.torrent.total_length) * 100)

        current_log_line = f"Connected peers: {number_of_peers} - {round(percentage_completed, 2)}% completed | {self.pieces_manager.complete_pieces}/{self.pieces_manager.number_of_pieces} pieces"
        if current_log_line != self.last_log_line:
            print(current_log_line)

        self.last_log_line = current_log_line
        self.percentage_completed = new_progression

    def _exit_threads(self):
        """
        Exits the threads
        """
        self.plot_stop_event.set()  # Stop the plot thread
        self.peers_manager.is_active = False
        os._exit(0)


if __name__ == '__main__':
    # Usage: clear && time python main.py <torrent_file>
    
    logging.basicConfig(level=logging.DEBUG)

    # Initializes the run object
    run = Run()
    run.start()
