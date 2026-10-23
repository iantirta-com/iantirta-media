import ast
import base64
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow


# Scope missmatch
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'


def _normalize_to_dict(variable: str | Path | dict) -> dict:
    def _parse(var: str):
        try:
            return json.loads(var)
        except json.decoder.JSONDecodeError:
            return ast.literal_eval(var)

    if isinstance(variable, (str, Path)):
        # Normalize first
        try:
            if Path(variable).is_file():
                variable = Path(variable).read_text('utf-8')
        except Exception:
            pass

        variable = _parse(variable)

    return variable


class GoogleApi:
    _cached_flow: ClassVar[dict[str, 'InstalledAppFlow']] = {}

    @staticmethod
    def get_auth_url(
        *,
        key: str,
        client_config: str | Path | dict,
        scopes: list[str],
        redirect_uri='urn:ietf:wg:oauth:2.0:oob:auto',  # OOB is deprecated.
        **kwargs,
    ) -> tuple[str, str]:
        """Get auth url and state for google auth.
        Returns:
            Tuple[str, str]: `auth_url` and `state`
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_config = _normalize_to_dict(client_config)

        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes,
            redirect_uri=redirect_uri,
        )
        GoogleApi._cached_flow[key] = flow

        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes='true',
            prompt='consent',
            token_usage="remote",
            **kwargs,
        )
        return auth_url, state

    @staticmethod
    def creds_from_flow_token(
        *,
        key: str,
        **kwargs,
    ) -> 'Credentials':
        """Return credentials from fetch token."""
        flow = GoogleApi._cached_flow.pop(key)
        if not flow:
            raise OSError(
                "You need to call `get_auth_url` "
                "first before able to get credentials from flow"
            )

        flow.fetch_token(**kwargs)
        return flow.credentials

    @staticmethod
    def creds_from_user_token(
        *,
        user_token: Path | str | dict,
    ) -> 'Credentials':
        if not user_token:
            raise OSError('User info token needed.')

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        user_token: dict = _normalize_to_dict(user_token)

        creds = Credentials.from_authorized_user_info(user_token)
        creds.refresh(Request())

        return creds

    @staticmethod
    def make_state(data: dict) -> str:
        """Serializes a dictionary to a URL-safe Base64 string."""
        json_str = json.dumps(data)
        # Encode to urlsafe base64
        b64_encoded = base64.urlsafe_b64encode(json_str.encode('utf-8'))
        # Decode back to string and strip padding for clean URLs
        return b64_encoded.decode('utf-8').rstrip('=')

    @staticmethod
    def parse_state(state: str) -> dict:
        """Deserializes a URL-safe Base64 string back to a dictionary."""
        # Calculate needed padding and append it
        padding_needed = '=' * (-len(state) % 4)
        padded_state = state + padding_needed
        
        try:
            json_bytes = base64.urlsafe_b64decode(padded_state.encode('utf-8'))
            return json.loads(json_bytes.decode('utf-8'))
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to parse OAuth state parameter: {e}")

if __name__ == '__main__':
    from rich import inspect as i
    state = GoogleApi.make_state({
        'key1': 'value1',
        'key2': 'value2',
    })
    state2 = GoogleApi.parse_state(state)
    i(state)
    i(state2)