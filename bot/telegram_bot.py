import os
import sys
import signal
import asyncio
import datetime as dt
import requests
import sqlite3
import pathlib

# Make the project root importable (for bot_settings / bot package)
ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot_settings as cfg
from bot import backup_manager as bk
from bot import ea_admin
from bot import channels
from telegram.error import Forbidden, BadRequest

from datetime import datetime
import pytz
from collections import defaultdict
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction, ParseMode

FA_COMMANDS = [
    BotCommand("start", "—"),
    BotCommand("help",  "—"),
    BotCommand("language", "—"),
]

EN_COMMANDS = [
    BotCommand("start", "."),
    BotCommand("help",  "."),
    BotCommand("language", "."),
]

async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    cid = update.effective_chat.id
    language = get_user_language(cid)
    
    messages = {
        'fa': "لطفاً زبان خود را انتخاب کنید:",
        'en': "Please select your language:"
    }
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇷 فارسی", callback_data="setlang_fa"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en")
        ]
    ])
    
    await update.message.reply_text(messages[language], reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = q.data.split("_")[1]  # setlang_fa → fa
    set_user_language(cid, language)
    
    messages = {
        'fa': "✅ زبان به فارسی تنظیم شد! حالا می‌تونی از منوی اصلی استفاده کنی.",
        'en': "✅ Language set to English! Now you can use the main menu."
    }
    
    await q.message.edit_text(messages[language], reply_markup=default_keyboard(language), parse_mode=ParseMode.HTML)
    await q.answer()
    
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
def get_user_language(chat_id: int) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT language FROM subscribers WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else 'en'
    except Exception as e:
        logger.error(f"Error in get_user_language for chat_id {chat_id}: {e}")
        return 'en'

def set_user_language(chat_id: int, language: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO subscribers (chat_id, language)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET language = excluded.language
            """,
            (chat_id, language)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    
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
               language    TEXT DEFAULT 'en'
        );"""
    )

    # جدول ارزهای انتخابی کاربر
    cur.execute(
        """CREATE TABLE IF NOT EXISTS user_currencies (
               chat_id     INTEGER PRIMARY KEY,
               currencies  TEXT DEFAULT 'USD'
        );"""
    )

    # جدول جدید برای جلوگیری از تکرار اطلاع به ادمین
    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
               chat_id   INTEGER PRIMARY KEY,
               joined_at TEXT DEFAULT CURRENT_TIMESTAMP
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()

    # اطمینان از وجود ستون language در subscribers
    try:
        cur.execute("ALTER TABLE subscribers ADD COLUMN language TEXT DEFAULT 'en'")
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

def load_subs() -> dict[int, str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT chat_id, digest_time FROM subscribers")
        rows = cur.fetchall()
        conn.close()
        return {int(cid): digest for cid, digest in rows}
    except:
        return {}

def update_sub_time(chat_id: int, digest_time: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("UPDATE subscribers SET digest_time = ? WHERE chat_id = ?",
                    (digest_time, chat_id))
        conn.commit()
        conn.close()
    except:
        pass

def save_sub(chat_id: int, digest_time: str = "07:00"):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id, digest_time) VALUES (?, ?)",
            (int(chat_id), digest_time)
        )
        conn.commit()
        conn.close()
    except:
        pass

def remove_sub(chat_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
    except:
        pass

# ───────────────  Decor & Utils  ─────────────
def build_event_block(ev: dict) -> str:
    ny_tz = pytz.timezone("America/New_York")
    date_str = ev.get("Date", "")
    time_str = ev.get("Time", "—")
    currency = ev.get("Currency", "???")
    event_name = ev.get("Event", "—")
    prev = ev.get("Previous", "—")
    fcst = ev.get("Forecast", "—")
    act  = ev.get("Actual", "—")

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
        f"© {event_name}\n"
        f"⏱ {time_str} | {date_formatted}\n"
        f"📍 Prev: {prev} | Fcst: {fcst} | Act: {act}"
    )

async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, delay: float = 1.0):
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(delay)

