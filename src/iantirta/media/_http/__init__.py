# Part of Iantirta.com
# See LICENSE file for full copyright and licensing details.

from typing import TYPE_CHECKING

from iantirta.lazy_import import LazyModule, define_import_structure

if TYPE_CHECKING:
    from ._http import *
else:
    import sys
    
    _file = globals()["__file__"]
    sys.modules[__name__] = LazyModule(
        __name__,
        _file,
        define_import_structure(_file),
        module_spec=__spec__,
    )
