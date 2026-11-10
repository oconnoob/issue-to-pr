"""Environment configuration shared by the HTTP receiver and delivery worker."""

from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    repository: str
    github_secret: str
    github_token: str
    trigger_url: str
    trigger_secret: str
    label: str = "agent"
    database: str = "./data/relay.sqlite3"

    @staticmethod
    def database_from_env():
        url = os.environ.get("DATABASE_URL", "")
        if url and not url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        if os.environ.get("APP_PLATFORM") and not url:
            raise ValueError("App Platform requires DATABASE_URL; SQLite is local only")
        return url or os.environ.get("DATABASE_PATH", "./data/relay.sqlite3")

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.environ.get(name, "")
            if not value:
                raise ValueError(f"Set {name}")
            return value

        settings = cls(
            repository=required("GITHUB_REPOSITORY"),
            github_secret=required("GITHUB_WEBHOOK_SECRET"),
            github_token=required("RELAY_GITHUB_TOKEN"),
            trigger_url=required("HARNESS_TRIGGER_URL"),
            trigger_secret=required("HARNESS_TRIGGER_SECRET"),
            label=os.environ.get("AGENT_LABEL", "agent"),
            database=cls.database_from_env(),
        )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", settings.repository):
            raise ValueError("GITHUB_REPOSITORY must be owner/repo")
        url = urlsplit(settings.trigger_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("HARNESS_TRIGGER_URL must be an HTTPS URL without credentials or fragment")
        if not settings.label.strip():
            raise ValueError("AGENT_LABEL cannot be empty")
        if settings.github_secret == settings.trigger_secret:
            raise ValueError("Use separate GitHub and Harness webhook secrets")
        return settings
