from __future__ import annotations

import asyncio
import datetime
import logging
import math
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from bot.database.db import async_session
from bot.database.models import (
    Customer, Expediter, Invoice, InvoiceDuplicate, InvoiceItem, Product, SalesAgent, Supplier, TelegramUser,
    UserStatus,
)
from bot.filters import IsAdmin
from bot.keyboards import BTN_ADMIN, main_menu
from bot.services import stats
from bot.services.export import build_full_xlsx, build_invoices_xlsx
from bot.services.pdf import build_invoice_pdf
from bot.services.stats import PERIOD_LABELS, period_start
from bot.services.users import (
    ROLE_ADMIN, ROLE_USER, claim_first_admin, get_user_by_tid, is_admin, is_env_admin,
)
from bot.utils import esc, fmt_num, local, today

logger = logging.getLogger(__name__)

entry_router = Router(name="admin_entry")  # /admin — hamma uchun ochiq (huquq ichkarida tekshiriladi)
router = Router(name="admin")              # qolgan hammasi faqat adminlar uchun
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

USERS_PAGE = 8
INV_PAGE = 6
STATUS_LABEL = {
    UserStatus.APPROVED: "✅ Tasdiqlangan",
    UserStatus.PENDING: "⏳ Kutilmoqda",
    UserStatus.REJECTED: "⛔ Rad etilgan",
}
STATUS_ICON = {UserStatus.APPROVED: "✅", UserStatus.PENDING: "⏳", UserStatus.REJECTED: "⛔"}


# ---------------------------------------------------------------- helpers
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pager(prefix: str, page: int, total: int, size: int) -> list[InlineKeyboardButton]:
    row = []
    if page > 0:
        row.append(btn("◀️", f"{prefix}{page - 1}"))
    if (page + 1) * size < total:
        row.append(btn("▶️", f"{prefix}{page + 1}"))
    return row


def period_row(current: str, make_data) -> list[InlineKeyboardButton]:
    return [btn(("• " if p == current else "") + label, make_data(p)) for p, label in PERIOD_LABELS.items()]


async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Xabarni tahrirlaydi; imkoni bo'lmasa (masalan rasm xabari) yangisini yuboradi."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


MENU_TEXT = "🛠 <b>Admin panel</b>\nKerakli bo'limni tanlang:"
MENU_KB = kb([
    [btn("📊 Statistika", "adm:stats:all"), btn("👥 Foydalanuvchilar", "adm:users:0")],
    [btn("🧾 Nakladnoylar", "adm:inv:all:0:0"), btn("🗄 Ma'lumotlar bazasi", "adm:db")],
    [btn("📥 Excel eksport", "adm:xls")],
])

# Ma'lumotlar bazasi obyektlari: kalit harf nakladnoylarni filtrlashda ham ishlatiladi (flt = harf + id).
ENT = {
    "c": {"model": Customer, "icon": "🏢", "title": "Xaridorlar", "name": lambda o: o.name, "order": Customer.name},
    "s": {"model": Supplier, "icon": "🏭", "title": "Postavshiklar", "name": lambda o: o.name, "order": Supplier.name},
    "a": {"model": SalesAgent, "icon": "🧑\u200d💼", "title": "Agentlar", "name": lambda o: o.full_name, "order": SalesAgent.full_name},
    "e": {"model": Expediter, "icon": "🚚", "title": "Ekspeditorlar", "name": lambda o: o.full_name, "order": Expediter.full_name},
    "p": {"model": Product, "icon": "🥤", "title": "Tovarlar", "name": lambda o: f"{o.code} • {o.name}", "order": Product.name},
}
DB_PAGE = 8


async def flt_label(session, flt: str) -> str | None:
    """Nakladnoylar ro'yxati sarlavhasi uchun filtr nomi."""
    if not flt or flt == "0":
        return None
    kind, oid = flt[0], int(flt[1:])
    if kind == "u":
        u = await session.get(TelegramUser, oid)
        return f"👤 {esc(u.full_name)}" if u else None
    e = ENT[kind]
    obj = await session.get(e["model"], oid)
    return f"{e['icon']} {esc(e['name'](obj))}" if obj else None


