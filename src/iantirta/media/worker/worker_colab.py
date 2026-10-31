# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.


import logging
import os
import re
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

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
    
        self.state = State(auth_session=session, creds=creds)
        self.creds = creds

    # Override

    def run(
        self,
        path_or_dir: str,
        *,
        run_in_background: bool = True,
        gpu: bool = False,
        on_close_hook: Callable[[None], None] | None = None,
    ) -> threading.Thread | None:
        """
        Run worker given any path / dir path.

        Provider method should override this.

        :param str path_or_dir:
            on colab this became the actual script path
        :param bool run_in_background:
        :param bool gpu:
        :param Callable[[None]] on_close_hook:
        :return: Thread object or None
        :rtype: threading.Thread | None
        """
        # Folder is file in colab worker
        file = path_or_dir

        if not os.path.isfile(file):
            raise FileNotFoundError(f"Script file not found: {file}")

        kwargs = {'gpu': 't4',} if gpu else {}
        s = self.state.resolve_session(self.name, **kwargs)

        return self.state.kernel.run(
            file,
            s=s,
            run_in_background=run_in_background,
            on_close_hook=on_close_hook
        )

    def get_quota(self) -> dict[str, Any]:
        """
        Fetch quota or usage for the worker.

        Provider method should override this.

        :rtype: dict[str, Any]
        """
        return asdict(self.state.client.get_consumption_user_info())
