
import hashlib
import hmac
import logging
from abc import abstractmethod
from pathlib import Path

from iantirta.media import constants


class StorageMixin:
    """
    Base class for storage api.

    :param str access_token:
    :param Optional[str | Path] staging_dir:
        if not set, will use ``DEFAULT_IANTIRTA_HOME / 'karaoke_staging'``
    :param Optional[logging.Logger] logger:
    """

    def __init__(
        self,
        *,
        access_token: str,
        staging_dir: str | Path | None = None,
        logger: logging.Logger | None = None
    ):
        self.access_token = access_token

        self.logger = logger or logging.getLogger(__name__)

        if not staging_dir:
            staging_dir = constants.DEFAULT_UPLOAD_STAGING_DIR
        self.staging_dir = Path(staging_dir)

    @abstractmethod
    @property
    def download_endpoint(self) -> str:
        """
        :return: a string uri endpoint that should hold the download url domain endpoint
        :rtype: str
        """
        return ''

    @abstractmethod
    def test_connection(self):
        """
        Test connection for the storage api
        inheritor should override this.
        """
        raise NotImplementedError()

    def _encode_name(self, name: str) -> str:
        """
        Encode any given str into 64 bytes string representation of it.
        with secrets.

        :param str name:
        :return: encoded string representing given name
        :rtype: str
        """
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
        chunk_size: int = constants.MAX_BYTES_PER_FILE,
    ) -> dict:
        """
        Will make chunk any given file
        in a ``chunk_size`` limit.

        Example :
            src: path/filename.txt
            target_path: target/path/
            will convert to: encoded_target_path/encoded_filename

        :param str | Path src_path:
            source path, will use .name for the chunk name.
        :param target_path str:
            subfolder for the storage api to stored the source path within.

        :return: dict metadata represanting the chunk file.
        :rtype: dict[str, Any]
        
        """
        if Path(target_path).suffix:
            raise ValueError('Currently not supported uploading directly to a named path, define subfolder instead.')

        if not chunk_size:
            chunk_size = constants.MAX_BYTES_PER_FILE

        target_path = self._encode_name(target_path.strip('/'))
        dest_dir = self.staging_dir / target_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        src_path = Path(src_path)
        file_bytes = src_path.read_bytes()
        file_name = src_path.stem

        count = 0

        # This will consist
        # encoded_target_path/encoded_chunk_name
        files: list[str] = []

        while file_bytes:
            # get the chunk bytes from file
            chunk_bytes = file_bytes[:chunk_size]
            # reduce the original file bytes
            file_bytes = file_bytes[chunk_size:]
            count += 1

            chunk_name = self._encode_name(f"{file_name}_({count:03d})")
            
            # Sharding method:
            # Since each of git/hf folder can only hold upto 10K files or folder
            # We uses a sharding where we uses 2 prefix of chunk_name as a subfolder.
            # That would leaves us with a 16 x 16 = 256 possible folder, and it could then
            # hold for about 2.56m files inside 1 single artist folder.
            shard_prefix = chunk_name[:2]
            shard_dir = dest_dir / shard_prefix
            shard_dir.mkdir(parents=True, exist_ok=True)

            chunk_file_path = shard_dir / chunk_name
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
