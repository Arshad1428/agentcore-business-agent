"""Local entry point: run the agent directly (no AgentCore, no AWS needed with Ollama)."""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from business_agent.agent import build_agent, extract_tool_calls  # noqa: E402
from business_agent.config import load_settings  # noqa: E402


def run(agent, prompt: str, trace: bool) -> None:
    start = len(agent.messages)
    result = agent(prompt)
    print(f"\nAgent: {result}\n")
    calls = extract_tool_calls(agent.messages[start:], include_inputs=True)
    if trace or calls:
        print("--- tool trace ---")
        for i, c in enumerate(calls, 1):
            print(f"{i}. {c['name']}({json.dumps(c.get('input', {}))}) -> {c['status']}")
        if not calls:
            print("(no tools used)")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Purchase Order Assistant (local)")
    parser.add_argument("prompt", nargs="?", help="One-shot request. Omit for interactive mode.")
    parser.add_argument("--trace", action="store_true", help="Always print the tool trace.")
    args = parser.parse_args()

    settings = load_settings()
    logging.basicConfig(level=settings.log_level)
    print(f"[provider={settings.model_provider}]")
    agent = build_agent(settings)

    if args.prompt:
        run(agent, args.prompt, args.trace)
        return
    print("Interactive mode. Ctrl+C or 'exit' to quit.")
    while True:
        try:
            prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if prompt.lower() in ("exit", "quit"):
            break
        if prompt:
            run(agent, prompt, args.trace)


if __name__ == "__main__":
    main()
