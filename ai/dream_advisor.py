import os, json, time, pathlib, statistics

_DREAM_FILE = pathlib.Path(os.getenv("DREAM_LOG_FILE", "logs/dream_log.json"))
_ADVICE_FILE = pathlib.Path("logs/dream_advice.json")
_DREAM_FILE.parent.mkdir(parents=True, exist_ok=True)

def _load():
    if _DREAM_FILE.exists():
        try:
            with open(_DREAM_FILE, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except Exception:
            return []
    return []

def _save_advice(d: dict):
    _ADVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_ADVICE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)

def dream_analyze(days: int = 7) -> dict:
    cutoff = int(time.time()) - days * 86400
    rows = [r for r in _load() if r.get("ts", 0) >= cutoff]
    if not rows:
        return {"info": "No data", "suggestions": []}

    alerts = [r for r in rows if r.get("event") in ("alert", "alert_plus")]
    headsups = [r for r in rows if r.get("event") == "headsup"]
    results = [r for r in rows if r.get("event") == "result"]

    total = len(alerts)
    wins = sum(1 for r in results if r.get("status") == "WIN")
    losses = sum(1 for r in results if r.get("status") == "LOSS")
    wr = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0

    avg_ai = statistics.mean([r.get("ai", 0) for r in alerts if r.get("ai")]) if alerts else 0
    avg_adx = statistics.mean([r.get("adx", 0) for r in alerts if r.get("adx")]) if alerts else 0
    avg_rrr = statistics.mean([r.get("rrr", 0) for r in alerts if r.get("rrr")]) if alerts else 0

    suggestions = []
    if wr < 50:
        suggestions.append("⚠️ Winrate pod 50 % → zvýšit ADX_MIN o +2 nebo AI_SCORE_MIN o +3")
    elif wr > 70:
        suggestions.append("✅ Winrate nad 70 % → mírně povolit filtry (ADX_MIN -2, AI_SCORE_MIN -3)")
    if avg_ai < 55:
        suggestions.append("AI skóre nízké → zvýšit AI_HEADSUP_MIN o +2 pro méně planých headsupů")
    if avg_adx < 18:
        suggestions.append("ADX slabý → zvýšit HTF_ADX_MIN o +1.5 pro jistější trendy")
    if avg_rrr < 1.3:
        suggestions.append("RRR nízké → zvýšit TP_MULT nebo srazit SL_MULT (více zisku na obchod)")

    out = {
        "analyzed_days": days,
        "total_alerts": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(wr, 1),
        "avg_ai": round(avg_ai, 1),
        "avg_adx": round(avg_adx, 1),
        "avg_rrr": round(avg_rrr, 2),
        "suggestions": suggestions
    }

    _save_advice(out)
    return out

def dream_report_txt(days: int = 7) -> str:
    d = dream_analyze(days)
    txt = (f"🌙 Dream Advisor — posledních {days} dní\n"
           f"Alerts: {d['total_alerts']} | Wins: {d['wins']} | Losses: {d['losses']}\n"
           f"Winrate: {d['winrate']}%\n"
           f"AI průměr: {d['avg_ai']} | ADX: {d['avg_adx']} | RRR: {d['avg_rrr']}\n")
    if d["suggestions"]:
        txt += "\n💡 Návrhy na ladění:\n" + "\n".join(d["suggestions"])
    else:
        txt += "\n✅ Žádné změny nejsou nutné — strategie stabilní."
    return txt

