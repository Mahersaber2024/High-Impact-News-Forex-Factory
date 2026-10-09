"""
/admin → 📦 EA versions

Upload new expert builds (.ex5 / .ex4) to the website's downloads folder, or delete old ones.
The download page (/download) lists that folder automatically, so nothing else to do.
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import bot_settings as cfg

EXT = (".ex5", ".ex4")
MAX_BYTES = 20 * 1024 * 1024        # Telegram bots can download up to 20 MB
AWAIT_UPLOAD = "ea_upload"
# Same patterns downloadpage.html uses to recognise builds
PAGE_PATTERNS = [
    re.compile(r"^HeySolo\[ATM\](?:_[A-Za-z0-9-]+)?v\d+(?:\.\d+)*\.(ex5|ex4)$", re.I),
    re.compile(r"^Heysolo-SecTM(?:_[A-Za-z0-9-]+)?v\d+(?:\.\d+)*\.(ex5|ex4)$", re.I),
    re.compile(r"^Heysolo-ForwardTester_(?:[A-Za-z0-9-]+)?v\d+(?:\.\d+)*\.(ex5|ex4)$", re.I),
]
SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-\[\]() ]+$")


def available() -> bool:
    """Only where this server hosts the site (Flask + nginx run here)."""
    return cfg.RUN_FLASK and cfg.DOWNLOADS_DIR.parent.is_dir()


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def list_builds() -> list[Path]:
    d = cfg.DOWNLOADS_DIR
    if not d.is_dir():
        return []
    files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in EXT and not p.name.startswith(".")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _download_page() -> str:
    return f"{cfg.PUBLIC_BASE_URL}/download" if cfg.PUBLIC_BASE_URL else ""


def _list_view(ctx) -> tuple[str, KB]:
    builds = list_builds()
    ctx.user_data["ea_files"] = [p.name for p in builds]
    lines = ["📦 <b>EA versions on the site</b>"]
    if builds:
        lines.append("Tap a file to delete it.\n")
    else:
        lines.append("\nNo builds uploaded yet.")
    rows = []
    for i, p in enumerate(builds):
        st = p.stat()
        mark = "" if any(r.match(p.name) for r in PAGE_PATTERNS) else " ⚠️"
        rows.append([B(f"🗑 {p.name} · {_size(st.st_size)} · {datetime.fromtimestamp(st.st_mtime):%m-%d}{mark}",
                       callback_data=f"ea:del:{i}")])
    if any(not any(r.match(p.name) for r in PAGE_PATTERNS) for p in builds):
        lines.append("⚠️ = name not recognised by the download page, it won't show there.")
    if _download_page():
        lines.append(f"\n🔗 {_download_page()}")
    rows.append([B("➕ Upload new version", callback_data="ea:up")])
    rows.append([B("🔙 Back", callback_data="admin_menu")])
    return "\n".join(lines), KB(rows)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split(":")
    act, arg = parts[1], (parts[2] if len(parts) > 2 else "")

    if act == "list":
        ctx.user_data.pop("awaiting", None)
        await q.answer()
        text, kb = _list_view(ctx)
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if act == "up":
        ctx.user_data["awaiting"] = AWAIT_UPLOAD
        await q.answer()
        await q.message.edit_text(
            "➕ <b>Upload new version</b>\n\n"
            "Send the <b>.ex5</b> / <b>.ex4</b> file(s) here (as File, max 20 MB).\n"
            "Same name = replaced. Name format, e.g. <code>HeySolo[ATM]v4.2.ex5</code>\n\n"
            "Tip: you can also just send a .ex5 to the bot any time.",
            reply_markup=KB([[B("✅ Done", callback_data="ea:list")]]), parse_mode=ParseMode.HTML)
        return

    names = ctx.user_data.get("ea_files", [])
    try:
        name = names[int(arg)]
    except (ValueError, IndexError):
        await q.answer("List expired, opening it again.")
        text, kb = _list_view(ctx)
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return
    path = cfg.DOWNLOADS_DIR / name

    if act == "del":
        await q.answer()
        await q.message.edit_text(f"🗑 Delete <code>{name}</code> from the site?",
                                  reply_markup=KB([[B("✅ Yes, delete", callback_data=f"ea:delok:{arg}"),
                                                    B("❌ No", callback_data="ea:list")]]),
                                  parse_mode=ParseMode.HTML)
        return

    if act == "delok":
        path.unlink(missing_ok=True)
        await q.answer(f"Deleted {name}")
        text, kb = _list_view(ctx)
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    await q.answer()


def wants_document(update: Update, ctx) -> bool:
    if not available():
        return False
    aw = ctx.user_data.get("awaiting")
    name = (update.message.document.file_name or "").lower()
    return aw == AWAIT_UPLOAD or (not aw and name.endswith(EXT))


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    doc = msg.document
    name = Path(doc.file_name or "").name
    if not name.lower().endswith(EXT):
        await msg.reply_text("❌ Only .ex5 / .ex4 files can be uploaded here.")
        return
    if name.startswith(".") or not SAFE_NAME.match(name):
        await msg.reply_text("❌ Use a simple file name (letters, numbers, . _ - [ ] only).")
        return
    if doc.file_size and doc.file_size > MAX_BYTES:
        await msg.reply_text("❌ Telegram bots can only download files up to 20 MB.")
        return

    d = cfg.DOWNLOADS_DIR
    d.mkdir(parents=True, exist_ok=True)
    dest = d / name
    existed = dest.exists()
    fd, tmp = tempfile.mkstemp(prefix=".upload-", dir=str(d))
    os.close(fd)
    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=tmp)
        os.chmod(tmp, 0o644)           # nginx (www-data) must be able to read it
        os.replace(tmp, dest)
    except Exception as e:
        Path(tmp).unlink(missing_ok=True)
        await msg.reply_text(f"❌ Upload failed: {e}")
        return

    text = f"✅ {'Replaced' if existed else 'Uploaded'} <code>{name}</code> ({_size(dest.stat().st_size)})"
    if not any(r.match(name) for r in PAGE_PATTERNS):
        text += ("\n⚠️ The download page won't recognise this name. Use e.g. "
                 "<code>HeySolo[ATM]v4.2.ex5</code>, <code>HeySolo[ATM]_PROPv4.2.ex5</code>, "
                 "<code>Heysolo-SecTMv1.0.ex5</code>")
    if _download_page():
        text += f"\n🔗 {_download_page()}"
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                         reply_markup=KB([[B("📦 EA versions", callback_data="ea:list")]]))
