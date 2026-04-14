from __future__ import annotations

from autonomous_agent.config import clear_settings_cache, get_settings


def test_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("E2B_API_KEY", "e2b_test")
    monkeypatch.setenv("E2B_TEMPLATE", "agent-template")
    monkeypatch.setenv("E2B_REQUIRE_SANDBOX", "true")
    monkeypatch.setenv("AGENT_DB_PATH", "data/custom.db")
    monkeypatch.setenv("AGENT_MAX_FULL_EPISODES", "30")
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "2000")
    monkeypatch.setenv("AGENT_CYCLE_SLEEP_SECONDS", "2.5")

    clear_settings_cache()
    settings = get_settings()

    assert settings.groq_api_key == "gsk_test"
    assert settings.e2b_api_key == "e2b_test"
    assert settings.e2b_template == "agent-template"
    assert settings.e2b_require_sandbox is True
    assert settings.agent_db_path == "data/custom.db"
    assert settings.max_full_episodes == 30
    assert settings.max_iterations == 2000
    assert settings.cycle_sleep_seconds == 2.5

    clear_settings_cache()
