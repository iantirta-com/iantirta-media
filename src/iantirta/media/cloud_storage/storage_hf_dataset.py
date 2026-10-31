
import logging
import os
from pathlib import Path

from iantirta.media import constants

from .base_storage import StorageMixin

__all__ = [
    'HFDatasetStorage'
]


ENV_IANTIRTA_HF_TOKEN = 'IANTIRTA_HF_TOKEN'
ENV_IANTIRTA_HF_DATASET_REPO_ID = 'IANTIRTA_HF_DATASET_REPO_ID'


class HFDatasetStorage(StorageMixin):
    """
    Huggingface dataset storage api.

    :param Optional[str] repo_id:
        required for location.
    """
    def __init__(
        self,
        *,
        repo_id: str | None = None,
        **kwargs,
    ):
        # Default access token on env.
        if not (access_token := kwargs.pop('access_token', None)):
            access_token = os.getenv(constants.DEFAULT_IANTIRTA_HF_TOKEN_ENV)
        super().__init__(access_token=access_token, **kwargs)

        if not repo_id:
            repo_id = os.getenv(constants.DEFAULT_IANTIRTA_HF_DATASET_REPO_ID_ENV)
        self.repo_id = repo_id

    # -----------------------
    # Specific provider properties
    # -----------------------

    @property
    def client(self):
        if not self._client:
            from huggingface_hub.hf_api import HfApi
            self._client = HfApi(token=self.access_token)
        return self._client

    # Override

    @property
    def download_endpoint(self) -> str:
        return 'https://huggingface.co/datasets/' + self.repo_id + '/resolve/main/'

    def test_connection(self):
        return self.client.auth_check(
            repo_id=self.repo_id,
            repo_type='dataset',
            token=self.access_token,
            write=True
        )

    # -----------------------
    # Storage method
    # -----------------------

    def upload_folder(
        self,
        *,
        dir_path: str | Path | None = None,
    ):
        """
        Will upload folder into the storage.
        
        :param Optional[str | Path] dir_path:
            the source dir_path that will be uploaded.
            if not set will use ``self.staging_dir``
        """
        if not dir_path:
            dir_path = self.staging_dir

        return self.client.upload_folder(
            folder_path=dir_path,
            path_in_repo='.',
            repo_id=self.repo_id,
            repo_type='dataset',
            token=self.access_token,
            commit_message="Batch upload from worker"
        )
