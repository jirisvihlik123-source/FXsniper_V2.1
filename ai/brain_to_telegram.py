import os, json, requests
from datetime import datetime as dt

BRAIN_SUMMARY = "ai/brain_summary.json"
TELEGRAM_BOT_TOKEN = "8364393500:AAG3q3QNe0OIQ9JIpBHFGnvovFzHrfH9FSQ"
CHAT_ID = "-1003018406463"

def send_message(text, parse_mode="HTML", disable_web_page_preview=True):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Chybí TELEGRAM_BOT_TOKEN nebo CHAT_ID")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()
    print("[OK] Zpráva odeslána do Telegramu")

def build_message(s):
    now = dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    details = "\n".join(
        [f"{int(b['score_bin'])} ➜ {b['winrate']:.1f}%" for b in s.get("bins", [])]
    )

    msg = f"""
<b>🧠 AI Brain Feedback</b>  <i>{now}</i>

📊 <b>Souhrn:</b>
• Průměrná přesnost: <b>{s.get('avg_winrate', 0):.1f}%</b>
• Nejlepší skóre bin: <b>{s.get('best_bin', '?')}</b> ➜ {s.get('best_winrate', 0):.1f}%
• Nejhorší skóre bin: <b>{s.get('worst_bin', '?')}</b> ➜ {s.get('worst_winrate', 0):.1f}%

<b>Detailně:</b>
<pre>{details}</pre>
""".strip()
    return msg

def main():
    if not os.path.exists(BRAIN_SUMMARY):
        raise SystemExit("[ERR] Soubor ai/brain_summary.json nebyl nalezen. Spusť nejdřív brain_feedback.py")

    with open(BRAIN_SUMMARY, "r", encoding="utf-8") as f:
        summary = json.load(f)

    msg = build_message(summary)
    send_message(msg)

if __name__ == "__main__":
    main()
