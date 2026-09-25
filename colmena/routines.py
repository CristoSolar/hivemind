import time
from datetime import datetime

from colmena.schedule import next_run, validate


class Routines:
    def __init__(self, hub):
        self.hub = hub

    @property
    def store(self):
        return self.hub.store

    def _changed(self):
        self.hub.broadcast({"type": "routines", "routines": self.list()})

    def _check_target(self, target):
        if target != "group" and self.store.agent(target) is None:
            raise ValueError("La rutina debe ir al Grupo o a un agente que exista.")

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
        if self.store.routine(routine_id) is None:
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
        self.store.update_routine(routine_id, **changes)
        self._changed()
        return self.store.routine(routine_id)

    def delete(self, routine_id):
        self.store.delete_routine(routine_id)
        self._changed()

    async def _fire(self, r, now, reschedule):
        if r["target"] != "group" and self.store.agent(r["target"]) is None:
            self.store.update_routine(r["id"], enabled=False)
            self.hub._post("group", "system", "system",
                           f"La rutina «{r['name']}» se pausó: su agente ya no existe.")
            self._changed()
            return
        fields = {"last_run": now}
        if reschedule:
            fields["next_run"] = self._next(r["schedule"], now)
        self.store.update_routine(r["id"], **fields)
        await self.hub.send(r["target"], f"⏰ Rutina «{r['name']}»: {r['prompt']}",
                            origin={"routine": r["name"]})
        self._changed()

    async def run_now(self, routine_id):
        r = self.store.routine(routine_id)
        if r is None:
            raise ValueError("Esa rutina no existe.")
        await self._fire(r, time.time(), reschedule=False)

    async def tick(self, now=None):
        now = now or time.time()
        for r in self.store.routines():
            if r["enabled"] and r["next_run"] <= now:
                await self._fire(r, now, reschedule=True)
