import json
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


def save_config(cfg):
    """Write config.toml readable only by the user: it may hold an API key."""
    path = config_dir() / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k} = {json.dumps(v)}" for k, v in cfg.items() if v is not None]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def load_config():
    path = config_dir() / "config.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}