def default_keyboard(language: str = 'en') -> InlineKeyboardMarkup:
    buttons = {
        'fa': [
            [InlineKeyboardButton("💱 انتخاب ارزها", callback_data="choose_currencies")],
            [
                InlineKeyboardButton("📅 امروز", callback_data="today"),
                InlineKeyboardButton("🚀 فردا", callback_data="tomorrow"),
                InlineKeyboardButton("🗓 هفته", callback_data="week"),
            ],
            [
                InlineKeyboardButton("📬 دریافت خودکار روزانه", callback_data="subscribe"),
                InlineKeyboardButton("❌ توقف پیام روزانه", callback_data="unsubscribe"),
            ],
            [
                InlineKeyboardButton("🕒 تنظیم ساعت دریافت", callback_data="choose_time"),
                InlineKeyboardButton("🌐 تغییر زبان", callback_data="change_language"),
            ],
            [InlineKeyboardButton("📢 ارسال به کانال من", callback_data="my_channel")],
        ],
        'en': [
            [InlineKeyboardButton("💱 Choose Currencies", callback_data="choose_currencies")],
            [
                InlineKeyboardButton("📅 Today", callback_data="today"),
                InlineKeyboardButton("🚀 Tomorrow", callback_data="tomorrow"),
                InlineKeyboardButton("🗓 Week", callback_data="week"),
            ],
            [
                InlineKeyboardButton("📬 Enable Daily Digest", callback_data="subscribe"),
                InlineKeyboardButton("❌ Stop Daily Digest", callback_data="unsubscribe"),
            ],
            [
                InlineKeyboardButton("🕒 Set Digest Time", callback_data="choose_time"),
                InlineKeyboardButton("🌐 Change Language", callback_data="change_language"),
            ],
            [InlineKeyboardButton("📢 Send to my channel", callback_data="my_channel")],
        ]
    }
    return InlineKeyboardMarkup(buttons[language])

def build_time_keyboard() -> InlineKeyboardMarkup:
    kb = []
    for base in range(0, 24, 3):
        row = []
        for h in range(base, base + 3):
            label = f"{h%24:02d}:30"
            row.append(
                InlineKeyboardButton(label, callback_data=f"settime_{h%24:02d}_30")
            )
        kb.append(row)
    return InlineKeyboardMarkup(kb)

# ───────────────  Core fetch  ─────────────
def get_filtered_events(endpoint: str, allowed_currencies: list[str]) -> list[dict]:
    try:
        response = requests.get(f"{API_BASE}/{endpoint}", timeout=10)
        response.raise_for_status()  # بررسی خطاهای HTTP
        data = response.json()
        return [ev for ev in data if ev.get("Currency") in allowed_currencies]
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
        currency = ev.get("Currency", "???")
        event_name = ev.get("Event", "—")
        time_str = ev.get("Time", "—")
        prev = ev.get("Previous", "—")
        fcst = ev.get("Forecast", "—")
        act = ev.get("Actual", "—")
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
            f"© {event_name}\n"
            f"⏱️ {time_str} | {date_str}\n"
            f"📍 Prev: {prev} | Fcst: {fcst} | Act: {act}\n"
        )
        grouped[currency][date_display].append(event_text)

    lines = [f"💫 {title}\n"]
    for currency in grouped:
        for day, ev_list in grouped[currency].items():
            if language == 'en':
                lines.append(f"📣 {day}\n")
            else:
                lines.append(f"📣 {day}")
            lines.extend(ev_list)
            lines.append("")

    return "\n".join(lines).strip()

async def fetch_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, endpoint: str, title: str):
    await send_typing(context, update.effective_chat.id, 0.8)
    cid = update.effective_chat.id
    language = get_user_language(cid)
    error_messages = {
        'fa': "😓 اوه! سرور جواب نداد؛ بعداً امتحان کن.",
        'en': "😓 Oops! Server didn't respond; try again later."
    }

    try:
        allowed = get_user_currencies(cid)
        events = get_filtered_events(endpoint, allowed)
    except Exception:
        await update.effective_message.reply_text(error_messages[language], parse_mode=ParseMode.HTML)
        return

    msg = format_message_clean(title, events, language)
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)

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

