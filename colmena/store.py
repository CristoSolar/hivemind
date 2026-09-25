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

    def set_session(self, id, session_id):
        with self.db:
            self.db.execute("update agents set session_id = ? where id = ?", (session_id, id))

    def allow_always(self, id, rule):
        rules = self.agent(id)["extra_allowed"]
        if rule not in rules:
            with self.db:
                self.db.execute("update agents set extra_allowed = ? where id = ?",
                                (json.dumps(rules + [rule]), id))

    def add_message(self, thread, author, kind, content):
        m = {"thread": thread, "author": author, "kind": kind, "content": content, "ts": time.time()}
        with self.db:
            cur = self.db.execute(
                "insert into messages(thread, author, kind, content, ts)"
                " values(:thread, :author, :kind, :content, :ts)", m)
        return {"id": cur.lastrowid, **m}

    def history(self, thread, before=None, limit=50):
        rows = self.db.execute(
            "select * from messages where thread = ? and id < ? order by id desc limit ?",
            (thread, before or 2**62, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

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
