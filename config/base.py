"""Shared configuration base classes."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(".env")
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


class SettingsBase(BaseSettings):
    """Base class that normalizes string values and ignores extra fields."""

    model_config = SettingsConfigDict(extra="ignore", validate_by_name=True)
