# Groups, Per-Conversation Memory and Clearing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named groups with chosen members, one Claude Code session per agent per conversation (with the private chat bridged into group turns), and clearing a conversation's messages and memory.

**Architecture:**
- The store gains three tables: `sessions`, `groups` and `group_members`.
- The hub stops treating `"group"` as the only group thread. A *group thread* is `"group"` (every agent) or a `g-…` id (its members).
- Each turn resumes and stores the session for `(agent, thread)`.
- `clear_thread` stops that thread's turns, then deletes its messages and sessions.
- The GTK window lists the groups, gains a group dialog, and gets "Limpiar" / "Nueva conversación" buttons.

**Tech Stack:** Python 3.14 stdlib (`sqlite3`, `asyncio`, `unittest`), claude-agent-sdk, GTK4/libadwaita.

**Spec:** `docs/superpowers/specs/2026-09-25-groups-and-clearing-design.md`

## Global Constraints

- Group ids are `g-` + 8 hex characters. `"group"` is the general group; every other thread id is an agent id.
- Bridge: the last 10 **text** messages of the agent's private thread, each truncated to 500 characters, under the heading "Tu chat privado reciente con el usuario". The section is omitted when there are none.
- Hop limit: 5, counted per thread and reset by a user message in that thread.
- UI copy is Spanish. Tests use stdlib `unittest`. Scratch files go in `~/.cache/tmp`.
- Never drive the user's screen. GTK checks run on Broadway (`gtk4-broadwayd :7`, `GDK_BACKEND=broadway`).
- The migration keeps the private memory: each `agents.session_id` becomes `sessions(agent, agent)`. The old column is left in place.

## Review Focus

1. Clearing a thread while one of its members is mid-turn: the turn must be stopped and awaited before the messages are deleted, so no message reappears afterwards. Pinned in Task 2.
2. A user mentioning an agent who is not a member of a custom group gets a notice, and nothing is routed to that agent. Pinned in Task 2.
3. Two groups with the same member must not leak messages into each other's prompt. Pinned in Task 2.
4. An existing user database migrates with the private memory intact and nothing duplicated when run twice. Pinned in Task 1.
5. Deleting a group or an agent pauses routines that target it and removes memberships. Pinned in Task 2.

---

### Task 1: Store — sessions, groups, members, migration, cascades

**Files:** Modify `hivemind/store.py`. Test: `tests/test_store.py`.

**Interfaces — produces (Store methods):**
- `session(agent_id, thread) -> str|None`
- `save_session(agent_id, thread, session_id)`
- `delete_sessions(agent_id=None, thread=None)`: at least one argument is required.
- `delete_messages(thread)`
- `create_group(name) -> dict`
- `groups() -> list[dict]`, where each dict is `{id, name, members: [agent_id], created_at}`
- `group(id) -> dict|None`
- `rename_group(id, name)`
- `set_members(id, members)`
- `delete_group(id)`
- `delete_agent(id)` now also removes the agent's sessions and memberships.

- [ ] **Step 1: Failing tests.** Append to `StoreTest`:

