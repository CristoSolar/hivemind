import os
import unittest
from pathlib import Path

from hivemind import attachments, paths

REAL_DATA = Path.home() / ".local" / "share" / "hivemind"
REAL_CONFIG = Path.home() / ".config" / "hivemind"


class IsolationTest(unittest.TestCase):
    """The suite must never read or delete the user's real HiveMind data."""

    def test_data_and_config_point_to_a_scratch_folder(self):
        for path in (paths.data_dir(), attachments.root(), paths.config_dir()):
            self.assertFalse(Path(path).resolve().is_relative_to(REAL_DATA.resolve()), path)
            self.assertFalse(Path(path).resolve().is_relative_to(REAL_CONFIG.resolve()), path)
        self.assertTrue(paths.data_dir().resolve().is_relative_to((Path.home() / ".cache" / "tmp").resolve()))


if __name__ == "__main__":
    unittest.main()
