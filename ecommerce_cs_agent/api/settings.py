from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    agent_api_token: str


def load_settings() -> Settings:
    return Settings(
        app_env=os.environ.get("APP_ENV", "development"),
        agent_api_token=os.environ.get("AGENT_API_TOKEN", ""),
    )
