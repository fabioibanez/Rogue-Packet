
# PyTorrent

# Helpful Commands
**If you want to ping a ip + port number:**
`nc -zv IP_ADDRESS_HERE PORT_NUMBER`

**Ping an ip:**
`ping IP_ADDRESS_HERE`

**View torrent pretty printed**
```bash
brew install transmission
transmission-show PATH_TO_TORRENT
```

# Original Code

PyTorrent is a CLI tool that downloads files from the **BitTorrent** network.

I wanted to make my own functional and straightforward program to learn how does BitTorrent protocol work and improve my python skills.

It is almost written from scratch with python 3.7, only the pubsub library was used to create events when a new peer is connected, or when data is received from a peer.
You first need to wait for the program to connect to some peers first, then it starts downloading.

This tool needs a lot of improvements, but it does its job, you can :
-	Read a torrent file
-	Scrape udp or http trackers
-	Connect to peers
-	Ask them for the blocks you want
-	Save a block in RAM, and when a piece is completed and checked, write the data into your hard drive
-	Deal with the one-file or multi-files torrents
-	Leech or Seed to other peers

But you can’t :
-	Download more than one torrent at a time
-	Benefit of a good algorithm to ask your peers for blocks (code of rarest piece algo is implemented but not used yet)
-	Pause and resume download

Don't hesitate to ask me questions if you need help, or send me a pull request for new features or improvements.

### Installation
You can run the following command to install the dependencies using pip

`pip install -r requirements.txt`

:boom: Because it's using the "select" function, this code will not be able to run on Windows: [python-select-on-windows](https://stackoverflow.com/a/22254123/3170071)

### Running the program

Simply run:
`python main.py /path/to/your/file.torrent`

The files will be downloaded in the same path as your main.py script.

### Sources :

I wouldn't have gone that far without the help of
[Lita](https://github.com/lita/bittorrent "Lita"), 
[Kristen Widman's](http://www.kristenwidman.com/blog/how-to-write-a-bittorrent-client-part-1 "Kristen Widman's blog") & the
[Bittorrent Unofficial Spec](https://wiki.theory.org/BitTorrentSpecification "Bittorrent Unofficial Spec"), so thank you.


## TODO
- [Done-Shounak] Optimistic Unchoking, random optimistic unchoking 
- [Done-Yousef] Send peers the `HAVE` message + Testing (testing left)
- [Done-Fabio] Non-optimistic unchoking, auction-strategy which is built into BitTorrent
- [Done-Jacob] Rarest Piece Selection, what is my current state of the world
- [] Figure out a testbed (that is the only way to test have messages)

### Implementation Notes

#### Rarest First Strategy

The existing code bulk-sends block requests to interesting peers in a while loop. It guards against overloading the network by not sending more than one request to a peer in a 200ms window, however, this can still result in many more than the typical 10-15 outstanding requests that you would see in a production BitTorrent client.

We can implement rarest-first piece selection by changing the iteration order for requests: rather than iterate from front-to-back (the behaviour of the existing code) we iterate over pieces in order of rarest-first. This order can be derived by looking at the sum of all connected peers bifields.

To fix the outstanding requests issue, we can keep track of how many outstanding requests have been sent to each peer. When sending a new request, if the sum of all requests across all peers is greater than a threshold value (e.g. 15), we don't send the request. This behaviour can simply be overlayed over the piece request loop.

