
import hashlib
import hmac
import logging
from abc import abstractmethod
from pathlib import Path

from iantirta.media import constants

_logger = logging.getLogger(__name__)


class StorageMixin:

    def __init__(
        self,
        *,
        access_token: str,
        staging_dir: str | Path | None = None,
        logger: logging.Logger | None = None
    ):
        self.access_token = access_token

        self.logger = logger or _logger

        if not staging_dir:
            staging_dir = constants.DEFAULT_UPLOAD_STAGING_DIR
        self.staging_dir = Path(staging_dir)

    @property
    def download_endpoint(self) -> str:
        return ''

    @abstractmethod
    def test_connection(self):
        raise NotImplementedError()

    @abstractmethod
    def upload_file(
        self,
        *
        src_path: str | Path,
        target_path: str | Path,
        logger: logging.Logger | None = None
    ) -> list[str]:
        raise NotImplementedError()

    def _encode_name(self, name: str) -> str:
        return hmac.new(
            b'karaoke_file',
            repr(name).encode(),
            hashlib.sha256,
        ).hexdigest()

    def make_chunk_file(
        self,
        *,
        src_path: str | Path,
        target_path: str,
    ) -> dict:
        """Will break any given file into separated chunk.

        Example:
            src: path/filename.txt
            target_path: target/path/
            will convert to: encoded_target_path/encoded_filename
        """
        if Path(target_path).suffix:
            raise ValueError('Currently not supported uploading directly to a named path, define subfolder instead.')

        # we encode target_path
        # as it will also be the same file being replaced
        # if it is the same target_path
        target_path = self._encode_name(target_path.strip('/'))
        dest_dir = self.staging_dir / target_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        src_path = Path(src_path)
        file_bytes = src_path.read_bytes()
        file_name = src_path.stem

        count = 0

        # This will consist
        # encoded_target_path/encoded_chunk_name
        files = []

        while file_bytes:
            # get the chunk bytes from file
            chunk_bytes = file_bytes[:constants.MAX_BYTES_PER_FILE]
            # reduce the original file bytes
            file_bytes = file_bytes[constants.MAX_BYTES_PER_FILE:]
            count += 1

            chunk_name = self._encode_name(f"{file_name}_({count:03d})")
            chunk_file_path = dest_dir / chunk_name
            chunk_file_path.write_bytes(chunk_bytes)

            files.append(
                self.download_endpoint + chunk_file_path.relative_to(self.staging_dir).as_posix()
            )

        return {
            'suffix': src_path.suffix,
            'count': count,
            'files': files,
            'size': src_path.stat().st_size
        }
