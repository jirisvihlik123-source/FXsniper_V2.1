import os
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
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

# ======================
# LOT KALKULAČKA
# ======================

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ahoj 👋\n\n"
        "Příkazy:\n"
        "/lot – výpočet velikosti lotu\n"
        "/status – statistika AI / ADX"
    )

# ======================
# /LOT – STAVOVÁ LOGIKA
# ======================

async def lot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = "risk"
    await update.message.reply_text("Zadej částku (USD), kterou chceš riskovat:")

async def lot_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "step" not in context.user_data:
        return

    step = context.user_data["step"]

    # KROK 1 – RISK
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

    # KROK 3 – PIPY
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
# WATCHER – OPEN + CLOSED
# ======================

async def watch_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    conn = get_connection()
    cur = conn.cursor()

    # OPEN ALERT
    open_signal = parse_open(text)
    if open_signal:
        cur.execute(
            """
            INSERT INTO open_signals (pair, ai, adx, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (
                open_signal["pair"],
                open_signal["ai"],
                open_signal["adx"],
                datetime.utcnow().isoformat(),
            )
        )
        conn.commit()
        conn.close()
        return

    # CLOSED ALERT
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lot_text_handler))
    app.add_handler(MessageHandler(filters.TEXT, watch_signals))

    print("Bot běží (ARCH B – OPEN → CLOSED)")
    app.run_polling()

if __name__ == "__main__":
    main()

