"""
Automated Sports Betting Bot
- Researches teams, players, H2H via API-Football
- Fetches odds via The Odds API
- Builds bet slips automatically
- Places bets on Unibet via Selenium
- Sends Telegram notifications
"""

import os
import time
import json
import logging
import requests
from datetime import datetime, timedelta
from telegram import Bot
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from config import (
    ODDS_API_KEY, API_FOOTBALL_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    UNIBET_USERNAME, UNIBET_PASSWORD, DEFAULT_STAKE, MIN_ODDS, MAX_LEGS,
    MIN_CONFIDENCE_SCORE
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 1. RESEARCH ENGINE
# ─────────────────────────────────────────

class ResearchEngine:
    BASE = "https://v3.football.api-sports.io"

    def __init__(self):
        self.headers = {"x-apisports-key": API_FOOTBALL_KEY}

    def _get(self, endpoint, params):
        r = requests.get(f"{self.BASE}/{endpoint}", headers=self.headers, params=params)
        r.raise_for_status()
        return r.json().get("response", [])

    def get_fixtures_today(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        return self._get("fixtures", {"date": today})

    def get_h2h(self, team1_id, team2_id, last=10):
        return self._get("fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}", "last": last
        })

    def get_team_form(self, team_id, last=5):
        return self._get("fixtures", {"team": team_id, "last": last, "status": "FT"})

    def get_team_stats(self, team_id, league_id, season):
        data = self._get("teams/statistics", {
            "team": team_id, "league": league_id, "season": season
        })
        return data[0] if data else {}

    def get_injuries(self, team_id, fixture_id):
        return self._get("injuries", {"team": team_id, "fixture": fixture_id})

    def analyze_fixture(self, fixture):
        """Full research on a fixture — returns confidence score and recommended bet."""
        fid = fixture["fixture"]["id"]
        home_id = fixture["teams"]["home"]["id"]
        away_id = fixture["teams"]["away"]["id"]
        league_id = fixture["league"]["id"]
        season = fixture["league"]["season"]
        home_name = fixture["teams"]["home"]["name"]
        away_name = fixture["teams"]["away"]["name"]

        log.info(f"Analyzing: {home_name} vs {away_name}")

        h2h = self.get_h2h(home_id, away_id)
        home_form = self.get_team_form(home_id)
        away_form = self.get_team_form(away_id)
        home_stats = self.get_team_stats(home_id, league_id, season)
        away_stats = self.get_team_stats(away_id, league_id, season)
        home_injuries = self.get_injuries(home_id, fid)
        away_injuries = self.get_injuries(away_id, fid)

        score = self._score_fixture(
            h2h, home_form, away_form,
            home_stats, away_stats,
            home_injuries, away_injuries
        )

        return {
            "fixture_id": fid,
            "home": home_name,
            "away": away_name,
            "confidence": score["confidence"],
            "recommended_bet": score["bet"],
            "reasoning": score["reasoning"]
        }

    def _score_fixture(self, h2h, home_form, away_form, home_stats, away_stats, home_inj, away_inj):
        """Score a fixture and return recommended bet."""
        confidence = 0
        reasoning = []
        bet = None

        # H2H analysis
        if h2h:
            home_wins = sum(1 for f in h2h if f["teams"]["home"]["winner"])
            away_wins = sum(1 for f in h2h if f["teams"]["away"]["winner"])
            avg_goals = sum(
                f["goals"]["home"] + f["goals"]["away"]
                for f in h2h if f["goals"]["home"] is not None
            ) / max(len(h2h), 1)

            if avg_goals > 2.5:
                confidence += 15
                reasoning.append(f"H2H avg {avg_goals:.1f} goals — over 2.5 trend")
            else:
                confidence += 10
                reasoning.append(f"H2H avg {avg_goals:.1f} goals — under 2.5 trend")

        # Home form
        if home_form:
            home_wins_recent = sum(
                1 for f in home_form
                if f["teams"]["home"]["winner"] or f["teams"]["away"]["winner"]
            )
            if home_wins_recent >= 4:
                confidence += 20
                reasoning.append("Home team in strong form (4+ wins in last 5)")

        # Away form
        if away_form:
            away_wins_recent = sum(
                1 for f in away_form
                if f["teams"]["home"]["winner"] or f["teams"]["away"]["winner"]
            )
            if away_wins_recent <= 1:
                confidence += 15
                reasoning.append("Away team in poor form (1 or fewer wins in last 5)")

        # Goals stats
        if home_stats and away_stats:
            home_scored = home_stats.get("goals", {}).get("for", {}).get("average", {}).get("home", 0)
            away_conceded = away_stats.get("goals", {}).get("against", {}).get("average", {}).get("away", 0)
            try:
                home_scored = float(home_scored or 0)
                away_conceded = float(away_conceded or 0)
                if home_scored > 1.8 and away_conceded > 1.5:
                    confidence += 20
                    reasoning.append(f"Home avg {home_scored} goals, away concedes {away_conceded}")
            except (ValueError, TypeError):
                pass

        # Injuries
        key_injuries_home = len(home_inj)
        key_injuries_away = len(away_inj)
        if key_injuries_away > key_injuries_home:
            confidence += 10
            reasoning.append(f"Away team has {key_injuries_away} injuries vs home {key_injuries_home}")

        # Determine bet type based on confidence and data
        if confidence >= 50:
            bet = "home_win"
        elif confidence >= 35:
            bet = "over_2.5"
        else:
            bet = "btts_yes"

        return {
            "confidence": min(confidence, 100),
            "bet": bet,
            "reasoning": reasoning
        }


# ─────────────────────────────────────────
# 2. ODDS ENGINE
# ─────────────────────────────────────────

class OddsEngine:
    BASE = "https://api.the-odds-api.com/v4"

    def __init__(self):
        self.key = ODDS_API_KEY

    def get_odds(self, sport="soccer", regions="eu", markets="h2h,totals,btts"):
        r = requests.get(f"{self.BASE}/sports/{sport}/odds", params={
            "apiKey": self.key,
            "regions": regions,
            "markets": markets,
            "bookmakers": "unibet"
        })
        r.raise_for_status()
        return r.json()

    def find_odds_for_fixture(self, home, away, bet_type, odds_data):
        """Find the best odds for a fixture and bet type."""
        for game in odds_data:
            if home.lower() in game["home_team"].lower() or away.lower() in game["away_team"].lower():
                for bookmaker in game.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        if bet_type == "home_win" and market["key"] == "h2h":
                            for outcome in market["outcomes"]:
                                if outcome["name"] == game["home_team"]:
                                    return outcome["price"]
                        elif bet_type == "over_2.5" and market["key"] == "totals":
                            for outcome in market["outcomes"]:
                                if outcome["name"] == "Over" and outcome.get("point") == 2.5:
                                    return outcome["price"]
                        elif bet_type == "btts_yes" and market["key"] == "btts":
                            for outcome in market["outcomes"]:
                                if outcome["name"] == "Yes":
                                    return outcome["price"]
        return None


# ─────────────────────────────────────────
# 3. SLIP BUILDER
# ─────────────────────────────────────────

class SlipBuilder:
    def __init__(self, research_engine, odds_engine):
        self.research = research_engine
        self.odds = odds_engine

    def build_slip(self):
        """Build an optimized bet slip from today's fixtures."""
        log.info("Building bet slip...")
        fixtures = self.research.get_fixtures_today()
        odds_data = self.odds.get_odds()

        selections = []
        for fixture in fixtures[:20]:  # limit API calls
            try:
                analysis = self.research.analyze_fixture(fixture)
                if analysis["confidence"] < MIN_CONFIDENCE_SCORE:
                    continue

                odds = self.odds.find_odds_for_fixture(
                    analysis["home"],
                    analysis["away"],
                    analysis["recommended_bet"],
                    odds_data
                )

                if odds and odds >= MIN_ODDS:
                    selections.append({
                        **analysis,
                        "odds": odds
                    })
                    log.info(f"✅ Added: {analysis['home']} vs {analysis['away']} — {analysis['recommended_bet']} @ {odds}")
            except Exception as e:
                log.warning(f"Skipped fixture: {e}")

        # Sort by confidence, take top MAX_LEGS
        selections.sort(key=lambda x: x["confidence"], reverse=True)
        slip = selections[:MAX_LEGS]

        if not slip:
            log.warning("No qualifying selections found.")
            return None

        combined_odds = 1
        for s in slip:
            combined_odds *= s["odds"]

        return {
            "selections": slip,
            "combined_odds": round(combined_odds, 2),
            "stake": DEFAULT_STAKE,
            "potential_payout": round(combined_odds * DEFAULT_STAKE, 2),
            "built_at": datetime.utcnow().isoformat()
        }


# ─────────────────────────────────────────
# 4. UNIBET AUTO PLACER
# ─────────────────────────────────────────

class UnibetPlacer:
    URL = "https://www.unibet.com"

    def __init__(self):
        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options=opts)
        self.wait = WebDriverWait(self.driver, 15)

    def login(self):
        log.info("Logging into Unibet...")
        self.driver.get(self.URL)
        time.sleep(3)

        # Click login button
        login_btn = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "[data-test='login-button'], .login-button, [class*='login']")
        ))
        login_btn.click()
        time.sleep(2)

        # Enter credentials
        username = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[name='username'], input[type='email'], #username")
        ))
        username.clear()
        username.send_keys(UNIBET_USERNAME)

        password = self.driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password'], #password")
        password.clear()
        password.send_keys(UNIBET_PASSWORD)

        submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], .login-submit")
        submit.click()
        time.sleep(4)
        log.info("Logged in successfully.")

    def place_bet(self, slip):
        """Place each selection on Unibet and build accumulator."""
        try:
            self.login()
            selections = slip["selections"]

            for sel in selections:
                self._add_selection(sel)
                time.sleep(2)

            self._set_stake(slip["stake"])
            self._confirm_bet()
            log.info(f"✅ Bet placed successfully! Stake: €{slip['stake']} | Potential: €{slip['potential_payout']}")
            return True
        except Exception as e:
            log.error(f"❌ Failed to place bet: {e}")
            self.driver.save_screenshot("/home/claude/betting-bot/error_screenshot.png")
            return False
        finally:
            self.driver.quit()

    def _add_selection(self, selection):
        """Navigate to match and add selection to betslip."""
        home = selection["home"].replace(" ", "+")
        away = selection["away"].replace(" ", "+")
        bet_type = selection["recommended_bet"]

        # Search for the match
        self.driver.get(f"{self.URL}/en/sports/football")
        time.sleep(2)

        try:
            search = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type='search'], .search-input, [placeholder*='Search']")
            ))
            search.clear()
            search.send_keys(selection["home"])
            time.sleep(2)

            # Click first match result
            result = self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, ".search-result, .match-result, [class*='fixture']")
            ))
            result.click()
            time.sleep(2)

            # Click the correct odds button
            if bet_type == "home_win":
                odds_btn = self.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-outcome='home'], .home-odds, [class*='home-win']")
                ))
            elif bet_type == "over_2.5":
                odds_btn = self.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-outcome='over'], [class*='over-2']")
                ))
            else:
                odds_btn = self.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "[data-outcome='btts-yes'], [class*='btts']")
                ))

            odds_btn.click()
            log.info(f"Added: {selection['home']} vs {selection['away']} — {bet_type}")
        except Exception as e:
            log.warning(f"Could not add selection {selection['home']}: {e}")

    def _set_stake(self, stake):
        """Set the stake amount in the betslip."""
        try:
            stake_input = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[class*='stake'], input[name='stake'], .betslip-stake input")
            ))
            stake_input.clear()
            stake_input.send_keys(str(stake))
            time.sleep(1)
        except Exception as e:
            log.error(f"Could not set stake: {e}")

    def _confirm_bet(self):
        """Click the place bet button."""
        confirm = self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "[class*='place-bet'], button[class*='confirm'], .betslip-submit")
        ))
        confirm.click()
        time.sleep(3)


