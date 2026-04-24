from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str = Field(alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")

    e2b_api_key: str = Field(alias="E2B_API_KEY")
    e2b_timeout_seconds: int = Field(default=3600, alias="E2B_TIMEOUT_SECONDS")
    e2b_step_timeout_seconds: int = Field(default=120, alias="E2B_STEP_TIMEOUT_SECONDS")

    agent_db_path: str = Field(default="data/agent_state.db", alias="AGENT_DB_PATH")
    agent_max_full_episodes: int = Field(default=25, alias="AGENT_MAX_FULL_EPISODES")
    agent_max_iterations: int = Field(default=100000, alias="AGENT_MAX_ITERATIONS")
    agent_cycle_sleep_seconds: int = Field(default=5, alias="AGENT_CYCLE_SLEEP_SECONDS")

    frontend_origins: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGINS")
    frontend_origin_regex: str = Field(default=r"^https?://localhost(:\d+)?$", alias="FRONTEND_ORIGIN_REGEX")

    @property
    def frontend_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
