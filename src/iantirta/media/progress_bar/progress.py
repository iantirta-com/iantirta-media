from contextlib import AbstractContextManager, nullcontext

from ._tqdm import tqdm

__all__ = [
    "create_progress_bar",
    "get_context_progressbar"
]


def create_progress_bar(
    *,
    cls: type[tqdm],
    log_level: int,
    name: str | None = None,
    **kwargs
) -> tqdm:
    """Create a progress bar.
    """
    # issubclass() crashes on non-class callables (e.g. functools.partial), guard with isinstance.
    if not (isinstance(cls, type) and issubclass(cls, tqdm)):
        return cls(**kwargs)  # type: ignore[return-value]

    return cls(**kwargs)  # type: ignore[return-value]


def get_context_progressbar(
    *,
    desc: str,
    log_level: int,
    total: int | None = None,
    initial: int = 0,
    unit: str = "B",
    unit_scale: bool = True,
    name: str | None = None,
    tqdm_class: type[tqdm] | None = None,
    _tqdm_bar: tqdm | None = None,
) -> AbstractContextManager[tqdm]:
    if _tqdm_bar is not None:
        return nullcontext(_tqdm_bar)
        # ^ `contextlib.nullcontext` mimics a context manager that does nothing
        #   Makes it easier to use the same code path for both cases but in the later
        #   case, the progress bar is not closed when exiting the context manager.
    
    return create_progress_bar(  # type: ignore
        cls=tqdm_class or tqdm,
        log_level=log_level,
        name=name,
        unit=unit,
        unit_scale=unit_scale,
        total=total,
        initial=initial,
        desc=desc,
    )
