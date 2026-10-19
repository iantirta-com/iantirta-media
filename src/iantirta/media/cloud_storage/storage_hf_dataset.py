import hmac, hashlib, os
from pathlib import Path
import logging

from .base_storage import StorageMixin

__all__ = [
    'HFDatasetStorage'
]


MAX_BYTES_PER_FILE = 5 * 1024 * 1024 # 5mb
ENV_IANTIRTA_HF_TOKEN = 'IANTIRTA_HF_TOKEN'
ENV_IANTIRTA_HF_DATASET_REPO_ID = 'IANTIRTA_HF_DATASET_REPO_ID'


class HFDatasetStorage(StorageMixin):

    def __init__(
        self,
        *
        repo_id: str,
        **kwargs,
    ):
        access_token = kwargs.pop('access_token', None)
        if not access_token:
            access_token = os.environ[ENV_IANTIRTA_HF_TOKEN]
        super().__init__(access_token=access_token, **kwargs)

        if not repo_id:
            repo_id = os.environ[ENV_IANTIRTA_HF_DATASET_REPO_ID]
        self.repo_id = repo_id

        from huggingface_hub import upload_file
        self._upload_file = upload_file

    def _encode_name(self, name: str) -> str:
        return hmac.new(
            'karaoke_file'.encode(),
            repr(name).encode(),
            hashlib.sha256,
        ).hexdigest()

    def upload_file(
        self,
        *
        src_path: str | Path,
        target_path: str,
        logger: logging.Logger | None = None,
    ) -> list[str]:
        if Path(target_path).suffix is not None:
            raise ValueError('Currently not supported uploading directly to a named path, define subfolder instead.')

        # we encode target_path
        # as it will also be the same file being replaced
        # if it is the same target_path
        target_path = self._encode_name(target_path.strip('/'))

        file_bytes = Path(src_path).read_bytes()

        file_name = Path(src_path).stem
        count = 0

        files = []
        while file_bytes:
            chunk = file_bytes[MAX_BYTES_PER_FILE:]
            count += 1

            chunk_name = self._encode_name(f'{file_name}_({count})')

            path_in_repo = f'{target_path}/{chunk_name}'
            self._upload_file(
                path_or_fileobj=chunk,
                path_in_repo=path_in_repo,
                repo_id=self.repo_id,
                repo_type='dataset',
                token=self.access_token,
            )
            files.append(path_in_repo)

        assert len(files) == count

        # download url