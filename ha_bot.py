import json, os, sys
import requests

# ─── הגדרות ───────────────────────────────────────────────
HA_URL           = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN         = os.environ.get("HA_TOKEN", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = "ha_bot_state.json"
HA_HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

# ─── מצב מתמשך (offset של טלגרם, רשימת מעקב, מצבים אחרונים) ─
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {"last_update_id": 0, "watched": [], "last_states": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ─── Home Assistant API ──────────────────────────────────
def ha_get_state(entity_id):
    r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=HA_HEADERS, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def ha_list_states(domain=None):
    r = requests.get(f"{HA_URL}/api/states", headers=HA_HEADERS, timeout=10)
    r.raise_for_status()
    states = r.json()
    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
    return states

def ha_call_service(entity_id, service):
    domain = entity_id.split(".")[0]
    r = requests.post(
        f"{HA_URL}/api/services/{domain}/{service}",
        headers=HA_HEADERS, json={"entity_id": entity_id}, timeout=10)
    r.raise_for_status()

# ─── טלגרם ────────────────────────────────────────────────
def telegram_get_updates(offset):
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        params={"offset": offset + 1, "timeout": 0}, timeout=10)
    r.raise_for_status()
    return r.json().get("result", [])

def send_telegram(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"  ❌ טלגרם: {e}")

# ─── פקודות ───────────────────────────────────────────────
HELP_TEXT = (
    "🏠 <b>פקודות זמינות:</b>\n"
    "/help — הצגת פקודות\n"
    "/list [domain] — רשימת מכשירים (למשל /list light)\n"
    "/status &lt;entity_id&gt; — מצב נוכחי של מכשיר\n"
    "/on &lt;entity_id&gt; — הדלקה/הפעלה\n"
    "/off &lt;entity_id&gt; — כיבוי\n"
    "/toggle &lt;entity_id&gt; — החלפת מצב\n"
    "/watch &lt;entity_id&gt; — הוספה להתראות שינוי מצב\n"
    "/unwatch &lt;entity_id&gt; — הסרה מהתראות\n"
    "/watching — רשימת המכשירים במעקב"
)

def handle_command(text, state):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help" or cmd == "/start":
        return HELP_TEXT

    if cmd == "/list":
        states = ha_list_states(domain=arg or None)
        if not states:
            return "לא נמצאו מכשירים."
        lines = [f"• {s['entity_id']} — {s['state']}" for s in states[:50]]
        return "\n".join(lines)

    if cmd == "/status":
        if not arg:
            return "שימוש: /status <entity_id>"
        s = ha_get_state(arg)
        if not s:
            return f"⚠️ לא נמצא מכשיר בשם {arg}"
        return f"{s['entity_id']}: <b>{s['state']}</b>"

    if cmd in ("/on", "/off", "/toggle"):
        if not arg:
            return f"שימוש: {cmd} <entity_id>"
        service = {"/on": "turn_on", "/off": "turn_off", "/toggle": "toggle"}[cmd]
        try:
            ha_call_service(arg, service)
            return f"✅ בוצע {service} עבור {arg}"
        except Exception as e:
            return f"❌ שגיאה: {e}"

    if cmd == "/watch":
        if not arg:
            return "שימוש: /watch <entity_id>"
        if arg not in state["watched"]:
            state["watched"].append(arg)
        return f"👁️ עוקב כעת אחרי {arg}"

    if cmd == "/unwatch":
        if arg in state["watched"]:
            state["watched"].remove(arg)
            state["last_states"].pop(arg, None)
        return f"🚫 הופסק מעקב אחרי {arg}"

    if cmd == "/watching":
        if not state["watched"]:
            return "אין מכשירים במעקב כרגע."
        return "👁️ במעקב:\n" + "\n".join(f"• {e}" for e in state["watched"])

    return "❓ פקודה לא מוכרת. שלח /help לרשימת הפקודות."

# ─── התראות על שינוי מצב ─────────────────────────────────
def check_watched(state):
    for entity_id in state["watched"]:
        s = ha_get_state(entity_id)
        if not s:
            continue
        new_val = s["state"]
        old_val = state["last_states"].get(entity_id)
        if old_val is not None and old_val != new_val:
            send_telegram(f"🔔 <b>{entity_id}</b> השתנה: {old_val} → {new_val}")
        state["last_states"][entity_id] = new_val

# ─── ראשי ─────────────────────────────────────────────────
def main():
    if not (HA_URL and HA_TOKEN and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("❌ חסרים משתני סביבה נדרשים: HA_URL, HA_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
        sys.exit(1)

    state = load_state()

    updates = telegram_get_updates(state["last_update_id"])
    for update in updates:
        state["last_update_id"] = update["update_id"]
        message = update.get("message", {})
        text = message.get("text", "")
        if text.startswith("/"):
            reply = handle_command(text, state)
            send_telegram(reply)

    check_watched(state)
    save_state(state)

if __name__ == "__main__":
    main()