def flt_back(flt: str) -> tuple[str, str]:
    if not flt or flt == "0":
        return "◀️ Menyu", "adm:menu"
    if flt[0] == "u":
        return "◀️ Foydalanuvchi", f"adm:user:{flt[1:]}:0"
    return "◀️ Obyekt kartasi", f"adm:dbc:{flt[0]}:{flt[1:]}:0"


# ---------------------------------------------------------------- renderers
async def render_stats(period: str):
    since = period_start(period)
    async with async_session() as session:
        s = await stats.summary(session, since)
        custs = await stats.top_customers(session, since)
        prods = await stats.top_products(session, since)
        by_user = await stats.per_user(session, since)
        pending = (await session.execute(
            select(func.count(TelegramUser.id)).where(TelegramUser.status == UserStatus.PENDING)
        )).scalar_one()

    lines = [
        f"📊 <b>Statistika — {PERIOD_LABELS[period]}</b>", "",
        f"🧾 Nakladnoylar: <b>{s['count']}</b>",
        f"📦 Jami soni: <b>{fmt_num(s['qty'])}</b> quti",
        f"💰 Jami summa: <b>{fmt_num(s['sum'])}</b> so'm",
    ]
    if custs:
        lines += ["", "🏢 <b>Top xaridorlar</b>"]
        lines += [f"{i}. {esc(n)} — {c} ta, {fmt_num(t)}" for i, (n, c, t) in enumerate(custs, 1)]
    if prods:
        lines += ["", "🥤 <b>Top tovarlar</b>"]
        lines += [f"{i}. {esc(n)} — {fmt_num(q)} quti, {fmt_num(t)}" for i, (n, q, t) in enumerate(prods, 1)]
    if by_user:
        lines += ["", "👤 <b>Foydalanuvchilar bo'yicha</b>"]
        lines += [f"{i}. {esc(n)} — {c} ta, {fmt_num(t)}" for i, (n, c, t) in enumerate(by_user, 1)]
    if pending:
        lines += ["", f"⏳ Tasdiq kutayotgan foydalanuvchilar: <b>{pending}</b>"]
    markup = kb([period_row(period, lambda p: f"adm:stats:{p}"), [btn("◀️ Menyu", "adm:menu")]])
    return "\n".join(lines), markup


async def render_users(page: int):
    async with async_session() as session:
        total = (await session.execute(select(func.count(TelegramUser.id)))).scalar_one()
        users = (await session.execute(
            select(TelegramUser).order_by(TelegramUser.created_at.desc())
            .offset(page * USERS_PAGE).limit(USERS_PAGE)
        )).scalars().all()
    pages = max(1, math.ceil(total / USERS_PAGE))
    rows = [[btn(f"{'👑' if u.role == ROLE_ADMIN else STATUS_ICON[u.status]} {u.full_name}", f"adm:user:{u.id}:{page}")]
            for u in users]
    nav = pager("adm:users:", page, total, USERS_PAGE)
    if nav:
        rows.append(nav)
    rows.append([btn("◀️ Menyu", "adm:menu")])
    return f"👥 <b>Foydalanuvchilar</b> ({total})\nSahifa {page + 1}/{pages}", kb(rows)


