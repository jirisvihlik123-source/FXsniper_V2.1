from database import get_connection
from datetime import datetime

# =========================
# Barva podle winrate
# =========================

def day_color(winrate: float) -> str:
    if winrate >= 70:
        return "🟢"
    elif winrate >= 55:
        return "🔵"
    elif winrate >= 45:
        return "🟡"
    elif winrate >= 30:
        return "🟠"
    else:
        return "🔴"

# =========================
# Hlavní /status
# =========================

def calculate_status():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT result, timestamp
        FROM closed_trades
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody."

    total = len(rows)

    # Inicializace dnů (0=Mon ... 6=Sun)
    days = {i: {"trades": 0, "wins": 0} for i in range(7)}

    for result, ts in rows:
        try:
            dt = datetime.fromisoformat(ts)
            weekday = dt.weekday()
        except:
            continue

        days[weekday]["trades"] += 1
        if result == "WIN":
            days[weekday]["wins"] += 1

    cz_days = {
        0: "Pondělí",
        1: "Úterý",
        2: "Středa",
        3: "Čtvrtek",
        4: "Pátek",
    }

    lines = []

    for i in range(5):  # jen pracovní dny
        trades = days[i]["trades"]

        if trades == 0:
            continue

        wins = days[i]["wins"]
        winrate = round(wins / trades * 100, 1)
        color = day_color(winrate)

        lines.append(
            f"{color} {cz_days[i]} – {winrate}% ({trades} obchodů)"
        )

    if not lines:
        return "Zatím není dost dat pro dny v týdnu."

    return (
        "📅 Dlouhodobý výkon podle dnů\n\n"
        + "\n".join(lines)
        + f"\n\nCelkem obchodů: {total}"
    )
    )
