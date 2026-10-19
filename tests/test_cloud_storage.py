import pytest

from iantirta.media import DriveStorage, HFDatasetStorage
from rich import inspect

pytestmark = pytest.mark.manual


@pytest.fixture
def drive_api():
    return DriveStorage()

@pytest.fixture
def hf_api():
    return HFDatasetStorage()

@pytest.fixture
def apis(drive_api, hf_api):
    return [drive_api, hf_api]


def test_construct_instance_default_using_env(apis):
    for api in apis:
        assert api is not None
        assert api.access_token is not None
        assert api.logger is not None
        

def test_api_test_connections(apis):
    for api in apis:
        inspect(api.test_connection())
        
