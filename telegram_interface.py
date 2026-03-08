"""
Telegram Bot Interface for BetBot
Commands:
  /start    - Welcome message
  /slip     - Show today's slip
  /run      - Trigger the bot manually
  /settings - View/change settings
  /history  - View recent bet history
  /stats    - Show P&L stats
  /pause    - Pause the bot
  /resume   - Resume the bot
"""

import os
import json
import logging
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SETTINGS_FILE = "settings.json"
HISTORY_FILE = "bet_history.json"
BOT_PAUSED = False


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def send_message(chat_id, text, parse_mode="Markdown"):
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    })

def send_keyboard(chat_id, text, buttons):
    """Send message with inline keyboard."""
    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": buttons
        }
    })

def load_settings():
    default = {
        "stake": 1.00,
        "max_legs": 5,
        "min_odds": 1.40,
        "min_confidence": 40,
        "paused": False
    }
    try:
        with open(SETTINGS_FILE) as f:
            return {**default, **json.load(f)}
    except:
        return default

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except:
        return []

def load_last_slip():
    try:
        with open("last_slip.json") as f:
            return json.load(f)
    except:
        return None


# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────

def handle_start(chat_id):
    send_keyboard(chat_id,
        "🤖 *BetBot Dashboard*\n\nWelcome back. What do you want to do?",
        [
            [{"text": "📋 Today's Slip", "callback_data": "slip"},
             {"text": "▶️ Run Bot", "callback_data": "run"}],
            [{"text": "📊 Stats", "callback_data": "stats"},
             {"text": "📜 History", "callback_data": "history"}],
            [{"text": "⚙️ Settings", "callback_data": "settings"},
             {"text": "⏸ Pause Bot", "callback_data": "pause"}],
        ]
    )

def handle_slip(chat_id):
    slip = load_last_slip()
    if not slip:
        send_message(chat_id, "⚠️ No slip found. Run the bot first with /run")
        return

    settings = load_settings()
    lines = [f"📋 *Today's Slip* — {slip.get('built_at', '')[:10]}\n"]

    for i, sel in enumerate(slip["selections"], 1):
        lines.append(
            f"{i}\\. *{sel['home']} vs {sel['away']}*\n"
            f"   `{sel['recommended_bet'].replace('_', ' ').upper()}` @ *{sel['odds']}*\n"
            f"   Confidence: {sel['confidence']}%\n"
        )

    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"📊 Combined Odds: *{slip['combined_odds']}*")
    lines.append(f"💰 Stake: *€{slip['stake']}*")
    lines.append(f"🏆 Potential: *€{slip['potential_payout']}*")

    send_keyboard(chat_id, "\n".join(lines), [
        [{"text": "▶️ Place This Bet", "callback_data": "place_bet"},
         {"text": "↻ Rebuild Slip", "callback_data": "run"}]
    ])

def handle_run(chat_id):
    settings = load_settings()
    if settings.get("paused"):
        send_message(chat_id, "⏸ Bot is paused. Use /resume to enable it.")
        return

    send_message(chat_id, "⏳ *Running bot...*\nResearching fixtures and building slip. This takes ~30 seconds.")

    try:
        # Import and run bot
        from bot import ResearchEngine, OddsEngine, SlipBuilder, UnibetPlacer
        research = ResearchEngine()
        odds_engine = OddsEngine()
        builder = SlipBuilder(research, odds_engine)
        slip = builder.build_slip()

        if not slip:
            send_message(chat_id, "⚠️ No qualifying bets found today.")
            return

        # Save slip
        with open("last_slip.json", "w") as f:
            json.dump(slip, f, indent=2)

        # Show slip
        handle_slip(chat_id)

        # Place bet
        send_message(chat_id, "🎯 Placing bet on Unibet...")
        placer = UnibetPlacer()
        success = placer.place_bet(slip)

        if success:
            send_message(chat_id, f"✅ *Bet placed!*\nStake: €{slip['stake']} | Potential: €{slip['potential_payout']}")
            log_history(slip, "pending")
        else:
            send_message(chat_id, "❌ Bet placement failed. Check logs.")

    except Exception as e:
        send_message(chat_id, f"❌ Bot error: `{str(e)}`")

def handle_stats(chat_id):
    history = load_history()

    if not history:
        send_message(chat_id, "📊 No bet history yet. Run the bot first!")
        return

    total = len(history)
    wins = sum(1 for b in history if b["status"] == "win")
    losses = sum(1 for b in history if b["status"] == "loss")
    total_staked = sum(b["stake"] for b in history)
    total_returned = sum(b.get("return", 0) for b in history)
    net_pl = total_returned - total_staked
    win_rate = (wins / total * 100) if total > 0 else 0
    roi = (net_pl / total_staked * 100) if total_staked > 0 else 0

    pl_emoji = "📈" if net_pl >= 0 else "📉"
    pl_sign = "+" if net_pl >= 0 else ""

    send_message(chat_id,
        f"📊 *Bot Statistics*\n\n"
        f"🎰 Total Bets: *{total}*\n"
        f"✅ Wins: *{wins}*\n"
        f"❌ Losses: *{losses}*\n"
        f"📈 Win Rate: *{win_rate:.1f}%*\n\n"
        f"💰 Total Staked: *€{total_staked:.2f}*\n"
        f"💵 Total Returned: *€{total_returned:.2f}*\n"
        f"{pl_emoji} Net P&L: *{pl_sign}€{net_pl:.2f}*\n"
        f"📊 ROI: *{pl_sign}{roi:.1f}%*"
    )

