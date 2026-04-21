import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def parse_csv_env(value: str) -> set[str]:
    return {
        item.strip()
        for item in value.split(",")
        if item.strip()
    }


@dataclass(slots=True)
class Settings:
    database_path: Path
    command_prefix: str
    bot_token: str
    announce_channel_id: int
    poll_interval_minutes: int
    allowed_users: set[str]


def load_settings() -> Settings:
    load_env_file()
    return Settings(
        database_path=Path(os.getenv("RSSCORD_DB_PATH", "rsscord.db")),
        command_prefix=os.getenv("RSSCORD_PREFIX", "%"),
        bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        announce_channel_id=int(os.getenv("RSSCORD_CHANNEL_ID", "0")),
        poll_interval_minutes=int(os.getenv("RSSCORD_POLL_INTERVAL_MINUTES", "10")),
        allowed_users=parse_csv_env(os.getenv("ALLOWED_USERS", "")),
    )
