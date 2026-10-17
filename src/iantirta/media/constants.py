
from pathlib import Path

# Default Home
DEFAULT_IANTIRTA_HOME = Path("~/.cache/iantirta/").expanduser().resolve()

DEFAULT_VIDEO_DOWNLOAD_DIR = DEFAULT_IANTIRTA_HOME / 'downloaded_video'
DEFAULT_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'cookies.txt'
DEFAULT_NOROTATE_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'norotate_cookies.txt'
