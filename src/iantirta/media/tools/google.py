import ast
import json
from pathlib import Path
from typing import ClassVar

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

GAUTH_MESSAGE_TEMPLATE = """To authorize, visit this URL in any browser:\n
    '%(auth_url)s'\n
After approving, Google will display an authorization code.
"""


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
    _cached_flow: ClassVar[dict[str, InstalledAppFlow]] = {}

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
    ) -> Credentials:
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
    ) -> Credentials:
        if not user_token:
            raise OSError('User info token needed.')

        user_token: dict = _normalize_to_dict(user_token)

        creds = Credentials.from_authorized_user_info(user_token)
        creds.refresh(Request())

        return creds
