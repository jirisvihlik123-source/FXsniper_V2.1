from database import get_connection
from datetime import datetime
import calendar

# =========================
# Pomocné funkce
# =========================

def day_label(winrate: float) -> str:
    if winrate < 45:
        return "🟥 TRASH"
    elif winrate < 52:
        return "🟧 RISKY"
    elif winrate < 60:
        return "🟩 GOOD"
    else:
        return "🟦 BEST"

# =========================
# Hlavní /status výpočet
# =========================

def calculate_status():
    conn = get_connection()
    cur = conn.cursor()

    # Všechny uzavřené obchody
    cur.execute("""
        SELECT ai, adx, result, timestamp
        FROM closed_trades
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody k analýze."

    total = len(rows)

    # =========================
    # AI / ADX STATISTIKA
    # =========================

    def winrate(cond):
        wins

