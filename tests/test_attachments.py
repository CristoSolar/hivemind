import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hivemind import attachments as att


class AttachmentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp"))
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(att, "root", lambda: self.dir / "adjuntos")
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, name, size=10):
        p = self.dir / name
        p.write_bytes(b"x" * size)
        return str(p)

    def test_kinds(self):
        self.assertEqual([att.kind_of(n) for n in ("a.png", "b.JPG", "c.pdf", "d.md", "e.m4a", "f.ogg", "g.bin")],
                         ["imagen", "imagen", "documento", "documento", "audio", "audio", "archivo"])

    def test_store_copies_under_thread_with_safe_names(self):
        src = self.make("mi captura (1).png")
        [entry] = att.store([src], "g-1")
        self.assertEqual((entry["name"], entry["kind"], entry["size"]), ("mi captura (1).png", "imagen", 10))
        stored = Path(entry["path"])
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.parent, self.dir / "adjuntos" / "g-1")
        self.assertNotIn(" ", stored.name)
        os.remove(src)
        self.assertTrue(stored.is_file())  # the message keeps its copy

    def test_rejects_bad_input_and_copies_nothing(self):
        good = self.make("ok.txt")
        big = self.make("big.bin", att.MAX_BYTES + 1)
        cases = ([str(self.dir / "no-existe.pdf")], [str(self.dir)], [good, big], [good] * (att.MAX_FILES + 1))
        for paths in cases:
            with self.assertRaises(ValueError):
                att.store(paths, "t")
        self.assertFalse((self.dir / "adjuntos" / "t").exists())

    def test_remove_thread(self):
        att.store([self.make("a.txt")], "t")
        att.remove_thread("t")
        self.assertFalse((self.dir / "adjuntos" / "t").exists())
        att.remove_thread("nunca-existió")  # no error

    def test_prompt_lines(self):
        entries = [{"name": "a.png", "path": "/r/a.png", "kind": "imagen", "size": 1, "transcript": None},
                   {"name": "n.m4a", "path": "/r/n.m4a", "kind": "audio", "size": 1, "transcript": "hola equipo"}]
        self.assertEqual(att.prompt_lines(entries),
                         "Adjuntos (ábrelos con la herramienta Read):\n- imagen: /r/a.png\n"
                         "- audio: /r/n.m4a — transcripción: «hola equipo»")
        self.assertEqual(att.prompt_lines([]), "")

    def test_transcribe_without_voxtype_returns_none(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(asyncio.run(att.transcribe(self.make("n.m4a"))))


if __name__ == "__main__":
    unittest.main()
