# Testing Guide

## Test Suites

- `tests/test_memory_manager.py`
- `tests/test_agent_loop.py`
- `tests/test_tool_executor.py`
- `tests/test_config.py`

## Coverage Summary

### Memory Manager

- Write/read persistence
- Persistence across restarts
- Compression behavior when full episodes exceed limits
- Groq summarization path via fake client
- Recency-weighted search ordering
- Duplicate key overwrites
- Empty database behavior

### Agent Loop

- Resume from previously saved state
- Save state after each executed step
- Skip already completed steps
- Fresh-start initialization path
- Goal completion behavior
- Autonomous plan generation from high-level goals
- Plan adaptation after failed execution
- Tool keep-alive integration between cycles

### Tool Executor

- Successful code execution path
- Web search execution in sandbox
- Retry behavior on transient failure
- Graceful failure after max retries
- Error classification taxonomy
- Keep-alive ping behavior
- Prefix-based task routing (`search:`, `fetch:`, `code:`)
- Natural-language fallback task execution

### Configuration

- `.env`/environment variable loading and typed settings parsing

## Running Tests

```bash
pytest --tb=short -v
```

## Notes

- Tool executor tests use fake sandbox implementations, so they run without E2B credentials.
- Memory compression tests use a fake Groq client, so they run without live API access.
