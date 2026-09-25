import asyncio
import unittest
from types import SimpleNamespace as NS

from claude_agent_sdk import (AssistantMessage, PermissionResultAllow, PermissionResultDeny,
                              ResultMessage, StreamEvent, TextBlock, ToolResultBlock,
                              ToolUseBlock, UserMessage)

from colmena.runner import DENY_MESSAGE, Turn


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
        self.assertEqual([e["type"] for e in events], ["delta", "text", "tool", "tool_result"])
        self.assertEqual(len(events[3]["content"]), 4000)
        self.assertEqual(asked, [])  # Read is in the role's allowed tools
        self.assertEqual(client.options.resume, None)
        self.assertEqual(client.options.system_prompt["append"], "rol")

    def test_extra_allowed_and_ask(self):
        script = [
            AssistantMessage(content=[ToolUseBlock(id="t1", name="Bash", input={"command": "ls -la"}),
                                      ToolUseBlock(id="t2", name="Bash", input={"command": "rm x"})], model="m"),
            result(),
        ]
        _, _, asked, client = self.run_turn(script, answer="deny")
        self.assertEqual(asked, [("Bash", "Bash")])
        self.assertIsInstance(client.decisions[0], PermissionResultAllow)
        self.assertIsInstance(client.decisions[1], PermissionResultDeny)
        self.assertEqual(client.decisions[1].message, DENY_MESSAGE)


if __name__ == "__main__":
    unittest.main()
