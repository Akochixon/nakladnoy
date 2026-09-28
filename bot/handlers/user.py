from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from bot.database.db import async_session
from bot.database.models import Invoice
from bot.keyboards import BTN_MY_STATS
from bot.services import stats
from bot.services.stats import PERIOD_LABELS, period_start
from bot.services.users import get_active_user
from bot.utils import esc, fmt_num

router = Router(name="user")


@router.message(Command("stats"))
@router.message(F.text == BTN_MY_STATS)
async def my_stats(message: Message) -> None:
    user = await get_active_user(message.from_user)
    if user is None:
        await message.answer("Statistika uchun avval ro'yxatdan o'tib, admin tasdig'ini kuting. /start")
        return

    async with async_session() as session:
        lines = [f"📊 <b>Mening statistikam</b> — {esc(user.full_name)}", ""]
        for p in ("today", "7", "30", "all"):
            s = await stats.summary(session, period_start(p), user.id)
            lines.append(f"<b>{PERIOD_LABELS[p]}:</b> {s['count']} ta nakladnoy, {fmt_num(s['sum'])} so'm")
        top = await stats.top_products(session, None, user.id, limit=3)
        recent = (
            await session.execute(
                select(Invoice).options(joinedload(Invoice.customer))
                .where(Invoice.submitted_by == user.id)
                .order_by(Invoice.created_at.desc()).limit(5)
            )
        ).scalars().all()

    if top:
        lines += ["", "🏆 <b>Eng ko'p tovarlarim</b>"]
        lines += [f"{i}. {esc(n)} — {fmt_num(q)} quti" for i, (n, q, _) in enumerate(top, 1)]
    if recent:
        lines += ["", "🕓 <b>Oxirgi nakladnoylarim</b>"]
        lines += [
            f"№{esc(i.invoice_number)} • {i.date:%d.%m.%Y} • {esc(i.customer.name)} • {fmt_num(i.total_sum)}"
            for i in recent
        ]
    if len(lines) == 2 + 4 and not recent:
        lines += ["", "Hali nakladnoy yuborilmagan."]
    await message.answer("\n".join(lines))
