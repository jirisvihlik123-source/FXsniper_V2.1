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
    ConversationHandler,
    ContextTypes,
    filters,
)

from database import init_db, get_connection
from parser import parse_signal
from stats import calculate_status

TOKEN = os.getenv("TELEGRAM_TOKEN")

# ======================
# LOT KALKULAČKA
# ======================

ENTER_RISK, SELECT_PAIR, ENTER_PIPS = range(3)

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
        "Dostupné příkazy:\n"
        "/lot – výpočet velikosti lotu\n"
        "/status – statistika AI / ADX signálů"
    )


async def lot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Zadej částku (USD), kterou chceš riskovat:")
    return ENTER_RISK


async def enter_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["risk"] = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Zadej platné číslo.")
        return ENTER_RISK

    keyboard = [
        [InlineKeyboardButton(pair, callback_data=pair)]
        for pair in PAIR_VALUES
    ]
    await update.message.reply_text(
        "Vyber měnový pár:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_PAIR


async def select_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pair"] = query.data
    await query.edit_message_text("Zadej počet pipů:")
    return ENTER_PIPS


async def enter_pips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pips = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Zadej platné číslo.")
        return ENTER_PIPS

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

    return ConversationHandler.END


# ======================
# STATUS / ANALYTIKA
# ======================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(calculate_status())


# ======================
# WATCHER SIGNÁLŮ
# ======================

async def watch_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Pasivně sleduje zprávy trading bota.
    Ukládá POUZE uzavřené obchody (WIN / LOST).
    """
    if not update.message or not update.message.text:
        return

    parsed = parse_signal(update.message.text)
    if not parsed:
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO signals (pair, ai, adx, result, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            parsed["pair"],
            parsed["ai"],
            parsed["adx"],
            parsed["result"],
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

    lot_conv = ConversationHandler(
        entry_points=[CommandHandler("lot", lot_start)],
        states={
            ENTER_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_risk)],
            SELECT_PAIR: [CallbackQueryHandler(select_pair)],
            ENTER_PIPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_pips)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(lot_conv)

    # sleduje všechny textové zprávy ve skupině
    app.add_handler(MessageHandler(filters.TEXT, watch_signals))

    print("Bot běží...")
    app.run_polling()


if __name__ == "__main__":
    main()

    main()
