
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class DriveStorage:
    def upload(
        self,
        src_path: str | Path,
        subfolder: str | Path, 
    ):
        src_path = Path(src_path)

        service = build('drive', 'v3', credentials=self.creds)

        if subfolder is not None:
            pass
        else:
            subfolder_id = self.root_folder_id

        request = service.files().create(
            body={
                'name': src_path.name,
                'parents': [subfolder_id]
            },
            media_body=MediaFileUpload(
                str(src_path),
                # mimetype='video/x-matroska', # MKV
                resumable=True
            ),
            fields='id, webViewLink, webContentLink',
            supportsAllDrives=True,
        )
