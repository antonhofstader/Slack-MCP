"""
Tests for Layer 3 — MCP transport layer (StdioTransport + McpClient).

All tests mock the subprocess so no real server is needed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from transport.mcp_client import McpClient, McpError, McpToolError, StdioTransport


def encode(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode()


def ok_response(req_id: int, result: object) -> bytes:
    return encode({"jsonrpc": "2.0", "id": req_id, "result": result})


def err_response(req_id: int, code: int, message: str) -> bytes:
    return encode({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


class TestStdioTransport:

    @pytest.mark.asyncio
    async def test_successful_request(self):
        transport = StdioTransport(cmd=["echo"])
        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.returncode = None
        mock_proc.stdin = AsyncMock()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.readline = AsyncMock(return_value=b"")
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=[ok_response(1, {"pong": True}), b""])

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await transport.start()
            result = await transport.request("ping")
            assert result == {"pong": True}
            await transport.stop()

    @pytest.mark.asyncio
    async def test_error_response_raises_mcp_error(self):
        transport = StdioTransport(cmd=["echo"])
        mock_proc = MagicMock()
        mock_proc.pid = 1
        mock_proc.returncode = None
        mock_proc.stdin = AsyncMock()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.readline = AsyncMock(return_value=b"")
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.readline = AsyncMock(
            side_effect=[err_response(1, -32601, "Method not found"), b""]
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await transport.start()
            with pytest.raises(McpError) as exc:
                await transport.request("unknown")
            assert "-32601" in str(exc.value)
            await transport.stop()


class TestMcpClient:

    def _make_client(self, transport: AsyncMock) -> McpClient:
        client = McpClient.__new__(McpClient)
        client._transport = transport
        client._tools = []
        return client

    @pytest.mark.asyncio
    async def test_handshake_and_tool_discovery(self):
        transport = AsyncMock()
        transport.request.side_effect = [
            # initialize
            {"protocolVersion": "2024-11-05", "serverInfo": {"name": "test", "version": "1"}, "capabilities": {}},
            # tools/list
            {"tools": [{"name": "slack_send_message", "description": "Send", "inputSchema": {}}]},
        ]
        client = self._make_client(transport)
        await client._handshake()
        assert len(client.tools) == 1
        assert client.tools[0]["name"] == "slack_send_message"

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        transport = AsyncMock()
        transport.request.return_value = {
            "content": [{"type": "text", "text": "Done"}],
            "isError": False,
        }
        client = self._make_client(transport)
        result = await client.call_tool("slack_list_channels", {})
        assert result == "Done"

    @pytest.mark.asyncio
    async def test_call_tool_error_raises(self):
        transport = AsyncMock()
        transport.request.return_value = {
            "content": [{"type": "text", "text": "channel_not_found"}],
            "isError": True,
        }
        client = self._make_client(transport)
        with pytest.raises(McpToolError) as exc:
            await client.call_tool("slack_send_message", {})
        assert "channel_not_found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_convenience_wrappers_call_correct_tools(self):
        transport = AsyncMock()
        transport.request.return_value = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        client = self._make_client(transport)

        cases = [
            (client.send_message("C1", "hi"),         "slack_send_message"),
            (client.get_channel_history("C1"),         "slack_get_channel_history"),
            (client.list_channels(),                   "slack_list_channels"),
            (client.create_channel("test"),            "slack_create_channel"),
            (client.add_reaction("C1", "123", "wave"), "slack_add_reaction"),
            (client.list_users(),                      "slack_list_users"),
        ]

        for coro, expected_tool in cases:
            await coro
            actual_tool = transport.request.call_args[0][1]["name"]
            assert actual_tool == expected_tool, f"Expected {expected_tool}, got {actual_tool}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
