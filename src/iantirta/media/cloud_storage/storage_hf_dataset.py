
import logging
import os
from pathlib import Path

from .base_storage import StorageMixin

from iantirta.media import constants

__all__ = [
    'HFDatasetStorage'
]


ENV_IANTIRTA_HF_TOKEN = 'IANTIRTA_HF_TOKEN'
ENV_IANTIRTA_HF_DATASET_REPO_ID = 'IANTIRTA_HF_DATASET_REPO_ID'


class HFDatasetStorage(StorageMixin):

    def __init__(
        self,
        *,
        repo_id: str | None = None,
        **kwargs,
    ):
        access_token = kwargs.pop('access_token', None)
        if not access_token:
            access_token = os.environ[ENV_IANTIRTA_HF_TOKEN]
        super().__init__(access_token=access_token, **kwargs)

        if not repo_id:
            repo_id = os.environ[ENV_IANTIRTA_HF_DATASET_REPO_ID]
        self.repo_id = repo_id

        from huggingface_hub.hf_api import HfApi
        self._api = HfApi(token=self.access_token)

    @property
    def download_endpoint(self) -> str:
        return 'https://huggingface.co/datasets/' + self.repo_id + '/resolve/main/'

    def test_connection(self):
        return self._api.auth_check(
            repo_id=self.repo_id,
            repo_type='dataset',
            token=self.access_token,
            write=True
        )

    def upload_folder(
        self,
        *,
        folder_path: str | Path | None = None,
        logger: logging.Logger | None = None,
    ):
        if not folder_path:
            folder_path = self.staging_dir
        return self._api.upload_folder(
            folder_path=folder_path,
            path_in_repo='.',
            repo_id=self.repo_id,
            repo_type='dataset',
            token=self.access_token,
            commit_message="Batch upload from worker"
        )

    def upload_file(
        self,
        *,
        src_path: str | Path,
        target_path: str,
        logger: logging.Logger | None = None,
    ) -> list[str]:
        if Path(target_path).suffix:
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
            chunk = file_bytes[:constants.MAX_BYTES_PER_FILE]
            file_bytes = file_bytes[constants.MAX_BYTES_PER_FILE:]
            count += 1

            chunk_name = self._encode_name(f'{file_name}_({count:03d})')

            path_in_repo = f'{target_path}/{chunk_name}'
            self._api.upload_file(
                path_or_fileobj=chunk,
                path_in_repo=path_in_repo,
                repo_id=self.repo_id,
                repo_type='dataset',
                token=self.access_token,
            )
            files.append(path_in_repo)

        assert len(files) == count

        # download url
        return [
            f"https://huggingface.co/datasets/{self.repo_id}/resolve/main/{f}?download=true"
            for f in files
        ]
