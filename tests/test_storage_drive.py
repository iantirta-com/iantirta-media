import pytest
import sys
import os
import json
from pathlib import Path

from iantirta.media import DriveStorage

pytestmark = pytest.mark.manual


@pytest.fixture
def user_info():
    return json.loads(os.environ['IANTIRTA_DRIVE_USER_TOKEN'])


@pytest.fixture
def user_cred_file_path():
    # change this on different device.
    return Path('~/storage/shared/download/JAZPIPER_AUTOMATION/creds.json').expanduser().resolve()


def test_gdrive_creds_from_user_info(user_info):
    creds = DriveStorage.get_gdrive_credentials(
        user_info
    )
    assert creds is not None


def test_gdrive_creds_request_gdrive_user_token_auth_url(user_cred_file_path):
    auth_url, state = DriveStorage.request_gdrive_user_token_auth_url(
        user_cred_file_path
    )
    assert auth_url is not None
    assert state is not None
    from rich import inspect as i
    i(auth_url)
    i(state, methods=True)
    print(auth_url)


def test_gdrive_creds_from_response_url(user_cred_file_path):
    creds = DriveStorage.get_gdrive_credentials_from_auth_url(
        user_cred_file_path,
        'https://accounts.google.com/signin/oauth/v3/nativeapp?'
        'app=Jazpiper%20Automation&'
        'approvalCode=4%2F1AXlqoi5Vx0ItHH2YRFR-9A4DfgkEkXCRiF7mgfwWiyp10JuuTe8zmm1juxM&'
        'as=S1731928763%3A1792318174402715&'
        'auto=true&client_id=294185921543-1ptm5pr2j3iqv10vlmj0vn16dp8m779q.apps.googleusercontent.com&flowName=GeneralOAuthFlow&hl=en&response=state%3DJcdv9mRwZDgEFBCz7poo1bDHfQwFlh%26iss%3Dhttps%3A%2F%2Faccounts.google.com%26code%3D4%2F1AXlqoi5Vx0ItHH2YRFR-9A4DfgkEkXCRiF7mgfwWiyp10JuuTe8zmm1juxM%26scope%3Dhttps%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive&authuser=3'
    )
    assert creds is not None