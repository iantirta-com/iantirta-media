from __future__ import annotations

import base64
from urllib.parse import quote
from pathlib import Path
import requests
from typing import TYPE_CHECKING
import re

from iantirta.media.worker.colab_utils.utils import get_status_code

if TYPE_CHECKING:
    from .state import SessionState, State


class ContentsClient:
    def _request(
        self,
        method: str,
        path: str,
        params: dict = None,
        json_data: dict = None,
        *,
        s: SessionState
    ):
        base_url = s.url.rstrip("/")
        token = s.token
        # Quote the path, but don't encode slashes so directory paths stay intact
        quoted_path = quote(path.strip("/"), safe="/")
        url = f"{base_url}/api/contents/{quoted_path}"

        req_params = {"authuser": "0", "colab-runtime-proxy-token": token}
        if params:
            req_params.update(params)

        response = requests.request(method, url, params=req_params, json=json_data)

        if get_status_code(response) == 404:
            raise FileNotFoundError(f"File or directory not found: {path}")

        response.raise_for_status()

        # DELETE doesn't return JSON
        if method == "DELETE":
            return None

        return response.json()

    def list_dir(self, s: SessionState, path: str):
        return self._request("GET", path, s=s)

    def read_range(
        self,
        s: SessionState,
        remote_path: str,
        offset: int,
    ) -> bytes:
        path = quote(remote_path.lstrip("/"), safe="/")
        url = f"{s.url.rstrip('/')}/files/{path}"

        response = requests.get(
            url,
            params={"authuser": "0", "colab-runtime-proxy-token": s.token},
            headers={"Range": f"bytes={offset}-"},
            #stream=True,
            #timeout=(10, 30),
        )

        status_code = get_status_code(response)
        if status_code == 404:
            raise FileNotFoundError(f"Remote File not found: {remote_path}")

         # The requested offset is at or beyond EOF.
        if status_code == 416:
            match = re.fullmatch(
                r"bytes \*/(\d+)",
                response.headers.get("Content-Range", ""),
            )
            if match:
                return b"", int(match.group(1))

        response.raise_for_status()

        if status_code != 206:
            raise RuntimeError(
                "Remote endpoint did not honor Range requests "
                f"(HTTP {status_code})"
            )

        match = re.fullmatch(
            r"bytes (\d+)-(\d+)/(\d+|\*)",
            response.headers.get("Content-Range", ""),
        )
        if not match:
            raise RuntimeError("Missing or invalid Content-Range header")
    
        start, end = int(match.group(1)), int(match.group(2))
        total = match.group(3)
    
        if start != offset:
            raise RuntimeError(
                f"Unexpected range start: requested {offset}, received {start}"
            )
    
        content = response.content
    
        if len(content) != end - start + 1:
            raise RuntimeError("Response length does not match Content-Range")
    
        return content, int(total) if total != "*" else end + 1
    
    def read_bytes(self, s: SessionState, remote_path: str) -> bytes:
        data = self._request("GET", remote_path, params={"content": "1"}, s=s)

        if data.get("type") == "directory":
            raise IsADirectoryError(f"Cannot read a directory: {remote_path}")

        content = data.get("content", "")

        if data.get("format") == "base64":
            return base64.b64decode(content)

        return str(content).encode("utf-8")

    def download(self, s: SessionState, remote_path: str, local_path: str):
        content = self.read_bytes(s, remote_path)
        Path(local_path).write_bytes(content)


if __name__ == '__main__':
    from pprint import pprint
    from iantirta.media.worker.colab_utils.state import state
    s = state.get_session('Unknown - 6f357c')
    c = ContentsClient()
    pprint(c.read_range(s, 'content/job.py', 5772))