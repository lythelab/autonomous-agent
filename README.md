# Autonomous Agent

Long-running autonomous agent prototype with persistent memory, resumable goal execution, and sandboxed tool execution.

## Features

- Persistent memory in SQLite via `MemoryManager`
- Automatic memory compression when full episode count exceeds configured limits
- Resumable orchestration loop via `AgentLoop`
- Autonomous planning via `TaskPlanner`
- Reflection-driven adaptation via `ReflectionEngine`
- Persistent goal lifecycle tracking via `StateTracker`
- Sandboxed code and web task execution via `ToolExecutor`
- Dedicated E2B sandbox session factory via `E2BHandler`
- Automatic local fallback executor when E2B sandbox is unavailable or unhealthy
- Long-running runtime wiring for E2B-backed operation via `build_default_agent` and `start_autonomous_goal`
- Retry and failure taxonomy for tool errors (`llm_error`, `tool_error`, `goal_ambiguity`)

## Deployment Architecture

- Frontend: static app in `frontend/`, deploy to Vercel
- Backend: FastAPI service in `src/autonomous_agent/api.py`
- Execution runtime: agent code and tool execution in E2B sandboxes managed by `E2BHandler`

## Project Layout

- `src/autonomous_agent/memory_manager.py`: Persistent memory and compression
- `src/autonomous_agent/agent_loop.py`: Stateful orchestration and resume logic
- `src/autonomous_agent/task_planner.py`: Goal decomposition and replanning
- `src/autonomous_agent/reflection_engine.py`: Outcome evaluation and strategy hints
- `src/autonomous_agent/state_tracker.py`: Persistent goal state helper
- `src/autonomous_agent/e2b_handler.py`: E2B sandbox creation and lifecycle helpers
- `src/autonomous_agent/tool_executor.py`: Sandboxed code/web execution with retries
- `src/autonomous_agent/runtime.py`: Default production wiring for long-running runs
- `tests/test_memory_manager.py`: Memory manager unit tests
- `tests/test_agent_loop.py`: Agent loop integration tests with memory
- `tests/test_tool_executor.py`: Tool executor unit tests

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

Create your environment file:

```bash
cp .env.example .env
```

## Environment Variables

- `GROQ_API_KEY`: Required only when using Groq-backed memory summarization
- `GROQ_MODEL`: Optional override for summarization model (defaults to `llama-3.3-70b-versatile`)
- `E2B_API_KEY`: Required only when creating a real E2B `Sandbox` in `ToolExecutor`
- `E2B_TEMPLATE`: Optional E2B sandbox template name/id used by `E2BHandler`
- `E2B_REQUIRE_SANDBOX`: Set to `true` to fail startup when E2B sandbox is unavailable
- `AGENT_DB_PATH`: Default SQLite state file path
- `AGENT_MAX_FULL_EPISODES`: Compression threshold for full episodes
- `AGENT_MAX_ITERATIONS`: Safety cap for long-running loops
- `AGENT_CYCLE_SLEEP_SECONDS`: Delay between cycles during long runs
- `BACKEND_API_URL`: Backend base URL exposed to the frontend via `/env`

The project automatically loads values from `.env` via `python-dotenv`.

If E2B is not configured or sandbox creation fails, the runtime now logs the exact reason and automatically switches `ToolExecutor` to a local fallback sandbox so the agent can continue running.

## Quick Example

```python
from autonomous_agent import AgentLoop, MemoryManager

memory = MemoryManager(db_path="data/agent_state.db", max_full_episodes=5)
agent = AgentLoop(memory=memory)

agent.set_goal(
	goal="Summarize AI news",
	steps=["fetch_headlines", "analyze", "write_summary"],
)

while True:
	cycle = agent.run_cycle()
	if cycle["status"] in {"completed", "failed"}:
		break
```

## Long-Running Autonomous Run (E2B)

```python
from autonomous_agent import start_autonomous_goal

final_state = start_autonomous_goal(
    goal="Monitor AI news and maintain rolling summaries every cycle",
    db_path="data/agent_state.db",
    runtime_seconds=1800,
)

print(final_state["status"], final_state["completed_steps"])
```

CLI entrypoint:

```bash
autonomous-agent --goal "Monitor AI news and summarize updates" --runtime-seconds 1800
```

`start_autonomous_goal` resumes from saved state if present and uses `ToolExecutor` with an E2B sandbox when dependencies and environment variables are configured.

## Run Tests

```bash
pytest --tb=short -v
```

See `TESTING.md` for coverage details and what each test validates.

## Deploy on AWS EC2

This repository is configured for AWS EC2-style deployment of the API service.

The frontend loads the backend URL from `/env`, so set `BACKEND_API_URL` in `.env` and serve the frontend from the same host or reverse proxy it through the API host.

- Systemd unit template: `deploy/autonomous-agent-api.service`
- Nginx reverse proxy template: `deploy/nginx-autonomous-agent.conf`
- Step-by-step deployment guide: `temp/instructions.md`