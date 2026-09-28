from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    waiting_full_name = State()
    waiting_id_number = State()


class InvoiceStates(StatesGroup):
    waiting_photo = State()
    waiting_confirmation = State()
    choosing_field_to_fix = State()
    waiting_field_value = State()
    waiting_duplicate_decision = State()
