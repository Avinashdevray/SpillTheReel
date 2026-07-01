"""
SpillTheReel – Application Configuration

Loads settings from environment variables via Pydantic Settings.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration sourced from .env / environment."""

    # General
    app_env: str = "development"
    debug: bool = True

    # Cognee
    cognee_api_key: str = ""
    cognee_llm_provider: str = "openai"
    cognee_llm_model: str = "gpt-4o-mini"

    # OpenAI
    openai_api_key: str = ""

    # Paths
    download_dir: str = "./downloads"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