async def render_user_card(pk: int, page: int):
    async with async_session() as session:
        u = await session.get(TelegramUser, pk)
        if u is None:
            return None
        s = await stats.summary(session, None, pk)
    env = is_env_admin(u.telegram_id)
    lines = [
        f"👤 <b>{esc(u.full_name)}</b>",
        f"JSHSHIR: {esc(u.id_number)}",
        f"Telegram ID: {u.telegram_id}" + (f" (@{esc(u.username)})" if u.username else ""),
        f"Holat: {STATUS_LABEL[u.status]}",
        f"Rol: {'👑 admin' if u.role == ROLE_ADMIN else 'foydalanuvchi'}" + (" (ADMIN_IDS)" if env else ""),
        f"Nakladnoylar: <b>{s['count']}</b> ta, {fmt_num(s['sum'])} so'm",
        f"Ro'yxatdan o'tgan: {local(u.created_at):%d.%m.%Y}",
    ]
    rows = []
    if u.status != UserStatus.APPROVED:
        rows.append([btn("✅ Tasdiqlash", f"adm:ust:{pk}:ok:{page}")])
    if u.status != UserStatus.REJECTED and not env:
        rows.append([btn("⛔ Rad etish / bloklash", f"adm:ust:{pk}:no:{page}")])
    if u.role == ROLE_ADMIN and not env:
        rows.append([btn("👑 Adminlikni olib tashlash", f"adm:role:{pk}:user:{page}")])
    elif u.role != ROLE_ADMIN and u.status == UserStatus.APPROVED:
        rows.append([btn("👑 Admin qilish", f"adm:role:{pk}:admin:{page}")])
    rows.append([btn("🧾 Nakladnoylari", f"adm:inv:all:u{pk}:0")])
    rows.append([btn("◀️ Ro'yxat", f"adm:users:{page}")])
    return "\n".join(lines), kb(rows)


async def render_invoices(period: str, flt: str, page: int):
    since = period_start(period)
    conds = stats.filters(since, None, flt)
    async with async_session() as session:
        total = (await session.execute(select(func.count(Invoice.id)).where(*conds))).scalar_one()
        invs = (await session.execute(
            select(Invoice).options(joinedload(Invoice.customer))
            .where(*conds).order_by(Invoice.date.desc(), Invoice.id.desc())
            .offset(page * INV_PAGE).limit(INV_PAGE)
        )).scalars().all()
        label = await flt_label(session, flt)
    pages = max(1, math.ceil(total / INV_PAGE))
    title = f"🧾 <b>Nakladnoylar — {PERIOD_LABELS[period]}</b>"
    if label:
        title += f"\n{label}"
    text = f"{title}\nJami: {total} ta • Sahifa {page + 1}/{pages}"
    if not invs:
        text += "\n\nNakladnoy topilmadi."
    rows = [period_row(period, lambda p: f"adm:inv:{p}:{flt}:0")]
    for i in invs:
        lbl = f"№{i.invoice_number} • {i.date:%d.%m} • {i.customer.name[:14]} • {fmt_num(i.total_sum)}"
        rows.append([btn(lbl, f"adm:invd:{i.id}:{period}:{flt}:{page}")])
    nav = pager(f"adm:inv:{period}:{flt}:", page, total, INV_PAGE)
    if nav:
        rows.append(nav)
    rows.append([btn(*flt_back(flt))])
    return text, kb(rows)


async def _load_invoice(inv_id: int):
    async with async_session() as session:
        return (await session.execute(
            select(Invoice).options(
                joinedload(Invoice.customer), joinedload(Invoice.supplier),
                joinedload(Invoice.sales_agent), joinedload(Invoice.expediter),
                joinedload(Invoice.submitter),
                selectinload(Invoice.items).joinedload(InvoiceItem.product),
            ).where(Invoice.id == inv_id)
        )).scalars().first()


def _invoice_head(inv: Invoice) -> list[str]:
    lines = [
        f"🧾 <b>Nakladnoy №{esc(inv.invoice_number)}</b>",
        f"📅 {inv.date:%d.%m.%Y}",
        f"🏭 {esc(inv.supplier.name)}",
        f"🏢 {esc(inv.customer.name)}",
    ]
    if inv.sales_agent:
        lines.append(f"👤 Agent: {esc(inv.sales_agent.full_name)}")
    if inv.expediter:
        lines.append(f"🚚 Ekspeditor: {esc(inv.expediter.full_name)}")
    lines.append(f"📨 Yubordi: {esc(inv.submitter.full_name)} ({local(inv.created_at):%d.%m.%Y %H:%M})")
    return lines


