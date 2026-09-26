import json
import sqlite3
import time
import uuid

SCHEMA = """
create table if not exists agents(
  id text primary key, name text not null unique collate nocase, role text not null,
  cwd text not null, session_id text, extra_allowed text not null default '[]',
  created_at real not null);
create table if not exists messages(
  id integer primary key, thread text not null, author text not null,
  kind text not null, content text not null, ts real not null);
create index if not exists messages_thread on messages(thread, id);
create table if not exists approvals(
  id text primary key, agent_id text not null, tool text not null, input text not null,
  rule text, status text not null, ts real not null);
create table if not exists kv(key text primary key, value text not null);
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
create table if not exists sessions(
  agent_id text not null, thread text not null, session_id text not null,
  primary key(agent_id, thread));
create table if not exists groups(id text primary key, name text not null, created_at real not null);
create table if not exists group_members(
  group_id text not null, agent_id text not null, primary key(group_id, agent_id));
"""


def _new_id():
    return uuid.uuid4().hex[:8]


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {r["name"] for r in self.db.execute("pragma table_info(agents)")}
        if "model" not in columns:  # databases created before per-agent models
            with self.db:
                self.db.execute("alter table agents add column model text")
        message_columns = {r["name"] for r in self.db.execute("pragma table_info(messages)")}
        if "attachments" not in message_columns:  # databases created before attachments
            with self.db:
                self.db.execute("alter table messages add column attachments text not null default '[]'")
        # Memory used to live on the agent row: it becomes the private chat's session, once.
        # Running this on every start would resurrect memory the user has since cleared.
        if self.get("sessions_migrated") is None:
            with self.db:
                self.db.execute("insert or ignore into sessions(agent_id, thread, session_id)"
                                " select id, id, session_id from agents where session_id is not null")
            self.set("sessions_migrated", "1")

    def _agent(self, row):
        if row is None:
            return None
        d = dict(row)
        d["extra_allowed"] = json.loads(d["extra_allowed"])
        return d

    def create_agent(self, name, role, cwd, model=None):
        a = {"id": _new_id(), "name": name, "role": role, "cwd": cwd, "model": model,
             "session_id": None, "created_at": time.time()}
        with self.db:
            self.db.execute(
                "insert into agents(id, name, role, cwd, model, session_id, created_at)"
                " values(:id, :name, :role, :cwd, :model, :session_id, :created_at)", a)
        return self.agent(a["id"])

    def update_agent(self, id, **fields):
        unknown = set(fields) - {"model", "cwd", "session_id"}
        if unknown:
            raise ValueError(f"Campos desconocidos: {unknown}")
        with self.db:
            for key, value in fields.items():
                self.db.execute(f"update agents set {key} = ? where id = ?", (value, id))

    def agents(self):
        return [self._agent(r) for r in self.db.execute("select * from agents order by created_at")]

    def agent(self, id):
        return self._agent(self.db.execute("select * from agents where id = ?", (id,)).fetchone())

    def delete_agent(self, id):
        with self.db:
            self.db.execute("delete from agents where id = ?", (id,))
            self.db.execute("delete from sessions where agent_id = ?", (id,))
            self.db.execute("delete from group_members where agent_id = ?", (id,))

    def set_session(self, id, session_id):
        with self.db:
            self.db.execute("update agents set session_id = ? where id = ?", (session_id, id))

    def allow_always(self, id, rule):
        rules = self.agent(id)["extra_allowed"]
        if rule not in rules:
            with self.db:
                self.db.execute("update agents set extra_allowed = ? where id = ?",
                                (json.dumps(rules + [rule]), id))

    def add_message(self, thread, author, kind, content, attachments=None):
        m = {"thread": thread, "author": author, "kind": kind, "content": content, "ts": time.time()}
        with self.db:
            cur = self.db.execute(
                "insert into messages(thread, author, kind, content, ts, attachments)"
                " values(:thread, :author, :kind, :content, :ts, :attachments)",
                {**m, "attachments": json.dumps(attachments or [])})
        return {"id": cur.lastrowid, **m, "attachments": attachments or []}

    @staticmethod
    def _message(row):
        d = dict(row)
        d["attachments"] = json.loads(d.get("attachments") or "[]")
        return d

    def last_activity(self, agent_id):
        row = self.db.execute("select max(ts) from messages where author = ? or thread = ?",
                              (agent_id, agent_id)).fetchone()
        return row[0]

    def history(self, thread, before=None, limit=50):
        rows = self.db.execute(
            "select * from messages where thread = ? and id < ? order by id desc limit ?",
            (thread, before or 2**62, limit)).fetchall()
        return [self._message(r) for r in reversed(rows)]

    def add_approval(self, agent_id, tool, input, rule):
        ap = {"id": _new_id(), "agent_id": agent_id, "tool": tool, "input": json.dumps(input),
              "rule": rule, "status": "pending", "ts": time.time()}
        with self.db:
            self.db.execute(
                "insert into approvals values(:id, :agent_id, :tool, :input, :rule, :status, :ts)", ap)
        return {**ap, "input": input}

    def resolve_approval(self, id, status):
        with self.db:
            self.db.execute("update approvals set status = ? where id = ?", (status, id))

    def approvals(self, status="pending"):
        rows = self.db.execute("select * from approvals where status = ? order by ts", (status,))
        return [{**dict(r), "input": json.loads(r["input"])} for r in rows]

    def get(self, key, default=None):
        row = self.db.execute("select value from kv where key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute("insert or replace into kv values(?, ?)", (key, value))

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