```python
    def test_sessions_per_thread(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        self.assertIsNone(self.s.session(a["id"], "group"))
        self.s.save_session(a["id"], "group", "g1")
        self.s.save_session(a["id"], a["id"], "p1")
        self.s.save_session(a["id"], "group", "g2")  # replaces
        self.assertEqual((self.s.session(a["id"], "group"), self.s.session(a["id"], a["id"])), ("g2", "p1"))
        self.s.delete_sessions(thread="group")
        self.assertEqual((self.s.session(a["id"], "group"), self.s.session(a["id"], a["id"])), (None, "p1"))
        self.s.delete_sessions(agent_id=a["id"])
        self.assertIsNone(self.s.session(a["id"], a["id"]))
        with self.assertRaises(ValueError):
            self.s.delete_sessions()

    def test_groups_and_members(self):
        a = self.s.create_agent("Dev", "dev", "/tmp")
        b = self.s.create_agent("Mkt", "dev", "/tmp")
        g = self.s.create_group("Lanzamiento")
        self.assertTrue(g["id"].startswith("g-"))
        self.s.set_members(g["id"], [a["id"], b["id"]])
        self.assertEqual(set(self.s.group(g["id"])["members"]), {a["id"], b["id"]})
        self.s.rename_group(g["id"], "Campaña")
        self.assertEqual(self.s.groups()[0]["name"], "Campaña")
        self.s.delete_agent(b["id"])
        self.assertEqual(self.s.group(g["id"])["members"], [a["id"]])
        self.s.delete_group(g["id"])
        self.assertIsNone(self.s.group(g["id"]))

    def test_delete_messages_of_one_thread(self):
        self.s.add_message("group", "user", "text", "a")
        self.s.add_message("g-1", "user", "text", "b")
        self.s.delete_messages("group")
        self.assertEqual([m["content"] for m in self.s.history("group")], [])
        self.assertEqual([m["content"] for m in self.s.history("g-1")], ["b"])

    def test_migration_moves_private_memory_once(self):
        import os, tempfile
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/.cache/tmp")) as d:
            path = d + "/old.db"
            old = Store(path)
            a = old.create_agent("Dev", "dev", "/tmp")
            old.set_session(a["id"], "legacy")  # pre-sessions memory lived on the agent row
            old.db.execute("delete from sessions")
            old.db.commit()
            old.db.close()
            for _ in range(2):  # idempotent
                s = Store(path)
                self.assertEqual(s.session(a["id"], a["id"]), "legacy")
                self.assertIsNone(s.session(a["id"], "group"))
                self.assertEqual(s.db.execute("select count(*) from sessions").fetchone()[0], 1)
                s.db.close()
```

- [ ] **Step 2: Run** `.venv/bin/python -m unittest tests.test_store -v`. Expected: FAIL with `AttributeError: 'Store' object has no attribute 'session'`.

- [ ] **Step 3: Implement.** Append to `SCHEMA`:

```sql
create table if not exists sessions(
  agent_id text not null, thread text not null, session_id text not null,
  primary key(agent_id, thread));
create table if not exists groups(id text primary key, name text not null, created_at real not null);
create table if not exists group_members(
  group_id text not null, agent_id text not null, primary key(group_id, agent_id));
```

In `Store.__init__`, after the model-column migration, add:

```python
        with self.db:  # memory used to live on the agent row: it becomes the private chat's session
            self.db.execute("insert or ignore into sessions(agent_id, thread, session_id)"
                            " select id, id, session_id from agents where session_id is not null")
```

Replace `delete_agent` with:

```python
    def delete_agent(self, id):
        with self.db:
            self.db.execute("delete from agents where id = ?", (id,))
            self.db.execute("delete from sessions where agent_id = ?", (id,))
            self.db.execute("delete from group_members where agent_id = ?", (id,))
```

Add these methods:

```python
    # sessions: one Claude Code session per agent per conversation ------------
    def session(self, agent_id, thread):
        row = self.db.execute("select session_id from sessions where agent_id = ? and thread = ?",
                              (agent_id, thread)).fetchone()
        return row[0] if row else None

    def save_session(self, agent_id, thread, session_id):
        with self.db:
            self.db.execute("insert or replace into sessions values(?, ?, ?)", (agent_id, thread, session_id))

    def delete_sessions(self, agent_id=None, thread=None):
        if agent_id is None and thread is None:
            raise ValueError("delete_sessions needs an agent, a thread or both")
        clauses, args = [], []
        for column, value in (("agent_id", agent_id), ("thread", thread)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        with self.db:
            self.db.execute("delete from sessions where " + " and ".join(clauses), args)

    def delete_messages(self, thread):
        with self.db:
            self.db.execute("delete from messages where thread = ?", (thread,))

    # groups -------------------------------------------------------------------
    def _group(self, row):
        if row is None:
            return None
        members = [r[0] for r in self.db.execute(
            "select agent_id from group_members where group_id = ? order by agent_id", (row["id"],))]
        return {**dict(row), "members": members}

    def create_group(self, name):
        g = {"id": "g-" + _new_id(), "name": name, "created_at": time.time()}
        with self.db:
            self.db.execute("insert into groups values(:id, :name, :created_at)", g)
        return self.group(g["id"])

    def groups(self):
        return [self._group(r) for r in self.db.execute("select * from groups order by created_at")]

    def group(self, id):
        return self._group(self.db.execute("select * from groups where id = ?", (id,)).fetchone())

    def rename_group(self, id, name):
        with self.db:
            self.db.execute("update groups set name = ? where id = ?", (name, id))

    def set_members(self, id, members):
        with self.db:
            self.db.execute("delete from group_members where group_id = ?", (id,))
            self.db.executemany("insert into group_members values(?, ?)", [(id, m) for m in members])

    def delete_group(self, id):
        with self.db:
            self.db.execute("delete from groups where id = ?", (id,))
            self.db.execute("delete from group_members where group_id = ?", (id,))
```