def _invoice_buttons(inv_id: int, ctx: str, has_photo: bool, current: str) -> InlineKeyboardMarkup:
    """current: 'table' yoki 'photo' — hozir ko'rsatilayotgan ko'rinish tugmasi o'rniga boshqasi chiqadi."""
    first = []
    if current == "table" and has_photo:
        first.append(btn("🖼 Rasm", f"adm:invp:{inv_id}:{ctx}"))
    if current == "photo":
        first.append(btn("📋 Jadval", f"adm:invd:{inv_id}:{ctx}"))
    first.append(btn("📄 PDF", f"adm:invf:{inv_id}:{ctx}"))
    period, flt, page = ctx.split(":")
    return kb([first, [btn("◀️ Ro'yxat", f"adm:inv:{period}:{flt}:{page}")]])


async def render_invoice_detail(inv_id: int, period: str, flt: str, page: int):
    inv = await _load_invoice(inv_id)
    if inv is None:
        return None
    head = _invoice_head(inv)
    foot = ["", f"📦 Jami: {fmt_num(inv.total_qty)} quti   💰 <b>{fmt_num(inv.total_sum)}</b> so'm"]
    items = [
        f"{i}. {esc(it.product.name)}\n    {fmt_num(it.quantity)} × {fmt_num(it.unit_price)} = <b>{fmt_num(it.line_total)}</b>"
        for i, it in enumerate(inv.items, 1)
    ]
    while items and len("\n".join(head + ["", "<b>Tovarlar:</b>"] + items + foot)) > 3900:
        items.pop()
    text = "\n".join(head + ["", "<b>Tovarlar:</b>"] + items + (["…"] if len(items) < len(inv.items) else []) + foot)
    return text, _invoice_buttons(inv_id, f"{period}:{flt}:{page}", bool(inv.photo_file_id), "table")


# ---------------------------------------------------------------- /admin entry
@entry_router.message(Command("admin"))
@entry_router.message(F.text == BTN_ADMIN)
async def open_admin(message: Message) -> None:
    tg = message.from_user
    if not await is_admin(tg.id):
        if await claim_first_admin(tg):
            await message.answer("👑 Siz birinchi admin bo'ldingiz.", reply_markup=main_menu(True))
        else:
            await message.answer("Sizda admin huquqi yo'q.")
            return
    await message.answer(MENU_TEXT, reply_markup=MENU_KB)


@router.callback_query(F.data == "adm:menu")
async def cb_menu(cb: CallbackQuery) -> None:
    await show(cb, MENU_TEXT, MENU_KB)


# ---------------------------------------------------------------- statistics
@router.callback_query(F.data.startswith("adm:stats:"))
async def cb_stats(cb: CallbackQuery) -> None:
    await show(cb, *await render_stats(cb.data.split(":")[2]))


# ---------------------------------------------------------------- users
@router.callback_query(F.data.startswith("adm:users:"))
async def cb_users(cb: CallbackQuery) -> None:
    await show(cb, *await render_users(int(cb.data.split(":")[2])))


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user_card(cb: CallbackQuery) -> None:
    _, _, pk, page = cb.data.split(":")
    card = await render_user_card(int(pk), int(page))
    if card is None:
        await cb.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await show(cb, *card)


async def _apply_status(pk: int, status: UserStatus, admin_tid: int) -> TelegramUser | None:
    async with async_session() as session:
        u = await session.get(TelegramUser, pk)
        if u is None:
            return None
        changed = u.status != status
        u.status = status
        u.approved_by = admin_tid
        u.approved_at = datetime.datetime.now(datetime.timezone.utc)
        await session.commit()
    u.changed = changed  # type: ignore[attr-defined]
    return u


