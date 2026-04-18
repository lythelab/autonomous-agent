from __future__ import annotations

import argparse
import logging
import sys

from .runtime import start_autonomous_goal


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the autonomous agent with .env-backed settings.")
    parser.add_argument("--goal", required=True, help="High-level goal for the autonomous agent.")
    parser.add_argument(
        "--runtime-seconds",
        type=float,
        default=None,
        help="Optional maximum runtime in seconds.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite DB path. Defaults to AGENT_DB_PATH or data/agent_state.db.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    state = start_autonomous_goal(
        goal=args.goal,
        db_path=args.db_path,
        runtime_seconds=args.runtime_seconds,
    )
    goal = state.get("goal") if isinstance(state, dict) else None
    status = state.get("status") if isinstance(state, dict) else None
    completed = len(state.get("completed_steps", [])) if isinstance(state, dict) else 0
    remaining = len(state.get("remaining_steps", [])) if isinstance(state, dict) else 0
    output = (
        f"Goal: {goal or 'n/a'}\n"
        f"Status: {status or 'unknown'}\n"
        f"Completed steps: {completed}\n"
        f"Remaining steps: {remaining}"
    )
    print(f"[report]\\n{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
