import os
import tempfile
import unittest

from hivemind import capacity

GB = 1024 * 1024  # kB


class CapacityTest(unittest.TestCase):
    def test_parse_meminfo(self):
        mem = capacity.parse_meminfo("MemTotal:  32000000 kB\nMemAvailable: 20000000 kB\nHugePages_Total: 0\n")
        self.assertEqual(mem["MemTotal"], 32000000)
        self.assertEqual(mem["MemAvailable"], 20000000)

    def test_formula_big_machine(self):
        mem = {"MemTotal": 32 * GB, "MemAvailable": 24 * GB}
        # reserve = 15% of 32 GB = 4.8 GB; (24 - 4.8) GB / 600 MB = 32.7
        self.assertEqual(capacity.max_running(mem, 600), 32)

    def test_formula_small_machine_uses_min_reserve(self):
        mem = {"MemTotal": 8 * GB, "MemAvailable": 4 * GB}
        # reserve = max(1.5 GB, 1.2 GB) = 1.5 GB; 2.5 GB / 600 MB = 4.2
        self.assertEqual(capacity.max_running(mem, 600), 4)

    def test_never_below_one(self):
        mem = {"MemTotal": 8 * GB, "MemAvailable": 1 * GB}
        self.assertEqual(capacity.max_running(mem, 600), 1)

    def test_override(self):
        mem = {"MemTotal": 8 * GB, "MemAvailable": 1 * GB}
        self.assertEqual(capacity.max_running(mem, 600, override=3), 3)

    def test_descendants_rss(self):
        with tempfile.TemporaryDirectory() as proc:
            def mk(pid, ppid, rss):
                os.makedirs(f"{proc}/{pid}")
                with open(f"{proc}/{pid}/stat", "w") as f:
                    f.write(f"{pid} (x y) S {ppid} 0 0\n")
                with open(f"{proc}/{pid}/status", "w") as f:
                    f.write(f"Name:\tx\nVmRSS:\t{rss} kB\n")
            mk(10, 1, 100)   # daemon
            mk(11, 10, 200)  # child
            mk(12, 11, 300)  # grandchild
            mk(13, 1, 999)   # unrelated
            self.assertEqual(capacity.descendants_rss_kb(10, proc), 500)

    def test_ema(self):
        self.assertAlmostEqual(capacity.ema(600, 1000), 720)


if __name__ == "__main__":
    unittest.main()
