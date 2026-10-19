import ast
import json
import logging
import os
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from rich import inspect as i

from iantirta.media import get_context_progressbar

__all__ = [
    'DriveMetadata',
    'DriveStorageOld',
]


_logger = logging.getLogger(__name__)


SCOPES = ['https://www.googleapis.com/auth/drive']


@dataclass
class DriveMetadata:
    download_url: str
    drive_file_id: str
    drive_folder_id: str

    def to_dict(self) -> dict:
        return asdict(self)


class DriveStorageOld:
    _cached_flow = {}

    def __init__(
        self,
        user_token: dict | str | None = None,
        root_folder_id: str | None = None,
        *,
        logger: logging.Logger | None = None
    ):
        if not user_token:
            user_token = os.environ['IANTIRTA_DRIVE_USER_TOKEN']

        if isinstance(user_token, str):
            try:
                user_token = json.loads(user_token)
    
            except json.decoder.JSONDecodeError:
                user_token = ast.literal_eval(user_token)
        
        self.user_token = user_token

        if not root_folder_id:
            root_folder_id = os.environ['IANTIRTA_DRIVE_ROOT_FOLDER_ID']
        self.root_folder_id = root_folder_id

        self.creds: Credentials = Credentials.from_authorized_user_info(
            self.user_token
        )

        if not logger:
            logger = _logger
        self.logger = logger

    def test_connection(self) -> bool:
        try:
            self._make_service().files().get(
                fileId=self.root_folder_id,
                fields='id',  # Requesting only 'id' minimizes network payload
                supportsAllDrives=True
            ).execute()
            return True
        except Exception:
            # Returns False if the ID does not exist, or if credentials fail
            return False

    @staticmethod
    def get_gdrive_credentials(user_info: dict | None = None):
        if not user_info:
            raise OSError('User info token needed.')

        if isinstance(user_info, str):
            user_info = json.loads(user_info)

        creds = Credentials.from_authorized_user_info(user_info)
        creds.refresh(Request())

        return creds

    @staticmethod
    def _normalize_client_config(client_config):
        if isinstance(client_config, (str, Path)):
            if Path(client_config).is_file():
                client_config = Path(client_config).read_text('utf-8')

            client_config = json.loads(client_config)

        return client_config

    @staticmethod
    def get_gdrive_credentials_from_auth_url(
        client_config,
        key: str,
        **kwargs,
    ):
        client_config = DriveStorage._normalize_client_config(client_config)

        flow = DriveStorage._cached_flow.pop(key)
        if not flow:
            raise OSError()

        flow.fetch_token(**kwargs)

        return flow.credentials

    @staticmethod
    def request_gdrive_user_token_auth_url(
        client_config,
        key: str,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob:auto',
        **kwargs
    ) -> tuple[str, dict]:
        client_config = DriveStorage._normalize_client_config(client_config)

        flow = InstalledAppFlow.from_client_config(
            client_config,
            SCOPES,
            redirect_uri=redirect_uri,
        )
        DriveStorage._cached_flow[key] = flow

        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes='true',
            # login_hint='tirtamoto@gmail.com',
            **kwargs,
        )
        return auth_url, state

    def _make_service(self):
        return build('drive', 'v3', credentials=self.creds)

    def _get_or_create_folder(
        self,
        service,
        folder_name: str,
        parent_id: str | None = None,
    ) -> str:
        """ Will return folder_id needed to put the file
        """
        query = (
            f"name='{folder_name}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"

        response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        if files := response.get('files', []):
            return files[0]['id']

        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
        
        folder = service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return folder.get('id')

    def search_file(
        self,
        name: str,
        *,
        subfolder_id: str | None = None,
        service=None,
        logger: logging.Logger | None = None,
    ) -> str:
        if not service:
            service = self._make_service()

        query = (
            f'name="{name}" '
            'and trashed=false'
        )
        
        if subfolder_id:
            query += f" and '{subfolder_id}' in parents"

        response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        if files := response.get('files', []):
            return files[0]['id']

        return None
        
    def upload(
        self,
        src_path: str | Path,
        *,
        subfolder: str | None = None,
        logger: logging.Logger | None = None,
        replace: bool = True,
    ):
        src_path = Path(src_path)

        service = self._make_service()

        if subfolder is not None:
            subfolder_id = self._get_or_create_folder(
                service, str(subfolder), self.root_folder_id
            )

        else:
            subfolder_id = self.root_folder_id

        drive_file_id = None
        download_url = None
        if drive_file_id := self.search_file(
            src_path.name, subfolder_id=subfolder_id,
            service=service, logger=logger
        ):
            (logger or self.logger).debug(f'Found current drive file id: {drive_file_id}')

        media_body = MediaFileUpload(
            str(src_path),
            # mimetype='video/x-matroska', # MKV
            resumable=True,
            chunksize=5 * 1024 * 1024,
        )
        if replace and drive_file_id is not None:
            request = service.files().update(
                fileId=drive_file_id,
                media_body=media_body,
                fields='id, webViewLink, webContentLink',
                supportsAllDrives=True,
            )
        else:
            request = service.files().create(
                body={
                    'name': src_path.name,
                    'parents': [subfolder_id]
                },
                media_body=media_body,
                fields='id, webViewLink, webContentLink',
                supportsAllDrives=True,
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
        
        drive_file_id = response.get('id')
        download_url = response.get('webContentLink')

        service.permissions().create(
            fileId=drive_file_id,
            body={
                'type': 'anyone',
                'role': 'reader'
            },
            fields='id'
        ).execute()

        (logger or self.logger).info(
            f"Successfully uploaded {src_path!s} to Drive. "
            f"File ID: {drive_file_id}"
        )

        return DriveMetadata(
            download_url=download_url,
            drive_file_id=drive_file_id,
            drive_folder_id=subfolder_id
        )


if __name__ == '__main__':
    from iantirta.telemetry import netsvc
    _logger = logging.getLogger('iantirta.drive')
    _logger.setLevel(logging.DEBUG)
    netsvc.setup_logger('', default_level=logging.DEBUG)
    _logger.debug('test')
    import os
    from pprint import pprint
    pprint(os.environ.get('IANTIRTA_DRIVE_ROOT_FOLDER_ID'), None)
    api = DriveStorage(None, None)
    from rich import inspect
    service = build('drive', 'v3', credentials=api.creds)
    query = (
        "mimeType='application/vnd.google-apps.folder'"
    )
    """Available is:

        get_media(**kwargs)
        get(**kwargs)
        create(**kwargs)
        copy(**kwargs)
        list(**kwargs)
        update(**kwargs)
    """
    #inspect(service.files(), all=True)
    # inspect(service.files().list(
    #     #q=query,
    #     spaces='drive',
    #     #fields='files(id, name)',
    #     supportsAllDrives=True,
    #     includeItemsFromAllDrives=True
    # ).execute())
    inspect(api.search_file(
        '0934_Feast - Maju Official Lyric Video (Karaoke).mkv',
        subfolder_id=None,
    ))
    
    inspect(api.upload(
        Path('~/testxet.incomplete').expanduser().resolve(),
        subfolder='test_folder'
    ))
    
    # folder = 'profkang'
    #drive_file_id='1PFzDq4NptOhozkXNaI7cEuXyjPNlGGgi',