from __future__ import annotations

import datetime

from aiogram.types import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.db import async_session
from bot.database.models import TelegramUser, UserStatus

ROLE_ADMIN = "admin"
ROLE_USER = "user"


def is_env_admin(telegram_id: int) -> bool:
    return telegram_id in settings.admin_ids


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def get_user_by_tid(session: AsyncSession, telegram_id: int) -> TelegramUser | None:
    return (
        await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == telegram_id))
    ).scalar_one_or_none()


async def _make_admin_row(session: AsyncSession, tg: User) -> TelegramUser:
    user = await get_user_by_tid(session, tg.id)
    if user is None:
        user = TelegramUser(
            telegram_id=tg.id, full_name=tg.full_name, id_number="-", username=tg.username,
            status=UserStatus.APPROVED, role=ROLE_ADMIN, approved_at=_now(),
        )
        session.add(user)
    elif user.status != UserStatus.APPROVED or user.role != ROLE_ADMIN:
        user.status, user.role = UserStatus.APPROVED, ROLE_ADMIN
    else:
        return user
    await session.commit()
    return user


async def ensure_env_admin(session: AsyncSession, tg: User) -> TelegramUser | None:
    """ADMIN_IDS dagi odam ro'yxatdan o'tmasdan avtomatik tasdiqlangan admin bo'ladi."""
    if not is_env_admin(tg.id):
        return None
    return await _make_admin_row(session, tg)


async def get_active_user(tg: User) -> TelegramUser | None:
    async with async_session() as session:
        if is_env_admin(tg.id):
            user = await ensure_env_admin(session, tg)
        else:
            user = await get_user_by_tid(session, tg.id)
    if user and user.status == UserStatus.APPROVED:
        return user
    return None


async def is_admin(telegram_id: int) -> bool:
    if is_env_admin(telegram_id):
        return True
    async with async_session() as session:
        user = await get_user_by_tid(session, telegram_id)
    return bool(user and user.role == ROLE_ADMIN and user.status == UserStatus.APPROVED)


async def admin_telegram_ids() -> list[int]:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(TelegramUser.telegram_id).where(
                    TelegramUser.role == ROLE_ADMIN, TelegramUser.status == UserStatus.APPROVED
                )
            )
        ).scalars().all()
    return sorted(set(rows) | set(settings.admin_ids))


async def claim_first_admin(tg: User) -> bool:
    """Faqat ADMIN_IDS bo'sh va bazada admin yo'q bo'lsa: birinchi /admin yuborgan odam admin bo'ladi."""
    if settings.admin_ids:
        return False
    async with async_session() as session:
        exists = (
            await session.execute(select(TelegramUser.id).where(TelegramUser.role == ROLE_ADMIN).limit(1))
        ).first()
        if exists:
            return False
        await _make_admin_row(session, tg)
    return True
