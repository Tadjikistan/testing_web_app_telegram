import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Settings:
    bot_token: str
    admin_id: int
    db_path: str


def load_settings() -> Settings:
    load_dotenv()
    bot_token = os.getenv("BOT_TOKEN")
    admin_id = os.getenv("ADMIN_ID")
    db_path = os.getenv("DB_PATH", "bot.db")

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    if not admin_id:
        raise RuntimeError("ADMIN_ID is required")

    return Settings(bot_token=bot_token, admin_id=int(admin_id), db_path=db_path)

