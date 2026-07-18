import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# ⚠️ ОБЯЗАТЕЛЬНО ВСТАВЬ СЮДА СВОЙ ТОКЕН ИЗ BOTFATHER
BOT_TOKEN = "ТВОЙ_ТОКЕН_ТУТ" 

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Состояния FSM
class SetupStates(StatesGroup):
    waiting_for_link = State()

# Глобальное состояние бота
class BotState:
    def __init__(self):
        self.is_running = False
        self.target_event_slug = None
        self.current_max_temp = None
        self.user_chat_id = None

state = BotState()

def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="▶️ СТАРТ"), types.KeyboardButton(text="⏸️ СТОП")],
        [types.KeyboardButton(text="📊 СТАТУС")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# Твоя оригинальная логика с подсчетом ликвидности и ставок
async def check_liquidity_and_bet(target_temp: int):
    # Тут вызывается твой API-запрос к Polymarket (например, получение стакана asks)
    # Ниже твоя проверенная математика:
    
    # Пример структуры, если бы мы её парсили: asks = [...]
    asks = [] 
    if not asks:
        return

    best_ask = asks[0]
    best_ask_price = float(best_ask.get("price"))  
    available_liquidity_shares = float(best_ask.get("size")) 

    free_balance = 100.0  
    required_money = available_liquidity_shares * best_ask_price

    if free_balance >= required_money:
        bet_amount_shares = available_liquidity_shares
        cost = required_money
    else:
        bet_amount_shares = free_balance / best_ask_price
        cost = bet_amount_shares * best_ask_price

    if bet_amount_shares > 0:
        total_payout = bet_amount_shares * 1.00
        net_pnl = total_payout - cost
        pnl_percent = (net_pnl / cost) * 100 if cost > 0 else 0

        # Отправка отчета в чат
        await bot.send_message(
            chat_id=state.user_chat_id,
            text=f"📊 **ОТЧЕТ О СДЕЛКЕ (СИМУЛЯЦИЯ)**\n"
                 f"Рынок: {state.target_event_slug}\n"
                 f"Куплено акций 'NO': {bet_amount_shares:.2f}\n"
                 f"Затрачено: ${cost:.2f} USDC\n"
                 f"Ожидаемый PnL: +${net_pnl:.2f} ({pnl_percent:.1f}%)"
        )

async def monitoring_worker(chat_id):
    state.user_chat_id = chat_id
    while state.is_running:
        try:
            # Для теста передаем 25 градусов, тут будет твоя логика температуры
            await check_liquidity_and_bet(25) 
        except Exception as e:
            logging.error(f"Ошибка в воркере: {e}")
        await asyncio.sleep(1800)  # Раз в полчаса

# Команда /start
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()
    await message.answer(
        "Бот-полуавтомат настроен на вывод отчетов и PnL прямо в этот чат.\n"
        "Нажмите **▶️ СТАРТ** для ввода ссылки на рынок.",
        reply_markup=get_main_keyboard()
    )

# Исправленная кнопка СТАРТ (работает всегда и везде)
@dp.message(F.text.contains("СТАРТ"))
async def start_button_click(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()
    if state.is_running:
        await message.answer("⚠️ Бот уже запущен.")
        return
    await message.answer("🔗 Отправьте ссылку на событие Polymarket:")
    await state_ctx.set_state(SetupStates.waiting_for_link)

# Обработка ссылки
@dp.message(SetupStates.waiting_for_link)
async def process_link(message: types.Message, state_ctx: FSMContext):
    link = message.text
    if "polymarket.com" not in link:
        await message.answer("❌ Это не похоже на ссылку Polymarket. Попробуйте еще раз.")
        return

    slug = link.split("/")[-1]
    state.target_event_slug = slug
    state.is_running = True
    
    await message.answer(
        f"✅ Рынок успешно выбран: `{slug}`\n"
        f"🚀 Мониторинг запущен! Отчеты будут приходить сюда каждые 30 минут."
    )
    await state_ctx.clear()
    asyncio.create_task(monitoring_worker(message.chat.id))

# Исправленная кнопка СТОП
@dp.message(F.text.contains("СТОП"))
async def stop_bot(message: types.Message, state_ctx: FSMContext):
    await state_ctx.clear()
    if not state.is_running:
        await message.answer("⚠️ Бот не запущен.")
        return
    state.is_running = False
    await message.answer("🛑 Мониторинг остановлен.")

# Исправленная кнопка СТАТУС
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

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
                    
