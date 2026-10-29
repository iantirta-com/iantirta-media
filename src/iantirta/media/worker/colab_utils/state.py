
import contextlib
import json
import logging
import os
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import IO, Any, Optional

import filelock

from iantirta.media import constants
from iantirta.media.worker.colab_utils.auth import (
    get_account_id,
    get_authorized_sessions,
    get_credentials,
)
from iantirta.media.worker.colab_utils.client import (
    HIGH_MEM_ONLY_ACCELERATORS,
    Accelerator,
    Client,
    ColabRequestError,
    RuntimeProxyInfo,
    Shape,
    TooManyAssignmentsError,
    Variant,
)
from iantirta.media.worker.colab_utils.kernel import Kernel
from iantirta.media.worker.colab_utils.runtime import ColabRuntime
from iantirta.media.worker.colab_utils.utils import get_status_code

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionState:
    name: str
    token: str
    url: str
    endpoint: str
    account_id: str
    _token_expires_at: float | None = None
    variant: str = "DEFAULT"
    accelerator: str = "NONE"
    machine_shape: str = "STANDARD"
    kernel_id: str | None = None
    session_id: str | None = None
    last_execution: tuple[str, str | None, str] | None = None
    running: str | None = None

    def __post_init__(self):
        if isinstance(self._token_expires_at, datetime):
            self._token_expires_at = self._token_expires_at.timestamp()

    @property
    def token_expires_at(self) -> datetime | None:
        if self._token_expires_at:
            return datetime.fromtimestamp(self._token_expires_at, tz=timezone.utc)
        return None

    @token_expires_at.setter
    def token_expires_at(self, value: datetime):
        self._token_expires_at = value.timestamp()


class _LockedFileStore:
    def __init__(self, path: str):
        self.path = path
        self.lock_path = f"{self.path}.lock"
        # ReadWriteLock gives us shared (concurrent) readers and exclusive
        # writers -- the cross-platform equivalent of fcntl LOCK_SH/LOCK_EX.
        # is_singleton=False keeps each store's lock independent: with the
        # default (True), two StateStore instances for the same path in one
        # process are merged into a single reentrant lock, whose reentrancy
        # guard then raises RuntimeError when two threads contend for the write
        # lock. We want them to actually serialize via the underlying file lock.
        self._rwlock = filelock.ReadWriteLock(self.lock_path, is_singleton=False)
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _write_data(self, f: IO, data: str):
        f.seek(0)
        f.truncate()
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    @contextlib.contextmanager
    def _lock_shared(self) -> Iterator[IO | None]:
        if not os.path.exists(self.path):
            yield None
            return
        with self._rwlock.read_lock(), open(self.path, "r") as f:
            yield f

    @contextlib.contextmanager
    def _lock_exclusive(self) -> Iterator[IO]:
        with self._rwlock.write_lock(), open(self.path, "a+") as f:
            yield f


