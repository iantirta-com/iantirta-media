# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.
#
# Partial code of 'colab_cli' improve by iantirta.com

import base64
import datetime
import hashlib
import json
import logging
import os
import re
import sys
import threading
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
import time
import websocket
from colab_cli import client, common, runtime, state, utils
from google.auth.transport import requests as google_requests

from iantirta.media.tools.google import GoogleApi
from iantirta.media.worker.worker_mixin import GPUWorker

__all__ = [
    "ColabWorker"
]


_logger = logging.getLogger(__name__)


TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

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

# We create a wrapper to ensure a FINISHED marker is ALWAYS printed to the log,
# even if the user script errors out.
wrapper_code = '''
import runpy, sys
try:
    runpy.run_path('/content/job.py', run_name='__main__')
finally:
    print("n__IANTIRTA_JOB_FINISHED__", flush=True)
'''
Path('/content/job_wrapper.py').write_text(wrapper_code)

# Launch it completely detached from this Jupyter kernel
p = subprocess.Popen(
    [sys.executable, '/content/job_wrapper.py'],
    stdout=open('/content/job.log', 'a'),
    stderr=subprocess.STDOUT,
    start_new_session=True  # CRITICAL: Prevents termination when WebSocket closes
)
Path('/content/job.pid').write_text(str(p.pid))
print(f"JOB_LAUNCHED_SUCCESSFULLY with PID: {{p.pid}}")
"""


_Sentinel = object()
ANSI_COLOR_CODE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class SessionState(state.SessionState):
    account_id: str
state.SessionState = SessionState


def _apply_proxy_info(s: SessionState, info: client.RuntimeProxyInfo, account_id: str):
    s.token = info.token
    s.url = info.url
    s.token_expires_at = info.expires_at()
    s.account_id = account_id


class ColabWorker(GPUWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.populate_google_creds()

        self._is_console_running = False
    
    def populate_google_creds(self):
        
        creds = GoogleApi.creds_from_user_token(
            user_token=self.access_token
        )
        session = google_requests.AuthorizedSession(creds)

        self.client = client.Client(client.Prod(), session)
        self.state = common.state
        self.state._client = self.client
        self.state.config_path = Path("~/.cache/iantirta/worker/colab-sessions.json").expanduser().resolve().as_posix()
        self.state.history.log_dir = Path("~/.cache/iantirta/worker/colab-history").expanduser().resolve().as_posix()
        os.makedirs(self.state.history.log_dir, exist_ok=True)
        self.creds = creds

        self._account_id = None

    def _get_account_id(self) -> str:
        """Return a stable, non-reversible account identifier."""
        if self._account_id is None:
            email = self.test_connection()["Email"]

            if not email or "@" not in email:
                raise OSError(
                    "Unable to identify the Google account. "
                    "Ensure the credentials include userinfo.email scope."
                )

            self._account_id = hashlib.sha256(
                email.strip().casefold().encode("utf-8")
            ).hexdigest()

        return self._account_id

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

    # Sessions Management
    def sync_sessions(self, local_sessions: dict[str, SessionState] = _Sentinel):
        account_id = self._get_account_id()

        if local_sessions is _Sentinel:
            local_sessions = self.state.store.list()
        else:
            local_sessions = dict(local_sessions)
        
        assignments = self.client.list_assignments()

        by_endpoint = {a.endpoint: a for a in assignments}
        local_by_endpoint = {s.endpoint: s for s_name, s in local_sessions.items()}

        _logger.debug(f"Server Assignment length: {len(assignments)}")
        for a in assignments:
            s = local_by_endpoint.get(a.endpoint)
            info = a.runtime_proxy_info
            metadata = {
                "variant": a.variant.name,
                "accelerator": a.accelerator.value,
                "machine_shape": client.Shape.HIGH_RAM.name if a.machine_shape == client.Shape.HIGH_RAM else client.Shape.STANDARD.name,
            }
            if s is None:
                _logger.debug("Local sessions is none but there is assignment records. creating local")
                # Populate data
                name = f"Unknown - {uuid.uuid4().hex[:6]}"
                s = SessionState(
                    name=name,
                    token=info.token,
                    url=info.url,
                    token_expires_at=info.expires_at(),
                    endpoint=a.endpoint,
                    account_id=account_id,
                    **metadata,
                )
                self.state.store.add(s)
                self.state.history.log_event(
                    name,
                    "session_forwarded",
                    {
                        "endpoint": s.endpoint,
                        "variant": s.variant,
                        "accelerator": s.accelerator,
                        "machine_shape": s.machine_shape,
                    },
                )
            else:
                _logger.debug(f"Local sessions existed: {s}")
                # update data
                _apply_proxy_info(s, info, account_id)
                s.variant = metadata["variant"]
                s.accelerator = metadata["accelerator"]
                s.machine_shape = metadata["machine_shape"]
                self.state.store.add(s)

        pruned = 0
        for name, s in list(local_sessions.items()):
            if s.endpoint not in by_endpoint and s.account_id == account_id:
                self.state.prune_session(name)
                pruned += 1
            elif s.account_id == account_id:
                # Since we already update it earlier
                pass
            else:
                raise OSError("There is no way the account id could be different.")

        if pruned > 0:
            _logger.info(f"[colab] Pruned {pruned} stale local session(s).")

        return self.state.store.list()

    def get_sessions(self):
        return self.sync_sessions()

    def get_session(self, name: str):
        if not name:
            raise OSError("`get_session` require session name")
        
        s = self.state.store.get(name)
        if s and (
            not s.token_expires_at
            or s.token_expires_at - datetime.now(timezone.utc) <= TOKEN_REFRESH_MARGIN
        ):
            s = self.sync_sessions().get(name)

        if not s:
            raise OSError(f"Session not found with name: {name}")

        return s

    def new_session(
        self,
        name: str | None = None,
        *,
        accelerator=None,
        variant=None,
        shape=None,
    ) -> 'SessionState':
        if not name:
            name = self.name

        if not accelerator:
            accelerator = client.Accelerator.NONE

        if not variant:
            variant = client.Variant.DEFAULT

        if not shape:
            shape = client.Shape.STANDARD

        try:
            res = self.client.assign(
                notebook_hash=uuid.uuid4(),
                variant=variant,
                accelerator=accelerator,
                shape=shape
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
            account_id=self._get_account_id(),
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

    def new_gpu_session(self, name: str | None = None):
        return self.new_session(
            name,
            accelerator = client.Accelerator.T4, # T4
            variant = client.Variant.GPU, # GPU
            shape = client.Shape.STANDARD,
         )

    def get_or_create_sessions(self, name: str | None = None, *, gpu: bool = False):
        if not name:
            sess = list(self.get_sessions().keys())
            if len(sess) == 1:
                name = sess[0]
            elif len(sess) > 1:
                raise OSError(
                    "Multiple active sessions found. Specify one with name"
                )
            else:
                name = self.name

        try:
            s = self.get_session(name)
        except Exception as e:
            _logger.error(f"Failed to get sessions, creating a new one. Error: {e}")
            if gpu:
                s = self.new_gpu_session(name)
            else:
                s = self.new_session(name)
        return s

    def close_session(self, name: str | None = None):
        if not name:
            name = self.name

        s = self.get_session(name)

        _logger.info(f"[colab] Stopping session '{name}'...")
        try:
            rt = runtime.ColabRuntime(s.url, s.token, kernel_id=s.kernel_id)
            rt.stop(shutdown_kernel=True)
        except Exception:
            pass

        self.state.client.unassign(s.endpoint)
        self.state.store.remove(name)
        self.state.history.log_event(
            name, "session_terminated",
            {"reason": "close"}
        )

        _logger.info("[colab] Session terminated.")

    # Kernel Management
    def kernel_exec(self, s: SessionState, code: str, **kwargs):
        _logger.info(f"Executing code using: {s.name}")

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
        def drivefs_hook(deserialize_msg, wsclient):
            print("Deserialize", deserialize_msg)
            print('Ws client', wsclient)
            return False
        rt.colab_request_hook = drivefs_hook

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
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            self.state.store.add(s)
            
            outputs = rt.execute_code(code, timeout=30.0, **kwargs)

            for out in outputs:
                if out.get("output_type") == "error":
                    ename = out.get("ename", "Error")
                    evalue = out.get("evalue", "")
                    tb = out.get("traceback", [])
                    if tb:
                        msg = "".join(tb) + "\n"
                    else:
                        msg = f"{ename}: {evalue}\n"
                    raise OSError(msg)
                else:
                    _logger.debug(out)
            
            _logger.debug(
                f"Worker ({s.name}) execution:\n"
                f"  code:\n"
                f"{'='*50}\n"
                f"{code}\n"
                f"{'='*50}\n"
            )
        
        finally:
            s.running = None
            self.state.store.add(s)
            rt.stop()

    def kernel_connect_console(self, s: SessionState, *, tty: bool = True, on_close_hook=None):
        parsed = urlparse(s.url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{ws_scheme}://{parsed.netloc}/colab/tty?colab-runtime-proxy-token={s.token}"

        def on_open(ws):
            _logger.info(f"[colab] WebSocket connected to {s.name}. Resuming log stream...")
            if tty:
                self._is_console_running = True
                # Setup the background thread to read from stdin
                def read_stdin():
                    # When stdin is piped and reaches EOF, we send "exit\n" to the remote shell and
                    # then wait this many seconds for any remaining output (the shell's goodbye,
                    # tmux teardown messages, etc.) to flush before closing the websocket from the
                    # client side. Empirically 0.5s is enough for the typical /colab/tty backend
                    # wrapped in tmux + bash; bumping it just delays exit, lowering it risks
                    # truncating tail output.
                    PIPED_EOF_GRACE_SECONDS = 0.5

                    is_tty = sys.stdin.isatty()
                    while self._is_console_running:
                        try:
                            # Read a single character (or escape sequence byte)
                            char = sys.stdin.read(1)
                            if not char:
                                if not is_tty:
                                    # Piped input has reached EOF. The remote /colab/tty
                                    # endpoint wraps bash in tmux which intercepts \x04
                                    # (Ctrl-D) as a literal character, so it never exits.
                                    # Instead send "exit\n" so bash voluntarily terminates,
                                    # wait a short grace period for the shell's goodbye
                                    # output to drain back to us, then close the websocket
                                    # ourselves to guarantee the client unblocks.
                                    try:
                                        ws.send(json.dumps({"data": "exit\n"}))
                                    except Exception:
                                        pass
                                    time.sleep(PIPED_EOF_GRACE_SECONDS)
                                    try:
                                        ws.close()
                                    except Exception:
                                        pass
                                break
                            ws.send(json.dumps({"data": char}))
                        except Exception:
                            break

                thread = threading.Thread(target=read_stdin, daemon=True)
                thread.start()
            else:
                # Send a bash command via TTY. It tails the log based on the PID. 
                # Once the PID dies, tail closes and it echoes the finish marker.
                cmd = (
                    'if [ -f /content/job.pid ]; then '
                    'tail -n 100 -f --pid=$(cat /content/job.pid) /content/job.log; '
                    'else echo "No running job found."; fi;\r '
                )
                ws.send(json.dumps({"data": cmd}))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if "data" in data:
                    # The backend sends raw ANSI escape sequences and string content.
                    if tty:
                        # We write it directly to stdout buffer to avoid python print() formatting.
                        sys.stdout.buffer.write(data["data"].encode("utf-8"))
                        sys.stdout.buffer.flush()
                    else:
                        text = ANSI_COLOR_CODE_RE.sub('', data['data'])
                        print(text.replace('\r\n', ''))
                        if "__IANTIRTA_JOB_FINISHED__" in text:
                            _logger.info("[colab] Job finished marker detected. Closing WebSocket.")
                            ws.close()
                    # print(data['data'], flush=True)
                else:
                    print("Message IS", data)
                # if isinstance(msg, list) and len(msg) >= 2 and msg[0] == "stdout":
                #     text = msg[1]
                #     # Print dynamically without adding newlines, mirroring a terminal
                #     print(text, end="", flush=True)
                    
                    
            except Exception as e:
                # Fallback for unexpected payloads
                _logger.debug(f"Error parsing message: {e}")
                if "__IANTIRTA_JOB_FINISHED__" in str(message):
                    ws.close()

        def on_error(ws, error):
            _logger.error(f"[colab] WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            if tty:
                self._is_console_running = False
            _logger.info(f"[colab] WebSocket connection closed for {s.name}.")

        ws = websocket.WebSocketApp(
            url=ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        try:
            ws.run_forever()
        finally:
            _logger.info(f"Connection of {s.name} closed.")
            if on_close_hook:
                on_close_hook()

    def kernel_connect_console_as_background(self, s: SessionState, **kwargs):
        thread = threading.Thread(
            target=self.kernel_connect_console, args=(s,), kwargs=kwargs, daemon=True
        )
        thread.start()
        return thread

    def kernel_push(self, s: SessionState, code: str):
        def on_close():
            self.close_session(s.name)
        self.kernel_exec(s, code, output_hook=print)
        return self.kernel_connect_console_as_background(
            s,
            tty=False,
            on_close_hook=on_close
        )

    def kernel_run(self, s: SessionState, code: str):
        return self.kernel_exec(s, code, output_hook=print)
    
    def attach(self, name: str | None = None):
        """Reconnect to an existing session and resume streaming the background job."""
        if not name:
            name = self.name
        s = self.get_session(name)
        _logger.info(f"Reattaching to background job on session '{s.name}'...")
        def on_close():
            self.close_session(s.name)
        return self.kernel_connect_console_as_background(
            s,
            tty=False,
            on_close_hook=on_close
        )

    # OVERRIDE
    def run(self, folder: str, *, name: str | None = None, run_in_background: bool = True, gpu: bool = False):
        # Folder is file in colab worker
        file = folder
        if not os.path.isfile(file):
            raise FileNotFoundError(f"Script file not found: {file}")
    
        if not name:
            name = self.name
        s = self.get_or_create_sessions(name, gpu=gpu)

        raw_code = Path(file).read_text(encoding='utf-8')

        if run_in_background:
            encoded_code = base64.b64encode(raw_code.encode('utf-8')).decode('utf-8')
            code = BOOTSTRAP_SCRIPT.format(encoded_code=encoded_code)
            return self.kernel_push(s, code)
        else:
            return self.kernel_run(s, raw_code)

    def get_quota(self):
        return self.client.get_consumption_user_info()


if __name__ == "__main__":
    from iantirta.telemetry import netsvc
    netsvc.setup_logger("__main__", default_level=logging.DEBUG)
#     from pathlib import Path
    from pprint import pprint
    colab = ColabWorker(
        access_token=os.environ['IANTIRTA_COLAB_USER_TOKEN']
    )

    # pprint(colab._get_account_id())
    # pprint(colab.new_session())
    # pprint(colab.get_or_create_sessions('test_worker'))
    # pprint(colab.get_or_create_sessions('Unknown - f10539'))
    # pprint(colab.get_sessions())
    # pprint(colab.close_session('test_worker'))
    t = colab.run((Path(__file__).parent / 'worker_mixin.py').as_posix(), name='test_worker', run_in_background=True)
    if t:
        _logger.info("Main script is waiting for the background job to finish...")
        t.join()  # This blocks the main script until ws.close() triggers the cleanup hook
        _logger.info("Job complete and session closed.")
