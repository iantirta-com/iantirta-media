
from abc import abstractmethod
from pathlib import Path
import logging


_logger = logging.getLogger(__name__)


class StorageMixin:

    def __init__(
        self,
        *,
        access_token: str,
        logger: logging.Logger | None = None
    ):
        self.access_token = access_token

        self.logger = logger or _logger

    @abstractmethod
    def test_connection(self):
        raise NotImplementedError()

    @abstractmethod
    def upload_file(
        self,
        *
        src_path: str | Path,
        target_path: str | Path,
        logger: logging.Logger | None = None
    ) -> list[str]:
        raise NotImplementedError()