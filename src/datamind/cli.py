"""DataMind command line interface."""

import argparse
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint for DataMind."""
    parser = argparse.ArgumentParser(
        prog="datamind",
        description="DataMind: Talk to Your Data with verifiable SQL and citations",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # init
    init_parser = subparsers.add_parser(
        "init",
        help="Introspect database schema and draft semantic model YAML",
    )
    init_parser.add_argument(
        "--accept",
        action="store_true",
        help="Accept drafted semantic model without interactive review",
    )

    # serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the DataMind API and UI server",
    )
    serve_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind server (default: 8000)",
    )

    # ask
    ask_parser = subparsers.add_parser(
        "ask",
        help="Ask a natural language question against configured dataset",
    )
    ask_parser.add_argument(
        "question",
        nargs="?",
        default="",
        help="Natural language question to ask",
    )
    ask_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )

    # eval
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run evaluation benchmark suites (business, trust)",
    )
    eval_parser.add_argument(
        "--suite",
        choices=["all", "business", "trust"],
        default="all",
        help="Evaluation suite to run",
    )

    # index
    index_parser = subparsers.add_parser(
        "index",
        help="Build full-text search index for document tables",
    )
    index_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand in {"init", "serve", "ask", "eval", "index"}:
        print(f"Command '{args.subcommand}' is not implemented yet.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
