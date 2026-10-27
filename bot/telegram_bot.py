import os
import sys
import signal
import asyncio
import datetime as dt
import requests
import sqlite3
import pathlib
import re
import html
from contextlib import closing

# Make the project root importable (for bot_settings / bot package)
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot_settings as cfg
from bot import backup_manager as bk
from bot import ea_admin
from bot import channels
from bot import reminders
from telegram.error import Forbidden, BadRequest

from datetime import datetime
import pytz
from collections import defaultdict
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
    BotCommand,
    MenuButtonCommands,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    TypeHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction, ParseMode

FA_COMMANDS = [
    BotCommand("start", "منوی اصلی"),
    BotCommand("help", "راهنما"),
]

EN_COMMANDS = [
    BotCommand("start", "Main menu"),
    BotCommand("help", "Help"),
]

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = q.data.split("_")[1]  # setlang_fa → fa
    if language not in LANGS:
        await q.answer()
        return
    set_user_language(cid, language)
    toast = {'fa': "✅ زبان: فارسی", 'en': "✅ Language: English"}
    await q.answer(toast[language])
    await safe_edit(q.message, main_menu_text(language, cid), main_menu_keyboard(language, cid))

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(cfg.LOG_PATH, encoding="utf-8"),  # ذخیره لاگ در فایل  
    ]
)
logger = logging.getLogger(__name__)

# در توابعی که خطا را نادیده می‌گیرید، لاگ کنید
LANGS = ("fa", "en")

def _db():
    return sqlite3.connect(DB_PATH, timeout=10)

def get_stored_language(chat_id: int) -> str | None:
    """The language the user picked, or None if they never picked one."""
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT language FROM subscribers WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] if row and row[0] in LANGS else None
    except Exception as e:
        logger.error(f"Error in get_stored_language for chat_id {chat_id}: {e}")
        return None

def get_user_language(chat_id: int, tg_language_code: str | None = None) -> str:
    """Stored language; if none yet, guess from the Telegram app language instead of forcing English."""
    stored = get_stored_language(chat_id)
    if stored:
        return stored
    return "fa" if (tg_language_code or "").lower().startswith("fa") else "en"

def set_user_language(chat_id: int, language: str):
    # Picking a language must NOT switch the Daily High-Impact News on (it used to insert a "subscribed" row)
    try:
        with closing(_db()) as conn, conn:
            conn.execute(
                """
                INSERT INTO subscribers (chat_id, language, digest_on)
                VALUES (?, ?, 0)
                ON CONFLICT(chat_id) DO UPDATE SET language = excluded.language
                """,
                (chat_id, language)
            )
    except Exception as e:
        logger.error(f"Error in set_user_language for chat_id {chat_id}: {e}")
    
def get_now_nyt() -> str:
    ny_tz = pytz.timezone("America/New_York")
    return datetime.now(ny_tz).strftime("%H:%M")

# ───────────────  Config  ────────────────
# All settings come from bot_settings.py (which reads .env)
BOT_TOKEN = cfg.TELEGRAM_BOT_TOKEN
DEFAULT_API_BASE = cfg.API_BASE_URL
ADMIN_CHAT_ID = cfg.ADMIN_CHAT_ID
BASE_DIR = cfg.BASE_DIR
DB_PATH = cfg.DB_PATH
SEND_RESTART_MSG = cfg.SEND_RESTART_MSG

# Admin can switch the active Flask server at runtime (see /setapi below).
# Initial value is loaded from the DB if the admin already set one, else falls back to .env.
API_BASE = DEFAULT_API_BASE

# ───────────────  DB helpers  ─────────────
def ensure_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    
    # جدول اصلی مشترکین
    cur.execute(
        """CREATE TABLE IF NOT EXISTS subscribers (
               chat_id     INTEGER PRIMARY KEY,
               digest_time TEXT DEFAULT '07:00',
               joined_at   TEXT DEFAULT CURRENT_TIMESTAMP,
               language    TEXT DEFAULT 'en',
               digest_on   INTEGER NOT NULL DEFAULT 1
        );"""
    )

    # جدول ارزهای انتخابی کاربر
    cur.execute(
        """CREATE TABLE IF NOT EXISTS user_currencies (
               chat_id     INTEGER PRIMARY KEY,
               currencies  TEXT DEFAULT 'USD',
               impacts     TEXT DEFAULT 'High'
        );"""
    )

    # جدول جدید برای جلوگیری از تکرار اطلاع به ادمین
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
               chat_id   INTEGER PRIMARY KEY,
               joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
               menu_kb   INTEGER NOT NULL DEFAULT 0
        );"""
    )

    # Key/value bot settings, including the active Flask API URL
    cur.execute(
        """CREATE TABLE IF NOT EXISTS bot_config (
               key   TEXT PRIMARY KEY,
               value TEXT
        );"""
    )

    # Named Flask servers saved by the admin
    cur.execute(
        """CREATE TABLE IF NOT EXISTS api_servers (
               name TEXT PRIMARY KEY,
               url  TEXT NOT NULL
        );"""
    )

    conn.commit()
    conn.close()
    channels.ensure_table()   # users' own channels for the daily digest
    ensure_calendar_table()   # 📆 daily date message (Persian / Gregorian), separate from the news
    reminders.ensure_tables() # ⏰ free reminders (one-time / daily / weekly)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()

    # اطمینان از وجود ستون language در subscribers
    try:
        cur.execute("ALTER TABLE subscribers ADD COLUMN language TEXT DEFAULT 'en'")
    except sqlite3.OperationalError:
        pass
    # 1 once the 🏠 Main Menu keyboard button has been sent to that user
    try:
        cur.execute("ALTER TABLE users ADD COLUMN menu_kb INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Impact filter per user (🔴 High / 🟠 Medium / 🟡 Low). Default: High only.
    try:
        cur.execute("ALTER TABLE user_currencies ADD COLUMN impacts TEXT DEFAULT 'High'")
    except sqlite3.OperationalError:
        pass
    # Daily High-Impact News on/off. Existing rows were all "subscribed", so they default to on.
    try:
        cur.execute("ALTER TABLE subscribers ADD COLUMN digest_on INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

# ───────────────  Runtime API server config  ─────────────
def get_config(key: str, default: str | None = None) -> str | None:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception as e:
        logger.error(f"Error in get_config for key {key}: {e}")
        return default

def set_config(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bot_config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value)
    )
    conn.commit()
    conn.close()

def load_api_base_from_db():
    """Load the admin's last saved API_BASE on startup, if any."""
    global API_BASE
    saved = get_config("api_base_url")
    if saved:
        API_BASE = saved
        logger.info(f"Loaded API_BASE from DB: {API_BASE}")
    else:
        API_BASE = DEFAULT_API_BASE
        logger.info(f"Using API_BASE from .env: {API_BASE}")

def restart_notice_on() -> bool:
    """'Bot is back online' message to all users on restart. Admin toggle (DB) wins over .env."""
    v = get_config("restart_notice")
    return SEND_RESTART_MSG if v is None else v == "1"

def is_admin(chat_id: int) -> bool:
    return ADMIN_CHAT_ID != 0 and chat_id == ADMIN_CHAT_ID