- [ ] **Step 4: Run** `.venv/bin/python -m unittest tests.test_store -v`. Expected: all OK.
- [ ] **Step 5: Commit** with the message `feat: store sessions per conversation and groups with members`.

---

### Task 2: Hub — group threads, per-thread sessions, bridge, clearing, group CRUD

**Files:** Modify `hivemind/hub.py` and `hivemind/routines.py`. Test: `tests/test_hub.py`, `tests/test_routines.py`.

**Interfaces:**
- **Consumes** the Task 1 store methods.
- **Produces (Hub):**
  - `is_group(thread) -> bool` and `members(thread) -> list[agent dict]`
  - `create_group(name, members) -> dict`
  - `update_group(group_id, name=None, members=None) -> dict`
  - `async delete_group(group_id)` and `async clear_thread(thread)`
  - `snapshot()["groups"]`
  - events `groups {groups}` and `thread_cleared {thread}`
  - `running` values become `(turn, task, thread)`.

- [ ] **Step 1: Failing tests.** First update the existing hub tests to the new session API:
  - In `test_private_chat_stores_session`, assert `self.store.session(a["id"], a["id"]) == "s-Dev"`.
  - In `test_update_model_keeps_session`, use `self.store.save_session(a["id"], a["id"], "s1")` and assert `self.store.session(a["id"], a["id"]) == "s1"`.
  - In `test_update_cwd_resets_session_with_notice`, use `save_session(a["id"], a["id"], "s1")` and `save_session(a["id"], "group", "g1")`, then assert both come back `None` after the folder change.

  Then append to `HubTest`:

