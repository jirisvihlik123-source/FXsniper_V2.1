from database import get_connection

def calculate_status(limit=30):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT ai, adx, result
        FROM closed_trades
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody pro analýzu."

    def winrate(data):
        return round(sum(data) / len(data) * 100, 1) if data else 0

    ai_high, ai_mid, ai_low = [], [], []
    adx_high, adx_mid, adx_low = [], [], []

    for ai, adx, result in rows:
        win = 1 if result == "WIN" else 0

        if ai >= 70:
            ai_high.append(win)
        elif ai >= 60:
            ai_mid.append(win)
        else:
            ai_low.append(win)

        if adx >= 30:
            adx_high.append(win)
        elif adx >= 20:
            adx_mid.append(win)
        else:
            adx_low.append(win)

    return (
        f"Statistika signálů (posledních {len(rows)})\n\n"
        f"AI:\n"
        f"70+   → Winrate {winrate(ai_high)} %\n"
        f"60–70 → Winrate {winrate(ai_mid)} %\n"
        f"<60   → Winrate {winrate(ai_low)} %\n\n"
        f"ADX:\n"
        f"≥30   → Winrate {winrate(adx_high)} %\n"
        f"20–30 → Winrate {winrate(adx_mid)} %\n"
        f"<20   → Winrate {winrate(adx_low)} %"
    )
