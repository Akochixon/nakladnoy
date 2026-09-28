from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    bot_token: str
    database_url: str
    gemini_api_key: str
    admin_ids: list[int]
    storage_chat_id: int | None = None  # ixtiyoriy: zaxira kanal/chat ID

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=os.environ["BOT_TOKEN"],
            database_url=os.environ["DATABASE_URL"],
            gemini_api_key=os.environ["GEMINI_API_KEY"],
            admin_ids=_parse_admin_ids(os.environ.get("ADMIN_IDS", "")),
            storage_chat_id=int(os.environ["STORAGE_CHAT_ID"]) if os.environ.get("STORAGE_CHAT_ID", "").strip() else None,
        )


settings = Settings.from_env()
