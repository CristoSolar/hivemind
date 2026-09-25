# Colmena as an Omarchy plugin: bar widget, routines, task board

Date: 2026-09-25. Status: approved in conversation, awaiting written review.
Builds on `2026-09-24-colmena-design.md`; everything there still holds unless changed here.

## Goal

Publish Colmena as an Omarchy plugin that people install with one command, and add three
features that set it apart from other multi-agent tools:

1. A bar widget and quick panel: see agent status and answer approvals without opening the window.
2. Routines: tasks that run on a schedule, even with the window closed.
3. A shared task board that agents read and update themselves.

Success: `omarchy plugin add <repo> --enable` puts a bee in the Omarchy bar. The first click
offers "Instalar Colmena", which installs everything. After that the user can approve an action
from the bar, create a routine that runs at 9:00 every Monday, and watch agents move tasks across
the board.

## Out of scope

- Phone or remote control.
- Drag and drop on the board (tasks move with buttons).
- Cron expressions for routines.

## 1. Plugin packaging

The Colmena repository is itself the plugin.

- At the repository root:
  - `manifest.json` (schemaVersion 1, id `gogema.colmena`, kinds `["bar-widget"]`,
    `entryPoints.barWidget = "Panel.qml"`, `barWidget.defaultSection = "right"`,
    category "Productivity").
  - `Panel.qml`.
- `omarchy plugin validate .` must pass. The repository must contain no symlinks.
- `omarchy plugin add` clones the whole repository into `~/.config/omarchy/plugins/gogema.colmena/`.
  The panel then runs `install.sh` from that folder when the user clicks "Instalar Colmena".
- `install.sh` is unchanged in behaviour (venv, systemd user service, desktop entry, icon).
  Running it again upgrades in place.
- Follow the structure and conventions of the existing `tinydfr.touchbar` plugin on this machine.

## 2. Bar widget and panel (Panel.qml)

**Connection**
- Quickshell.Io `Socket` to `$XDG_RUNTIME_DIR/colmena.sock`, speaking the existing JSON-lines protocol.
- On connect it sends `hello`, then follows these events: `status`, `approval`,
  `approval_resolved`, `agents` and `capacity`.
- If the socket is missing or refused, it retries every 3 s.

**Bar glyph**
- Pixel-art bee (see section 5), with these states:
  - muted when no agent is working;
  - accent colour plus a count when agents are working;
  - yellow plus "!" when approvals are pending;
  - struck through when the daemon is unreachable.

**Panel**
- Pending approvals first. Each shows the agent name, the tool, the command or path (truncated),
  the rule that "Siempre" would save, and the buttons Permitir, Denegar and Siempre, which send
  `approve`.
- Then one row per agent with its status.
- An "Abrir Colmena" button, which runs `colmena`.

**Not installed**
- When no daemon is reachable and `~/.local/share/colmena/venv` does not exist, the panel shows
  "Instalar Colmena".
- The button runs `install.sh` through `Process` and streams its output into the panel.
  On success the panel connects.
- Uses the Omarchy shell `Style` helpers and theme colours, like the touchbar plugin does.

## 3. Routines

**Data** — table `routines` with these columns:
- `id`, `name`, `target` (`"group"` or an agent id), `prompt`;
- `schedule` (JSON, one of the forms below), `enabled`, `last_run`, `next_run`, `created_at`.

Schedule forms:
- `{"every_hours": N}` with N from 1 to 168;
- `{"daily": "HH:MM"}`;
- `{"weekly": {"days": [0..6], "time": "HH:MM"}}`, where 0 is Monday.

All times are local time.

**Scheduler** — a daemon task wakes every 30 s. For each enabled routine with
`next_run <= now`, it does the following:
- It sends the prompt with `Hub.send(target, "⏰ Rutina «<name>»: <prompt>")`, so the run goes
  through the queue, capacity and approvals like any user message.
