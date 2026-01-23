import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

# Načtení tokenu z proměnných prostředí (Railway)
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Kroky konverzace
SELECT_RISK, SELECT_PAIR, ENTER_PIPS = range(3)

# Menové páry a jejich hodnota pipu na 1 lot v USD
PAIR_VALUES = {
    "EURUSD": 10,
    "GBPJPY": 9.3,
    "GBPUSD": 10,
    "USDCHF": 11,
    "USDJPY": 9.5,
    "USDCAD": 8,
    "AUDCAD": 7.4,
    "EURGBP": 12
}

# Start bota
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ahoj! 👋\nPoužij příkaz /lot pro výpočet velikosti lotu.")

# Začátek výpočtu
async def lot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Riziko 1 %", callback_data="1"),
         InlineKeyboardButton("Riziko 2 %", callback_data="2"),
         InlineKeyboardButton("Riziko 3 %", callback_data="3")]
    ]
    await update.message.reply_text(
        "Zvol, kolik procent účtu chceš riskovat:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_RISK

# Po výběru rizika
async def select_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["risk"] = float(query.data)

    keyboard = [[InlineKeyboardButton(pair, callback_data=pair)] for pair in PAIR_VALUES.keys()]
    await query.edit_message_text(
        "Vyber měnový pár:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_PAIR

# Po výběru měnového páru
async def select_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pair"] = query.data

    await query.edit_message_text("Zadej hodnotu pipů (např. 25.4):")
    return ENTER_PIPS

# Po zadání pipů
async def enter_pips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pips = float(update.message.text.replace(",", "."))
        context.user_data["pips"] = pips
        risk_percent = context.user_data["risk"]
        pair = context.user_data["pair"]

        # Výpočet lotu
        balance = 1000  # můžeš později načítat z uživatelského nastavení
        risk_amount = balance * (risk_percent / 100)
        pip_value = PAIR_VALUES[pair]
        lot_size = risk_amount / (pips * pip_value)

        result = (
            f"💰 *Výsledek výpočtu:*\n\n"
            f"Riziko: {risk_percent}%\n"
            f"Pár: {pair}\n"
            f"Pipy: {pips}\n"
            f"Lot: *{lot_size:.3f}*"
        )

        await update.message.reply_text(result, parse_mode="Markdown")
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Neplatná hodnota pipů. Zkus to znovu.")
        return ENTER_PIPS

# Konec
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Výpočet zrušen.")
    return ConversationHandler.END

# Spuštění aplikace
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("lot", lot_start)],
        states={
            SELECT_RISK: [CallbackQueryHandler(select_risk)],
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

