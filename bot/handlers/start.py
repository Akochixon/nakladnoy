from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.database.db import async_session
from bot.database.models import TelegramUser, UserStatus
from bot.keyboards import BTN_HELP, admin_approval_keyboard, main_menu
from bot.services.users import ROLE_ADMIN, admin_telegram_ids, ensure_env_admin, get_user_by_tid, is_env_admin
from bot.states import RegistrationStates
from bot.utils import esc

logger = logging.getLogger(__name__)
router = Router(name="start")

HELP_TEXT = (
    "ℹ️ <b>Qanday ishlaydi</b>\n"
    "1. Nakladnoyni tik, yorug'da, to'liq (chekkalari ko'rinadigan) suratga oling.\n"
    "2. Rasmni shu yerga <b>oddiy rasm</b> sifatida yuboring (fayl emas).\n"
    "3. Bot o'qigan ma'lumotni tekshirib, «To'g'ri» tugmasini bosing. Xato bo'lsa «Xato, tuzatish».\n\n"
    "Buyruqlar:\n/stats — mening statistikam\n/cancel — joriy amalni bekor qilish\n/start — bosh menyu"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user
    async with async_session() as session:
        user = await ensure_env_admin(session, tg) if is_env_admin(tg.id) else await get_user_by_tid(session, tg.id)

    if user is None:
        await message.answer(
            "Assalomu alaykum! Botdan foydalanish uchun ro'yxatdan o'tishingiz kerak.\n\n"
            "Ism va familyangizni to'liq kiriting:"
        )
        await state.set_state(RegistrationStates.waiting_full_name)
    elif user.status == UserStatus.PENDING:
        await message.answer("So'rovingiz hali admin tomonidan ko'rib chiqilmoqda. Iltimos kuting.")
    elif user.status == UserStatus.REJECTED:
        await message.answer("Kechirasiz, so'rovingiz rad etilgan. Savollar uchun administratorga murojaat qiling.")
    else:
        await message.answer(
            "Xush kelibsiz! Nakladnoy rasmini yuboring, men uni tahlil qilaman.",
            reply_markup=main_menu(user.role == ROLE_ADMIN),
        )


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi. Yangi nakladnoy rasmini yuborishingiz mumkin.")


@router.message(RegistrationStates.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext) -> None:
    full_name = (message.text or "").strip()
    if len(full_name.split()) < 2:
        await message.answer("Iltimos ism va familyangizni to'liq kiriting (masalan: Aliyev Vali).")
        return
    await state.update_data(full_name=full_name)
    await message.answer("JSHSHIR (ID) raqamingizni kiriting:")
    await state.set_state(RegistrationStates.waiting_id_number)


@router.message(RegistrationStates.waiting_id_number)
async def process_id_number(message: Message, state: FSMContext) -> None:
    id_number = (message.text or "").strip()
    if not id_number.isdigit() or len(id_number) < 9:
        await message.answer("ID raqami noto'g'ri ko'rinyapti. Faqat raqamlarni kiriting.")
        return

    full_name = (await state.get_data())["full_name"]
    async with async_session() as session:
        user = TelegramUser(
            telegram_id=message.from_user.id, full_name=full_name, id_number=id_number,
            username=message.from_user.username, status=UserStatus.PENDING,
        )
        session.add(user)
        await session.commit()
        user_pk = user.id

    await state.clear()
    await message.answer("So'rovingiz adminga yuborildi. Tasdiqlanishini kuting.")

    for admin_id in await admin_telegram_ids():
        try:
            await message.bot.send_message(
                admin_id,
                "🆕 Yangi foydalanuvchi so'rovi:\n"
                f"Ism: {esc(full_name)}\nID: {esc(id_number)}\nTelegram ID: {message.from_user.id}",
                reply_markup=admin_approval_keyboard(user_pk),
            )
        except Exception:
            logger.warning("Adminga (%s) xabar yuborib bo'lmadi", admin_id)
