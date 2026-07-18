import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Включаем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Берем токен из переменных окружения Render
API_TOKEN = os.environ.get("API_TOKEN")
METAR_URL = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/"
POLYMARKET_API_URL = "https://clob.polymarket.com"

if not API_TOKEN:
    raise ValueError("Критическая ошибка: Переменная API_TOKEN не найдена в окружении Render!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Состояния FSM
class SetupStates(StatesGroup):
    waiting_for_link = State()

# Глобальное состояние бота
class BotState:
    def __init__(self):
        self.is_running = False
        self.last_processed_time = None
        self.current_max_temp = None
        self.user_chat_id = None
        self.target_event_slug = None

bot_state = BotState()

# Клавиатура управления
def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="▶️ СТАРТ"), types.KeyboardButton(text="⏸️ СТОП")],
        [types.KeyboardButton(text="📊 СТАТУС")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# Заглушка воркера
async def monitoring_worker(chat_id):
    bot_state.user_chat_id = chat_id
    while bot_state.is_running:
        try:
            logging.info("Мониторинг активен, проверка условий...")
        except Exception as e:
            logging.error(f"Ошибка в воркере: {e}")
        await asyncio.sleep(1800)  # Раз в полчаса

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()  # Принудительный сброс состояний
    await message.answer(
        "Бот-полуавтомат настроен на вывод отчетов и PnL прямо в этот чат.\n"
        "Нажмите **▶️ СТАРТ** для ввода ссылки на рынок.",
        reply_markup=get_main_keyboard()
    )

# Исправленная кнопка СТАРТ
@dp.message(F.text.contains("СТАРТ"))
async def start_button_click(message: types.Message, state: FSMContext):
    await state.clear()
    if bot_state.is_running:
        await message.answer("⚠️ Бот уже запущен.")
        return
    await message.answer("🔗 Отправьте ссылку на событие Polymarket:")
    await state.set_state(SetupStates.waiting_for_link)

# Обработка входящей ссылки
@dp.message(SetupStates.waiting_for_link)
async def process_link(message: types.Message, state: FSMContext):
    link = message.text
    if "polymarket.com" not in link:
        await message.answer("❌ Это не похоже на ссылку Polymarket. Попробуйте еще раз.")
        return

    slug = link.split("/")[-1]
    bot_state.target_event_slug = slug
    bot_state.is_running = True
    
    await message.answer(
        f"✅ Рынок успешно выбран: `{slug}`\n"
        f"🚀 Мониторинг запущен! Отчеты будут приходить сюда каждые 30 минут."
    )
    await state.clear()
    asyncio.create_task(monitoring_worker(message.chat.id))

# Исправленная кнопка СТОП
@dp.message(F.text.contains("СТОП"))
async def stop_bot(message: types.Message, state: FSMContext):
    await state.clear()
    if not bot_state.is_running:
        await message.answer("⚠️ Бот не запущен.")
        return
    bot_state.is_running = False
    await message.answer("🛑 Мониторинг остановлен.")

# Исправленная кнопка СТАТУС
@dp.message(F.text.contains("СТАТУС"))
async def status_bot(message: types.Message):
    status = "АКТИВЕН 🟢" if bot_state.is_running else "ВЫКЛЮЧЕН 🛑"
    slug = bot_state.target_event_slug if bot_state.target_event_slug else "Не выбрано"
    max_t = f"{bot_state.current_max_temp}°C" if bot_state.current_max_temp is not None else "Не определена"
    
    await message.answer(
        f"📋 **Текущее состояние:**\n"
        f"● Работа: **{status}**\n"
        f"● Рынок: `{slug}`\n"
        f"● Максимум дня: **{max_t}**\n"
        f"● Каждые полчаса бот выводит отчеты сюда."
    )

# Главный запуск
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