def build_admin_menu_text() -> str:
    backups = bk.list_backups()
    last = backups[0].name if backups else "none yet"
    return (
        f"⚙️ <b>Admin panel</b>\n\nActive server:\n<code>{API_BASE}</code>\n\n"
        f"💾 Last backup: <code>{last}</code>"
    )

def build_admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔀 Switch server", callback_data="admin_switch")],
        [InlineKeyboardButton("➕ Add server", callback_data="admin_add")],
        [InlineKeyboardButton("🗑 Delete server", callback_data="admin_delete")],
        [
            InlineKeyboardButton("💾 Full backup", callback_data="admin_backup"),
            InlineKeyboardButton("♻️ Restore", callback_data="admin_restore"),
        ],
        [InlineKeyboardButton("🗂 Saved backups", callback_data="admin_backups")],
    ] + ([[InlineKeyboardButton("📦 EA versions (site downloads)", callback_data="ea:list")]]
          if ea_admin.available() else []))

def build_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]])

def build_switch_keyboard() -> InlineKeyboardMarkup:
    servers = list_api_servers()
    kb = []
    for name in servers:
        marker = "✅ " if servers[name] == API_BASE else "▫️ "
        kb.append([InlineKeyboardButton(f"{marker}{name}", callback_data=f"adminuse_{name}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

def build_delete_keyboard() -> InlineKeyboardMarkup:
    servers = list_api_servers()
    kb = [[InlineKeyboardButton(f"🗑 {name}", callback_data=f"admindel_{name}")] for name in servers]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])
    return InlineKeyboardMarkup(kb)

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /admin — opens the server-management panel (buttons only, no other commands needed)."""
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
    await q.message.edit_text(
        build_admin_menu_text(), reply_markup=build_admin_menu_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_switch_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    servers = list_api_servers()
    if not servers:
        await q.message.edit_text(
            f"{build_admin_menu_text()}\n\nNo saved servers yet — use ➕ Add server first.",
            reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
        )
        return
    await q.message.edit_text(
        f"{build_admin_menu_text()}\n\nTap a server to switch to it:",
        reply_markup=build_switch_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_use_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global API_BASE
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    name = q.data.split("_", 1)[1]
    servers = list_api_servers()
    if name not in servers:
        await q.answer("That server no longer exists.", show_alert=True)
        return
    API_BASE = servers[name]
    set_config("api_base_url", API_BASE)
    await q.answer(f"Switched to {name}")
    await q.message.edit_text(
        f"{build_admin_menu_text()}\n\nTap a server to switch to it:",
        reply_markup=build_switch_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_delete_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    servers = list_api_servers()
    if not servers:
        await q.message.edit_text(
            f"{build_admin_menu_text()}\n\nNo saved servers to delete.",
            reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
        )
        return
    await q.message.edit_text(
        f"{build_admin_menu_text()}\n\nTap a server to delete it:",
        reply_markup=build_delete_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_delete_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    name = q.data.split("_", 1)[1]
    deleted = delete_api_server(name)
    await q.answer(f"Deleted {name}" if deleted else "Not found")
    servers = list_api_servers()
    if not servers:
        await q.message.edit_text(
            f"{build_admin_menu_text()}\n\nNo saved servers left.",
            reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
        )
        return
    await q.message.edit_text(
        f"{build_admin_menu_text()}\n\nTap a server to delete it:",
        reply_markup=build_delete_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_add_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.message.chat.id):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    context.user_data["awaiting"] = ADMIN_AWAIT_ADD_SERVER
    await q.message.edit_text(
        f"{build_admin_menu_text()}\n\n"
        "Send the new server as a single message:\n<code>name https://url</code>\n\n"
        "Example:\n<code>iran https://iran.heysolo.ir/api/forex</code>",
        reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
    )

async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches the admin's reply after tapping ➕ Add server in the /admin panel."""
    cid = update.effective_chat.id
    if not is_admin(cid) or context.user_data.get("awaiting") != ADMIN_AWAIT_ADD_SERVER:
        return
    context.user_data.pop("awaiting", None)

    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) != 2 or not (parts[1].startswith("http://") or parts[1].startswith("https://")):
        await update.message.reply_text(
            "❌ Format not recognized. Open /admin again and send:\n<code>name https://url</code>",
            parse_mode=ParseMode.HTML
        )
        return

    name, url = parts[0], parts[1].rstrip("/")
    save_api_server(name, url)
    await update.message.reply_text(
        f"✅ Saved server «{name}»:\n<code>{url}</code>",
        reply_markup=build_admin_menu_keyboard(), parse_mode=ParseMode.HTML
    )

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
    """💾 Full backup: snapshot DB + .env into a zip and send it to the admin."""
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
        await q.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        logger.exception("Backup failed")
        await q.message.reply_text(f"❌ Backup failed: {e}")
        return
    caption = (
        "✅ <b>Full backup</b>\n"
        f"<code>{path.name}</code>\n\n{_fmt_counts(counts)}\n\n"
        + (f"📦 EA builds included: {len(bk._build_files())}\n" if bk._build_files() else "") +
        "⚠️ Contains your bot token (.env). Keep it private.\n"
        "To restore: /admin → ♻️ Restore → send this file."
    )
    try:
        await _send_backup_file(context, q.message.chat.id, path, caption)
    except Exception as e:
        logger.exception("Sending backup failed")
        await q.message.reply_text(f"⚠️ Backup saved on server as <code>{path.name}</code> but sending failed: {e}",
                                   parse_mode=ParseMode.HTML)
    await q.message.reply_text(build_admin_menu_text(), reply_markup=build_admin_menu_keyboard(),
                               parse_mode=ParseMode.HTML)

