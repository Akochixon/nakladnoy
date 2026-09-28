from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import settings
from bot.database.db import init_db
from bot.handlers import admin, invoice, start, user

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Tartib muhim: aniqroq handlerlar (start/admin/user) umumiy rasm handleridan oldin turadi.
    dp.include_router(start.router)
    dp.include_router(admin.entry_router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(invoice.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Bosh menyu"),
        BotCommand(command="stats", description="Mening statistikam"),
        BotCommand(command="cancel", description="Amalni bekor qilish"),
        BotCommand(command="help", description="Yordam"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