class StateStore(_LockedFileStore):
    def __init__(self, path: str | None = None):
        if not path:
            path = constants.DEFAULT_COLAB_STATE_CONFIG_PATH.as_posix()
        super().__init__(path)

    def _load_raw(self, f) -> dict[str, SessionState]:
        try:
            f.seek(0)
            content = f.read()
            if not content or content.isspace():
                return {}
            data = json.loads(content)
            return {k: SessionState(**v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_raw(self, f, sessions: dict[str, SessionState]):
        content = json.dumps(
            {k: asdict(v) for k, v in sessions.items()}, indent=2
        )
        self._write_data(f, content)

    def add(self, state: SessionState):
        with self._lock_exclusive() as f:
            sessions = self._load_raw(f)
            sessions[state.name] = state
            self._save_raw(f, sessions)

    def get(self, name: str) -> SessionState | None:
        with self._lock_shared() as f:
            if f is None:
                return None
            sessions = self._load_raw(f)
            return sessions.get(name)

    def remove(self, name: str):
        with self._lock_exclusive() as f:
            sessions = self._load_raw(f)
            if name in sessions:
                del sessions[name]
                self._save_raw(f, sessions)

    def list(self) -> dict[str, SessionState]:
        with self._lock_shared() as f:
            if f is None:
                return {}
            return self._load_raw(f)


class HistoryLogger:
    def __init__(self, log_dir: str | None = None):
        if not log_dir:
            log_dir = constants.DEFAULT_COLAB_HISTORY_LOG_DIR.as_posix()
        self.log_dir = os.path.expanduser(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)

    def _get_log_path(self, session_name: str) -> str:
        return os.path.join(self.log_dir, f"{session_name}.jsonl")

    def log_event(self, session_name: str, event_type: str, data: dict[str, Any]):
        """
        Appends a structured event to the session's history file.

        event_types:
          - session_created
          - session_terminated
          - execution (code + outputs)
          - input_requested (stdin prompts/replies)
          - file_operation (ls, rm, upload, download)
          - automation (auth, install, drivemount)
        """
        log_path = self._get_log_path(session_name)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **data,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def list_sessions(self) -> list[str]:
        if not os.path.exists(self.log_dir):
            return []
        return [f[:-6] for f in os.listdir(self.log_dir) if f.endswith(".jsonl")]

    def get_history(self, session_name: str) -> list[dict[str, Any]]:
        log_path = self._get_log_path(session_name)
        if not os.path.exists(log_path):
            return []

        history = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    history.append(json.loads(line))
        return history


def _apply_proxy_info(s: SessionState, info: RuntimeProxyInfo, account_id: str):
    s.token = info.token
    s.url = info.url
    s.token_expires_at = info.expires_at()
    s.account_id = account_id


class State:
    _creds = None
    _store = None
    _history = None
    _client = None
    _kernel = None
    _auth_session = None

    def __init__(self, auth_session=None):
        self._auth_session = auth_session

    @property
    def kernel(self):
        if self._kernel is None:
            self._kernel = Kernel(self)
        return self._kernel

    @property
    def store(self):
        if self._store is None:
            self._store = StateStore()
        return self._store

    @property
    def history(self):
        if self._history is None:
            self._history = HistoryLogger()
        return self._history

    @property
    def creds(self):
        if self._creds is None:
            self._creds = get_credentials()
        return self._creds

    @property
    def client(self):
        if self._client is None:
            if not self._auth_session:
                self._auth_session = get_authorized_sessions(creds=self.creds)
            self._client = Client(self._auth_session)
        return self._client

    def prune_session(self, name: str):
        """Removes a session from local state."""
        self.store.remove(name)
        self.history.log_event(name, "session_terminated", {"reason": "pruned"})

    def get_sessions(self) -> dict[str, SessionState]:
        """Returns all sessions locally and server."""
        account_id = get_account_id(self.creds.token)
        local_sessions = self.store.list()
        server_sessions = self.client.list_assignments()

        _logger.debug(f"Server Assignment length: {len(server_sessions)}")
        local_by_endpoint = {s.endpoint: s for name, s in local_sessions.items()}
        for s in server_sessions:
            local_s = local_by_endpoint.get(s.endpoint)
            info = s.runtime_proxy_info
            metadata = {
                "variant": s.variant.name,
                "accelerator": s.accelerator.value,
                "machine_shape": Shape.HIGH_RAM.name if s.machine_shape == Shape.HIGH_RAM else Shape.STANDARD.name,
            }
            if local_s is None:
                _logger.debug("Local sessions is none but there is assignment records. creating local")
                name = f"Unknown - {uuid.uuid4().hex[:6]}"
                local_s = SessionState(
                    name=name,
                    token=info.token,
                    url=info.url,
                    _token_expires_at=info.expires_at(),
                    endpoint=s.endpoint,
                    account_id=account_id,
                    **metadata,
                )
                self.store.add(local_s)
                self.history.log_event(
                    name,
                    "session_forwarded",
                    {
                        "endpoint": local_s.endpoint,
                        "variant": local_s.variant,
                        "accelerator": local_s.accelerator,
                        "machine_shape": local_s.machine_shape,
                    },
                )
            else:
                _logger.debug(f"Local sessions existed updating data {local_s.name}")
                # update data
                _apply_proxy_info(local_s, info, account_id)
                local_s.variant = metadata["variant"]
                local_s.accelerator = metadata["accelerator"]
                local_s.machine_shape = metadata["machine_shape"]
                self.store.add(local_s)

        by_endpoint = {a.endpoint: a for a in server_sessions}
        pruned = 0
        for name, s in list(local_sessions.items()):
            if s.endpoint not in by_endpoint and s.account_id == account_id:
                self.prune_session(name)
                pruned += 1
            elif s.account_id == account_id:
                # Since we already update it earlier
                pass
            else:
                raise OSError("There is no way the account id could be different.")

        if pruned > 0:
            _logger.info(f"[colab] Pruned {pruned} stale local session(s).")

        return self.store.list()

    def get_session(self, name: str) -> SessionState:
        if not name:
            raise ValueError("`get_session` require session name")

        s = self.store.get(name)
        if s and (
            not s.token_expires_at
            or s.token_expires_at - datetime.now(timezone.utc) <= constants.DEFAULT_COLAB_TOKEN_REFRESH_MARGIN
        ):
            s = self.get_sessions().get(name)

        if not s:
            raise ValueError(f'Session {name} not found.')

        return s

    def resolve_session(self, name: str, **kwargs) -> SessionState:
        if not name:
            sess_keys = list(self.get_sessions().keys())
            if len(sess_keys) == 1:
                name = sess_keys[0]
            if len(sess_keys) > 1:
                raise ValueError('Error: Multiple sessions found, specify one with name')
            else:
                raise ValueError('Error: No active sessions found, create one')

        try:
            s = self.get_session(name)
        except ValueError:
            _logger.debug(f"Session {name} not found. creating new one")
            s = self.new_session(name, **kwargs)
        return s

    def new_session(
        self,
        name: str,
        *,
        gpu: str | None = None,
        tpu: str | None = None,
        high_mem: bool = False,
    ):
        if tpu:
            variant = Variant.TPU
            accelerator = Accelerator.V5E1 if tpu.lower() == "v5e1" else Accelerator.V6E1
        elif gpu:
            variant = Variant.GPU
            mapping = {
                "a100": Accelerator.A100,
                "h100": Accelerator.H100,
                "l4": Accelerator.L4,
                "t4": Accelerator.T4,
                "g4": Accelerator.G4,
            }
            accelerator = mapping.get(gpu.lower(), Accelerator.A100)
        else:
            variant = Variant.DEFAULT
            accelerator = Accelerator.NONE

        if not high_mem or accelerator in HIGH_MEM_ONLY_ACCELERATORS:
            shape = None
        else:
            shape = Shape.HIGH_RAM
    
        account_id = get_account_id(self.creds.token)

        try:
            res = self.client.assign(
                notebook_hash=uuid.uuid4(),
                variant=variant,
                accelerator=accelerator,
                shape=shape
            )
        except TooManyAssignmentsError:
            raise TooManyAssignmentsError(
                "[colab] Allocation refused (precondition failed). This can mean "
                "too many active sessions, or a temporary usage or capacity "
                "limit for the requested runtime. Run `colab stop` to free up a "
                "session, wait and retry, or try a different accelerator."
            )
        except ColabRequestError as e:
            # The Colab backend returns 400 when the caller is not entitled to the
            # requested accelerator (e.g. no A100 quota). Translate that to a
            # friendly, actionable message instead of a raw traceback. We only
            # interpret it this way when an accelerator was actually requested;
            # otherwise we re-raise so the user sees the real cause.
            if get_status_code(e) == 400 and accelerator != Accelerator.NONE:
                raise RuntimeError(
                    f"[colab] Backend rejected accelerator '{accelerator.value}'. "
                    "You may not have quota or entitlement for this accelerator on "
                    "your account. Try a different one (e.g. --gpu T4) or omit "
                    "--gpu/--tpu for a CPU runtime."
                )
            raise

        token = res.runtime_proxy_info.token
        url = res.runtime_proxy_info.url
        endpoint = res.endpoint

        s = SessionState(
            name=name,
            token=token,
            url=url,
            account_id=account_id,
            endpoint=endpoint,
            _token_expires_at=res.runtime_proxy_info.expires_at(),
            variant=variant.value,
            accelerator=accelerator.value,
            machine_shape=(
                Shape.HIGH_RAM.name if shape == Shape.HIGH_RAM else Shape.STANDARD.name
            ),
        )
        self.store.add(s)
        self.history.log_event(
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

    def stop_session(self, name: str, *, reason: str = 'close'):
        s = self.get_session(name)
        _logger.info(f"[colab] Stopping session '{name}'...")
        try:
            rt = ColabRuntime(s.url, s.token, kernel_id=s.kernel_id)
            rt.stop(shutdown_kernel=True)
        except Exception:
            pass

        self.client.unassign(s.endpoint)
        self.store.remove(name)
        self.history.log_event(
            name, "session_terminated",
            {"reason": reason}
        )

        _logger.info("[colab] Session terminated.")


state = State()


if __name__ == '__main__':
    from iantirta.telemetry import netsvc
    netsvc.setup_logger(__name__, default_level=logging.DEBUG)
    from pprint import pprint
    pprint(state.resolve_session('any'))