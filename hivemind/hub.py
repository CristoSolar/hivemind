import asyncio
import json
import os
import sqlite3
import subprocess
import time
import sys
from collections import deque

from hivemind import attachments as att, capacity, palette, paths
from hivemind.board import Board
from hivemind.router import CONTEXT_MESSAGES, MAX_HOPS, NAME_RE, mentions
from hivemind.routines import Routines
from hivemind.runner import Turn


def notify(title, body):
    try:
        subprocess.Popen(["notify-send", "-a", "HiveMind", title, body])
    except OSError:
        pass


MODELS = (None, "opus", "sonnet", "haiku")  # None = Claude Code's default
AUTH_MODES = ("subscription", "api_key")
NO_TRANSCRIPT = ("No pude transcribir el audio: instala Voxtype desde el menú de Omarchy (Instalar → Voxtype) "
                 "y elige un modelo multilingüe para audios en español.")
PRIVATE_BRIDGE = 10  # private messages an agent sees when it speaks in a group


class Hub:
    def __init__(self, store, roles, turn_factory=Turn, meminfo=capacity.read_meminfo,
                 config=None, notifier=notify, save_config=paths.save_config, transcriber=None):
        self.store, self.roles = store, roles
        self.turn_factory, self.meminfo, self.notifier = turn_factory, meminfo, notifier
        self.save_config = save_config
        self.transcriber = transcriber or att.transcribe
        self.config = config or {}
        self.clients = []
        self.queue = deque()        # (agent_id, thread, prompt)
        self.running = {}           # agent_id -> (Turn, asyncio.Task)
        self.pending = {}           # approval_id -> (agent_id, Future)
        self.statuses = {a["id"]: "idle" for a in store.agents()}
        self.activities = {}  # agent_id -> "thinking" | "tool" while a turn runs
        self.last_active = {a["id"]: store.last_activity(a["id"]) or a["created_at"] for a in store.agents()}
        self.hops = {}  # thread -> agent-to-agent hops since the last user message
        self.per_turn_mb = float(store.get("per_turn_mb", capacity.DEFAULT_PER_TURN_MB))
        self.board = Board(self)
        self.routines = Routines(self)

    # events -----------------------------------------------------------------
    def has_window(self):
        """A GTK window is connected (the always-on bar panel does not count)."""
        return any(not getattr(fn, "panel", False) for fn in self.clients)

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

    def _activity(self, agent_id, activity):
        if activity is None:
            self.activities.pop(agent_id, None)
            self.last_active[agent_id] = time.time()
        elif self.activities.get(agent_id) == activity:
            return
        else:
            self.activities[agent_id] = activity
        self.broadcast({"type": "activity", "agent": agent_id, "activity": activity,
                        "last_active": self.last_active.get(agent_id)})

    def _post(self, thread, author, kind, content, files=None):
        message = self.store.add_message(thread, author, kind, content, files)
        self.broadcast({"type": "message", "message": message})
        return message

    def max_running(self):
        return capacity.max_running(self.meminfo(), self.per_turn_mb, self.config.get("max_running"))

    def _capacity(self):
        return {"running": len(self.running), "max": self.max_running()}

    def snapshot(self):
        return {"agents": self.store.agents(), "roles": self.roles, "statuses": self.statuses, "settings": self.settings(),
                "activities": self.activities, "last_active": self.last_active,
                "approvals": self.store.approvals(), "capacity": self._capacity(),
                "routines": self.routines.list(), "tasks": self.board.list(), "groups": self.store.groups()}

    # conversations --------------------------------------------------------------
    def is_group(self, thread):
        return thread == "group" or (thread.startswith("g-") and self.store.group(thread) is not None)

    def members(self, thread):
        agents = self.store.agents()
        if thread == "group":
            return agents
        group = self.store.group(thread)
        return [a for a in agents if group and a["id"] in group["members"]]

    def _check_members(self, members):
        known = {a["id"] for a in self.store.agents()}
        if not members or any(m not in known for m in members):
            raise ValueError("Elige al menos un agente que exista.")
        return list(dict.fromkeys(members))

    def create_group(self, name, members):
        name = (name or "").strip()
        if not name:
            raise ValueError("El grupo necesita un nombre.")
        members = self._check_members(members)
        group = self.store.create_group(name)
        self.store.set_members(group["id"], members)
        self.broadcast({"type": "groups", "groups": self.store.groups()})
        return self.store.group(group["id"])

    async def update_group(self, group_id, name=None, members=None):
        group = self.store.group(group_id)
        if group is None:
            raise ValueError("Ese grupo no existe.")
        if name is not None:
            if not name.strip():
                raise ValueError("El grupo necesita un nombre.")
            self.store.rename_group(group_id, name.strip())
        if members is not None:
            members = self._check_members(members)
            gone = set(group["members"]) - set(members)
            await self._stop_in_thread(group_id, agents=gone)  # a leaving member stops talking there first
            for agent_id in gone:
                self.store.delete_sessions(agent_id=agent_id, thread=group_id)  # they forget this group
            self.store.set_members(group_id, members)
        self.broadcast({"type": "groups", "groups": self.store.groups()})
        return self.store.group(group_id)

    async def delete_group(self, group_id):
        if self.store.group(group_id) is None:
            raise ValueError("Ese grupo no existe.")
        await self.clear_thread(group_id)
        self.store.delete_group(group_id)
        self.routines.pause_target(group_id)
        self.broadcast({"type": "groups", "groups": self.store.groups()})

    async def _stop_in_thread(self, thread, agents=None):
        """Drop queued work for `thread` and stop turns running in it, until none is left.

        Loops because a turn that finishes as it is stopped can still enqueue a hand-off.
        `agents` limits this to some agents (members leaving a group)."""
        def mine(agent_id):
            return agents is None or agent_id in agents

        while True:
            self.queue = deque(q for q in self.queue if not (q[1] == thread and mine(q[0])))
            stopping = []
            for agent_id, (turn, task, running_thread) in list(self.running.items()):
                if running_thread == thread and mine(agent_id):
                    for ap_id, (a, _) in list(self.pending.items()):
                        if a == agent_id:
                            self.approve(ap_id, "deny")
                    turn.discard = True  # whatever it still says belongs to a conversation being wiped
                    await turn.stop()
                    stopping.append(task)
            if not stopping:
                return
            await asyncio.gather(*stopping, return_exceptions=True)

    async def clear_thread(self, thread):
        if self.is_group(thread):
            members = [a["id"] for a in self.members(thread)]
        elif self.store.agent(thread):
            members = [thread]
        else:
            raise ValueError("Esa conversación no existe.")
        # Stop what is running in this conversation first, so nothing is posted after the wipe.
        await self._stop_in_thread(thread)
        self.store.delete_messages(thread)
        att.remove_thread(thread)
        for agent_id in members:
            self.store.delete_sessions(agent_id=agent_id, thread=thread)
        if thread == "group" or thread.startswith("g-"):
            self.hops.pop(thread, None)
        self.broadcast({"type": "thread_cleared", "thread": thread})

    # agents -----------------------------------------------------------------
    def _check_model(self, model):
        if model not in MODELS:
            raise ValueError(f"Modelo desconocido: {model}. Usa opus, sonnet o haiku.")

    def _check_cwd(self, cwd):
        cwd = os.path.expanduser(cwd)
        if not os.path.isdir(cwd):
            raise ValueError(f"La carpeta {cwd} no existe.")
        return cwd

    def create_agent(self, name, role, cwd=None, model=None, brief="", tint=None):
        self._check_model(model)
        if not NAME_RE.match(name or ""):
            raise ValueError("El nombre solo puede tener letras, números, guiones y guiones bajos.")
        if role not in self.roles:
            raise ValueError(f"No existe el rol «{role}».")
        cwd = self._check_cwd(cwd or self.roles[role]["cwd"])
        # SQLite's NOCASE only folds ASCII, so check Unicode case here too.
        if any(a["name"].casefold() == name.casefold() for a in self.store.agents()):
            raise ValueError(f"Ya existe un agente llamado «{name}».")
        try:
            agent = self.store.create_agent(name, role, cwd, model, (brief or "").strip(),
                                            self._check_tint(tint))
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya existe un agente llamado «{name}».") from None
        self.statuses[agent["id"]] = "idle"
        self.last_active[agent["id"]] = agent["created_at"]
        self.broadcast({"type": "agents", "agents": self.store.agents()})
        return agent

    @staticmethod
    def _check_tint(tint):
        """None means the window picks one; anything else must name a palette colour."""
        if tint is None:
            return None
        if not palette.valid(tint):
            raise ValueError("Ese color no existe.")
        return tint

    def update_agent(self, agent_id, **changes):
        agent = self.store.agent(agent_id)
        if agent is None:
            raise ValueError("Ese agente no existe.")
        fields = {}
        if "model" in changes:
            self._check_model(changes["model"])
            fields["model"] = changes["model"]
        if "brief" in changes:
            fields["brief"] = (changes["brief"] or "").strip()
        if "tint" in changes:
            fields["tint"] = self._check_tint(changes["tint"])
        if changes.get("cwd"):
            cwd = self._check_cwd(changes["cwd"])
            if cwd != agent["cwd"]:
                # Claude Code keeps sessions per project folder; none of them can be resumed.
                fields.update(cwd=cwd)
                self.store.delete_sessions(agent_id=agent_id)
                self._post(agent_id, "system", "system",
                           f"Carpeta cambiada a {cwd}. La conversación empieza de cero.")
        self.store.update_agent(agent_id, **fields)
        self.broadcast({"type": "agents", "agents": self.store.agents()})
        return self.store.agent(agent_id)

    # settings ---------------------------------------------------------------
    def settings(self):
        return {"auth": self.config.get("auth", "subscription"),
                "has_api_key": bool(self.config.get("api_key"))}

    def set_settings(self, auth, api_key=None):
        if auth not in AUTH_MODES:
            raise ValueError("Cuenta inválida.")
        cfg = {**self.config, "auth": auth}
        if api_key:
            cfg["api_key"] = api_key.strip()
        if auth == "api_key" and not cfg.get("api_key"):
            raise ValueError("Escribe una API key.")
        self.save_config(cfg)
        self.config = cfg
        return self.settings()

    def _env(self):
        if self.config.get("auth") == "api_key" and self.config.get("api_key"):
            return {"ANTHROPIC_API_KEY": self.config["api_key"]}
        return None

    def automation_allowed(self):
        """Unattended turns need an API key: the Consumer Terms allow automated access only
        that way, and Pro/Max limits assume ordinary, individual use. On a subscription a
        routine waits for one human click instead."""
        return self._env() is not None

    async def delete_agent(self, agent_id):
        await self.stop(agent_id)
        entry = self.running.get(agent_id)
        if entry:
            await asyncio.gather(entry[1], return_exceptions=True)
        self.store.delete_agent(agent_id)
        att.remove_thread(agent_id)  # files attached in its private chat
        self.statuses.pop(agent_id, None)
        self.activities.pop(agent_id, None)
        self.last_active.pop(agent_id, None)
        self.broadcast({"type": "agents", "agents": self.store.agents()})
        self.broadcast({"type": "groups", "groups": self.store.groups()})

    # messages ---------------------------------------------------------------
    async def send(self, thread, text, origin=None, attachments=None):
        text = text or ""
        if not text.strip() and not attachments:
            raise ValueError("Escribe un mensaje o adjunta un archivo.")
        files = self._attach(thread, attachments or [])  # raises before anything is posted
        message = self._post(thread, "user", "text", text, files)  # show it now, even if audio is slow
        audios = [f for f in files if f["kind"] == "audio"]
        if audios:
            self._post(thread, "system", "system", "Transcribiendo audio…")
            for f in audios:
                f["transcript"] = await self.transcriber(f["path"])
            updated = self.store.update_attachments(message["id"], files)
            if updated:
                self.broadcast({"type": "message_updated", "message": updated})
            if not all(f["transcript"] for f in audios):
                self._post(thread, "system", "system", NO_TRANSCRIPT)
            if not (self.is_group(thread) or self.store.agent(thread)):
                return  # the conversation was cleared or deleted while transcribing
        if self.is_group(thread):
            self.hops[thread] = 0
            self._route(thread, text, author=None, origin=origin)
        elif self.store.agent(thread):
            prompt = "\n\n".join(p for p in (text, att.prompt_lines(files)) if p)
            self._enqueue(thread, thread, prompt, origin)

    def _attach(self, thread, sources):
        if sources and not (self.is_group(thread) or self.store.agent(thread)):
            raise ValueError("Esa conversación no existe.")
        return att.store(sources, thread) if sources else []

    def _route(self, thread, text, author, origin=None):
        agents = self.store.agents()
        members = {a["id"] for a in self.members(thread)}
        me = next((a["name"] for a in agents if a["id"] == author), None)
        known, unknown = mentions(text, [a["name"] for a in agents], exclude=me)
        if unknown:
            self._post(thread, "system", "system", "No hay agentes llamados: " + ", ".join("@" + u for u in unknown))
        outsiders = [a["name"] for a in agents if a["name"] in known and a["id"] not in members]
        if outsiders:
            self._post(thread, "system", "system",
                       " ".join(f"«{n}» no está en este grupo." for n in outsiders))
            known = [n for n in known if n not in outsiders]
        if not known:
            if author is not None or unknown or outsiders:
                return
            known = [a["name"] for a in agents if a["id"] in members]  # no @: every member answers
        if author is not None:
            if self.hops.get(thread, 0) >= MAX_HOPS:
                self._post(thread, "system", "system",
                           f"Se alcanzó el límite de {MAX_HOPS} pases entre agentes. Escribe para continuar.")
                return
            self.hops[thread] = self.hops.get(thread, 0) + 1
        for a in agents:
            if a["name"] in known:
                self._enqueue(a["id"], thread, self._group_prompt(thread, a["id"]), origin)

    def _group_prompt(self, thread, agent_id):
        names = {a["id"]: a["name"] for a in self.store.agents()}

        def who(m):
            return {"user": "Usuario", "system": "Sistema"}.get(m["author"]) or names.get(m["author"], "?")

        lines = []
        for m in self.store.history(thread, limit=CONTEXT_MESSAGES):
            line = f"[{who(m)}]: {m['content']}"
            if m.get("attachments"):
                line += "\n" + att.prompt_lines(m["attachments"])
            lines.append(line)
        prompt = ("Mensajes recientes de esta conversación grupal de HiveMind. Te mencionaron en el último. "
                  "Tu respuesta se publicará en el grupo.\n\n" + "\n".join(lines))
        # Bridge: what the agent and the user said in private, so status questions get real answers.
        private = [m for m in self.store.history(agent_id, limit=40) if m["kind"] == "text"][-PRIVATE_BRIDGE:]
        if private:
            prompt += ("\n\nTu chat privado reciente con el usuario (contexto, no lo repitas si no hace falta):\n"
                       + "\n".join(f"[{who(m)}]: {m['content'][:500]}" for m in private))
        return prompt

    # queue ------------------------------------------------------------------
    def _enqueue(self, agent_id, thread, prompt, origin=None):
        self.queue.append((agent_id, thread, prompt, origin))
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
            agent = {**agent, "session_id": self.store.session(agent_id, item[1])}
            turn = self.turn_factory(
                agent, self.roles[agent["role"]], item[2],
                emit=lambda ev, a=agent_id, t=item[1]: self._on_event(a, t, ev),
                ask=lambda tool, inp, rule, a=agent_id: self._ask(a, tool, inp, rule),
                model=self.config.get("model"), env=self._env(), thread=item[1],
                mcp_servers={"tablero": self.board.mcp_server(agent_id)})
            task = asyncio.get_running_loop().create_task(self._run(agent, item[1], turn, item[3]))
            self.running[agent_id] = (turn, task, item[1])
        self.broadcast({"type": "capacity", **self._capacity()})

    async def _run(self, agent, thread, turn, origin=None):
        agent_id = agent["id"]
        self._status(agent_id, "working")
        self._activity(agent_id, "thinking")
        status = "idle"
        try:
            out = await turn.run()
            if out["session_id"] and self.store.agent(agent_id) and not getattr(turn, "discard", False):
                self.store.save_session(agent_id, thread, out["session_id"])
            if out["is_error"]:
                status = "error"
                self._post(thread, "system", "system", out["text"] or "El turno terminó con error.")
            elif self.is_group(thread) and not getattr(turn, "stopped", False) and not getattr(turn, "discard", False):
                self._route(thread, out["text"], author=agent_id)  # a stopped turn hands nothing off
            if origin and not self.has_window():
                self.notifier(f"Rutina «{origin['routine']}» lista", (out["text"] or "")[:200])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # SDK/CLI failures must not kill the daemon
            print(f"hivemind: turno de {agent['name']} falló: {e!r}", file=sys.stderr)
            status = "error"
            self._post(thread, "system", "system", f"Error: {e}")
        finally:
            self.running.pop(agent_id, None)
            if agent_id in self.statuses:
                self._activity(agent_id, None)
            if agent_id in self.statuses:
                queued = any(q[0] == agent_id for q in self.queue)
                self._status(agent_id, "queued" if queued else status)
            self._pump()

    def _on_event(self, agent_id, thread, ev):
        entry = self.running.get(agent_id)
        if entry and getattr(entry[0], "discard", False) and ev["type"] != "activity":
            return
        if ev["type"] == "activity":
            self._activity(agent_id, ev["kind"])
        elif ev["type"] == "delta":
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
        if not self.has_window():
            name = self.store.agent(agent_id)["name"]
            self.notifier(f"{name} necesita tu aprobación", f"{tool}: {rule}")
        try:
            return await fut
        finally:
            self.pending.pop(ap["id"], None)
            if fut.cancelled():  # the SDK/CLI dropped the request; clear the card
                self.store.resolve_approval(ap["id"], "expired")
                self.broadcast({"type": "approval_resolved", "id": ap["id"], "status": "expired"})
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
            tasks = [t for _, t, _ in self.running.values()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(0)
