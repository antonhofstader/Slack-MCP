"""
Layer 1 — 👤 User(s)
Entry point for human operators / end-users.

Accepts natural language input and passes it to the Prompt + Agent layer.

Usage:
    python main.py
    python main.py --prompt "List all Slack channels"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from agent.agent import SlackAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)


async def interactive_mode(agent: SlackAgent) -> None:
    """REPL: read a prompt from the user, hand it to the agent, print the result."""
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║        Slack MCP Assistant  (type 'quit' to exit)    ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print("Examples:")
    print("  • List all channels")
    print("  • Send 'Hello team!' to channel C012AB3CD")
    print("  • Show the last 5 messages in C012AB3CD")
    print("  • Create a channel called project-updates")
    print("  • Add a thumbsup reaction to message 1234567890.000 in C012AB3CD")
    print("  • List all users\n")

    while True:
        try:
            prompt = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not prompt:
            continue
        if prompt.lower() in {"quit", "exit", "q"}:
            print("Goodbye!")
            break

        response = await agent.handle(prompt)
        print(f"\nAssistant > {response}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Slack MCP — User interface (Layer 1)"
    )
    parser.add_argument(
        "--prompt",
        help="Single prompt to execute (non-interactive mode)",
    )
    parser.add_argument(
        "--server-cmd",
        default="dotnet run --project ../server-csharp/SlackMcpServer.csproj",
        help="Command to launch the C# MCP server",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level)

    if not os.environ.get("SLACK_BOT_TOKEN"):
        print(
            "WARNING: SLACK_BOT_TOKEN is not set — Slack calls will fail.",
            file=sys.stderr,
        )

    server_cmd = args.server_cmd.split()

    async with SlackAgent(server_cmd=server_cmd) as agent:
        if args.prompt:
            # Non-interactive: run one prompt and exit
            response = await agent.handle(args.prompt)
            print(response)
        else:
            await interactive_mode(agent)


if __name__ == "__main__":
    asyncio.run(main())