async def admin_restore_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """♻️ Restore: wait for the admin to upload a backup file."""
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    _clear_pending_restore(context)
    context.user_data["awaiting"] = ADMIN_AWAIT_RESTORE_FILE
    await q.message.edit_text(
        "♻️ <b>Restore</b>\n\n"
        "Send the backup <b>.zip</b> file here (or an old <code>forexbot.db</code>).\n\n"
        "Nothing changes until you confirm. A safety backup of the current data is "
        "taken automatically before restoring.",
        reply_markup=build_back_keyboard(), parse_mode=ParseMode.HTML
    )

async def _show_restore_preview(message, context: ContextTypes.DEFAULT_TYPE, plan: "bk.RestorePlan"):
    context.user_data["pending_restore"] = plan
    created = plan.manifest.get("created_at", "unknown")
    kind = "raw database file" if plan.manifest.get("label") == "raw-db" else "full backup"
    rows = [[InlineKeyboardButton("✅ Restore data", callback_data="adminrs_data")]]
    if plan.has_settings:
        rows.append([InlineKeyboardButton("✅ Data + settings (.env, restarts bot)", callback_data="adminrs_all")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="adminrs_cancel")])
    await message.reply_text(
        "🔎 <b>Backup checked, looks good</b>\n\n"
        f"Type: {kind}\nCreated: <code>{created}</code>\n"
        f"Settings included: {'yes' if plan.has_settings else 'no'}\n"
        f"EA builds included: {len(plan.builds)}\n\n"
        f"{_fmt_counts(plan.counts)}\n\n"
        "⚠️ Restoring <b>replaces</b> all current users, subscriptions and servers.",
        reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML
    )