def list_api_servers() -> dict[str, str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name, url FROM api_servers ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        return {name: url for name, url in rows}
    except Exception:
        return {}

def save_api_server(name: str, url: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO api_servers (name, url) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET url = excluded.url
        """,
        (name, url)
    )
    conn.commit()
    conn.close()

def delete_api_server(name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM api_servers WHERE name = ?", (name,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

DEFAULT_BRIEF_TIME = "07:00"

def load_subs() -> dict[int, str]:
    """chat_id → time, only for users whose Daily High-Impact News is on."""
    try:
        with closing(_db()) as conn:
            rows = conn.execute("SELECT chat_id, digest_time FROM subscribers WHERE digest_on = 1").fetchall()
        return {int(cid): (t or DEFAULT_BRIEF_TIME) for cid, t in rows}
    except Exception as e:
        logger.error(f"Error in load_subs: {e}")
        return {}

def get_brief(chat_id: int) -> tuple[bool, str]:
    """(is_on, time) for one user."""
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT digest_on, digest_time FROM subscribers WHERE chat_id = ?",
                               (chat_id,)).fetchone()
    except Exception as e:
        logger.error(f"Error in get_brief for chat_id {chat_id}: {e}")
        row = None
    if not row:
        return False, DEFAULT_BRIEF_TIME
    return bool(row[0]), (row[1] or DEFAULT_BRIEF_TIME)

def set_brief_on(chat_id: int, on: bool, language: str | None = None):
    language = language or get_user_language(chat_id)
    with closing(_db()) as conn, conn:
        conn.execute(
            """INSERT INTO subscribers (chat_id, language, digest_on) VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET digest_on = excluded.digest_on""",
            (int(chat_id), language, 1 if on else 0))

def set_brief_time(chat_id: int, hhmm: str, language: str | None = None):
    language = language or get_user_language(chat_id)
    with closing(_db()) as conn, conn:
        conn.execute(
            """INSERT INTO subscribers (chat_id, language, digest_on, digest_time) VALUES (?, ?, 0, ?)
               ON CONFLICT(chat_id) DO UPDATE SET digest_time = excluded.digest_time""",
            (int(chat_id), language, hhmm))

def update_sub_time(chat_id: int, digest_time: str):   # kept for compatibility
    set_brief_time(chat_id, digest_time)

def save_sub(chat_id: int, digest_time: str | None = None):   # kept for compatibility
    if digest_time:
        set_brief_time(chat_id, digest_time)
    set_brief_on(chat_id, True)

def remove_sub(chat_id: int):
    # Turn it off, keep the row: deleting it threw away the user's language (→ English) and time
    set_brief_on(chat_id, False)

# ───────────────  Decor & Utils  ─────────────
def build_event_block(ev: dict) -> str:
    ny_tz = pytz.timezone("America/New_York")
    date_str = ev.get("Date", "")
    time_str = html.escape(str(ev.get("Time", "—")), quote=False)
    currency = html.escape(str(ev.get("Currency", "???")), quote=False)
    event_name = html.escape(str(ev.get("Event", "—")), quote=False)
    prev = html.escape(str(ev.get("Previous", "—")), quote=False)
    fcst = html.escape(str(ev.get("Forecast", "—")), quote=False)
    act  = html.escape(str(ev.get("Actual", "—")), quote=False)

    try:
        date_obj = datetime.strptime(date_str + f" {datetime.now().year}", "%a, %b %d %Y")
        date_obj = ny_tz.localize(date_obj)
        date_formatted = date_obj.strftime("%b %d")
        weekday_en = date_obj.strftime("%A")
        weekday_fa = {
            "Saturday": "شنبه", "Sunday": "یک‌شنبه", "Monday": "دوشنبه",
            "Tuesday": "سه‌شنبه", "Wednesday": "چهارشنبه", "Thursday": "پنج‌شنبه", "Friday": "جمعه"
        }.get(weekday_en, weekday_en)
    except:
        date_formatted = date_str
        weekday_fa = "—"

    return (
        f"📣 {weekday_fa}\n"
        f"{currency}\n"
        f"{IMPACT_DOT.get(ev.get('Impact', 'High'), '🔴')} {event_name}\n"
        f"⏱ {time_str} | {date_formatted}\n"
        f"📍 Prev: {prev} | Fcst: {fcst} | Act: {act}"
    )

async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, delay: float = 0):
    """Shows 'typing…' without blocking. (The old version slept 1s on every command = the /start lag.)"""
    try:
        await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

# ───────────────  UI texts  ─────────────
BRIEF_NAME = {'fa': "دریافت روزانه اخبار مهم", 'en': "Daily High-Impact News"}

UI = {
    'fa': {
        'welcome': "<b>خوش اومدی به خوشگل‌ترین ربات اخبار اقتصادی.</b>\n\n"
                   "من می‌تونم اخبار مهم اقتصادی ارزهایی که تو انتخاب می‌کنی، برات بفرستم.\n\n",
        'welcome_back': "<b>💎 برگشتی به منوی اصلی.</b>\n\n"
                        "اخبار مهم اقتصادی، فقط برای ارزهایی که خودت انتخاب می‌کنی.\n\n",
        'status_on': "🔔 <b>دریافت روزانه اخبار مهم</b> روشنه: هر روز کاری ساعت <b>{time}</b> به وقت نیویورک.",
        'status_off': "🔕 <b>دریافت روزانه اخبار مهم</b> خاموشه. از دکمه‌ی پایین روشنش کن.",
        'currencies': "💱 ارزها و اهمیت خبر",
        'today': "📅 امروز", 'tomorrow': "🚀 فردا", 'week': "🗓 هفته",
        'brief_btn_on': "🔔 دریافت روزانه اخبار مهم · {time}",
        'brief_btn_off': "🔕 دریافت روزانه اخبار مهم · خاموش",
        'channel': "📢 کانال من",
        'other_lang': ("🌐 English", "setlang_en"),
        # panel
        'p_title': "📰 <b>دریافت روزانه اخبار مهم</b>",
        'p_about': "هر روز کاری، سر ساعتی که خودت تعیین می‌کنی، خبرهای مهم ارزهات رو یک‌جا برات می‌فرستم.",
        'p_status_on': "وضعیت: <b>🟢 روشن</b>",
        'p_status_off': "وضعیت: <b>⚪️ خاموش</b>",
        'p_time': "⏰ ساعت: <b>{time}</b> (به وقت نیویورک)",
        'p_cur': "💱 ارزها: <b>{cur}</b>",
        'p_imp': "🎚 اهمیت: {imp}",
        'p_dest': "📍 مقصد: <b>{dest}</b>",
        'p_dest_chat': "همین چت",
        'p_toggle_on': "🟢 روشنه · بزن تا خاموش شه",
        'p_toggle_off': "⚪️ خاموشه · بزن تا روشن شه",
        'p_change_time': "⏰ تغییر ساعت · {time}",
        'back': "🔙 بازگشت",
        'toast_on': "🔔 دریافت روزانه اخبار مهم روشن شد · {time}",
        'toast_off': "🔕 دریافت روزانه اخبار مهم خاموش شد",
        'toast_time': "⏰ ساعت: {time}",
        # time picker
        't_title': "⏰ <b>ساعت ارسال</b> (به وقت نیویورک)\n\nالان روی <b>{time}</b> تنظیمه.\nاول ساعت رو بزن، بعد دقیقه.",
        't_done': "✅ تأیید",
    },
    'en': {
        'welcome': "<b>💎 Welcome to the beautiful economic news bot!</b>\n\n"
                   "I can send you High-Impact news for the currencies you choose.\n\n",
        'welcome_back': "<b>💎 Back to the main menu.</b>\n\n"
                        "High-Impact news, only for the currencies you choose.\n\n",
        'status_on': "🔔 <b>Daily High-Impact News</b> is on: every weekday at <b>{time}</b> New York time.",
        'status_off': "🔕 <b>Daily High-Impact News</b> is off. Turn it on with the button below.",
        'currencies': "💱 Currencies & Impact",
        'today': "📅 Today", 'tomorrow': "🚀 Tomorrow", 'week': "🗓 Week",
        'brief_btn_on': "🔔 Daily High-Impact News · {time}",
        'brief_btn_off': "🔕 Daily High-Impact News · Off",
        'channel': "📢 My channel",
        'other_lang': ("🌐 فارسی", "setlang_fa"),
        'p_title': "📰 <b>Daily High-Impact News</b>",
        'p_about': "Every weekday, at the time you pick, I send you all the high-impact news for your currencies.",
        'p_status_on': "Status: <b>🟢 On</b>",
        'p_status_off': "Status: <b>⚪️ Off</b>",
        'p_time': "⏰ Time: <b>{time}</b> (New York)",
        'p_cur': "💱 Currencies: <b>{cur}</b>",
        'p_imp': "🎚 Impact: {imp}",
        'p_dest': "📍 Sent to: <b>{dest}</b>",
        'p_dest_chat': "this chat",
        'p_toggle_on': "🟢 On · tap to turn off",
        'p_toggle_off': "⚪️ Off · tap to turn on",
        'p_change_time': "⏰ Change time · {time}",
        'back': "🔙 Back",
        'toast_on': "🔔 Daily High-Impact News on · {time}",
        'toast_off': "🔕 Daily High-Impact News off",
        'toast_time': "⏰ Time: {time}",
        't_title': "⏰ <b>Delivery time</b> (New York time)\n\nCurrently <b>{time}</b>.\nTap an hour, then the minutes.",
        't_done': "✅ Done",
    },
}

async def safe_edit(message, text: str, kb: InlineKeyboardMarkup | None = None):
    """edit_text that ignores Telegram's 'message is not modified' (tapping the selected option)."""
    try:
        await message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise

# ───────────────  ⌨️ Keyboard under the input box: 📊 Economic News · 📆 Calendar · ⏰ Reminders  ─────────────
# ⌨️ Keyboard under the input box. Changed the buttons? Bump KB_VERSION by 1:
# every user gets the new keyboard the first time they tap any button / send anything.
KB_VERSION = 4

KB_LABELS = {
    'fa': {'admin': "🛠 پنل ادمین", 'menu': "📊 اخبار اقتصادی", 'cal': "📆 تقویم", 'rem': "⏰ یادآورها"},
    'en': {'admin': "🛠 Admin Panel", 'menu': "📊 Economic News", 'cal': "📆 Calendar", 'rem': "⏰ Reminders"},
}
MENU_BUTTON = "🏠 Main Menu"          # old labels, still on some users' keyboards: keep working
KB_ACTIONS = {MENU_BUTTON: 'menu', "🏠 منو": 'menu', "🏠 Menu": 'menu'}
for _lbls in KB_LABELS.values():
    for _act, _lbl in _lbls.items():
        KB_ACTIONS[_lbl] = _act

def menu_kb(language: str = 'en', cid: int | None = None) -> ReplyKeyboardMarkup:
    """Keyboard under the input box. It rides along on messages that have no inline buttons.
    The admin (and only the admin) also gets 🛠 Admin Panel on the first row."""
    l = KB_LABELS.get(language, KB_LABELS['en'])
    rows = [
        [KeyboardButton(l['menu'])],                              # 📊 news, full width
        [KeyboardButton(l['cal']), KeyboardButton(l['rem'])],     # then two columns
    ]
    if cid is not None and is_admin(cid):
        rows.insert(0, [KeyboardButton(l['admin'])])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

MENU_KB = menu_kb('en')   # old name

def _kb_stamp(language: str, cid: int | None = None) -> int:
    """users.menu_kb stores which keyboard the user has: version * 10 + language (1 = fa, 2 = en),
    + 1000 for the admin keyboard. A version bump, a language switch or becoming admin all trigger a refresh."""
    return KB_VERSION * 10 + (1 if language == 'fa' else 2) + (1000 if cid is not None and is_admin(cid) else 0)

def _menu_kb_sent(cid: int, language: str | None = None) -> bool:
    """True if this user already has the current keyboard."""
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT menu_kb FROM users WHERE chat_id = ?", (cid,)).fetchone()
        return bool(row) and row[0] == _kb_stamp(language or get_user_language(cid), cid)
    except Exception:
        return False

def _mark_menu_kb(cid: int, language: str | None = None):
    stamp = _kb_stamp(language or get_user_language(cid), cid)
    try:
        with closing(_db()) as conn, conn:
            conn.execute("INSERT INTO users (chat_id, menu_kb) VALUES (?, ?) "
                         "ON CONFLICT(chat_id) DO UPDATE SET menu_kb = excluded.menu_kb", (cid, stamp))
    except Exception as e:
        logger.error(f"Error in _mark_menu_kb for {cid}: {e}")

# Telegram can only swap the keyboard together with a message, so one short general note goes out
KB_UPDATED = {
    'fa': "✅ ربات به‌روز شد.",
    'en': "✅ The bot has been updated.",
}

def kb_updated_text(language: str, cid: int) -> str:
    return KB_UPDATED.get(language, KB_UPDATED['en'])

async def keyboard_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs AFTER every handler (group 1): if the user's keyboard is older than KB_VERSION
    (or in the other language), send it once with a short note. Telegram can only set this keyboard with a message."""
    chat = update.effective_chat
    if chat is None or chat.type != "private":
        return
    language = get_stored_language(chat.id)
    if language is None or _menu_kb_sent(chat.id, language):   # new user still picking a language: wait
        return
    try:
        await context.bot.send_message(chat.id, kb_updated_text(language, chat.id), reply_markup=menu_kb(language, chat.id),
                                       parse_mode=ParseMode.HTML)
        _mark_menu_kb(chat.id, language)
    except Forbidden:
        _mark_menu_kb(chat.id, language)
    except Exception as e:
        logger.warning(f"Keyboard refresh for {chat.id} failed: {e}")

async def ensure_menu_button(context, cid: int, language: str, force: bool = False):
    """No more 🏠 carrier message (send + delete). The native Telegram Menu button is set once,
    globally, in post_init, so it exists for every user without /start. Kept as a no-op for old callers."""
    return

async def menu_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 Economic News tapped: cancel any pending input and show the main menu as a new message."""
    cid = update.effective_chat.id
    context.user_data.pop("awaiting", None)
    language = get_stored_language(cid)
    if language is None:   # never picked a language: same as /start
        await start(update, context)
        return
    await update.message.reply_text(main_menu_text(language, cid), reply_markup=main_menu_keyboard(language, cid),
                                    parse_mode=ParseMode.HTML)

def main_menu_text(language: str, cid: int, back: bool = False) -> str:
    t = UI[language]
    on, time_ = get_brief(cid)
    status = t['status_on'].format(time=time_) if on else t['status_off']
    return t['welcome_back' if back else 'welcome'] + status

def main_menu_keyboard(language: str = 'en', cid: int | None = None) -> InlineKeyboardMarkup:
    t = UI[language]
    on, time_ = get_brief(cid) if cid is not None else (False, DEFAULT_BRIEF_TIME)
    other_label, other_cb = t['other_lang']
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['currencies'], callback_data="choose_currencies")],
        [
            InlineKeyboardButton(t['today'], callback_data="today"),
            InlineKeyboardButton(t['tomorrow'], callback_data="tomorrow"),
            InlineKeyboardButton(t['week'], callback_data="week"),
        ],
        # One button for the whole Daily High-Impact News: shows its state, opens the panel
        [InlineKeyboardButton(t['brief_btn_on'].format(time=time_) if on else t['brief_btn_off'],
                              callback_data="brief")],
        [
            InlineKeyboardButton(t['channel'], callback_data="my_channel"),
            InlineKeyboardButton(other_label, callback_data=other_cb),   # one tap language switch
        ],
    ])

