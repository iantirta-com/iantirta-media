import hashlib
import os
import urllib.error
import json
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from iantirta.media.tools.google import GoogleApi
from iantirta.media import constants


from google.auth.transport import requests as google_requests



def get_credentials(user_token = None, show_login: bool = False):
    if not user_token:
        # Check env first, then path,
        # if not prompt auth if needed.
        if (user_token := os.environ.get(
            constants.DEFAULT_COLAB_USER_TOKEN_ENV
        )) is not None:
            pass

        elif (user_token := constants.DEFAULT_COLAB_USER_TOKEN_PATH).exists():
            user_token = user_token.as_posix()

    if not user_token and not show_login:
        raise ValueError(
            'User token is needed. you can pass params "show_login=True". '
            'For interactive login.'
        )

    if not user_token:
        creds = GoogleApi.run_interactive_prompt(
            client_config=constants.DEFAULT_COLAB_CLIENT_CONFIG,
            scopes=constants.DEFAULT_COLAB_PUBLIC_SCOPES
        )
    else:
        creds = GoogleApi.creds_from_user_token(
            user_token=user_token
        )
    constants.DEFAULT_COLAB_USER_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    constants.DEFAULT_COLAB_USER_TOKEN_PATH.write_text(creds.to_json(), encoding='utf-8')
    return creds


def get_authorized_sessions(
    *,
    creds=None,
):
    if not creds:
        creds = get_credentials()

    return google_requests.AuthorizedSession(creds)


_cached_user_info = {}
def get_user_info(
    *,
    token: str | None = None,
    creds=None,
):
    if not token:
        if not creds:
            creds = get_credentials()
        if creds:
            token = creds.token
        else:
            raise ValueError('Either token or creds is needed to get user info')

    if data := _cached_user_info.get(token):
        return data

    qs = urlencode({"access_token": token})
    url = f"https://oauth2.googleapis.com/tokeninfo?{qs}"
    try:
        with urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            info = json.loads(body)
    except urllib.error.HTTPError as e:
        # tokeninfo returns 400 for invalid/expired/revoked tokens with a
        # JSON body like {"error":"invalid_token","error_description":"..."}.
        # Surface that body so the developer can see *why* it was rejected.
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        raise urllib.error.HTTPError(
            f"Token Info returned with status: {e.code} : {err_body or e.reason}"
        )

    email = info.get("email") or "<unavailable: token has no userinfo.email scope>"
    expires_in = info.get("expires_in")
    try:
        expires_min = int(expires_in) // 60
        expires_str = f"{expires_min}m"
    except (TypeError, ValueError):
        expires_str = str(expires_in) if expires_in else "<unknown>"

    audience = info.get("audience") or info.get("aud") or "<none>"
    scopes = (info.get("scope") or "").split()

    data = {
        'Email': email,
        'Audience': audience,
        'Expires': expires_str,
        'Scopes': scopes or '<none>'
    }
    _cached_user_info[token] = data
    return data

_cached_account_id = {}
def get_account_id(token: str):
    if account_id := _cached_account_id.get(token):
        return account_id

    email = get_user_info(token=token)["Email"]
    if not email or "@" not in email:
        raise ValueError(
            "Unable to identify the Google account. "
            "Ensure the credentials include userinfo.email scope."
        )

    account_id = hashlib.sha256(
        email.strip().casefold().encode("utf-8")
    ).hexdigest()
    _cached_account_id[token] = account_id
    return account_id

if __name__ == '__main__':
    from pprint import pprint
    pprint(get_user_info())
