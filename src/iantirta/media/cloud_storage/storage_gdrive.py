import json, os
from pathlib import Path
import logging
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from contextlib import ExitStack

from iantirta.media import get_context_progressbar
from .base_storage import StorageMixin

__all__ = [
    'DriveStorage'
]


ENV_DRIVE_USER_TOKEN = 'IANTIRTA_DRIVE_USER_TOKEN'
ENV_IANTIRTA_DRIVE_ROOT_FOLDER_ID = 'IANTIRTA_DRIVE_ROOT_FOLDER_ID'

class DriveStorage(StorageMixin):
    def __init__(
        self,
        root_folder_id: str | None = None,
        **kwargs,
    ):
        access_token = kwargs.pop('access_token', None)
        if not access_token:
            access_token = json.loads(os.environ[ENV_DRIVE_USER_TOKEN])
        super().__init__(access_token=access_token, **kwargs)

        self.creds: Credentials = Credentials.from_authorized_user_info(
            self.access_token
        )

        if not root_folder_id:
            root_folder_id = os.environ[ENV_IANTIRTA_DRIVE_ROOT_FOLDER_ID]
        self.root_folder_id = root_folder_id

        self.service = build('drive', 'v3', credentials=self.creds)

    # Auth Method

    # Authenticated Method
    def test_connection(self):
        return self.service.files().get(
            fileId=self.root_folder_id,
            fields='id',  # Requesting only 'id' minimizes network payload
            supportsAllDrives=True
        ).execute()

    def _get_folder(self, folder_name: str) -> str | None:
        query = (
            f"name='{folder_name}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false "
            f"and '{self.root_folder_id}' in parents"
        )

        response = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        if files := response.get('files', []):
            return files[0]['id']

        return None

    def _create_folder(self, folder_name: str) -> str:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [self.root_folder_id]
        }

        folder = self.service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return folder.get('id')

    def _get_or_create_folder(self, folder_name: str) -> str:
        if folder_id := self._get_folder(folder_name):
            return folder_id
        return self._create_folder(folder_name)
    
    def upload_file(
        self,
        *
        src_path: str | Path,
        target_path: str,
        logger: logging.Logger | None = None,
        replace: bool = True,
    ) -> list[str]:
        if Path(target_path).suffix is not None:
            raise ValueError('Currently not supported uploading directly to a named path, define subfolder instead.')

        subfolder = None
        target_path = target_path.strip('/')
        if '/' in target_path:
            subfolder, target_path = target_path.rsplit('/', 1)

        if subfolder is not None:
            subfolder_id = self._get_or_create_folder(subfolder)
        else:
            subfolder_id = self.root_folder_id

        media_body = MediaFileUpload(
            str(src_path),
            # mimetype='video/x-matroska', # MKV
            resumable=True,
            chunksize=5 * 1024 * 1024,
        )
        upload_params = {
            'media_body': media_body,
            'fields': 'id, webViewLink, webContentLink',
            'supportsAllDrives': True,
        }

        if (
            replace
            and (file_id := self.search_file(
                    Path(src_path).name,
                    subfolder_id=subfolder_id
                ))
        ):
            (logger or self.logger).debug(f'Found current file id: {file_id}')
            request = self.service.files().update(
                fileId=file_id,
                **upload_params,
            )
        else:
            (logger or self.logger).debug('Creating new file on drive.')
            request = self.service.files().create(
                body={
                    'name': Path(src_path).name,
                    'parents': [subfolder_id]
                },
                **upload_params
            )

        with ExitStack() as stack:
            displayed_filename = f"Upload progress {src_path.name}"

            if len(displayed_filename) > 40:
                displayed_filename = f"(...){displayed_filename[-40:]}"

            pbar_cm = get_context_progressbar(
                desc=displayed_filename,
                log_level=(logger or self.logger).getEffectiveLevel(),
                total=media_body.size(),
            )
            pbar = stack.enter_context(pbar_cm)
            response = None
            uploaded = 0
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pbar.update(status.resumable_progress - uploaded)
                    uploaded = status.resumable_progress
            pbar.update(media_body.size() - uploaded)

        file_id = response.get('id')
        download_url = response.get('webContentLink')

        self.service.permissions().create(
            fileId=file_id,
            body={
                'type': 'anyone',
                'role': 'reader'
            },
            fields='id'
        ).execute()

        (logger or self.logger).info(
            f"Successfully uploaded {src_path!s} to Drive. "
            f"File ID: {file_id}"
        )

        return [download_url]

    def search_file(
        self,
        file_name: str,
        *,
        subfolder_id: str | None = None,
        logger: logging.Logger | None = None,
    ) -> str | None:
        if not subfolder_id:
            subfolder_id = self.root_folder_id

        query = (
            f'name="{file_name}" '
            'and trashed=false '
            f"and '{subfolder_id}' in parents"
        )

        response = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        if files := response.get('files', []):
            return files[0]['id']

        return None
