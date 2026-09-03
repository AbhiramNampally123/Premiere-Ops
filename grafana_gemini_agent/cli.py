"""Command-line interface for one-shot and interactive Grafana questions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from .config import AgentConfig
from .errors import AgentError
from .gemini_agent import GeminiReasoningAgent
from .mcp_adapter import GrafanaMcpAdapter


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="grafana-gemini-agent",
        description="Ask grounded natural-language questions about Grafana metrics.",
    )
    parser.add_argument(
        "-q",
        "--question",
        help="Ask one question and exit. Without it, start the interactive prompt.",
    )
    return parser.parse_args(argv)


async def run_question(config: AgentConfig, question: str) -> int:
    async with GrafanaMcpAdapter(config) as mcp:
        answer = await GeminiReasoningAgent(config, mcp).answer(question)
    print(answer.text)
    if answer.tools_used:
        print(f"\nTools consulted: {', '.join(answer.tools_used)}")
    else:
        print("\nNo Grafana read tool was needed; live metric observations were not available.")
    return 0


async def run_interactive(config: AgentConfig) -> int:
    print("Grafana Gemini Agent — ask about Grafana metrics. Type 'quit' to exit.")
    async with GrafanaMcpAdapter(config) as mcp:
        agent = GeminiReasoningAgent(config, mcp)
        while True:
            try:
                question = input("\nQuestion> ").strip()
            except EOFError:
                print()
                return 0
            if question.lower() in {"quit", "exit"}:
                return 0
            if not question:
                continue
            try:
                answer = await agent.answer(question)
                print(f"\n{answer.text}")
                if answer.tools_used:
                    print(f"Tools consulted: {', '.join(answer.tools_used)}")
            except AgentError as exc:
                print(f"\nError: {exc}", file=sys.stderr)


async def _async_main(args: argparse.Namespace) -> int:
    config = AgentConfig.from_env()
    if args.question:
        return await run_question(config, args.question)
    return await run_interactive(config)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except AgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130