def default_keyboard(language: str = 'en', cid: int | None = None) -> InlineKeyboardMarkup:   # old name
    return main_menu_keyboard(language, cid)

def brief_panel(language: str, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    t = UI[language]
    on, time_ = get_brief(cid)
    ch = channels.get_channel(cid)
    text = "\n".join([
        t['p_title'], "", t['p_about'], "",
        t['p_status_on'] if on else t['p_status_off'],
        t['p_time'].format(time=time_),
        t['p_cur'].format(cur=", ".join(get_user_currencies(cid))),
        t['p_imp'].format(imp=" ".join(IMPACT_DOT[i] for i in get_user_impacts(cid))),
        t['p_dest'].format(dest=channels.label(ch) if ch else t['p_dest_chat']),
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t['p_toggle_on'] if on else t['p_toggle_off'], callback_data="brief_toggle")],
        [InlineKeyboardButton(t['p_change_time'].format(time=time_), callback_data="brief_time")],
        [InlineKeyboardButton(t['back'], callback_data="main_menu")],
    ])
    return text, kb

def brief_time_picker(language: str, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    t = UI[language]
    _, time_ = get_brief(cid)
    cur_h, cur_m = time_.split(":")
    rows, row = [], []
    for h in range(24):
        hh = f"{h:02d}"
        row.append(InlineKeyboardButton(f"✅{hh}" if hh == cur_h else hh, callback_data=f"brief_h_{hh}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    rows.append([
        InlineKeyboardButton(f"✅:{mm}" if mm == cur_m else f":{mm}", callback_data=f"brief_m_{mm}")
        for mm in ("00", "15", "30", "45")
    ])
    rows.append([InlineKeyboardButton(t['t_done'], callback_data="brief")])
    return t['t_title'].format(time=time_), InlineKeyboardMarkup(rows)


# ───────────────  📆 Calendar: Persian (Jalali) + Gregorian, with its own daily date message  ─────────────
# No extra package needed: the Jalali conversion is done right here.
NY_TZ = pytz.timezone("America/New_York")
DEFAULT_CAL_TIME = "07:00"
CAL_KINDS = ("jalali", "gregorian")

JALALI_MONTHS = {
    'fa': ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"],
    'en': ["Farvardin", "Ordibehesht", "Khordad", "Tir", "Mordad", "Shahrivar",
           "Mehr", "Aban", "Azar", "Dey", "Bahman", "Esfand"],
}
GREGORIAN_MONTHS = {
    'fa': ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
           "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"],
    'en': ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}
