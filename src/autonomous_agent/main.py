import argparse
import time

import uvicorn

from .app import agent


def run_api() -> None:
    uvicorn.run(
        "autonomous_agent.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        access_log=False,
        log_level="warning",
    )


def run_cli(goal: str) -> None:
    session_id = agent.start(goal=goal)
    last_seen = 0

    while True:
        status = agent.status(session_id)
        if status.session is None:
            break

        outputs = status.outputs
        if len(outputs) > last_seen:
            for line in outputs[last_seen:]:
                if line.strip():
                    print(line)
            last_seen = len(outputs)

        if status.session.status not in {"running"}:
            break

        time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-running autonomous agent")
    parser.add_argument("--mode", choices=["api", "cli"], default="api")
    parser.add_argument("--goal", help="Goal for CLI mode")
    args = parser.parse_args()

    if args.mode == "api":
        run_api()
        return

    if not args.goal:
        raise ValueError("--goal is required in cli mode")

    run_cli(args.goal)


if __name__ == "__main__":
    main()