async def _notify_status(bot: Bot, u: TelegramUser) -> None:
    if not getattr(u, "changed", True):
        return
    try:
        if u.status == UserStatus.APPROVED:
            await bot.send_message(u.telegram_id, "✅ So'rovingiz tasdiqlandi! Endi nakladnoy rasmini yuborishingiz mumkin.",
                                   reply_markup=main_menu(u.role == ROLE_ADMIN))
        else:
            await bot.send_message(u.telegram_id, "❌ Kechirasiz, so'rovingiz rad etildi.")
    except Exception:
        logger.warning("Foydalanuvchiga (%s) xabar yuborib bo'lmadi", u.telegram_id)


@router.callback_query(F.data.startswith("adm:ust:"))
async def cb_user_status(cb: CallbackQuery) -> None:
    _, _, pk, action, page = cb.data.split(":")
    u = await _apply_status(int(pk), UserStatus.APPROVED if action == "ok" else UserStatus.REJECTED, cb.from_user.id)
    if u is None:
        await cb.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await _notify_status(cb.bot, u)
    await show(cb, *await render_user_card(int(pk), int(page)))


@router.callback_query(F.data.startswith("approve_user:"))
@router.callback_query(F.data.startswith("reject_user:"))
async def cb_notification_decision(cb: CallbackQuery) -> None:
    action, pk = cb.data.split(":")
    ok = action == "approve_user"
    u = await _apply_status(int(pk), UserStatus.APPROVED if ok else UserStatus.REJECTED, cb.from_user.id)
    if u is None:
        await cb.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await _notify_status(cb.bot, u)
    await cb.message.edit_text(esc(cb.message.text) + ("\n\n✅ Tasdiqlandi" if ok else "\n\n❌ Rad etildi"))
    await cb.answer()


async def _set_role(bot: Bot, pk: int, role: str) -> tuple[TelegramUser | None, str | None]:
    async with async_session() as session:
        u = await session.get(TelegramUser, pk)
        if u is None:
            return None, "Foydalanuvchi topilmadi."
        if role == ROLE_USER and is_env_admin(u.telegram_id):
            return u, "Bu admin ADMIN_IDS orqali berilgan, uni bu yerdan olib bo'lmaydi."
        if role == ROLE_ADMIN and u.status != UserStatus.APPROVED:
            return u, "Avval foydalanuvchini tasdiqlang."
        u.role = role
        await session.commit()
    try:
        if role == ROLE_ADMIN:
            await bot.send_message(u.telegram_id, "👑 Sizga admin huquqi berildi. /admin buyrug'ini yuboring.",
                                   reply_markup=main_menu(True))
        else:
            await bot.send_message(u.telegram_id, "Sizning admin huquqingiz olib tashlandi.", reply_markup=main_menu(False))
    except Exception:
        logger.warning("Foydalanuvchiga (%s) xabar yuborib bo'lmadi", u.telegram_id)
    return u, None


@router.callback_query(F.data.startswith("adm:role:"))
async def cb_role(cb: CallbackQuery) -> None:
    _, _, pk, role, page = cb.data.split(":")
    u, err = await _set_role(cb.bot, int(pk), role)
    if err:
        await cb.answer(err, show_alert=True)
        return
    await show(cb, *await render_user_card(int(pk), int(page)))


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Foydalanish: <code>/addadmin 123456789</code> (Telegram ID). "
                             "Foydalanuvchi avval botga /start yozib, tasdiqlangan bo'lishi kerak.")
        return
    async with async_session() as session:
        u = await get_user_by_tid(session, int(arg))
    if u is None:
        await message.answer("Bunday foydalanuvchi topilmadi. Avval u botga /start yozib ro'yxatdan o'tsin.")
        return
    _, err = await _set_role(message.bot, u.id, ROLE_ADMIN)
    await message.answer(err or f"👑 {esc(u.full_name)} endi admin.")


# ---------------------------------------------------------------- invoices
@router.callback_query(F.data.startswith("adm:inv:"))
async def cb_invoices(cb: CallbackQuery) -> None:
    _, _, period, flt, page = cb.data.split(":")
    await show(cb, *await render_invoices(period, flt, int(page)))


