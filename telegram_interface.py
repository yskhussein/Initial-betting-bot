"""
Telegram Bot Interface v2
Commands:
  /start      - Main menu
  /slip       - Today's slip
  /run        - Trigger bot manually
  /stats      - P&L stats
  /history    - Recent bet history
  /settings   - View/change settings
  /set        - Change a setting
  /pause      - Pause bot
  /resume     - Resume bot
  /report     - Analytics report (daily/weekly/monthly)
  /upcoming   - Upcoming high confidence picks
  /preview    - Send 7-day match preview
"""

import os
import json
import logging
import requests
import threading
from datetime import datetime
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN.strip()}"
SETTINGS_FILE = "settings.json"
HISTORY_FILE = "bet_history.json"


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": parse_mode
        })
    except Exception as e:
        log.error(f"Send error: {e}")

def send_keyboard(chat_id, text, buttons):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": buttons}
        })
    except Exception as e:
        log.error(f"Keyboard error: {e}")

def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def load_settings():
    return load_json(SETTINGS_FILE, {
        "stake": 1.00, "max_legs": 5,
        "min_odds": 1.40, "min_confidence": 40, "paused": False
    })

def save_settings(s): save_json(SETTINGS_FILE, s)
def load_history(): return load_json(HISTORY_FILE, [])
def load_last_slip(): return load_json("last_slip.json", None)


# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────

def handle_start(chat_id):
    send_keyboard(chat_id,
        "🤖 *BetBot v2*\n\nWhat do you want to do?",
        [
            [{"text": "📋 Today's Slip", "callback_data": "slip"},
             {"text": "▶️ Run Bot", "callback_data": "run"}],
            [{"text": "📊 Stats", "callback_data": "stats"},
             {"text": "📜 History", "callback_data": "history"}],
            [{"text": "📅 Upcoming", "callback_data": "upcoming"},
             {"text": "📈 Report", "callback_data": "report_weekly"}],
            [{"text": "⚙️ Settings", "callback_data": "settings"},
             {"text": "⏸ Pause", "callback_data": "pause"}],
        ]
    )

def handle_slip(chat_id):
    slip = load_last_slip()
    if not slip:
        send_message(chat_id, "⚠️ No slip found. Use /run to build one.")
        return

    lines = [f"📋 *Today's Slip* — {slip.get('built_at','')[:10]}\n"]
    for i, sel in enumerate(slip["selections"], 1):
        bet = sel['recommended_bet'].replace('_', ' ').upper()
        lines.append(
            f"{i}\\. *{sel['home']} vs {sel['away']}*\n"
            f"   `{bet}` @ *{sel['odds']}*\n"
            f"   Confidence: {sel['confidence']}%\n"
        )
    lines += [
        "━━━━━━━━━━━━━━━",
        f"📊 Odds: *{slip['combined_odds']}x*",
        f"💰 Stake: *€{slip['stake']}*",
        f"🏆 Potential: *€{slip['potential_payout']}*"
    ]
    send_keyboard(chat_id, "\n".join(lines), [
        [{"text": "▶️ Place Bet", "callback_data": "place_bet"},
         {"text": "↻ Rebuild", "callback_data": "run"}]
    ])

def handle_run(chat_id):
    settings = load_settings()
    if settings.get("paused"):
        send_message(chat_id, "⏸ Bot is paused. Use /resume first.")
        return

    send_message(chat_id, "⏳ *Running bot...*\nBuilding slip, this takes ~30 seconds.")

    def run_bot():
        try:
            from bot import ResearchEngine, OddsEngine, SlipBuilder, UnibetPlacer, TelegramNotifier
            notifier = TelegramNotifier()
            slip = SlipBuilder(ResearchEngine(), OddsEngine()).build_slip()
            if slip:
                notifier.notify_slip(slip)
                success = UnibetPlacer().place_bet(slip)
                notifier.notify_result(success, slip)
                log_history(slip, "pending")
            else:
                send_message(chat_id, "⚠️ No qualifying bets found today.")
        except Exception as e:
            send_message(chat_id, f"❌ Error: `{str(e)}`")

    threading.Thread(target=run_bot, daemon=True).start()

