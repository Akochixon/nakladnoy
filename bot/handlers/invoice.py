from __future__ import annotations

import asyncio
import datetime
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.database.db import async_session
from bot.database.models import DuplicateDecision
from bot.keyboards import duplicate_decision_keyboard, field_choice_keyboard, invoice_confirmation_keyboard
from bot.services import invoice_service
from bot.services.ocr import extract_invoice
from bot.services.users import get_active_user
from bot.states import InvoiceStates
from bot.utils import esc, fmt_num

logger = logging.getLogger(__name__)
router = Router(name="invoice")


def _format_summary(data: dict) -> str:
    lines = [
        f"📄 Nakladnoy №{esc(data.get('invoice_number'))}",
        f"📅 Sana: {esc(data.get('date'))}",
        f"🏢 Xaridor: {esc(data.get('customer_name'))}",
        f"👤 Agent: {esc(data.get('sales_agent_name') or '-')}",
        "",
        "Tovarlar:",
    ]
    for idx, item in enumerate(data.get("items", []), start=1):
        lines.append(
            f"{idx}. {esc(item.get('name'))} — {fmt_num(item.get('quantity'))} "
            f"{esc(item.get('unit') or 'dona')} — {fmt_num(item.get('line_total'))}"
        )
    lines += ["", f"💰 Jami (chekda ko'rsatilgan): {fmt_num(data.get('total_sum'))} so'm"]
    return "\n".join(lines)


def _parse_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value.strip(), "%d.%m.%Y").date()


@router.message(F.photo)
async def handle_invoice_photo(message: Message, state: FSMContext) -> None:
    user = await get_active_user(message.from_user)
    if user is None:
        await message.answer("Rasm qabul qilish uchun avval ro'yxatdan o'tib, admin tasdig'ini kutishingiz kerak. /start")
        return

    await message.answer("🔍 Chek tahlil qilinmoqda, biroz kuting...")
    photo = message.photo[-1]
    try:
        file = await message.bot.get_file(photo.file_id)
        image_bytes = (await message.bot.download_file(file.file_path)).read()
        # OCR sinxron kutubxona: alohida oqimda ishlatamiz, shunda bot boshqa foydalanuvchilarga ham javob beradi.
        result = await asyncio.to_thread(extract_invoice, image_bytes)
    except Exception:
        logger.exception("OCR xatosi")
        await message.answer("⚠️ Rasmni o'qishda xatolik yuz berdi. Iltimos, birozdan keyin qayta yuboring.")
        return

    if not result.is_valid or not result.raw.get("items"):
        missing = ", ".join(result.missing_fields) if result.missing_fields else "asosiy maydonlar"
        await message.answer(
            f"⚠️ Rasmda quyidagi ma'lumotlarni aniq o'qib bo'lmadi: {esc(missing)}.\n\n"
            "Iltimos hujjatni tik, yaxshi yorug'lik ostida, to'liq (barcha chekka va matn "
            "ko'rinadigan) holda qayta suratga oling va yuboring."
        )
        return

    # Rasm Telegram serverida qoladi: bazaga faqat file_id yoziladi.
    await state.update_data(draft=result.raw, photo_file_id=photo.file_id, telegram_user_pk=user.id)
    await state.set_state(InvoiceStates.waiting_confirmation)
    await message.answer(_format_summary(result.raw), reply_markup=invoice_confirmation_keyboard())