- It stores `last_run = now` and computes `next_run` from `now`. A routine that was missed while
  the machine was off or asleep therefore runs once on return, then resumes its normal cadence.
- If the target agent no longer exists, it disables the routine and posts a system message in the group.
- When the run's turn finishes and no window or panel is connected, it sends
  `notify-send "Rutina «<name>» lista"`.

**Protocol** — `list_routines`, `create_routine`, `update_routine` (any field, including
`enabled`), `delete_routine`, `run_routine_now`. Changes broadcast a `routines` event.

**UI**
- A "Rutinas" entry in the sidebar, below Grupo and above the agents.
- It opens a list of routines. Each shows name, target, a human-readable schedule
  ("Lunes y jueves 09:00") and next run, with a switch, "Correr ahora", edit and delete.
- The create and edit dialog has: name, target dropdown, prompt, schedule type
  (Cada N horas / Todos los días / Días de la semana), then an hour spinner, a time entry or
  weekday toggles.

## 4. Task board

**Data**
- Table `tasks`: `id`, `title`, `description`, `status` (`todo`, `doing` or `done`),
  `assignee` (agent id or null), `created_by` (`"user"` or agent id), `created_at`, `updated_at`.
- Table `task_log`: `task_id`, `actor`, `text`, `ts`.

**Agent tools**
- An in-process MCP server (`create_sdk_mcp_server`) named `tablero`, passed to every turn
  through `mcp_servers`. Its tools:
  - `tablero_listar(estado?)` returns the tasks;
  - `tablero_crear(titulo, descripcion?, asignado?)`;
  - `tablero_mover(id, estado)`;
  - `tablero_asignar(id, agente?)`.
- Agent names are resolved case-insensitively. Unknown ids, names or states return an error
  text to the agent and change nothing.
- `mcp__tablero__*` is always permitted, so the board tools never ask for approval.
- The role system prompt gains one line: the board exists, and the agent should use it to
  coordinate multi-step work.

**Protocol and events**
- `list_tasks`, `create_task`, `update_task` (title, description, status, assignee), `delete_task`.
- Every change, whether from the user or an agent, writes a `task_log` row and broadcasts `tasks`.

**UI**
- A "Tablero" entry in the sidebar.
- It opens three columns: Por hacer, En curso and Listo.
- Each card shows the title, the assignee's bee and name, and the buttons ◀ ▶ to move it,
  plus a menu to assign or delete.
- "+ Tarea" opens a small dialog.
- Clicking a card shows its description and log.

## 5. Visual: 8-bit chibi icons

- Replace the current app icon and bee avatar with pixel-art versions: a 16×16 grid drawn as
  SVG `<rect>`s with `shape-rendering="crispEdges"`, scaled without smoothing.
- App icon: a chunky honeycomb hexagon holding a chibi bee face.
- Agent avatar: a chibi bee (big head, small body, big eyes with a highlight, blush and
  antennae) in a few flat colours.
- The bar glyph uses a monochrome 16×16 version of the bee, so it can take theme colours.
- Drafts are shown to the user before they replace the current icons.

## Errors

- The panel never throws on malformed or partial daemon messages: unknown events are ignored.
- A routine whose prompt fails behaves like any failed turn: error status and a system message.
- Board tool errors are returned to the agent as text and are never raised into the SDK.

## Testing

- stdlib `unittest`, as before.
- Schedule maths:
  - every N hours;
  - daily before and after the time;
  - weekly across a week boundary;
  - end of month and year;
  - invalid schedules rejected.
- Scheduler: a missed routine runs once, a disabled routine never runs, and a deleted target
  disables the routine.
- Board: store operations; each tool with valid and invalid input; tools auto-permitted;
  a log row for every change.
- Protocol round trips for the routine and task methods.
- `omarchy plugin validate .` passes, run as a test step.
- `Panel.qml` cannot be unit-tested here. The user loads it with `omarchy plugin add` from the
  local path and reports what they see. The executor must not drive the user's screen.