WEEKDAYS = {   # Python weekday(): Monday = 0
    'fa': ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"],
    'en': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def fa_num(x) -> str:
    return str(x).translate(_FA_DIGITS)

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd

def jalali_str(d: dt.date, language: str) -> str:
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    wd = WEEKDAYS[language][d.weekday()]
    if language == 'fa':
        return f"{wd} {fa_num(jd)} {JALALI_MONTHS['fa'][jm - 1]} {fa_num(jy)}"
    return f"{wd}, {jd} {JALALI_MONTHS['en'][jm - 1]} {jy}"

def gregorian_str(d: dt.date, language: str) -> str:
    wd = WEEKDAYS[language][d.weekday()]
    if language == 'fa':
        return f"{wd} {fa_num(d.day)} {GREGORIAN_MONTHS['fa'][d.month - 1]} {fa_num(d.year)}"
    return f"{wd}, {d.day} {GREGORIAN_MONTHS['en'][d.month - 1]} {d.year}"

def ny_today() -> dt.date:
    return datetime.now(NY_TZ).date()

CAL_UI = {
    'fa': {
        'menu_off': "📆 تقویم",
        'menu_on': "📆 تقویم · {time}",
        'title': "📆 <b>تاریخ امروز</b>",
        'jalali': "☀️ شمسی", 'gregorian': "🌍 میلادی",
        'daily_title': "📬 <b>ارسال روزانه تاریخ</b>",
        'daily_about': "هر روز (حتی آخر هفته) سر ساعتی که خودت تعیین می‌کنی، تاریخ امروز رو برات می‌فرستم.",
        'status_on': "وضعیت: <b>🟢 روشن</b> · ساعت <b>{time}</b> (به وقت نیویورک)",
        'status_off': "وضعیت: <b>⚪️ خاموش</b>",
        'which': "تقویم‌هایی که تو پیام روزانه میاد رو تیک بزن:",
        'toggle_on': "🟢 روشنه · بزن تا خاموش شه",
        'toggle_off': "⚪️ خاموشه · بزن تا روشن شه",
        'change_time': "⏰ تغییر ساعت · {time}",
        'toast_on': "📬 ارسال روزانه تاریخ روشن شد · {time}",
        'toast_off': "📭 ارسال روزانه تاریخ خاموش شد",
        'toast_time': "⏰ ساعت: {time}",
        'keep_one': "حداقل یکی باید روشن بمونه",
        'ch_on': "📢 ارسال به کانال {ch} · روشن", 'ch_off': "📢 ارسال به کانال · خاموش",
        'ch_none': "📢 ارسال به کانال · کانالی وصل نیست",
        'ch_need': "اول از منوی اخبار، «📢 کانال من» رو بزن و کانالت رو وصل کن",
        'ch_dest': "📍 مقصد: <b>کانال {ch}</b>",
        'toast_ch_on': "📢 از این به بعد تاریخ توی کانال {ch} ارسال میشه", 'toast_ch_off': "📢 ارسال به کانال خاموش شد",
        't_title': "⏰ <b>ساعت ارسال تاریخ</b> (به وقت نیویورک)\n\nالان روی <b>{time}</b> تنظیمه.\nاول ساعت رو بزن، بعد دقیقه.",
        'daily_msg': "📆 <b>تاریخ امروز</b>",
        'back': "🔙 بازگشت", 'done': "✅ تأیید",
    },
    'en': {
        'menu_off': "📆 Calendar",
        'menu_on': "📆 Calendar · {time}",
        'title': "📆 <b>Today's date</b>",
        'jalali': "☀️ Persian", 'gregorian': "🌍 Gregorian",
        'daily_title': "📬 <b>Daily date message</b>",
        'daily_about': "Every day (weekends too), at the time you pick, I send you today's date.",
        'status_on': "Status: <b>🟢 On</b> · at <b>{time}</b> (New York time)",
        'status_off': "Status: <b>⚪️ Off</b>",
        'which': "Tick the calendars to include in the daily message:",
        'toggle_on': "🟢 On · tap to turn off",
        'toggle_off': "⚪️ Off · tap to turn on",
        'change_time': "⏰ Change time · {time}",
        'toast_on': "📬 Daily date on · {time}",
        'toast_off': "📭 Daily date off",
        'toast_time': "⏰ Time: {time}",
        'keep_one': "Keep at least one on",
        'ch_on': "📢 Post to channel {ch} · On", 'ch_off': "📢 Post to channel · Off",
        'ch_none': "📢 Post to channel · no channel connected",
        'ch_need': "First connect your channel: News menu → “📢 My channel”",
        'ch_dest': "📍 Sent to: <b>channel {ch}</b>",
        'toast_ch_on': "📢 The date now goes to {ch}", 'toast_ch_off': "📢 Channel posting off",
        't_title': "⏰ <b>Date delivery time</b> (New York time)\n\nCurrently <b>{time}</b>.\nTap an hour, then the minutes.",
        'daily_msg': "📆 <b>Today's date</b>",
        'back': "🔙 Back", 'done': "✅ Done",
    },
}

def ensure_calendar_table():
    with closing(_db()) as conn, conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS date_daily (
                   chat_id   INTEGER PRIMARY KEY,
                   is_on     INTEGER NOT NULL DEFAULT 0,
                   send_time TEXT    NOT NULL DEFAULT '07:00',
                   kinds     TEXT    NOT NULL DEFAULT 'jalali,gregorian',
                   last_sent TEXT
            );""")
        # 📢 also post the daily date in the user's connected channel (default: off)
        try:
            conn.execute("ALTER TABLE date_daily ADD COLUMN to_channel INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass

def get_cal(chat_id: int) -> dict:
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT is_on, send_time, kinds, last_sent, to_channel FROM date_daily WHERE chat_id = ?",
                               (chat_id,)).fetchone()
    except Exception as e:
        logger.error(f"Error in get_cal for {chat_id}: {e}")
        row = None
    if not row:
        return {"on": False, "time": DEFAULT_CAL_TIME, "kinds": list(CAL_KINDS), "last_sent": None, "to_channel": False}
    kinds = [k for k in (row[2] or "").split(",") if k in CAL_KINDS] or list(CAL_KINDS)
    return {"on": bool(row[0]), "time": row[1] or DEFAULT_CAL_TIME, "kinds": kinds, "last_sent": row[3],
            "to_channel": bool(row[4])}

def _set_cal(chat_id: int, column: str, value):
    assert column in ("is_on", "send_time", "kinds", "last_sent", "to_channel")
    with closing(_db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO date_daily (chat_id) VALUES (?)", (int(chat_id),))
        conn.execute(f"UPDATE date_daily SET {column} = ? WHERE chat_id = ?", (value, int(chat_id)))

def calendar_menu_label(language: str, cid: int | None) -> str:
    c = CAL_UI[language]
    cal = get_cal(cid) if cid is not None else {"on": False}
    return c['menu_on'].format(time=cal['time']) if cal['on'] else c['menu_off']

def date_lines(language: str, kinds: list[str], d: dt.date | None = None) -> list[str]:
    c, d = CAL_UI[language], d or ny_today()
    lines = []
    if "jalali" in kinds:
        lines.append(f"{c['jalali']}: <b>{jalali_str(d, language)}</b>")
    if "gregorian" in kinds:
        lines.append(f"{c['gregorian']}: <b>{gregorian_str(d, language)}</b>")
    return lines

def calendar_panel(language: str, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    c, cal = CAL_UI[language], get_cal(cid)
    ch = channels.get_channel(cid)
    if not ch:
        ch_label = c['ch_none']
    else:
        ch_label = c['ch_on'].format(ch=channels.label(ch)) if cal['to_channel'] else c['ch_off']
    text = "\n".join([
        c['title'], "",
        *date_lines(language, list(CAL_KINDS)), "",
        c['daily_title'], c['daily_about'], "",
        c['status_on'].format(time=cal['time']) if cal['on'] else c['status_off'],
        *([c['ch_dest'].format(ch=channels.label(ch))] if (ch and cal['to_channel']) else []),
        c['which'],
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(c['toggle_on'] if cal['on'] else c['toggle_off'], callback_data="cal_toggle")],
        [InlineKeyboardButton(f"{'✅' if k in cal['kinds'] else '☑️'} {c[k]}", callback_data=f"cal_kind_{k}")
         for k in CAL_KINDS],
        [InlineKeyboardButton(c['change_time'].format(time=cal['time']), callback_data="cal_time")],
        [InlineKeyboardButton(ch_label, callback_data="cal_chan")],
        [InlineKeyboardButton(c['back'], callback_data="main_menu")],
    ])
    return text, kb

def calendar_time_picker(language: str, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    c, time_ = CAL_UI[language], get_cal(cid)['time']
    cur_h, cur_m = time_.split(":")
    rows, row = [], []
    for h in range(24):
        hh = f"{h:02d}"
        row.append(InlineKeyboardButton(f"✅{hh}" if hh == cur_h else hh, callback_data=f"cal_h_{hh}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    rows.append([InlineKeyboardButton(f"✅:{mm}" if mm == cur_m else f":{mm}", callback_data=f"cal_m_{mm}")
                 for mm in ("00", "15", "30", "45")])
    rows.append([InlineKeyboardButton(c['done'], callback_data="cal")])
    return c['t_title'].format(time=time_), InlineKeyboardMarkup(rows)

async def calendar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid, getattr(update.effective_user, "language_code", None))
    text, kb = calendar_panel(language, cid)
    await update.effective_message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """All 📆 buttons: cal, cal_toggle, cal_kind_X, cal_time, cal_h_HH, cal_m_MM."""
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    c, data, cal = CAL_UI[language], q.data, get_cal(cid)
    toast = None
    if data == "cal_toggle":
        on = not cal['on']
        _set_cal(cid, "is_on", 1 if on else 0)
        toast = c['toast_on'].format(time=cal['time']) if on else c['toast_off']
    elif data == "cal_chan":
        ch = channels.get_channel(cid)
        if not ch:
            await q.answer(c['ch_need'], show_alert=True)
            return
        on = not cal['to_channel']
        _set_cal(cid, "to_channel", 1 if on else 0)
        toast = c['toast_ch_on'].format(ch=channels.label(ch)) if on else c['toast_ch_off']
    elif data.startswith("cal_kind_"):
        kind = data[len("cal_kind_"):]
        kinds = cal['kinds']
        if kind in kinds and len(kinds) == 1:
            await q.answer(c['keep_one'])
            return
        if kind in CAL_KINDS:
            kinds = [k for k in kinds if k != kind] if kind in kinds else kinds + [kind]
            _set_cal(cid, "kinds", ",".join(k for k in CAL_KINDS if k in kinds))
        toast = f"{c.get(kind, kind)} {'✓' if kind in kinds else '✕'}"
    elif data == "cal_time" or data.startswith(("cal_h_", "cal_m_")):
        if data != "cal_time":
            _, part, val = data.split("_")
            h, m = cal['time'].split(":")
            new = f"{val}:{m}" if part == "h" else f"{h}:{val}"
            _set_cal(cid, "send_time", new)
            await q.answer(c['toast_time'].format(time=new))
        else:
            await q.answer()
        await safe_edit(q.message, *calendar_time_picker(language, cid))
        return
    await q.answer(toast)
    await safe_edit(q.message, *calendar_panel(language, cid))

async def reminders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await reminders.cmd(update, context, get_user_language(cid, getattr(update.effective_user, "language_code", None)))

async def reminders_tick(context: ContextTypes.DEFAULT_TYPE):
    await reminders.tick(context, get_user_language, menu_kb)

async def date_loop(context: ContextTypes.DEFAULT_TYPE):
    """Every minute: send today's date to users whose daily date time is now (New York time), once per day."""
    now = datetime.now(NY_TZ)
    hhmm, today_s = now.strftime("%H:%M"), now.date().isoformat()
    try:
        with closing(_db()) as conn:
            rows = conn.execute(
                "SELECT chat_id FROM date_daily WHERE is_on = 1 AND send_time = ? "
                "AND (last_sent IS NULL OR last_sent <> ?)", (hhmm, today_s)).fetchall()
    except Exception as e:
        logger.error(f"date_loop query failed: {e}")
        return
    for (cid,) in rows:
        try:
            _set_cal(cid, "last_sent", today_s)   # mark first: never send twice even if sending is slow
            language = get_user_language(cid)
            cal = get_cal(cid)
            text = "\n".join([CAL_UI[language]['daily_msg'], "", *date_lines(language, cal['kinds'], now.date())])
            ch = channels.get_channel(cid) if cal['to_channel'] else None
            if ch:
                try:
                    await context.bot.send_message(ch["id"], text, parse_mode=ParseMode.HTML)
                    continue
                except (Forbidden, BadRequest) as e:   # bot removed from the channel: fall back to the private chat
                    logger.warning(f"Daily date to channel {ch['id']} of {cid} failed: {e}")
            await context.bot.send_message(cid, text, parse_mode=ParseMode.HTML, reply_markup=menu_kb(language, cid))
            _mark_menu_kb(cid, language)
            await asyncio.sleep(0.05)
        except Forbidden:
            _set_cal(cid, "is_on", 0)   # user blocked the bot
        except Exception as e:
            logger.warning(f"Daily date for {cid} failed: {e}")


# ───────────────  Core fetch  ─────────────
def fill_missing_times(events: list[dict]) -> list[dict]:
    """Safety net if the API server still runs the old scraper: an event with an empty time
    happens at the same time as the event right before it on the same day (ForexFactory style)."""
    last_date, last_time = None, None
    for ev in events:
        date, time_ = ev.get("Date"), (ev.get("Time") or "").strip()
        if date != last_date:
            last_date, last_time = date, None
        if time_:
            last_time = time_
        elif last_time:
            ev["Time"] = last_time
    return events

IMPACTS = ("High", "Medium", "Low")
IMPACT_DOT = {"High": "🔴", "Medium": "🟠", "Low": "🟡", "Holiday": "⚪️"}

def get_filtered_events(endpoint: str, allowed_currencies: list[str],
                        impacts: list[str] | None = None) -> list[dict]:
    impacts = impacts or ["High"]
    try:
        # Old API servers ignore ?impact= and return High only, which is still correct for High
        response = requests.get(f"{API_BASE}/{endpoint}", params={"impact": ",".join(impacts).lower()}, timeout=10)
        response.raise_for_status()  # بررسی خطاهای HTTP
        data = fill_missing_times(response.json())
        return [ev for ev in data
                if ev.get("Currency") in allowed_currencies and ev.get("Impact", "High") in impacts]
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data from {API_BASE}/{endpoint}: {e}")
        return []

def group_by_currency(events: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ev in events:
        cur = ev.get("Currency", "???")
        grouped.setdefault(cur, []).append(ev)
    return grouped

def format_message_clean(title: str, events: list[dict], language: str = 'en') -> str:
    if not events:
        return "😴 No hot news today." if language == 'en' else "😴 هیچ خبر داغی نیست."

    messages = {
        'fa': {
            'day_map': {
                "Monday": "دوشنبه", "Tuesday": "سه‌شنبه", "Wednesday": "چهارشنبه",
                "Thursday": "پنج‌شنبه", "Friday": "جمعه", "Saturday": "شنبه", "Sunday": "یکشنبه"
            }
        },
        'en': {
            'day_map': {
                "Monday": "Monday", "Tuesday": "Tuesday", "Wednesday": "Wednesday",
                "Thursday": "Thursday", "Friday": "Friday", "Saturday": "Saturday", "Sunday": "Sunday"
            }
        }
    }

    ny_tz = pytz.timezone("America/New_York")
    grouped = defaultdict(lambda: defaultdict(list))

    for ev in events:
        # Escape: names like "S&P Global PMI" are invalid Telegram HTML and made the whole message fail
        currency = html.escape(str(ev.get("Currency", "???")), quote=False)
        event_name = html.escape(str(ev.get("Event", "—")), quote=False)
        time_str = html.escape(str(ev.get("Time", "—")), quote=False)
        prev = html.escape(str(ev.get("Previous", "—")), quote=False)
        fcst = html.escape(str(ev.get("Forecast", "—")), quote=False)
        act = html.escape(str(ev.get("Actual", "—")), quote=False)
        date_str = ev.get("Date", "—")

        try:
            date_obj = datetime.strptime(date_str + f" {datetime.now().year}", "%a, %b %d %Y")
            date_obj = ny_tz.localize(date_obj)
            date_str = date_obj.strftime("%b %d")
            farsi_day = messages[language]['day_map'].get(date_obj.strftime("%A"), date_obj.strftime("%A"))
            date_display = farsi_day
            date_line = f"📣 {farsi_day}"
        except:
            date_display = date_str
            date_line = f"📣 {date_str}"

        event_text = (
            f"{currency}\n"
            f"{IMPACT_DOT.get(ev.get('Impact', 'High'), '🔴')} {event_name}\n"
            f"⏱️ {time_str} | {date_str}\n"
            f"📍 Prev: {prev} | Fcst: {fcst} | Act: {act}\n"
        )
        grouped[currency][date_display].append(event_text)

    lines = [f"💫 {html.escape(title, quote=False)}\n"]
    for currency in grouped:
        for day, ev_list in grouped[currency].items():
            if language == 'en':
                lines.append(f"📣 {day}\n")
            else:
                lines.append(f"📣 {day}")
            lines.extend(ev_list)
            lines.append("")

    return "\n".join(lines).strip()

TG_LIMIT = 3900   # Telegram max is 4096 characters per message; keep a margin

def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split a long news message on blank lines (between events) so each part fits in one Telegram message.
    The weekly list, especially with 🟠/🟡 on, is often longer than 4096 chars and was silently dropped."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        while len(block) > limit:                      # a single huge block: hard cut
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(block[:limit])
            block = block[limit:]
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts

async def fetch_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, endpoint: str, title: str):
    await send_typing(context, update.effective_chat.id)
    cid = update.effective_chat.id
    language = get_user_language(cid)
    error_messages = {
        'fa': "😓 اوه! سرور جواب نداد؛ بعداً امتحان کن.",
        'en': "😓 Oops! Server didn't respond; try again later."
    }

    try:
        allowed = get_user_currencies(cid)
        # requests is blocking: run it in a thread so the whole bot doesn't freeze (up to 10s) for everyone
        events = await asyncio.to_thread(get_filtered_events, endpoint, allowed, get_user_impacts(cid))
        msg = format_message_clean(title, events, language)
        parts = split_message(msg)
        for i, part in enumerate(parts):
            # these messages have no inline buttons, so they carry the 🏠 keyboard for free (no extra message)
            await update.effective_message.reply_text(part, parse_mode=ParseMode.HTML,
                                                      reply_markup=menu_kb(language, cid) if i == len(parts) - 1 else None)
        _mark_menu_kb(cid, language)
    except Exception as e:
        logger.exception(f"Sending {endpoint} news to {cid} failed: {e}")
        await update.effective_message.reply_text(error_messages[language])

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int, user_info: dict):
    """ارسال پیام به ادمین هنگام加入 کاربر جدید"""
    try:
        username = user_info.get('username', 'نامشخص')
        first_name = user_info.get('first_name', 'نامشخص')
        last_name = user_info.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip()
        message = (
            f"📢 کاربر جدید به ربات اضافه شد!\n"
            f"🆔 شناسه: {user_id}\n"
            f"👤 نام: {full_name}\n"
            f"📛 نام کاربری: @{username if username != 'نامشخص' else 'ندارد'}\n"
            f"🕒 زمان: {datetime.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')} NYT"
        )
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=message, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Error notifying admin: {e}")
# ───────────────  Admin: Flask server panel (/admin)  ─────────────
ADMIN_AWAIT_ADD_SERVER = "add_server"
ADMIN_AWAIT_RESTORE_FILE = "restore_file"

