import asyncio
import unittest
from types import SimpleNamespace as NS

from claude_agent_sdk import (AssistantMessage, PermissionResultAllow, PermissionResultDeny,
                              ResultMessage, StreamEvent, TextBlock, ToolResultBlock,
                              ToolUseBlock, UserMessage)

from hivemind.runner import DENY_MESSAGE, Turn


class FakeClient:
    """Stands in for ClaudeSDKClient: replays messages, calls can_use_tool on ToolUseBlocks."""

    def __init__(self, options, script):
        self.options, self.script, self.interrupted = options, script, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def query(self, prompt):
        self.prompt = prompt

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        for m in self.script:
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        self.decisions = getattr(self, "decisions", [])
                        self.decisions.append(await self.options.can_use_tool(b.name, b.input, NS(suggestions=[])))
            yield m


def result(text="listo"):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                         num_turns=1, session_id="s-1", total_cost_usd=0.01, result=text)


AGENT = {"id": "a1", "name": "Dev", "cwd": "/tmp", "session_id": None, "extra_allowed": ["Bash(ls*)"]}
ROLE = {"system_prompt": "rol", "allowed_tools": ["Read"]}


class RunnerTest(unittest.TestCase):
    def run_turn(self, script, answer="allow"):
        events, asked, clients = [], [], []

        async def ask(tool, input, rule):
            asked.append((tool, rule))
            return answer

        def factory(options):
            clients.append(FakeClient(options, script))
            return clients[-1]

        turn = Turn(AGENT, ROLE, "hola", events.append, ask, client_factory=factory)
        out = asyncio.run(turn.run())
        return out, events, asked, clients[0]

    def test_events_and_result(self):
        script = [
            StreamEvent(uuid="u", session_id="s-1", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ho"}}),
            AssistantMessage(content=[TextBlock(text="hola"), ToolUseBlock(id="t1", name="Read", input={"file_path": "/x"})], model="m"),
            UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text": "x" * 5000}], is_error=False)]),
            result(),
        ]
        out, events, asked, client = self.run_turn(script)
        self.assertEqual(out, {"session_id": "s-1", "is_error": False, "text": "listo", "cost": 0.01})
        content = [e for e in events if e["type"] != "activity"]
        self.assertEqual([e["type"] for e in content], ["delta", "text", "tool", "tool_result"])
        self.assertEqual(len(content[3]["content"]), 4000)
        self.assertEqual(asked, [])  # Read is in the role's allowed tools
        self.assertEqual(client.options.resume, None)
        self.assertTrue(client.options.system_prompt["append"].startswith("rol"))

    def test_extra_allowed_and_ask(self):
        script = [
            AssistantMessage(content=[ToolUseBlock(id="t1", name="Bash", input={"command": "ls -la"}),
                                      ToolUseBlock(id="t2", name="Bash", input={"command": "rm x"})], model="m"),
            result(),
        ]
        _, _, asked, client = self.run_turn(script, answer="deny")
        self.assertEqual(asked, [("Bash", "Bash(rm x)")])
        self.assertIsInstance(client.decisions[0], PermissionResultAllow)
        self.assertIsInstance(client.decisions[1], PermissionResultDeny)
        self.assertEqual(client.decisions[1].message, DENY_MESSAGE)

    def test_stop_while_connecting_skips_the_prompt(self):
        clients = []

        class SlowClient(FakeClient):
            async def __aenter__(self):
                await asyncio.sleep(0.05)  # CLI still starting
                return self

        def factory(options):
            clients.append(SlowClient(options, [result()]))
            return clients[-1]

        async def scenario():
            turn = Turn(AGENT, ROLE, "hola", lambda e: None, None, client_factory=factory)
            task = asyncio.ensure_future(turn.run())
            await asyncio.sleep(0.01)
            await turn.stop()
            return await task

        out = asyncio.run(scenario())
        self.assertFalse(hasattr(clients[0], "prompt"))
        self.assertFalse(out["is_error"])

    def test_agent_model_and_api_key_env(self):
        clients = []

        def factory(options):
            clients.append(FakeClient(options, [result()]))
            return clients[-1]

        agent = {**AGENT, "model": "haiku"}
        asyncio.run(Turn(agent, ROLE, "hola", lambda e: None, None, model="opus",
                         env={"ANTHROPIC_API_KEY": "k"}, client_factory=factory).run())
        self.assertEqual(clients[0].options.model, "haiku")
        self.assertEqual(clients[0].options.env, {"ANTHROPIC_API_KEY": "k"})
        asyncio.run(Turn(AGENT, ROLE, "hola", lambda e: None, None, model="opus", client_factory=factory).run())
        self.assertEqual(clients[1].options.model, "opus")  # agent without model -> global default

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
    def test_prompt_tells_agent_its_name_and_the_board(self):
        clients = []

        def factory(options):
            clients.append(FakeClient(options, [result()]))
            return clients[-1]

        asyncio.run(Turn(AGENT, ROLE, "hola", lambda e: None, None, client_factory=factory).run())
        append = clients[0].options.system_prompt["append"]
        self.assertTrue(append.startswith("rol"))
        self.assertIn("Te llamas Dev", append)
        self.assertIn("tablero", append)
        # Existing sessions must pick up prompt changes (role edits, this line) on resume.
        self.assertIs(clients[0].options.system_prompt.get("snapshot"), False)

    def test_activity_follows_thinking_and_tools(self):
        script = [
            StreamEvent(uuid="u", session_id="s-1", event={"type": "content_block_start", "index": 0,
                                                           "content_block": {"type": "thinking"}}),
            AssistantMessage(content=[ToolUseBlock(id="t1", name="Read", input={"file_path": "/x"})], model="m"),
            UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok", is_error=False)]),
            StreamEvent(uuid="u", session_id="s-1", event={"type": "content_block_start", "index": 0,
                                                           "content_block": {"type": "text"}}),
            result(),
        ]
        _, events, _, _ = self.run_turn(script)
        self.assertEqual([e["kind"] for e in events if e["type"] == "activity"],
                         ["thinking", "tool", "thinking", "thinking"])

    def test_attachments_folder_is_readable_without_asking(self):
        from hivemind import attachments
        inside = str(attachments.root() / "a1" / "ab12-captura.png")
        script = [AssistantMessage(content=[ToolUseBlock(id="t1", name="Read", input={"file_path": inside}),
                                            ToolUseBlock(id="t2", name="Read", input={"file_path": "/etc/shadow"}),
                                            ToolUseBlock(id="t3", name="Read",
                                                         input={"file_path": str(attachments.root() / "a1" / ".." / ".." / ".." / "x")})],
                                   model="m"), result()]
        clients, asked = [], []

        async def ask(tool, input, rule):
            asked.append(input["file_path"])
            return "deny"

        def factory(options):
            clients.append(FakeClient(options, script))
            return clients[-1]

        role = {"system_prompt": "rol", "allowed_tools": []}  # a role that allows nothing by itself
        asyncio.run(Turn(AGENT, role, "mira", lambda e: None, ask, thread="a1", client_factory=factory).run())
        self.assertEqual(asked[0], "/etc/shadow")
        self.assertEqual(len(asked), 2)  # "../" out of the folder still asks
        self.assertIn(str(attachments.root() / "a1"), clients[0].options.add_dirs)

    def test_only_this_conversations_attachments_are_free_to_read(self):
        from hivemind import attachments
        mine = str(attachments.root() / "a1" / "x-mine.png")
        other = str(attachments.root() / "g-12345678" / "x-other.png")
        script = [AssistantMessage(content=[ToolUseBlock(id="t1", name="Read", input={"file_path": mine}),
                                            ToolUseBlock(id="t2", name="Read", input={"file_path": other}),
                                            ToolUseBlock(id="t3", name="Read", input={"file_path": "adjuntos/a1/x.png"})],
                                   model="m"), result()]
        clients, asked = [], []

        async def ask(tool, input, rule):
            asked.append(input["file_path"])
            return "deny"

        def factory(options):
            clients.append(FakeClient(options, script))
            return clients[-1]

        role = {"system_prompt": "rol", "allowed_tools": []}
        asyncio.run(Turn(AGENT, role, "mira", lambda e: None, ask, thread="a1", client_factory=factory).run())
        self.assertEqual(asked, [other, "adjuntos/a1/x.png"])  # other conversations and relative paths ask
        self.assertEqual(clients[0].options.add_dirs, [str(attachments.root() / "a1")])


if __name__ == "__main__":
    unittest.main()
