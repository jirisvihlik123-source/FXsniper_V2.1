import os
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import init_db, get_connection
from parser import parse_open, parse_close
from stats import calculate_status

TOKEN = os.getenv("TELEGRAM_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ahoj 👋\n"
        "Jsem kalkulační a analytický bot.\n\n"
        "Příkazy:\n"
        "/lot – výpočet lotu\n"
        "/status – AI / ADX statistika"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(calculate_status())


async def watch_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # OPEN ALERT
    open_data = parse_open(text)
    if open_data:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO trades (
                pair, timeframe, side, entry,
                sl_pips, rrr, ai, adx, adx_delta,
                status, opened_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """, (
            open_data["pair"],
            open_data["timeframe"],
            open_data["side"],
            open_data["entry"],
            open_data["sl_pips"],
            open_data["rrr"],
            open_data["ai"],
            open_data["adx"],
            open_data["adx_delta"],
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()
        return

    # CLOSED ALERT
    close_data = parse_close(text)
    if close_data:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE trades
            SET status='CLOSED', result=?, closed_at=?
            WHERE pair=? AND timeframe=? AND side=? AND status='OPEN'
            ORDER BY opened_at DESC
            LIMIT 1
        """, (
            close_data["result"],
            datetime.utcnow().isoformat(),
            close_data["pair"],
            close_data["timeframe"],
            close_data["side"]
        ))

        conn.commit()
        conn.close()


def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT, watch_messages))

    print("Bot běží (OPEN → CLOSED model)")
    app.run_polling()


if __name__ == "__main__":
    main()
