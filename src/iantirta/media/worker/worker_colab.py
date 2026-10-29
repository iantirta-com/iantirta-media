# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.


import logging
import os
import re
from dataclasses import asdict

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

        creds = get_credentials(user_token=self.access_token)
        session = get_authorized_sessions(creds=creds)
    
        self.state = State(auth_session=session)
        self.creds = creds
    
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

        return self.state.kernel.run(file, s=s, run_in_background=run_in_background)

    def get_quota(self):
        return asdict(self.state.client.get_consumption_user_info())


if __name__ == "__main__":
    from iantirta.telemetry import netsvc
    netsvc.setup_logger("__main__", default_level=logging.DEBUG)
    from pathlib import Path
    from pprint import pprint
    colab = ColabWorker(
        name='test_worker',
        access_token=os.environ['IANTIRTA_COLAB_USER_TOKEN']
    )
    pprint(colab.get_quota())

    # pprint(colab._get_account_id())
    # pprint(colab.new_session())
    # pprint(colab.get_or_create_sessions('test_worker'))
    # pprint(colab.get_or_create_sessions('Unknown - f10539'))
    # pprint(colab.get_sessions())
    # pprint(colab.close_session('test_worker'))
    t = colab.run(
        (Path(__file__).parent / 'worker_mixin.py').as_posix(),
        run_in_background=True
    )
    if t:
        _logger.info("Main script is waiting for the background job to finish...")
        t.join()  # This blocks the main script until ws.close() triggers the cleanup hook
        _logger.info("Job complete and session closed.")
