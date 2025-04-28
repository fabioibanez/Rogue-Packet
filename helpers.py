# Author: Shounak Ray

import pprint
from typing import Dict

def print_torrent(data: Dict) -> None:
    """Print torrent data with pieces count instead of binary content."""
    d = data.copy()
    if 'info' in d and isinstance(d['info'], dict):
        if 'pieces' in d['info']:
            d['info'] = d['info'].copy()
            d['info']['pieces'] = f"<{len(d['info']['pieces'])} bytes>"
    
    print("\033[1;32m")  # Bold green text
    print("TORRENT FILE CONTENT:")
    pprint.pprint(d)
    print("\033[0m")  # Reset text formatting