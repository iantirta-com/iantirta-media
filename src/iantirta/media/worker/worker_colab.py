# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.
#
# Partial code of 'colab_cli' improve by iantirta.com

import base64
import datetime
import json
import logging
import os
import urllib.error
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from urllib.request import urlopen

from google.auth.transport import requests as google_requests

from iantirta.media.tools.google import GoogleApi
from iantirta.media.worker.worker_mixin import GPUWorker

if TYPE_CHECKING:
    from colab_cli.state import SessionState

__all__ = [
    "ColabWorker"
]

_logger = logging.getLogger(__name__)

# Standard Scopes for Colab and Drive (Public Auth)
PUBLIC_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/colaboratory",
    "https://www.googleapis.com/auth/drive.file",
]


BOOTSTRAP_SCRIPT = """
import base64
import subprocess
import sys
from pathlib import Path

# Write the actual payload to disk
code = base64.b64decode('{encoded_code}')
Path('/content/job.py').write_bytes(code)

# Launch it completely detached from this Jupyter kernel
subprocess.Popen(
    [sys.executable, '/content/job.py'],
    stdout=open('/content/job.log', 'a'),
    stderr=subprocess.STDOUT,
    start_new_session=True  # CRITICAL: Prevents termination when WebSocket closes
)
print("JOB_LAUNCHED_SUCCESSFULLY")
"""