@router.callback_query(InvoiceStates.waiting_confirmation, F.data == "invoice:fix")
async def ask_which_field(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(InvoiceStates.choosing_field_to_fix)
    await callback.message.answer("Qaysi maydonda xatolik bor?", reply_markup=field_choice_keyboard())
    await callback.answer()


@router.callback_query(InvoiceStates.choosing_field_to_fix, F.data.startswith("fixfield:"))
async def choose_field(callback: CallbackQuery, state: FSMContext) -> None:
    field_key = callback.data.split(":", 1)[1]
    if field_key == "retake_photo":
        await state.set_state(InvoiceStates.waiting_photo)
        await callback.message.answer("Yaxshi, hujjatni qaytadan suratga olib yuboring.")
    else:
        await state.update_data(fixing_field=field_key)
        await state.set_state(InvoiceStates.waiting_field_value)
        hint = " (DD.MM.YYYY, masalan 11.08.2026)" if field_key == "date" else ""
        await callback.message.answer(f"Yangi qiymatni kiriting{hint}:")
    await callback.answer()


@router.message(InvoiceStates.waiting_field_value)
async def apply_field_fix(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    draft, field_key = data["draft"], data["fixing_field"]
    value = (message.text or "").strip()

    if field_key == "date":
        try:
            _parse_date(value)
        except ValueError:
            await message.answer("Sana formati noto'g'ri. DD.MM.YYYY ko'rinishida kiriting (masalan 11.08.2026):")
            return
    elif field_key == "total_sum":
        try:
            value = float(value.replace(" ", "").replace(",", "."))
        except ValueError:
            await message.answer("Faqat raqam kiriting:")
            return

    draft[field_key] = value
    await state.update_data(draft=draft)
    await state.set_state(InvoiceStates.waiting_confirmation)
    await message.answer(_format_summary(draft), reply_markup=invoice_confirmation_keyboard())


@router.callback_query(InvoiceStates.waiting_confirmation, F.data == "invoice:confirm")
async def confirm_invoice(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data["draft"]
    try:
        _parse_date(draft.get("date", ""))
    except ValueError:
        await callback.answer("Sana o'qilmadi. «Xato, tuzatish» orqali DD.MM.YYYY formatida kiriting.", show_alert=True)
        return

    async with async_session() as session:
        supplier = await invoice_service.get_or_create_supplier(
            session, name=draft.get("supplier_name", ""), inn=draft.get("supplier_inn"),
            address=draft.get("supplier_address"), phone=draft.get("supplier_phone"),
        )
        existing = await invoice_service.find_existing_invoice(session, supplier.id, draft["invoice_number"])
        info = None
        if existing is not None:
            info = {
                "id": existing.id, "number": existing.invoice_number, "date": existing.date.strftime("%d.%m.%Y"),
                "customer": existing.customer.name, "total": existing.total_sum,
                "submitter": existing.submitter.full_name,
            }

    if info:
        await state.update_data(existing_invoice_id=info["id"])
        await state.set_state(InvoiceStates.waiting_duplicate_decision)
        await callback.message.answer(
            f"⚠️ Bu nakladnoy (№{esc(info['number'])}) allaqachon {esc(info['submitter'])} tomonidan "
            f"kiritilgan (sana: {info['date']}).\nXaridor: {esc(info['customer'])}\n"
            f"Jami: {fmt_num(info['total'])}\n\nSiz ham shu hujjatni topshirmoqchimisiz?",
            reply_markup=duplicate_decision_keyboard(),
        )
        await callback.answer()
        return

    await _save_invoice(callback, state, data)


@router.callback_query(InvoiceStates.waiting_duplicate_decision, F.data == "duplicate:yes")
async def duplicate_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    async with async_session() as session:
        await invoice_service.log_duplicate_decision(
            session, invoice_id=data["existing_invoice_id"], submitted_by_id=data["telegram_user_pk"],
            decision=DuplicateDecision.ACCEPTED_AS_DUPLICATE,
        )
    await state.clear()
    await callback.message.answer("✅ Qayd etildi, rahmat!")
    await callback.answer()


@router.callback_query(InvoiceStates.waiting_duplicate_decision, F.data == "duplicate:no")
async def duplicate_no(callback: CallbackQuery, state: FSMContext) -> None:
    await _save_invoice(callback, state, await state.get_data())


async def _save_invoice(callback: CallbackQuery, state: FSMContext, data: dict) -> None:
    draft, file_id = data["draft"], data["photo_file_id"]
    try:
        async with async_session() as session:
            supplier = await invoice_service.get_or_create_supplier(
                session, name=draft.get("supplier_name", ""), inn=draft.get("supplier_inn"),
                address=draft.get("supplier_address"), phone=draft.get("supplier_phone"),
            )
            customer = await invoice_service.get_or_create_customer(
                session, name=draft.get("customer_name", ""), inn=draft.get("customer_inn"),
                address=draft.get("customer_address"), client_code=draft.get("customer_client_code"),
            )
            sales_agent = await invoice_service.get_or_create_sales_agent(session, draft.get("sales_agent_name"))
            expediter = await invoice_service.get_or_create_expediter(session, draft.get("expediter_name"))
            invoice = await invoice_service.create_invoice(
                session, invoice_number=draft["invoice_number"], date=_parse_date(draft["date"]),
                supplier=supplier, customer=customer, sales_agent=sales_agent, expediter=expediter,
                submitted_by_id=data["telegram_user_pk"], items=draft.get("items", []), photo_file_id=file_id,
            )
            number, total = invoice.invoice_number, invoice.total_sum
    except Exception:
        logger.exception("Nakladnoyni saqlashda xato")
        await callback.message.answer("⚠️ Saqlashda xatolik yuz berdi. Birozdan keyin «To'g'ri» tugmasini qayta bosing.")
        await callback.answer()
        return

    await state.clear()
    await callback.message.answer(f"✅ Nakladnoy №{esc(number)} muvaffaqiyatli saqlandi!\nJami: {fmt_num(total)} so'm")
    await callback.answer()

    if settings.storage_chat_id:  # ixtiyoriy zaxira: yopiq kanalga nusxa
        try:
            await callback.bot.send_photo(
                settings.storage_chat_id, file_id,
                caption=f"№{esc(number)} | {esc(draft.get('date'))} | {esc(draft.get('customer_name'))} | "
                        f"{esc(callback.from_user.full_name)}",
            )
        except Exception:
            logger.warning("Zaxira chatga yuborib bo'lmadi")
