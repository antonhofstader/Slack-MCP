"""
Layer 2 — Prompt + Agent Layer
Claude (Anthropic) or External Agent.

Responsibilities:
  • Interprets natural language user intent
  • Decides which MCP tool(s) to call
  • Formats tool results back into a human-readable response

This module is intentionally decoupled from both the User layer (main.py)
and the transport layer (transport/mcp_client.py).  Swap out the
_resolve_intent() method to plug in a real LLM (Claude API, OpenAI, etc.).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from transport.mcp_client import McpClient

log = logging.getLogger("agent")


# ── Intent model ───────────────────────────────────────────────────────────────


@dataclass
class Intent:
    """Structured representation of what the user wants to do."""

    tool: str
    args: dict[str, Any]
    explanation: str  # human-readable description of what will happen


# ── Agent ──────────────────────────────────────────────────────────────────────


class SlackAgent:
    """
    Prompt + Agent layer.

    Can be used as an async context manager — it manages the lifecycle of the
    underlying MCP client (and therefore the C# server process).

    Replace or extend _resolve_intent() to connect a real LLM.
    """

    def __init__(self, server_cmd: list[str]) -> None:
        self._client = McpClient(server_cmd)

    async def __aenter__(self) -> "SlackAgent":
        await self._client.__aenter__()
        log.info("SlackAgent ready. Tools: %s", [t["name"] for t in self._client.tools])
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.__aexit__(*args)

    # ── public API ──────────────────────────────────────────────────────────────

    async def handle(self, user_prompt: str) -> str:
        """
        Main entry point called by the User layer.

        1. Resolves the prompt into a structured Intent.
        2. Calls the appropriate MCP tool via the transport layer.
        3. Formats and returns the result.
        """
        log.info("Handling prompt: %r", user_prompt)

        intent = self._resolve_intent(user_prompt)
        log.info("Resolved intent: tool=%s args=%s", intent.tool, intent.args)

        try:
            raw = await self._client.call_tool(intent.tool, intent.args)
            return self._format_response(intent, raw)
        except Exception as e:  # noqa: BLE001
            log.error("Tool call failed: %s", e)
            return f"Sorry, something went wrong: {e}"

    # ── intent resolution (rule-based / swap for LLM) ──────────────────────────

    def _resolve_intent(self, prompt: str) -> Intent:
        """
        Rule-based intent resolver.

        In production replace this body with a call to Claude via the
        Anthropic Python SDK, passing `self._client.tools` as the
        `tools` parameter so the model can pick and fill them itself.

        Example (Claude API):
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1024,
                tools=self._client.tools,   # MCP tool schemas
                messages=[{"role": "user", "content": prompt}],
            )
            tool_use = next(b for b in response.content if b.type == "tool_use")
            return Intent(tool=tool_use.name, args=tool_use.input, explanation=prompt)
        """
        p = prompt.lower()

        # ── send message ────────────────────────────────────────────────────────
        send_match = re.search(
            r"send\s+['\"]?(.+?)['\"]?\s+to\s+(?:channel\s+)?(\S+)", prompt, re.IGNORECASE
        )
        if send_match:
            text, channel = send_match.group(1), send_match.group(2)
            return Intent(
                tool="slack_send_message",
                args={"channel": channel, "text": text},
                explanation=f"Sending message to {channel}",
            )

        # ── get history ─────────────────────────────────────────────────────────
        history_match = re.search(
            r"(?:show|get|fetch|last)\s+(?:(\d+)\s+)?messages?\s+(?:in|from|for)\s+(\S+)",
            prompt, re.IGNORECASE,
        )
        if history_match:
            limit = int(history_match.group(1) or 10)
            channel = history_match.group(2)
            return Intent(
                tool="slack_get_channel_history",
                args={"channel": channel, "limit": str(limit)},
                explanation=f"Fetching last {limit} messages from {channel}",
            )

        # ── create channel ──────────────────────────────────────────────────────
        create_match = re.search(
            r"create\s+(?:a\s+)?channel\s+(?:called\s+|named\s+)?(\S+)", prompt, re.IGNORECASE
        )
        if create_match:
            name = create_match.group(1).lstrip("#")
            return Intent(
                tool="slack_create_channel",
                args={"name": name},
                explanation=f"Creating channel #{name}",
            )

        # ── add reaction ────────────────────────────────────────────────────────
        reaction_match = re.search(
            r"add\s+(?:a\s+)?(\w+)\s+reaction\s+to\s+(?:message\s+)?(\S+)\s+in\s+(\S+)",
            prompt, re.IGNORECASE,
        )
        if reaction_match:
            emoji, ts, channel = reaction_match.group(1), reaction_match.group(2), reaction_match.group(3)
            return Intent(
                tool="slack_add_reaction",
                args={"channel": channel, "timestamp": ts, "emoji": emoji},
                explanation=f"Adding :{emoji}: reaction",
            )

        # ── list users ──────────────────────────────────────────────────────────
        if any(kw in p for kw in ("list users", "show users", "all users", "workspace members", "list members")):
            return Intent(
                tool="slack_list_users",
                args={},
                explanation="Listing all workspace users",
            )

        # ── list channels (default) ─────────────────────────────────────────────
        return Intent(
            tool="slack_list_channels",
            args={"types": "public_channel"},
            explanation="Listing all public channels",
        )

    # ── response formatting ─────────────────────────────────────────────────────

    def _format_response(self, intent: Intent, raw: str) -> str:
        """Turn the raw tool output into a friendly reply."""
        lines = raw.strip().splitlines()

        if intent.tool == "slack_send_message":
            return f"✅ Message sent! {raw}"

        if intent.tool == "slack_get_channel_history":
            if not lines:
                return "No messages found."
            header = f"📜 Last {len(lines)} message(s):\n"
            return header + "\n".join(f"  {l}" for l in lines)

        if intent.tool == "slack_list_channels":
            if not lines:
                return "No channels found."
            return f"📋 {len(lines)} channel(s) found:\n" + "\n".join(f"  {l}" for l in lines)

        if intent.tool == "slack_create_channel":
            return f"✅ {raw}"

        if intent.tool == "slack_add_reaction":
            return f"✅ {raw}"

        if intent.tool == "slack_list_users":
            if not lines:
                return "No users found."
            return f"👥 {len(lines)} user(s):\n" + "\n".join(f"  {l}" for l in lines)

        return raw
