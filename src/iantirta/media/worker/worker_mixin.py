

import uuid
from abc import abstractmethod


class GPUWorker:

    def __init__(self, *, access_token: str,  name: str | None = None):
        self.access_token = access_token

        if not name:
            name = f'gpu_worker:{uuid.uuid4().hex[:6]}'
        self.name = name

    @abstractmethod
    def get_quota(self) -> dict:
        raise NotImplementedError()

    @abstractmethod
    def run(self, folder: str):
        raise NotImplementedError()


if __name__ == "__main__":
    import time
    # time.sleep(30)
    for i in range(100):
        print(i, "Hello World")
        time.sleep(2)