import os
from pathlib import Path

import googleapiclient.errors
import pytest
from google.oauth2.credentials import Credentials
from rich import inspect

from iantirta.media import DriveStorage
from iantirta.media.cloud_storage.storage_gdrive import ENV_DRIVE_USER_TOKEN

pytestmark = pytest.mark.manual


@pytest.fixture
def drive_api():
    return DriveStorage()


def test_api_drive_connection(drive_api: DriveStorage):
    drive_api.test_connection()


def test_api_drive_connection_root_folder_not_exists(drive_api: DriveStorage):
    drive_api.root_folder_id = '50'

    with pytest.raises(googleapiclient.errors.HttpError, match='File not found: 50.'):
        drive_api.test_connection()


def test_api_drive_access_token_not_valid():
    with pytest.raises(ValueError, match="Authorized user info was not in the expected format"):
        DriveStorage(
            access_token={'1': "hello"}
        )


def test_api_drive_upload_file(drive_api: DriveStorage, tmp_path):
    file: Path = tmp_path / 'test-upload.txt'
    file.write_text("THIS IS TEST UPLOAD FILE")

    out = drive_api.upload_file(src_path=file, target_path='test-upload-folder')
    assert len(out) == 1


def test_api_drive_upload_file_nested_target_path(drive_api: DriveStorage, tmp_path):
    file: Path = tmp_path / 'test-upload.txt'
    file.write_text("THIS IS TEST UPLOAD FILE")

    out = drive_api.upload_file(src_path=file, target_path='test-upload-folder/nested-test-upload')
    assert len(out) == 1


def test_api_drive_upload_file_will_use_the_same_encode(drive_api: DriveStorage, tmp_path):
    file: Path = tmp_path / 'test-upload-2.txt'
    file.write_text("THIS IS TEST 2 UPLOAD FILE WILL USE THE SAME FOLDER")

    out = drive_api.upload_file(src_path=file, target_path='test-upload-folder')
    assert len(out) == 1

    out = drive_api.upload_file(src_path=file, target_path='test-upload-folder/nested-test-upload')
    assert len(out) == 1


def test_api_drive_get_credentials(drive_api: DriveStorage):
    user_token = os.environ[ENV_DRIVE_USER_TOKEN]
    creds = drive_api.get_credentials(user_token=user_token)
    assert creds is not None
    assert isinstance(creds, Credentials)


def test_api_drive_setup_user_token(drive_api: DriveStorage):
    client_config = Path("~/.cache/iantirta/drive/creds.json").expanduser().resolve()
    assert client_config.is_file()
    auth_url, _ = drive_api.setup_user_token(client_config=client_config, key="test")
    assert auth_url is not None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(['-v', '-s', __file__]))