async def admin_document_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the backup file after tapping ♻️ Restore, or EA builds (📦 EA versions)."""
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
        await update.message.reply_text("❌ File is larger than 20 MB, Telegram bots can't download it.")
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
        await update.message.reply_text(f"❌ {e}\n\nOpen /admin → ♻️ Restore to try again.")
        return
    except Exception as e:
        logger.exception("Restore upload failed")
        await update.message.reply_text(f"❌ Couldn't read that file: {e}")
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
        await q.answer("This restore expired. Start again from ♻️ Restore.", show_alert=True)
        return
    context.user_data.pop("pending_restore", None)
    await q.answer("Restoring…")
    await q.message.edit_text("⏳ Restoring, hang on…")
    include_settings = action == "all"
    try:
        safety, settings_changed = await asyncio.to_thread(bk.apply_restore, plan, include_settings)
        ensure_db()              # add any tables/columns the old backup didn't have
        load_api_base_from_db()  # pick up the restored active server
        counts = await asyncio.to_thread(bk._table_counts, cfg.DB_PATH)
    except bk.BackupError as e:
        plan.cleanup()
        await q.message.edit_text(f"❌ Restore failed: {e}\nYour current data was not changed.")
        return
    except Exception as e:
        plan.cleanup()
        logger.exception("Restore failed")
        await q.message.edit_text(
            f"❌ Restore failed: {e}\n\nIf anything looks off, use 🗂 Saved backups → the "
            "latest <i>pre-restore</i> backup to roll back.", parse_mode=ParseMode.HTML)
        return

    text = (
        "✅ <b>Restore complete</b>\n\n"
        + (f"📦 EA builds restored: {len(plan.builds)}\n\n" if plan.builds else "") +
        f"{_fmt_counts(counts)}\n\n"
        f"Active server: <code>{API_BASE}</code>\n"
    )
    if safety:
        text += f"\n🛟 Previous data saved as <code>{safety.name}</code> (🗂 Saved backups)."
    if include_settings and settings_changed:
        text += "\n\n🔄 Settings restored, restarting the bot in a few seconds…"
        await q.message.edit_text(text, parse_mode=ParseMode.HTML)
        context.job_queue.run_once(_restart_job, when=3)
        return
    await q.message.edit_text(text, reply_markup=build_admin_menu_keyboard(), parse_mode=ParseMode.HTML)

async def admin_backups_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🗂 Saved backups: backups stored on the server (manual + pre-restore)."""
    q = update.callback_query
    if not _admin_only(q):
        await q.answer("Admins only.", show_alert=True)
        return
    await q.answer()
    backups = bk.list_backups()
    if not backups:
        await q.message.edit_text("🗂 No backups on the server yet. Tap 💾 Full backup first.",
                                  reply_markup=build_back_keyboard())
        return
    kb = [[InlineKeyboardButton(f"📦 {p.name[7:-4]}", callback_data=f"adminbk_{p.name}")] for p in backups]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_menu")])
    await q.message.edit_text(
        f"🗂 <b>Saved backups</b> (keeping last {cfg.BACKUP_KEEP})\nTap one to send or restore it:",
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
        await _send_backup_file(context, q.message.chat.id, path, f"📦 <code>{path.name}</code>")
        return
    if prefix == "adminbkrs":
        await q.answer()
        _clear_pending_restore(context)
        try:
            plan = await asyncio.to_thread(bk.prepare_restore, path)
        except bk.BackupError as e:
            await q.message.reply_text(f"❌ {e}")
            return
        await _show_restore_preview(q.message, context, plan)
        return
    # adminbk_<name>: details
    await q.answer()
    await q.message.edit_text(
        f"📦 <code>{bk.describe(path)}</code>",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📤 Send to me", callback_data=f"adminbksend_{path.name}"),
                InlineKeyboardButton("♻️ Restore this", callback_data=f"adminbkrs_{path.name}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_backups")],
        ]),
        parse_mode=ParseMode.HTML
    )

def _subscribe_and_get_time(chat_id: int) -> str:
    save_sub(chat_id)                       # no-op if already subscribed
    return load_subs().get(chat_id, "07:00")

async def channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channels.on_message(update, context, get_user_language(update.effective_chat.id),
                              _subscribe_and_get_time)

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes plain text / forwarded posts to whichever flow is waiting for input."""
    if update.message is None or update.effective_chat.type != "private":
        return
    if context.user_data.get("awaiting") == channels.AWAIT_CHANNEL:
        await channel_input(update, context)
        return
    if update.message.text:
        await admin_text_input(update, context)

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns the chat id — useful for setting ADMIN_CHAT_ID."""
    await update.message.reply_text(f"🆔 Chat ID: <code>{update.effective_chat.id}</code>", parse_mode=ParseMode.HTML)

