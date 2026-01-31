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
from parser import parse_signal
from stats import calculate_stats

TOKEN = os.getenv("TELEGRAM_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ahoj 👋\n"
        "Jsem kalkulační a analytický bot.\n\n"
        "Příkazy:\n"
        "/lot   – výpočet velikosti lotu\n"
        "/stats – statistika AI / ADX signálů"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = calculate_stats()
    await update.message.reply_text(text)


async def watch_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Pasivně sleduje zprávy FXsniper bota
    a ukládá jen UZAVŘENÉ obchody (CLOSED → WIN / LOST)
    """
    if not update.message or not update.message.text:
        return

    parsed = parse_signal(update.message.text)
    if not parsed:
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO signals (pair, ai, adx, result, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        parsed["pair"],
        parsed["ai"],
        parsed["adx"],
        parsed["result"],
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()


def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))

    # SLEDUJE VŠECHNY ZPRÁVY VE SKUPINĚ (pasivně)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, watch_signals))

    print("Bot běží...")
    app.run_polling()


if __name__ == "__main__":
    main()
