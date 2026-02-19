import os, time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import *

from database import init_db, get_connection
from parser import parse_open, parse_closed
from stats import calculate_status

TOKEN = os.getenv("TELEGRAM_TOKEN")
LOT_TIMEOUT = 120

PAIR_VALUES = {
    "EURUSD":10,"GBPJPY":9.3,"GBPUSD":10,"USDCHF":11,
    "USDJPY":9.5,"USDCAD":8,"AUDCAD":7.4,"EURGBP":12
}

async def start(update, context):
    await update.message.reply_text("/lot – kalkulačka\n/status – statistika")

async def lot(update, context):
    context.user_data.clear()
    context.user_data.update({
        "active":True,
        "step":"risk",
        "start":time.time()
    })
    await update.message.reply_text("Zadej risk (USD):")

async def lot_text(update, context):
    if not context.user_data.get("active"):
        return

    if time.time() - context.user_data["start"] > LOT_TIMEOUT:
        context.user_data.clear()
        await update.message.reply_text("Timeout. Napiš /lot znovu.")
        return

    if context.user_data["step"]=="risk":
        context.user_data["risk"]=float(update.message.text)
        context.user_data["step"]="pair"
        kb=[[InlineKeyboardButton(p,callback_data=p)] for p in PAIR_VALUES]
        await update.message.reply_text("Vyber pár:",reply_markup=InlineKeyboardMarkup(kb))
    elif context.user_data["step"]=="pips":
        p=float(update.message.text)
        lot=context.user_data["risk"]/(p*PAIR_VALUES[context.user_data["pair"]])
        await update.message.reply_text(f"Lot: {lot:.3f}")
        context.user_data.clear()

async def pair_cb(update, context):
    q=update.callback_query
    await q.answer()
    context.user_data["pair"]=q.data
    context.user_data["step"]="pips"
    await q.edit_message_text("Zadej pipy:")

async def status(update, context):
    await update.message.reply_text(calculate_status())

async def watcher(update, context):
    if context.user_data.get("active"):
        return
    if not update.message:
        return

    text=update.message.text
    conn=get_connection()
    cur=conn.cursor()

    o=parse_open(text)
    if o:
        cur.execute("INSERT INTO open_signals VALUES(NULL,?,?,?,?)",
            (o["pair"],o["ai"],o["adx"],datetime.utcnow().isoformat()))
        conn.commit(); conn.close(); return

    c=parse_closed(text)
    if c:
        cur.execute("SELECT id,ai,adx FROM open_signals WHERE pair=? ORDER BY id LIMIT 1",(c["pair"],))
        r=cur.fetchone()
        if r:
            cur.execute("INSERT INTO closed_trades VALUES(NULL,?,?,?,?,?)",
                (c["pair"],r[1],r[2],c["result"],datetime.utcnow().isoformat()))
            cur.execute("DELETE FROM open_signals WHERE id=?",(r[0],))
        conn.commit(); conn.close()

def main():
    init_db()
    app=ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("lot",lot))
    app.add_handler(CommandHandler("status",status))
    app.add_handler(CallbackQueryHandler(pair_cb),group=0)
    app.add_handler(MessageHandler(filters.TEXT,watcher),group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,lot_text),group=2)

    app.run_polling()

main()
    app.run_polling()

main()