ADMIN_RULE = "──────────────"
_BK_NAME = re.compile(r"^backup-(\d{8})-(\d{6})-([a-z\-]+?)-*\.zip$")

def _backup_label(p: pathlib.Path) -> str:
    """backup-20261009-073550-manual.zip → Oct 09, 07:35 · manual"""
    m = _BK_NAME.match(p.name)
    if not m:
        return p.name
    when = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return f"{when:%b %d, %H:%M} · {m.group(3)}"

def _active_server_name() -> str:
    for name, url in list_api_servers().items():
        if url == API_BASE:
            return name
    return "default (.env)"

def _user_stats() -> tuple[int, int]:
    try:
        with closing(_db()) as conn:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            daily = conn.execute("SELECT COUNT(*) FROM subscribers WHERE digest_on = 1").fetchone()[0]
        return users, daily
    except Exception:
        return 0, 0

def build_admin_menu_text() -> str:
    backups = bk.list_backups()
    users, daily = _user_stats()
    last = f"{_backup_label(backups[0])} · {len(backups)} saved" if backups else "none yet"
    lines = [
        "<b>ADMIN PANEL</b>", ADMIN_RULE,
        f"<b>Server</b>     ● {html.escape(_active_server_name())}",
        f"<code>{html.escape(API_BASE)}</code>",
        "",
        f"<b>Users</b>      {users} · {daily} get daily news",
        f"<b>Backup</b>     {last}",
        f"<b>Restart msg</b>  {'● on' if restart_notice_on() else '○ off'}",
    ]
    if ea_admin.available():
        lines.append(f"<b>Downloads</b>  {ea_admin.summary()}")
    return "\n".join(lines)

def build_admin_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("⇄ Servers", callback_data="admin_servers")]]
    if ea_admin.available():
        rows[0].append(InlineKeyboardButton("▤ Downloads", callback_data="ea:list"))
    rows += [
        [
            InlineKeyboardButton("⤓ Backup now", callback_data="admin_backup"),
            InlineKeyboardButton("↺ Restore", callback_data="admin_restore"),
        ],
        [InlineKeyboardButton("▦ Saved backups", callback_data="admin_backups")],
        [InlineKeyboardButton("● Restart message · On" if restart_notice_on() else "○ Restart message · Off",
                              callback_data="admin_restartmsg")],
    ]
    return InlineKeyboardMarkup(rows)

async def admin_restartmsg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-tap toggle for the 'Bot is back online' message sent to every user after a restart."""
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    on = not restart_notice_on()
    set_config("restart_notice", "1" if on else "0")
    await q.answer("● Users get a message after each restart" if on else "○ Restarts are silent now")
    await safe_edit(q.message, build_admin_menu_text(), build_admin_menu_keyboard())

def build_back_keyboard(to: str = "admin_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Back", callback_data=to)]])

def build_servers_view() -> tuple[str, InlineKeyboardMarkup]:
    """One screen for servers: tap = make active, ✕ = delete, ＋ = add."""
    servers = list_api_servers()
    lines = ["<b>SERVERS</b>", ADMIN_RULE]
    kb = []
    if servers:
        lines.append("Tap a server to make it active.")
        for name, url in servers.items():
            active = url == API_BASE
            kb.append([
                InlineKeyboardButton(f"{'●' if active else '○'}  {name}", callback_data=f"adminuse_{name}"),
                InlineKeyboardButton("✕", callback_data=f"admindelq_{name}"),
            ])
        if API_BASE not in servers.values():
            lines.append(f"\n● default (.env)\n<code>{html.escape(API_BASE)}</code>")
    else:
        lines.append(f"Using the default from .env:\n<code>{html.escape(API_BASE)}</code>\n\nNo saved servers yet.")
    kb.append([
        InlineKeyboardButton("＋ Add server", callback_data="admin_add"),
        InlineKeyboardButton("← Back", callback_data="admin_menu"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(kb)



async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /admin opens the panel (buttons only, no other commands needed)."""
    cid = update.effective_chat.id
    if not is_admin(cid):
        return
    context.user_data.pop("awaiting", None)
    _clear_pending_restore(context)
    await update.message.reply_text(
        build_admin_menu_text(), reply_markup=build_admin_menu_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    context.user_data.pop("awaiting", None)
    await q.answer()
    await safe_edit(q.message, build_admin_menu_text(), build_admin_menu_keyboard())

async def admin_servers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, toast: str | None = None):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    context.user_data.pop("awaiting", None)
    await q.answer(toast)
    await safe_edit(q.message, *build_servers_view())

async def admin_use_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global API_BASE
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    name = q.data.split("_", 1)[1]
    servers = list_api_servers()
    if name not in servers:
        await admin_servers_callback(update, context, "That server no longer exists.")
        return
    already = servers[name] == API_BASE
    API_BASE = servers[name]
    set_config("api_base_url", API_BASE)
    await admin_servers_callback(update, context, f"{name} is already active" if already else f"● Switched to {name}")

async def admin_delete_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    name = q.data.split("_", 1)[1]
    servers = list_api_servers()
    if name not in servers:
        await admin_servers_callback(update, context, "That server no longer exists.")
        return
    if servers[name] == API_BASE:
        await q.answer("This server is active. Switch to another one first.", show_alert=True)
        return
    await q.answer()
    await safe_edit(
        q.message,
        f"<b>DELETE SERVER</b>\n{ADMIN_RULE}\n{html.escape(name)}\n<code>{html.escape(servers[name])}</code>",
        InlineKeyboardMarkup([[
            InlineKeyboardButton("✕ Delete", callback_data=f"admindel_{name}"),
            InlineKeyboardButton("← Cancel", callback_data="admin_servers"),
        ]]),
    )

async def admin_delete_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    name = q.data.split("_", 1)[1]
    if list_api_servers().get(name) == API_BASE:
        await q.answer("This server is active. Switch to another one first.", show_alert=True)
        return
    deleted = delete_api_server(name)
    await admin_servers_callback(update, context, f"✕ Deleted {name}" if deleted else "Not found")

async def admin_add_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    context.user_data["awaiting"] = ADMIN_AWAIT_ADD_SERVER
    await safe_edit(
        q.message,
        f"<b>ADD SERVER</b>\n{ADMIN_RULE}\n"
        "Send it as one message:\n<code>name https://url</code>\n\n"
        "<i>Example</i>\n<code>iran https://iran.heysolo.ir/api/forex</code>",
        build_back_keyboard("admin_servers"),
    )

async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches the admin's reply after tapping ＋ Add server."""
    cid = update.effective_chat.id
    if not is_admin(cid) or context.user_data.get("awaiting") != ADMIN_AWAIT_ADD_SERVER:
        return

    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) != 2 or not parts[1].startswith(("http://", "https://")) or " " in parts[1]:
        await update.message.reply_text(
            "✕ Not recognised. Send it like this:\n<code>name https://url</code>",
            reply_markup=build_back_keyboard("admin_servers"), parse_mode=ParseMode.HTML
        )
        return   # still waiting, the admin can just send it again
    name, url = parts[0], parts[1].rstrip("/")
    if len(f"admindelq_{name}".encode()) > 64:
        await update.message.reply_text("✕ Name is too long, keep it short (e.g. iran, de1).",
                                        reply_markup=build_back_keyboard("admin_servers"))
        return
    context.user_data.pop("awaiting", None)
    save_api_server(name, url)
    text, kb = build_servers_view()
    await update.message.reply_text(f"✓ Saved {html.escape(name)}\n\n" + text, reply_markup=kb,
                                    parse_mode=ParseMode.HTML)

