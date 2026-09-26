"""Every test runs against scratch data and config folders, never the user's real HiveMind.

This package is imported before any test module, so the XDG variables are set before
anything computes a path. Scratch lives in ~/.cache/tmp (on small machines /tmp is RAM)."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_scratch = Path.home() / ".cache" / "tmp"
_scratch.mkdir(parents=True, exist_ok=True)
_root = tempfile.mkdtemp(prefix="hivemind-tests-", dir=_scratch)
os.environ["XDG_DATA_HOME"] = os.path.join(_root, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_root, "config")
atexit.register(shutil.rmtree, _root, ignore_errors=True)
