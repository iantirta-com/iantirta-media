
import pytest
import math

from pathlib import Path

from iantirta.media import constants
from iantirta.media.cloud_storage.base_storage import StorageMixin


@pytest.fixture
def storage(tmp_path) -> StorageMixin:
    return StorageMixin(
        access_token=None,
        staging_dir=tmp_path / 'staging'
    )


def test_make_chunk_file(storage: StorageMixin, tmp_path: Path):
    file_size_mb = 12
    chunk_size_mb = constants.MAX_BYTES_PER_FILE / (1024 * 1024)
    expected_chunks = math.ceil(file_size_mb / chunk_size_mb)

    src_file = tmp_path / "large-source.bin"
    src_file.write_bytes(b"0" * (file_size_mb * 1024 * 1024))

    target_path = 'artist-test'

    chunk_data = storage.make_chunk_file(
        src_path=src_file,
        target_path=target_path,
    )
    assert chunk_data['suffix'] == '.bin'
    assert chunk_data['count'] == len(chunk_data['files']) == expected_chunks
    count = 0
    for file in chunk_data['files']:
        file = str(file)
        assert '/' in file
        parts = file.split('/')
        assert len(parts) == 2
        count += 1
        assert parts[0] == storage._encode_name(target_path)
        assert parts[-1] == storage._encode_name(
            f'{src_file.stem}_({count:03d})'
        )

    assert src_file.stat().st_size == chunk_data['size']
