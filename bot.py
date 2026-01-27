import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# Načtení tokenu z prostředí (Railway)
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Kroky konverzace
ENTER_RISK, SELECT_PAIR, ENTER_PIPS = range(3)

# Měnové páry a hodnota pipu na 1 lot v USD
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


# Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ahoj \nPoužij příkaz /lot pro výpočet velikosti lotu."
    )


# Začátek výpočtu
async def lot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Zadej částku (v USD), kterou chceš riskovat:")
    return ENTER_RISK


# Uživatel zadal částku k riziku
async def enter_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        risk_amount = float(update.message.text.replace(",", "."))
        context.user_data["risk_amount"] = risk_amount

        keyboard = [
            [InlineKeyboardButton(pair, callback_data=pair)]
            for pair in PAIR_VALUES.keys()
        ]
        await update.message.reply_text(
            "Vyber měnový pár:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SELECT_PAIR

    except ValueError:
        await update.message.reply_text("Neplatná částka. Zkus to znovu (např. 25 nebo 10.5).")
        return ENTER_RISK


# Po výběru měnového páru
async def select_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pair"] = query.data

    await query.edit_message_text("Zadej počet pipů (např. 22.4):")
    return ENTER_PIPS


# Po zadání pipů
async def enter_pips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pips = float(update.message.text.replace(",", "."))
        context.user_data["pips"] = pips
        risk_amount = context.user_data["risk_amount"]
        pair = context.user_data["pair"]

        # Výpočet lotu
        pip_value = PAIR_VALUES[pair]
        lot_size = risk_amount / (pips * pip_value)

        result = (
            f"Výsledek výpočtu:\n\n"
            f"Riziko: {risk_amount} USD\n"
            f"Pár: {pair}\n"
            f"Pipy: {pips}\n"
            f"Lot: {lot_size:.3f}"
        )

        await update.message.reply_text(result)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Neplatná hodnota pipů. Zkus to znovu.")
        return ENTER_PIPS


# Konec
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Výpočet zrušen.")
    return ConversationHandler.END


# Spuštění
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("lot", lot_start)],
        states={
            ENTER_RISK: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_risk)],
            SELECT_PAIR: [CallbackQueryHandler(select_pair)],
            ENTER_PIPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_pips)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("✅ Bot běží...")
    app.run_polling()


if __name__ == "__main__":
    main()
