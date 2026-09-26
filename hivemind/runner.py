from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient,
                              PermissionResultAllow, PermissionResultDeny, ResultMessage,
                              StreamEvent, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage)

from hivemind import attachments
from hivemind.roles import permitted, suggested_rule

DENY_MESSAGE = "El usuario denegó esta acción"
BOARD_RULE = "mcp__tablero__*"
_MAX_RESULT = 4000


def _text_of(content):
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return (content or "")[:_MAX_RESULT]


class Turn:
    def __init__(self, agent, role, prompt, emit, ask, model=None, env=None, mcp_servers=None,
                 client_factory=ClaudeSDKClient):
        self.agent, self.role, self.prompt = agent, role, prompt
        self.emit, self.ask = emit, ask
        self.model = agent.get("model") or model
        self.env = env
        self.mcp_servers = mcp_servers
        self.client_factory = client_factory
        self.client = None
        self.stopped = False

    async def _can_use(self, tool, input, ctx):
        rules = [BOARD_RULE] + self.role["allowed_tools"] + self.agent["extra_allowed"]
        if permitted(tool, input, rules) or self._reads_an_attachment(tool, input):
            return PermissionResultAllow()
        decision = await self.ask(tool, input, suggested_rule(tool, input, ctx.suggestions))
        if decision == "deny":
            return PermissionResultDeny(message=DENY_MESSAGE)
        return PermissionResultAllow()

    def _prompt(self):
        return (f"{self.role['system_prompt']}\n\nTe llamas {self.agent['name']} en HiveMind. Hay un tablero "
                "compartido de tareas (herramientas tablero_listar, tablero_crear, tablero_mover y "
                "tablero_asignar): úsalo para coordinar trabajo de varios pasos con los demás agentes.")

    @staticmethod
    def _reads_an_attachment(tool, input):
        """Reading files attached to messages never needs approval. The path is resolved first,
        so "adjuntos/../../etc" does not count as inside the folder."""
        if tool != "Read" or not input.get("file_path"):
            return False
        path = Path(input["file_path"]).expanduser().resolve()
        return path.is_relative_to(attachments.root().resolve())

    def _options(self):
        attachments.root().mkdir(parents=True, exist_ok=True)  # the CLI wants add_dirs to exist
        return ClaudeAgentOptions(
            cwd=self.agent["cwd"],
            resume=self.agent["session_id"],
            model=self.model,
            system_prompt={"type": "preset", "preset": "claude_code", "append": self._prompt(),
                           "snapshot": False},
            can_use_tool=self._can_use,
            include_partial_messages=True,
            setting_sources=["user", "project", "local"],
            env=self.env or {},
            mcp_servers=self.mcp_servers or {},
            add_dirs=[str(attachments.root())],
        )

    def _translate(self, m):
        if isinstance(m, StreamEvent):
            delta = m.event.get("delta", {})
            if m.event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                self.emit({"type": "delta", "text": delta["text"]})
            elif (m.event.get("type") == "content_block_start"
                  and m.event.get("content_block", {}).get("type") in ("thinking", "text")):
                self.emit({"type": "activity", "kind": "thinking"})
        elif isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, TextBlock):
                    self.emit({"type": "text", "text": b.text})
                elif isinstance(b, ToolUseBlock):
                    self.emit({"type": "activity", "kind": "tool"})
                    self.emit({"type": "tool", "id": b.id, "name": b.name, "input": b.input})
        elif isinstance(m, UserMessage) and isinstance(m.content, list):
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    self.emit({"type": "tool_result", "id": b.tool_use_id,
                               "content": _text_of(b.content), "is_error": bool(b.is_error)})
                    self.emit({"type": "activity", "kind": "thinking"})

    async def run(self):
        out = {"session_id": self.agent["session_id"], "is_error": True, "text": "", "cost": None}
        async with self.client_factory(self._options()) as client:
            if self.stopped:  # stopped while the CLI was still starting
                return {**out, "is_error": False}
            self.client = client
            await client.query(self.prompt)
            async for m in client.receive_response():
                if isinstance(m, ResultMessage):
                    out = {"session_id": m.session_id, "is_error": m.is_error,
                           "text": m.result or "", "cost": m.total_cost_usd}
                else:
                    self._translate(m)
        self.client = None
        return out

    async def stop(self):
        self.stopped = True
        if self.client:
            await self.client.interrupt()
