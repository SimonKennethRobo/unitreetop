"""Use the bundled unitree_sdk2_python (git submodule) so a checkout is self-contained.

Resolution order:
  1. ``UNITREETOP_SDK=system``  -> use whatever ``unitree_sdk2py`` is installed
  2. ``third_party/unitree_sdk2_python`` present (submodule checked out) -> bundled copy
  3. otherwise the installed package (e.g. a non-editable pip install of unitreetop)

The CycloneDDS Python binding (``cyclonedds==0.10.x``) is still an external dependency.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(ROOT, "third_party", "unitree_sdk2_python")


def setup():
    if os.environ.get("UNITREETOP_SDK", "").lower() == "system":
        return "system"
    if os.path.isdir(os.path.join(BUNDLED, "unitree_sdk2py")):
        if BUNDLED not in sys.path:
            sys.path.insert(0, BUNDLED)
        return "bundled"
    return "system"


SOURCE = setup()


def describe():
    """Where unitree_sdk2py was (or will be) imported from, for the INFO page."""
    mod = sys.modules.get("unitree_sdk2py")
    path = os.path.dirname(mod.__file__) if mod is not None and getattr(mod, "__file__", None) else ""
    return "{}{}".format(SOURCE, " ({})".format(path) if path else "")