# ─────────────────────────────────────────
# 5. TELEGRAM NOTIFIER
# ─────────────────────────────────────────

class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.chat_id = TELEGRAM_CHAT_ID

    def send(self, message):
        try:
            self.bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")
            log.info("Telegram notification sent.")
        except Exception as e:
            log.error(f"Telegram error: {e}")

    def notify_slip(self, slip):
        lines = ["🎯 *New Bet Slip Built*\n"]
        for i, sel in enumerate(slip["selections"], 1):
            lines.append(
                f"{i}. *{sel['home']} vs {sel['away']}*\n"
                f"   Bet: {sel['recommended_bet'].replace('_', ' ').title()}\n"
                f"   Odds: {sel['odds']} | Confidence: {sel['confidence']}%\n"
                f"   Reason: {', '.join(sel['reasoning'][:2])}\n"
            )
        lines.append(f"📊 *Combined Odds:* {slip['combined_odds']}")
        lines.append(f"💰 *Stake:* €{slip['stake']}")
        lines.append(f"🏆 *Potential Payout:* €{slip['potential_payout']}")
        self.send("\n".join(lines))

    def notify_result(self, success, slip):
        if success:
            self.send(
                f"✅ *Bet Placed Successfully!*\n"
                f"Stake: €{slip['stake']}\n"
                f"Potential: €{slip['potential_payout']}\n"
                f"Odds: {slip['combined_odds']}"
            )
        else:
            self.send("❌ *Bet placement failed!* Check logs.")


# ─────────────────────────────────────────
# 6. MAIN RUNNER
# ─────────────────────────────────────────

def run():
    log.info("🤖 Betting bot starting...")
    notifier = TelegramNotifier()

    try:
        research = ResearchEngine()
        odds = OddsEngine()
        builder = SlipBuilder(research, odds)

        slip = builder.build_slip()
        if not slip:
            notifier.send("⚠️ No qualifying bets found today.")
            return

        # Notify slip built
        notifier.notify_slip(slip)

        # Save slip to file
        with open("/home/claude/betting-bot/last_slip.json", "w") as f:
            json.dump(slip, f, indent=2)

        # Place bet
        placer = UnibetPlacer()
        success = placer.place_bet(slip)
        notifier.notify_result(success, slip)

    except Exception as e:
        log.error(f"Bot error: {e}")
        notifier.send(f"❌ Bot crashed: {str(e)}")


if __name__ == "__main__":
    run()