```python
    def make(self, *names):
        return [self.hub.create_agent(n, "dev") for n in names]

    async def test_custom_group_routes_only_to_members(self):
        dev, mkt, ops = self.make("Dev", "Mkt", "Ops")
        g = self.hub.create_group("Lanzamiento", [dev["id"], mkt["id"]])
        await self.hub.send(g["id"], "hola equipo")
        await self.hub.drain()
        self.assertEqual(sorted(x[0] for x in FakeTurn.log if x[1] == "start"), ["Dev", "Mkt"])
        self.assertEqual({m["thread"] for m in self.store.history(g["id"])}, {g["id"]})

    async def test_mentioning_a_non_member_gives_notice(self):
        dev, ops = self.make("Dev", "Ops")
        g = self.hub.create_group("Solo dev", [dev["id"]])
        await self.hub.send(g["id"], "@Ops ayuda")
        await self.hub.drain()
        self.assertEqual(FakeTurn.log, [])
        self.assertIn("no está en este grupo", self.store.history(g["id"])[-1]["content"])

    async def test_group_prompt_has_thread_and_private_bridge_only(self):
        prompts = {}

        class SpyTurn(FakeTurn):
            def __init__(self, agent, role, prompt, *a, **kw):
                prompts.setdefault(agent["name"], []).append(prompt)
                super().__init__(agent, role, prompt, *a, **kw)

        self.hub.turn_factory = SpyTurn
        dev, = self.make("Dev")
        g1 = self.hub.create_group("Uno", [dev["id"]])
        g2 = self.hub.create_group("Dos", [dev["id"]])
        await self.hub.send(dev["id"], "avance: la API ya está lista")
        await self.hub.drain()
        await self.hub.send(g1["id"], "secreto del grupo uno")
        await self.hub.drain()
        await self.hub.send(g2["id"], "¿cómo va el desarrollo?")
        await self.hub.drain()
        last = prompts["Dev"][-1]
        self.assertIn("¿cómo va el desarrollo?", last)
        self.assertIn("Tu chat privado reciente con el usuario", last)
        self.assertIn("la API ya está lista", last)
        self.assertNotIn("secreto del grupo uno", last)

    async def test_sessions_are_per_conversation(self):
        dev, = self.make("Dev")
        seen = []

        class SessionTurn(FakeTurn):
            async def run(self):
                seen.append(self.agent["session_id"])
                return {**await super().run(), "session_id": "s-" + self.prompt[:5]}

        self.hub.turn_factory = SessionTurn
        await self.hub.send(dev["id"], "priv1")
        await self.hub.drain()
        await self.hub.send("group", "@Dev grupo")
        await self.hub.drain()
        await self.hub.send(dev["id"], "priv2")
        await self.hub.drain()
        self.assertEqual(seen, [None, None, "s-priv1"])
        self.assertEqual(self.store.session(dev["id"], dev["id"]), "s-priv2")
        self.assertTrue(self.store.session(dev["id"], "group").startswith("s-"))

    async def test_hops_are_per_thread(self):
        a, b = self.make("A", "B")
        FakeTurn.replies = {"A": "@B", "B": "@A"}
        g = self.hub.create_group("AB", [a["id"], b["id"]])
        await self.hub.send(g["id"], "@A empieza")
        await self.hub.drain()
        self.assertEqual(len([x for x in FakeTurn.log if x[1] == "start"]), 6)
        self.assertEqual(self.store.history(g["id"])[-1]["author"], "system")
        self.assertEqual(self.store.history("group"), [])

    async def test_clear_thread_stops_its_turns_and_forgets_only_that_conversation(self):
        FakeTurn.gate = asyncio.Event()
        dev, = self.make("Dev")
        self.store.save_session(dev["id"], dev["id"], "private")
        self.store.save_session(dev["id"], "group", "old-group")
        await self.hub.send("group", "@Dev tema viejo")
        await asyncio.sleep(0)  # the turn is running and waiting on the gate
        await self.hub.clear_thread("group")
        await self.hub.drain()
        self.assertEqual(self.store.history("group"), [])  # nothing reappears after the stop
        self.assertIsNone(self.store.session(dev["id"], "group"))
        self.assertEqual(self.store.session(dev["id"], dev["id"]), "private")
        self.assertIn({"type": "thread_cleared", "thread": "group"}, self.events)

    async def test_new_conversation_clears_private_chat(self):
        dev, = self.make("Dev")
        await self.hub.send(dev["id"], "hola")
        await self.hub.drain()
        self.store.save_session(dev["id"], "group", "keep")
        await self.hub.clear_thread(dev["id"])
        self.assertEqual(self.store.history(dev["id"]), [])
        self.assertIsNone(self.store.session(dev["id"], dev["id"]))
        self.assertEqual(self.store.session(dev["id"], "group"), "keep")

    async def test_group_crud_validation_and_cascades(self):
        dev, mkt = self.make("Dev", "Mkt")
        for bad in (("", [dev["id"]]), ("X", []), ("X", ["nadie"])):
            with self.assertRaises(ValueError):
                self.hub.create_group(*bad)
        g = self.hub.create_group("Campaña", [dev["id"], mkt["id"]])
        self.store.save_session(mkt["id"], g["id"], "s")
        self.hub.update_group(g["id"], members=[dev["id"]])  # removing a member forgets their group memory
        self.assertIsNone(self.store.session(mkt["id"], g["id"]))
        r = self.hub.routines.create("R", g["id"], "hola", {"every_hours": 1})
        await self.hub.delete_group(g["id"])
        self.assertIsNone(self.store.group(g["id"]))
        self.assertFalse(self.store.routine(r["id"])["enabled"])
        self.assertEqual(self.events[-1]["type"] in ("groups", "routines", "message"), True)

    def test_snapshot_lists_groups(self):
        dev, = self.make("Dev")
        self.hub.create_group("G", [dev["id"]])
        self.assertEqual([g["name"] for g in self.hub.snapshot()["groups"]], ["G"])
```

