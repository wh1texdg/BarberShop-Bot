from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_master = State()
    choosing_date = State()
    choosing_time = State()
    entering_name = State()
    entering_phone = State()
    confirming = State()


class ReviewStates(StatesGroup):
    entering_comment = State()


class AdminServiceStates(StatesGroup):
    entering_name = State()
    entering_price = State()
    entering_duration = State()
    entering_description = State()


class AdminMasterStates(StatesGroup):
    entering_name = State()
    entering_description = State()


class AdminClientStates(StatesGroup):
    searching = State()
