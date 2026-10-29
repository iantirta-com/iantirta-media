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
import time
import urllib.error
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import websocket
from colab_cli import client, common, runtime, state, utils
from google.auth.transport import requests as google_requests

from iantirta.media.tools.google import GoogleApi
from iantirta.media.worker.colab_utils.auth import (
    get_authorized_sessions,
    get_credentials,
)
from iantirta.media.worker.colab_utils.state import State
from iantirta.media.worker.worker_mixin import GPUWorker

__all__ = [
    "ColabWorker"
]


_logger = logging.getLogger(__name__)


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

class ColabWorker(GPUWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.populate_google_creds()

        self._is_console_running = False
    
    def populate_google_creds(self):
        
        creds = get_credentials(user_token=self.access_token)
        session = get_authorized_sessions(creds=creds)
    
        self.state = State(auth_session=session)
        self.creds = creds


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
    def run(
        self,
        folder: str,
        *,
        run_in_background: bool = True,
        gpu: bool = False
    ):
        # Folder is file in colab worker
        file = folder
        if not os.path.isfile(file):
            raise FileNotFoundError(f"Script file not found: {file}")

        kwargs = {'gpu': 't4',} if gpu else {}
        s = self.state.resolve_session(self.name, **kwargs)

        raw_code = Path(file).read_text(encoding='utf-8')

        if run_in_background:
            encoded_code = base64.b64encode(raw_code.encode('utf-8')).decode('utf-8')
            code = BOOTSTRAP_SCRIPT.format(encoded_code=encoded_code)
            return self.kernel_push(s, code)
        else:
            return self.kernel_run(s, raw_code)

    def get_quota(self):
        return asdict(self.state.client.get_consumption_user_info())


if __name__ == "__main__":
    from iantirta.telemetry import netsvc
    netsvc.setup_logger("__main__", default_level=logging.DEBUG)
#     from pathlib import Path
    from pprint import pprint
    colab = ColabWorker(
        access_token=os.environ['IANTIRTA_COLAB_USER_TOKEN']
    )
    pprint(colab.get_quota())

    # pprint(colab._get_account_id())
    # pprint(colab.new_session())
    # pprint(colab.get_or_create_sessions('test_worker'))
    # pprint(colab.get_or_create_sessions('Unknown - f10539'))
    # pprint(colab.get_sessions())
    # pprint(colab.close_session('test_worker'))
    # t = colab.run((Path(__file__).parent / 'worker_mixin.py').as_posix(), name='test_worker', run_in_background=True)
    # if t:
    #     _logger.info("Main script is waiting for the background job to finish...")
    #     t.join()  # This blocks the main script until ws.close() triggers the cleanup hook
    #     _logger.info("Job complete and session closed.")
