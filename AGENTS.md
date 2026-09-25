# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Cursor, …) that install, run or change
HiveMind. Humans: see [README.md](README.md). The user-facing UI copy is Spanish; this file,
code comments and commit messages are English.

## What this is

HiveMind is a desktop app for Omarchy (Arch Linux + Hyprland). It runs a team of named Claude
Code agents. It is built from three parts:

- `hivemind-daemon`: a systemd **user** service written in asyncio Python. It owns all state
  in SQLite and runs each agent turn through `claude-agent-sdk`: one short-lived `claude`
  process per turn, which resumes that agent's session. It serves newline-delimited JSON on
  `$XDG_RUNTIME_DIR/hivemind.sock`.
- `hivemind`: a GTK4 + libadwaita window (PyGObject). It is a pure view over the socket.
- `Panel.qml`: an Omarchy shell bar widget (Quickshell). It is another view over the same
  socket. The repo root is the plugin (`manifest.json`, id `gogema.hivemind`).

## Install for a user

Run these steps in order and check each one. None of them need root; do not use `sudo`.

1. **Preconditions**:
   ```bash
   command -v claude && claude --version     # Claude Code must be installed and logged in
   python -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')"
   ```
   If the second command fails, the system lacks `gtk4`, `libadwaita` or `python-gobject`.
   On Omarchy they ship by default, so ask the user before installing packages.
2. **Get the code**. Clone it wherever the user keeps repositories: ask them, and do not put
   it in `/tmp`.
   ```bash
   git clone https://github.com/CristoSolar/hivemind <dir> && cd <dir>
   ```
3. **Install** (idempotent; re-run it to upgrade):
   ```bash
   ./install.sh
   ```
4. **Verify**:
   ```bash
   systemctl --user is-active hivemind        # → active
   test -S "$XDG_RUNTIME_DIR/hivemind.sock" && echo socket-ok
   journalctl --user -u hivemind -n 20 --no-pager   # no tracebacks
   ```
5. **Optional, as an Omarchy plugin**: `omarchy plugin add https://github.com/CristoSolar/hivemind --enable`.
   The bar panel offers to run `install.sh` itself.

Do **not**:
- Launch the GUI or move focus on the user's live screen to "check" it. Ask the user to open
  HiveMind, or use the headless Broadway backend (below).
- Read, print or copy `~/.config/hivemind/config.toml`. It can hold an Anthropic API key.
- Delete `~/.local/share/hivemind` or `~/.config/hivemind`. They hold the user's agents, chats,
  routines and board.

## Talk to a running daemon

Scripts and agents can drive HiveMind through the socket. Send one JSON object per line
(`{"id": n, "method": ..., "params": {...}}`); each reply echoes `id` with a `result` or an
`error`. Events arrive as `{"event": {...}}`. Send `hello` with `{"role": "panel"}` when you
are not a GUI window, so notifications keep reaching the user.

| Method | Params |
|---|---|
| `hello` | `role?` — returns a snapshot: agents, roles, statuses, activities, last_active, approvals, capacity, routines, tasks, settings (never the API key) |
| `history` | `thread` (`"group"`, a group id or an agent id), `before?`, `limit?` |
| `send` | `thread`, `text` |
| `stop` / `delete_agent` | `agent` |
| `create_agent` | `name` (`[\w-]+`, unique ignoring case), `role`, `cwd?`, `model?` (`opus`/`sonnet`/`haiku`/null) |
| `update_agent` | `agent`, `model?`, `cwd?` (changing `cwd` resets the session) |
| `approve` | `approval`, `decision` (`allow`/`deny`/`always`) |
| `list_groups` / `create_group` / `update_group` / `delete_group` | `group`, `name`, `members` (agent ids) — group ids look like `g-1a2b3c4d`; `"group"` is the built-in group with every agent |
| `clear_thread` | `thread` — deletes that conversation's messages and its members' session for it; stops turns running in it first |
| `get_settings` / `set_settings` | `auth` (`subscription`/`api_key`), `api_key?` |
| `list_routines` / `create_routine` / `update_routine` / `delete_routine` / `run_routine_now` | `routine`, `name`, `target`, `prompt`, `schedule`, `enabled` |
| `list_tasks` / `create_task` / `update_task` / `delete_task` / `task_log` | `task`, `title`, `description`, `status` (`todo`/`doing`/`done`), `assignee` |

