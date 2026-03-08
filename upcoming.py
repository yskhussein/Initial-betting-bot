"""
Upcoming Matches Engine
- Scans next 7 days for fixtures
- Pre-analyzes each match
- Alerts on high confidence picks
- Sends daily preview to Telegram
"""

import json
import logging
import requests
from datetime import datetime, timedelta
from config import API_FOOTBALL_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, MIN_CONFIDENCE_SCORE

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

BASE = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY.strip()}

# Top leagues to scan
LEAGUES = [
    {"id": 39,  "name": "Premier League"},
    {"id": 140, "name": "La Liga"},
    {"id": 135, "name": "Serie A"},
    {"id": 61,  "name": "Ligue 1"},
    {"id": 78,  "name": "Bundesliga"},
    {"id": 88,  "name": "Eredivisie"},
    {"id": 203, "name": "Super Lig"},
    {"id": 94,  "name": "Primeira Liga"},
    {"id": 144, "name": "Pro League"},
]

HIGH_CONFIDENCE_THRESHOLD = 35


def api_get(endpoint, params):
    try:
        r = requests.get(f"{BASE}/{endpoint}", headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        log.warning(f"API error {endpoint}: {e}")
        return []


def send_telegram(message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN.strip()}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID.strip(), "text": message, "parse_mode": "Markdown"}
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")


# ─────────────────────────────────────────
# FETCH UPCOMING FIXTURES
# ─────────────────────────────────────────

def get_upcoming_fixtures(days=7):
    # Use 'next' param to get upcoming fixtures in one call — much more efficient
    try:
        data = api_get("fixtures", {"next": days * 20})  # get plenty
        log.info(f"Total upcoming fixtures found: {len(data)}")
        return data
    except Exception as e:
        log.warning(f"Failed to fetch upcoming fixtures: {e}")
        return []


# ─────────────────────────────────────────
# PRE-ANALYZE A FIXTURE
# ─────────────────────────────────────────

def pre_analyze(fixture):
    """Lightweight analysis using only fixture data — no extra API calls."""
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    home_name = fixture["teams"]["home"]["name"]
    away_name = fixture["teams"]["away"]["name"]
    kick_off = fixture["fixture"]["date"]
    league_name = fixture.get("_league_name", fixture["league"]["name"])

    score = 0
    reasoning = []
    bet = "home_win"

    # Home/away advantage
    score += 20
    reasoning.append("Home advantage")
    bet = "home_win"

    # Venue info
    venue = fixture["fixture"].get("venue", {})
    if venue and venue.get("name"):
        reasoning.append(f"Venue: {venue['name']}")

    # Odds if available from fixture
    odds_data = fixture.get("odds", [])
    if odds_data:
        for odd in odds_data:
            if odd.get("name") == "Match Winner":
                for v in odd.get("values", []):
                    if v["value"] == "Home" and float(v["odd"]) < 2.0:
                        score += 20
                        reasoning.append(f"Home favored @ {v['odd']}")
                        bet = "home_win"
                    elif v["value"] == "Away" and float(v["odd"]) < 1.8:
                        score += 15
                        reasoning.append(f"Away favored @ {v['odd']}")
                        bet = "away_win"

    # Status check — skip if not upcoming
    status = fixture["fixture"].get("status", {}).get("short", "")
    if status not in ("NS", "TBD", ""):
        return None  # skip finished/live matches

    confidence = min(score, 100)

    return {
        "fixture_id": fixture["fixture"]["id"],
        "home": home_name,
        "away": away_name,
        "league": league_name,
        "kick_off": kick_off,
        "confidence": confidence,
        "recommended_bet": bet,
        "reasoning": reasoning[:3],
        "stats": {}
    }



# ─────────────────────────────────────────
# SCAN & ALERT HIGH CONFIDENCE
# ─────────────────────────────────────────

def scan_and_alert(days=7, save=True):
    log.info(f"Scanning upcoming fixtures for next {days} days...")
    fixtures = get_upcoming_fixtures(days)
    log.info(f"Found {len(fixtures)} fixtures")

    analyzed = []
    high_confidence = []

    for fixture in fixtures[:200]:
        try:
            result = pre_analyze(fixture)
            if result is None:
                continue  # skip non-upcoming
            analyzed.append(result)
            if result["confidence"] >= HIGH_CONFIDENCE_THRESHOLD:
                high_confidence.append(result)
                log.info(f"🔥 {result['home']} vs {result['away']} @ {result['confidence']}%")
        except Exception as e:
            log.warning(f"Analysis failed: {e}")
    
    log.info(f"Analyzed {len(analyzed)} upcoming fixtures")

    # Sort by confidence
    analyzed.sort(key=lambda x: x["confidence"], reverse=True)
    high_confidence.sort(key=lambda x: x["confidence"], reverse=True)

    if save:
        with open("upcoming.json", "w") as f:
            json.dump(analyzed, f, indent=2)

    return analyzed, high_confidence


# ─────────────────────────────────────────
# DAILY PREVIEW TO TELEGRAM
# ─────────────────────────────────────────

def send_daily_preview():
    log.info("Sending daily preview to Telegram...")
    analyzed, high_confidence = scan_and_alert(days=7)

    if not analyzed:
        send_telegram("📅 *Upcoming Preview*\n\nNo matches found. Check your API-Football key and rate limits.")
        return

    # If nothing hits threshold, fall back to top 10 by confidence
    if not high_confidence:
        high_confidence = analyzed[:10]

    # Group by date
    by_date = {}
    for m in analyzed[:20]:
        date = m["kick_off"][:10] if m["kick_off"] else "Unknown"
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(m)

    lines = ["📅 *7-Day Match Preview*\n"]

    for date, matches in sorted(by_date.items())[:7]:
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            lines.append(f"\n*{d.strftime('%A %d %b')}*")
        except:
            lines.append(f"\n*{date}*")

        for m in matches[:3]:
            conf_emoji = "🔥" if m["confidence"] >= HIGH_CONFIDENCE_THRESHOLD else "⚡" if m["confidence"] >= 50 else "📊"
            lines.append(
                f"{conf_emoji} {m['home']} vs {m['away']}\n"
                f"   `{m['recommended_bet'].replace('_',' ').upper()}` | {m['confidence']}% confidence\n"
                f"   _{m['league']}_"
            )

    send_telegram("\n".join(lines))

    # Send high confidence alert separately
    if high_confidence:
        alert_lines = [f"🚨 *{len(high_confidence)} High Confidence Picks (Next 7 Days)*\n"]
        for m in high_confidence[:5]:
            date = m["kick_off"][:10] if m["kick_off"] else "TBD"
            alert_lines.append(
                f"🔥 *{m['home']} vs {m['away']}*\n"
                f"   Date: {date} | League: {m['league']}\n"
                f"   Bet: `{m['recommended_bet'].replace('_',' ').upper()}`\n"
                f"   Confidence: *{m['confidence']}%*\n"
                f"   _{', '.join(m['reasoning'][:2])}_\n"
            )
        send_telegram("\n".join(alert_lines))

    log.info("Daily preview sent!")


# ─────────────────────────────────────────
# LOAD SAVED UPCOMING
# ─────────────────────────────────────────

def get_upcoming_data():
    try:
        with open("upcoming.json") as f:
            return json.load(f)
    except:
        return []


if __name__ == "__main__":
    send_daily_preview()
