import unittest

from hivemind.ui.bee_frames import SEQUENCES, SLEEP_AFTER, TICK_MS, animation, frame_for


class BeeFramesTest(unittest.TestCase):
    def frames(self, key, n=None):
        return [frame_for(key, t)[0] for t in range(n or len(SEQUENCES[key]))]

    def test_tool_flaps_every_tick(self):
        self.assertEqual(self.frames("tool", 4), ["up", "down", "up", "down"])
        self.assertLessEqual(TICK_MS, 150)

    def test_thinking_wears_glasses_and_flaps_slowly(self):
        frames = self.frames("thinking")
        self.assertEqual(set(frames), {"think-up", "think-down"})
        self.assertGreater(len(frames), 4)  # slower than tool

    def test_idle_bobs_and_sometimes_flaps(self):
        frames = self.frames("idle")
        self.assertIn("low", frames)
        self.assertIn("down", frames)

    def test_sleeping_breathes_with_zzz(self):
        self.assertEqual(set(self.frames("sleeping")), {"sleep-1", "sleep-2"})

    def test_waiting_blinks_with_bang(self):
        self.assertEqual({frame_for("waiting", t) for t in range(len(SEQUENCES["waiting"]))},
                         {("wait", 1.0), ("wait", 0.35)})

    def test_error_and_unknown_are_still(self):
        self.assertEqual({frame_for("error", t) for t in range(20)}, {("error", 1.0)})
        self.assertEqual(frame_for("nope", 3), ("up", 1.0))

    def test_offset_desynchronises_bees(self):
        self.assertNotEqual([frame_for("idle", t, 0) for t in range(40)], [frame_for("idle", t, 7) for t in range(40)])

    def test_animation_picks_state(self):
        self.assertEqual(SLEEP_AFTER, 300)
        self.assertEqual(animation("working", "thinking", 0), "thinking")
        self.assertEqual(animation("working", "tool", 0), "tool")
        self.assertEqual(animation("working", None, 0), "tool")
        self.assertEqual(animation("idle", None, 10), "idle")
        self.assertEqual(animation("idle", None, 300), "sleeping")
        self.assertEqual(animation("waiting", "tool", 999), "waiting")
        self.assertEqual(animation("queued", None, 999), "queued")
        self.assertEqual(animation("error", None, 999), "error")


if __name__ == "__main__":
    unittest.main()
