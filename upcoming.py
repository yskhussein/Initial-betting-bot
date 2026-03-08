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
    fixtures = []
    today = datetime.utcnow()

    for day_offset in range(1, days + 1):
        date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for league in LEAGUES:
            try:
                data = api_get("fixtures", {
                    "league": league["id"],
                    "date": date,
                    "season": today.year
                })
                for f in data:
                    f["_league_name"] = league["name"]
                fixtures.extend(data)
            except Exception as e:
                log.warning(f"Failed to fetch {league['name']} for {date}: {e}")

    return fixtures


# ─────────────────────────────────────────
# PRE-ANALYZE A FIXTURE
# ─────────────────────────────────────────

def pre_analyze(fixture):
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    league_id = fixture["league"]["id"]
    season = fixture["league"]["season"]
    home_name = fixture["teams"]["home"]["name"]
    away_name = fixture["teams"]["away"]["name"]
    kick_off = fixture["fixture"]["date"]

    # Fetch data
    h2h = api_get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": 10})
    home_form = api_get("fixtures", {"team": home_id, "last": 6, "status": "FT"})
    away_form = api_get("fixtures", {"team": away_id, "last": 6, "status": "FT"})
    predictions = api_get("predictions", {"fixture": fixture["fixture"]["id"]})
    home_injuries = api_get("injuries", {"team": home_id, "fixture": fixture["fixture"]["id"]})
    away_injuries = api_get("injuries", {"team": away_id, "fixture": fixture["fixture"]["id"]})

    score = 0
    reasoning = []
    bet = "home_win"

    # H2H
    if h2h:
        home_wins = sum(1 for f in h2h if f["teams"]["home"]["id"] == home_id and f["teams"]["home"]["winner"])
        away_wins = sum(1 for f in h2h if f["teams"]["away"]["id"] == away_id and f["teams"]["away"]["winner"])
        avg_goals = sum((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)
                       for f in h2h if f["goals"]["home"] is not None) / max(len(h2h), 1)

        if home_wins > away_wins:
            score += 20; bet = "home_win"
            reasoning.append(f"H2H: home won {home_wins}/{len(h2h)}")
        elif away_wins > home_wins:
            score += 15; bet = "away_win"
            reasoning.append(f"H2H: away won {away_wins}/{len(h2h)}")

        if avg_goals > 2.5:
            score += 10
            reasoning.append(f"H2H avg {avg_goals:.1f} goals")

    # Home form
    if home_form:
        wins = sum(1 for f in home_form
                  if (f["teams"]["home"]["id"] == home_id and f["teams"]["home"]["winner"]) or
                     (f["teams"]["away"]["id"] == home_id and f["teams"]["away"]["winner"]))
        if wins >= 4:
            score += 25
            reasoning.append(f"Home in great form ({wins}/6 wins)")
        elif wins >= 3:
            score += 15
            reasoning.append(f"Home in good form ({wins}/6 wins)")

    # Away form
    if away_form:
        losses = sum(1 for f in away_form
                    if (f["teams"]["home"]["id"] == away_id and f["teams"]["away"]["winner"]) or
                       (f["teams"]["away"]["id"] == away_id and f["teams"]["home"]["winner"]))
        if losses >= 4:
            score += 15
            reasoning.append(f"Away poor form ({losses}/6 losses)")

    # Injuries
    if len(away_injuries) > len(home_injuries) + 2:
        score += 10
        reasoning.append(f"Away missing {len(away_injuries)} players")

    # API prediction
    if predictions:
        winner = predictions[0].get("predictions", {}).get("winner", {})
        if winner.get("id") == home_id:
            score += 15
            reasoning.append(f"Model predicts: {winner.get('comment', 'Home win')}")
        elif winner.get("id") == away_id:
            score += 10; bet = "away_win"
            reasoning.append("Model predicts: Away win")

    confidence = min(score, 100)

    # Adjust bet based on confidence
    if confidence < 30:
        bet = "double_chance"

    return {
        "fixture_id": fixture["fixture"]["id"],
        "home": home_name,
        "away": away_name,
        "league": fixture.get("_league_name", fixture["league"]["name"]),
        "kick_off": kick_off,
        "confidence": confidence,
        "recommended_bet": bet,
        "reasoning": reasoning[:3]
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

    for fixture in fixtures[:50]:  # limit to avoid API rate limits
        try:
            result = pre_analyze(fixture)
            analyzed.append(result)
            if result["confidence"] >= HIGH_CONFIDENCE_THRESHOLD:
                high_confidence.append(result)
                log.info(f"🔥 High confidence: {result['home']} vs {result['away']} @ {result['confidence']}%")
        except Exception as e:
            log.warning(f"Analysis failed: {e}")

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
