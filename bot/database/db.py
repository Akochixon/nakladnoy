from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings


class Base(DeclarativeBase):
    pass


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_normalize_url(settings.database_url), pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


_MIGRATIONS = [
    "ALTER TABLE telegram_users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'user'",
    "ALTER TABLE telegram_users ADD COLUMN IF NOT EXISTS username VARCHAR(64)",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(255)",
    "ALTER TABLE invoices ALTER COLUMN photo_path DROP NOT NULL",
]


async def init_db() -> None:
    from bot.database import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Mavjud jadvallarga yangi ustunlarni qo'shadi (idempotent).
        for stmt in _MIGRATIONS:
            await conn.execute(text(stmt))