class ColabWorker(GPUWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        creds = GoogleApi.creds_from_user_token(
            user_token=self.access_token
        )
        session = google_requests.AuthorizedSession(creds)

        from colab_cli import client, common
        self.client = client.Client(client.Prod(), session)
        self.state = common.state
        self.state._client = self.client
        self.state.config_path = os.path.expanduser("~/.cache/iantirta/worker/colab-sessions.json")
        self.creds = creds

    def test_connection(self):
        token = self.creds.token

        if not token:
            raise OSError("Google credentials have no valid token or empty token")

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
        return data

    def _new(self, worker_name: str | None = None) -> 'SessionState':
        from colab_cli import client, state, utils

        name = worker_name or uuid.uuid4().hex[:6]

        accelerator = client.Accelerator.NONE # T4
        variant = client.Variant.DEFAULT # GPU
        shape = client.Shape.STANDARD

        try:
            res = self.client.assign(
                uuid.uuid4(), variant=variant, accelerator=accelerator, shape=shape
            )
        except client.TooManyAssignmentsError:
            raise OSError(
                "[colab] Allocation refused (precondition failed). This can mean "
                "too many active sessions, or a temporary usage or capacity "
                "limit for the requested runtime. Run `colab stop` to free up a "
                "session, wait and retry, or try a different accelerator."
            )
        except client.ColabRequestError as e:
            # The Colab backend returns 400 when the caller is not entitled to the
            # requested accelerator (e.g. no A100 quota). Translate that to a
            # friendly, actionable message instead of a raw traceback. We only
            # interpret it this way when an accelerator was actually requested;
            # otherwise we re-raise so the user sees the real cause.
            if utils.get_status_code(e) == 400 and accelerator != client.Accelerator.NONE:
                raise OSError(
                    f"[colab] Backend rejected accelerator '{accelerator.value}'. "
                    "You may not have quota or entitlement for this accelerator on "
                    "your account. Try a different one (e.g. --gpu T4) or omit "
                    "--gpu/--tpu for a CPU runtime."
                )
            raise
        
        if isinstance(res, client.PostAssignmentResponse):
            token = res.runtime_proxy_info.token
            url = res.runtime_proxy_info.url
            endpoint = res.endpoint
        else:
            token = (
                res.runtime_proxy_info.token
                if hasattr(res, "runtime_proxy_info")
                else getattr(res, "runtime_proxy_token", "")
            )
            url = res.runtime_proxy_info.url if hasattr(res, "runtime_proxy_info") else ""
            endpoint = res.endpoint

        s = state.SessionState(
            name=name,
            token=token,
            url=url,
            endpoint=endpoint,
            token_expires_at=(
                res.runtime_proxy_info.expires_at()
                if hasattr(res, "runtime_proxy_info")
                else None
            ),
            variant=variant.value,
            accelerator=accelerator.value,
            machine_shape=(
                client.Shape.HIGH_RAM.name if shape == client.Shape.HIGH_RAM else client.Shape.STANDARD.name
            ),
        )

        self.state.store.add(s)
        self.state.history.log_event(
            name,
            "session_created",
            {
                "endpoint": endpoint,
                "variant": variant.value,
                "accelerator": accelerator.value,
                "machine_shape": s.machine_shape,
            },
        )

        return s

    def new(self, worker_name: str | None = None) -> 'SessionState':
        if not worker_name:
            worker_name = self.name

        try:
            s_name = self.state.resolve_session(worker_name)
            s = self.state.get_session(s_name)
        except Exception:  # noqa: BLE001
            s = None

        if not s:
            s = self._new(worker_name)

        return s

    def _exec(self, s: 'SessionState', code: str, *, name: str | None=None):
        from colab_cli import runtime, utils

        if not s:
            s = self.new(name)
        
        def on_started(kid):
            s.kernel_id = kid
            self.state.store.add(s)

        def on_sess_started(sid):
            s.session_id = sid
            self.state.store.add(s)

        rt = runtime.ColabRuntime(
            s.url,
            s.token,
            kernel_id=s.kernel_id,
            session_id=s.session_id,
            on_kernel_started=on_started,
            on_session_started=on_sess_started,
        )

        try:
            # Ensure we are in /content which is the standard Colab working directory
            rt.execute_code(
                "import os; os.makedirs('/content', exist_ok=True); os.chdir('/content')"
            )
        except Exception as e:
            if utils.is_terminal_error(e):
                self.state.prune_session(s.name)
                raise OSError(
                    f"[colab] Session '{s.name}' appears to be lost (404/401). Cleaning up."
                )
            raise

        try:
            s.running = "background_job(code_exec)"
            s.last_execution = (
                "code_exec",
                None,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self.state.store.add(s)
            
            outputs = rt.execute_code(code, timeout=30.0)
            
            _logger.debug(
                f"Worker ({s.name}) execution:\n"
                f"  code:\n"
                f"{'='*50}\n"
                f"{code}\n"
                f"{'='*50}\n"
                f"  outputs:\n"
                f"{'='*50}\n"
                f"{outputs}\n"
            )

        finally:
            s.running = None
            self.state.store.add(s)
            rt.stop()

    def kernel_push(self, s: 'SessionState', file: str, *, name: str | None=None):
        if not s:
            s = self.new(name)

        if not os.path.isfile(file):
            raise FileNotFoundError(f"Script file not found: {file}")

        raw_code = Path(file).read_text(encoding='utf-8')
        
        encoded_code = base64.b64encode(raw_code.encode('utf-8')).decode('utf-8')

        code = BOOTSTRAP_SCRIPT.format(encoded_code=encoded_code)
        outputs = self._exec(s, code)

        _logger.info(f"Colab job submitted to {s.name}. Bootstrap outputs: {outputs}")

    def exec_code(self, s: 'SessionState', code: str, *, name: str | None=None):
        if not s:
            s = self.new(name)
        return self._exec(s, code)

    def run(self, folder: str):
        s = self.new(self.name)
        # ----- Execute the script -------------------------------------------------
        # Folder is a folder in kaggle worker, but a file path in google colab worker
        self.kernel_push(s, folder,)

    def _close(self, s: 'SessionState'):
        """Best-effort full session teardown: kill the keep-alive daemon, ask the
        remote kernel to shut down, unassign the VM, and remove local state.

        Mirrors `commands.session.stop` but with a richer history event reason and
        swallowing all errors (we don't want a teardown failure to mask the user's
        exit code).
        """
        from colab_cli import runtime
    
        _logger.info(f"[colab] Stopping session '{s.name}'...")
        try:
            # The script may have outlived the proxy token.
            fresh = self.state.get_session(s.name, ignore_missing_session=True)
            if fresh:
                rt = runtime.ColabRuntime(fresh.url, fresh.token, kernel_id=fresh.kernel_id)
                rt.stop(shutdown_kernel=True)
        except Exception:
            pass

        try:
            self.state.client.unassign(s.endpoint)
        except Exception:
            pass

        try:
            self.state.store.remove(s.name)
        except Exception:
            pass

        try:
            self.state.history.log_event(s.name, "session_terminated", {"reason": 'close'})
        except Exception:
            pass
        
        _logger.info("[colab] Session terminated.")

    def close(self, s: 'SessionState | None' = None, *, name: str | None = None):
        if not s:
            s = self.new(name)

        return self._close(s)

    def get_quota(self):
        return self.client.get_consumption_user_info()

if __name__ == "__main__":
    from iantirta.telemetry import netsvc
    netsvc.setup_logger("__main__", default_level=logging.DEBUG)
#     from pathlib import Path
    from pprint import pprint
    colab = ColabWorker(access_token=os.environ['IANTIRTA_COLAB_USER_TOKEN'])
    # pprint(colab.get_quota())
#     # pprint(colab.test_connection())
#     # pprint(colab.new('test_worker'))
#     # pprint(colab.colab_session.resolve_session(None))
#     # pprint(colab.colab_session.store.get('test_worker'))
    s = colab.new()
    # pprint(s)
#     # pprint(colab.run((Path(__file__).parent / 'worker_mixin.py').as_posix()))
    code = """
!ls
!cat job.log
!cat job.py
!pgrep -f "python /content/job.py"
# !pgrep -f /content/job.py
"""
    pprint(colab.exec_code(s, code))
    # pprint(colab.close(s))
#     # pprint(colab.exec(s, (Path(__file__).parent / 'worker_mixin.py').as_posix()))
#     # colab.run(__file__)