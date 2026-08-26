import os
import asyncio
import datetime as dt
import requests
import sqlite3
import pathlib

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
        logging.FileHandler("bot.log"),  # ذخیره لاگ در فایل  
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
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:45869/api/forex")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
BASE_DIR   = pathlib.Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "forexbot.db"
SEND_RESTART_MSG = os.getenv("SEND_RESTART_MSG", "true").lower() == "true"

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
# ───────────────  Admin: switch Flask server  ─────────────
def build_servers_keyboard() -> InlineKeyboardMarkup:
    servers = list_api_servers()
    kb = []
    for name in servers:
        marker = "✅ " if servers[name] == API_BASE else "▫️ "
        kb.append([InlineKeyboardButton(f"{marker}{name}", callback_data=f"useserver_{name}")])
    return InlineKeyboardMarkup(kb) if kb else None

async def setapi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /setapi <url_or_saved_name> — switch the active Flask server."""
    global API_BASE
    cid = update.effective_chat.id
    if not is_admin(cid):
        return

    if not context.args:
        await update.message.reply_text(
            "استفاده:\n"
            "<code>/setapi https://iran.heysolo.ir/api/forex</code>\n"
            "یا اسم یه سرور ذخیره‌شده:\n"
            "<code>/setapi iran</code>\n\n"
            f"آدرس فعلی:\n<code>{API_BASE}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    arg = context.args[0].strip()
    servers = list_api_servers()

    if arg in servers:
        new_url = servers[arg]
    elif arg.startswith("http://") or arg.startswith("https://"):
        new_url = arg.rstrip("/")
    else:
        await update.message.reply_text(
            "❌ ورودی معتبر نیست. یا یه URL کامل با http(s):// بده، یا اسم یه سرور ذخیره‌شده با /servers ببین."
        )
        return

    API_BASE = new_url
    set_config("api_base_url", new_url)
    await update.message.reply_text(
        f"✅ سرور Flask فعال عوض شد به:\n<code>{new_url}</code>\n\n"
        "این تغییر همین الان اعمال شد و بعد از ری‌استارت ربات هم باقی می‌مونه.",
        parse_mode=ParseMode.HTML
    )

async def addserver_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /addserver <name> <url> — save a Flask server under a name."""
    cid = update.effective_chat.id
    if not is_admin(cid):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "استفاده:\n<code>/addserver iran https://iran.heysolo.ir/api/forex</code>",
            parse_mode=ParseMode.HTML
        )
        return

    name = context.args[0].strip()
    url = context.args[1].strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ آدرس باید با http:// یا https:// شروع بشه.")
        return

    save_api_server(name, url)
    await update.message.reply_text(
        f"✅ سرور «{name}» ذخیره شد:\n<code>{url}</code>\n\n"
        "برای فعال کردنش: <code>/setapi " + name + "</code> یا از /servers استفاده کن.",
        parse_mode=ParseMode.HTML
    )

async def delserver_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /delserver <name> — remove a saved server."""
    cid = update.effective_chat.id
    if not is_admin(cid):
        return

    if not context.args:
        await update.message.reply_text("استفاده: <code>/delserver iran</code>", parse_mode=ParseMode.HTML)
        return

    name = context.args[0].strip()
    if delete_api_server(name):
        await update.message.reply_text(f"🗑 سرور «{name}» حذف شد.")
    else:
        await update.message.reply_text(f"❌ سروری با اسم «{name}» پیدا نشد.")

async def servers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /servers — list saved servers with quick-switch buttons."""
    cid = update.effective_chat.id
    if not is_admin(cid):
        return

    servers = list_api_servers()
    text = f"📡 سرور فعال فعلی:\n<code>{API_BASE}</code>\n\n"
    if not servers:
        text += (
            "هنوز سروری ذخیره نکردی. با این دستور اضافه کن:\n"
            "<code>/addserver iran https://iran.heysolo.ir/api/forex</code>"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    text += "سرورهای ذخیره‌شده (برای سوییچ روش بزن):"
    await update.message.reply_text(text, reply_markup=build_servers_keyboard(), parse_mode=ParseMode.HTML)

async def use_server_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline button handler for quick server switching."""
    global API_BASE
    q = update.callback_query
    cid = q.message.chat.id
    if not is_admin(cid):
        await q.answer("فقط ادمین می‌تونه این کارو بکنه.", show_alert=True)
        return

    name = q.data.split("_", 1)[1]
    servers = list_api_servers()
    if name not in servers:
        await q.answer("این سرور دیگه وجود نداره.", show_alert=True)
        return

    API_BASE = servers[name]
    set_config("api_base_url", API_BASE)
    await q.answer(f"✅ سوییچ شد به {name}")
    await q.message.edit_text(
        f"📡 سرور فعال فعلی:\n<code>{API_BASE}</code>\n\nسرورهای ذخیره‌شده (برای سوییچ روش بزن):",
        reply_markup=build_servers_keyboard(),
        parse_mode=ParseMode.HTML
    )

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """چت‌آیدی رو برمی‌گردونه؛ برای ست کردن ADMIN_CHAT_ID توی .env مفیده."""
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
            "• /language — تغییر زبان ربات\n\n"
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
            "• /language — Change the bot's language\n\n"
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
                    'prefix': "💌 این پیام به‌خاطر فعال بودن دریافت خودکار برات ارسال شده.\n\n",
                    'title': "{cur} — 📅 خبرهای امروز"
                },
                'en': {
                    'no_news': "😴 No news today.",
                    'prefix': "💌 This message is sent because auto-delivery is enabled.\n\n",
                    'title': "{cur} — 📅 Today's News"
                }
            }
            if not grouped_events:
                await context.bot.send_message(cid, messages[language]['no_news'], parse_mode=ParseMode.HTML)
                continue
            for cur, ev_list in grouped_events.items():
                msg = (
                    messages[language]['prefix'] +
                    format_message_clean(messages[language]['title'].format(cur=cur), ev_list, language)
                )
                await context.bot.send_message(cid, msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            pass
        
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
        await back_to_main_menu(update, context)
        return
    if data == "choose_time":
        await choose_time_keyboard(update, context)
        return
    if data.startswith("settime_"):
        _, h, m = data.split("_")
        await set_time_handler(update, context, h, m)
        return
    if data.startswith("useserver_"):
        await use_server_callback(update, context)
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
    # Admin-only commands for switching the Flask server
    app.add_handler(CommandHandler("setapi", setapi_cmd))
    app.add_handler(CommandHandler("addserver", addserver_cmd))
    app.add_handler(CommandHandler("delserver", delserver_cmd))
    app.add_handler(CommandHandler("servers", servers_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CallbackQueryHandler(button_router))
    app.job_queue.run_repeating(digest_loop, interval=60, first=0)
    print("🥵 bot is online!")
    app.run_polling()

if __name__ == "__main__":
    run_bot = os.getenv("RUN_BOT", "false").lower() == "true"
    if run_bot:
        main()
    else:
        print("RUN_BOT is false. Telegram bot will not start.")