@router.callback_query(F.data.startswith("adm:invd:"))
async def cb_invoice_detail(cb: CallbackQuery) -> None:
    _, _, inv_id, period, flt, page = cb.data.split(":")
    res = await render_invoice_detail(int(inv_id), period, flt, int(page))
    if res is None:
        await cb.answer("Nakladnoy topilmadi.", show_alert=True)
        return
    await show(cb, *res)


@router.callback_query(F.data.startswith("adm:invp:"))
async def cb_invoice_photo(cb: CallbackQuery) -> None:
    _, _, inv_id, period, flt, page = cb.data.split(":")
    inv = await _load_invoice(int(inv_id))
    if inv is None or not inv.photo_file_id:
        await cb.answer("Rasm saqlanmagan.", show_alert=True)
        return
    caption = (f"🧾 №{esc(inv.invoice_number)} • {inv.date:%d.%m.%Y}\n🏢 {esc(inv.customer.name)}\n"
               f"💰 {fmt_num(inv.total_sum)} so'm")
    markup = _invoice_buttons(int(inv_id), f"{period}:{flt}:{page}", True, "photo")
    try:
        await cb.message.answer_photo(inv.photo_file_id, caption=caption, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer("⚠️ Rasmni Telegramdan olib bo'lmadi (file_id yaroqsiz).")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:invf:"))
async def cb_invoice_pdf(cb: CallbackQuery) -> None:
    inv_id = int(cb.data.split(":")[2])
    inv = await _load_invoice(inv_id)
    if inv is None:
        await cb.answer("Nakladnoy topilmadi.", show_alert=True)
        return
    await cb.answer("PDF tayyorlanmoqda…")
    data = await asyncio.to_thread(build_invoice_pdf, inv)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", inv.invoice_number)
    await cb.message.answer_document(
        BufferedInputFile(data, filename=f"nakladnoy_{safe}_{inv.date:%Y%m%d}.pdf"),
        caption=f"📄 Nakladnoy №{esc(inv.invoice_number)} • {inv.date:%d.%m.%Y} (bazadagi ma'lumotlar asosida)",
    )


# ---------------------------------------------------------------- database browser
async def render_db_menu():
    async with async_session() as session:
        counts = {k: (await session.execute(select(func.count(e["model"].id)))).scalar_one() for k, e in ENT.items()}
        n_users = (await session.execute(select(func.count(TelegramUser.id)))).scalar_one()
        n_inv = (await session.execute(select(func.count(Invoice.id)))).scalar_one()
        n_items = (await session.execute(select(func.count(InvoiceItem.id)))).scalar_one()
        n_dup = (await session.execute(select(func.count(InvoiceDuplicate.id)))).scalar_one()
    text = ("🗄 <b>Ma'lumotlar bazasi</b>\nBarcha jadvallarni ko'rish mumkin. "
            f"Nakladnoy qatorlari: {n_items} ta.")
    rows = [[btn(f"👥 Foydalanuvchilar ({n_users})", "adm:users:0"), btn(f"🧾 Nakladnoylar ({n_inv})", "adm:inv:all:0:0")]]
    ent_btns = [btn(f"{e['icon']} {e['title']} ({counts[k]})", f"adm:dbl:{k}:0") for k, e in ENT.items()]
    rows += [ent_btns[i:i + 2] for i in range(0, len(ent_btns), 2)]
    rows.append([btn(f"🔁 Dublikat so'rovlari ({n_dup})", "adm:dbl:d:0")])
    rows.append([btn("📥 Butun bazani Excelga", "adm:xls:db")])
    rows.append([btn("◀️ Menyu", "adm:menu")])
    return text, kb(rows)


async def render_db_list(kind: str, page: int):
    async with async_session() as session:
        if kind == "d":
            total = (await session.execute(select(func.count(InvoiceDuplicate.id)))).scalar_one()
            rows_db = (await session.execute(
                select(InvoiceDuplicate.invoice_id, Invoice.invoice_number, TelegramUser.full_name, InvoiceDuplicate.created_at)
                .select_from(InvoiceDuplicate).join(Invoice, Invoice.id == InvoiceDuplicate.invoice_id)
                .join(TelegramUser, TelegramUser.id == InvoiceDuplicate.submitted_by)
                .order_by(InvoiceDuplicate.created_at.desc()).offset(page * DB_PAGE).limit(DB_PAGE)
            )).all()
            title = "🔁 <b>Dublikat so'rovlari</b>\nBir xil nakladnoyni qayta topshirganlar (nakladnoyni ochish uchun bosing)"
            buttons = [[btn(f"№{n} • {u[:14]} • {local(t):%d.%m %H:%M}", f"adm:invd:{iid}:all:0:0")] for iid, n, u, t in rows_db]
        else:
            e = ENT[kind]
            total = (await session.execute(select(func.count(e["model"].id)))).scalar_one()
            objs = (await session.execute(
                select(e["model"]).order_by(e["order"]).offset(page * DB_PAGE).limit(DB_PAGE)
            )).scalars().all()
            title = f"{e['icon']} <b>{e['title']}</b>"
            buttons = [[btn(f"{e['icon']} {e['name'](o)[:44]}", f"adm:dbc:{kind}:{o.id}:{page}")] for o in objs]
    pages = max(1, math.ceil(total / DB_PAGE))
    rows = buttons
    nav = pager(f"adm:dbl:{kind}:", page, total, DB_PAGE)
    if nav:
        rows.append(nav)
    rows.append([btn("◀️ Ma'lumotlar bazasi", "adm:db")])
    text = f"{title}\nJami: {total} ta • Sahifa {page + 1}/{pages}" + ("" if total else "\n\nHozircha bo'sh.")
    return text, kb(rows)


def _top_lines(rows, unit: str = "") -> list[str]:
    return [f"{i}. {esc(n)} — {fmt_num(q)}{unit}, {fmt_num(t)}" for i, (n, q, t) in enumerate(rows, 1)]


async def render_db_card(kind: str, oid: int, page: int):
    e = ENT[kind]
    flt = f"{kind}{oid}"
    async with async_session() as session:
        obj = await session.get(e["model"], oid)
        if obj is None:
            return None
        lines = [f"{e['icon']} <b>{esc(e['name'](obj))}</b>", f"ID: {obj.id}"]
        if kind == "c":
            lines += [f"INN: {esc(obj.inn)}", f"Manzil: {esc(obj.address)}", f"Mijoz kodi: {esc(obj.client_code)}"]
        elif kind == "s":
            lines += [f"INN: {esc(obj.inn)}", f"Manzil: {esc(obj.address)}", f"Telefon: {esc(obj.phone)}"]
        elif kind == "p":
            lines += [f"Kod: {esc(obj.code)}", f"Nomi: {esc(obj.name)}", f"Birlik: {esc(obj.unit)}"]

        if kind == "p":
            n_inv, qty, total, lo, hi = (await session.execute(
                select(func.count(func.distinct(InvoiceItem.invoice_id)),
                       func.coalesce(func.sum(InvoiceItem.quantity), 0), func.coalesce(func.sum(InvoiceItem.line_total), 0),
                       func.min(InvoiceItem.unit_price), func.max(InvoiceItem.unit_price))
                .where(InvoiceItem.product_id == oid)
            )).one()
            lines += ["", f"🧾 Nakladnoylarda: <b>{n_inv}</b> ta", f"📦 Jami sotilgan: <b>{fmt_num(qty)}</b> quti",
                      f"💰 Jami summa: <b>{fmt_num(total)}</b> so'm"]
            if lo is not None:
                lines.append("💲 Narx: " + (fmt_num(lo) if lo == hi else f"{fmt_num(lo)} – {fmt_num(hi)}"))
            tc = (await session.execute(
                select(Customer.name, func.sum(InvoiceItem.quantity), func.sum(InvoiceItem.line_total))
                .select_from(InvoiceItem).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                .join(Customer, Customer.id == Invoice.customer_id).where(InvoiceItem.product_id == oid)
                .group_by(Customer.id, Customer.name).order_by(func.sum(InvoiceItem.line_total).desc()).limit(5)
            )).all()
            if tc:
                lines += ["", "🏢 <b>Eng ko'p olgan xaridorlar</b>"] + _top_lines(tc, " quti")
        else:
            s = await stats.summary(session, None, None, flt=flt)
            d_from, d_to = (await session.execute(
                select(func.min(Invoice.date), func.max(Invoice.date)).where(*stats.filters(None, None, flt))
            )).one()
            lines += ["", f"🧾 Nakladnoylar: <b>{s['count']}</b> ta", f"📦 Jami: <b>{fmt_num(s['qty'])}</b> quti",
                      f"💰 Jami summa: <b>{fmt_num(s['sum'])}</b> so'm"]
            if d_from:
                lines.append(f"📅 {d_from:%d.%m.%Y} — {d_to:%d.%m.%Y}")
            if kind in ("c", "s"):
                top = await stats.top_products(session, None, None, limit=5, flt=flt)
                if top:
                    lines += ["", "🥤 <b>Top tovarlar</b>"] + _top_lines(top, " quti")
            else:
                top = await stats.top_customers(session, None, None, limit=5, flt=flt)
                if top:
                    lines += ["", "🏢 <b>Top xaridorlar</b>"] + [
                        f"{i}. {esc(n)} — {c} ta, {fmt_num(t)}" for i, (n, c, t) in enumerate(top, 1)]
    markup = kb([[btn("🧾 Nakladnoylari", f"adm:inv:all:{flt}:0")], [btn("◀️ Ro'yxat", f"adm:dbl:{kind}:{page}")]])
    return "\n".join(lines), markup


@router.callback_query(F.data == "adm:db")
async def cb_db_menu(cb: CallbackQuery) -> None:
    await show(cb, *await render_db_menu())


@router.callback_query(F.data.startswith("adm:dbl:"))
async def cb_db_list(cb: CallbackQuery) -> None:
    _, _, kind, page = cb.data.split(":")
    await show(cb, *await render_db_list(kind, int(page)))


@router.callback_query(F.data.startswith("adm:dbc:"))
async def cb_db_card(cb: CallbackQuery) -> None:
    _, _, kind, oid, page = cb.data.split(":")
    card = await render_db_card(kind, int(oid), int(page))
    if card is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await show(cb, *card)


# ---------------------------------------------------------------- Excel export
@router.callback_query(F.data == "adm:xls")
async def cb_xls_menu(cb: CallbackQuery) -> None:
    rows = [[btn(label, f"adm:xls:{p}") for p, label in PERIOD_LABELS.items()],
            [btn("🗄 Butun baza (barcha jadvallar)", "adm:xls:db")], [btn("◀️ Menyu", "adm:menu")]]
    await show(cb, "📥 <b>Excel eksport</b>\nNakladnoylarni davr bo'yicha yoki butun bazani yuklab oling:", kb(rows))


@router.callback_query(F.data.startswith("adm:xls:"))
async def cb_xls(cb: CallbackQuery) -> None:
    period = cb.data.split(":")[2]
    await cb.answer("Tayyorlanmoqda…")
    if period == "db":
        async with async_session() as session:
            data, counts = await build_full_xlsx(session)
        summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
        await cb.message.answer_document(
            BufferedInputFile(data, filename=f"baza_{today():%Y%m%d}.xlsx"),
            caption=f"🗄 Butun baza\n{summary}",
        )
        return
    async with async_session() as session:
        data, count = await build_invoices_xlsx(session, period_start(period))
    if not count:
        await cb.message.answer("Tanlangan davrda nakladnoy yo'q.")
        return
    await cb.message.answer_document(
        BufferedInputFile(data, filename=f"nakladnoylar_{period}_{today():%Y%m%d}.xlsx"),
        caption=f"📥 {PERIOD_LABELS[period]}: {count} ta nakladnoy (varaqlar: Nakladnoylar, Tovar qatorlari)",
    )
