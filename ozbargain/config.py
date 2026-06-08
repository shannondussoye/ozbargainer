import os
from typing import Optional
from urllib.parse import urlparse
from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure we locate the .env file in the root project directory relative to config.py
config_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(config_dir)
env_path = os.path.join(project_root, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_path, env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: Optional[str] = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, validation_alias="TELEGRAM_CHAT_ID")
    min_heat_score: int = Field(default=60, validation_alias="MIN_HEAT_SCORE")
    trending_check_interval: int = Field(default=30, validation_alias="TRENDING_CHECK_INTERVAL")
    poll_interval: int = Field(default=5, validation_alias="POLL_INTERVAL")
    scrape_cooldown_seconds: int = Field(default=120, validation_alias="SCRAPE_COOLDOWN_SECONDS")
    healthcheck_ping_url: Optional[str] = Field(default=None, validation_alias="HEALTHCHECK_PING_URL")
    chrome_cdp_url: Optional[str] = Field(default=None, validation_alias="CHROME_CDP_URL")
    ozbargain_db_path: str = Field(default="ozbargain.db", validation_alias="OZBARGAIN_DB_PATH")
    ozbargain_base_url: str = Field(default="https://www.ozbargain.com.au")
    logtail_token: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("LOGTAIL_TOKEN", "LOGTAIL_SOURCE_TOKEN")
    )

    @field_validator("chrome_cdp_url")
    @classmethod
    def validate_cdp_url(cls, v: Optional[str]) -> Optional[str]:
        if v:
            parsed_url = urlparse(v)
            if parsed_url.hostname not in ["127.0.0.1", "localhost"]:
                raise ValueError(
                    f"CRITICAL: CDP URL must bind to localhost/127.0.0.1 to prevent RCE. Got: {parsed_url.hostname}"
                )
        return v


# Singleton settings instance
settings = Settings()
