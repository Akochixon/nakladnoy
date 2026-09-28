from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.database.models import (
    Customer,
    DuplicateDecision,
    Expediter,
    Invoice,
    InvoiceDuplicate,
    InvoiceItem,
    Product,
    SalesAgent,
    Supplier,
)


async def get_or_create_supplier(session, name, inn, address, phone):
    supplier = None
    if inn:
        supplier = (
            await session.execute(select(Supplier).where(Supplier.inn == inn))
        ).scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=name, inn=inn or "", address=address, phone=phone)
        session.add(supplier)
        await session.flush()
    return supplier


async def get_or_create_customer(session, name, inn, address, client_code):
    customer = None
    if client_code:
        customer = (
            await session.execute(select(Customer).where(Customer.client_code == client_code))
        ).scalar_one_or_none()
    if customer is None:
        customer = Customer(name=name, inn=inn, address=address, client_code=client_code)
        session.add(customer)
        await session.flush()
    return customer


async def get_or_create_sales_agent(session, full_name):
    if not full_name:
        return None
    agent = (
        await session.execute(select(SalesAgent).where(SalesAgent.full_name == full_name))
    ).scalar_one_or_none()
    if agent is None:
        agent = SalesAgent(full_name=full_name)
        session.add(agent)
        await session.flush()
    return agent


async def get_or_create_expediter(session, full_name):
    if not full_name:
        return None
    expediter = (
        await session.execute(select(Expediter).where(Expediter.full_name == full_name))
    ).scalar_one_or_none()
    if expediter is None:
        expediter = Expediter(full_name=full_name)
        session.add(expediter)
        await session.flush()
    return expediter


async def get_or_create_product(session, code, name, unit):
    product = (
        await session.execute(select(Product).where(Product.code == code))
    ).scalar_one_or_none()
    if product is None:
        product = Product(code=code, name=name, unit=unit)
        session.add(product)
        await session.flush()
    return product


async def find_existing_invoice(session: AsyncSession, supplier_id: int, invoice_number: str):
    result = await session.execute(
        select(Invoice)
        .options(joinedload(Invoice.customer), joinedload(Invoice.submitter))
        .where(Invoice.supplier_id == supplier_id, Invoice.invoice_number == invoice_number)
        .order_by(Invoice.created_at.asc())
    )
    return result.scalars().first()


async def create_invoice(
    session: AsyncSession,
    *,
    invoice_number: str,
    date: datetime.date,
    supplier,
    customer,
    sales_agent,
    expediter,
    submitted_by_id: int,
    items: list[dict],
    photo_file_id: str | None,
) -> Invoice:
    total_qty = sum(item["quantity"] for item in items)
    total_sum = sum(item["line_total"] for item in items)

    invoice = Invoice(
        invoice_number=invoice_number,
        date=date,
        supplier_id=supplier.id,
        customer_id=customer.id,
        sales_agent_id=sales_agent.id if sales_agent else None,
        expediter_id=expediter.id if expediter else None,
        submitted_by=submitted_by_id,
        total_qty=total_qty,
        total_sum=total_sum,
        photo_file_id=photo_file_id,
    )
    session.add(invoice)
    await session.flush()

    for item in items:
        product = await get_or_create_product(session, item["code"], item["name"], item.get("unit"))
        session.add(
            InvoiceItem(
                invoice_id=invoice.id,
                product_id=product.id,
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                line_total=item["line_total"],
            )
        )

    await session.commit()
    return invoice


async def log_duplicate_decision(session: AsyncSession, invoice_id: int, submitted_by_id: int, decision):
    session.add(
        InvoiceDuplicate(invoice_id=invoice_id, submitted_by=submitted_by_id, decision=decision)
    )
    await session.commit()
