from database import get_connection


def calculate_stats(limit=30):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT ai, adx, result
        FROM signals
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádná data pro statistiku."

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

    def winrate(data):
        return round(sum(data) / len(data) * 100, 1) if data else 0

    return (
        f"Statistika signálů (posledních {len(rows)})\n\n"
        f"AI skóre:\n"
        f"70+   → Winrate {winrate(buckets['ai_70'])} %\n"
        f"60–70 → Winrate {winrate(buckets['ai_60'])} %\n"
        f"< 60  → Winrate {winrate(buckets['ai_low'])} %\n\n"
        f"ADX:\n"
        f"≥ 30  → Winrate {winrate(buckets['adx_high'])} %\n"
        f"20–30 → Winrate {winrate(buckets['adx_mid'])} %\n"
        f"< 20  → Winrate {winrate(buckets['adx_low'])} %"
    )

