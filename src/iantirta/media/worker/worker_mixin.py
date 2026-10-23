

from abc import abstractmethod


class GPUWorker:

    def __init__(self, *, access_token: str):
        self.access_token = access_token

    @abstractmethod
    def get_quota(self) -> dict:
        raise NotImplementedError()

    @abstractmethod
    def run(self, folder: str):
        raise NotImplementedError()


if __name__ == "__main__":
    import time
    time.sleep(30)