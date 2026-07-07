import argparse
from dataclasses import asdict
import json
import sys
import textwrap
from typing import Any, List, Optional

from engines.Python.Gumroad.lms_sdk import configure_localhost, get_default_model_name, create_client, local_llm
from engines.Python.Gumroad.model_tools import get_all_tools
from working_memory import (
    STORE_CONTEXT,
    add_memory,
    find_memory,
    get_memory,
    list_memory_keys,
    refresh_from_gumroad,
    summarize_memory,
)


def build_system_prompt() -> str:
    memory_summary = summarize_memory()
    return textwrap.dedent(
        f"""
        You are the GumOps assistant for the user's local Gumroad operations and agent CLI.
        Before each response, you must consult the working memory summary below.

        WORKING MEMORY SUMMARY:
        {memory_summary}

        STORE CONTEXT:
        {STORE_CONTEXT}

        Guidance:
        - Use the available tools when you need to inspect files, query Gumroad, refresh memory, or perform structured operations.
        - Keep answers grounded in the store context and memory.
        - If a question depends on data not available in memory, prefer using a relevant tool rather than guessing.
        - When the user asks for an action, respond with the tool-enabled agent flow.
        """
    )


def run_agent_query(query: str, model_name: Optional[str] = None, use_tools: bool = True) -> str:
    configure_localhost()
    prompt = build_system_prompt() + "\n\nUSER QUERY:\n" + query.strip()
    if use_tools:
        tools = get_all_tools()
        response = local_llm(model_name or get_default_model_name(), client=create_client()).act(prompt, tools)
    else:
        model = local_llm(model_name or get_default_model_name(), client=create_client())
        response = model.respond(prompt)
    return str(response)


def pretty_print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def list_tools() -> None:
    tools = get_all_tools()
    for tool in tools:
        description = tool.__doc__.strip().splitlines()[0] if getattr(tool, "__doc__", None) else ""
        print(f"{tool.__name__}: {description}")


def query_memory(query: str) -> List[Any]:
    normalized = query.lower()

    def predicate(item: Any) -> bool:
        value_text = json.dumps(item.value, ensure_ascii=False) if not isinstance(item.value, str) else item.value
        metadata_text = json.dumps(item.metadata, ensure_ascii=False)
        return (
            normalized in item.key.lower()
            or normalized in value_text.lower()
            or normalized in metadata_text.lower()
        )

    return find_memory(predicate)


def do_interactive(model_name: Optional[str] = None) -> None:
    print("GumOps Agent Interactive CLI")
    print("Press Ctrl-D or type 'exit' to quit.")
    print("Current working memory summary:")
    print(summarize_memory())
    print()

    while True:
        try:
            prompt = input("gumops> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit", "q"}:
            print("Exiting.")
            return
        if prompt.startswith(":"):
            print("Commands inside interactive mode are not supported. Use the CLI subcommands instead.")
            continue

        response = run_agent_query(prompt, model_name=model_name)
        print(response)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GumOps agent CLI for local Gumroad operations, tools, and working memory-aware LLM interaction.",
    )
    parser.add_argument("--model", help="Optional local LM Studio model name.")
    subparsers = parser.add_subparsers(dest="command")

    parser_query = subparsers.add_parser("query", help="Ask the GumOps agent a question.")
    parser_query.add_argument("text", nargs=argparse.REMAINDER, help="Question text.")
    parser_query.add_argument("--no-tools", action="store_true", help="Send prompt without tool-enabled agent actions.")

    subparsers.add_parser("interactive", help="Start an interactive GumOps agent session.")
    subparsers.add_parser("refresh-memory", help="Refresh working memory with the latest Gumroad data.")
    subparsers.add_parser("refresh-gumroad", help="Alias for refresh-memory.")

    memory_parser = subparsers.add_parser("memory", help="Inspect or modify working memory.")
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    memory_sub.add_parser("list", help="List memory keys.")

    get_parser = memory_sub.add_parser("get", help="Get a memory item by key.")
    get_parser.add_argument("key", help="Memory key to retrieve.")

    add_parser = memory_sub.add_parser("add", help="Add or update a memory entry.")
    add_parser.add_argument("key", help="Memory key to add.")
    add_parser.add_argument("value", nargs=argparse.REMAINDER, help="Value for the memory entry.")

    find_parser = memory_sub.add_parser("find", help="Search memory entries by query.")
    find_parser.add_argument("query", nargs=argparse.REMAINDER, help="Search query text.")

    tools_parser = subparsers.add_parser("tools", help="Inspect available tools.")
    tools_parser.add_argument("action", nargs="?", default="list", choices=["list"], help="Tool action.")

    args = parser.parse_args()

    if args.command in {None, "interactive"}:
        do_interactive(model_name=args.model)
        return

    if args.command == "query":
        text = " ".join(args.text).strip()
        if not text:
            parser.error("query requires text")
        response = run_agent_query(text, model_name=args.model, use_tools=not args.no_tools)
        print(response)
        return

    if args.command in {"refresh-memory", "refresh-gumroad"}:
        result = refresh_from_gumroad()
        pretty_print_json(result)
        return

    if args.command == "memory":
        if args.memory_command == "list":
            for key in list_memory_keys():
                print(key)
            return
        if args.memory_command == "get":
            item = get_memory(args.key)
            if item is None:
                print(f"Memory key not found: {args.key}")
                return
            pretty_print_json({"key": item.key, "value": item.value, "timestamp": item.timestamp, "metadata": item.metadata})
            return
        if args.memory_command == "add":
            value_text = " ".join(args.value).strip()
            if not value_text:
                parser.error("memory add requires a value")
            try:
                value = json.loads(value_text)
            except Exception:
                value = value_text
            item = add_memory(args.key, value)
            pretty_print_json(asdict(item) if hasattr(item, "__dict__") else {"key": item.key, "value": item.value, "timestamp": item.timestamp, "metadata": item.metadata})
            return
        if args.memory_command == "find":
            query = " ".join(args.query).strip()
            if not query:
                parser.error("memory find requires a query")
            results = query_memory(query)
            for item in results:
                pretty_print_json({"key": item.key, "value": item.value, "timestamp": item.timestamp, "metadata": item.metadata})
            return
        parser.error("memory requires a subcommand")

    if args.command == "tools":
        list_tools()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