# ───────────────  Admin: backup & restore  ─────────────
def _admin_only(q) -> bool:
    return is_admin(q.message.chat.id)

def _fmt_counts(counts: dict) -> str:
    keys = ["subscribers", "users", "user_currencies", "api_servers", "bot_config"]
    parts = [f"{k}: <b>{counts[k]}</b>" for k in keys if k in counts]
    parts += [f"{k}: <b>{v}</b>" for k, v in counts.items() if k not in keys]
    return "\n".join(f"• {p}" for p in parts) or "• (empty)"

def _clear_pending_restore(context: ContextTypes.DEFAULT_TYPE):
    plan = context.user_data.pop("pending_restore", None)
    if plan is not None:
        plan.cleanup()

async def _send_backup_file(context: ContextTypes.DEFAULT_TYPE, chat_id: int, path: pathlib.Path, caption: str):
    with open(path, "rb") as fh:
        await context.bot.send_document(
            chat_id=chat_id, document=fh, filename=path.name,
            caption=caption, parse_mode=ParseMode.HTML,
        )

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⤓ Backup now: snapshot DB + .env into a zip and send it to the admin."""
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer("Creating backup…")
    await context.bot.send_chat_action(chat_id=q.message.chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    try:
        path = await asyncio.to_thread(bk.create_backup, "manual")
        counts = await asyncio.to_thread(bk._table_counts, cfg.DB_PATH)
    except bk.BackupError as e:
        await q.message.reply_text(f"✕ {e}")
        return
    except Exception as e:
        logger.exception("Backup failed")
        await q.message.reply_text(f"✕ Backup failed: {e}")
        return
    caption = (
        f"<b>BACKUP</b>\n{ADMIN_RULE}\n"
        f"<code>{path.name}</code>\n\n{_fmt_counts(counts)}\n\n"
        + (f"▤ Download files included: {len(bk._build_files())}\n" if bk._build_files() else "") +
        "△ Contains your bot token (.env). Keep it private.\n"
        "To restore: /admin → ↺ Restore → send this file."
    )
    try:
        await _send_backup_file(context, q.message.chat.id, path, caption)
    except Exception as e:
        logger.exception("Sending backup failed")
        await q.message.reply_text(f"△ Backup saved on server as <code>{path.name}</code> but sending failed: {e}",
                                   parse_mode=ParseMode.HTML)
    await q.message.reply_text(build_admin_menu_text(), reply_markup=build_admin_menu_keyboard(),
                               parse_mode=ParseMode.HTML)

async def admin_restore_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """↺ Restore: wait for the admin to upload a backup file."""
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    _clear_pending_restore(context)
    context.user_data["awaiting"] = ADMIN_AWAIT_RESTORE_FILE
    await q.message.edit_text(
        f"<b>RESTORE</b>\n{ADMIN_RULE}\n"
        "Send the backup <b>.zip</b> file here (or an old <code>forexbot.db</code>).\n\n"
        "Nothing changes until you confirm. A safety backup of the current data is "
        "taken automatically before restoring.",
        reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
    )

async def _show_restore_preview(message, context: ContextTypes.DEFAULT_TYPE, plan: "bk.RestorePlan"):
    context.user_data["pending_restore"] = plan
    created = plan.manifest.get("created_at", "unknown")
    kind = "raw database file" if plan.manifest.get("label") == "raw-db" else "full backup"
    rows = [[InlineKeyboardButton("✓ Restore data", callback_data="adminrs_data")]]
    if plan.has_settings:
        rows.append([InlineKeyboardButton("✓ Data + settings (.env, restarts bot)", callback_data="adminrs_all")])
    rows.append([InlineKeyboardButton("✕ Cancel", callback_data="adminrs_cancel")])
    await message.reply_text(
        f"<b>BACKUP CHECKED</b>\n{ADMIN_RULE}\n✓ Looks good\n\n"
        f"Type: {kind}\nCreated: <code>{created}</code>\n"
        f"Settings included: {'yes' if plan.has_settings else 'no'}\n"
        f"Download files included: {len(plan.builds)}\n\n"
        f"{_fmt_counts(plan.counts)}\n\n"
        "△ Restoring <b>replaces</b> all current users, subscriptions and servers.",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML
    )

async def admin_document_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the backup file after tapping ↺ Restore, or EA builds (EA versions)."""
    cid = update.effective_chat.id
    if context.user_data.get("awaiting") == channels.AWAIT_CHANNEL:
        await channel_input(update, context)
        return
    if not is_admin(cid):
        return
    if context.user_data.get("awaiting") != ADMIN_AWAIT_RESTORE_FILE:
        if ea_admin.wants_document(update, context):
            await ea_admin.handle_document(update, context)
        return
    doc = update.message.document
    if doc.file_size and doc.file_size > bk.MAX_RESTORE_BYTES:
        await update.message.reply_text("✕ File is larger than 20 MB, Telegram bots can't download it.")
        return
    context.user_data.pop("awaiting", None)
    _clear_pending_restore(context)

    incoming_dir = cfg.DATA_DIR / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    target = incoming_dir / f"upload-{update.message.message_id}.bin"
    await context.bot.send_chat_action(chat_id=cid, action=ChatAction.TYPING)
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=str(target))
        plan = await asyncio.to_thread(bk.prepare_restore, target)
    except bk.BackupError as e:
        await update.message.reply_text(f"✕ {e}\n\nOpen /admin → ↺ Restore to try again.")
        return
    except Exception as e:
        logger.exception("Restore upload failed")
        await update.message.reply_text(f"✕ Couldn't read that file: {e}")
        return
    finally:
        target.unlink(missing_ok=True)
    await _show_restore_preview(update.message, context, plan)

def _restart_process():
    """Exit cleanly; systemd (Restart=always) brings the bot back with the new .env."""
    os.kill(os.getpid(), signal.SIGTERM)

async def _restart_job(context: ContextTypes.DEFAULT_TYPE):
    _restart_process()

async def admin_restore_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    action = q.data.split("_", 1)[1]
    plan = context.user_data.get("pending_restore")
    if action == "cancel":
        _clear_pending_restore(context)
        await q.answer("Cancelled")
        await q.message.edit_text(build_admin_menu_text(), reply_markup=build_admin_menu_keyboard(),
                                  parse_mode=ParseMode.HTML)
        return
    if plan is None:
        await q.answer("This restore expired. Start again from ↺ Restore.", show_alert=True)
        return
    context.user_data.pop("pending_restore", None)
    await q.answer("Restoring…")
    await q.message.edit_text("Restoring, hang on…")
    include_settings = action == "all"
    try:
        safety, settings_changed = await asyncio.to_thread(bk.apply_restore, plan, include_settings)
        ensure_db()              # add any tables/columns the old backup didn't have
        load_api_base_from_db()  # pick up the restored active server
        counts = await asyncio.to_thread(bk._table_counts, cfg.DB_PATH)
    except bk.BackupError as e:
        plan.cleanup()
        await q.message.edit_text(f"✕ Restore failed: {e}\nYour current data was not changed.")
        return
    except Exception as e:
        plan.cleanup()
        logger.exception("Restore failed")
        await q.message.edit_text(
            f"✕ Restore failed: {e}\n\nIf anything looks off, use ▦ Saved backups → the "
            "latest <i>pre-restore</i> backup to roll back.", parse_mode=ParseMode.HTML)
        return

    text = (
        f"<b>RESTORE COMPLETE</b>\n{ADMIN_RULE}\n"
        + (f"▤ Download files restored: {len(plan.builds)}\n\n" if plan.builds else "") +
        f"{_fmt_counts(counts)}\n\n"
        f"Active server: <code>{API_BASE}</code>\n"
    )
    if safety:
        text += f"\nPrevious data saved as <code>{safety.name}</code> (▦ Saved backups)."
    if include_settings and settings_changed:
        text += "\n\n↻ Settings restored, restarting the bot in a few seconds…"
        await q.message.edit_text(text, parse_mode=ParseMode.HTML)
        context.job_queue.run_once(_restart_job, when=3)
        return
    await q.message.edit_text(text, reply_markup=build_admin_menu_keyboard(), parse_mode=ParseMode.HTML)

async def admin_backups_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """▦ Saved backups: backups stored on the server (manual + pre-restore)."""
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    backups = bk.list_backups()
    if not backups:
        await q.message.edit_text("No backups on the server yet. Tap ⤓ Backup now first.",
                                  reply_markup=build_back_keyboard())
        return
    kb = [[InlineKeyboardButton(_backup_label(p), callback_data=f"adminbk_{p.name}")] for p in backups]
    kb.append([InlineKeyboardButton("← Back", callback_data="admin_menu")])
    await q.message.edit_text(
        f"<b>SAVED BACKUPS</b>\n{ADMIN_RULE}\nKeeping the last {cfg.BACKUP_KEEP}. Tap one to send or restore it.",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML
    )

async def admin_backup_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    prefix, name = q.data.split("_", 1)
    path = bk.resolve_backup_name(name)
    if path is None:
        await q.answer("That backup no longer exists.", show_alert=True)
        return
    if prefix == "adminbksend":
        await q.answer("Sending…")
        await _send_backup_file(context, q.message.chat.id, path, f"<code>{path.name}</code>")
        return
    if prefix == "adminbkrs":
        await q.answer()
        _clear_pending_restore(context)
        try:
            plan = await asyncio.to_thread(bk.prepare_restore, path)
        except bk.BackupError as e:
            await q.message.reply_text(f"✕ {e}")
            return
        await _show_restore_preview(q.message, context, plan)
        return
    # adminbk_<name>: details
    await q.answer()
    await q.message.edit_text(
        f"<b>BACKUP</b>\n{ADMIN_RULE}\n{_backup_label(path)}\n<code>{bk.describe(path)}</code>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⤒ Send to me", callback_data=f"adminbksend_{path.name}"),
                InlineKeyboardButton("↺ Restore this", callback_data=f"adminbkrs_{path.name}"),
            ],
            [InlineKeyboardButton("← Back", callback_data="admin_backups")],
        ]),
        parse_mode=ParseMode.HTML
    )

def _subscribe_and_get_time(chat_id: int) -> str:
    set_brief_on(chat_id, True)
    return get_brief(chat_id)[1]

