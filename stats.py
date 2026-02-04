from database import get_connection

def calculate_status():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT ai, adx, result FROM closed_trades")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody k analýze."

    total = len(rows)

    def winrate(cond):
        data = [1 for ai,adx,res in rows if cond(ai,adx) and res=="WIN"]
        base = [1 for ai,adx,res in rows if cond(ai,adx)]
        return round(len(data)/len(base)*100,1) if base else 0

    return (
        f"Statistika (posledních {total} obchodů)\n\n"
        f"AI:\n"
        f"70+ → {winrate(lambda ai,adx: ai>=70)} %\n"
        f"60–70 → {winrate(lambda ai,adx: 60<=ai<70)} %\n"
        f"<60 → {winrate(lambda ai,adx: ai<60)} %\n\n"
        f"ADX:\n"
        f"≥30 → {winrate(lambda ai,adx: adx>=30)} %\n"
        f"20–30 → {winrate(lambda ai,adx: 20<=adx<30)} %\n"
        f"<20 → {winrate(lambda ai,adx: adx<20)} %"
    )
