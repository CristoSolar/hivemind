import os
import tomllib
from pathlib import Path


def _xdg(var, fallback):
    return Path(os.environ.get(var) or Path.home() / fallback)


def data_dir():
    return _xdg("XDG_DATA_HOME", ".local/share") / "colmena"


def config_dir():
    return _xdg("XDG_CONFIG_HOME", ".config") / "colmena"


def socket_path():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "colmena.sock"


def load_config():
    path = config_dir() / "config.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}