In `FakeTurn.run`, the gated wait must honour `stop()`. It already does, because `stop()` sets the gate.

- [ ] **Step 2: Run** `.venv/bin/python -m unittest tests.test_hub -v`. Expected: FAIL with `AttributeError: 'Hub' object has no attribute 'create_group'`, and the session tests fail.

- [ ] **Step 3: Implement** in `hivemind/hub.py`:

1. `self.hops = 0` becomes `self.hops = {}  # thread -> agent-to-agent hops since the last user message`.
2. Snapshot: add `"groups": self.store.groups(),`.
3. Add after `_capacity`:

```python
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

    def update_group(self, group_id, name=None, members=None):
        group = self.store.group(group_id)
        if group is None:
            raise ValueError("Ese grupo no existe.")
        if name is not None:
            if not name.strip():
                raise ValueError("El grupo necesita un nombre.")
            self.store.rename_group(group_id, name.strip())
        if members is not None:
            members = self._check_members(members)
            for gone in set(group["members"]) - set(members):
                self.store.delete_sessions(agent_id=gone, thread=group_id)  # they forget this group
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

    async def clear_thread(self, thread):
        if self.is_group(thread):
            members = [a["id"] for a in self.members(thread)]
        elif self.store.agent(thread):
            members = [thread]
        else:
            raise ValueError("Esa conversación no existe.")
        # Stop what is running in this conversation first, so nothing is posted after the wipe.
        self.queue = deque(q for q in self.queue if q[1] != thread)
        stopping = []
        for agent_id, (turn, task, running_thread) in list(self.running.items()):
            if running_thread == thread:
                for ap_id, (a, _) in list(self.pending.items()):
                    if a == agent_id:
                        self.approve(ap_id, "deny")
                await turn.stop()
                stopping.append(task)
        if stopping:
            await asyncio.gather(*stopping, return_exceptions=True)
        self.store.delete_messages(thread)
        for agent_id in members:
            self.store.delete_sessions(agent_id=agent_id, thread=thread)
        if thread == "group" or thread.startswith("g-"):
            self.hops.pop(thread, None)
        self.broadcast({"type": "thread_cleared", "thread": thread})
```

4. `update_agent`: a folder change resets every session:

```python
            if cwd != agent["cwd"]:
                # Claude Code keeps sessions per project folder; none of them can be resumed.
                fields.update(cwd=cwd)
                self.store.delete_sessions(agent_id=agent_id)
                self._post(agent_id, "system", "system",
                           f"Carpeta cambiada a {cwd}. La conversación empieza de cero.")
```

5. `delete_agent`: after `self.store.delete_agent(agent_id)`, broadcast groups too, since memberships may have changed:

```python
        self.broadcast({"type": "groups", "groups": self.store.groups()})
```

6. `send`:

```python
    async def send(self, thread, text, origin=None):
        self._post(thread, "user", "text", text)
        if self.is_group(thread):
            self.hops[thread] = 0
            self._route(thread, text, author=None, origin=origin)
        elif self.store.agent(thread):
            self._enqueue(thread, thread, text, origin)
```

7. Replace `_route` and `_group_prompt`:

```python
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

        lines = [f"[{who(m)}]: {m['content']}" for m in self.store.history(thread, limit=CONTEXT_MESSAGES)]
        prompt = ("Mensajes recientes de esta conversación grupal de HiveMind. Te mencionaron en el último. "
                  "Tu respuesta se publicará en el grupo.\n\n" + "\n".join(lines))
        # Bridge: what the agent and the user said in private, so status questions get real answers.
        private = [m for m in self.store.history(agent_id, limit=40) if m["kind"] == "text"][-PRIVATE_BRIDGE:]
        if private:
            prompt += ("\n\nTu chat privado reciente con el usuario (contexto, no lo repitas si no hace falta):\n"
                       + "\n".join(f"[{who(m)}]: {m['content'][:500]}" for m in private))
        return prompt
```

