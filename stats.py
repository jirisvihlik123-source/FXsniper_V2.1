from database import get_connection
from datetime import datetime

def day_label(winrate: float) -> str:
    if winrate < 45:
        return "🟥 TRASH"
    elif winrate < 52:
        return "🟧 RISKY"
    elif winrate < 60:
        return "🟩 GOOD"
    else:
        return "🟦 BEST"

def calculate_status():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT result, timestamp FROM closed_trades")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody."

    days = {i: {"trades": 0, "wins": 0} for i in range(7)}

    for result, ts in rows:
        try:
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            wd = dt.weekday()
        except:
            continue

        days[wd]["trades"] += 1
        if str(result).upper() == "WIN":
            days[wd]["wins"] += 1

    cz_days = {
        0: "Pondělí",
        1: "Úterý",
        2: "Středa",
        3: "Čtvrtek",
        4: "Pátek",
    }

    total = sum(days[i]["trades"] for i in range(7))
    wins_total = sum(days[i]["wins"] for i in range(7))
    wr_total = round((wins_total / total) * 100, 1) if total else 0

    lines = [f"📅 Dlouhodobý výkon ({total} obchodů | WR {wr_total}%)\n"]

    for i in range(5):
        trades = days[i]["trades"]
        wins = days[i]["wins"]

        if trades == 0:
            lines.append(f"{cz_days[i]}: — (0 obchodů)")
            continue

        wr = round((wins / trades) * 100, 1)
        label = day_label(wr)

        lines.append(f"{cz_days[i]}: {label} | {wr}% ({trades} obchodů)")

    return "\n".join(lines)
