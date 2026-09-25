# Colmena — design

Date: 2026-09-24. Status: draft, awaiting review.

## Goal

A native Omarchy desktop app for running several named Claude Code agents,
Grok Bot style: each agent has a role and its own chat, agents share a group
thread and hand work to each other with `@Name`, risky actions wait for the
user's approval, and agents keep working after the window is closed.

Success: open Colmena, create an agent, give it a task, switch to another
agent's chat, come back and see what the first one did, approve a pending
action — all without a terminal.

Must run on any Omarchy install, x86_64 and aarch64, with no per-arch build.
Target machines: an 8 GB aarch64 laptop and a 32 GB desktop.

## Out of scope (v1)

- Scheduled routines ("every morning check the ads").
- Mobile / remote access.
- More than one group thread.
- Cloud-hosted agents.

The socket protocol below is the seam for the first two later.

## Architecture

Two Python processes, same repo:

```
colmena (GTK4 + libadwaita window)
   │  JSON lines over $XDG_RUNTIME_DIR/colmena.sock
colmena-daemon (systemd --user service)
   │  claude-agent-sdk (Python)
claude processes, one per running turn
   │
SQLite: ~/.local/share/colmena/colmena.db
```

### colmena-daemon

- Owns all state. The window is a pure view; closing it changes nothing.
- One asyncio process. Modules:
  - `store.py` — SQLite (stdlib `sqlite3`): roles, agents, messages, approvals.
  - `runner.py` — runs one agent turn through `claude-agent-sdk`, resuming the
    agent's stored `session_id`, streams events out, routes permission
    requests to `approvals`.
  - `router.py` — group-thread `@Name` routing and the hop limit.
  - `capacity.py` — how many turns may run at once on this machine.
  - `server.py` — the Unix socket, request/response plus event broadcast.
  - `notify.py` — `notify-send` when an approval is pending or a turn
    finishes and no window is connected.
- Installed as `~/.config/systemd/user/colmena.service`, `WantedBy=default.target`.

### colmena (window)

- `Adw.NavigationSplitView`:
  - Sidebar: "Grupo" thread pinned on top, then agents with a status dot
    (idle / working / waiting for approval / error) and an unread count.
    "+" button opens the new-agent dialog (name, role, working directory).
  - Content: the selected chat. Message bubbles rendered from a small
    Markdown subset (paragraphs, bold, italics, inline code, fenced code
    blocks, lists) to Pango markup in selectable `Gtk.Label`s; code blocks
    in a monospace frame. Agent tool steps (Bash, Edit, Read, MCP call…)
    shown as collapsible `Gtk.Expander` rows with the command or file and
    the result. Approval requests shown as cards with
    **Permitir** / **Denegar** / **Permitir siempre para este agente**.
  - Composer at the bottom with `@Name` completion in the group thread,
    and a Stop button while a turn is running.
- Reconnects to the socket automatically if the daemon restarts.

### Omarchy integration

- Colors: read `~/.local/state/omarchy/current/theme/colors.toml` (stdlib
  `tomllib`), build a CSS provider from `background`, `foreground`,
  `accent`, `lighter_background`, `muted`, `red`, `green`, `yellow`; a
  `Gio.FileMonitor` on that file restyles live on theme change. `mode`
  selects libadwaita light/dark.
- `colmena.desktop` in `~/.local/share/applications` so it shows in the
  Omarchy app launcher; a suggested Hyprland binding in the README.
- Notifications through `notify-send`, which Omarchy already themes.

## Roles and agents

A **role** is a template: name, system prompt, allowed tools (auto-approved),
MCP servers, default working directory. Shipped defaults, editable as TOML in
`~/.config/colmena/roles/*.toml`:

- `dev` — code in a repository; auto-allows Read, Grep, Glob, Edit in its cwd.
- `marketing` — Meta Ads, Gmail, Drive MCP servers; auto-allows read-only calls.
- `sysadmin` — Omarchy/system maintenance; auto-allows Read, Grep, Glob.

An **agent** is a named instance of a role: `id, name, role, cwd,
session_id, extra_allowed_tools, status, created_at`. Names are unique and
used for `@Name` (case-insensitive).

