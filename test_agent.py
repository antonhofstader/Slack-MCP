"""
Tests for Layer 2 — Prompt + Agent layer.

Verifies that _resolve_intent() correctly maps natural language prompts
to the right MCP tool and arguments, independently of any live server.
"""
from __future__ import annotations

import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.agent import SlackAgent, Intent


def make_agent() -> SlackAgent:
    agent = SlackAgent.__new__(SlackAgent)
    agent._client = MagicMock()
    agent._client.tools = []
    return agent


class TestIntentResolution:

    def test_list_channels_default(self):
        agent = make_agent()
        intent = agent._resolve_intent("what channels are there?")
        assert intent.tool == "slack_list_channels"

    def test_list_channels_explicit(self):
        agent = make_agent()
        intent = agent._resolve_intent("list all channels")
        assert intent.tool == "slack_list_channels"

    def test_send_message(self):
        agent = make_agent()
        intent = agent._resolve_intent("Send 'Hello team!' to channel C012AB3CD")
        assert intent.tool == "slack_send_message"
        assert intent.args["channel"] == "C012AB3CD"
        assert "Hello team!" in intent.args["text"]

    def test_get_history_with_limit(self):
        agent = make_agent()
        intent = agent._resolve_intent("Show last 5 messages in C012AB3CD")
        assert intent.tool == "slack_get_channel_history"
        assert intent.args["channel"] == "C012AB3CD"
        assert intent.args["limit"] == "5"

    def test_get_history_default_limit(self):
        agent = make_agent()
        intent = agent._resolve_intent("get messages from C999XYZ")
        assert intent.tool == "slack_get_channel_history"
        assert intent.args["limit"] == "10"

    def test_create_channel(self):
        agent = make_agent()
        intent = agent._resolve_intent("Create a channel called project-updates")
        assert intent.tool == "slack_create_channel"
        assert intent.args["name"] == "project-updates"

    def test_add_reaction(self):
        agent = make_agent()
        intent = agent._resolve_intent("Add a thumbsup reaction to message 1234567890.000 in C012AB3CD")
        assert intent.tool == "slack_add_reaction"
        assert intent.args["emoji"] == "thumbsup"
        assert intent.args["timestamp"] == "1234567890.000"
        assert intent.args["channel"] == "C012AB3CD"

    def test_list_users(self):
        agent = make_agent()
        for prompt in ["list users", "show all users", "list workspace members"]:
            intent = agent._resolve_intent(prompt)
            assert intent.tool == "slack_list_users", f"Failed for: {prompt!r}"


class TestFormatResponse:

    def test_format_send_message(self):
        agent = make_agent()
        intent = Intent(tool="slack_send_message", args={}, explanation="")
        result = agent._format_response(intent, "Message sent. Timestamp: 123")
        assert "✅" in result

    def test_format_list_channels(self):
        agent = make_agent()
        intent = Intent(tool="slack_list_channels", args={}, explanation="")
        raw = "C001 | #general\nC002 | #random"
        result = agent._format_response(intent, raw)
        assert "2 channel(s)" in result
        assert "#general" in result

    def test_format_list_users(self):
        agent = make_agent()
        intent = Intent(tool="slack_list_users", args={}, explanation="")
        raw = "U001 | @alice (Alice Smith)\nU002 | @bob (Bob Jones)"
        result = agent._format_response(intent, raw)
        assert "2 user(s)" in result
        assert "@alice" in result

    def test_format_empty_history(self):
        agent = make_agent()
        intent = Intent(tool="slack_get_channel_history", args={}, explanation="")
        result = agent._format_response(intent, "")
        assert "No messages" in result


class TestHandleIntegration:
    """Integration tests that mock the MCP client."""

    @pytest.mark.asyncio
    async def test_handle_calls_tool_and_formats(self):
        agent = make_agent()
        agent._client.call_tool = AsyncMock(return_value="C001 | #general\nC002 | #random")

        result = await agent.handle("list channels")
        assert "2 channel(s)" in result
        agent._client.call_tool.assert_called_once_with("slack_list_channels", {"types": "public_channel"})

    @pytest.mark.asyncio
    async def test_handle_returns_error_on_exception(self):
        agent = make_agent()
        agent._client.call_tool = AsyncMock(side_effect=Exception("Slack is down"))

        result = await agent.handle("list channels")
        assert "wrong" in result.lower() or "error" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
