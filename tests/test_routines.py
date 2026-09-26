import unittest
from datetime import datetime

from hivemind.hub import Hub
from hivemind.store import Store
from tests.test_hub import GB, ROLES, FakeTurn


def ts(*args):
    return datetime(*args).timestamp()


class RoutinesTest(unittest.IsolatedAsyncioTestCase):
    # An API key is the account that may run unattended turns; see Hub.automation_allowed.
    CONFIG = {"auth": "api_key", "api_key": "sk-test"}

    def setUp(self):
        FakeTurn.replies, FakeTurn.log, FakeTurn.gate = {}, [], None
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.notes = []
        self.hub = Hub(self.store, ROLES, turn_factory=FakeTurn,
                       meminfo=lambda: {"MemTotal": 32 * GB, "MemAvailable": 24 * GB},
                       notifier=lambda t, b: self.notes.append(t), save_config=lambda c: None,
                       config=self.CONFIG)
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


class SubscriptionRoutinesTest(RoutinesTest):
    """On a subscription a routine never fires itself: it waits for one human click."""

    CONFIG = {"auth": "subscription"}

    # inherited scheduling tests assume automation; only the waiting behaviour is checked here
    async def test_missed_routine_runs_once_then_resumes(self):
        pass

    async def test_due_routine_waits_instead_of_running(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 9, 1))
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])
        got = self.store.routine(r["id"])
        self.assertEqual(got["due_since"], ts(2026, 9, 25, 9, 1))
        self.assertEqual(got["next_run"], ts(2026, 9, 25, 10, 1))
        self.assertEqual(self.notes, ["«Resumen» te espera"])

    async def test_days_away_leave_one_pending_run(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        for hour in range(9, 20):  # away all day; the routine comes due every hour
            await self.hub.routines.tick(now=ts(2026, 9, 25, hour, 1))
        await self.hub.drain()
        self.assertEqual(self.store.routine(r["id"])["due_since"], ts(2026, 9, 25, 9, 1))
        self.assertEqual(len(self.notes), 1, "one notification, not one per missed slot")
        self.assertEqual(len(self.hub.routines.pending()), 1)

    async def test_clicking_run_clears_the_wait(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 9, 1))
        await self.hub.routines.run_now(r["id"])
        await self.hub.drain()
        self.assertEqual([x for x in FakeTurn.log if x[1] == "start"], [("Hori", "start")])
        self.assertIsNone(self.store.routine(r["id"])["due_since"])
        self.assertEqual(self.hub.routines.pending(), [])

    async def test_pending_survives_a_restart(self):
        self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                 now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 9, 1))
        self.notes.clear()  # the toast is long gone; the database mark is not
        self.hub.routines.notify_pending()
        self.assertEqual(self.notes, ["1 rutina(s) esperan tu OK"])

    async def test_skipping_drops_the_pending_run(self):
        r = self.hub.routines.create("Resumen", self.agent["id"], "resume", {"every_hours": 1},
                                     now=ts(2026, 9, 25, 8, 0))
        await self.hub.routines.tick(now=ts(2026, 9, 25, 9, 1))
        self.hub.routines.skip(r["id"])
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])
        got = self.store.routine(r["id"])
        self.assertIsNone(got["due_since"])
        self.assertEqual(got["next_run"], ts(2026, 9, 25, 10, 1), "the next slot still stands")
