
from pathlib import Path

# Default Home
DEFAULT_IANTIRTA_HOME = Path("~/.cache/iantirta/").expanduser().resolve()

DEFAULT_VIDEO_DOWNLOAD_DIR = DEFAULT_IANTIRTA_HOME / 'downloaded_video'
DEFAULT_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'cookies.txt'
DEFAULT_NOROTATE_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'norotate_cookies.txt'

# Storage
DEFAULT_UPLOAD_STAGING_DIR = DEFAULT_IANTIRTA_HOME / 'karaoke_staging'
MAX_BYTES_PER_FILE = 5 * 1024 * 1024  # 5mb
