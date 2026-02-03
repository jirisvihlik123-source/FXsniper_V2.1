import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from database import init_db, get_connection
from parser import parse_open, parse_closed
from stats import calculate_status

TOKEN = os.getenv("TELEGRAM_TOKEN")

PAIR_VALUES = {
    "EURUSD": 10,
    "GBPJPY": 9.3,
    "GBPUSD": 10,
    "USDCHF": 11,
    "USDJPY": 9.5,
    "USDCAD": 8,
    "AUDCAD": 7.4,
    "EURGBP": 12,
}

# ======================
# /START
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ahoj 👋\n\n"
        "/lot – výpočet lotu\n"
        "/status – statistika obchodů"
    )

# ======================
# /LOT
# ======================

async def lot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["active_lot"] = True
    context.user_data["step"] = "risk"

    await update.message.reply_text("Zadej částku (USD), kterou chceš riskovat:")

async def lot_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("active_lot"):
        return

    step = context.user_data.get("step")

    if step == "risk":
        try:
            context.user_data["risk"] = float(update.message.text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Zadej platné číslo.")
            return

        keyboard = [
            [InlineKeyboardButton(pair, callback_data=pair)]
            for pair in PAIR_VALUES
        ]

        context.user_data["step"] = "pair"
        await update.message.reply_text(
            "Vyber měnový pár:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif step == "pips":
        try:
            pips = float(update.message.text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Zadej platné číslo.")
            return

        risk = context.user_data["risk"]
        pair = context.user_data["pair"]
        pip_value = PAIR_VALUES[pair]

        lot = risk / (pips * pip_value)

        await update.message.reply_text(
            "Výsledek výpočtu:\n\n"
            f"Riziko: {risk} USD\n"
            f"Pár: {pair}\n"
            f"Pipy: {pips}\n"
            f"Lot: {lot:.3f}"
        )

        context.user_data.clear()

async def lot_pair_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("active_lot"):
        return

    query = update.callback_query
    await query.answer()

    context.user_data["pair"] = query.data
    context.user_data["step"] = "pips"

    await query.edit_message_text("Zadej počet pipů:")

# ======================
# /STATUS
# ======================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(calculate_status())

# ======================
# WATCHER (NESMÍ BLOKOVAT)
# ======================

async def watch_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    conn = get_connection()
    cur = conn.cursor()

    open_sig = parse_open(text)
    if open_sig:
        cur.execute(
            """
            INSERT INTO open_signals (pair, ai, adx, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (
                open_sig["pair"],
                open_sig["ai"],
                open_sig["adx"],
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()
        return

    closed = parse_closed(text)
    if closed:
        cur.execute(
            """
            SELECT ai, adx FROM open_signals
            WHERE pair = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (closed["pair"],)
        )
        row = cur.fetchone()

        if row:
            ai, adx = row
            cur.execute(
                """
                INSERT INTO closed_trades (pair, ai, adx, result, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    closed["pair"],
                    ai,
                    adx,
                    closed["result"],
                    datetime.utcnow().isoformat(),
                )
            )

        conn.commit()
        conn.close()

# ======================
# MAIN
# ======================

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lot", lot_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(lot_pair_handler))

    # 🔴 watcher NESMÍ blokovat
    app.add_handler(
        MessageHandler(filters.TEXT, watch_signals),
        block=False
    )

    # 🟢 lot vstup
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, lot_text_handler)
    )

    print("Bot běží (LOT + STATUS OK)")
    app.run_polling()

if __name__ == "__main__":
    main()