async def channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channels.on_message(update, context, get_user_language(update.effective_chat.id),
                              _subscribe_and_get_time)

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes plain text / forwarded posts to whichever flow is waiting for input."""
    if update.message is None or update.effective_chat.type != "private":
        return
    action = KB_ACTIONS.get((update.message.text or "").strip())
    if action:
        context.user_data.pop("awaiting", None)   # a keyboard button cancels any pending input
        if action == 'admin':
            await admin_cmd(update, context)   # does nothing for non-admins
        elif action == 'menu':
            await menu_button_pressed(update, context)
        elif action == 'cal':
            await calendar_cmd(update, context)
        else:
            await reminders_cmd(update, context)
        return
    if context.user_data.get("awaiting") == channels.AWAIT_CHANNEL:
        await channel_input(update, context)
        return
    if str(context.user_data.get("awaiting") or "").startswith("rem_") and update.message.text:
        await reminders.on_text(update, context, get_user_language(update.effective_chat.id))
        return
    if update.message.text:
        await admin_text_input(update, context)

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns the chat id — useful for setting ADMIN_CHAT_ID."""
    await update.message.reply_text(f"🆔 Chat ID: <code>{update.effective_chat.id}</code>", parse_mode=ParseMode.HTML)

# ───────────────  Commands  ─────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id

    # ---------- بررسی عضویت اولیه برای اطلاع به ادمین ----------
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE chat_id = ?", (cid,))
    first_time = cur.fetchone() is None

    if first_time:
        # ثبت کاربر به عنوان دیده‌شده
        cur.execute("INSERT INTO users (chat_id) VALUES (?)", (cid,))
        conn.commit()

        # ارسال پیام به ادمین
        user = update.effective_user
        # in the background: the user shouldn't wait for the admin message
        context.application.create_task(notify_admin(context, cid, {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        }))

    conn.close()

    # ---------- بررسی زبان کاربر ----------
    language = get_stored_language(cid)
    if language is None:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗣 فارسی", callback_data="setlang_fa"),
                InlineKeyboardButton("🗣 English", callback_data="setlang_en")
            ]
        ])
        await update.message.reply_text(
            "Please select your language:\nلطفاً زبان خود را انتخاب کنید:",
            reply_markup=keyboard
        )
        return

    await update.message.reply_text(main_menu_text(language, cid), reply_markup=main_menu_keyboard(language, cid),
                                    parse_mode=ParseMode.HTML)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    cid = update.effective_chat.id
    language = get_user_language(cid)
    
    messages = {
        'fa': (
            "<b>📘 راهنمای خوشگل‌ترین ربات اقتصادی دنیا</b>\n\n"
            "📊 این ربات تقویم اقتصادی و خبرهای مهم بازار رو مستقیم از سایت "
            "<b>Forex Factory</b> (forexfactory.com) می‌گیره و برات مرتب می‌فرسته.\n\n"
            "🗓 <b>اخبار هفته</b> از دوشنبه تا یک‌شنبه‌ست. هفته‌ی جدید بامداد <b>دوشنبه</b> میاد "
            "و اطلاعاتش هر روز یک بار به‌روز می‌شه.\n\n"
            "📆 <b>تقویم شمسی و میلادی</b> (دکمه‌ی 📆 تقویم پایین صفحه): تاریخ امروز رو ببین، یا ارسال روزانه‌ی تاریخ رو "
            "روشن کن و ساعتش رو تنظیم کن.\n\n"
            "⏰ <b>یادآورها</b> (دکمه‌ی ⏰ یادآورها پایین صفحه): یادآور یک‌باره، روزانه یا هفتگی بساز.\n\n"
            "همه‌چی از دکمه‌های زیر در دسترسه"
        ),
        'en': (
            "<b>📘 Guide to the beautiful Economic News Bot</b>\n\n"
            "📊 This bot pulls the economic calendar and key market news straight from "
            "<b>Forex Factory</b> (forexfactory.com) and delivers it to you, neatly organized.\n\n"
            "🗓 <b>Weekly news</b> runs Monday to Sunday. The new week shows up early <b>Monday</b> "
            "and its data is refreshed once a day.\n\n"
            "📆 <b>Persian & Gregorian calendar</b> (📆 Calendar button below): see today's date, or turn on a daily date "
            "message at your own time.\n\n"
            "⏰ <b>Reminders</b> (⏰ Reminders button below): one-time, daily or weekly reminders.\n\n"
            "Everything is available from the buttons below"
        )
    }
    
    await update.message.reply_text(messages[language], reply_markup=main_menu_keyboard(language, cid), parse_mode=ParseMode.HTML)

async def show_brief(update: Update, context: ContextTypes.DEFAULT_TYPE, toast: str | None = None):
    """Daily High-Impact News panel: edits the message when coming from a button, sends a new one for commands."""
    cid = update.effective_chat.id
    language = get_user_language(cid, getattr(update.effective_user, "language_code", None))
    text, kb = brief_panel(language, cid)
    q = update.callback_query
    if q:
        await q.answer(toast)
        await safe_edit(q.message, text, kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid, getattr(update.effective_user, "language_code", None))
    set_brief_on(cid, True, language)
    await show_brief(update, context, UI[language]['toast_on'].format(time=get_brief(cid)[1]))

async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid, getattr(update.effective_user, "language_code", None))
    set_brief_on(cid, False, language)
    await show_brief(update, context, UI[language]['toast_off'])


async def brief_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """All Daily High-Impact News buttons: brief, brief_toggle, brief_time, brief_h_HH, brief_m_MM."""
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    t = UI[language]
    data = q.data
    if data == "brief":
        await show_brief(update, context)
        return
    if data == "brief_toggle":
        on, time_ = get_brief(cid)
        set_brief_on(cid, not on, language)
        await show_brief(update, context, t['toast_off'] if on else t['toast_on'].format(time=time_))
        return
    if data.startswith(("brief_h_", "brief_m_")):
        _, part, val = data.split("_")
        h, m = get_brief(cid)[1].split(":")
        new = f"{val}:{m}" if part == "h" else f"{h}:{val}"
        set_brief_time(cid, new, language)
        await q.answer(t['toast_time'].format(time=new))
    else:  # brief_time
        await q.answer()
    text, kb = brief_time_picker(language, cid)
    await safe_edit(q.message, text, kb)



async def digest_loop(context: ContextTypes.DEFAULT_TYPE):
    # بررسی روز هفته در منطقه زمانی نیویورک
    ny_tz = pytz.timezone("America/New_York")
    current_day = datetime.now(ny_tz).strftime("%A")
    
    # اگر روز شنبه یا یک‌شنبه باشد، از ارسال پیام صرف‌نظر کن
    if current_day in ["Saturday", "Sunday"]:
        return
    
    now_nyt = get_now_nyt()
    subs_map = load_subs()
    recipients = [cid for cid, t in subs_map.items() if t == now_nyt]

    if not recipients:
        return

    for cid in recipients:
        try:
            language = get_user_language(cid)
            allowed = get_user_currencies(cid)
            events = await asyncio.to_thread(get_filtered_events, "today", allowed, get_user_impacts(cid))
            grouped_events = group_by_currency(events)
            messages = {
                'fa': {
                    'no_news': "😴 امروز خبری نیست.",
                    'title': "{cur} — 📅 خبرهای امروز"
                },
                'en': {
                    'no_news': "😴 No news today.",
                    'title': "{cur} — 📅 Today's News"
                }
            }
            if grouped_events:
                texts = [format_message_clean(messages[language]['title'].format(cur=cur), ev_list, language)
                         for cur, ev_list in grouped_events.items()]
            else:
                texts = [messages[language]['no_news']]

            # Send to the user's own channel if connected, otherwise to the private chat
            ch = channels.get_channel(cid)
            target = ch["id"] if ch else cid
            texts = [part for text in texts for part in split_message(text)]
            for i, text in enumerate(texts):
                kb = menu_kb(language, cid) if (target == cid and i == len(texts) - 1) else None
                try:
                    await context.bot.send_message(target, text, parse_mode=ParseMode.HTML, reply_markup=kb)
                except (Forbidden, BadRequest) as e:
                    if not ch:
                        raise
                    logger.warning(f"Channel {ch['id']} of {cid} failed: {e}; falling back to private chat")
                    await channels.notify_failed(context, cid, language, ch)
                    ch, target = None, cid
                    await context.bot.send_message(target, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"Digest for {cid} failed: {e}")
        
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    if data.startswith("setlang_"):
        await set_language(update, context)
        return
    if data == "change_language":
        language = get_user_language(q.message.chat.id)
        messages = {
            'fa': "لطفاً زبان خود را انتخاب کنید:",
            'en': "Please select your language:"
        }
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗣 فارسی", callback_data="setlang_fa"),
                InlineKeyboardButton("🗣 English", callback_data="setlang_en")
            ]
        ])
        await q.message.edit_text(messages[language], reply_markup=keyboard)
        await q.answer()
        return
    if data == "choose_currencies":
        await choose_currency_keyboard(update, context)
        return
    if data.startswith("toggleimp_"):
        await toggle_impact(update, context)
        return
    if data.startswith("togglecur_"):
        await toggle_currency(update, context)
        return
    if data == "brief" or data.startswith("brief_"):
        await brief_callback(update, context)
        return
    if data == "cal":
        await q.answer()
        cid = q.message.chat.id
        await safe_edit(q.message, *calendar_panel(get_user_language(cid, getattr(q.from_user, "language_code", None)), cid))
        return
    if data.startswith("cal_"):
        await calendar_callback(update, context)
        return
    if data == "rem" or data.startswith("rem_"):
        await reminders.on_callback(update, context,
                                    get_user_language(q.message.chat.id, getattr(q.from_user, "language_code", None)))
        return
    # Buttons from old menus still in users' chat history → new Daily High-Impact News panel
    if data == "subscribe":
        await subscribe_cmd(update, context)
        return
    if data == "unsubscribe":
        await unsubscribe_cmd(update, context)
        return
    if data in ("choose_time", "settime") or data.startswith("settime_"):
        if data.startswith("settime_"):
            _, h, m = data.split("_")
            set_brief_time(q.message.chat.id, f"{h}:{m}")
        await show_brief(update, context)
        return
    if data in ("currencies_done", "main_menu"):
        awaiting = str(context.user_data.get("awaiting") or "")
        if awaiting == channels.AWAIT_CHANNEL or awaiting.startswith("rem_"):
            context.user_data.pop("awaiting", None)
        await back_to_main_menu(update, context)
        return
    if data == "my_channel":
        await channels.show(update, context, get_user_language(q.message.chat.id))
        return
    if data in ("chan_remove", "chan_change"):
        await channels.on_callback(update, context, get_user_language(q.message.chat.id))
        return
    if data == "admin_menu":
        await admin_menu_callback(update, context)
        return
    if data == "admin_restartmsg":
        await admin_restartmsg_callback(update, context)
        return
    if data.startswith("ea:"):
        if not is_admin(q.message.chat.id):
            await q.answer("Admins only.", show_alert=True)
            return
        await ea_admin.handle_callback(update, context)
        return
    if data in ("admin_servers", "admin_switch"):
        await admin_servers_callback(update, context)
        return
    if data == "admin_add":
        await admin_add_menu_callback(update, context)
        return
    if data == "admin_delete":   # button from old panels
        await admin_servers_callback(update, context)
        return
    if data.startswith("admindelq_"):
        await admin_delete_ask_callback(update, context)
        return
    if data.startswith("adminuse_"):
        await admin_use_server_callback(update, context)
        return
    if data.startswith("admindel_"):
        await admin_delete_server_callback(update, context)
        return
    if data == "admin_backup":
        await admin_backup_callback(update, context)
        return
    if data == "admin_restore":
        await admin_restore_menu_callback(update, context)
        return
    if data == "admin_backups":
        await admin_backups_list_callback(update, context)
        return
    if data.startswith(("adminbk_", "adminbksend_", "adminbkrs_")):
        await admin_backup_item_callback(update, context)
        return
    if data.startswith("adminrs_"):
        await admin_restore_confirm_callback(update, context)
        return
    await q.answer()
    mapping = {"today": today, "tomorrow": tomorrow, "week": week}
    if data in mapping:
        fake_update = Update(update.update_id, message=q.message, callback_query=q)
        await mapping[data](fake_update, context)