Add the module constant `PRIVATE_BRIDGE = 10` next to `MODELS`.

8. `_pump`: resume the session of this conversation, and remember the thread:

```python
            agent = {**agent, "session_id": self.store.session(agent_id, item[1])}
            turn = self.turn_factory(
                ...same arguments as before...)
            task = asyncio.get_running_loop().create_task(self._run(agent, item[1], turn, item[3]))
            self.running[agent_id] = (turn, task, item[1])
```

(Insert the `agent = {...}` line right after `if agent is None: continue`.)

9. `_run`: store the session per conversation, and route in any group:

```python
            if out["session_id"] and self.store.agent(agent_id):
                self.store.save_session(agent_id, thread, out["session_id"])
            if out["is_error"]:
                status = "error"
                self._post(thread, "system", "system", out["text"] or "El turno terminó con error.")
            elif self.is_group(thread):
                self._route(thread, out["text"], author=agent_id)
```

10. `delete_agent`, `stop` and `drain`: unpack the running entries as 3-tuples. `delete_agent` uses `entry[1]`, `stop` uses `entry[0]`, and `drain` uses `[t for _, t, _ in self.running.values()]`.

In `hivemind/routines.py`:
- `_check_target(target)` accepts a group: `if target != "group" and not self.store.group(target) and self.store.agent(target) is None:`.
- In `_fire`, the missing-target test becomes `if not self._target_exists(r["target"]):`, with this helper:

```python
    def _target_exists(self, target):
        return target == "group" or self.store.group(target) is not None or self.store.agent(target) is not None

    def pause_target(self, target):
        for r in self.store.routines():
            if r["target"] == target and r["enabled"]:
                self.store.update_routine(r["id"], enabled=False)
                self.hub._post("group", "system", "system", f"La rutina «{r['name']}» se pausó: su destino ya no existe.")
        self._changed()
```

Also change `_check_target` to use `_target_exists`, keeping the same Spanish error message.

- [ ] **Step 4: Run the suite** `.venv/bin/python -m unittest discover -s tests -t .`. Expected: OK. Fix any old test that unpacks `running` as a 2-tuple.
- [ ] **Step 5: Commit** with the message `feat: custom groups, per-conversation sessions with private bridge, and clearing conversations`.

---

### Task 3: Protocol

**Files:** Modify `hivemind/server.py`. Test: `tests/test_server.py`.

- [ ] **Step 1: Failing test.** Append to `ServerTest`:

```python
    async def test_group_and_clear_methods(self):
        a = (await self.call("create_agent", name="Dev", role="dev"))["result"]
        g = (await self.call("create_group", name="Lanzamiento", members=[a["id"]]))["result"]
        self.assertEqual(g["members"], [a["id"]])
        self.assertEqual((await self.call("update_group", group=g["id"], name="Campaña"))["result"]["name"], "Campaña")
        self.assertEqual(len((await self.call("list_groups"))["result"]), 1)
        await self.call("send", thread=g["id"], text="hola")
        await self.hub.drain()
        await self.call("clear_thread", thread=g["id"])
        self.assertEqual((await self.call("history", thread=g["id"]))["result"], [])
        await self.call("delete_group", group=g["id"])
        self.assertEqual((await self.call("list_groups"))["result"], [])
        self.assertIn("thread_cleared", self.events)
        self.assertIn("groups", self.events)
```

- [ ] **Step 2: Run** it. Expected: FAIL with `KeyError: 'result'`.
- [ ] **Step 3: Implement.** Add to `_dispatch`:

```python
    if method == "list_groups":
        return hub.store.groups()
    if method == "create_group":
        return hub.create_group(p["name"], p["members"])
    if method == "update_group":
        return hub.update_group(p["group"], p.get("name"), p.get("members"))
    if method == "delete_group":
        await hub.delete_group(p["group"])
        return True
    if method == "clear_thread":
        await hub.clear_thread(p["thread"])
        return True
```

