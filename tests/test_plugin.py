import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import tools.pixel_icons as px

ROOT = Path(__file__).resolve().parent.parent


class PluginTest(unittest.TestCase):
    def test_manifest(self):
        m = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual((m["schemaVersion"], m["id"], m["kinds"]), (1, "gogema.colmena", ["bar-widget"]))
        self.assertTrue((ROOT / m["entryPoints"]["barWidget"]).is_file())
        self.assertEqual(m["barWidget"]["defaultSection"], "right")

    @unittest.skipUnless(shutil.which("omarchy-plugin-validate"), "not on Omarchy")
    def test_omarchy_validate(self):
        # Validate what a user would clone: tracked files only (the dev .venv has symlinks).
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                   cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
            for f in files:
                if (ROOT / f).is_file():
                    (Path(d) / f).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / f, Path(d) / f)
            out = subprocess.run(["omarchy-plugin-validate", d], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_no_symlinks(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", ".superpowers", "build")]
            for name in dirnames + filenames:
                self.assertFalse(os.path.islink(os.path.join(dirpath, name)), name)

    def test_panel_uses_protocol_and_reconnects(self):
        qml = (ROOT / "Panel.qml").read_text()
        for needle in ('"hello"', '"approve"', "colmena.sock", "Timer", "SplitParser", "install.sh"):
            self.assertIn(needle, qml)

    def test_install_view_survives_until_install_finishes(self):
        qml = (ROOT / "Panel.qml").read_text()
        # The reconnect timer must not flip `installed` mid-install, and a failed install keeps its log.
        self.assertIn("if (!root.installing) probe.running = true", qml)
        self.assertIn("root.installFailed = exitCode !== 0", qml)
        self.assertIn("visible: root.installing || root.installFailed || (!root.connected && !root.installed)", qml)

    def test_panel_bee_matches_icon(self):
        qml = (ROOT / "Panel.qml").read_text()
        start = qml.index("BEE_MASK_START") + len("BEE_MASK_START\n")
        end = qml.index("BEE_MASK_END")
        rows = re.findall(r'"([#.]{16})"', qml[start:end])
        self.assertEqual("\n".join(rows), px.mask(px.BEE))


if __name__ == "__main__":
    unittest.main()
