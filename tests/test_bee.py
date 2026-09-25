import unittest

from hivemind.ui.bee_frames import SEQUENCES, TICK_MS, frame_for


class BeeFramesTest(unittest.TestCase):
    def test_working_flaps_every_tick(self):
        frames = [frame_for("working", t)[0] for t in range(4)]
        self.assertEqual(frames, ["up", "down", "up", "down"])
        self.assertLessEqual(TICK_MS, 150)  # at least ~3 flaps per second

    def test_idle_bobs_and_sometimes_flaps(self):
        frames = [frame_for("idle", t)[0] for t in range(len(SEQUENCES["idle"]))]
        self.assertIn("low", frames)
        self.assertIn("down", frames)
        self.assertGreater(frames.count("up") + frames.count("low"), frames.count("down") * 3)

    def test_waiting_blinks(self):
        opacities = {frame_for("waiting", t)[1] for t in range(len(SEQUENCES["waiting"]))}
        self.assertEqual(len(opacities), 2)

    def test_error_and_unknown_are_still(self):
        self.assertEqual({frame_for("error", t) for t in range(20)}, {("up", 1.0)})
        self.assertEqual(frame_for("nope", 3), ("up", 1.0))

    def test_offset_desynchronises_bees(self):
        a = [frame_for("idle", t, offset=0) for t in range(40)]
        b = [frame_for("idle", t, offset=7) for t in range(40)]
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
