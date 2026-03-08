"""
Railway API Server
Serves live bot data to the dashboard
Endpoints:
  GET /api/slip       - Today's slip
  GET /api/history    - Bet history
  GET /api/stats      - P&L stats
  GET /api/settings   - Current settings
  POST /api/settings  - Update settings
  POST /api/run       - Trigger bot manually
  GET /health         - Health check
"""

import json
import logging
import os
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ALLOWED_ORIGINS = ["*"]


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_stats():
    history = load_json("bet_history.json", [])
    if not history:
        return {"total": 0, "wins": 0, "losses": 0, "pending": 0,
                "total_staked": 0, "total_returned": 0, "net_pl": 0,
                "win_rate": 0, "roi": 0}

    total = len(history)
    wins = sum(1 for b in history if b["status"] == "win")
    losses = sum(1 for b in history if b["status"] == "loss")
    pending = sum(1 for b in history if b["status"] == "pending")
    total_staked = sum(b.get("stake", 0) for b in history)
    total_returned = sum(b.get("return", 0) for b in history)
    net_pl = total_returned - total_staked
    win_rate = round(wins / total * 100, 1) if total > 0 else 0
    roi = round(net_pl / total_staked * 100, 1) if total_staked > 0 else 0

    # P&L over time for chart
    pl_chart = []
    running = 0
    for b in history:
        running += b.get("return", 0) - b.get("stake", 0)
        pl_chart.append(round(running, 2))

    return {
        "total": total, "wins": wins, "losses": losses, "pending": pending,
        "total_staked": round(total_staked, 2),
        "total_returned": round(total_returned, 2),
        "net_pl": round(net_pl, 2),
        "win_rate": win_rate, "roi": roi,
        "pl_chart": pl_chart
    }


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self.send_json({"status": "ok", "ts": datetime.utcnow().isoformat()})

        elif path == "/api/slip":
            slip = load_json("last_slip.json", None)
            self.send_json(slip or {"error": "No slip found"})

        elif path == "/api/history":
            history = load_json("bet_history.json", [])
            self.send_json(list(reversed(history[-20:])))

        elif path == "/api/stats":
            self.send_json(get_stats())

        elif path == "/api/upcoming":
            upcoming = load_json("upcoming.json", [])
            self.send_json(upcoming)

        elif path == "/api/settings":
            settings = load_json("settings.json", {
                "stake": 1.00, "max_legs": 5,
                "min_odds": 1.40, "min_confidence": 40, "paused": False
            })
            self.send_json(settings)

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        if path == "/api/settings":
            settings = load_json("settings.json", {})
            settings.update(body)
            save_json("settings.json", settings)
            self.send_json({"ok": True, "settings": settings})

        elif path == "/api/run":
            def run_bot():
                try:
                    from bot import ResearchEngine, OddsEngine, SlipBuilder, UnibetPlacer, TelegramNotifier
                    notifier = TelegramNotifier()
                    slip = SlipBuilder(ResearchEngine(), OddsEngine()).build_slip()
                    if slip:
                        notifier.notify_slip(slip)
                        success = UnibetPlacer().place_bet(slip)
                        notifier.notify_result(success, slip)
                    else:
                        notifier.send("⚠️ No qualifying bets found.")
                except Exception as e:
                    log.error(f"Bot run error: {e}")

            thread = threading.Thread(target=run_bot)
            thread.daemon = True
            thread.start()
            self.send_json({"ok": True, "message": "Bot triggered — check Telegram"})

        elif path == "/api/history/update":
            history = load_json("bet_history.json", [])
            history.append(body)
            save_json("bet_history.json", history)
            self.send_json({"ok": True})

        else:
            self.send_json({"error": "Not found"}, 404)


def run_server(port=8080):
    port = int(os.getenv("PORT", port))
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    log.info(f"🌐 API server running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
