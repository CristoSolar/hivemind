import time
from datetime import datetime

from hivemind.schedule import next_run, validate


class Routines:
    def __init__(self, hub):
        self.hub = hub

    @property
    def store(self):
        return self.hub.store

    def _changed(self):
        self.hub.broadcast({"type": "routines", "routines": self.list()})

    def _target_exists(self, target):
        return target == "group" or self.store.group(target) is not None or self.store.agent(target) is not None

    def pause_target(self, target):
        for r in self.store.routines():
            if r["target"] == target and r["enabled"]:
                self.store.update_routine(r["id"], enabled=False)
                self.hub._post("group", "system", "system", f"La rutina «{r['name']}» se pausó: su destino ya no existe.")
        self._changed()

    def _check_target(self, target):
        if not self._target_exists(target):
            raise ValueError("La rutina debe ir a un grupo o a un agente que exista.")

    @staticmethod
    def _next(schedule, now):
        return next_run(schedule, datetime.fromtimestamp(now)).timestamp()

    def list(self):
        return self.store.routines()

    def create(self, name, target, prompt, schedule, now=None):
        name, prompt = (name or "").strip(), (prompt or "").strip()
        if not name or not prompt:
            raise ValueError("La rutina necesita nombre e instrucción.")
        self._check_target(target)
        schedule = validate(schedule)
        r = self.store.create_routine(name, target, prompt, schedule, self._next(schedule, now or time.time()))
        self._changed()
        return r

    def update(self, routine_id, now=None, **fields):
        current = self.store.routine(routine_id)
        if current is None:
            raise ValueError("Esa rutina no existe.")
        changes = {}
        for key in ("name", "prompt"):
            if key in fields:
                value = (fields[key] or "").strip()
                if not value:
                    raise ValueError("La rutina necesita nombre e instrucción.")
                changes[key] = value
        if "target" in fields:
            self._check_target(fields["target"])
            changes["target"] = fields["target"]
        if "schedule" in fields:
            changes["schedule"] = validate(fields["schedule"])
            changes["next_run"] = self._next(changes["schedule"], now or time.time())
        if "enabled" in fields:
            changes["enabled"] = bool(fields["enabled"])
            if changes["enabled"] and not current["enabled"]:
                # Waking up a paused routine: its old next_run is in the past, so do not fire it at once.
                self._check_target(changes.get("target", current["target"]))
                schedule = changes.get("schedule", current["schedule"])
                changes["next_run"] = self._next(schedule, now or time.time())
        self.store.update_routine(routine_id, **changes)
        self._changed()
        return self.store.routine(routine_id)

    def delete(self, routine_id):
        self.store.delete_routine(routine_id)
        self._changed()

    async def _fire(self, r, now, reschedule):
        if not self._target_exists(r["target"]):
            self.store.update_routine(r["id"], enabled=False)
            self.hub._post("group", "system", "system",
                           f"La rutina «{r['name']}» se pausó: su agente ya no existe.")
            self._changed()
            return
        fields = {"last_run": now, "due_since": None}
        if reschedule:
            fields["next_run"] = self._next(r["schedule"], now)
        self.store.update_routine(r["id"], **fields)
        await self.hub.send(r["target"], f"⏰ Rutina «{r['name']}»: {r['prompt']}",
                            origin={"routine": r["name"]})
        self._changed()

    def skip(self, routine_id):
        """Drop a pending run without firing it; the next slot is already scheduled."""
        r = self.store.routine(routine_id)
        if r is None:
            raise ValueError("Esa rutina no existe.")
        self.store.update_routine(routine_id, due_since=None)
        self._changed()

    async def run_now(self, routine_id):
        r = self.store.routine(routine_id)
        if r is None:
            raise ValueError("Esa rutina no existe.")
        await self._fire(r, time.time(), reschedule=False)

    def _defer(self, r, now):
        """Subscription account: the routine waits for one click instead of running itself."""
        if not self._target_exists(r["target"]):
            self.store.update_routine(r["id"], enabled=False)
            self.hub._post("group", "system", "system",
                           f"La rutina «{r['name']}» se pausó: su agente ya no existe.")
            self._changed()
            return
        fields = {"next_run": self._next(r["schedule"], now)}
        if r["due_since"] is None:  # already waiting: one pending run, never a pile
            fields["due_since"] = now
            self.hub.notifier(f"«{r['name']}» te espera",
                              "Ábrela en HiveMind y pulsa Correr.")
        self.store.update_routine(r["id"], **fields)
        self._changed()

    def pending(self):
        return [r for r in self.store.routines() if r["enabled"] and r["due_since"]]

    def notify_pending(self):
        """After a restart the notification is long gone; the mark in the database is not."""
        waiting = self.pending()
        if waiting:
            names = ", ".join(f"«{r['name']}»" for r in waiting[:3])
            self.hub.notifier(f"{len(waiting)} rutina(s) esperan tu OK", names)

    async def tick(self, now=None):
        now = now or time.time()
        for r in self.store.routines():
            if r["enabled"] and r["next_run"] <= now:
                if self.hub.automation_allowed():
                    await self._fire(r, now, reschedule=True)
                else:
                    self._defer(r, now)
