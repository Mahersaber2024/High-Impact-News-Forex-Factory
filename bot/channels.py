"""
📢 "Send to my channel": a user connects their own channel and the daily digest is posted there
instead of in the private chat. The bot must be an admin of the channel (Post Messages).
"""
from __future__ import annotations

import sqlite3

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Update
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

import bot_settings as cfg

AWAIT_CHANNEL = "set_channel"
DEFAULT_BOT_USERNAME = "ForexFactoryN_Bot"
ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


# ───────────────  DB  ────────────────
def ensure_table():
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_channels (
               chat_id    INTEGER PRIMARY KEY,
               channel_id INTEGER NOT NULL,
               title      TEXT,
               username   TEXT
        );"""
    )
    conn.commit()
    conn.close()


def get_channel(chat_id: int) -> dict | None:
    conn = sqlite3.connect(cfg.DB_PATH)
    row = conn.execute("SELECT channel_id, title, username FROM user_channels WHERE chat_id = ?",
                       (chat_id,)).fetchone()
    conn.close()
    return {"id": row[0], "title": row[1], "username": row[2]} if row else None


def set_channel(chat_id: int, channel_id: int, title: str, username: str | None):
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.execute(
        """INSERT INTO user_channels (chat_id, channel_id, title, username) VALUES (?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET channel_id = excluded.channel_id,
               title = excluded.title, username = excluded.username""",
        (chat_id, channel_id, title, username))
    conn.commit()
    conn.close()


def remove_channel(chat_id: int):
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.execute("DELETE FROM user_channels WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def label(ch: dict) -> str:
    return f"@{ch['username']}" if ch.get("username") else (ch.get("title") or str(ch["id"]))


# ───────────────  texts  ────────────────
def _bot_name(ctx) -> str:
    return "@" + (getattr(ctx.bot, "username", None) or DEFAULT_BOT_USERNAME)


T = {
    "fa": {
        "intro": ("📢 <b>ارسال خبرها به کانال خودت</b>\n\n"
                  "۱) ربات {bot} رو به کانالت اضافه کن و <b>ادمین</b> کن (دسترسی «ارسال پیام» لازمه).\n"
                  "۲) بعد آیدی کانال رو بفرست، مثلاً <code>@mychannel</code>\n"
                  "   یا اگه کانال خصوصیه، یه پیام از کانال رو برام فوروارد کن.\n\n"
                  "از اون به بعد خبرهای روزانه (با همون ارزها و ساعتی که تنظیم کردی) توی کانالت ارسال میشه."),
        "current": "📢 کانال فعلی: <b>{ch}</b>\nخبرهای روزانه اونجا ارسال میشه.",
        "change": "🔄 تغییر کانال", "remove": "❌ قطع اتصال کانال", "cancel": "🔙 بازگشت",
        "not_found": "❌ این کانال رو پیدا نکردم. مطمئن شو {bot} توی کانال ادمینه و آیدی رو درست فرستادی.",
        "not_channel": "❌ این یه کانال نیست. آیدی کانال (مثل @mychannel) رو بفرست.",
        "bot_not_admin": "❌ ربات {bot} هنوز ادمین کانال نیست. اول ادمینش کن (با دسترسی ارسال پیام)، بعد دوباره بفرست.",
        "bot_no_post": "❌ ربات ادمینه ولی دسترسی «ارسال پیام» نداره. این دسترسی رو روشن کن و دوباره بفرست.",
        "user_not_admin": "❌ فقط ادمین‌های همون کانال می‌تونن وصلش کنن.",
        "done": "✅ کانال <b>{ch}</b> وصل شد! خبرهای روزانه ساعت <b>{time} NYT</b> اونجا ارسال میشه.",
        "removed": "✅ کانال جدا شد. خبرهای روزانه دوباره همین‌جا برات میاد.",
        "send_failed": "⚠️ نتونستم توی کانال <b>{ch}</b> پست بذارم (احتمالاً ربات از کانال حذف شده یا ادمین نیست). "
                       "کانال جدا شد و خبرها از این به بعد همین‌جا میاد. برای وصل دوباره از منو «📢 کانال من» رو بزن.",
    },
    "en": {
        "intro": ("📢 <b>Get the news in your own channel</b>\n\n"
                  "1) Add {bot} to your channel and make it an <b>admin</b> (it needs “Post messages”).\n"
                  "2) Then send the channel username here, e.g. <code>@mychannel</code>\n"
                  "   or, for a private channel, forward any message from the channel to me.\n\n"
                  "From then on the daily digest (same currencies and time you set) is posted in your channel."),
        "current": "📢 Current channel: <b>{ch}</b>\nThe daily digest is posted there.",
        "change": "🔄 Change channel", "remove": "❌ Disconnect channel", "cancel": "🔙 Back",
        "not_found": "❌ I can't find that channel. Make sure {bot} is an admin there and the username is right.",
        "not_channel": "❌ That's not a channel. Send the channel username, like @mychannel.",
        "bot_not_admin": "❌ {bot} isn't an admin of that channel yet. Make it admin (with Post messages) and send it again.",
        "bot_no_post": "❌ The bot is admin but can't post messages. Enable “Post messages” and send it again.",
        "user_not_admin": "❌ Only admins of that channel can connect it.",
        "done": "✅ Channel <b>{ch}</b> connected! The daily digest will be posted there at <b>{time} NYT</b>.",
        "removed": "✅ Channel disconnected. The daily digest comes here again.",
        "send_failed": "⚠️ I couldn't post in your channel <b>{ch}</b> (the bot was probably removed or isn't admin). "
                       "It's disconnected now and the news comes here. Tap “📢 My channel” in the menu to connect again.",
    },
}


def _t(lang: str) -> dict:
    return T.get(lang, T["en"])


# ───────────────  handlers  ────────────────
async def show(update: Update, ctx: ContextTypes.DEFAULT_TYPE, language: str):
    """Button '📢 My channel'."""
    q = update.callback_query
    cid = q.message.chat.id
    t = _t(language)
    ch = get_channel(cid)
    if ch:
        text = t["current"].format(ch=label(ch)) + "\n\n" + t["intro"].format(bot=_bot_name(ctx))
        rows = [[B(t["change"], callback_data="chan_change")], [B(t["remove"], callback_data="chan_remove")],
                [B(t["cancel"], callback_data="currencies_done")]]
    else:
        text = t["intro"].format(bot=_bot_name(ctx))
        rows = [[B(t["cancel"], callback_data="currencies_done")]]
    ctx.user_data["awaiting"] = AWAIT_CHANNEL
    await q.answer()
    await q.message.edit_text(text, reply_markup=KB(rows), parse_mode=ParseMode.HTML)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, language: str):
    q = update.callback_query
    t = _t(language)
    if q.data == "chan_remove":
        remove_channel(q.message.chat.id)
        ctx.user_data.pop("awaiting", None)
        await q.answer()
        await q.message.edit_text(t["removed"], parse_mode=ParseMode.HTML)
        return
    # chan_change
    ctx.user_data["awaiting"] = AWAIT_CHANNEL
    await q.answer()
    await q.message.edit_text(t["intro"].format(bot=_bot_name(ctx)),
                              reply_markup=KB([[B(t["cancel"], callback_data="currencies_done")]]),
                              parse_mode=ParseMode.HTML)


def _channel_ref(msg) -> int | str | None:
    """@username / t.me link / -100 id typed by the user, or the channel of a forwarded post."""
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None) is not None:
        return origin.chat.id
    fwd_chat = getattr(msg, "forward_from_chat", None)   # older python-telegram-bot
    if fwd_chat is not None:
        return fwd_chat.id
    text = (msg.text or "").strip()
    if not text:
        return None
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if text.lower().startswith(prefix):
            text = "@" + text[len(prefix):].split("/")[0].split("?")[0]
    if text.lstrip("-").isdigit():
        return int(text)
    if not text.startswith("@"):
        text = "@" + text
    return text if len(text) > 4 and " " not in text else None


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, language: str,
                     subscribe_and_get_time) -> None:
    """Text / forwarded post while waiting for the channel."""
    msg = update.message
    t = _t(language)
    bot = _bot_name(ctx)
    ref = _channel_ref(msg)
    if ref is None:
        await msg.reply_text(t["not_found"].format(bot=bot), parse_mode=ParseMode.HTML)
        return
    try:
        chat = await ctx.bot.get_chat(ref)
    except TelegramError:
        await msg.reply_text(t["not_found"].format(bot=bot), parse_mode=ParseMode.HTML)
        return
    if chat.type != ChatType.CHANNEL:
        await msg.reply_text(t["not_channel"], parse_mode=ParseMode.HTML)
        return
    try:
        me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
    except TelegramError:
        await msg.reply_text(t["bot_not_admin"].format(bot=bot), parse_mode=ParseMode.HTML)
        return
    if me.status not in ADMIN_STATUSES:
        await msg.reply_text(t["bot_not_admin"].format(bot=bot), parse_mode=ParseMode.HTML)
        return
    if me.status == ChatMemberStatus.ADMINISTRATOR and getattr(me, "can_post_messages", True) is False:
        await msg.reply_text(t["bot_no_post"], parse_mode=ParseMode.HTML)
        return
    # Only the channel's own admins may connect it (stops people pointing the bot at someone else's channel)
    try:
        member = await ctx.bot.get_chat_member(chat.id, update.effective_user.id)
        is_channel_admin = member.status in ADMIN_STATUSES
    except TelegramError:
        is_channel_admin = False
    if not is_channel_admin:
        await msg.reply_text(t["user_not_admin"], parse_mode=ParseMode.HTML)
        return

    set_channel(msg.chat.id, chat.id, chat.title or "", chat.username)
    ctx.user_data.pop("awaiting", None)
    digest_time = subscribe_and_get_time(msg.chat.id)   # connecting a channel turns the digest on
    ch = label({"id": chat.id, "title": chat.title, "username": chat.username})
    await msg.reply_text(t["done"].format(ch=ch, time=digest_time), parse_mode=ParseMode.HTML)


async def notify_failed(ctx, chat_id: int, language: str, ch: dict):
    remove_channel(chat_id)
    try:
        await ctx.bot.send_message(chat_id, _t(language)["send_failed"].format(ch=label(ch)),
                                   parse_mode=ParseMode.HTML)
    except TelegramError:
        pass