- [ ] **Step 4: Run the suite.** Expected: OK.
- [ ] **Step 5: Commit** with the message `feat: groups and clearing over the socket`.

---

### Task 4: GTK — groups in the sidebar, group dialog, Limpiar / Nueva conversación

**Files:** Modify `hivemind/ui/window.py`, `hivemind/ui/dialogs.py`, `hivemind/ui/chat.py` and `hivemind/ui/routines.py`. Test: `tests/test_layout.py` (Broadway).

**Behaviour:**
- `window.groups` is loaded from `hello` and updated on the `groups` event.
- **Sidebar order:** Grupo, custom groups (thread = group id, `hivemind-hex-symbolic` icon, subtitle `f"{n} integrantes"`), Rutinas, Tablero, agents.
- **The "+" button** is a `Gtk.MenuButton` whose popover has two flat buttons, "Nuevo agente" and "Nuevo grupo".
- **Group dialog** (`dialogs.group_dialog(parent, agents, on_done, group=None)`): an `Adw.AlertDialog` with a name entry and one `Gtk.CheckButton` per agent. It calls `on_done({"name", "members"})`.
- **Header:** a "Limpiar" button (`edit-clear-all-symbolic`, tooltip "Limpiar conversación") is visible for every group and agent thread. ⚙ is visible for custom groups and agents: it opens the group dialog or the agent dialog. 🗑 is visible for custom groups and agents: it deletes the group or the agent, after confirmation.
- **Limpiar** confirms with an `Adw.AlertDialog`, using the spec copy, then calls `clear_thread`.
- **`thread_cleared`:** the open view for that thread calls `load(self.approvals)`, which reloads it empty.
- **`ChatView`:** its `is_group` flag is `thread == "group" or thread.startswith("g-")`. It uses the flag for the placeholder, the author labels and hiding the stop button.
- **Routines:** the target dropdown lists Grupo, then the custom groups, then the agents. The row label resolves group names.

- [ ] **Step 1: Failing test.** Append to `tests/test_layout.py`:

```python
    def test_sidebar_lists_custom_groups_after_grupo(self):
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, GLib
        from hivemind.ui import theme
        from hivemind.ui.window import MainWindow
        threads = []

        class App(Adw.Application):
            def do_activate(self):
                theme.install(Gdk.Display.get_default())
                self.win = MainWindow(self)
                self.win.present()
                self.win.agents = [{"id": "a1", "name": "Dev", "role": "dev", "model": None}]
                self.win.groups = [{"id": "g-1", "name": "Lanzamiento", "members": ["a1"]}]
                self.win._rebuild_sidebar()
                i = 0
                while (row := self.win.sidebar_list.get_row_at_index(i)):
                    threads.append(row.thread)
                    i += 1
                GLib.idle_add(self.quit)

        App(application_id="com.gogema.LayoutTest2").run([])
        self.assertEqual(threads, ["group", "g-1", "routines", "board", "a1"])
```

- [ ] **Step 2: Run on Broadway.** Expected: FAIL, because `threads` lacks `g-1`.
- [ ] **Step 3: Implement** the behaviour above. Keep the Alt+N shortcuts working in sidebar order.
- [ ] **Step 4: Run the full suite on Broadway**, plus the view contract test (`tests/test_ui_contract.py` already covers ChatView). Expected: OK.
- [ ] **Step 5: Commit** with the message `feat: groups, Limpiar and Nueva conversación in the window`.

---

### Task 5: Reinstall and live check

- [ ] Run `./install.sh`; expected: the service is active.
- [ ] `hello` via `.superpowers/drive.py` shows `groups: []`. Hori and Seior still resume their private memory, because `sessions` holds a row per agent for its own thread.
- [ ] Real turn: create a group with a throwaway Haiku agent, send a message, then `clear_thread`. The history is empty and the agent's group session is gone. Delete the throwaway agent.
- [ ] Update the README (Guía de uso → Grupos, Limpiar) and AGENTS.md (the new methods). Commit, then push.
