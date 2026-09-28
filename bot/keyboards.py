from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_approval_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Tasdiqlash", callback_data=f"approve_user:{user_id}")
    builder.button(text="Rad etish", callback_data=f"reject_user:{user_id}")
    builder.adjust(2)
    return builder.as_markup()


def invoice_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="To'g'ri", callback_data="invoice:confirm")
    builder.button(text="Xato, tuzatish", callback_data="invoice:fix")
    builder.adjust(2)
    return builder.as_markup()


def field_choice_keyboard() -> InlineKeyboardMarkup:
    fields = [
        ("Hujjat raqami", "invoice_number"),
        ("Sana", "date"),
        ("Xaridor", "customer_name"),
        ("Agent", "sales_agent_name"),
        ("Jami summa", "total_sum"),
        ("Rasmni qayta yuborish", "retake_photo"),
    ]
    builder = InlineKeyboardBuilder()
    for label, key in fields:
        builder.button(text=label, callback_data=f"fixfield:{key}")
    builder.adjust(2)
    return builder.as_markup()


def duplicate_decision_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Ha, men ham topshiraman", callback_data="duplicate:yes")
    builder.button(text="Yo'q, bu boshqa hujjat", callback_data="duplicate:no")
    builder.adjust(1)
    return builder.as_markup()


BTN_MY_STATS = "📊 Mening statistikam"
BTN_HELP = "ℹ️ Yordam"
BTN_ADMIN = "🛠 Admin panel"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=BTN_MY_STATS), KeyboardButton(text=BTN_HELP)]]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
