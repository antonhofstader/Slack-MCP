# Slack MCP — Python Client + C# Server

A complete **Model Context Protocol (MCP)** implementation with four architectural layers.

| Layer | Language | File(s) |
|-------|----------|---------|
| 1 — Users             | Python 3.11+ | `client-python/main.py` |
| 2 — Prompt + Agent    | Python 3.11+ | `client-python/agent/agent.py` |
| 3 — MCP Client/Server | Python + C#  | `client-python/transport/mcp_client.py` · `server-csharp/` |
| 4 — Slack             | C# / .NET 8  | `server-csharp/Services/SlackService.cs` |

---

## Architecture

```
  👤 User(s)
  (human operators / end-users)
       │  natural language input
       ▼
┌──────────────────────────────────────────────────────────┐
│  Prompt + Agent Layer                                    │
│                                                          │
│  Claude (Anthropic) ──or── External Agent                │
│    • interprets user intent                              │
│    • decides which MCP tool(s) to call                   │
│    • formats results back to the user                    │
└──────────────────────┬───────────────────────────────────┘
                       │  tool calls
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Python MCP Client  (client-python/transport/)           │
│                                                          │
│  McpClient                                               │
│    └── StdioTransport                                    │
│          ├── spawns: dotnet run SlackMcpServer           │
│          └── JSON-RPC 2.0 over stdin / stdout            │
└──────────────────────┬───────────────────────────────────┘
                       │  stdio
┌──────────────────────▼───────────────────────────────────┐
│  C# MCP Server  (server-csharp/)                         │
│                                                          │
│  Program.cs  (stdio loop)                                │
│    └── ToolRegistry  (dispatch)                          │
│          └── SlackService  (Slack Web API)               │
└──────────────────────┬───────────────────────────────────┘
                       │  HTTPS
┌──────────────────────▼───────────────────────────────────┐
│  Slack                                                   │
│                                                          │
│  • send_message     → post to channel or thread          │
│  • get_history      → read recent messages               │
│  • list_channels    → browse workspace channels          │
│  • create_channel   → open a new public channel          │
│  • add_reaction     → emoji-react to a message           │
│  • list_users       → enumerate workspace members        │
└──────────────────────────────────────────────────────────┘
```

### MCP Protocol Flow

```
Python Client                    C# Server
     │                               │
     │── initialize ────────────────►│
     │◄─ InitializeResult ───────────│
     │── initialized (notification) ►│
     │── tools/list ────────────────►│
     │◄─ ListToolsResult ────────────│
     │── tools/call {name, args} ───►│
     │◄─ CallToolResult ─────────────│
```

---

## Layer Responsibilities

### Layer 1 — 👤 Users  (`main.py`)
Entry point for human operators. Provides an interactive REPL or single-prompt CLI. Has no knowledge of Slack or MCP — it only calls `agent.handle(prompt)`.

### Layer 2 — Prompt + Agent  (`agent/agent.py`)
Interprets natural language intent and decides which MCP tool to call. The `_resolve_intent()` method is rule-based by default — **replace it with a real LLM call** (see comments in the file). Formats raw tool output into human-readable responses.

### Layer 3 — MCP Transport  (`transport/mcp_client.py` + `server-csharp/`)
Pure protocol layer. The Python side spawns the C# process and speaks JSON-RPC 2.0 over stdio. The C# side receives requests, dispatches to `ToolRegistry`, and writes responses. Neither side knows about user intent.

### Layer 4 — Slack  (`server-csharp/Services/SlackService.cs`)
Deepest layer. Each of the six methods maps directly to one Slack Web API endpoint. No MCP concepts here — just HTTP calls and typed DTOs.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| .NET SDK | 8.0+ |
| Slack Bot Token | `xoxb-…` |

### Slack Bot Scopes Required

Go to **api.slack.com/apps** → OAuth & Permissions → Bot Token Scopes:

| Scope | Used by |
|-------|---------|
| `chat:write`       | send_message |
| `channels:history` | get_history  |
| `channels:read`    | list_channels |
| `channels:write`   | create_channel |
| `reactions:write`  | add_reaction |
| `users:read`       | list_users |

---

## Quick Start

```bash
# 1. Set your Slack bot token
export SLACK_BOT_TOKEN="xoxb-your-token-here"

# 2. Build the C# server
cd server-csharp
dotnet build

# 3. Run the interactive client
cd ../client-python
python main.py --server-cmd "dotnet run --project ../server-csharp/SlackMcpServer.csproj"

# Or run a single prompt
python main.py --prompt "List all channels"
```

---

## Connecting a Real LLM (Claude)

Open `client-python/agent/agent.py` and replace `_resolve_intent()` with:

```python
import anthropic

def _resolve_intent(self, prompt: str) -> Intent:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        tools=self._client.tools,   # pass MCP schemas directly
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return Intent(
        tool=tool_use.name,
        args=tool_use.input,
        explanation=prompt,
    )
```

Install the SDK: `pip install anthropic`

---

## Running Tests

```bash
cd client-python
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

Tests are split by layer:
- `tests/test_agent.py` — Layer 2: intent resolution and response formatting
- `tests/test_transport.py` — Layer 3: JSON-RPC transport and MCP client

---

## Project Structure

```
mcp-slack/
├── server-csharp/                   # Layer 3 (server) + Layer 4
│   ├── SlackMcpServer.csproj
│   ├── Program.cs                   # stdio JSON-RPC loop
│   ├── Models/
│   │   └── McpModels.cs             # JSON-RPC + MCP protocol types
│   ├── Services/
│   │   └── SlackService.cs          # Layer 4 — Slack Web API
│   └── Tools/
│       └── ToolRegistry.cs          # MCP tool definitions + dispatcher
│
└── client-python/                   # Layers 1, 2, 3 (client)
    ├── main.py                      # Layer 1 — User entry point
    ├── agent/
    │   ├── __init__.py
    │   └── agent.py                 # Layer 2 — Prompt + Agent
    ├── transport/
    │   ├── __init__.py
    │   └── mcp_client.py            # Layer 3 — MCP transport
    ├── tests/
    │   ├── conftest.py
    │   ├── test_agent.py
    │   └── test_transport.py
    ├── pytest.ini
    └── requirements.txt
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `SLACK_BOT_TOKEN is not set` | `export SLACK_BOT_TOKEN="xoxb-..."` |
| `channel_not_found` | Use a Channel ID like `C012AB3CD`, not `#general` |
| `not_in_channel` | Invite the bot to the channel first |
| Server won't start | Run `dotnet build` in `server-csharp/` first |
| Intent not recognized | Extend `_resolve_intent()` or plug in a real LLM |
