import os
import sqlite3
from datetime import datetime, timedelta, time as dtime

import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Multi owners & multi channels (comma-separated in .env)
OWNER_IDS = [int(x.strip()) for x in os.getenv("OWNER_IDS").split(",")]
CHANNEL_IDS = [int(x.strip()) for x in os.getenv("CHANNEL_IDS").split(",")]
print("OWNER_IDS =", OWNER_IDS)
print("CHANNEL_IDS =", CHANNEL_IDS)


TZ = pytz.timezone("Africa/Cairo")

DB_FILE = "mints.db"

# ---------- DB ----------
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS mints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    link TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint_id INTEGER,
    stage_num INTEGER,
    start_time TEXT,
    price TEXT,
    notified INTEGER DEFAULT 0
)
""")
conn.commit()

# ---------- Helpers ----------
def is_owner(update: Update):
    return update.effective_user and update.effective_user.id in OWNER_IDS

def parse_date_only(s: str):
    return datetime.strptime(s, "%Y-%m-%d")

def parse_time_only(s: str):
    return datetime.strptime(s, "%H:%M")

AR_STAGE_NAMES = {
    1: "الأولى", 2: "الثانية", 3: "الثالثة", 4: "الرابعة", 5: "الخامسة",
    6: "السادسة", 7: "السابعة", 8: "الثامنة", 9: "التاسعة", 10: "العاشرة",
}

def ar_stage_name(n: int):
    return AR_STAGE_NAMES.get(n, str(n))

def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Add Mint"), KeyboardButton("List Mints")],
            [KeyboardButton("Edit Mint"), KeyboardButton("Delete Mint")],
            [KeyboardButton("Test Channel"), KeyboardButton("Cancel")],
        ],
        resize_keyboard=True
    )

# ---------- State ----------
user_states = {}

def reset_state(uid):
    user_states.pop(uid, None)

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    reset_state(update.effective_user.id)
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=main_menu())

async def test_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    try:
        for ch in CHANNEL_IDS:
            await context.bot.send_message(chat_id=ch, text="✅ Test message from Mint Bot")
        await update.message.reply_text("Sent a test message to all channels.", reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send:\n{e}", reply_markup=main_menu())

# ---------- List ----------
async def list_mints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    rows = cur.execute("SELECT id, name, link FROM mints ORDER BY id DESC").fetchall()
    if not rows:
        await update.message.reply_text("No mints yet.", reply_markup=main_menu())
        return

    msg = "📋 Mints:\n\n"
    for r in rows:
        msg += f"• {r[1]}\n{r[2]}\n"
        stages = cur.execute(
            "SELECT stage_num, start_time, price FROM stages WHERE mint_id=? ORDER BY stage_num",
            (r[0],)
        ).fetchall()
        for s in stages:
            msg += f"  - Stage {s[0]}: {s[1]} | Price: {s[2]}\n"
        msg += "\n"
    await update.message.reply_text(msg, reply_markup=main_menu())

# ---------- Add Mint ----------
async def start_add_mint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    uid = update.effective_user.id
    user_states[uid] = {"mode": "add", "step": "name", "data": {}}
    await update.message.reply_text("Send mint name:")

# ---------- Edit / Delete selectors ----------
def mints_keyboard(action: str):
    rows = cur.execute("SELECT id, name FROM mints ORDER BY id DESC").fetchall()
    if not rows:
        return None
    buttons = [[InlineKeyboardButton(r[1], callback_data=f"{action}:{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)

async def start_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    kb = mints_keyboard("delpick")
    if not kb:
        await update.message.reply_text("No mints to delete.", reply_markup=main_menu())
        return
    await update.message.reply_text("Choose a mint to delete:", reply_markup=kb)

async def start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    kb = mints_keyboard("editpick")
    if not kb:
        await update.message.reply_text("No mints to edit.", reply_markup=main_menu())
        return
    await update.message.reply_text("Choose a mint to edit:", reply_markup=kb)

# ---------- Callback Queries ----------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "cancel":
        reset_state(uid)
        await query.edit_message_text("Cancelled.")
        await context.bot.send_message(chat_id=uid, text="Back to menu.", reply_markup=main_menu())
        return

    if data.startswith("delpick:"):
        mint_id = int(data.split(":")[1])
        user_states[uid] = {"mode": "delete", "mint_id": mint_id}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes", callback_data=f"delconfirm:{mint_id}")],
            [InlineKeyboardButton("No", callback_data="cancel")]
        ])
        await query.edit_message_text("Are you sure you want to delete this mint?", reply_markup=kb)
        return

    if data.startswith("delconfirm:"):
        mint_id = int(data.split(":")[1])
        cur.execute("DELETE FROM stages WHERE mint_id=?", (mint_id,))
        cur.execute("DELETE FROM mints WHERE id=?", (mint_id,))
        conn.commit()
        reset_state(uid)
        await query.edit_message_text("✅ Mint deleted.")
        await context.bot.send_message(chat_id=uid, text="Back to menu.", reply_markup=main_menu())
        return

    if data.startswith("editpick:"):
        mint_id = int(data.split(":")[1])
        user_states[uid] = {"mode": "edit", "mint_id": mint_id}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Edit Name", callback_data="edit:name")],
            [InlineKeyboardButton("Edit Link", callback_data="edit:link")],
            [InlineKeyboardButton("Edit Stages", callback_data="edit:stages")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")]
        ])
        await query.edit_message_text("What do you want to edit?", reply_markup=kb)
        return

    if data.startswith("edit:"):
        field = data.split(":")[1]
        state = user_states.get(uid)
        if not state or state.get("mode") != "edit":
            await query.edit_message_text("Session expired.")
            return

        state["edit_field"] = field
        if field == "name":
            state["step"] = "edit_name"
            await query.edit_message_text("Send new name:")
        elif field == "link":
            state["step"] = "edit_link"
            await query.edit_message_text("Send new link:")
        elif field == "stages":
            state["step"] = "stages_count"
            state["data"] = {}
            await query.edit_message_text("How many stages? (number)")
        return

# ---------- Message Handler ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    uid = update.effective_user.id
    text = update.message.text.strip()

    # Menu buttons
    if text == "Add Mint":
        return await start_add_mint(update, context)
    if text == "List Mints":
        return await list_mints(update, context)
    if text == "Edit Mint":
        return await start_edit(update, context)
    if text == "Delete Mint":
        return await start_delete(update, context)
    if text == "Test Channel":
        return await test_channel(update, context)
    if text == "Cancel":
        reset_state(uid)
        await update.message.reply_text("Cancelled. Back to menu.", reply_markup=main_menu())
        return

    state = user_states.get(uid)
    if not state:
        return

    # ---------- ADD FLOW ----------
    if state.get("mode") == "add":
        step = state.get("step")

        if step == "name":
            state["data"]["name"] = text
            state["step"] = "link"
            await update.message.reply_text("Send mint link:")
            return

        if step == "link":
            state["data"]["link"] = text
            state["step"] = "stages_count"
            await update.message.reply_text("How many stages? (number)")
            return

        if step == "stages_count":
            try:
                count = int(text)
                state["data"]["count"] = count
                state["data"]["stages"] = []
                state["step"] = "stage_date"
                await update.message.reply_text("Send date for stage 1 (YYYY-MM-DD):")
            except:
                await update.message.reply_text("Please send a valid number.")
            return

        if step == "stage_date":
            try:
                d = parse_date_only(text)
                state["data"]["last_date"] = d
                state["step"] = "stage_time"
                await update.message.reply_text("Send time (HH:MM):")
            except:
                await update.message.reply_text("Wrong date format. Use: YYYY-MM-DD")
            return

        if step == "stage_time":
            try:
                t = parse_time_only(text)
                d = state["data"]["last_date"]
                combined = datetime(d.year, d.month, d.day, t.hour, t.minute)
                combined = TZ.localize(combined)
                state["data"]["last_datetime"] = combined
                state["step"] = "stage_price"
                await update.message.reply_text("Send price for this stage:")
            except:
                await update.message.reply_text("Wrong time format. Use: HH:MM")
            return

        if step == "stage_price":
            price = text
            state["data"]["stages"].append((state["data"]["last_datetime"], price))

            if len(state["data"]["stages"]) < state["data"]["count"]:
                next_stage = len(state["data"]["stages"]) + 1
                state["step"] = "stage_date"
                await update.message.reply_text(f"Send date for stage {next_stage} (YYYY-MM-DD):")
                return

            # Save
            name = state["data"]["name"]
            link = state["data"]["link"]

            cur.execute("INSERT INTO mints (name, link) VALUES (?, ?)", (name, link))
            mint_id = cur.lastrowid

            for idx, (dtv, pricev) in enumerate(state["data"]["stages"], start=1):
                cur.execute(
                    "INSERT INTO stages (mint_id, stage_num, start_time, price, notified) VALUES (?, ?, ?, ?, 0)",
                    (mint_id, idx, dtv.strftime("%Y-%m-%d %H:%M"), pricev)
                )

            conn.commit()
            stages_count = len(state["data"]["stages"])
            reset_state(uid)

            await update.message.reply_text(
                f"✅ Mint saved successfully!\n"
                f"🧩 Name: {name}\n"
                f"🗂️ Stages: {stages_count}\n\n"
                f"You can check it now from: List Mints",
                reply_markup=main_menu()
            )
            return

    # ---------- EDIT FLOW ----------
    if state.get("mode") == "edit":
        mint_id = state.get("mint_id")
        step = state.get("step")

        if step == "edit_name":
            cur.execute("UPDATE mints SET name=? WHERE id=?", (text, mint_id))
            conn.commit()
            reset_state(uid)
            await update.message.reply_text("✅ Name updated.", reply_markup=main_menu())
            return

        if step == "edit_link":
            cur.execute("UPDATE mints SET link=? WHERE id=?", (text, mint_id))
            conn.commit()
            reset_state(uid)
            await update.message.reply_text("✅ Link updated.", reply_markup=main_menu())
            return

        if step == "stages_count":
            try:
                count = int(text)
                state["data"]["count"] = count
                state["data"]["stages"] = []
                state["step"] = "stage_date"
                await update.message.reply_text("Send date for stage 1 (YYYY-MM-DD):")
            except:
                await update.message.reply_text("Please send a valid number.")
            return

        if step == "stage_date":
            try:
                d = parse_date_only(text)
                state["data"]["last_date"] = d
                state["step"] = "stage_time"
                await update.message.reply_text("Send time (HH:MM):")
            except:
                await update.message.reply_text("Wrong date format. Use: YYYY-MM-DD")
            return

        if step == "stage_time":
            try:
                t = parse_time_only(text)
                d = state["data"]["last_date"]
                combined = datetime(d.year, d.month, d.day, t.hour, t.minute)
                combined = TZ.localize(combined)
                state["data"]["last_datetime"] = combined
                state["step"] = "stage_price"
                await update.message.reply_text("Send price for this stage:")
            except:
                await update.message.reply_text("Wrong time format. Use: HH:MM")
            return

        if step == "stage_price":
            price = text
            state["data"]["stages"].append((state["data"]["last_datetime"], price))

            if len(state["data"]["stages"]) < state["data"]["count"]:
                next_stage = len(state["data"]["stages"]) + 1
                state["step"] = "stage_date"
                await update.message.reply_text(f"Send date for stage {next_stage} (YYYY-MM-DD):")
                return

            # Replace stages
            cur.execute("DELETE FROM stages WHERE mint_id=?", (mint_id,))
            for idx, (dtv, pricev) in enumerate(state["data"]["stages"], start=1):
                cur.execute(
                    "INSERT INTO stages (mint_id, stage_num, start_time, price, notified) VALUES (?, ?, ?, ?, 0)",
                    (mint_id, idx, dtv.strftime("%Y-%m-%d %H:%M"), pricev)
                )
            conn.commit()

            stages_count = len(state["data"]["stages"])
            reset_state(uid)

            await update.message.reply_text(
                f"✅ Stages updated successfully!\n"
                f"🗂️ New stages count: {stages_count}\n\n"
                f"Check the result in: List Mints",
                reply_markup=main_menu()
            )
            return

# ---------- Jobs ----------
async def check_stages_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    rows = cur.execute("""
        SELECT s.id, m.name, m.link, s.stage_num, s.start_time, s.price, s.notified
        FROM stages s
        JOIN mints m ON m.id = s.mint_id
    """).fetchall()

    for r in rows:
        stage_id, name, link, stage_num, start_str, price, notified = r

        if notified:
            continue

        start_naive = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        start = TZ.localize(start_naive)

        minutes_left = (start - now).total_seconds() / 60

        if minutes_left <= 0:
            continue

        should_send = False

        if 0 < minutes_left <= 10:
            should_send = True
        else:
            notify_time = start - timedelta(minutes=10)
            if notify_time <= now < notify_time + timedelta(minutes=1):
                should_send = True

        if should_send:
            ar_name = ar_stage_name(stage_num)
            text = (
                f"⏰ المرحلة {ar_name} هتبدأ كمان 10 دقائق\n"
                f"⏰ Stage {stage_num} starts in 10 minutes\n\n"
                f"🧩 {name}\n"
                f"🔗 {link}\n"
                f"💰 Price: {price}"
            )
            for ch in CHANNEL_IDS:
                await context.bot.send_message(chat_id=ch, text=text)
            cur.execute("UPDATE stages SET notified=1 WHERE id=?", (stage_id,))
            conn.commit()

async def daily_post_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    rows = cur.execute("""
        SELECT DISTINCT m.name, m.link
        FROM stages s
        JOIN mints m ON m.id = s.mint_id
        WHERE s.start_time LIKE ?
    """, (today + "%",)).fetchall()

    if not rows:
        return

    text = "🔔 Mints of the Day / منتات اليوم\n\n"
    for r in rows:
        text += f"🧩 {r[0]}\n🔗 {r[1]}\n\n"
    for ch in CHANNEL_IDS:
        await context.bot.send_message(chat_id=ch, text=text)

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Jobs
    app.job_queue.run_repeating(check_stages_job, interval=60, first=10)
    app.job_queue.run_daily(daily_post_job, time=dtime(hour=0, minute=0))

    print("Bot is running (Egypt Time)...")
    app.run_polling()

if __name__ == "__main__":
    main()
