
from pathlib import Path

# Default Home
DEFAULT_IANTIRTA_HOME = Path("~/.cache/iantirta/").expanduser().resolve()

DEFAULT_VIDEO_DOWNLOAD_DIR = DEFAULT_IANTIRTA_HOME / 'downloaded_video'
DEFAULT_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'cookies.txt'
DEFAULT_NOROTATE_COOKIEPATH = DEFAULT_IANTIRTA_HOME / 'norotate_cookies.txt'

# Storage
DEFAULT_UPLOAD_STAGING_DIR = DEFAULT_IANTIRTA_HOME / 'karaoke_staging'
MAX_BYTES_PER_FILE = 5 * 1024 * 1024  # 5mb

# Worker
DEFAULT_WORKER_PATH = DEFAULT_IANTIRTA_HOME / 'worker'
DEFAULT_COLAB_USER_TOKEN_PATH = DEFAULT_WORKER_PATH / 'user_token.json'
DEFAULT_COLAB_STATE_CONFIG_PATH = DEFAULT_WORKER_PATH / 'colab-sessions.json'
DEFAULT_COLAB_HISTORY_LOG_DIR = DEFAULT_WORKER_PATH / 'colab-history'

DEFAULT_COLAB_USER_TOKEN_ENV = 'IANTIRTA_COLAB_USER_TOKEN'

# Standard Scopes for Colab and Drive (Public Auth)
DEFAULT_COLAB_PUBLIC_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/colaboratory",
    "https://www.googleapis.com/auth/drive.file",
]
