import os, requests

def _env(name: str) -> str | None:
    return os.getenv(name) or os.getenv(name.lower())

def send_message(text: str,
                 parse_mode: str|None="HTML",
                 disable_web_page_preview: bool=True):
    token = _env("TELEGRAM_BOT_TOKEN") or _env("TG_BOT_TOKEN")
    chat  = _env("TELEGRAM_CHAT_ID")  or _env("TG_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN/CHAT_ID env vars")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat,
        "text": text,
        "disable_web_page_preview": "true" if disable_web_page_preview else "false",
    }
    if parse_mode:
        data["parse_mode"] = parse_mode
    r = requests.post(url, data=data, timeout=20)
    r.raise_for_status()
    return r.json()