def handle_stats(chat_id):
    history = load_history()
    if not history:
        send_message(chat_id, "📊 No history yet. Run the bot first!")
        return

    total = len(history)
    wins = sum(1 for b in history if b["status"] == "win")
    losses = sum(1 for b in history if b["status"] == "loss")
    staked = sum(b.get("stake", 0) for b in history)
    returned = sum(b.get("return", 0) for b in history)
    net_pl = returned - staked
    win_rate = round(wins / total * 100, 1) if total else 0
    roi = round(net_pl / staked * 100, 1) if staked else 0
    pl_sign = "+" if net_pl >= 0 else ""
    pl_emoji = "📈" if net_pl >= 0 else "📉"

    send_keyboard(chat_id,
        f"📊 *Bot Statistics*\n\n"
        f"🎰 Total: *{total}* | ✅ {wins}W / ❌ {losses}L\n"
        f"📈 Win Rate: *{win_rate}%*\n"
        f"💰 Staked: *€{staked:.2f}*\n"
        f"💵 Returned: *€{returned:.2f}*\n"
        f"{pl_emoji} Net P&L: *{pl_sign}€{net_pl:.2f}*\n"
        f"📊 ROI: *{pl_sign}{roi}%*",
        [[{"text": "📅 Daily Report", "callback_data": "report_daily"},
          {"text": "📅 Weekly Report", "callback_data": "report_weekly"}],
         [{"text": "📅 Monthly Report", "callback_data": "report_monthly"}]]
    )

def handle_history(chat_id):
    history = load_history()
    if not history:
        send_message(chat_id, "📜 No history yet.")
        return
    lines = ["📜 *Recent Bets*\n"]
    for b in reversed(history[-7:]):
        emoji = {"win": "✅", "loss": "❌", "pending": "⏳"}.get(b["status"], "❓")
        ret = f"+€{b.get('return',0):.2f}" if b["status"] == "win" else "—"
        lines.append(f"{emoji} *{b.get('date','?')}* — {b.get('legs','?')}-fold @ {b.get('odds','?')}\n   Stake: €{b.get('stake',0):.2f} | Return: {ret}\n")
    send_message(chat_id, "\n".join(lines))

def handle_report(chat_id, period="weekly"):
    send_message(chat_id, f"⏳ Generating {period} report...")
    try:
        from analytics import generate_telegram_report
        report = generate_telegram_report(period)
        send_message(chat_id, report)
    except Exception as e:
        send_message(chat_id, f"❌ Report error: `{str(e)}`")

def handle_upcoming(chat_id):
    send_message(chat_id, "⏳ Loading upcoming high confidence picks...")
    try:
        from upcoming import get_upcoming_data
        data = get_upcoming_data()
        if not data:
            send_message(chat_id, "📅 No upcoming data. Use /preview to scan.")
            return

        high_conf = [m for m in data if m["confidence"] >= 65][:5]
        if not high_conf:
            send_message(chat_id, "📅 No high confidence picks found yet.")
            return

        lines = [f"🔥 *High Confidence Upcoming Picks*\n"]
        for m in high_conf:
            date = m.get("kick_off","")[:10]
            lines.append(
                f"*{m['home']} vs {m['away']}*\n"
                f"   📅 {date} | {m['league']}\n"
                f"   `{m['recommended_bet'].replace('_',' ').upper()}` | {m['confidence']}% confidence\n"
                f"   _{', '.join(m.get('reasoning',[])[:2])}_\n"
            )
        send_keyboard(chat_id, "\n".join(lines), [
            [{"text": "↻ Refresh Scan", "callback_data": "preview"}]
        ])
    except Exception as e:
        send_message(chat_id, f"❌ Error: `{str(e)}`")

def handle_preview(chat_id):
    send_message(chat_id, "⏳ Scanning next 7 days... this takes ~1 minute.")
    def run():
        try:
            from upcoming import send_daily_preview
            send_daily_preview()
        except Exception as e:
            send_message(chat_id, f"❌ Preview error: `{str(e)}`")
    threading.Thread(target=run, daemon=True).start()

