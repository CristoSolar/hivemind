import unittest
from datetime import datetime

from colmena.hub import Hub
from colmena.store import Store
from tests.test_hub import GB, ROLES, FakeTurn


def ts(*args):
    return datetime(*args).timestamp()


class RoutinesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeTurn.replies, FakeTurn.log, FakeTurn.gate = {}, [], None
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.notes = []
        self.hub = Hub(self.store, ROLES, turn_factory=FakeTurn,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                       notifier=lambda t, b: self.notes.append(t), save_config=lambda c: None)
        self.agent = self.hub.create_agent("Hori", "dev")

    def test_create_validates_and_computes_next_run(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"daily": "09:00"},
                                     now=ts(2026, 9, 25, 10, 0))
        self.assertEqual(r["next_run"], ts(2026, 9, 26, 9, 0))
        for bad in (dict(target="nadie"), dict(schedule={"daily": "25:00"}), dict(name=" "), dict(prompt="")):
            args = dict(name="R", target="group", prompt="p", schedule={"every_hours": 1}) | bad
            with self.assertRaises(ValueError):
                self.hub.routines.create(**args)

    async def test_missed_routine_runs_once_then_resumes(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 14, 30))  # machine was off for 6 h
        await self.hub.drain()
        await self.hub.routines.tick(now=ts(2026, 9, 25, 14, 31))
        await self.hub.drain()
        self.assertEqual([x for x in FakeTurn.log if x[1] == "start"], [("Hori", "start")])
        got = self.store.routine(r["id"])
        self.assertEqual((got["last_run"], got["next_run"]), (ts(2026, 9, 25, 14, 30), ts(2026, 9, 25, 15, 30)))
        self.assertTrue(self.store.history(self.agent["id"])[0]["content"].startswith("⏰ Rutina «Resumen»"))

    async def test_disabled_routine_never_runs(self):
        r = self.hub.routines.create("R", "group", "hola", {"every_hours": 1}, now=ts(2026, 9, 25, 8, 0))
        self.hub.routines.update(r["id"], enabled=False)
        await self.hub.routines.tick(now=ts(2026, 9, 26, 8, 0))
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])

    async def test_deleted_target_pauses_with_notice(self):
        r = self.hub.routines.create("R", self.agent["id"], "hola", {"every_hours": 1}, now=ts(2026, 9, 25, 8, 0))
        await self.hub.delete_agent(self.agent["id"])
        await self.hub.routines.tick(now=ts(2026, 9, 25, 10, 0))
        self.assertFalse(self.store.routine(r["id"])["enabled"])
        self.assertEqual(self.store.history("group")[-1]["author"], "system")

    async def test_notifies_when_no_window(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.run_now(r["id"])
        await self.hub.drain()
        self.assertEqual(self.notes, ["Rutina «Resumen» lista"])

    async def test_schedule_change_recomputes_next_run(self):
        r = self.hub.routines.create("R", "group", "hola", {"every_hours": 1}, now=ts(2026, 9, 25, 8, 0))
        got = self.hub.routines.update(r["id"], schedule={"daily": "09:00"}, now=ts(2026, 9, 25, 10, 0))
        self.assertEqual(got["next_run"], ts(2026, 9, 26, 9, 0))
        with self.assertRaises(ValueError):
            self.hub.routines.update(r["id"], schedule={"every_hours": 0})

    async def test_reenabling_waits_for_next_slot(self):
        r = self.hub.routines.create("R", "group", "hola", {"daily": "09:00"}, now=ts(2026, 9, 21, 8, 0))
        self.hub.routines.update(r["id"], enabled=False, now=ts(2026, 9, 21, 8, 30))
        got = self.hub.routines.update(r["id"], enabled=True, now=ts(2026, 9, 25, 15, 0))
        self.assertEqual(got["next_run"], ts(2026, 9, 26, 9, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 15, 1))
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])

    async def test_reenabling_with_deleted_target_is_rejected(self):
        r = self.hub.routines.create("R", self.agent["id"], "hola", {"every_hours": 1}, now=ts(2026, 9, 25, 8, 0))
        await self.hub.delete_agent(self.agent["id"])
        await self.hub.routines.tick(now=ts(2026, 9, 25, 10, 0))
        with self.assertRaises(ValueError):
            self.hub.routines.update(r["id"], enabled=True)

    def test_snapshot_includes_routines_and_tasks(self):
        self.hub.routines.create("R", "group", "hola", {"every_hours": 1})
        self.hub.board.create("Tarea")
        snap = self.hub.snapshot()
        self.assertEqual((len(snap["routines"]), len(snap["tasks"])), (1, 1))


if __name__ == "__main__":
    unittest.main()
