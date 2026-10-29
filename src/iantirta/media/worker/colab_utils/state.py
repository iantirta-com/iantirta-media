
import contextlib
import json
import os
from datetime import datetime
from typing import Dict, Optional, Tuple, Iterator, IO

import filelock

from iantirta.media import constants
from iantirta.media.worker.colab_utils.auth import get_credentials, get_authorized_sessions


class _LockedFileStore:
    def __init__(self, path: str):
        self.path = path
        self.lock_path = "%s.lock" % self.path
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
    def _lock_shared(self) -> Iterator[Optional[IO]]:
        if not os.path.exists(self.path):
            yield None
            return
        with self._rwlock.read_lock():
            with open(self.path, "r") as f:
                yield f

    @contextlib.contextmanager
    def _lock_exclusive(self) -> Iterator[IO]:
        with self._rwlock.write_lock():
            with open(self.path, "a+") as f:
                yield f


class StateStore(_LockedFileStore):
    def __init__(self, path: Optional[str] = None):
        if not path:
            path = constants.DEFAULT_COLAB_STATE_CONFIG_PATH.as_posix()
        super().__init__(path)

    def _load_raw(self, f) -> Dict[str, SessionState]:
        try:
            f.seek(0)
            content = f.read()
            if not content or content.isspace():
                return {}
            data = json.loads(content)
            return {k: SessionState(**v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_raw(self, f, sessions: Dict[str, SessionState]):
        content = json.dumps(
            {k: v.model_dump(mode="json") for k, v in sessions.items()}, indent=2
        )
        self._write_data(f, content)

    def add(self, state: SessionState):
        with self._lock_exclusive() as f:
            sessions = self._load_raw(f)
            sessions[state.name] = state
            self._save_raw(f, sessions)

    def get(self, name: str) -> Optional[SessionState]:
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

    def list(self) -> Dict[str, SessionState]:
        with self._lock_shared() as f:
            if f is None:
                return {}
            return self._load_raw(f)


class State:
    _store = None
    _client = None
    
    @property
    def store(self):
        if self._store is None:
            self._store = StateStore()
        return self._store

    @property
    def client(self):
        if self._client is None:
            creds = get_credentials()
            auth_sessions = get_authorized_sessions(creds=creds)
            self._client = Client(auth_sessions)
        return self._client

state = State()


if __name__ == '__main__':
    from pprint import pprint
    pprint(state.store.list())