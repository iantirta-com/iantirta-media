from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import websocket

from iantirta.media.worker.colab_utils.runtime import ColabRuntime
from iantirta.media.worker.colab_utils.utils import is_terminal_error

try:
    import termios
    import tty
except ImportError:
    # Windows has neither termios nor tty. connect_console() below degrades
    # gracefully to line-buffered input when these are unavailable.
    termios = None
    tty = None

if TYPE_CHECKING:
    from .state import SessionState, State


_logger = logging.getLogger(__name__)


ANSI_COLOR_CODE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
ANSI_CHAR_CODE_RE = re.compile(r'\x1B(?:\][^\x07\x1B]*?(?:\x07|\x1B\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])')

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


def display_output(out, output_image=None):
    if out.get("output_type") == "stream":
        stream = sys.stderr if out.get("name") == "stderr" else sys.stdout
        stream.write(out.get("text", ""))
        stream.flush()
    else:
        print(out)


def send_terminal_size(ws):
    """Sends the current terminal size to the remote backend."""
    try:
        size = os.get_terminal_size()
        payload = json.dumps({"cols": size.columns, "rows": size.lines})
        ws.send(payload)
    except Exception as e:
        _logger.debug(f"Failed to send terminal size: {e}")


class Kernel:
    def __init__(self, state: State):
        self.state = state

    def _run(self, s: SessionState, code: str, **kwargs):
        _logger.info(f"Executing code using: {s.name}")

        def on_started(kid):
            s.kernel_id = kid
            self.state.store.add(s)

        def on_sess_started(sid):
            s.session_id = sid
            self.state.store.add(s)

        rt = ColabRuntime(
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
            if is_terminal_error(e):
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
            
            outputs = rt.execute_code(
                code,
                timeout=30.0,
                output_hook=display_output,
                **kwargs
            )

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

    def console(
        self,
        s: SessionState,
        *,
        run_in_background: bool = False,
        on_close_hook=None,
    ):
        is_console_running = False
        _last_error = None

        def connect_console():
            parsed = urlparse(s.url)
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = f"{ws_scheme}://{parsed.netloc}/colab/tty?colab-runtime-proxy-token={s.token}"

            is_tty = sys.stdin.isatty()
            fd = None
            old_settings = None
            can_raw = termios is not None and tty is not None and is_tty
            if can_raw:
                try:
                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)
                except Exception:
                    fd = None
                    old_settings = None
                    can_raw = False
            
            def on_open(ws):
                _logger.info(f"[colab] WebSocket connected to {s.name}. Resuming log stream...")
                
                # Send initial terminal size
                send_terminal_size(ws)
                
                if not run_in_background:
                    nonlocal is_console_running
                    is_console_running = True
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
                        while is_console_running:
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
                        if not run_in_background:
                            # We write it directly to stdout buffer to avoid python print() formatting.
                            sys.stdout.buffer.write(data["data"].encode("utf-8"))
                            sys.stdout.buffer.flush()
                        else:
                            text = ANSI_CHAR_CODE_RE.sub('', data['data'])
                            sys.stdout.buffer.write(text.encode('utf-8'))
                            sys.stdout.buffer.flush()
                            if "__IANTIRTA_JOB_FINISHED__" in text:
                                _logger.info("[colab] Job finished marker detected. Closing WebSocket.")
                                ws.close()
                    else:
                        print("Message IS", data)
                        
                        
                except Exception as e:
                    # Fallback for unexpected payloads
                    _logger.debug(f"Error parsing message: {e}")
                    if "__IANTIRTA_JOB_FINISHED__" in str(message):
                        ws.close()

            def on_error(ws, error):
                nonlocal _last_error
                _last_error = error
                _logger.error(f"[colab] WebSocket error: {error}")

            def on_close(ws, close_status_code, close_msg):
                if not run_in_background:
                    nonlocal is_console_running
                    is_console_running = False
                _logger.info(f"[colab] WebSocket connection closed for {s.name}.")

            ws = websocket.WebSocketApp(
                url=ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            if not run_in_background:
                import signal
                def handle_sigwinch(signum, frame):
                    """Handle window resize events."""
                    if is_console_running:
                        send_terminal_size(ws)

                sigwinch = getattr(signal, "SIGWINCH", None)

            try:
                if not run_in_background and can_raw:
                    tty.setraw(fd, termios.TCSANOW)
                    if sigwinch is not None:
                        signal.signal(sigwinch, handle_sigwinch)

                ws.run_forever()

                if _last_error:
                    # Re-raise or wrap terminal errors
                    err_msg = str(_last_error)
                    if "404" in err_msg or "401" in err_msg:
                        # We raise a standard exception that the caller can recognize
                        raise RuntimeError(f"Connection failed: {err_msg}")
            finally:
                if not run_in_background and can_raw:
                    # Always ensure the terminal is restored to its original state
                    try:
                        termios.tcsetattr(fd, termios.TCSANOW, old_settings)
                    except Exception:
                        pass
                    # Restore the default signal handler for resize
                    if sigwinch is not None:
                        try:
                            signal.signal(sigwinch, signal.SIG_DFL)
                        except Exception:
                            pass
                _logger.info(f"Connection of {s.name} closed.")
                if on_close_hook:
                    on_close_hook()


        if run_in_background:
            thread = threading.Thread(target=connect_console, daemon=True)
            thread.start()
            return thread
        else:
            return connect_console()
    
    def run(
        self,
        script_path: str,
        *,
        s: SessionState | None = None,
        name: str | None = None,
        run_in_background: bool = False,
        on_close_hook=None,
        **kwargs,
    ):
        """Run python script. create session if not exists"""
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script file not found: {script_path}")
        
        if s is None:
            name = name or uuid.uuid4().hex[:6]
            s = self.state.resolve_session(name, **kwargs)

        raw_code = Path(script_path).read_text(encoding='utf-8')

        def on_close():
            if on_close_hook:
                try:
                    on_close_hook()
                except Exception as e:
                    _logger.error(f"Error on close hook: {e}")
            self.state.stop_session(s.name)
        
        if run_in_background:
            encoded_code = base64.b64encode(raw_code.encode('utf-8')).decode('utf-8')
            code = BOOTSTRAP_SCRIPT.format(encoded_code=encoded_code)
            self._run(s, code)
            return self.console(s, run_in_background=True, on_close_hook=on_close)
        else:
            self._run(s, raw_code)
            on_close()


if __name__ == '__main__':
    from iantirta.telemetry import netsvc
    netsvc.setup_logger(__name__, default_level=logging.DEBUG)
    from pprint import pprint

    from iantirta.media.worker.colab_utils.state import state
    kernel = Kernel(state)

    def on_close():
        quota = state.client.get_consumption_user_info()
        print("This is after closing, quota is", quota)
    
    t = kernel.run(
        (Path(__file__).parent.parent / 'worker_mixin.py').as_posix(),
        name='test_colab',
        run_in_background=True,
        on_close_hook=on_close,
    )
    if t:
        _logger.info("Main script is waiting for the background job to finish...")
        t.join()  # This blocks the main script until ws.close() triggers the cleanup hook
        _logger.info("Job complete and session closed.")