def handle_settings(chat_id):
    s = load_settings()
    send_message(chat_id,
        f"⚙️ *Current Settings*\n\n"
        f"💰 Stake: *€{s['stake']}*\n"
        f"🎰 Max Legs: *{s['max_legs']}*\n"
        f"📊 Min Odds: *{s['min_odds']}*\n"
        f"🎯 Min Confidence: *{s['min_confidence']}%*\n"
        f"⏸ Paused: *{s.get('paused', False)}*\n\n"
        f"To change:\n"
        f"`/set stake 2.00`\n"
        f"`/set max_legs 6`\n"
        f"`/set min_odds 1.50`\n"
        f"`/set min_confidence 50`"
    )

def handle_set(chat_id, args):
    if len(args) < 2:
        send_message(chat_id, "Usage: `/set <key> <value>`")
        return
    key, value = args[0], args[1]
    valid = ["stake", "max_legs", "min_odds", "min_confidence"]
    if key not in valid:
        send_message(chat_id, f"❌ Valid keys: {', '.join(valid)}")
        return
    try:
        s = load_settings()
        s[key] = float(value) if "." in value else int(value)
        save_settings(s)
        send_message(chat_id, f"✅ *{key}* set to *{value}*")
    except:
        send_message(chat_id, f"❌ Invalid value: `{value}`")

def handle_pause(chat_id):
    s = load_settings(); s["paused"] = True; save_settings(s)
    send_message(chat_id, "⏸ *Bot paused.* Use /resume to re-enable.")

def handle_resume(chat_id):
    s = load_settings(); s["paused"] = False; save_settings(s)
    send_message(chat_id, "▶️ *Bot resumed.*")

def log_history(slip, status, ret=0):
    history = load_history()
    history.append({
        "date": datetime.utcnow().strftime("%d %b"),
        "date_full": datetime.utcnow().strftime("%Y-%m-%d"),
        "legs": len(slip["selections"]),
        "odds": slip["combined_odds"],
        "stake": slip["stake"],
        "return": ret,
        "status": status,
        "avg_confidence": round(sum(s["confidence"] for s in slip["selections"]) / len(slip["selections"]), 1)
    })
    save_json(HISTORY_FILE, history)


# ─────────────────────────────────────────
# UPDATE PROCESSOR
# ─────────────────────────────────────────

def process_update(update):
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        data = cq["data"]
        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": cq["id"]})

        handlers = {
            "slip": handle_slip, "run": handle_run, "stats": handle_stats,
            "history": handle_history, "settings": handle_settings,
            "pause": handle_pause, "upcoming": handle_upcoming, "preview": handle_preview,
            "report_daily": lambda c: handle_report(c, "daily"),
            "report_weekly": lambda c: handle_report(c, "weekly"),
            "report_monthly": lambda c: handle_report(c, "monthly"),
        }
        if data in handlers:
            handlers[data](chat_id)
        return

    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    if not text.startswith("/"): return

    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    args = parts[1:]

    command_map = {
        "start": lambda: handle_start(chat_id),
        "slip": lambda: handle_slip(chat_id),
        "run": lambda: handle_run(chat_id),
        "stats": lambda: handle_stats(chat_id),
        "history": lambda: handle_history(chat_id),
        "settings": lambda: handle_settings(chat_id),
        "set": lambda: handle_set(chat_id, args),
        "pause": lambda: handle_pause(chat_id),
        "resume": lambda: handle_resume(chat_id),
        "report": lambda: handle_report(chat_id, args[0] if args else "weekly"),
        "upcoming": lambda: handle_upcoming(chat_id),
        "preview": lambda: handle_preview(chat_id),
    }

    if cmd in command_map:
        command_map[cmd]()
    else:
        send_message(chat_id,
            "❓ Commands:\n"
            "/slip /run /stats /history\n"
            "/report daily|weekly|monthly\n"
            "/upcoming /preview\n"
            "/settings /set /pause /resume"
        )


# ─────────────────────────────────────────
# POLLING
# ─────────────────────────────────────────

def run_polling():
    log.info("🤖 Telegram bot polling started...")
    offset = 0
    while True:
        try:
            r = requests.get(f"{BASE_URL}/getUpdates",
                           params={"offset": offset, "timeout": 30}, timeout=35)
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                try: process_update(update)
                except Exception as e: log.error(f"Update error: {e}")
        except Exception as e:
            log.error(f"Polling error: {e}")
            import time; time.sleep(5)


if __name__ == "__main__":
    run_polling()
