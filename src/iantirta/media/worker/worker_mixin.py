

import uuid
from abc import abstractmethod
from typing import Any


class GPUWorker:
    """
    Base class mixin for GPU Worker

    :param str access_token:
    :param str | None name:
    """

    def __init__(self, *, access_token: str,  name: str | None = None):
        self.access_token = access_token

        if not name:
            name = f'gpu_worker:{uuid.uuid4().hex[:6]}'
        self.name = name

    @abstractmethod
    def get_quota(self) -> dict[str, Any]:
        """
        Fetch quota or usage for the worker.

        Provider method should override this.

        :rtype: dict[str, Any]
        """
        raise NotImplementedError()

    @abstractmethod
    def run(self, path_or_dir: str, **kwargs):
        """
        Run worker given any path / dir path.

        Provider method should override this.

        :param str path_or_dir:
        """
        raise NotImplementedError()
