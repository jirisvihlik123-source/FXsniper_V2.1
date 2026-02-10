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
        wins = [1 for ai, adx, res, ts in rows if cond(ai, adx) and res == "WIN"]
        base = [1 for ai, adx, res, ts in rows if cond(ai, adx)]
        return round(len(wins) / len(base) * 100, 1) if base else 0

    ai_adx_block = (
        f"📊 Statistika (posledních {total} obchodů)\n\n"
        f"AI:\n"
        f"70+ → {winrate(lambda ai, adx: ai >= 70)} %\n"
        f"60–70 → {winrate(lambda ai, adx: 60 <= ai < 70)} %\n"
        f"<60 → {winrate(lambda ai, adx: ai < 60)} %\n\n"
        f"ADX:\n"
        f"≥30 → {winrate(lambda ai, adx: adx >= 30)} %\n"
        f"20–30 → {winrate(lambda ai, adx: 20 <= adx < 30)} %\n"
        f"<20 → {winrate(lambda ai, adx: adx < 20)} %\n"
    )

    # =========================
    # DEN V TÝDNU STATISTIKA
    # =========================

    # Inicializace
    days = {i: {"trades": 0, "wins": 0} for i in range(7)}

    for ai, adx, result, ts in rows:
        try:
            dt = datetime.fromisoformat(ts)
            weekday = dt.weekday()  # 0=Mon ... 6=Sun
        except Exception:
            continue

        days[weekday]["trades"] += 1
        if result == "WIN":
            days[weekday]["wins"] += 1

    day_lines = []
    for i in range(5):  # Pondělí–Pátek
        trades = days[i]["trades"]
        if trades == 0:
            continue

        wins = days[i]["wins"]
        winrate_day = round(wins / trades * 100, 1)
        label = day_label(winrate_day)
        name = calendar.day_name[i]

        # Přeložené názvy dnů
        cz_days = {
            "Monday": "Pondělí",
            "Tuesday": "Úterý",
            "Wednesday": "Středa",
            "Thursday": "Čtvrtek",
            "Friday": "Pátek",
        }

        day_lines.append(
            f"{cz_days.get(name, name)}: {label} ({winrate_day} %)"
        )

    day_block = "\n".join(day_lines)

    # =========================
    # FINÁLNÍ VÝSTUP
    # =========================

    return (
        ai_adx_block
        + "\n📅 Výkon podle dnů v týdnu\n\n"
        + (day_block if day_block else "Zatím není dost dat pro dny v týdnu.")
    )