Schedules have one of three forms: `{"every_hours": 1..168}`, `{"daily": "HH:MM"}` or
`{"weekly": {"days": [0..6], "time": "HH:MM"}}`, where 0 is Monday and times are local.

Minimal client:

```python
import asyncio, json, os
async def call(method, **params):
    r, w = await asyncio.open_unix_connection(os.environ["XDG_RUNTIME_DIR"] + "/hivemind.sock", limit=2**24)
    w.write((json.dumps({"id": 1, "method": method, "params": params}) + "\n").encode())
    while True:
        msg = json.loads(await r.readline())
        if msg.get("id") == 1:
            return msg
print(asyncio.run(call("hello", role="panel"))["result"]["agents"])
```

## Develop

```bash
python -m venv --system-site-packages .venv        # system site-packages provide GTK
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -t .
```

- **Tests** use stdlib `unittest` only; do not add pytest or other test dependencies. Write
  the failing test first, then the code.
- **GUI tests** are skipped unless they run under Broadway, a headless GTK backend that never
  touches the user's screen:
  ```bash
  gtk4-broadwayd :7 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 .venv/bin/python -m unittest discover -s tests -t .
  ```
- **Scratch files** go in `~/.cache/tmp`, not `/tmp`. On small machines `/tmp` is RAM.
- **Icons** are generated. Edit `tools/icons.py`, then run `python tools/icons.py`;
  `tests/test_icons.py` fails if the committed SVGs drift from the generator. Symbolic icons
  must be single-colour fills with no strokes, so GTK can recolour them from the theme.
- **Animations**: `hivemind/ui/bee_frames.py` is the source of truth. `Panel.qml` mirrors its
  sequences, and `tests/test_plugin.py` checks that the two stay in sync.
- **Plugin**: `omarchy plugin validate .` must pass (a test runs it on a clean copy). Never
  commit symlinks.
- **After changing code**, re-run `./install.sh`. The service runs from
  `~/.local/share/hivemind/venv`, not from the repo.

## Layout

```
hivemind/store.py      SQLite: agents, messages, approvals, routines, tasks, task_log, kv
hivemind/hub.py        orchestration: queue, RAM capacity, approvals, groups + @mention routing, per-conversation
                       sessions (the private chat is bridged into group turns), clearing, activity
hivemind/runner.py     one agent turn over claude-agent-sdk → plain event dicts
hivemind/router.py     @mention parsing (MAX_HOPS = 5 agent-to-agent hops)
hivemind/roles.py      role TOML loading, permission rule matching
hivemind/capacity.py   /proc/meminfo formula, process-tree RSS
hivemind/routines.py   scheduled prompts; hivemind/schedule.py is the pure maths
hivemind/board.py      task board + the in-process MCP server "tablero" given to agents
hivemind/server.py     socket protocol; hivemind/daemon.py is the entry point
hivemind/ui/           GTK window; bee.py + bee_frames.py animate the agent avatars
Panel.qml              Omarchy bar widget; manifest.json is the plugin manifest
docs/superpowers/      design specs and implementation plans
```

## Safety rules the code enforces (keep them)

- Tools not allowed by the agent's role need a user approval. "Allow always" stores a rule
  pinned to the exact command or path. Wildcard rules never match shell commands containing
  `; & | $ < >`, backticks or newlines.
- The board tools (`mcp__tablero__*`) are the only tools every agent may use without asking.
- The daemon never returns the API key over the socket.
- The socket is `0600`, and the config file holding the key is `0600`.
