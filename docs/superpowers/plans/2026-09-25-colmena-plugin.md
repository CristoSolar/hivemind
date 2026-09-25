# Colmena Plugin, Routines and Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Colmena as an Omarchy plugin: a bar widget and panel for status and approvals, scheduled routines, a shared task board that agents drive through their own tools, and 8-bit chibi icons.

**Architecture:** The repo root becomes the plugin (`manifest.json` + `Panel.qml`). The panel speaks the existing socket protocol through Quickshell `Socket`. Routines and the board live in the daemon as two small modules owned by `Hub`:
- `routines.py`: a schedule tick that sends prompts through `Hub.send`.
- `board.py`: store operations plus an in-process SDK MCP server named `tablero`.

Pure schedule maths lives in `schedule.py`. The GTK window gains two views: `ui/routines.py` and `ui/board.py`.

**Tech Stack:** Python 3.14 stdlib, claude-agent-sdk 0.2.x (`create_sdk_mcp_server`, `tool`), GTK4/libadwaita via PyGObject, QML with Quickshell (`Quickshell.Io.Socket`, `Process`, `SplitParser`) and the Omarchy shell modules `qs.Commons` and `qs.Ui`.

**Spec:** `docs/superpowers/specs/2026-09-25-colmena-plugin-design.md` (builds on `2026-09-24-colmena-design.md`).

## Global Constraints

- Plugin id `gogema.colmena`, kinds `["bar-widget"]`, `entryPoints.barWidget = "Panel.qml"`, `defaultSection = "right"`. `omarchy-plugin-validate .` must pass. No symlinks in the repo.
- Schedule forms, exactly:
  - `{"every_hours": N}` with N from 1 to 168;
  - `{"daily": "HH:MM"}`;
  - `{"weekly": {"days": [0..6], "time": "HH:MM"}}`, where 0 is Monday.
  - All times are local.
- A missed routine runs once on return, and its `next_run` is computed from the actual run time.
- Board statuses are `todo`, `doing` and `done`, shown as "Por hacer", "En curso" and "Listo".
- Board tools are `tablero_listar`, `tablero_crear`, `tablero_mover` and `tablero_asignar`, on the MCP server `tablero`. They appear to the CLI as `mcp__tablero__<tool>` and are always permitted.
- The UI copy is in Spanish. Tests use stdlib `unittest` only. Never put scratch files in `/tmp`; use `~/.cache/tmp`.
- Never drive the user's screen (no focus changes, `wtype` or screenshots of the live desktop). For GTK smoke checks use `GDK_BACKEND=broadway` with `gtk4-broadwayd :7`.
- Run commands from `~/Repositorios/colmena` with `.venv/bin/python`. The full suite is `.venv/bin/python -m unittest discover -s tests -t .`

## Review Focus

1. A routine targeting an agent that was deleted must pause with a notice in the group, never crash the tick. Pinned in Task 4.
2. An agent passing an unknown task id, agent name or status to a board tool gets an error text, and nothing changes. Pinned in Task 3.
3. A daily or weekly routine around midnight, month end or year end computes the correct next run. Pinned in Task 1.
4. The daemon restarting while the panel is connected: the panel must reconnect rather than show stale approvals. This is QML and is checked by reading `Panel.qml` (retry `Timer`, state cleared on disconnect). Pinned by `tests/test_plugin.py` in Task 8.
5. Invalid schedule input from the UI (hour 25, empty weekday list, `every_hours: 0`) is rejected with a Spanish error and not stored. Pinned in Task 1 and Task 4.

---

## File Structure

```
manifest.json               plugin manifest (new)
Panel.qml                   bar widget + quick panel (new)
tools/pixel_icons.py        ASCII-grid → SVG generator for the 8-bit icons (new)
colmena/schedule.py         validate / next_run / describe (new)
colmena/store.py            + routines, tasks, task_log tables (modify)
colmena/board.py            Board: task ops + MCP server for agents (new)
colmena/routines.py         Routines: CRUD + tick + run_now (new)
colmena/hub.py              own Board/Routines, origin tag, mcp_servers per turn (modify)
colmena/runner.py           mcp_servers option, board tools always permitted (modify)
colmena/server.py           routine/task methods (modify)
colmena/daemon.py           tick routines every 30 s (modify)
colmena/ui/icons/*.svg      regenerated pixel icons (modify)
colmena/ui/routines.py      RoutinesView + routine dialog (new)
colmena/ui/board.py         BoardView + task dialogs (new)
colmena/ui/window.py        sidebar entries Rutinas / Tablero (modify)
tests/test_schedule.py test_board.py test_routines.py test_plugin.py test_icons.py (new)
tests/test_store.py test_hub.py test_server.py (modify)
README.md                   plugin install section (modify)
```

---

### Task 1: Schedule maths

**Files:**
- Create: `colmena/schedule.py`, `tests/test_schedule.py`

**Interfaces:**
- Produces:
  - `validate(s: dict) -> dict`: returns the normalized schedule or raises `ValueError` with a Spanish message.
  - `next_run(s: dict, after: datetime) -> datetime`: the first run strictly after `after`, as a naive local datetime.
  - `describe(s: dict) -> str`: for example "Cada 3 horas", "Todos los días 09:00" or "Lunes y Jueves 09:00".
  - `DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]`

- [ ] **Step 1: Write the failing test** `tests/test_schedule.py`

```python
import unittest
from datetime import datetime

from colmena.schedule import describe, next_run, validate


class ScheduleTest(unittest.TestCase):
    def test_every_hours(self):
        self.assertEqual(next_run({"every_hours": 3}, datetime(2026, 9, 25, 10, 15)), datetime(2026, 9, 25, 13, 15))

    def test_daily_before_and_after_time(self):
        s = {"daily": "09:00"}
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 8, 59)), datetime(2026, 9, 25, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 9, 0)), datetime(2026, 9, 26, 9, 0))

    def test_daily_month_and_year_end(self):
        self.assertEqual(next_run({"daily": "00:30"}, datetime(2026, 12, 31, 23, 0)), datetime(2027, 1, 1, 0, 30))
        self.assertEqual(next_run({"daily": "07:00"}, datetime(2026, 2, 28, 8, 0)), datetime(2026, 3, 1, 7, 0))

    def test_weekly_across_week_boundary(self):
        s = {"weekly": {"days": [0, 3], "time": "09:00"}}  # lunes y jueves
        # 2026-09-25 is a Friday
        self.assertEqual(next_run(s, datetime(2026, 9, 25, 12, 0)), datetime(2026, 9, 28, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 28, 9, 0)), datetime(2026, 10, 1, 9, 0))
        self.assertEqual(next_run(s, datetime(2026, 9, 28, 8, 0)), datetime(2026, 9, 28, 9, 0))

    def test_validate_rejects_bad_input(self):
        for bad in ({"every_hours": 0}, {"every_hours": 169}, {"every_hours": "3"}, {"daily": "25:00"},
                    {"daily": "9"}, {"weekly": {"days": [], "time": "09:00"}},
                    {"weekly": {"days": [7], "time": "09:00"}}, {}, {"daily": "09:00", "every_hours": 1}):
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)

    def test_validate_normalizes(self):
        self.assertEqual(validate({"daily": "9:05"}), {"daily": "09:05"})
        self.assertEqual(validate({"weekly": {"days": [3, 0, 3], "time": "18:30"}}),
                         {"weekly": {"days": [0, 3], "time": "18:30"}})

    def test_describe(self):
        self.assertEqual(describe({"every_hours": 1}), "Cada hora")
        self.assertEqual(describe({"every_hours": 3}), "Cada 3 horas")
        self.assertEqual(describe({"daily": "09:00"}), "Todos los días 09:00")
        self.assertEqual(describe({"weekly": {"days": [0, 3], "time": "09:00"}}), "Lunes y Jueves 09:00")
        self.assertEqual(describe({"weekly": {"days": [0, 2, 4], "time": "07:30"}}), "Lunes, Miércoles y Viernes 07:30")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_schedule -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'colmena.schedule'`

- [ ] **Step 3: Write implementation** `colmena/schedule.py`

```python
from datetime import datetime, timedelta

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _time(value):
    try:
        h, m = (int(x) for x in str(value).split(":"))
    except ValueError:
        raise ValueError(f"Hora inválida: {value}. Usa HH:MM.") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Hora inválida: {value}. Usa HH:MM.")
    return h, m


def validate(s):
    if not isinstance(s, dict) or len(s) != 1:
        raise ValueError("Elige una sola forma de repetir la rutina.")
    (kind, value), = s.items()
    if kind == "every_hours":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 168:
            raise ValueError("Las horas deben ser un número entre 1 y 168.")
        return {"every_hours": value}
    if kind == "daily":
        h, m = _time(value)
        return {"daily": f"{h:02d}:{m:02d}"}
    if kind == "weekly":
        days = sorted(set(value.get("days") or [])) if isinstance(value, dict) else []
        if not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ValueError("Elige al menos un día de la semana.")
        h, m = _time(value.get("time"))
        return {"weekly": {"days": days, "time": f"{h:02d}:{m:02d}"}}
    raise ValueError(f"Forma de repetición desconocida: {kind}.")


def next_run(s, after):
    s = validate(s)
    if "every_hours" in s:
        return after + timedelta(hours=s["every_hours"])
    if "daily" in s:
        h, m = _time(s["daily"])
        candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
        return candidate if candidate > after else candidate + timedelta(days=1)
    h, m = _time(s["weekly"]["time"])
    for offset in range(8):
        day = after + timedelta(days=offset)
        candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
        if day.weekday() in s["weekly"]["days"] and candidate > after:
            return candidate
    raise AssertionError("unreachable: a weekly schedule always fires within 8 days")


def _join(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def describe(s):
    s = validate(s)
    if "every_hours" in s:
        n = s["every_hours"]
        return "Cada hora" if n == 1 else f"Cada {n} horas"
    if "daily" in s:
        return f"Todos los días {s['daily']}"
    return f"{_join([DAYS[d] for d in s['weekly']['days']])} {s['weekly']['time']}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_schedule -v`
