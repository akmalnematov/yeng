import os
from pydantic import BaseModel, Field
# fast_ig_bot_light/config.py boshiga qo‘shing:
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseModel):
    BOT_TOKEN: str = Field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    TELEGRAM_LIMIT: int = int(os.getenv("TELEGRAM_LIMIT", str(2_090_000_000)))  # ~2GB
    DB_PATH: str = os.getenv("DB_PATH", "bot.db")

settings = Settings()
