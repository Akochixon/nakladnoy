from __future__ import annotations

import datetime
import enum

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.db import Base


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DuplicateDecision(str, enum.Enum):
    ACCEPTED_AS_DUPLICATE = "accepted_as_duplicate"
    TREATED_AS_NEW = "treated_as_new"


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    inn: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(64))

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="supplier")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    inn: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(500))
    client_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class SalesAgent(Base):
    __tablename__ = "sales_agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="sales_agent")


class Expediter(Base):
    __tablename__ = "expediters"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="expediter")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(32))

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="product")


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    id_number: Mapped[str] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    status: Mapped[UserStatus] = mapped_column(default=UserStatus.PENDING)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="submitter")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_supplier_number", "supplier_id", "invoice_number"),
        Index("ix_invoices_date", "date"),
        Index("ix_invoices_customer", "customer_id"),
        Index("ix_invoices_sales_agent", "sales_agent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)

    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    sales_agent_id: Mapped[int | None] = mapped_column(ForeignKey("sales_agents.id"))
    expediter_id: Mapped[int | None] = mapped_column(ForeignKey("expediters.id"))
    submitted_by: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"))

    total_qty: Mapped[float] = mapped_column(Numeric(12, 2))
    total_sum: Mapped[float] = mapped_column(Numeric(14, 2))

    # Rasm Telegram serverlarida saqlanadi, file_id orqali qayta olinadi.
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    photo_path: Mapped[str | None] = mapped_column(String(500))  # eski yozuvlar uchun

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship(back_populates="invoices")
    customer: Mapped[Customer] = relationship(back_populates="invoices")
    sales_agent: Mapped[SalesAgent | None] = relationship(back_populates="invoices")
    expediter: Mapped[Expediter | None] = relationship(back_populates="invoices")
    submitter: Mapped[TelegramUser] = relationship(back_populates="invoices")

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    duplicate_reports: Mapped[list["InvoiceDuplicate"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))

    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2))
    line_total: Mapped[float] = mapped_column(Numeric(14, 2))

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="items")


class InvoiceDuplicate(Base):
    __tablename__ = "invoice_duplicates"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    submitted_by: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"))
    decision: Mapped[DuplicateDecision] = mapped_column()
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    invoice: Mapped[Invoice] = relationship(back_populates="duplicate_reports")