async def today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    messages = {
        'fa': "در حال ارسال خبرهای امروز...",
        'en': "Fetching today's news..."
    }
    await update.effective_message.reply_text(messages[language])
    await fetch_and_send(update, ctx, "today", "Today's Economic News" if language == 'en' else "خبرهای اقتصادی امروز")

async def tomorrow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    messages = {
        'fa': "در حال ارسال خبرهای فردا...",
        'en': "Fetching tomorrow's news..."
    }
    await update.effective_message.reply_text(messages[language])
    await fetch_and_send(update, ctx, "tomorrow", "Tomorrow's Economic News" if language == 'en' else "خبرهای اقتصادی فردا")

async def week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    messages = {
        'fa': "در حال ارسال خبرهای هفته...",
        'en': "Fetching this week's news..."
    }
    await update.effective_message.reply_text(messages[language])
    await fetch_and_send(update, ctx, "weekly", "This Week's Economic News" if language == 'en' else "خبرهای اقتصادی این هفته")
    
IMPACT_LABEL = {
    'fa': {"High": "🔴 زیاد", "Medium": "🟠 متوسط", "Low": "🟡 کم"},
    'en': {"High": "🔴 High", "Medium": "🟠 Medium", "Low": "🟡 Low"},
}
CURRENCY_SCREEN = {
    'fa': "💱 <b>ارزها</b>\nارزهایی که می‌خوای دنبالشون کنی رو تیک بزن (چندتایی هم میشه).\n\n"
          "🎚 <b>اهمیت خبر</b>\nکدوم خبرها برات بیاد؟ پیش‌فرض فقط 🔴 مهم‌ها.",
    'en': "💱 <b>Currencies</b>\nTick the currencies you want to follow (pick as many as you like).\n\n"
          "🎚 <b>Impact</b>\nWhich news should I send? Default is 🔴 High only.",
}

def build_currency_keyboard(selected: list[str], language: str = 'en',
                            impacts: list[str] | None = None) -> InlineKeyboardMarkup:
    impacts = impacts or ["High"]
    all_currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNY"]
    kb = []
    row = []
    for i, cur in enumerate(all_currencies):
        is_on = "✅" if cur in selected else "☑️"
        row.append(InlineKeyboardButton(f"{is_on} {cur}", callback_data=f"togglecur_{cur}"))
        if (i + 1) % 3 == 0:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([
        InlineKeyboardButton(f"{'✅' if lvl in impacts else '☑️'} {IMPACT_LABEL[language][lvl]}",
                             callback_data=f"toggleimp_{lvl}")
        for lvl in IMPACTS
    ])
    save_button = {
        'fa': "✅ ذخیره و بازگشت",
        'en': "✅ Save and Return"
    }
    kb.append([InlineKeyboardButton(save_button[language], callback_data="currencies_done")])
    return InlineKeyboardMarkup(kb)

def get_user_impacts(chat_id: int) -> list[str]:
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT impacts FROM user_currencies WHERE chat_id = ?", (chat_id,)).fetchone()
        levels = [x for x in (row[0] or "").split(",") if x in IMPACTS] if row else []
        return levels or ["High"]
    except Exception as e:
        logger.error(f"Error in get_user_impacts for chat_id {chat_id}: {e}")
        return ["High"]

def set_user_impacts(chat_id: int, impacts: list[str]):
    value = ",".join(lvl for lvl in IMPACTS if lvl in impacts) or "High"
    with closing(_db()) as conn, conn:
        conn.execute(
            """INSERT INTO user_currencies (chat_id, currencies, impacts) VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET impacts = excluded.impacts""",
            (chat_id, ",".join(get_user_currencies(chat_id)), value))

async def toggle_impact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    level = q.data.split("_", 1)[1]
    if level not in IMPACTS:
        await q.answer()
        return
    impacts = get_user_impacts(cid)
    if level in impacts:
        if len(impacts) == 1:
            await q.answer("حداقل یکی باید روشن بمونه" if language == 'fa' else "Keep at least one on", show_alert=False)
            return
        impacts.remove(level)
    else:
        impacts.append(level)
    set_user_impacts(cid, impacts)
    await q.answer(IMPACT_LABEL[language][level] + (" ✓" if level in impacts else " ✕"))
    await safe_edit(q.message, CURRENCY_SCREEN[language],
                    build_currency_keyboard(get_user_currencies(cid), language, get_user_impacts(cid)))

def get_user_currencies(chat_id: int) -> list[str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT currencies FROM user_currencies WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        conn.close()
        return row[0].split(",") if row and row[0] else ["USD"]
    except:
        return ["USD"]

def set_user_currencies(chat_id: int, currencies: list[str]):
    cur_str = ",".join(sorted(set(currencies)))
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_currencies (chat_id, currencies)
        VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET currencies = excluded.currencies
        """,
        (chat_id, cur_str)
    )
    conn.commit()
    conn.close()

async def toggle_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    currency = q.data.split("_")[1]
    selected = get_user_currencies(cid)
    if currency in selected:
        selected.remove(currency)
    else:
        selected.append(currency)
    set_user_currencies(cid, selected)
    messages = {
        'fa': f"👌 {currency} {'حذف شد' if currency not in selected else 'اضافه شد'}",
        'en': f"👌 {currency} {'removed' if currency not in selected else 'added'}"
    }
    await q.answer(messages[language])
    await safe_edit(q.message, CURRENCY_SCREEN[language],
                    build_currency_keyboard(get_user_currencies(cid), language, get_user_impacts(cid)))

async def choose_currency_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    await q.answer()
    await safe_edit(q.message, CURRENCY_SCREEN[language],
                    build_currency_keyboard(get_user_currencies(cid), language, get_user_impacts(cid)))

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid, getattr(q.from_user, "language_code", None))
    await q.answer()
    await safe_edit(q.message, main_menu_text(language, cid, back=True), main_menu_keyboard(language, cid))

# تغییر در تابع notify_restart:
async def notify_restart(application):
    """ارسال پیام «بات دوباره آنلاین شد» به همه کاربران قبلی"""
    # اگر تنظیمات غیرفعال باشد، هیچ کاری نکن
    if not restart_notice_on():
        logger.info("Restart notification is disabled globally.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM users")
        users = cur.fetchall()
        conn.close()

        if not users:
            logger.info("No previous users found to notify on restart.")
            return

        restart_message_fa = (
            "✅ <b>بات دوباره آنلاین شد!</b>\n\n"
            "خوش اومدی دوباره 😊\n"
            "حالا می‌تونی مثل قبل از منوی اصلی استفاده کنی."
        )

        restart_message_en = (
            "✅ <b>Bot is back online!</b>\n\n"
            "Welcome back 😊\n"
            "You can use the main menu as before."
        )

        for (chat_id,) in users:
            try:
                language = get_user_language(chat_id)
                msg = restart_message_fa if language == 'fa' else restart_message_en
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                    reply_markup=menu_kb(language, chat_id),   # existing users get the 📊 / 📆 / ⏰ keyboard too
                )
                _mark_menu_kb(chat_id, language)
                await asyncio.sleep(0.3)  # جلوگیری از محدودیت سرعت
            except Exception as e:
                logger.warning(f"Could not send restart message to {chat_id}: {e}")

        logger.info(f"Restart notification sent to {len(users)} users.")

    except Exception as e:
        logger.error(f"Error in notify_restart: {e}")
        
async def post_init(application):
    await application.bot.set_my_commands(EN_COMMANDS)
    await application.bot.set_my_commands(FA_COMMANDS, language_code="fa")
    # Native Telegram Menu button (next to the input box) for ALL users, independent of /start
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await notify_restart(application)

def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is empty. Run: python bot_settings.py")
        sys.exit(1)
    ensure_db()
    load_api_base_from_db()  # use admin's saved server, if any
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)         # 3) ثبت post_init
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    # Admin-only: single /admin panel for switching the Flask server
    app.add_handler(CommandHandler("admin", admin_cmd))   # hidden, admin only (no button for it)
    app.add_handler(CommandHandler("myid", myid_cmd))     # hidden, needed once to find ADMIN_CHAT_ID
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(TypeHandler(Update, keyboard_refresh), group=1)   # ⌨️ new keyboard after KB_VERSION bump
    # Text replies: channel username for 📢 My channel, or the admin's reply when adding a server
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND & ~filters.Document.ALL, text_router))
    # Catches the backup file the admin uploads after tapping ♻️ Restore
    app.add_handler(MessageHandler(filters.Document.ALL, admin_document_input))
    app.job_queue.run_repeating(digest_loop, interval=60, first=0)
    app.job_queue.run_repeating(date_loop, interval=30, first=0)   # 30s + last_sent: never misses / never doubles
    app.job_queue.run_repeating(reminders_tick, interval=30, first=5)   # ⏰ due reminders
    print("🥵 bot is online!")
    app.run_polling()

if __name__ == "__main__":
    if cfg.RUN_BOT:
        main()
    else:
        print("RUN_BOT is false. Telegram bot will not start.")
