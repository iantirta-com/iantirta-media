

import os


class HFDataset:
    def __init__(
        self,
        repo_id: str | None = None,
        token: str | None = None,
        repo_type: str | None = None,
    ):
        if not repo_id:
            repo_id = os.environ["IANTIRTA_HF_DATASET_REPO_ID"]
        self.repo_id = repo_id

        if not token:
            token = os.environ["IANTIRTA_HF_TOKEN"]
        self.token = token

        if not repo_type:
            repo_type = 'dataset'
        self.repo_type = repo_type

        from huggingface_hub import upload_file
        self._upload_file = upload_file

    def upload_file(self, **kwargs):
        return self._upload_file(repo_id=self.repo_id, token=self.token, repo_type=self.repo_type, **kwargs)


if __name__ == "__main__":
    from pathlib import Path
    api = HFDataset(
        repo_id="yancovenant/karaoke-archive",
    )
    api.upload_file(
        path_or_fileobj=str(Path("D:/IANTIRTACOM/dataset/vocals.wav").expanduser().resolve()),
        path_in_repo='test/upload/file'
    )
