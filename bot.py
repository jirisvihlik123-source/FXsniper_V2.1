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
# TEST HANDLER /lot
# ======================

async def lot_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("LOT COMMAND ZACHYCEN")

# ======================
# LOT KALKULAČKA (zatím NEAKTIVNÍ)
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

async def lot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Zadej částku (USD), kterou chceš riskovat:")
    return ENTER_RISK

async def enter_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def select_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def enter_pips(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # 🔴 TEST: tenhle handler MUSÍ odpovědět
    app.add_handler(CommandHandler("lot", lot_test))

    # status funguje jako kontrola
    app.add_handler(CommandHandler("status", status_command))

    # watcher
    app.add_handler(MessageHandler(filters.TEXT, watch_signals))

    print("Bot běží (TEST MODE)...")
    app.run_polling()

if __name__ == "__main__":
    main()
