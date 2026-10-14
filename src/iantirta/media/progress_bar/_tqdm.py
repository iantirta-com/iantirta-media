import sys


class _FallbackTqdm:
    def __init__(self, *args, **kwargs):
        self.n = 0

    def update(self, n: int, *args, **kwargs):
        self.n += n
        sys.stderr.write(f"\r[ ]: {self.n}")
        sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return

    def format_sizeof(self, *args, **kwargs):
        return "Unknown"


try:
    from tqdm import tqdm
except ImportError:
    tqdm = _FallbackTqdm
