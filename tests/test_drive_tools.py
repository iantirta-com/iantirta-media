import os
from pathlib import Path

import pytest

from iantirta.media import DriveStorage
from iantirta.media.cloud_storage.storage_gdrive import SCOPES
from iantirta.media.tools.google import GoogleApi

pytestmark = pytest.mark.manual


@pytest.fixture
def client_config_path():
    return Path("~/.cache/iantirta/drive/creds.json").expanduser().resolve()


@pytest.fixture
def user_token():
    return os.environ['IANTIRTA_DRIVE_USER_TOKEN']


@pytest.fixture
def drive_api():
    return DriveStorage()


def test_drive_tools_all(drive_api):
    from rich import inspect as i

    i(drive_api.service, all=True)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(['-v', '-s', __file__]))
