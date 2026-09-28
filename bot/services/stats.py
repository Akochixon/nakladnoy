from __future__ import annotations

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Customer, Invoice, InvoiceItem, Product, TelegramUser
from bot.utils import today

PERIOD_LABELS = {"today": "Bugun", "7": "7 kun", "30": "30 kun", "all": "Hammasi"}


def period_start(period: str) -> datetime.date | None:
    t = today()
    if period == "today":
        return t
    if period == "7":
        return t - datetime.timedelta(days=6)
    if period == "30":
        return t - datetime.timedelta(days=29)
    return None


def filters(since: datetime.date | None = None, user_pk: int | None = None, flt: str = "0") -> list:
    """flt: '0' (filtrsiz) yoki tur+id: u=foydalanuvchi, c=xaridor, s=postavshik, a=agent, e=ekspeditor, p=tovar."""
    conds = []
    if since is not None:
        conds.append(Invoice.date >= since)
    if user_pk:
        conds.append(Invoice.submitted_by == user_pk)
    if flt and flt != "0":
        kind, val = flt[0], int(flt[1:])
        col = {"u": Invoice.submitted_by, "c": Invoice.customer_id, "s": Invoice.supplier_id,
               "a": Invoice.sales_agent_id, "e": Invoice.expediter_id}.get(kind)
        if col is not None:
            conds.append(col == val)
        elif kind == "p":
            conds.append(Invoice.id.in_(select(InvoiceItem.invoice_id).where(InvoiceItem.product_id == val)))
    return conds


async def summary(session: AsyncSession, since=None, user_pk=None, flt: str = "0") -> dict:
    q = select(
        func.count(Invoice.id),
        func.coalesce(func.sum(Invoice.total_sum), 0),
        func.coalesce(func.sum(Invoice.total_qty), 0),
    ).where(*filters(since, user_pk, flt))
    count, total, qty = (await session.execute(q)).one()
    return {"count": count, "sum": total, "qty": qty}


async def top_customers(session: AsyncSession, since=None, user_pk=None, limit: int = 5, flt: str = "0"):
    total = func.sum(Invoice.total_sum)
    q = (
        select(Customer.name, func.count(Invoice.id), total)
        .select_from(Invoice)
        .join(Customer, Customer.id == Invoice.customer_id)
        .where(*filters(since, user_pk, flt))
        .group_by(Customer.id, Customer.name)
        .order_by(total.desc())
        .limit(limit)
    )
    return (await session.execute(q)).all()


async def top_products(session: AsyncSession, since=None, user_pk=None, limit: int = 5, flt: str = "0"):
    total = func.sum(InvoiceItem.line_total)
    q = (
        select(Product.name, func.sum(InvoiceItem.quantity), total)
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .where(*filters(since, user_pk, flt))
        .group_by(Product.id, Product.name)
        .order_by(total.desc())
        .limit(limit)
    )
    return (await session.execute(q)).all()


async def per_user(session: AsyncSession, since=None, limit: int = 5):
    total = func.sum(Invoice.total_sum)
    q = (
        select(TelegramUser.full_name, func.count(Invoice.id), total)
        .select_from(Invoice)
        .join(TelegramUser, TelegramUser.id == Invoice.submitted_by)
        .where(*filters(since))
        .group_by(TelegramUser.id, TelegramUser.full_name)
        .order_by(total.desc())
        .limit(limit)
    )
    return (await session.execute(q)).all()
