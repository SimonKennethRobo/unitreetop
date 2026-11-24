"""unitreetop - jtop-style monitor for Unitree robots."""
__version__ = "0.1.0"

from . import _sdk  # noqa: E402,F401  (puts the bundled SDK on sys.path before anything imports it)
from .core import UnitreeTop  # noqa: E402

__all__ = ["UnitreeTop", "__version__"]