## Running turns

- A turn = one user (or routed) message to one agent until its result.
- The daemon does not keep a claude process per agent. Each turn starts the
  SDK with `resume=session_id` and ends when the result arrives, so idle
  agents cost no RAM. The first turn stores the new `session_id`.
- Events streamed to the window as they arrive: text deltas, tool use,
  tool result, status change, result (with cost/duration).
- Stop button interrupts the running turn.

## Capacity (per machine)

- Limits **concurrent running turns**, not the number of agents; extra turns
  queue in FIFO order and the agent shows "en cola".
- `max_running = max(1, floor((MemAvailable − reserve) / per_turn_mb))`
  - `MemAvailable` from `/proc/meminfo`, re-read before each start.
  - `reserve = max(1.5 GB, 15% of MemTotal)`.
  - `per_turn_mb` starts at 600 and becomes the rolling average of the peak
    RSS of finished turns' process trees (`/proc/<pid>/status` VmRSS of the
    claude child and descendants), stored in the DB so it survives restarts.
- Overridable with `max_running` in `~/.config/colmena/config.toml`.
- The sidebar footer shows "3/7 activos" so the limit is visible.

## Group thread

- One shared thread. Members = all agents.
- User message in the group: every `@Name` mentioned gets a turn. No mention
  = message is only stored, no agent runs.
- The routed turn's prompt contains the triggering message plus the last 20
  group messages as context, labelled by author.
- An agent's reply is posted to the group; each `@Name` in it (other than
  itself) starts a turn for that agent.
- Hop limit: a counter per chain, reset by any user message; at 5
  agent-to-agent hops routing stops and a system notice is posted.
- Private chats stay separate; group context is not injected into them.

## Approvals

- SDK `can_use_tool` callback. Tool in the role's allowed list or the agent's
  `extra_allowed_tools` → allow without asking. Otherwise → create a pending
  approval, emit it to the window, notify if no window connected, and wait.
- Permitir → allow once. Denegar → deny with the message "El usuario denegó
  esta acción". Permitir siempre → allow and append the tool (with its
  pattern, e.g. `Bash(git status)`) to the agent's `extra_allowed_tools`.
- Pending approvals persist; after a daemon restart they are denied and the
  turn is marked interrupted, because the claude process is gone.

## Socket protocol

Newline-delimited JSON. Requests carry `id`; responses echo it.

Requests: `hello`, `list_agents`, `list_roles`, `create_agent`,
`delete_agent`, `history {thread, before?, limit}`, `send {thread, text}`,
`stop {agent}`, `approve {approval, decision}`.

Events (pushed to all clients): `message`, `delta`, `tool`, `status`,
`approval`, `approval_resolved`, `capacity`.

`thread` is `"group"` or an agent id.

## Auth

Use the logged-in `claude` CLI so agents run on the user's subscription.
First implementation task verifies `claude-agent-sdk` works with that login;
if not, fall back to `ANTHROPIC_API_KEY` from `~/.config/colmena/config.toml`
and tell the user.

## Errors

- Turn crash or SDK error → agent status `error`, error text posted as a
  system message in its chat, next message retries normally.
- Daemon down → window shows a banner "Daemon detenido" with a button that
  runs `systemctl --user start colmena`.
- Unknown `@Name` → system notice in the group, nothing routed.

## Packaging

- Python venv in `~/.local/share/colmena/venv` with `claude-agent-sdk`;
  GTK comes from system packages (`gtk4`, `libadwaita`, `python-gobject`)
  via `--system-site-packages`.
- `install.sh`: create venv, install, write the systemd unit and
  `.desktop`, enable and start the service.

## Testing

Stdlib `unittest`, no framework:

- `router` — mention parsing, self-mention ignored, hop limit, reset on
  user message.
- `capacity` — formula with fake `/proc/meminfo` values, override.
- `store` — round trip of agents/messages/approvals.
- `server` — protocol round trip against a fake runner (no claude calls).
- Manual smoke test: real agent, one approval, one group handoff.