# ───────────────  Commands  ─────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await send_typing(context, cid)

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
        await notify_admin(context, cid, {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name
        })

    conn.close()

    # ---------- بررسی زبان کاربر ----------
    language = get_user_language(cid)

    if not language or language not in ['fa', 'en']:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇮🇷 فارسی", callback_data="setlang_fa"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en")
            ]
        ])
        # تغییر: ابتدا انگلیسی نمایش داده شود
        await update.message.reply_text(
            "Please select your language:\nلطفاً زبان خود را انتخاب کنید:",
            reply_markup=keyboard
        )
        return

    # ---------- نمایش پیام خوش‌آمدگویی ----------
    messages = {
        'fa': {
            'welcome': "<b>💎 خوش اومدی به خوشگل‌ترین ربات اخبار اقتصادی.</b>\n\n"
                       "من می‌تونم اخبار مهم اقتصادی ارزهایی که تو انتخاب می‌کنی، برات بفرستم.\n\n",
            'sub_status': "📬 دریافت خودکار روشنه؛ ساعت <b>{time} NYT</b> برات می‌فرستم 😘",
            'no_sub': "📪 دریافت خودکار فعلاً خاموشه — می‌خوای روشنش کنی؟"
        },
        'en': {
            'welcome': "<b>💎 Welcome to the beautiful economic news bot!</b>\n\n"
                       "I can send you High-Impact news for the currencies you choose.\n\n",
            'sub_status': "📬 Auto-delivery is on; I’ll send it at <b>{time} NYT</b> 😘",
            'no_sub': "📪 Auto-delivery is off — want to turn it on?"
        }
    }

    subs_map = load_subs()
    status = messages[language]['sub_status'].format(time=subs_map.get(cid, '07:00')) if cid in subs_map else messages[language]['no_sub']
    text = messages[language]['welcome'] + status

    await update.message.reply_text(text, reply_markup=default_keyboard(language), parse_mode=ParseMode.HTML)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing(context, update.effective_chat.id)
    cid = update.effective_chat.id
    language = get_user_language(cid)
    
    messages = {
        'fa': (
            "<b>📘 راهنمای خوشگل‌ترین ربات اقتصادی دنیا</b>\n"
            "ببین چیا بلدم:\n\n"
            "• /today — خبرهای امروز\n"
            "• /tomorrow — خبرهای فردا\n"
            "• /week — کل هفته\n"
            "• /subscribe — فعال‌سازی پیام روزانه\n"
            "• /unsubscribe — لغو پیام روزانه\n"
            "• /settime HH:MM — تغییر ساعت دریافت\n"
            "• /language — تغییر زبان ربات\n"
            "• 📢 ارسال به کانال من — خبرهای روزانه توی کانال خودت\n\n"
            "یا راحت از دکمه‌های پایین استفاده کن 💅"
        ),
        'en': (
            "<b>📘 Guide to the beautiful Economic News Bot</b>\n"
            "Check out what I can do:\n\n"
            "• /today — Today's news\n"
            "• /tomorrow — Tomorrow's news\n"
            "• /week — This week's news\n"
            "• /subscribe — Enable daily digest\n"
            "• /unsubscribe — Disable daily digest\n"
            "• /settime HH:MM — Change digest time\n"
            "• /language — Change the bot's language\n"
            "• 📢 Send to my channel — get the daily digest in your own channel\n\n"
            "Or just use the buttons below 💅"
        )
    }
    
    await update.message.reply_text(messages[language], reply_markup=default_keyboard(language), parse_mode=ParseMode.HTML)

async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    messages = {
        'fa': {
            'already_sub': "قبلاً عضو بودی، خوشگله 😘",
            'success': "✅ دریافت خودکار فعال شد! 🙋\nزمان پیش‌فرض <b>۰۷:۰۰ صبح نیویورک</b>ه.\nبا «🥒 تنظیم ساعت» هر موقع خواستی عوضش کن 😈"
        },
        'en': {
            'already_sub': "You're already subscribed, cutie 😘",
            'success': "✅ Auto-delivery activated! 🙋\nDefault time is <b>07:00 AM NYT</b>.\nChange it anytime with «🥒 Set Time» 😈"
        }
    }
    subs = load_subs()
    if cid in subs:
        await update.message.reply_text(messages[language]['already_sub'], parse_mode=ParseMode.HTML)
        return
    save_sub(cid)
    await update.message.reply_text(messages[language]['success'], parse_mode=ParseMode.HTML)