Expected: 7 tests OK

- [ ] **Step 5: Commit**

```bash
git add colmena/schedule.py tests/test_schedule.py
git commit -m "feat: add routine schedule maths"
```

---

### Task 2: Store tables for routines and tasks

**Files:**
- Modify: `colmena/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces (Store methods):
  - `create_routine(name, target, prompt, schedule: dict, next_run: float) -> dict`, `routines() -> list[dict]`, `routine(id) -> dict|None`, `update_routine(id, **fields)` (fields: `name, target, prompt, schedule, enabled, last_run, next_run`), `delete_routine(id)`
  - Routine dict: `{id, name, target, prompt, schedule: dict, enabled: bool, last_run, next_run, created_at}`
  - `create_task(title, description, assignee, created_by) -> dict`, `tasks(status=None) -> list[dict]` (ordered by `created_at`), `task(id) -> dict|None`, `update_task(id, **fields)` (fields: `title, description, status, assignee`; sets `updated_at`), `delete_task(id)` (also deletes its log), `add_task_log(task_id, actor, text)`, `task_log(task_id) -> list[dict]`
  - Task dict: `{id, title, description, status, assignee, created_by, created_at, updated_at}`; new tasks have `status="todo"`

- [ ] **Step 1: Write the failing test**. Append to `tests/test_store.py` before `if __name__`:

```python
    def test_routines(self):
        r = self.s.create_routine("Resumen", "group", "resume", {"daily": "09:00"}, 100.0)
        self.assertEqual((r["schedule"], r["enabled"], r["last_run"]), ({"daily": "09:00"}, True, None))
        self.s.update_routine(r["id"], enabled=False, last_run=50.0, next_run=200.0, schedule={"every_hours": 2})
        got = self.s.routine(r["id"])
        self.assertEqual((got["enabled"], got["last_run"], got["next_run"], got["schedule"]),
                         (False, 50.0, 200.0, {"every_hours": 2}))
        self.assertEqual(len(self.s.routines()), 1)
        with self.assertRaises(ValueError):
            self.s.update_routine(r["id"], nope=1)
        self.s.delete_routine(r["id"])
        self.assertEqual(self.s.routines(), [])

    def test_tasks_and_log(self):
        t = self.s.create_task("Landing", "hero nuevo", None, "user")
        self.assertEqual((t["status"], t["assignee"], t["created_by"]), ("todo", None, "user"))
        self.s.update_task(t["id"], status="doing", assignee="a1")
        got = self.s.task(t["id"])
        self.assertEqual((got["status"], got["assignee"]), ("doing", "a1"))
        self.assertGreaterEqual(got["updated_at"], got["created_at"])
        self.assertEqual([x["id"] for x in self.s.tasks("doing")], [t["id"]])
        self.assertEqual(self.s.tasks("done"), [])
        self.s.add_task_log(t["id"], "user", "creó la tarea")
        self.assertEqual([x["text"] for x in self.s.task_log(t["id"])], ["creó la tarea"])
        with self.assertRaises(ValueError):
            self.s.update_task(t["id"], created_by="x")
        self.s.delete_task(t["id"])
        self.assertIsNone(self.s.task(t["id"]))
        self.assertEqual(self.s.task_log(t["id"]), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_store -v`
Expected: FAIL with `AttributeError: 'Store' object has no attribute 'create_routine'`

- [ ] **Step 3: Implement**. Append to the `SCHEMA` string in `colmena/store.py` (before the closing `"""`):

```sql
create table if not exists routines(
  id text primary key, name text not null, target text not null, prompt text not null,
  schedule text not null, enabled integer not null default 1, last_run real,
  next_run real not null, created_at real not null);
create table if not exists tasks(
  id text primary key, title text not null, description text not null default '',
  status text not null default 'todo', assignee text, created_by text not null,
  created_at real not null, updated_at real not null);
create table if not exists task_log(
  id integer primary key, task_id text not null, actor text not null, text text not null, ts real not null);
```

Add these methods to `Store`:

```python
    # routines ---------------------------------------------------------------
    def _routine(self, row):
        if row is None:
            return None
        d = dict(row)
        d["schedule"] = json.loads(d["schedule"])
        d["enabled"] = bool(d["enabled"])
        return d

    def create_routine(self, name, target, prompt, schedule, next_run):
        r = {"id": _new_id(), "name": name, "target": target, "prompt": prompt,
             "schedule": json.dumps(schedule), "next_run": next_run, "created_at": time.time()}
        with self.db:
            self.db.execute(
                "insert into routines(id, name, target, prompt, schedule, next_run, created_at)"
                " values(:id, :name, :target, :prompt, :schedule, :next_run, :created_at)", r)
        return self.routine(r["id"])

    def routines(self):
        return [self._routine(r) for r in self.db.execute("select * from routines order by created_at")]

    def routine(self, id):
        return self._routine(self.db.execute("select * from routines where id = ?", (id,)).fetchone())

    def update_routine(self, id, **fields):
        allowed = {"name", "target", "prompt", "schedule", "enabled", "last_run", "next_run"}
        if set(fields) - allowed:
            raise ValueError(f"Campos desconocidos: {set(fields) - allowed}")
        if "schedule" in fields:
            fields["schedule"] = json.dumps(fields["schedule"])
        if "enabled" in fields:
            fields["enabled"] = int(bool(fields["enabled"]))
        with self.db:
            for key, value in fields.items():
                self.db.execute(f"update routines set {key} = ? where id = ?", (value, id))

    def delete_routine(self, id):
        with self.db:
            self.db.execute("delete from routines where id = ?", (id,))

    # tasks ------------------------------------------------------------------
    def create_task(self, title, description, assignee, created_by):
        now = time.time()
        t = {"id": _new_id(), "title": title, "description": description or "", "assignee": assignee,
             "created_by": created_by, "created_at": now, "updated_at": now}
        with self.db:
            self.db.execute(
                "insert into tasks(id, title, description, assignee, created_by, created_at, updated_at)"
                " values(:id, :title, :description, :assignee, :created_by, :created_at, :updated_at)", t)
        return self.task(t["id"])

    def tasks(self, status=None):
        if status:
            rows = self.db.execute("select * from tasks where status = ? order by created_at", (status,))
        else:
            rows = self.db.execute("select * from tasks order by created_at")
        return [dict(r) for r in rows]

    def task(self, id):
        row = self.db.execute("select * from tasks where id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, id, **fields):
        allowed = {"title", "description", "status", "assignee"}
        if set(fields) - allowed:
            raise ValueError(f"Campos desconocidos: {set(fields) - allowed}")
        with self.db:
            for key, value in fields.items():
                self.db.execute(f"update tasks set {key} = ? where id = ?", (value, id))
            self.db.execute("update tasks set updated_at = ? where id = ?", (time.time(), id))

    def delete_task(self, id):
        with self.db:
            self.db.execute("delete from tasks where id = ?", (id,))
            self.db.execute("delete from task_log where task_id = ?", (id,))

    def add_task_log(self, task_id, actor, text):
        with self.db:
            self.db.execute("insert into task_log(task_id, actor, text, ts) values(?, ?, ?, ?)",
                            (task_id, actor, text, time.time()))

    def task_log(self, task_id):
        rows = self.db.execute("select * from task_log where task_id = ? order by id", (task_id,))
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_store -v`
Expected: all store tests OK

- [ ] **Step 5: Commit**

```bash
git add colmena/store.py tests/test_store.py
git commit -m "feat: store routines, tasks and task log"
```

---

### Task 3: Board (task operations and agent tools)

**Files:**
- Create: `colmena/board.py`, `tests/test_board.py`
- Modify: `colmena/runner.py` (the `mcp_servers` option and an always-permitted `mcp__tablero__*`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Store` task methods (Task 2); a `hub` object with `.store`, `.broadcast(event)` and `.store.agents()`.
- Produces:
  - `STATUSES = {"todo": "Por hacer", "doing": "En curso", "done": "Listo"}`
  - `class Board(hub)` with these methods:
    - `list(status=None) -> list[dict]`: each task dict gets an added `assignee_name`.
    - `create(title, description="", assignee=None, actor="user") -> dict`
    - `update(task_id, actor="user", **fields) -> dict`
    - `delete(task_id, actor="user")`
    - `log(task_id) -> list[dict]`
    - `mcp_server(agent_id) -> McpSdkServerConfig`
    - `tools(agent_id) -> list[SdkMcpTool]`, exposed for tests.
  - `assignee` accepts an agent id, an agent name (case-insensitive), or `None`/`""` to unassign. `status` accepts `todo|doing|done` and the Spanish labels, case-insensitive. Invalid input raises `ValueError` in Spanish.
  - Every change calls `hub.broadcast({"type": "tasks", "tasks": board.list()})` and writes a log row.
  - `runner.Turn(..., mcp_servers=None)`: when given, it is passed as `ClaudeAgentOptions(mcp_servers=...)`. `BOARD_RULE = "mcp__tablero__*"` is always permitted.

- [ ] **Step 1: Write the failing test** `tests/test_board.py`

```python
import asyncio
import unittest

from colmena.board import Board
from colmena.store import Store


class FakeHub:
    def __init__(self):
        self.store = Store(":memory:")
        self.events = []

    def broadcast(self, ev):
        self.events.append(ev)


def call(tool, **args):
    return asyncio.run(tool.handler(args))


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()
        self.addCleanup(self.hub.store.db.close)
        self.hori = self.hub.store.create_agent("Hori", "marketing", "/tmp")
        self.board = Board(self.hub)

    def test_user_crud_logs_and_broadcasts(self):
        t = self.board.create("Landing", "hero", assignee="hori")
        self.assertEqual((t["assignee"], t["assignee_name"]), (self.hori["id"], "Hori"))
        self.board.update(t["id"], status="En curso")
        self.assertEqual(self.hub.store.task(t["id"])["status"], "doing")
        self.board.update(t["id"], assignee="")
        self.assertIsNone(self.hub.store.task(t["id"])["assignee"])
        self.assertEqual(self.hub.events[-1]["type"], "tasks")
        self.assertEqual(len(self.board.log(t["id"])), 3)
        self.board.delete(t["id"])
        self.assertEqual(self.board.list(), [])

    def test_invalid_input_changes_nothing(self):
        t = self.board.create("Landing")
        for bad in ({"status": "volando"}, {"assignee": "Nadie"}, {"title": "  "}):
            with self.assertRaises(ValueError):
                self.board.update(t["id"], **bad)
        with self.assertRaises(ValueError):
            self.board.update("no-existe", status="done")
        with self.assertRaises(ValueError):
            self.board.create("")
        self.assertEqual(self.hub.store.task(t["id"])["status"], "todo")

    def test_agent_tools(self):
        tools = {t.name: t for t in self.board.tools(self.hori["id"])}
        self.assertEqual(set(tools), {"tablero_listar", "tablero_crear", "tablero_mover", "tablero_asignar"})
        out = call(tools["tablero_crear"], titulo="Copy Meta", asignado="Hori")
        self.assertFalse(out.get("is_error"))
        task = self.hub.store.tasks()[0]
        self.assertEqual((task["created_by"], task["assignee"]), (self.hori["id"], self.hori["id"]))
        self.assertIn("Copy Meta", call(tools["tablero_listar"])["content"][0]["text"])
        self.assertFalse(call(tools["tablero_mover"], id=task["id"], estado="listo").get("is_error"))
        self.assertEqual(self.hub.store.task(task["id"])["status"], "done")
        self.assertIn("Hori", self.board.log(task["id"])[-1]["text"])

    def test_agent_tool_errors_are_text(self):
        tools = {t.name: t for t in self.board.tools(self.hori["id"])}
        for name, args in (("tablero_mover", {"id": "x", "estado": "done"}),
                           ("tablero_asignar", {"id": "x", "agente": "Hori"}),
                           ("tablero_crear", {"titulo": ""})):
            out = call(tools[name], **args)
            self.assertTrue(out["is_error"], name)
            self.assertIsInstance(out["content"][0]["text"], str)


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_runner.py` (inside `RunnerTest`):

```python
    def test_board_tools_always_permitted_and_server_passed(self):
        script = [AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__tablero__tablero_mover",
                                                         input={"id": "x", "estado": "done"})], model="m"),
                  result()]
        clients, asked = [], []

        async def ask(*a):
            asked.append(a)
            return "deny"

        def factory(options):
            clients.append(FakeClient(options, script))
            return clients[-1]

        asyncio.run(Turn(AGENT, ROLE, "hola", lambda e: None, ask, mcp_servers={"tablero": "srv"},
                         client_factory=factory).run())
        self.assertEqual(asked, [])
        self.assertEqual(clients[0].options.mcp_servers, {"tablero": "srv"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_board tests.test_runner -v`
Expected: FAIL: `No module named 'colmena.board'`, and a `TypeError` for the unexpected `mcp_servers` kwarg.

- [ ] **Step 3: Implement** `colmena/board.py`

```python
from claude_agent_sdk import create_sdk_mcp_server, tool

STATUSES = {"todo": "Por hacer", "doing": "En curso", "done": "Listo"}
_STATUS_ALIASES = {"todo": "todo", "por hacer": "todo", "pendiente": "todo",
                   "doing": "doing", "en curso": "doing", "haciendo": "doing",
                   "done": "done", "listo": "done", "hecho": "done", "terminado": "done"}


def _text(message, error=False):
    out = {"content": [{"type": "text", "text": message}]}
    if error:
        out["is_error"] = True
    return out


class Board:
    def __init__(self, hub):
        self.hub = hub

    @property
    def store(self):
        return self.hub.store

    def _names(self):
        return {a["id"]: a["name"] for a in self.store.agents()}

    def _actor(self, actor):
        return "Usuario" if actor == "user" else self._names().get(actor, "?")

    def _status(self, value):
        status = _STATUS_ALIASES.get(str(value).strip().lower())
        if status is None:
            raise ValueError(f"Estado desconocido: {value}. Usa Por hacer, En curso o Listo.")
        return status

    def _assignee(self, value):
        if value in (None, ""):
            return None
        for a in self.store.agents():
            if value == a["id"] or str(value).casefold() == a["name"].casefold():
                return a["id"]
        raise ValueError(f"No hay un agente llamado {value}.")

    def _task(self, task_id):
        task = self.store.task(task_id)
        if task is None:
            raise ValueError(f"No existe la tarea {task_id}.")
        return task

    def _changed(self):
        self.hub.broadcast({"type": "tasks", "tasks": self.list()})

    def list(self, status=None):
        names = self._names()
        return [{**t, "assignee_name": names.get(t["assignee"])}
                for t in self.store.tasks(self._status(status) if status else None)]

    def create(self, title, description="", assignee=None, actor="user"):
        title = (title or "").strip()
        if not title:
            raise ValueError("La tarea necesita un título.")
        task = self.store.create_task(title, description or "", self._assignee(assignee), actor)
        self.store.add_task_log(task["id"], actor, f"{self._actor(actor)} creó la tarea")
        self._changed()
        return next(t for t in self.list() if t["id"] == task["id"])

    def update(self, task_id, actor="user", **fields):
        task = self._task(task_id)
        changes, notes = {}, []
        if "title" in fields:
            title = (fields["title"] or "").strip()
            if not title:
                raise ValueError("La tarea necesita un título.")
            changes["title"] = title
        if "description" in fields:
            changes["description"] = fields["description"] or ""
        if "status" in fields:
            changes["status"] = self._status(fields["status"])
            notes.append(f"movió la tarea a {STATUSES[changes['status']]}")
        if "assignee" in fields:
            changes["assignee"] = self._assignee(fields["assignee"])
            who = self._names().get(changes["assignee"])
            notes.append(f"asignó la tarea a {who}" if who else "dejó la tarea sin asignar")
        if not changes:
            return next(t for t in self.list() if t["id"] == task["id"])
        self.store.update_task(task_id, **changes)
        for note in notes or ["editó la tarea"]:
            self.store.add_task_log(task_id, actor, f"{self._actor(actor)} {note}")
        self._changed()
        return next(t for t in self.list() if t["id"] == task_id)

    def delete(self, task_id, actor="user"):
        self._task(task_id)
        self.store.delete_task(task_id)
        self._changed()

    def log(self, task_id):
        return self.store.task_log(task_id)

    # agent tools ------------------------------------------------------------
    def tools(self, agent_id):
        def guarded(fn):
            async def handler(args):
                try:
                    return _text(fn(args))
                except ValueError as e:
                    return _text(str(e), error=True)
            return handler

        def listar(args):
            tasks = self.list(args.get("estado"))
            if not tasks:
                return "El tablero está vacío."
            return "\n".join(f"[{t['id']}] {STATUSES[t['status']]} · {t['title']}"
                             f" · {t['assignee_name'] or 'sin asignar'}" for t in tasks)

        def crear(args):
            t = self.create(args.get("titulo"), args.get("descripcion", ""), args.get("asignado"), actor=agent_id)
            return f"Creada la tarea [{t['id']}] {t['title']}."

        def mover(args):
            t = self.update(args.get("id"), actor=agent_id, status=args.get("estado"))
            return f"[{t['id']}] ahora está en {STATUSES[t['status']]}."

        def asignar(args):
            t = self.update(args.get("id"), actor=agent_id, assignee=args.get("agente"))
            return f"[{t['id']}] asignada a {t['assignee_name'] or 'nadie'}."

        schema = lambda props, required=(): {"type": "object", "properties": props, "required": list(required)}
        s = {"type": "string"}
        return [
            tool("tablero_listar", "Lista las tareas del tablero compartido de Colmena. Filtra por estado opcional: "
                 "Por hacer, En curso o Listo.", schema({"estado": s}))(guarded(listar)),
            tool("tablero_crear", "Crea una tarea en el tablero compartido. Asigna a un agente por su nombre si quieres.",
                 schema({"titulo": s, "descripcion": s, "asignado": s}, ["titulo"]))(guarded(crear)),
            tool("tablero_mover", "Cambia el estado de una tarea: Por hacer, En curso o Listo.",
                 schema({"id": s, "estado": s}, ["id", "estado"]))(guarded(mover)),
            tool("tablero_asignar", "Asigna una tarea a un agente por su nombre, o déjala sin asignar con agente vacío.",
                 schema({"id": s, "agente": s}, ["id"]))(guarded(asignar)),
        ]

    def mcp_server(self, agent_id):
        return create_sdk_mcp_server("tablero", tools=self.tools(agent_id))
```

In `colmena/runner.py`:
- add `BOARD_RULE = "mcp__tablero__*"` below `DENY_MESSAGE`;
- add a `mcp_servers=None` parameter to `Turn.__init__`, stored as `self.mcp_servers`;
- in `_can_use`, change the rules line to `rules = [BOARD_RULE] + self.role["allowed_tools"] + self.agent["extra_allowed"]`;
- in `_options`, add `mcp_servers=self.mcp_servers or {},`.

The exact edits:

```python
DENY_MESSAGE = "El usuario denegó esta acción"
BOARD_RULE = "mcp__tablero__*"
```

```python
    def __init__(self, agent, role, prompt, emit, ask, model=None, env=None, mcp_servers=None,
                 client_factory=ClaudeSDKClient):
        ...
        self.env = env
        self.mcp_servers = mcp_servers
```

```python
        rules = [BOARD_RULE] + self.role["allowed_tools"] + self.agent["extra_allowed"]
```

```python
            env=self.env or {},
            mcp_servers=self.mcp_servers or {},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_board tests.test_runner -v`
Expected: all OK. If `tool(...)(handler)` requires the handler to be `async def` taking `args`, the `guarded` wrapper already satisfies that. If the SDK rejects a JSON Schema dict, change `schema(...)` to the dict-style `{"titulo": str}` and record a ruling.

- [ ] **Step 5: Commit**

```bash
git add colmena/board.py colmena/runner.py tests/test_board.py tests/test_runner.py
git commit -m "feat: add shared task board with agent tools"
```

---

### Task 4: Routines and hub wiring

**Files:**
- Create: `colmena/routines.py`, `tests/test_routines.py`
- Modify: `colmena/hub.py`, `colmena/daemon.py`, `tests/test_hub.py` (FakeTurn accepts `**kw`)

**Interfaces:**
- Consumes: `schedule.validate/next_run` (Task 1), the Store routine methods (Task 2) and `Board` (Task 3).
- Produces:
  - `class Routines(hub)` with these methods:
    - `list() -> list[dict]`
    - `create(name, target, prompt, schedule, now=None) -> dict`
    - `update(routine_id, now=None, **fields) -> dict`
    - `delete(routine_id)`
    - `async run_now(routine_id)`
    - `async tick(now=None)`
  - `target` is `"group"` or an existing agent id (checked). A change to `schedule` recomputes `next_run`.
  - Every change broadcasts `{"type": "routines", "routines": [...]}`.
  - Changes to `Hub`:
    - `self.board = Board(self)` and `self.routines = Routines(self)`;
    - `send(thread, text, origin=None)`;
    - queue items become `(agent_id, thread, prompt, origin)`;
    - `_pump` passes `mcp_servers={"tablero": self.board.mcp_server(agent_id)}` to `turn_factory`;
    - when a turn whose `origin` is a routine finishes and no client is connected, it calls `notifier(f"Rutina «{name}» lista", text[:200])`;
    - `snapshot()` adds `routines` and `tasks`.
  - `daemon._main` calls `await hub.routines.tick()` every 30 s (every 6th 5-second loop).

- [ ] **Step 1: Write the failing test** `tests/test_routines.py`

```python
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

    def test_snapshot_includes_routines_and_tasks(self):
        self.hub.routines.create("R", "group", "hola", {"every_hours": 1})
        self.hub.board.create("Tarea")
        snap = self.hub.snapshot()
        self.assertEqual((len(snap["routines"]), len(snap["tasks"])), (1, 1))


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_hub.py`, change the FakeTurn constructor signature so it accepts the new kwarg:

```python
    def __init__(self, agent, role, prompt, emit, ask, model=None, env=None, **kw):
```

Also append this hub test (inside `HubTest`):

```python
    async def test_turn_gets_board_server(self):
        seen = {}

        class SpyTurn(FakeTurn):
            def __init__(self, *a, mcp_servers=None, **kw):
                seen["servers"] = mcp_servers
                super().__init__(*a, **kw)

        self.hub.turn_factory = SpyTurn
        a = self.hub.create_agent("Dev", "dev")
        await self.hub.send(a["id"], "hola")
        await self.hub.drain()
        self.assertEqual(list(seen["servers"]), ["tablero"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_routines tests.test_hub -v`
Expected: FAIL: `AttributeError: 'Hub' object has no attribute 'routines'`, and a `KeyError`/`None` on `seen["servers"]`.

- [ ] **Step 3: Implement** `colmena/routines.py`

```python
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
```

Modify `colmena/hub.py`:

1. Imports:
```python
from colmena.board import Board
from colmena.routines import Routines
```
2. At the end of `Hub.__init__`:
```python
        self.board = Board(self)
        self.routines = Routines(self)
```
3. `snapshot()` adds these two entries:
```python
                "routines": self.routines.list(), "tasks": self.board.list(),
```
4. Replace `send`, `_route`'s signature and fan-out, and `_enqueue` so an `origin` travels with the item:
```python
    async def send(self, thread, text, origin=None):
        self._post(thread, "user", "text", text)
        if thread == "group":
            self.hops = 0
            self._route(text, author=None, origin=origin)
        elif self.store.agent(thread):
            self._enqueue(thread, thread, text, origin)
```
In `_route`, change the signature to `def _route(self, text, author, origin=None):`, and in its final loop use `self._enqueue(a["id"], "group", prompt, origin)`.
```python
    def _enqueue(self, agent_id, thread, prompt, origin=None):
        self.queue.append((agent_id, thread, prompt, origin))
        if agent_id not in self.running:
            self._status(agent_id, "queued")
        self._pump()
```
5. In `_pump`, pass the board server and the origin:
```python
            turn = self.turn_factory(
                agent, self.roles[agent["role"]], item[2],
                emit=lambda ev, a=agent_id, t=item[1]: self._on_event(a, t, ev),
                ask=lambda tool, inp, rule, a=agent_id: self._ask(a, tool, inp, rule),
                model=self.config.get("model"), env=self._env(),
                mcp_servers={"tablero": self.board.mcp_server(agent_id)})
            task = asyncio.get_running_loop().create_task(self._run(agent, item[1], turn, item[3]))
```
6. `_run` gains `origin=None`. After a successful turn (the `elif thread == "group"` routing branch stays as it is), add:
```python
            if origin and not self.clients:
                self.notifier(f"Rutina «{origin['routine']}» lista", (out["text"] or "")[:200])
```
Place it right after the `if out["is_error"]: ... elif thread == "group": ...` block, inside the `try`.

Modify `colmena/daemon.py` so the loop becomes:
```python
    async with server:
        beat = 0
        while True:
            await asyncio.sleep(5)
            await hub.sample_memory()
            beat += 1
            if beat % 6 == 0:  # every 30 s
                await hub.routines.tick()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK` (every test, old and new).

- [ ] **Step 5: Commit**

```bash
git add colmena/routines.py colmena/hub.py colmena/daemon.py tests/test_routines.py tests/test_hub.py
git commit -m "feat: add scheduled routines and wire board and routines into the hub"
```

---

### Task 5: Protocol methods

**Files:**
- Modify: `colmena/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `hub.routines.*` and `hub.board.*` (Tasks 3 and 4).
- Produces these methods:
  - `list_routines`
  - `create_routine {name, target, prompt, schedule}`
  - `update_routine {routine, ...fields}`
  - `delete_routine {routine}`
  - `run_routine_now {routine}`
  - `list_tasks {status?}`
  - `create_task {title, description?, assignee?}`
  - `update_task {task, ...fields}`
  - `delete_task {task}`
  - `task_log {task}`

- [ ] **Step 1: Write the failing test**. Append inside `ServerTest`:

```python
    async def test_routine_and_task_methods(self):
        r = (await self.call("create_routine", name="R", target="group", prompt="hola",
                             schedule={"daily": "09:00"}))["result"]
        self.assertEqual(r["schedule"], {"daily": "09:00"})
        self.assertIn("error", await self.call("create_routine", name="R", target="group", prompt="hola",
                                               schedule={"daily": "99:00"}))
        got = (await self.call("update_routine", routine=r["id"], enabled=False))["result"]
        self.assertFalse(got["enabled"])
        self.assertEqual(len((await self.call("list_routines"))["result"]), 1)
        await self.call("delete_routine", routine=r["id"])
        t = (await self.call("create_task", title="Landing"))["result"]
        self.assertEqual((await self.call("update_task", task=t["id"], status="done"))["result"]["status"], "done")
        self.assertEqual(len((await self.call("task_log", task=t["id"]))["result"]), 2)
        self.assertEqual(len((await self.call("list_tasks", status="done"))["result"]), 1)
        await self.call("delete_task", task=t["id"])
        self.assertEqual((await self.call("list_tasks"))["result"], [])
        self.assertIn("routines", self.events)
        self.assertIn("tasks", self.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_server -v`
Expected: FAIL: `KeyError: 'result'` (the method is unknown, so an error comes back).

- [ ] **Step 3: Implement**. Add to `_dispatch` in `colmena/server.py`, before the final `raise`:

```python
    if method == "list_routines":
        return hub.routines.list()
    if method == "create_routine":
        return hub.routines.create(p["name"], p["target"], p["prompt"], p["schedule"])
    if method == "update_routine":
        fields = {k: p[k] for k in ("name", "target", "prompt", "schedule", "enabled") if k in p}
        return hub.routines.update(p["routine"], **fields)
    if method == "delete_routine":
        hub.routines.delete(p["routine"])
        return True
    if method == "run_routine_now":
        await hub.routines.run_now(p["routine"])
        return True
    if method == "list_tasks":
        return hub.board.list(p.get("status"))
    if method == "create_task":
        return hub.board.create(p["title"], p.get("description", ""), p.get("assignee"))
    if method == "update_task":
        fields = {k: p[k] for k in ("title", "description", "status", "assignee") if k in p}
        return hub.board.update(p["task"], **fields)
    if method == "delete_task":
        hub.board.delete(p["task"])
        return True
    if method == "task_log":
        return hub.board.log(p["task"])
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add colmena/server.py tests/test_server.py
git commit -m "feat: expose routines and board over the socket"
```

---

### Task 6: 8-bit chibi icons

**Files:**
- Create: `tools/pixel_icons.py`, `tests/test_icons.py`
- Modify: `colmena/ui/icons/bee.svg`, `colmena/ui/icons/colmena.svg` (regenerated)

**Interfaces:**
- Produces:
  - `pixel_icons.BEE` and `pixel_icons.HEX`: 16×16 ASCII grids.
  - `pixel_icons.svg(grid) -> str`
  - `pixel_icons.mask(grid) -> str`: 16 lines of `#`/`.`, where `#` is any non-transparent pixel except wings and highlights, used for the monochrome bar glyph.
  - `python tools/pixel_icons.py` writes both SVGs into `colmena/ui/icons/`.

- [ ] **Step 1: Write the failing test** `tests/test_icons.py`

```python
import re
import unittest
from pathlib import Path

import tools.pixel_icons as px

ICONS = Path("colmena/ui/icons")


class IconsTest(unittest.TestCase):
    def test_grids_are_16x16(self):
        for grid in (px.BEE, px.HEX):
            rows = grid.strip("\n").split("\n")
            self.assertEqual(len(rows), 16)
            self.assertTrue(all(len(r) == 16 for r in rows))

    def test_committed_svgs_match_generator(self):
        self.assertEqual((ICONS / "bee.svg").read_text(), px.svg(px.BEE))
        self.assertEqual((ICONS / "colmena.svg").read_text(), px.svg(px.HEX))

    def test_svg_is_crisp_pixel_art(self):
        out = px.svg(px.BEE)
        self.assertIn('viewBox="0 0 16 16"', out)
        self.assertIn('shape-rendering="crispEdges"', out)
        self.assertTrue(re.search(r'<rect x="\d+" y="\d+" width="1" height="1"', out))

    def test_mask_shape(self):
        rows = px.mask(px.BEE).split("\n")
        self.assertEqual(len(rows), 16)
        self.assertTrue(set("".join(rows)) <= {"#", "."})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `touch tools/__init__.py 2>/dev/null || (mkdir -p tools && touch tools/__init__.py); .venv/bin/python -m unittest tests.test_icons -v`
Expected: FAIL: `ModuleNotFoundError: No module named 'tools.pixel_icons'`

- [ ] **Step 3: Implement** `tools/pixel_icons.py` (the grids the user approved on 2026-09-25)

```python
"""8-bit chibi icons for Colmena, drawn as 16x16 ASCII grids.

Run `python tools/pixel_icons.py` to regenerate colmena/ui/icons/*.svg.
"""
from pathlib import Path

PALETTE = {"K": "#2b2118", "Y": "#ffd23f", "O": "#e8a200", "W": "#d8f1ff", "w": "#ffffff",
           "P": "#ff8fab", "B": "#2b2118", "H": "#f5b400", "h": "#ffe07a", "D": "#7a4a00"}

BEE = """
...K........K...
....K......K....
.....KKKKKK.....
.WW.KYYYYYYK.WW.
WwWKYYYYYYYYKWwW
WWKYYYYYYYYYYKWW
.KYYwKYYYYwKYYK.
.KYYKKYYYYKKYYK.
.KYPPYYYYYYPPYK.
.KYYYYKYYKYYYYK.
..KYYYYKKYYYYK..
...KKKKKKKKKK...
....KOOOOOOK....
....KBBBBBBK....
.....KOOOOK.....
.......KK.......
"""

HEX = """
.......DD.......
.....DDHHDD.....
...DDHHhhHHDD...
.DDHHhHHHHHHHDD.
DHHHhHHHHHHHHHHD
DHHHHHHHHHHHHHHD
DHHHHHHHHHHHHHHD
DHHHwKHHHHwKHHHD
DHHHKKHHHHKKHHHD
DHHPPHHHHHHPPHHD
DHHHHHKHHKHHHHHD
DHHHHHHKKHHHHHHD
.DDHHHHHHHHHHDD.
...DDHHHHHHDD...
.....DDHHDD.....
.......DD.......
"""


def _rows(grid):
    return grid.strip("\n").split("\n")


def svg(grid):
    rects = [f'<rect x="{x}" y="{y}" width="1" height="1" fill="{PALETTE[ch]}"/>'
             for y, row in enumerate(_rows(grid)) for x, ch in enumerate(row) if ch != "."]
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
            + "".join(rects) + "</svg>\n")


def mask(grid):
    return "\n".join("".join("." if ch in ".wW" else "#" for ch in row) for row in _rows(grid))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "colmena" / "ui" / "icons"
    (out / "bee.svg").write_text(svg(BEE))
    (out / "colmena.svg").write_text(svg(HEX))
    print("wrote", out / "bee.svg", out / "colmena.svg")
```

Then regenerate the SVGs: `.venv/bin/python tools/pixel_icons.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_icons -v`
Expected: 4 tests OK

- [ ] **Step 5: Commit**

```bash
git add tools tests/test_icons.py colmena/ui/icons
git commit -m "feat: 8-bit chibi bee and honeycomb icons"
```

---

### Task 7: GTK views — Rutinas and Tablero

**Files:**
- Create: `colmena/ui/routines.py`, `colmena/ui/board.py`
- Modify: `colmena/ui/window.py`, `colmena/ui/theme.py` (card CSS)
- Smoke: `.superpowers/ui_probe2.py` (scratch, not committed)

**Interfaces:**
- Consumes: the protocol methods from Task 5, `schedule.describe` / `DAYS`, `ICONS`, and `_toast_error` from window.
- Produces:
  - `RoutinesView(window)` with `on_event(ev)` and `load(routines)`.
  - `BoardView(window)` with `on_event(ev)` and `load(tasks)`.
  - The window sidebar gains the rows "Rutinas" (thread `"routines"`) and "Tablero" (thread `"board"`) after Grupo. Alt+1…9 order: Grupo, Rutinas, Tablero, agents.

No unit tests (GTK). Verified by the Broadway smoke in Step 4.

- [ ] **Step 1: Write** `colmena/ui/routines.py`

```python
from datetime import datetime

from gi.repository import Adw, Gtk

from colmena.schedule import DAYS, describe

KINDS = [("every_hours", "Cada N horas"), ("daily", "Todos los días"), ("weekly", "Días de la semana")]


def _when(ts):
    return datetime.fromtimestamp(ts).strftime("%a %d %H:%M") if ts else "—"


class RoutinesView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window, self.client = window, window.client
        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=6, margin_start=16, margin_end=16)
        title = Gtk.Label(label="Tareas que se repiten solas", xalign=0, hexpand=True)
        title.add_css_class("dim-label")
        add = Gtk.Button(label="+ Rutina")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._dialog())
        bar.append(title)
        bar.append(add)
        self.append(bar)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=16, margin_end=16)
        self.list.add_css_class("colmena-cards")
        self.append(Gtk.ScrolledWindow(vexpand=True, child=self.list, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.routines = []

    def _target_name(self, target):
        return "Grupo" if target == "group" else self.window._names().get(target, "?")

    def load(self, routines):
        self.routines = routines
        self.list.remove_all()
        if not routines:
            empty = Gtk.Label(label="Aún no hay rutinas. Crea una con «+ Rutina».", margin_top=24)
            empty.add_css_class("dim-label")
            self.list.append(empty)
        for r in routines:
            self.list.append(self._row(r))

    def _row(self, r):
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        name = Gtk.Label(label=r["name"], xalign=0)
        name.add_css_class("heading")
        texts.append(name)
        sub = Gtk.Label(xalign=0, wrap=True, label=f"{describe(r['schedule'])} · {self._target_name(r['target'])}"
                        f" · próxima: {_when(r['next_run']) if r['enabled'] else 'pausada'}")
        sub.add_css_class("dim-label")
        texts.append(sub)
        box.append(texts)
        switch = Gtk.Switch(active=r["enabled"], valign=Gtk.Align.CENTER, tooltip_text="Activa o pausa")
        switch.connect("notify::active", lambda s, _p: self.client.call(
            "update_routine", {"routine": r["id"], "enabled": s.get_active()}, self.window._toast_error))
        box.append(switch)
        for icon, tip, fn in (("media-playback-start-symbolic", "Correr ahora",
                               lambda *_: self.client.call("run_routine_now", {"routine": r["id"]},
                                                           self.window._toast_error)),
                              ("document-edit-symbolic", "Editar", lambda *_: self._dialog(r)),
                              ("user-trash-symbolic", "Borrar", lambda *_: self.client.call(
                                  "delete_routine", {"routine": r["id"]}, self.window._toast_error))):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
            b.connect("clicked", fn)
            box.append(b)
        return box

    def on_event(self, ev):
        if ev["type"] == "routines":
            self.load(ev["routines"])
        elif ev["type"] == "agents":
            self.load(self.routines)

    def _dialog(self, r=None):
        dialog = Adw.AlertDialog(heading="Editar rutina" if r else "Nueva rutina")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(text=r["name"] if r else "", placeholder_text="Nombre, p. ej. Resumen de anuncios")
        targets = [("group", "Grupo")] + [(a["id"], a["name"]) for a in self.window.agents]
        target = Gtk.DropDown.new_from_strings([label for _, label in targets])
        if r:
            target.set_selected(next((i for i, (t, _) in enumerate(targets) if t == r["target"]), 0))
        prompt = Gtk.Entry(text=r["prompt"] if r else "", placeholder_text="Instrucción, p. ej. revisa los anuncios y resume")
        kind = Gtk.DropDown.new_from_strings([label for _, label in KINDS])
        hours = Gtk.SpinButton.new_with_range(1, 168, 1)
        time_entry = Gtk.Entry(text="09:00", max_width_chars=6, placeholder_text="HH:MM")
        days_box = Gtk.Box(spacing=4)
        day_buttons = [Gtk.ToggleButton(label=d[:2]) for d in DAYS]
        for b in day_buttons:
            days_box.append(b)
        s = r["schedule"] if r else {"daily": "09:00"}
        if "every_hours" in s:
            kind.set_selected(0)
            hours.set_value(s["every_hours"])
        elif "daily" in s:
            kind.set_selected(1)
            time_entry.set_text(s["daily"])
        else:
            kind.set_selected(2)
            time_entry.set_text(s["weekly"]["time"])
            for d in s["weekly"]["days"]:
                day_buttons[d].set_active(True)

        def sync(*_):
            k = KINDS[kind.get_selected()][0]
            hours.set_visible(k == "every_hours")
            time_entry.set_visible(k != "every_hours")
            days_box.set_visible(k == "weekly")

        kind.connect("notify::selected", sync)
        sync()
        for w in (name, target, prompt, kind, hours, time_entry, days_box):
            box.append(w)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Guardar")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, response):
            if response != "ok":
                return
            k = KINDS[kind.get_selected()][0]
            if k == "every_hours":
                schedule = {"every_hours": int(hours.get_value())}
            elif k == "daily":
                schedule = {"daily": time_entry.get_text().strip()}
            else:
                schedule = {"weekly": {"days": [i for i, b in enumerate(day_buttons) if b.get_active()],
                                       "time": time_entry.get_text().strip()}}
            params = {"name": name.get_text(), "target": targets[target.get_selected()][0],
                      "prompt": prompt.get_text(), "schedule": schedule}
            if r:
                self.client.call("update_routine", {"routine": r["id"], **params}, self.window._toast_error)
            else:
                self.client.call("create_routine", params, self.window._toast_error)

        dialog.connect("response", done)
        dialog.present(self.window)
```

- [ ] **Step 2: Write** `colmena/ui/board.py`

```python
from gi.repository import Adw, GLib, Gtk, Pango

from colmena.ui.window_icons import BEE_ICON

COLUMNS = [("todo", "Por hacer"), ("doing", "En curso"), ("done", "Listo")]
ORDER = [c for c, _ in COLUMNS]


class BoardView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window, self.client = window, window.client
        bar = Gtk.Box(spacing=8, margin_top=10, margin_bottom=6, margin_start=16, margin_end=16)
        hint = Gtk.Label(label="Los agentes también mueven estas tareas", xalign=0, hexpand=True)
        hint.add_css_class("dim-label")
        add = Gtk.Button(label="+ Tarea")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._new())
        bar.append(hint)
        bar.append(add)
        self.append(bar)
        cols = Gtk.Box(spacing=12, homogeneous=True, vexpand=True,
                       margin_start=16, margin_end=16, margin_bottom=12)
        self.columns = {}
        for status, label in COLUMNS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            head = Gtk.Label(label=label.upper(), xalign=0)
            head.add_css_class("colmena-author")
            col.append(head)
            cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            col.append(Gtk.ScrolledWindow(vexpand=True, child=cards, hscrollbar_policy=Gtk.PolicyType.NEVER))
            self.columns[status] = cards
            cols.append(col)
        self.append(cols)
        self.tasks = []

    def load(self, tasks):
        self.tasks = tasks
        for cards in self.columns.values():
            while (child := cards.get_first_child()):
                cards.remove(child)
        for t in tasks:
            self.columns[t["status"]].append(self._card(t))

    def _move(self, t, delta):
        i = ORDER.index(t["status"]) + delta
        if 0 <= i < len(ORDER):
            self.client.call("update_task", {"task": t["id"], "status": ORDER[i]}, self.window._toast_error)

    def _card(self, t):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("colmena-card")
        title = Gtk.Button(child=Gtk.Label(label=t["title"], xalign=0, wrap=True,
                                           wrap_mode=Pango.WrapMode.WORD_CHAR))
        title.add_css_class("flat")
        title.connect("clicked", lambda *_: self._details(t))
        card.append(title)
        row = Gtk.Box(spacing=6)
        who = Gtk.Box(spacing=4, hexpand=True)
        if t["assignee_name"]:
            who.append(Gtk.Image(file=BEE_ICON, pixel_size=16))
        who.append(Gtk.Label(label=t["assignee_name"] or "sin asignar", xalign=0))
        row.append(who)
        for text, delta in (("◀", -1), ("▶", 1)):
            b = Gtk.Button(label=text, sensitive=0 <= ORDER.index(t["status"]) + delta < len(ORDER))
            b.connect("clicked", lambda _b, d=delta: self._move(t, d))
            row.append(b)
        menu = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Asignar o borrar")
        pop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        for agent_id, label in [(None, "Sin asignar")] + [(a["id"], a["name"]) for a in self.window.agents]:
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, a=agent_id: (menu.popdown(), self.client.call(
                "update_task", {"task": t["id"], "assignee": a or ""}, self.window._toast_error)))
            pop.append(b)
        delete = Gtk.Button(label="Borrar tarea")
        delete.add_css_class("destructive-action")
        delete.connect("clicked", lambda *_: (menu.popdown(), self.client.call(
            "delete_task", {"task": t["id"]}, self.window._toast_error)))
        pop.append(delete)
        menu.set_popover(Gtk.Popover(child=pop))
        row.append(menu)
        card.append(row)
        return card

    def _new(self):
        dialog = Adw.AlertDialog(heading="Nueva tarea")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        title = Gtk.Entry(placeholder_text="Título")
        desc = Gtk.Entry(placeholder_text="Descripción (opcional)")
        people = [(None, "Sin asignar")] + [(a["id"], a["name"]) for a in self.window.agents]
        who = Gtk.DropDown.new_from_strings([label for _, label in people])
        for w in (title, desc, who):
            box.append(w)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("ok", "Crear")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _d, resp: resp == "ok" and self.client.call("create_task", {
            "title": title.get_text(), "description": desc.get_text(),
            "assignee": people[who.get_selected()][0]}, self.window._toast_error))
        dialog.present(self.window)

    def _details(self, t):
        def show(log, err):
            lines = "\n".join(f"• {GLib.markup_escape_text(e['text'])}" for e in (log or []))
            body = (GLib.markup_escape_text(t["description"] or "Sin descripción.") + "\n\n<b>Historial</b>\n" + lines)
            dialog = Adw.AlertDialog(heading=t["title"], body=body, body_use_markup=True)
            dialog.add_response("ok", "Cerrar")
            dialog.present(self.window)
        self.client.call("task_log", {"task": t["id"]}, show)

    def on_event(self, ev):
        if ev["type"] == "tasks":
            self.load(ev["tasks"])
        elif ev["type"] == "agents":
            self.load(self.tasks)
```

Create `colmena/ui/window_icons.py` so `board.py` does not import `window.py` (which imports the views):

```python
from pathlib import Path

ICONS = Path(__file__).parent / "icons"
BEE_ICON = str(ICONS / "bee.svg")
HEX_ICON = str(ICONS / "colmena.svg")
```

- [ ] **Step 3: Wire the views into** `colmena/ui/window.py`

1. Imports:
```python
from colmena.ui.board import BoardView
from colmena.ui.routines import RoutinesView
from colmena.ui.window_icons import ICONS
```
Delete the local line `ICONS = Path(__file__).parent / "icons"`, and delete `from pathlib import Path` if nothing else uses it.
2. In `__init__`, add `self.routines, self.tasks = [], []` next to `self.agents, ...`.
3. In `_hello`, after the approvals line:
```python
        self.routines, self.tasks = snap.get("routines", []), snap.get("tasks", [])
        for thread, view in self.views.items():
            if thread == "routines":
                view.load(self.routines)
            elif thread == "board":
                view.load(self.tasks)
            else:
                view.load(self.approvals)
```
Remove the old loop `for view in self.views.values(): view.load(self.approvals)`.
4. In `_row`, choose the icon by thread:
```python
        if thread in ("routines", "board"):
            image = Gtk.Image(icon_name="alarm-symbolic" if thread == "routines" else "view-grid-symbolic", pixel_size=24)
        else:
            image = Gtk.Image(file=str(ICONS / ("colmena.svg" if thread == "group" else "bee.svg")), pixel_size=32)
        avatar = Gtk.Overlay(child=image)
```
(This replaces the `icon = ...` and `avatar = Gtk.Overlay(child=Gtk.Image(...))` lines. Keep the status dot only when `thread not in ("routines", "board")`.)
5. In `_rebuild_sidebar`, after the Grupo row:
```python
        self.sidebar_list.append(self._row("routines", "Rutinas", f"{len(self.routines)} programadas"))
        self.sidebar_list.append(self._row("board", "Tablero", f"{sum(t['status'] != 'done' for t in self.tasks)} abiertas"))
```
6. In `_select`, build the right view:
```python
        if thread not in self.views:
            if thread == "routines":
                view = RoutinesView(self)
                view.load(self.routines)
            elif thread == "board":
                view = BoardView(self)
                view.load(self.tasks)
            else:
                view = ChatView(self.client, thread, self._names())
                view.load(self.approvals)
            self.views[thread] = view
            self.stack.add_named(view, thread)
        self.stack.set_visible_child_name(thread)
        if hasattr(self.views[thread], "entry"):
            self.views[thread].entry.grab_focus()
        special = thread in ("group", "routines", "board")
        self.delete_btn.set_visible(not special)
        self.settings_btn.set_visible(not special)
        name = {"group": "Grupo", "routines": "Rutinas", "board": "Tablero"}.get(thread) or self._names().get(thread, "")
```
(Replace the existing lines of `_select` from `if thread not in self.views:` through `name = ...` with this block.)
7. In `_on_event`, keep the sidebar counts fresh:
```python
        elif t == "routines":
            self.routines = ev["routines"]
            self._rebuild_sidebar()
        elif t == "tasks":
            self.tasks = ev["tasks"]
            self._rebuild_sidebar()
```
8. `ChatView.on_event` must ignore the `routines` and `tasks` event types. It already does, because it only matches known types.

Add card CSS to `css()` in `colmena/ui/theme.py`, before `.colmena-dot {{`:
```python
.colmena-card {{ border: 2px solid {c['muted']}; border-radius: 0; padding: 8px; background: {c['dark_background']}; }}
.colmena-cards > row {{ border-bottom: 1px solid {c['muted']}; }}
```

- [ ] **Step 4: Smoke test on Broadway** (headless; never the user's screen)

Write `.superpowers/ui_probe2.py`:
```python
import sys, traceback
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib
from colmena.ui import theme
from colmena.ui.window import MainWindow

errors = []
sys.excepthook = lambda *a: errors.append("".join(traceback.format_exception(*a)))

class App(Adw.Application):
    def do_activate(self):
        theme.install(Gdk.Display.get_default())
        self.win = MainWindow(self)
        self.win.present()
        GLib.timeout_add(1500, self.step)

    def step(self):
        try:
            for i in range(3):
                self.win._select_index(i)
            self.win.views["routines"]._dialog()
            self.win.views["routines"]._dialog({"id": "x", "name": "R", "target": "group", "prompt": "p",
                                                "schedule": {"weekly": {"days": [0, 3], "time": "09:00"}},
                                                "enabled": True, "next_run": 0})
            self.win.views["board"]._new()
            self.win.views["board"].load([{"id": "t", "title": "Landing", "description": "", "status": "doing",
                                           "assignee": None, "assignee_name": None}])
        except Exception:
            errors.append(traceback.format_exc())
        GLib.timeout_add(800, self.finish)
        return False

    def finish(self):
        print("ERRORS:", errors or "none", flush=True)
        self.quit()

App(application_id="com.gogema.ColmenaProbe2").run([])
```
Run:
```bash
(gtk4-broadwayd :7 >/dev/null 2>&1 &); sleep 1
GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 timeout 25 .venv/bin/python .superpowers/ui_probe2.py
pkill -x gtk4-broadwayd
```
Expected: `ERRORS: none`. This probe connects to the installed daemon's socket if it is running; that is fine because it only reads (`hello`).

- [ ] **Step 5: Commit**

```bash
git add colmena/ui
git commit -m "feat: Rutinas and Tablero views in the window"
```

---

### Task 8: Omarchy plugin — manifest and Panel.qml

**Files:**
- Create: `manifest.json`, `Panel.qml`, `tests/test_plugin.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the socket protocol (`hello`, `approve`), the events `status`, `agents`, `approval`, `approval_resolved` and `capacity`, `install.sh`, and `tools/pixel_icons.mask(BEE)`.
- Produces: an Omarchy bar widget `gogema.colmena`.

- [ ] **Step 1: Write the failing test** `tests/test_plugin.py`

```python
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import tools.pixel_icons as px

ROOT = Path(__file__).resolve().parent.parent


class PluginTest(unittest.TestCase):
    def test_manifest(self):
        m = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual((m["schemaVersion"], m["id"], m["kinds"]), (1, "gogema.colmena", ["bar-widget"]))
        self.assertTrue((ROOT / m["entryPoints"]["barWidget"]).is_file())
        self.assertEqual(m["barWidget"]["defaultSection"], "right")

    @unittest.skipUnless(shutil.which("omarchy-plugin-validate"), "not on Omarchy")
    def test_omarchy_validate(self):
        out = subprocess.run(["omarchy-plugin-validate", str(ROOT)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_no_symlinks(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", ".superpowers", "build")]
            for name in dirnames + filenames:
                self.assertFalse(os.path.islink(os.path.join(dirpath, name)), name)

    def test_panel_uses_protocol_and_reconnects(self):
        qml = (ROOT / "Panel.qml").read_text()
        for needle in ('"hello"', '"approve"', "colmena.sock", "Timer", "SplitParser", "install.sh"):
            self.assertIn(needle, qml)

    def test_panel_bee_matches_icon(self):
        qml = (ROOT / "Panel.qml").read_text()
        start = qml.index("BEE_MASK_START") + len("BEE_MASK_START\n")
        end = qml.index("BEE_MASK_END")
        rows = [line.strip().strip('"+, ') for line in qml[start:end].strip().split("\n")]
        self.assertEqual("\n".join(rows), px.mask(px.BEE))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_plugin -v`
Expected: FAIL: `FileNotFoundError: .../manifest.json`

- [ ] **Step 3: Write** `manifest.json`

```json
{
  "schemaVersion": 1,
  "id": "gogema.colmena",
  "name": "Colmena",
  "version": "0.2.0",
  "author": "gogema",
  "license": "MIT",
  "description": "Un equipo de agentes de Claude en tu escritorio: chats, grupo con @menciones, rutinas, tablero y aprobaciones desde la barra.",
  "kinds": ["bar-widget"],
  "entryPoints": {
    "barWidget": "Panel.qml"
  },
  "barWidget": {
    "displayName": "Colmena",
    "description": "Estado de tus agentes y aprobaciones pendientes.",
    "category": "Productivity",
    "allowMultiple": false,
    "defaultSection": "right"
  }
}
```

Write `Panel.qml`:

```qml
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Colmena bar widget. Talks to colmena-daemon over its Unix socket with the
// same newline-delimited JSON protocol the GTK window uses: `hello` for a
// snapshot, then live events. Approvals are answered with `approve`.
Panel {
  id: root
  moduleName: "gogema.colmena"
  ipcTarget: "gogema.colmena"

  readonly property string socketPath: Quickshell.env("XDG_RUNTIME_DIR") + "/colmena.sock"
  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace("file://", "")
  readonly property string venvDaemon: Quickshell.env("HOME") + "/.local/share/colmena/venv/bin/colmena-daemon"

  property bool connected: false
  property bool installed: true
  property bool installing: false
  property string installLog: ""
  property var agents: []
  property var statuses: ({})
  property var approvals: []
  property int nextId: 1

  readonly property int working: Object.keys(root.statuses).filter(k => root.statuses[k] === "working").length
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color glyphColor: !root.connected ? root.dim
    : root.approvals.length > 0 ? Color.urgent
    : root.working > 0 ? Color.accent : root.dim

  // BEE_MASK_START
  readonly property var beeMask: [
    "...#........#...",
    "....#......#....",
    ".....######.....",
    "....########....",
    "...##########...",
    "..############..",
    ".###.#####.####.",
    ".##############.",
    ".##############.",
    ".##############.",
    "..############..",
    "...##########...",
    "....########....",
    "....########....",
    ".....######.....",
    ".......##......."
  ]
  // BEE_MASK_END

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function send(method, params) {
    if (!root.connected) return
    sock.write(JSON.stringify({ id: root.nextId++, method: method, params: params || {} }) + "\n")
    sock.flush()
  }

  function nameOf(id) {
    const a = root.agents.find(x => x.id === id)
    return a ? a.name : "?"
  }

  function handle(line) {
    let msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.result && msg.result.agents !== undefined && msg.result.statuses !== undefined) {
      root.agents = msg.result.agents
      root.statuses = msg.result.statuses
      root.approvals = msg.result.approvals || []
      return
    }
    const ev = msg.event
    if (!ev) return
    if (ev.type === "agents") root.agents = ev.agents
    else if (ev.type === "status") {
      const s = Object.assign({}, root.statuses); s[ev.agent] = ev.status; root.statuses = s
    }
    else if (ev.type === "approval") root.approvals = root.approvals.concat([ev.approval])
    else if (ev.type === "approval_resolved") root.approvals = root.approvals.filter(a => a.id !== ev.id)
  }

  function install() {
    if (root.installing) return
    root.installing = true
    root.installLog = ""
    installProcess.command = ["bash", root.pluginDir + "/install.sh"]
    installProcess.running = true
  }

  Socket {
    id: sock
    path: root.socketPath
    connected: true
    parser: SplitParser { onRead: data => root.handle(data) }
    onConnectionStateChanged: {
      root.connected = sock.connected
      if (sock.connected) root.send("hello", {})
      else { root.approvals = []; root.statuses = ({}) }
    }
  }

  // Reconnect every 3 s while the daemon is down or restarting.
  Timer {
    interval: 3000
    running: !root.connected
    repeat: true
    onTriggered: {
      probe.running = true
      sock.connected = false
      sock.connected = true
    }
  }

  Process {
    id: probe
    command: ["test", "-x", root.venvDaemon]
    onExited: function(exitCode) { root.installed = exitCode === 0 }
  }

  Process {
    id: installProcess
    running: false
    command: []
    stdout: SplitParser { onRead: data => root.installLog = (root.installLog + data + "\n").slice(-2000) }
    stderr: SplitParser { onRead: data => root.installLog = (root.installLog + data + "\n").slice(-2000) }
    onExited: function(exitCode) {
      root.installing = false
      probe.running = true
    }
  }

  Process { id: openProcess; command: ["colmena"] }

  Component.onCompleted: probe.running = true

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        implicitWidth: Style.space(16)
        implicitHeight: Style.space(16)
        Grid {
          anchors.centerIn: parent
          columns: 16
          Repeater {
            model: 256
            Rectangle {
              required property int index
              width: Math.max(1, Math.round(Style.space(1)))
              height: width
              color: root.beeMask[Math.floor(index / 16)][index % 16] === "#" ? root.glyphColor : "transparent"
            }
          }
        }
        Text {
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          visible: root.connected && (root.approvals.length > 0 || root.working > 0)
          text: root.approvals.length > 0 ? "!" : String(root.working)
          color: root.glyphColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) openProcess.startDetached()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: flick.width
          spacing: Style.spacing.md

          // --- not installed -------------------------------------------------
          Column {
            width: parent.width
            spacing: Style.spacing.md
            visible: !root.connected && !root.installed

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              text: "Colmena aún no está instalada. Se instala en tu usuario: una app, un servicio y sin permisos de root."
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
            Button {
              text: root.installing ? "Instalando…" : "Instalar Colmena"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.install()
            }
            Text {
              width: parent.width
              visible: root.installLog.length > 0
              wrapMode: Text.WrapAnywhere
              text: root.installLog
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // --- installed but daemon down ------------------------------------
          Text {
            width: parent.width
            visible: !root.connected && root.installed
            wrapMode: Text.Wrap
            text: "El daemon de Colmena no responde. Reintentando…"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          // --- approvals -----------------------------------------------------
          PanelSectionHeader {
            visible: root.connected && root.approvals.length > 0
            text: "APROBACIONES"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.connected ? root.approvals : []
            delegate: Column {
              required property var modelData
              width: column.width
              spacing: Style.spacing.xs
              Text {
                width: parent.width
                elide: Text.ElideRight
                text: root.nameOf(modelData.agent_id) + " quiere usar " + modelData.tool
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                width: parent.width
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 3
                elide: Text.ElideRight
                text: modelData.input.command || modelData.input.file_path || JSON.stringify(modelData.input)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              Row {
                spacing: Style.spacing.sm
                Button { text: "Permitir"; foreground: root.foreground; fontFamily: root.fontFamily; bordered: true
                         onClicked: root.send("approve", { approval: modelData.id, decision: "allow" }) }
                Button { text: "Denegar"; foreground: root.foreground; fontFamily: root.fontFamily; bordered: true
                         onClicked: root.send("approve", { approval: modelData.id, decision: "deny" }) }
                Button { text: "Siempre"; foreground: root.foreground; fontFamily: root.fontFamily
                         tooltipText: "Guardará: " + (modelData.rule || modelData.tool)
                         onClicked: root.send("approve", { approval: modelData.id, decision: "always" }) }
              }
            }
          }

          // --- agents --------------------------------------------------------
          PanelSectionHeader {
            visible: root.connected
            text: "AGENTES"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.connected ? root.agents : []
            delegate: Row {
              required property var modelData
              spacing: Style.spacing.sm
              Text {
                text: "●"
                color: ({ working: Color.accent, waiting: Color.urgent, error: Color.urgent })[root.statuses[modelData.id]] || root.dim
                font.pixelSize: Style.font.caption
              }
              Text {
                text: modelData.name + "  ·  " + ({ idle: "inactivo", queued: "en cola", working: "trabajando",
                      waiting: "esperando aprobación", error: "error" })[root.statuses[modelData.id] || "idle"]
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
            }
          }

          Button {
            visible: root.connected || root.installed
            text: "Abrir Colmena"
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: { openProcess.startDetached(); root.close() }
          }
        }
      }
    }
  }
}
```

The `beeMask` rows above are `px.mask(px.BEE)` for the approved grid; `test_panel_bee_matches_icon` keeps them in sync if the icon changes.

Add to `README.md`, right after the first paragraph:

````markdown
## Instalar como plugin de Omarchy

```bash
omarchy plugin add https://github.com/<tu-usuario>/colmena --enable
```

Aparece una abejita en la barra. El primer clic ofrece «Instalar Colmena» (app, servicio de
usuario y atajo en el menú). Después, la abejita muestra cuántos agentes trabajan y se pone
amarilla con «!» cuando alguno espera tu aprobación: puedes aprobar desde ahí mismo. Clic
del medio abre la ventana.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_plugin -v && omarchy-plugin-validate .`
Expected: 5 tests OK, and the validator exits with status 0.

- [ ] **Step 5: Commit**

```bash
git add manifest.json Panel.qml tests/test_plugin.py README.md
git commit -m "feat: Omarchy plugin with bar widget and approvals panel"
```

---

### Task 9: Install, reinstall and hand over for a live check

**Files:** none new.

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 2: Reinstall the daemon and app**

Run: `./install.sh && sleep 3 && systemctl --user is-active colmena`
Expected: `active`. Then run `.venv/bin/python .superpowers/drive.py 'hello {}'`. Its result must include the `routines` and `tasks` keys, and the existing agents must be preserved.

- [ ] **Step 3: Real board-tool turn** (proves the in-process MCP server works end to end)

```bash
ID=$(.venv/bin/python .superpowers/drive.py 'create_agent {"name":"Prueba","role":"dev","cwd":"/home/admin/Repositorios/colmena","model":"haiku"}' | python -c "import json,sys; print(json.loads(sys.stdin.read())['result']['id'])")
.venv/bin/python .superpowers/drive.py "send {\"thread\":\"$ID\",\"text\":\"Crea en el tablero la tarea 'Probar Colmena' asignada a ti y muévela a Listo. Responde solo: hecho\"}"
sleep 40
.venv/bin/python .superpowers/drive.py 'list_tasks {}'
```
Expected: one task "Probar Colmena" with status `done` and assignee = the agent id, and no approval was requested for the `mcp__tablero__*` tools. Clean up afterwards: `delete_task` for that task and `delete_agent` for `$ID`.

- [ ] **Step 4: Hand the plugin check to the user**

Do not load the plugin into the user's live bar yourself. Tell the user to run:
```bash
omarchy plugin add ~/Repositorios/colmena --enable
```
(or, if `plugin add` requires a git URL, `omarchy plugin clone`/copy per `omarchy plugin --help`), then report what the bar shows.

- [ ] **Step 5: Commit any fix-ups** with a message that names them.
