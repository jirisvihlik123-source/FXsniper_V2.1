from database import get_connection


def calculate_status(limit=50):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT ai, adx, result
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY closed_at DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody pro statistiku."

    buckets = {
        "ai_70": [],
        "ai_60": [],
        "ai_low": [],
        "adx_high": [],
        "adx_mid": [],
        "adx_low": []
    }

    for ai, adx, result in rows:
        win = 1 if result == "WIN" else 0

        if ai >= 70:
            buckets["ai_70"].append(win)
        elif ai >= 60:
            buckets["ai_60"].append(win)
        else:
            buckets["ai_low"].append(win)

        if adx >= 30:
            buckets["adx_high"].append(win)
        elif adx >= 20:
            buckets["adx_mid"].append(win)
        else:
            buckets["adx_low"].append(win)

    def wr(x):
        return round(sum(x) / len(x) * 100, 1) if x else 0

    return (
        f"Status signálů (posledních {len(rows)})\n\n"
        f"AI:\n"
        f"70+   → {wr(buckets['ai_70'])} %\n"
        f"60–70 → {wr(buckets['ai_60'])} %\n"
        f"< 60  → {wr(buckets['ai_low'])} %\n\n"
        f"ADX:\n"
        f"≥ 30  → {wr(buckets['adx_high'])} %\n"
        f"20–30 → {wr(buckets['adx_mid'])} %\n"
        f"< 20  → {wr(buckets['adx_low'])} %"
    )
