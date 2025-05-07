import asyncio
import logging
import time
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode

from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 🔐 Конфигурация
API_TOKEN = '7676017244:AAHfNC22t8VPUgvriekXzqoHlFmKGEFMOsA'
SERVICE_ACCOUNT_FILE = 'C:\\Race_bot\\online-results-458409-8d6404e76052.json'

# 📊 Таблицы
SPREADSHEET_ID = '1I_f4dzlJYyR32Zu3VTkLWFmPDC7rmq9Gje7C4yQnSXY'
SHEET_NAME = 'Race Results'

REG_SPREADSHEET_ID = '1nP-i937JHOVN0Sfzxsx5I5iKfI3NBs4_oyYA33r7avI'
REG_SHEET_NAME = 'Участники'

logging.basicConfig(level=logging.INFO)

start_time = None
race_finished = False
participants = {}  # будет заполнено динамически


def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))


def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Старт", callback_data="start_race")],
        [InlineKeyboardButton(text="✅ Завершить гонку", callback_data="finish_race")]
    ])


def get_participants_keyboard():
    builder = InlineKeyboardBuilder()
    for number in sorted(participants.keys()):  # 🔼 сортировка от меньшего к большему
        builder.button(text=str(number), callback_data=str(number))
    builder.adjust(5)
    return builder.as_markup()


def build_table_data():
    summary = []
    for num, data in participants.items():
        total_time = sum(data['laps'])
        last_name, first_name = data["name"].split(maxsplit=1) if ' ' in data["name"] else (data["name"], "")
        summary.append({
            "number": num,
            "last_name": last_name,
            "first_name": first_name,
            "laps": data["laps"],
            "total": total_time
        })

    summary.sort(key=lambda x: x["total"] if x["total"] > 0 else float('inf'))

    values = [["🏆 Место", "№", "Фамилия", "Имя", "Общее время"] + [f"Круг {i+1}" for i in range(4)]]
    medals = ["🥇", "🥈", "🥉"]

    for idx, p in enumerate(summary):
        place = medals[idx] if idx < 3 else f"{idx + 1}"
        lap_times = [format_time(t) for t in p["laps"]]
        lap_times += [""] * (4 - len(lap_times))
        values.append([
            place, p["number"], p["last_name"], p["first_name"], format_time(p["total"])
        ] + lap_times)

    return values



def upload_to_google_sheets(values):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE,
                                                  scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    sheet.values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:AN1000").execute()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()


def load_participants_from_sheet():
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE,
                                                      scopes=["https://www.googleapis.com/auth/spreadsheets"])
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()

        result = sheet.values().get(
            spreadsheetId=REG_SPREADSHEET_ID,
            range=f"{REG_SHEET_NAME}!A1:Z1000"
        ).execute()

        values = result.get("values", [])
        headers = values[0]
        data_rows = values[1:]

        participants_data = {}
        for row in data_rows:
            row_dict = dict(zip(headers, row))
            try:
                number = int(row_dict.get("Номер участника", "").strip())
                full_name = f"{row_dict.get('Фамилия', '').strip()} {row_dict.get('Имя', '').strip()}"
                participants_data[number] = {
                    "name": full_name,
                    "laps": [],
                    "last_lap_time": None
                }
            except (ValueError, AttributeError):
                continue

        return participants_data

    except HttpError as error:
        logging.error(f"Ошибка при чтении таблицы регистрации: {error}")
        return {}


async def google_sheet_updater():
    while True:
        if not race_finished and start_time:
            try:
                values = build_table_data()
                upload_to_google_sheets(values)
                logging.info("Google Таблица обновлена")
            except Exception as e:
                logging.error(f"Ошибка при обновлении таблицы: {e}")
        await asyncio.sleep(20)


async def main():
    global participants
    participants = load_participants_from_sheet()
    if not participants:
        logging.warning("Не удалось загрузить участников из таблицы. Используются участники по умолчанию.")
        participants = {
            i: {"name": f"Участник {i}", "laps": [], "last_lap_time": None} for i in range(1, 41)
        }

    bot = Bot(token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    asyncio.create_task(google_sheet_updater())

    @dp.message(F.text == "/start")
    async def start_cmd(message: Message):
        await message.answer("Выбери действие:", reply_markup=get_main_keyboard())

    @dp.callback_query(F.data == "start_race")
    async def handle_start(callback: CallbackQuery):
        global start_time, race_finished
        start_time = time.time()
        race_finished = False
        for data in participants.values():
            data["laps"].clear()
            data["last_lap_time"] = None

        await callback.message.answer("🏁 Гонка началась!")
        await callback.message.answer("Фиксируйте круги:", reply_markup=get_participants_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "finish_race")
    async def handle_finish(callback: CallbackQuery):
        global race_finished
        race_finished = True
        values = build_table_data()
        upload_to_google_sheets(values)

        table = ""
        for row in values[1:]:
            place, number, last_name, first_name, total_time = row[:5]
            laps = [t for t in row[5:] if t]
            laps_str = ", ".join(laps)
            full_name = f"{last_name} {first_name}".strip()
            table += f"{place} #{number} {full_name} — {total_time} ({laps_str})\n"

        sheet_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Открыть таблицу с результатами", url=sheet_url)]
            ]
        )

        await callback.message.answer(f"🏁 Гонка завершена!\n\n{table}", reply_markup=keyboard)
        await callback.answer()

    @dp.callback_query()
    async def handle_lap(callback: CallbackQuery):
        if race_finished:
            await callback.answer("Гонка завершена!")
            return

        num = int(callback.data)
        participant = participants.get(num)
        if not participant:
            await callback.answer("Участник не найден.")
            return

        now = time.time()
        lap_time = now - (participant["last_lap_time"] or start_time)
        participant["laps"].append(lap_time)
        participant["last_lap_time"] = now

        lap_number = len(participant["laps"])
        total_time = sum(participant["laps"])

        log_text = (
            f"✅ Участник #{num} завершил круг #{lap_number}\n"
            f"⏱ Время круга: {format_time(lap_time)}\n"
            f"🕒 Общее время: {format_time(total_time)}"
        )

        await callback.message.answer(log_text)
        await callback.answer()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())