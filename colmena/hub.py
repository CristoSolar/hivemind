import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from collections import deque

from colmena import capacity
from colmena.router import CONTEXT_MESSAGES, MAX_HOPS, NAME_RE, mentions
from colmena.runner import Turn


def notify(title, body):
    try:
        subprocess.Popen(["notify-send", "-a", "Colmena", title, body])
    except OSError:
        pass


class Hub:
    def __init__(self, store, roles, turn_factory=Turn, meminfo=capacity.read_meminfo,
                 config=None, notifier=notify):
        self.store, self.roles = store, roles
        self.turn_factory, self.meminfo, self.notifier = turn_factory, meminfo, notifier
        self.config = config or {}
        self.clients = []
        self.queue = deque()        # (agent_id, thread, prompt)
        self.running = {}           # agent_id -> (Turn, asyncio.Task)
        self.pending = {}           # approval_id -> (agent_id, Future)
        self.statuses = {a["id"]: "idle" for a in store.agents()}
        self.hops = 0
        self.per_turn_mb = float(store.get("per_turn_mb", capacity.DEFAULT_PER_TURN_MB))

    # events -----------------------------------------------------------------
    def subscribe(self, fn):
        self.clients.append(fn)

    def unsubscribe(self, fn):
        if fn in self.clients:
            self.clients.remove(fn)

    def broadcast(self, event):
        for fn in list(self.clients):
            fn(event)

    def _status(self, agent_id, status):
        self.statuses[agent_id] = status
        self.broadcast({"type": "status", "agent": agent_id, "status": status})

    def _post(self, thread, author, kind, content):
        self.broadcast({"type": "message", "message": self.store.add_message(thread, author, kind, content)})

    def max_running(self):
        return capacity.max_running(self.meminfo(), self.per_turn_mb, self.config.get("max_running"))

    def _capacity(self):
        return {"running": len(self.running), "max": self.max_running()}

    def snapshot(self):
        return {"agents": self.store.agents(), "roles": self.roles, "statuses": self.statuses,
                "approvals": self.store.approvals(), "capacity": self._capacity()}

    # agents -----------------------------------------------------------------
    def create_agent(self, name, role, cwd=None):
        if not NAME_RE.match(name or ""):
            raise ValueError("El nombre solo puede tener letras, números, guiones y guiones bajos.")
        if role not in self.roles:
            raise ValueError(f"No existe el rol «{role}».")
        cwd = os.path.expanduser(cwd or self.roles[role]["cwd"])
        if not os.path.isdir(cwd):
            raise ValueError(f"La carpeta {cwd} no existe.")
        try:
            agent = self.store.create_agent(name, role, cwd)
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya existe un agente llamado «{name}».") from None
        self.statuses[agent["id"]] = "idle"
        self.broadcast({"type": "agents", "agents": self.store.agents()})
        return agent

    async def delete_agent(self, agent_id):
        await self.stop(agent_id)
        entry = self.running.get(agent_id)
        if entry:
            await asyncio.gather(entry[1], return_exceptions=True)
        self.store.delete_agent(agent_id)
        self.statuses.pop(agent_id, None)
        self.broadcast({"type": "agents", "agents": self.store.agents()})

    # messages ---------------------------------------------------------------
    async def send(self, thread, text):
        self._post(thread, "user", "text", text)
        if thread == "group":
            self.hops = 0
            self._route(text, author=None)
        elif self.store.agent(thread):
            self._enqueue(thread, thread, text)

    def _route(self, text, author):
        agents = self.store.agents()
        me = next((a["name"] for a in agents if a["id"] == author), None)
        known, unknown = mentions(text, [a["name"] for a in agents], exclude=me)
        if unknown:
            self._post("group", "system", "system", "No hay agentes llamados: " + ", ".join("@" + u for u in unknown))
        if not known:
            return
        if author is not None:
            if self.hops >= MAX_HOPS:
                self._post("group", "system", "system",
                           f"Se alcanzó el límite de {MAX_HOPS} pases entre agentes. Escribe para continuar.")
                return
            self.hops += 1
        prompt = self._group_prompt()
        for a in agents:
            if a["name"] in known:
                self._enqueue(a["id"], "group", prompt)

    def _group_prompt(self):
        names = {a["id"]: a["name"] for a in self.store.agents()}
        lines = []
        for m in self.store.history("group", limit=CONTEXT_MESSAGES):
            who = {"user": "Usuario", "system": "Sistema"}.get(m["author"]) or names.get(m["author"], "?")
            lines.append(f"[{who}]: {m['content']}")
        return ("Mensajes recientes del chat grupal de Colmena. Te mencionaron en el último. "
                "Tu respuesta se publicará en el grupo.\n\n" + "\n".join(lines))

    # queue ------------------------------------------------------------------
    def _enqueue(self, agent_id, thread, prompt):
        self.queue.append((agent_id, thread, prompt))
        if agent_id not in self.running:
            self._status(agent_id, "queued")
        self._pump()

    def _pump(self):
        limit = self.max_running()
        for item in list(self.queue):
            if len(self.running) >= limit:
                break
            agent_id = item[0]
            if agent_id in self.running:
                continue
            self.queue.remove(item)
            agent = self.store.agent(agent_id)
            if agent is None:
                continue
            turn = self.turn_factory(
                agent, self.roles[agent["role"]], item[2],
                emit=lambda ev, a=agent_id, t=item[1]: self._on_event(a, t, ev),
                ask=lambda tool, inp, rule, a=agent_id: self._ask(a, tool, inp, rule),
                model=self.config.get("model"))
            task = asyncio.get_running_loop().create_task(self._run(agent, item[1], turn))
            self.running[agent_id] = (turn, task)
        self.broadcast({"type": "capacity", **self._capacity()})

    async def _run(self, agent, thread, turn):
        agent_id = agent["id"]
        self._status(agent_id, "working")
        status = "idle"
        try:
            out = await turn.run()
            if out["session_id"] and self.store.agent(agent_id):
                self.store.set_session(agent_id, out["session_id"])
            if out["is_error"]:
                status = "error"
                self._post(thread, "system", "system", out["text"] or "El turno terminó con error.")
            elif thread == "group":
                self._route(out["text"], author=agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # SDK/CLI failures must not kill the daemon
            print(f"colmena: turno de {agent['name']} falló: {e!r}", file=sys.stderr)
            status = "error"
            self._post(thread, "system", "system", f"Error: {e}")
        finally:
            self.running.pop(agent_id, None)
            if agent_id in self.statuses:
                queued = any(q[0] == agent_id for q in self.queue)
                self._status(agent_id, "queued" if queued else status)
            self._pump()

    def _on_event(self, agent_id, thread, ev):
        if ev["type"] == "delta":
            self.broadcast({"type": "delta", "agent": agent_id, "thread": thread, "text": ev["text"]})
        elif ev["type"] == "text":
            self._post(thread, agent_id, "text", ev["text"])
        elif ev["type"] in ("tool", "tool_result"):
            self._post(agent_id, agent_id, "tool", json.dumps(ev))

    # approvals --------------------------------------------------------------
    async def _ask(self, agent_id, tool, input, rule):
        ap = self.store.add_approval(agent_id, tool, input, rule)
        fut = asyncio.get_running_loop().create_future()
        self.pending[ap["id"]] = (agent_id, fut)
        self._status(agent_id, "waiting")
        self.broadcast({"type": "approval", "approval": ap})
        if not self.clients:
            name = self.store.agent(agent_id)["name"]
            self.notifier(f"{name} necesita tu aprobación", f"{tool}: {rule}")
        try:
            return await fut
        finally:
            self.pending.pop(ap["id"], None)
            if agent_id in self.running:
                self._status(agent_id, "working")

    def approve(self, approval_id, decision):
        if decision not in ("allow", "deny", "always"):
            raise ValueError("Decisión inválida.")
        entry = self.pending.get(approval_id)
        if entry is None:
            raise ValueError("Esa aprobación ya no está pendiente.")
        agent_id, fut = entry
        if decision == "always":
            ap = next(a for a in self.store.approvals() if a["id"] == approval_id)
            self.store.allow_always(agent_id, ap["rule"])
        self.store.resolve_approval(approval_id, decision)
        if not fut.done():
            fut.set_result(decision)
        self.broadcast({"type": "approval_resolved", "id": approval_id, "status": decision})

    def expire_stale_approvals(self):
        for ap in self.store.approvals():
            self.store.resolve_approval(ap["id"], "expired")

    async def stop(self, agent_id):
        self.queue = deque(q for q in self.queue if q[0] != agent_id)
        for ap_id, (a, _) in list(self.pending.items()):
            if a == agent_id:
                self.approve(ap_id, "deny")
        entry = self.running.get(agent_id)
        if entry:
            await entry[0].stop()

    # memory -----------------------------------------------------------------
    async def sample_memory(self):
        if not self.running:
            return
        rss_mb = capacity.descendants_rss_kb(os.getpid()) / 1024 / len(self.running)
        if rss_mb > 0:
            self.per_turn_mb = capacity.ema(self.per_turn_mb, rss_mb)
            self.store.set("per_turn_mb", str(round(self.per_turn_mb)))
        self.broadcast({"type": "capacity", **self._capacity()})

    async def drain(self):
        while self.running or self.queue:
            tasks = [t for _, t in self.running.values()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(0)
