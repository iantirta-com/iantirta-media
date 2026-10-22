
import math
from pathlib import Path

import pytest

pytestmark = pytest.mark.manual

from iantirta.media import HFDatasetStorage


@pytest.fixture
def hf_api():
    return HFDatasetStorage()


def test_api_hfdataset_connection(hf_api: HFDatasetStorage):
    hf_api.test_connection()


def test_api_hfdataset_repo_not_exists(hf_api: HFDatasetStorage):
    import huggingface_hub.errors
    with pytest.raises(huggingface_hub.errors.RepositoryNotFoundError):
        hf_api.repo_id = 'yancovenant/test-connection'
        hf_api.test_connection()


def test_api_hfdataset_access_token_invalid(hf_api: HFDatasetStorage):
    import huggingface_hub.errors
    with pytest.raises(huggingface_hub.errors.RepositoryNotFoundError):
        hf_api.access_token = '12345'
        hf_api.test_connection()


def test_api_hfdataset_upload_file(hf_api: HFDatasetStorage, tmp_path):
    file: Path = tmp_path / 'test-upload.txt'
    file.write_text("THIS IS TEST UPLOAD FILE")

    out = hf_api.upload_file(src_path=file, target_path='test-upload-folder')
    assert len(out) == 1


def test_api_hfdataset_upload_chunked_file(hf_api: HFDatasetStorage, tmp_path: Path):
    file_size_mb = 12
    chunk_size_mb = 5
    expected_chunks = math.ceil(file_size_mb / chunk_size_mb)  # Should be 3
    
    test_file = tmp_path / "large-test-upload.bin"
    # 12 MB dummy binary data
    test_file.write_bytes(b"0" * (file_size_mb * 1024 * 1024))

    urls = hf_api.upload_file(src_path=test_file, target_path="test-upload-folder")

    assert len(urls) == expected_chunks, f"Expected {expected_chunks} chunks, got {len(urls)}"


def test_api_hfdataset_upload_chunked_file_will_replace(hf_api: HFDatasetStorage, tmp_path: Path):
    file_size_mb = 9
    chunk_size_mb = 5
    expected_chunks = math.ceil(file_size_mb / chunk_size_mb)  # Should be 2

    test_file = tmp_path / "large-test-upload.bin"
    test_file.write_bytes(b"1" * (file_size_mb * 1024 * 1024))

    urls = hf_api.upload_file(src_path=test_file, target_path="test-upload-folder")

    assert len(urls) == expected_chunks, f"Expected {expected_chunks} chunks, got {len(urls)}"


def test_api_hfdataset_upload_folder(hf_api: HFDatasetStorage, tmp_path: Path):
    test_dir = tmp_path / "batch_upload_test"
    test_dir.mkdir()
    (test_dir / "file1.txt").write_text("chunk 1")
    (test_dir / "file2.txt").write_text("chunk 2")

    hf_api.upload_folder(
        folder_path=test_dir,
    )

def test_api_hfdataset_upload_folder_nested(hf_api: HFDatasetStorage, tmp_path: Path):
    test_dir = tmp_path / "batch_upload_test"
    test_dir.mkdir()
    test_repo_dir = test_dir / 'batch_upload_test_in_repo'
    test_repo_dir.mkdir()
    (test_repo_dir / "file1.txt").write_text("chunk 1")
    (test_repo_dir / "file2.txt").write_text("chunk 2")

    hf_api.upload_folder(
        folder_path=test_dir,
    )



if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(['-v', '-s', __file__]))
