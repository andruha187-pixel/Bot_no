import os
import asyncio
import re
import logging
from datetime import datetime
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)

API_TOKEN = os.environ.get("API_TOKEN")
METAR_URL = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/UUWW.TXT"
POLYMARKET_API_URL = "https://clob.polymarket.com"

if not API_TOKEN:
    raise ValueError("Критическая ошибка: Переменная окружения API_TOKEN не задана!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

class SetupStates(StatesGroup):
    waiting_for_link = State()

class BotState:
    is_running = False
    last_processed_time = None  
    current_max_temp = None     
    user_chat_id = None         
    target_event_slug = None    
    today_markets = {}          

state = BotState()

# --- ПАРСЕР METAR ---
async def parse_metar_report(text_data: str):
    try:
        lines = text_data.strip().split('\n')
        if len(lines) < 2: return None, None, False
        metar_body = lines[1].strip()
        if "SPECI" in metar_body: return None, None, True
            
        time_match = re.search(r'\b\d{2}(\d{4})Z\b', metar_body)
        if not time_match: return None, None, False
        observation_time_str = time_match.group(1)
        
        temp_match = re.search(r'\b(M?\d{2})/(M?\d{2})\b', metar_body)
        if not temp_match: return None, None, False
            
        temp_str = temp_match.group(1)
        temp = -int(temp_str[1:]) if temp_str.startswith('M') else int(temp_str)
        
        return observation_time_str, temp, False
    except Exception as e:
        logging.error(f"Ошибка при парсинге METAR: {e}")
        return None, None, False

# --- ПАРСЕР POLYMARKET ---
async def load_markets_by_slug(slug: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{POLYMARKET_API_URL}/markets", 
                params={"keyword": slug, "active": "true"},
                timeout=10.0
            )
            if response.status_code != 200: return False
                
            markets_data = response.json()
            new_markets = {}
            
            for market in markets_data:
                question = market.get("question", "")
                if slug.replace("-", " ").lower() in question.lower() or "temperature" in question.lower():
                    temp_match = re.search(r'(\d+)\s*°?C', question)
                    if temp_match:
                        temp_val = int(temp_match.group(1))
                        clob_token_ids = market.get("clobTokenIds")
                        if clob_token_ids and len(clob_token_ids) >= 2:
                            new_markets[temp_val] = clob_token_ids[1] # Токен для 'NO'
            
            if new_markets:
                state.today_markets = new_markets
                return True
            return False
        except Exception as e:
            logging.error(f"Ошибка API Polymarket: {e}")
            return False

# --- РАСЧЕТ ЛИКВИДНОСТИ, СТАВКИ И PNL ---
async def check_liquidity_and_bet(target_temp: int):
    if not state.user_chat_id:
        return

    token_id = state.today_markets.get(target_temp)
    if not token_id:
        await bot.send_message(state.user_chat_id, f"⚠️ Токен для {target_temp}°C не найден.")
        return

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{POLYMARKET_API_URL}/book", params={"token_id": token_id})
            if response.status_code != 200: return
                
            book_data = response.json()
            asks = book_data.get("asks", [])
            
            if not asks:
                await bot.send_message(state.user_chat_id, f"ℹ️ Стакан для {target_temp}°C пуст, нет ликвидности.")
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
                bet_amount_shares = int(free_balance / best_ask_price)
                cost = bet_amount_shares * best_ask_price
                
            if bet_amount_shares > 0:
                total_payout = bet_amount_shares * 1.00
                net_pnl = total_payout - cost
                pnl_percent = (net_pnl / cost) * 100 if cost > 0 else 0
                
                await bot.send_message(
                    chat_id=state.user_chat_id,
                    text=f"📊 **ОТЧЕТ О СДЕЛКЕ (СИМУЛЯЦИЯ)**\n"
                         f"📈 Исход: температура упала/пройдена -> **{target_temp}°C**\n"
                         f"🛒 Ставка: **Куплено исходов 'NO'**\n\n"
                         f"● Цена за акцию: `{best_ask_price:.2f}$`\n"
                         f"● Куплено акций: `{bet_amount_shares}` шт.\n"
                         f"● Сумма затрат: `{cost:.2f}$`\n"
                         f"💰 **Прогноз выплаты:** `{total_payout:.2f}$` (при закрытии рынка)\n"
                         f"🟩 **Чистый PnL по ставке:** `+{net_pnl:.2f}$` (`+{pnl_percent:.1f}%`)"
                )
            
        except Exception as e:
            logging.error(f"Ошибка при работе со стаканом: {e}")

# --- РАБОЧИЙ ЦИКЛ ОПРОСА ---
async def monitoring_worker(chat_id):
    await bot.send_message(
        chat_id, 
        f"🟢 Мониторинг погоды UUWW запущен под событие:\n"
        f"👉 `{state.target_event_slug}`\n\n"
        f"Проверка сводок выполняется в **XX:04-05** и **XX:34-35**."
    )
    
    while state.is_running:
        now = datetime.utcnow()
        current_minute = now.minute
        
        is_target_window = (4 <= current_minute <= 5) or (34 <= current_minute <= 35)
        
        if is_target_window:
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(METAR_URL, timeout=2.0)
                    if response.status_code == 200:
                        obs_time, temp, is_speci = await parse_metar_report(response.text)
                        
                        if is_speci: pass
                        elif obs_time and temp is not None:
                            if state.last_processed_time is None or obs_time != state.last_processed_time:
                                state.last_processed_time = obs_time
                                
                                if state.current_max_temp is None:
                                    state.current_max_temp = temp
                                    await bot.send_message(chat_id, f"ℹ️ Стартовый максимум температуры зафиксирован: **{temp}°C**")
                                elif temp > state.current_max_temp:
                                    previous_max = state.current_max_temp
                                    state.current_max_temp = temp
                                    
                                    await bot.send_message(
                                        chat_id, 
                                        f"🚀 Рекорд дня побит! Было: {previous_max}°C -> Стало: **{temp}°C** (Сводка {obs_time} UTC)."
                                    )
                                    
                                    for cold_temp in range(previous_max, temp):
                                        await check_liquidity_and_bet(cold_temp)
                                else:
                                    await bot.send_message(
                                        chat_id,
                                        f"☁️ Сводка {obs_time} UTC: **{temp}°C**. Максимум дня прежний (**{state.current_max_temp}°C**). Ставок нет."
                                    )
                except Exception as e:
                    logging.error(f"Ошибка запроса NOAA: {e}")
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(5)

# --- КНОПКИ И КОМАНДЫ ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="▶️ СТАРТ")
    builder.button(text="⏸️ СТОП")
    builder.button(text="📊 СТАТУС")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    state.user_chat_id = message.chat.id
    await message.answer(
        "Бот-полуавтомат настроен на вывод отчетов и PnL прямо в этот чат.\n"
        "Нажмите **▶️ СТАРТ** для ввода ссылки на рынок.", 
        reply_markup=get_main_keyboard()
    )

# Исправлено: Свободная проверка кнопки СТАРТ
@dp.message(lambda message: message.text and "СТАРТ" in message.text)
async def start_button_click(message: types.Message, state_ctx: FSMContext):
    if state.is_running:
        await message.answer("⚠️ Бот уже запущен.")
        return
    await message.answer("🔗 Отправьте ссылку на событие Polymarket:")
    await state_ctx.set_state(SetupStates.waiting_for_link)

@dp.message(SetupStates.waiting_for_link)
async def process_link(message: types.Message, state_ctx: FSMContext):
    link = message.text.strip()
    match = re.search(r'event/([^/]+)', link)
    if not match:
        await message.answer("❌ Ссылка должна содержать `/event/`. Попробуйте еще раз.")
        return
        
    event_slug = match.group(1)
    await message.answer("⏳ Анализирую событие и ищу стаканы...")
    
    state.today_markets.clear()
    state.current_max_temp = None
    state.last_processed_time = None
    
    success = await load_markets_by_slug(event_slug)
    if not success:
        await message.answer("❌ Не удалось считать рынки. Проверьте ссылку.")
        return
        
    state.target_event_slug = event_slug
    state.is_running = True
    state.user_chat_id = message.chat.id
    
    await state_ctx.clear()
    asyncio.create_task(monitoring_worker(message.chat.id))

# Исправлено: Свободная проверка кнопки СТОП
@dp.message(lambda message: message.text and "СТОП" in message.text)
async def stop_bot(message: types.Message):
    if not state.is_running:
        await message.answer("⚠️ Бот не запущен.")
        return
    state.is_running = False
    await message.answer("🛑 Мониторинг остановлен.")

# Исправлено: Свободная проверка кнопки СТАТУС
@dp.message(lambda message: message.text and "СТАТУС" in message.text)
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
