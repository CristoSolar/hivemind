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
