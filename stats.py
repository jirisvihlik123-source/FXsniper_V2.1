from database import get_connection
from datetime import datetime
import calendar

def day_label(winrate: float) -> str:
    if winrate < 45:
        return "🟥 TRASH"
    elif winrate < 52:
        return "🟧 RISKY"
    elif winrate < 60:
        return "🟩 GOOD"
    else:
        return "🟦 BEST"

def _parse_iso(ts: str):
    if not ts:
        return None
    # Railway/py někdy vrací ...Z, fromisoformat to nemá rád
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def calculate_status():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT result, timestamp FROM closed_trades")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Zatím nejsou žádné uzavřené obchody."

    # 0=Mon ... 6=Sun
    days = {i: {"trades": 0, "wins": 0} for i in range(7)}

    for result, ts in rows:
        dt = _parse_iso(ts)
        if not dt:
            continue
        wd = dt.weekday()
        days[wd]["trades"] += 1
        if str(result).upper() == "WIN":
            days[wd]["wins"] += 1

    cz_days = {
        0: "Pondělí",
        1: "Úterý",
        2: "Středa",
        3: "Čtvrtek",
        4: "Pátek",
        5: "Sobota",
        6: "Neděle",
    }

    lines = []
    total_all = sum(days[i]["trades"] for i in range(7))
    wins_all = sum(days[i]["wins"] for i in range(7))
    wr_all = (wins_all / total_all * 100.0) if total_all else 0.0

    lines.append(f"📅 Výkon podle dnů (celkem {total_all} obchodů, WR {wr_all:.1f}%)\n")

    for i in range(5):  # Po–Pá
        trades = days[i]["trades"]
        wins = days[i]["wins"]

        if trades == 0:
            lines.append(f"{cz_days[i]}: — (0 obchodů)")
            continue

        wr = round(wins / trades * 100.0, 1)
        label = day_label(wr)
        lines.append(f"{cz_days[i]}: {label} | WR {wr:.1f}% | {trades} obchodů")

    return "\n".join(lines)
