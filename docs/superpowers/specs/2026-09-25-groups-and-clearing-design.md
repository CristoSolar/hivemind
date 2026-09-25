# Groups, per-conversation memory and clearing history

Date: 2026-09-25. Status: approved in conversation, awaiting written review.
Builds on the earlier HiveMind specs in this folder.

## Problem

- There is a single group thread and no way to clear it. After deleting agents and creating new
  ones, the new agents keep reading the old conversation in the group context and pick up the
  old topic.
- Each agent has one Claude Code session for everything. Clearing a group can therefore only
  work by wiping the agent's whole memory, private chat included.
- The user cannot hold a conversation with just some of the agents.

## Decisions (from the user)

1. Clearing a group deletes its messages **and** the members' memory **of that group**.
2. An agent's private chat can be cleared with **Nueva conversación**, which deletes the messages
   and the private memory.
3. **Grupo** keeps including everyone. The user can also create named groups with chosen members.
4. Memory is **per conversation**, bridged: when an agent speaks in a group, it receives its
   recent private chat with the user. Example: the user asks in a group "¿cómo va el desarrollo
   para activar la campaña?" and Dev answers with what they did in private.

## Data model

- New table `sessions(agent_id, thread, session_id, primary key(agent_id, thread))`. It holds
  one Claude Code session per agent per conversation. `thread` is the agent id for the private
  chat, `"group"` for Grupo, or a group id.
  - Migration: every non-null `agents.session_id` is copied to `sessions(agent_id, agent_id, …)`,
    so the private chat keeps its memory. The Grupo session starts empty. The migration is
    idempotent, and the old column is kept (unused) so a rollback still finds it.
- New table `groups(id, name, created_at)`, with `id` of the form `g-<8 hex>` so it never
  collides with agent ids.
- New table `group_members(group_id, agent_id, primary key(group_id, agent_id))`.
- Deleting an agent removes its sessions and its group memberships.
- Changing an agent's folder resets all of its sessions, because Claude Code stores sessions
  per folder.

## Conversations

A *group thread* is `"group"` (members: every agent) or a custom group id (members:
`group_members`). Every rule that applied to the single group now applies to each group thread:

- A user message with no `@` goes to all members; `@Name` goes only to the members named.
- `@Name` of an agent who is not a member produces a system notice
  "«Name» no está en este grupo" and routes nothing to that agent.
- Agent replies route within the same thread. The hop counter is per thread: 5 hops, reset by
  a user message in that thread.
- The group prompt holds the last 20 messages of **that** thread, then a section
  "Tu chat privado reciente con el usuario". That section has the last 10 text messages of the
  agent's private thread (tool rows excluded, each message truncated to 500 characters), and
  is omitted when there are none.
- A turn uses and stores the session for `(agent, thread)`.

## Clearing

`clear_thread(thread)` works on any group thread or private chat:

1. It stops members that are currently running a turn in that thread, and drops their queued
   items for that thread. Turns in other threads keep going.
2. It deletes every message of the thread.
3. It deletes the sessions of `(member, thread)`.
4. It broadcasts `thread_cleared {thread}`.

The UI asks for confirmation first. In a group: "Se borran los mensajes y los integrantes
olvidan esta conversación. Sus chats privados no cambian." In a private chat (Nueva
conversación): "Se borra el chat y <Name> olvida esta conversación."

## Groups CRUD

- `create_group(name, members)`: `name` must not be empty, and `members` must be at least one
  existing agent.
- `update_group(id, name?, members?)`: removing a member deletes that member's session for the
  group.
- `delete_group(id)`: clears the thread (as above), then deletes the group. Routines that target
  it are paused with a notice, like routines whose agent was deleted.
- Routines may target a group id. A missing group pauses the routine.

## Protocol

- New methods: `list_groups`, `create_group`, `update_group`, `delete_group`, `clear_thread`.
- New events: `groups {groups}` and `thread_cleared {thread}`.
- `hello` adds `groups`. A group dict is `{id, name, members: [agent_id]}`.

## UI

- **Sidebar order:** Grupo, then custom groups (hive icon, name, "N integrantes"), Rutinas,
  Tablero, agents.
- **The "+" button** opens a small menu: "Nuevo agente" and "Nuevo grupo".
- **Group dialog:** a name field and a checkbox per agent. The same dialog edits a group
  through ⚙.
- **Chat header:**
  - Custom groups: ⚙ edit, 🗑 delete, and "Limpiar".
  - Grupo: only "Limpiar".
  - Agents: ⚙, 🗑, and "Nueva conversación".
- **Routine target dropdown:** Grupo, custom groups, agents.
- **After `thread_cleared`,** the open view reloads empty.

## Out of scope

- A per-group role or system prompt.
- Moving a message between threads.
- The bar panel shows no groups; it is about agents and approvals.

## Testing (stdlib unittest)

- **Store:**
  - the sessions table and the migration (idempotent, keeps private memory);
  - groups and members CRUD;
  - the cascades when an agent is deleted.
- **Hub:**
  - routing inside a custom group, with and without `@`;
  - a non-member mention;
  - hop limit per thread;
  - the group prompt contains that thread's messages and the private bridge, and no other
    group's messages;
  - a session is used and stored per `(agent, thread)`;
  - `clear_thread` stops only turns in that thread, deletes its messages and sessions, and
    keeps private sessions;
  - "Nueva conversación";
  - `delete_group` pauses its routines;
  - a folder change resets all sessions.
- **Server:** round trips for the new methods and events.
- **GTK:** a Broadway test that the sidebar lists custom groups, and the existing view-interface
  contract test extended to group views.