async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    messages = {
        'fa': {
            'not_subscribed': "هم‌اکنون غیرفعاله 🤔",
            'success': "❌ دریافت خودکار غیرفعال شد."
        },
        'en': {
            'not_subscribed': "Auto-delivery is already off 🤔",
            'success': "❌ Auto-delivery has been disabled."
        }
    }
    subs = load_subs()
    if cid not in subs:
        await update.message.reply_text(messages[language]['not_subscribed'], parse_mode=ParseMode.HTML)
        return
    remove_sub(cid)
    await update.message.reply_text(messages[language]['success'], parse_mode=ParseMode.HTML)

async def choose_time_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid)
    messages = {
        'fa': "⏰ لطفاً ساعت دلخواه برای دریافت پیام روزانه را انتخاب کن (UTC):",
        'en': "⏰ Please select your preferred time for daily digest (UTC):"
    }
    await q.answer()
    await q.message.edit_text(messages[language], reply_markup=build_time_keyboard())

async def set_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, hour: str, minute: str):
    cid = update.effective_chat.id
    language = get_user_language(cid)
    nyt_time = f"{hour}:{minute}"
    subs_map = load_subs()
    if cid not in subs_map:
        save_sub(cid, nyt_time)
    else:
        update_sub_time(cid, nyt_time)

    messages = {
        'fa': f"✅ زمان دریافت روزانه روی {nyt_time} NYT تنظیم شد!",
        'en': f"✅ Daily digest time set to {nyt_time} NYT!"
    }
    await update.callback_query.edit_message_text(messages[language])

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
            events = get_filtered_events("today", allowed)
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
            for text in texts:
                try:
                    await context.bot.send_message(target, text, parse_mode=ParseMode.HTML)
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
                InlineKeyboardButton("🇮🇷 فارسی", callback_data="setlang_fa"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en")
            ]
        ])
        await q.message.edit_text(messages[language], reply_markup=keyboard)
        await q.answer()
        return
    if data == "choose_currencies":
        await choose_currency_keyboard(update, context)
        return
    if data.startswith("togglecur_"):
        await toggle_currency(update, context)
        return
    if data == "currencies_done":
        if context.user_data.get("awaiting") == channels.AWAIT_CHANNEL:
            context.user_data.pop("awaiting", None)
        await back_to_main_menu(update, context)
        return
    if data == "my_channel":
        await channels.show(update, context, get_user_language(q.message.chat.id))
        return
    if data in ("chan_remove", "chan_change"):
        await channels.on_callback(update, context, get_user_language(q.message.chat.id))
        return
    if data == "choose_time":
        await choose_time_keyboard(update, context)
        return
    if data.startswith("settime_"):
        _, h, m = data.split("_")
        await set_time_handler(update, context, h, m)
        return
    if data == "admin_menu":
        await admin_menu_callback(update, context)
        return
    if data.startswith("ea:"):
        if not is_admin(q.message.chat.id):
            await q.answer("Admins only.", show_alert=True)
            return
        await ea_admin.handle_callback(update, context)
        return
    if data == "admin_switch":
        await admin_switch_menu_callback(update, context)
        return
    if data == "admin_add":
        await admin_add_menu_callback(update, context)
        return
    if data == "admin_delete":
        await admin_delete_menu_callback(update, context)
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
    mapping = {
        "today": today, "tomorrow": tomorrow, "week": week,
        "subscribe": subscribe_cmd, "unsubscribe": unsubscribe_cmd,
    }
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
    
