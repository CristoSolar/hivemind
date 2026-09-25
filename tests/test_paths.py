import os
import stat
import tempfile
import unittest
from unittest import mock

from colmena import paths


class PathsTest(unittest.TestCase):
    def test_save_config_round_trip_private(self):
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            cfg = {"auth": "api_key", "api_key": 'sk-"raro"\\x', "max_running": 3}
            paths.save_config(cfg)
            self.assertEqual(paths.load_config(), cfg)
            mode = stat.S_IMODE(os.stat(paths.config_dir() / "config.toml").st_mode)
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
