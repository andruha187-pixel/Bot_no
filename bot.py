import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# ТОКЕН БОТА (Render должен брать его из Environment Variables, либо вставь свой вместо "")
BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА" 

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Состояния FSM для отслеживания ввода ссылки
class SetupStates(StatesGroup):
    waiting_for_link = State()

# Глобальный объект для хранения статуса работы (симуляция простой базы данных)
class BotState:
    def __init__(self):
        self.is_running = False
        self.target_event_slug = None
        self.current_max_temp = None
        self.user_chat_id = None

state = BotState()

# Клавиатура главного меню
def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="▶️ СТАРТ"), types.KeyboardButton(text="⏸️ СТОП")],
        [types.KeyboardButton(text="📊 СТАТУС")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# Имитация воркера мониторинга (замени на свою логику парсинга Polymarket)
async def monitoring_worker(chat_id):
    state.user_chat_id = chat_id
    while state.is_running:
        logging.info("Мониторинг активен, проверка данных...")
        # Тут должна быть твоя логика check_liquidity_and_bet
        await asyncio.sleep(1800)  # Раз в полчаса

# Команда /start
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()  # Полный сброс FSM принудительно
    await message.answer(
        "Бот-полуавтомат настроен на вывод отчетов и PnL прямо в этот чат.\n"
        "Нажмите **▶️ СТАРТ** для ввода ссылки на рынок.",
        reply_markup=get_main_keyboard()
    )

# Обработчик кнопки СТАРТ (срабатывает при любом состоянии FSM благодаря F.text)
@dp.message(F.text.contains("СТАРТ"))
async def start_button_click(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()  # Чистим любые зависшие состояния
    
    if state.is_running:
        await message.answer("⚠️ Бот уже запущен.")
        return
        
    await message.answer("🔗 Отправьте ссылку на событие Polymarket:")
    await state_ctx.set_state(SetupStates.waiting_for_link)

# Обработчик ввода ссылки (сработает только после нажатия СТАРТ)
@dp.message(SetupStates.waiting_for_link)
async def process_link(message: types.Message, state_ctx: FSMContext):
    link = message.text
    if "polymarket.com" not in link:
        await message.answer("❌ Это не похоже на ссылку Polymarket. Попробуйте еще раз или нажмите СТОП.")
        return

    # Извлекаем слаг из ссылки для отчетов
    slug = link.split("/")[-1]
    state.target_event_slug = slug
    state.is_running = True
    
    await message.answer(
        f"✅ Рынок успешно выбран: `{slug}`\n"
        f"🚀 Мониторинг запущен! Отчеты будут приходить сюда каждые 30 минут."
    )
    
    await state_ctx.clear()
    asyncio.create_task(monitoring_worker(message.chat.id))

# Обработчик кнопки СТОП
@dp.message(F.text.contains("СТОП"))
async def stop_bot(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()  # На случай если нажали СТОП во время ввода ссылки
    
    if not state.is_running:
        await message.answer("⚠️ Бот не запущен.")
        return
        
    state.is_running = False
    await message.answer("🛑 Мониторинг остановлен.")

# Обработчик кнопки СТАТУС
@dp.message(F.text.contains("СТАТУС"))
async def status_bot(message: types.Message):
    status = "АКТИВЕН 🟢" if state.is_running else "ВЫКЛЮЧЕН 🛑"
    slug = state.target_event_slug if state.target_event_slug else "Не выбрано"
    max_t = f"{state.current_max_temp}°C" if state.current_max_temp is not None else "Не определена"
    
    await message.answer(
        f"📋 **Текущее состояние:**\n"
        f"● Работа: **{status}**\n"
        f"● Рынок: `{slug}`\n"
        f"● Максимум дня: **{max_t}**\n"
        f"● Каждые полчаса бот выводит отчеты сюда."
    )

# Главная функция запуска
async def main():
    # Очищаем очередь старых сообщений, скопившихся пока бот лежал, 
    # чтобы он не спамил старыми ответами при перезапуске на Render
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