def handle_history(chat_id):
    history = load_history()

    if not history:
        send_message(chat_id, "📜 No bet history yet.")
        return

    recent = history[-7:]
    lines = ["📜 *Recent Bets*\n"]

    for b in reversed(recent):
        status_emoji = {"win": "✅", "loss": "❌", "pending": "⏳"}.get(b["status"], "❓")
        ret = f"+€{b.get('return', 0):.2f}" if b["status"] == "win" else "—"
        lines.append(
            f"{status_emoji} *{b['date']}* — {b['legs']}-fold @ {b['odds']}\n"
            f"   Stake: €{b['stake']:.2f} | Return: {ret}\n"
        )

    send_message(chat_id, "\n".join(lines))

def handle_settings(chat_id):
    settings = load_settings()
    send_message(chat_id,
        f"⚙️ *Current Settings*\n\n"
        f"💰 Stake: *€{settings['stake']}*\n"
        f"🎰 Max Legs: *{settings['max_legs']}*\n"
        f"📊 Min Odds: *{settings['min_odds']}*\n"
        f"🎯 Min Confidence: *{settings['min_confidence']}%*\n"
        f"⏸ Paused: *{settings.get('paused', False)}*\n\n"
        f"To change a setting, send:\n"
        f"`/set stake 2.00`\n"
        f"`/set max_legs 6`\n"
        f"`/set min_odds 1.50`\n"
        f"`/set min_confidence 50`"
    )

def handle_set(chat_id, args):
    if len(args) < 2:
        send_message(chat_id, "Usage: `/set <key> <value>`\nExample: `/set stake 2.00`")
        return

    key, value = args[0], args[1]
    settings = load_settings()
    valid_keys = ["stake", "max_legs", "min_odds", "min_confidence"]

    if key not in valid_keys:
        send_message(chat_id, f"❌ Unknown setting. Valid: {', '.join(valid_keys)}")
        return

    try:
        settings[key] = float(value) if "." in value else int(value)
        save_settings(settings)
        send_message(chat_id, f"✅ *{key}* set to *{value}*")
    except ValueError:
        send_message(chat_id, f"❌ Invalid value: `{value}`")

def handle_pause(chat_id):
    settings = load_settings()
    settings["paused"] = True
    save_settings(settings)
    send_message(chat_id, "⏸ *Bot paused.* No bets will be placed.\nUse /resume to re-enable.")

def handle_resume(chat_id):
    settings = load_settings()
    settings["paused"] = False
    save_settings(settings)
    send_message(chat_id, "▶️ *Bot resumed.* Bets will run as scheduled.")

def log_history(slip, status, ret=0):
    history = load_history()
    history.append({
        "date": datetime.utcnow().strftime("%d %b"),
        "legs": len(slip["selections"]),
        "odds": slip["combined_odds"],
        "stake": slip["stake"],
        "return": ret,
        "status": status
    })
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ─────────────────────────────────────────
# WEBHOOK / POLLING HANDLER
# ─────────────────────────────────────────

def process_update(update):
    """Process incoming Telegram update."""
    # Handle callback queries (button presses)
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        data = cq["data"]

        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": cq["id"]})

        handlers = {
            "slip": handle_slip,
            "run": handle_run,
            "stats": handle_stats,
            "history": handle_history,
            "settings": handle_settings,
            "pause": handle_pause,
        }
        if data in handlers:
            handlers[data](chat_id)
        return

    # Handle text messages
    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    if not text.startswith("/"):
        return

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
    }

    if cmd in command_map:
        command_map[cmd]()
    else:
        send_message(chat_id,
            "❓ Unknown command. Available:\n"
            "/slip — Today's slip\n"
            "/run — Run bot now\n"
            "/stats — P&L stats\n"
            "/history — Recent bets\n"
            "/settings — View settings\n"
            "/set <key> <value> — Change setting\n"
            "/pause — Pause bot\n"
            "/resume — Resume bot"
        )


# ─────────────────────────────────────────
# POLLING LOOP (for local/GitHub Actions)
# ─────────────────────────────────────────

def run_polling():
    log.info("🤖 Telegram bot polling started...")
    offset = 0

    while True:
        try:
            r = requests.get(f"{BASE_URL}/getUpdates", params={
                "offset": offset,
                "timeout": 30
            }, timeout=35)
            updates = r.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                try:
                    process_update(update)
                except Exception as e:
                    log.error(f"Error processing update: {e}")

        except Exception as e:
            log.error(f"Polling error: {e}")
            import time; time.sleep(5)


if __name__ == "__main__":
    run_polling()