def build_currency_keyboard(selected: list[str], language: str = 'en') -> InlineKeyboardMarkup:
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
    save_button = {
        'fa': "✅ ذخیره و بازگشت",
        'en': "✅ Save and Return"
    }
    kb.append([InlineKeyboardButton(save_button[language], callback_data="currencies_done")])
    return InlineKeyboardMarkup(kb)

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
    language = get_user_language(cid)
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
    
    currency_messages = {
        'fa': "💱 لطفاً ارزهایی که می‌خوای دنبال کنی رو انتخاب کن (چندتایی هم می‌تونی تیک بزن):",
        'en': "💱 Please select the currencies you want to follow (you can choose multiple):"
    }
    await q.message.edit_text(currency_messages[language], reply_markup=build_currency_keyboard(selected, language))

async def choose_currency_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid)
    messages = {
        'fa': "💱 لطفاً ارزهایی که می‌خوای دنبال کنی رو انتخاب کن (چندتایی هم می‌تونی تیک بزن):",
        'en': "💱 Please select the currencies you want to follow (you can choose multiple):"
    }
    selected = get_user_currencies(cid)
    await q.message.edit_text(messages[language], reply_markup=build_currency_keyboard(selected, language))
    await q.answer()

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cid = q.message.chat.id
    language = get_user_language(cid)
    subs_map = load_subs()
    
    messages = {
        'fa': {
            'welcome': "<b>💎 برگشتی به منوی اصلی خوشگل‌ترین ربات اخبار اقتصادی.</b>\n\n"
                       "من می‌تونم اخبار مهم اقتصادی رو فقط ارزهایی که تو انتخاب می‌کنی، برات بفرستم.\n\n",
            'sub_status': "📬 دریافت خودکار روشنه؛ ساعت <b>{time} NYT</b> برات می‌فرستم 😘",
            'no_sub': "📪 دریافت خودکار فعلاً خاموشه — می‌خوای روشنش کنی؟"
        },
        'en': {
            'welcome': "<b>💎 Back to the main menu of the beautiful economic news bot!</b>\n\n"
                       "I can send you High-Impact news for the currencies you choose.\n\n",
            'sub_status': "📬 Auto-delivery is on; I’ll send it at <b>{time} NYT</b> 😘",
            'no_sub': "📪 Auto-delivery is off — want to turn it on?"
        }
    }
    
    status = messages[language]['sub_status'].format(time=subs_map.get(cid, '07:00')) if cid in subs_map else messages[language]['no_sub']
    text = messages[language]['welcome'] + status

    await q.message.edit_text(text, reply_markup=default_keyboard(language), parse_mode=ParseMode.HTML)
    await q.answer()

# تغییر در تابع notify_restart:
async def notify_restart(application):
    """ارسال پیام «بات دوباره آنلاین شد» به همه کاربران قبلی"""
    # اگر تنظیمات غیرفعال باشد، هیچ کاری نکن
    if not SEND_RESTART_MSG:
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
                    parse_mode=ParseMode.HTML
                )
                await asyncio.sleep(0.3)  # جلوگیری از محدودیت سرعت
            except Exception as e:
                logger.warning(f"Could not send restart message to {chat_id}: {e}")

        logger.info(f"Restart notification sent to {len(users)} users.")

    except Exception as e:
        logger.error(f"Error in notify_restart: {e}")
        
async def post_init(application):
    await application.bot.set_my_commands(EN_COMMANDS)
    await application.bot.set_my_commands(FA_COMMANDS, language_code="fa")
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
    app.add_handler(CommandHandler("language", language_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("week", week))
    # Admin-only: single /admin panel for switching the Flask server
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CallbackQueryHandler(button_router))
    # Text replies: channel username for 📢 My channel, or the admin's reply when adding a server
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND & ~filters.Document.ALL, text_router))
    # Catches the backup file the admin uploads after tapping ♻️ Restore
    app.add_handler(MessageHandler(filters.Document.ALL, admin_document_input))
    app.job_queue.run_repeating(digest_loop, interval=60, first=0)
    print("🥵 bot is online!")
    app.run_polling()

if __name__ == "__main__":
    if cfg.RUN_BOT:
        main()
    else:
        print("RUN_BOT is false. Telegram bot will not start.")
