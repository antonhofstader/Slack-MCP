"""
Layer 3 — Python MCP Client  (transport layer)

Responsibilities:
  • Spawns the C# MCP server process
  • Speaks JSON-RPC 2.0 over the process stdin / stdout
  • Implements the MCP lifecycle (initialize → tools/list → tools/call)
  • Exposes a clean async API to the Agent layer above

This module knows nothing about Slack or user intent — it is a pure
MCP transport implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("mcp.transport")


# ── Exceptions ─────────────────────────────────────────────────────────────────


class McpError(Exception):
    def __init__(self, message: str, code: int = -1) -> None:
        super().__init__(f"MCP error {code}: {message}")
        self.code = code


class McpToolError(Exception):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"Tool '{tool}' returned error: {message}")
        self.tool = tool


# ── Low-level stdio transport ──────────────────────────────────────────────────


@dataclass
class StdioTransport:
    """
    Manages the C# server subprocess and handles raw JSON-RPC framing.
    One line in → one JSON object; one JSON object → one line out.
    """

    cmd: list[str]
    _proc: asyncio.subprocess.Process | None = field(default=None, init=False)
    _pending: dict[int, asyncio.Future[Any]] = field(default_factory=dict, init=False)
    _read_task: asyncio.Task | None = field(default=None, init=False)
    _next_id: int = field(default=1, init=False)

    async def start(self) -> None:
        env = {**os.environ}
        self._proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._read_task = asyncio.create_task(self._read_loop(), name="stdio-read")
        asyncio.create_task(self._stderr_loop(), name="stdio-stderr")
        log.info("Server process started (pid=%d, cmd=%s)", self._proc.pid, self.cmd[0])

    async def stop(self) -> None:
        if self._read_task:
            self._read_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        log.info("Server process stopped.")

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        req_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, **({"params": params} if params else {})})
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((msg + "\n").encode())
        await self._proc.stdin.drain()
        log.debug("→ %s (id=%d)", method, req_id)

        return await asyncio.wait_for(future, timeout=30.0)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg = json.dumps({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((msg + "\n").encode())
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                log.warning("Server stdout closed.")
                break
            try:
                msg = json.loads(raw.decode().strip())
            except json.JSONDecodeError as exc:
                log.warning("Malformed server message (%s): %r", exc, raw[:200])
                continue

            req_id = msg.get("id")
            if req_id is not None and req_id in self._pending:
                fut = self._pending.pop(req_id)
                if "error" in msg:
                    e = msg["error"]
                    fut.set_exception(McpError(e["message"], e.get("code", -1)))
                else:
                    fut.set_result(msg.get("result"))
            else:
                log.debug("Notification / unknown id: method=%s", msg.get("method"))

    async def _stderr_loop(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            log.debug("[server] %s", line.decode().rstrip())


# ── High-level MCP client ──────────────────────────────────────────────────────


class McpClient:
    """
    High-level MCP client used by the Agent layer.

    Wraps StdioTransport with:
      - MCP lifecycle management (initialize / initialized)
      - Tool discovery (tools/list)
      - Tool invocation (tools/call)
      - Typed convenience wrappers for every Slack tool
    """

    def __init__(self, server_cmd: list[str]) -> None:
        self._transport = StdioTransport(cmd=server_cmd)
        self._tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> "McpClient":
        await self._transport.start()
        await self._handshake()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._transport.stop()

    # ── MCP lifecycle ───────────────────────────────────────────────────────────

    async def _handshake(self) -> None:
        result = await self._transport.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "python-mcp-client", "version": "2.0.0"},
            },
        )
        info = result.get("serverInfo", {})
        log.info("Connected → %s %s", info.get("name"), info.get("version"))
        await self._transport.notify("initialized")
        await self._discover_tools()

    async def _discover_tools(self) -> None:
        result = await self._transport.request("tools/list")
        self._tools = result.get("tools", [])
        log.info("Tools discovered: %s", [t["name"] for t in self._tools])

    # ── public API (used by Agent layer) ────────────────────────────────────────

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Return the raw MCP tool schemas (pass directly to an LLM's tools param)."""
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """
        Call any MCP tool by name.  Returns the concatenated text content.
        Raises McpToolError if the server returns isError=True.
        """
        result = await self._transport.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if result.get("isError"):
            raise McpToolError(name, result["content"][0]["text"])
        return "\n".join(c["text"] for c in result.get("content", []))

    # ── typed convenience wrappers ──────────────────────────────────────────────

    async def send_message(self, channel: str, text: str, thread_ts: str | None = None) -> str:
        args: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            args["thread_ts"] = thread_ts
        return await self.call_tool("slack_send_message", args)

    async def get_channel_history(self, channel: str, limit: int = 10) -> str:
        return await self.call_tool("slack_get_channel_history", {"channel": channel, "limit": str(limit)})

    async def list_channels(self, types: str = "public_channel") -> str:
        return await self.call_tool("slack_list_channels", {"types": types})

    async def create_channel(self, name: str) -> str:
        return await self.call_tool("slack_create_channel", {"name": name})

    async def add_reaction(self, channel: str, timestamp: str, emoji: str) -> str:
        return await self.call_tool("slack_add_reaction", {"channel": channel, "timestamp": timestamp, "emoji": emoji})

    async def list_users(self) -> str:
        return await self.call_tool("slack_list_users")
