# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.
"""Media Utility."""

from importlib.metadata import version
from typing import TYPE_CHECKING

from iantirta.lazy_import import LazyModule, define_import_structure

__version__ = version("iantirta-media")


if TYPE_CHECKING:
    from ._http import *
    from .song_lyrics import *
    from .video import *
else:
    import sys
    
    _file = globals()["__file__"]
    sys.modules[__name__] = LazyModule(
        __name__,
        _file,
        define_import_structure(_file),
        module_spec=__spec__,
        extra_objects={"__version__": __version__},
    )
