# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.
#
# Partial code of 'colab_cli' improve by iantirta.com
#
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import logging
import os
import time
import uuid

from colab_cli.client import (
    Accelerator,
    ColabRequestError,
    PostAssignmentResponse,
    Variant,
)
from colab_cli.runtime import ColabRuntime
from colab_cli.state import SessionState
from colab_cli.utils import get_status_code, is_terminal_error
from google.auth.transport import requests as google_requests
from colab_cli.commands.session import (
    _is_scope_error,
    _scope_remediation_message,
    spawn_keep_alive,
)
from iantirta.media.tools.google import GoogleApi
from iantirta.media.worker.worker_mixin import GPUWorker
from colab_cli import auth
auth.TOKEN_CONFIG_PATH

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


class ColabWorker(GPUWorker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        creds = GoogleApi.creds_from_user_token(
            user_token=self.access_token
        )
        session = google_requests.AuthorizedSession(creds)

        from colab_cli import client
        self._api = client.Client(client.Prod(), session)


    def test_connection(self):
        print(self._api.list_assignments())
        # res = self._api.assign(
        #     uuid.uuid4(),
        # )
        # from rich import inspect as i
        # i(res)
    
    def run2(self):
        from colab_cli import client

        res = self._api.assign(
            uuid.uuid4(),
            # variant=variant, accelerator=accelerator
        )

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

        try:
            self._api.keep_alive_assignment(endpoint)
        except Exception:
            self._api.unassign(endpoint)

        runtime = ColabRuntime(
            url,
            token,
        )

        try:
            runtime.execute_code(
                "import os; os.makedirs('/content', exist_ok=True); "
                "os.chdir('/content')"
            )
        finally:
            runtime.stop(shutdown_kernel=True)

    # TODO(sethtroisi): dedupe this logic with similar in session.py
    @staticmethod
    def _resolve_accelerator(gpu: str | None, tpu: str | None):
        """Mirror the mapping logic in `commands.session.new`. Centralised so the
        two commands stay in lock-step on supported accelerator names.
        """
        if tpu:
            variant = Variant.TPU
            accelerator = Accelerator.V5E1 if tpu.lower() == "v5e1" else Accelerator.V6E1
            return variant, accelerator
        if gpu:
            mapping = {
                "a100": Accelerator.A100,
                "h100": Accelerator.H100,
                "l4": Accelerator.L4,
                "t4": Accelerator.T4,
                "g4": Accelerator.G4,
            }
            return Variant.GPU, mapping.get(gpu.lower(), Accelerator.A100)
        return Variant.DEFAULT, Accelerator.NONE

    @staticmethod
    def _strip_shebang(body: str) -> str:
        """Remove a leading `#!...\\n` if present. The remote kernel doesn't need
        or understand it (it's a contract between the local kernel and the file's
        executable bit), and leaving it in just adds noise.
        """
        if body.startswith("#!"):
            nl = body.find("\n")
            return body[nl + 1 :] if nl != -1 else ""
        return body

    @staticmethod
    def _build_script_payload(script_path: str, script_args: list[str]) -> str:
        """Wrap the script body so it executes with native-`python`-like semantics.

        Specifically:
        - `sys.argv = [<basename>, *script_args]` so `argparse` etc. work.
        - `__name__ = '__main__'` so `if __name__ == "__main__":` guards fire.
        - Suppress the IPython UserWarning "To exit: use 'exit', 'quit', or
            Ctrl-D." which fires whenever the script calls `sys.exit(...)`. This
            warning is meaningful in an interactive REPL, but for `colab run` it
            is pure noise that doesn't appear when running `python script.py`.

        The script body is appended verbatim; the prelude is short so any
        traceback line numbers from user code remain close to the original.
        """
        basename = os.path.basename(script_path)
        with open(script_path, "r", encoding="utf-8") as f:
            body = f.read()

        # `repr()` produces a safe, round-trippable Python literal for arbitrary
        # strings (handles quotes, backslashes, non-ASCII).
        argv_literal = f"[{', '.join(repr(x) for x in [basename] + script_args)}]"

        return (
            "import sys, warnings\n"
            f"sys.argv = {argv_literal}\n"
            "__name__ = '__main__'\n"
            "warnings.filterwarnings('ignore', message=\"To exit: use\")\n"
            + ColabWorker._strip_shebang(body)
        )

    @staticmethod
    def _is_systemexit(out) -> bool:
        """True iff this output is a `raise SystemExit(...)` (a.k.a. `sys.exit`)."""
        return out.get("output_type") == "error" and out.get("ename") == "SystemExit"
    
    @staticmethod
    def _systemexit_code(out) -> int:
        """Map a SystemExit kernel output back to a CPython-style integer exit code.

        CPython conventions (mirrored):
        - `sys.exit()` / `sys.exit(None)` / `sys.exit(0)` -> 0
        - `sys.exit(<int>)`                                -> <int>
        - `sys.exit('msg')` (any non-int)                  -> 1
        """
        evalue = (out.get("evalue") or "").strip()
        if evalue in ("", "None", "0"):
            return 0
        try:
            return int(evalue)
        except ValueError:
            return 1

    @staticmethod
    def _make_run_output_hook(output_image=None):
        """Build an `output_hook` for `runtime.execute_code` that:
        - Routes normal output to `display_output` (stream/image/error).
        - Suppresses the `SystemExit` traceback so `sys.exit(0)` is silent (it
            wouldn't print anything under `python script.py` either) and
            `sys.exit(N)` doesn't dump a noisy IPython-styled traceback when the
            intent is "shell exit code N".

        The kernel still RETURNS the SystemExit output to us (so we can derive the
        exit code in `_exit_code_from_outputs`); we just don't render it.
        """
        # Imported here to avoid a circular import via execution.py at module load.
        from colab_cli.commands.execution import display_output

        def hook(out):
            if ColabWorker._is_systemexit(out):
                return
            display_output(out, output_image)

        return hook

    @staticmethod
    def _exit_code_from_outputs(outputs) -> int:
        """Derive the CLI's exit code from the kernel's outputs for a single cell.

        A `SystemExit` is treated like CPython would treat the same call from a
        plain `python script.py` invocation. Any *other* error (uncaught
        exception, NameError, etc.) is exit 1.
        """
        code = 0
        for o in outputs:
            if o.get("output_type") != "error":
                continue
            if ColabWorker._is_systemexit(o):
                ec = ColabWorker._systemexit_code(o)
                # Last SystemExit wins, matching the runtime — and any non-zero
                # eclipses any prior zero.
                code = ec if ec != 0 else code
            else:
                return 1
        return code

    @staticmethod
    def _teardown(name: str, s: SessionState, *, reason: str) -> None:
        """Best-effort full session teardown: kill the keep-alive daemon, ask the
        remote kernel to shut down, unassign the VM, and remove local state.

        Mirrors `commands.session.stop` but with a richer history event reason and
        swallowing all errors (we don't want a teardown failure to mask the user's
        exit code).
        """
        from colab_cli.common import kill_process, state

        _logger.info(f"[colab] Stopping session '{name}'...", err=True)
        if s.keep_alive_pid:
            try:
                kill_process(s.keep_alive_pid)
            except Exception:
                pass

        try:
            rt = ColabRuntime(s.url, s.token, kernel_id=s.kernel_id)
            rt.stop(shutdown_kernel=True)
        except Exception:
            pass

        try:
            state.client.unassign(s.endpoint)
        except Exception:
            pass

        try:
            state.store.remove(name)
        except Exception:
            pass

        try:
            state.history.log_event(name, "session_terminated", {"reason": reason})
        except Exception:
            pass
        _logger.info("[colab] Session terminated.", err=True)

    def run(
        self,
        script,
        script_args=None,
        session=None,
        tpu=None,
        gpu=None,
        keep=False,
        timeout=30.0
    ):
        """Run a Python script on a fresh Colab VM, then release the VM

        Designed to be used as a shebang interpreter, e.g.

            #!/usr/bin/env -S colab run --gpu T4

        so a single executable .py file can rent a GPU, run, and clean up after
        itself.
        """
        from colab_cli.common import state

        script_args = script_args or []

        # AGENTS.md item 10: validate locally BEFORE allocating a VM. A typo'd
        # script path should not cost the user real compute.
        if not os.path.isfile(script):
            raise FileNotFoundError(f"Script file not found: {script}")

        name = session or f"run-{uuid.uuid4().hex[:6]}"
        variant, accelerator = self._resolve_accelerator(gpu, tpu)

        # typer.echo(f"[colab] Creating session '{name}'...", err=True)
        try:
            res = state.client.assign(
                uuid.uuid4(), variant=variant, accelerator=accelerator
            )
        except ColabRequestError as e:
            # Mirror `colab new`'s friendly accelerator-quota message.
            if get_status_code(e) == 400 and accelerator != Accelerator.NONE:
                typer.echo(
                    f"[colab] Backend rejected accelerator '{accelerator.value}'. "
                    "You may not have quota or entitlement for this accelerator on "
                    "your account. Try a different one (e.g. --gpu T4) or omit "
                    "--gpu/--tpu for a CPU runtime.",
                    err=True,
                )
                raise typer.Exit(code=1)
            raise

        if isinstance(res, PostAssignmentResponse):
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

        s = SessionState(
            name=name,
            token=token,
            url=url,
            endpoint=endpoint,
            variant=variant.value,
            accelerator=accelerator.value,
        )

        # Pre-flight keep-alive: same scope-detection dance as `colab new` so a
        # missing OAuth scope doesn't leak a billable assignment.
        try:
            state.client.keep_alive_assignment(endpoint)
        except ColabRequestError as e:
            if get_status_code(e) == 403 and _is_scope_error(e):
                typer.echo(
                    "[colab] Keep-alive pre-flight failed: your credentials "
                    "are missing an OAuth scope required by Colab.\n",
                    err=True,
                )
                typer.echo(_scope_remediation_message(state.auth_provider), err=True)
                try:
                    state.client.unassign(endpoint)
                except Exception:
                    pass
                raise typer.Exit(code=1)
            # Other failures: don't block — the daemon will retry.

        # AGENTS.md item 17: persist BEFORE spawning the daemon so the daemon's
        # initial state.store.get(name) doesn't race the parent.
        state.store.add(s)
        s.keep_alive_pid = spawn_keep_alive(
            endpoint,
            name,
            auth_provider=state.auth_provider,
            config_path=state.config_path,
        )
        state.store.add(s)
        state.history.log_event(
            name,
            "session_created",
            {
                "endpoint": endpoint,
                "variant": variant.value,
                "accelerator": accelerator.value,
                "via": "run",
            },
        )
        _logger.info(f"[colab] Session READY ({name}). Executing {script}...", err=True)

        # ----- Execute the script -------------------------------------------------
        exit_code = 0
        cleanup_reason = "run_completed"

        def on_started(kid):
            s.kernel_id = kid
            state.store.add(s)

        def on_sess_started(sid):
            s.session_id = sid
            state.store.add(s)

        runtime = ColabRuntime(
            s.url,
            s.token,
            kernel_id=s.kernel_id,
            session_id=s.session_id,
            on_kernel_started=on_started,
            on_session_started=on_sess_started,
        )

        try:
            # Same /content prelude as `colab exec` for consistency.
            try:
                runtime.execute_code(
                    "import os; os.makedirs('/content', exist_ok=True); "
                    "os.chdir('/content')"
                )
            except Exception as e:
                if is_terminal_error(e):
                    typer.echo(
                        f"[colab] Session '{name}' appears to be lost (404/401).",
                        err=True,
                    )
                    state.prune_session(name)
                    raise typer.Exit(1)
                raise

            payload = self._build_script_payload(script, script_args)
            s.running = f"run({os.path.basename(script)})"
            s.last_execution = (
                script,
                None,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            state.store.add(s)

            try:
                st = time.time()
                print("starting")
                outputs = runtime.execute_code(
                    payload,
                    # output_hook=self._make_run_output_hook(),
                    # output_hook=print,
                    timeout=timeout
                )
                print("done", time.time() - st)
            except Exception:
                # Genuine transport-level failure. Cleanup still happens via the
                # outer finally; surface non-zero exit so callers/CI notice.
                exit_code = 1
                cleanup_reason = "run_failed"
                raise
            else:
                exit_code = self._exit_code_from_outputs(outputs)
                if exit_code != 0:
                    cleanup_reason = "run_failed"
                state.history.log_event(
                    name,
                    "execution",
                    {"code": payload, "outputs": outputs, "via": "run"},
                )
        finally:
            s.running = None
            state.store.add(s)
            # Best-effort runtime close (keeps remote kernel alive for --keep).
            try:
                runtime.stop()
            except Exception:
                pass

            if not keep:
                self._teardown(name, s, reason=cleanup_reason)

        if exit_code != 0:
            raise RuntimeError(f"Error exit code: {exit_code}")

if __name__ == "__main__":
    from pathlib import Path
    colab = ColabWorker(access_token=os.environ['IANTIRTA_COLAB_USER_TOKEN'])
    colab.test_connection()
    colab.run((Path(__file__).parent / 'worker_mixin.py').as_posix())
    # colab.run(__file__)