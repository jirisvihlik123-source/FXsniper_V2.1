import os
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import init_db, get_connection
from parser import parse_open, parse_closed
from stats import calculate_status

TOKEN = os.getenv("TELEGRAM_TOKEN")
LOT_TIMEOUT = 120

PAIR_VALUES = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 6.5,
    "GBPJPY": 6.2,
    "USDCHF": 11.0,
    "USDCAD": 7.2,
    "AUDCAD": 6.0,
    "EURGBP": 12.0,
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/lot – kalkulačka\n/status – statistika")

async def lot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data.update({
        "active": True,
        "step": "risk",
        "start": time.time()
    })
    await update.message.reply_text("Zadej risk (USD):")

async def lot_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("active"):
        return

    if time.time() - context.user_data["start"] > LOT_TIMEOUT:
        context.user_data.clear()
        await update.message.reply_text("Timeout. Napiš /lot znovu.")
        return

    if context.user_data["step"] == "risk":
        try:
            risk = float(update.message.text.replace(",", "."))
        except:
            await update.message.reply_text("Zadej číslo.")
            return

        context.user_data["risk"] = risk
        context.user_data["step"] = "pair"

        kb = [[InlineKeyboardButton(p, callback_data=p)] for p in PAIR_VALUES]
        await update.message.reply_text("Vyber pár:", reply_markup=InlineKeyboardMarkup(kb))

    elif context.user_data["step"] == "pips":
        try:
            pips = float(update.message.text.replace(",", "."))
        except:
            await update.message.reply_text("Zadej číslo pipů.")
            return

        pair = context.user_data["pair"]
        risk = context.user_data["risk"]

        lot = risk / (pips * PAIR_VALUES[pair])
        await update.message.reply_text(f"Lot: {lot:.3f}")

        context.user_data.clear()

async def pair_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["pair"] = query.data
    context.user_data["step"] = "pips"
    await query.edit_message_text("Zadej pipy:")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(calculate_status())

async def watcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("active"):
        return
    if not update.message:
        return

    text = update.message.text or ""

    conn = get_connection()
    cur = conn.cursor()

    o = parse_open(text)
    if o:
        cur.execute(
            "INSERT INTO open_signals VALUES(NULL,?,?,?,?)",
            (o["pair"], o["ai"], o["adx"], datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return

    c = parse_closed(text)
    if c:
        cur.execute(
            "INSERT INTO closed_trades VALUES(NULL,?,?,?,?,?)",
            (c["pair"], None, None, c["result"], datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return

    conn.close()

def main():
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_TOKEN.")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lot", lot))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CallbackQueryHandler(pair_cb), group=0)
    app.add_handler(MessageHandler(filters.TEXT, watcher), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lot_text), group=2)

    print("Lot calculator running...")
    app.run_polling()

if __name__ == "__main__":
    main()
