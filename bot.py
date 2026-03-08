"""
Automated Sports Betting Bot v2
- Improved research: form, H2H, injuries, league position, predictions
- 8 bet types: home_win, away_win, draw, over_2.5, btts_yes,
  draw_no_bet, double_chance, asian_handicap
- Places bets on Unibet via Selenium
- Sends Telegram notifications
"""

import os
import time
import json
import logging
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from config import (
    ODDS_API_KEY, API_FOOTBALL_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    UNIBET_USERNAME, UNIBET_PASSWORD, DEFAULT_STAKE, MIN_ODDS, MAX_LEGS,
    MIN_CONFIDENCE_SCORE
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
# 1. RESEARCH ENGINE (IMPROVED)
# ─────────────────────────────────────────

class ResearchEngine:
    BASE = "https://v3.football.api-sports.io"

    def __init__(self):
        self.headers = {"x-apisports-key": API_FOOTBALL_KEY.strip()}

    def _get(self, endpoint, params):
        try:
            r = requests.get(f"{self.BASE}/{endpoint}", headers=self.headers, params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("response", [])
        except Exception as e:
            log.warning(f"API error {endpoint}: {e}")
            return []

    def get_fixtures_today(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        return self._get("fixtures", {"date": today})

    def get_h2h(self, team1_id, team2_id, last=10):
        return self._get("fixtures/headtohead", {"h2h": f"{team1_id}-{team2_id}", "last": last})

    def get_team_form(self, team_id, last=6):
        return self._get("fixtures", {"team": team_id, "last": last, "status": "FT"})

    def get_team_stats(self, team_id, league_id, season):
        data = self._get("teams/statistics", {"team": team_id, "league": league_id, "season": season})
        return data[0] if data else {}

    def get_injuries(self, team_id, fixture_id):
        return self._get("injuries", {"team": team_id, "fixture": fixture_id})

    def get_standings(self, league_id, season):
        data = self._get("standings", {"league": league_id, "season": season})
        if data and data[0].get("league", {}).get("standings"):
            return data[0]["league"]["standings"][0]
        return []

    def get_predictions(self, fixture_id):
        data = self._get("predictions", {"fixture": fixture_id})
        return data[0] if data else {}

    def analyze_fixture(self, fixture):
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
        standings = self.get_standings(league_id, season)
        predictions = self.get_predictions(fid)

        score = self._score_fixture(
            h2h, home_form, away_form, home_stats, away_stats,
            home_injuries, away_injuries, standings, predictions, home_id, away_id
        )

        return {
            "fixture_id": fid,
            "home": home_name,
            "away": away_name,
            "league": fixture["league"]["name"],
            "confidence": score["confidence"],
            "recommended_bet": score["bet"],
            "reasoning": score["reasoning"],
            "stats": score["stats"]
        }

    def _get_team_position(self, standings, team_id):
        for team in standings:
            if team["team"]["id"] == team_id:
                return team["rank"], team["points"], team["goalsDiff"]
        return None, None, None

    def _score_fixture(self, h2h, home_form, away_form, home_stats, away_stats,
                       home_inj, away_inj, standings, predictions, home_id, away_id):
        reasoning = []
        stats = {}
        scores = {
            "home_win": 0, "away_win": 0, "draw": 0,
            "over_2.5": 0, "btts_yes": 0,
            "draw_no_bet": 0, "double_chance": 0, "asian_handicap": 0
        }

        # H2H
        if h2h:
            home_h2h_wins = sum(1 for f in h2h if f["teams"]["home"]["id"] == home_id and f["teams"]["home"]["winner"])
            away_h2h_wins = sum(1 for f in h2h if f["teams"]["away"]["id"] == away_id and f["teams"]["away"]["winner"])
            avg_goals = sum((f["goals"]["home"] or 0) + (f["goals"]["away"] or 0)
                           for f in h2h if f["goals"]["home"] is not None) / max(len(h2h), 1)
            stats.update({"h2h_home_wins": home_h2h_wins, "h2h_away_wins": away_h2h_wins, "h2h_avg_goals": round(avg_goals, 2)})

            if home_h2h_wins > away_h2h_wins:
                scores["home_win"] += 20; scores["draw_no_bet"] += 15
                reasoning.append(f"H2H: home won {home_h2h_wins}/{len(h2h)} meetings")
            elif away_h2h_wins > home_h2h_wins:
                scores["away_win"] += 20
                reasoning.append(f"H2H: away won {away_h2h_wins}/{len(h2h)} meetings")

            if avg_goals > 2.5:
                scores["over_2.5"] += 20; scores["btts_yes"] += 15
                reasoning.append(f"H2H avg {avg_goals:.1f} goals — high scoring")
            else:
                reasoning.append(f"H2H avg {avg_goals:.1f} goals — low scoring")

        # Home form
        if home_form:
            results, goals_scored, goals_conceded = [], [], []
            for f in home_form:
                is_home = f["teams"]["home"]["id"] == home_id
                s = f["goals"]["home"] if is_home else f["goals"]["away"]
                c = f["goals"]["away"] if is_home else f["goals"]["home"]
                if s is not None:
                    goals_scored.append(s); goals_conceded.append(c or 0)
                won = f["teams"]["home"]["winner"] if is_home else f["teams"]["away"]["winner"]
                results.append("W" if won else ("D" if not f["teams"]["home"]["winner"] and not f["teams"]["away"]["winner"] else "L"))

            wins = results.count("W")
            avg_s = sum(goals_scored) / max(len(goals_scored), 1)
            avg_c = sum(goals_conceded) / max(len(goals_conceded), 1)
            clean_sheets = sum(1 for g in goals_conceded if g == 0)
            stats.update({"home_form": "".join(results), "home_avg_scored": round(avg_s, 2),
                          "home_avg_conceded": round(avg_c, 2), "home_clean_sheets": clean_sheets})

            if wins >= 4:
                scores["home_win"] += 25; scores["draw_no_bet"] += 20; scores["double_chance"] += 15
                reasoning.append(f"Home excellent form: {wins}/6 wins")
            elif wins >= 3:
                scores["home_win"] += 15; scores["double_chance"] += 10
                reasoning.append(f"Home good form: {wins}/6 wins")
            if avg_s > 2.0:
                scores["over_2.5"] += 15; scores["btts_yes"] += 10
                reasoning.append(f"Home scoring {avg_s:.1f} goals/game")
            if clean_sheets >= 3:
                scores["btts_yes"] -= 10

        # Away form
        if away_form:
            results, goals_scored, goals_conceded = [], [], []
            for f in away_form:
                is_away = f["teams"]["away"]["id"] == away_id
                s = f["goals"]["away"] if is_away else f["goals"]["home"]
                c = f["goals"]["home"] if is_away else f["goals"]["away"]
                if s is not None:
                    goals_scored.append(s); goals_conceded.append(c or 0)
                won = f["teams"]["away"]["winner"] if is_away else f["teams"]["home"]["winner"]
                results.append("W" if won else ("D" if not f["teams"]["home"]["winner"] and not f["teams"]["away"]["winner"] else "L"))

            wins = results.count("W"); losses = results.count("L")
            avg_s = sum(goals_scored) / max(len(goals_scored), 1)
            avg_c = sum(goals_conceded) / max(len(goals_conceded), 1)
            stats.update({"away_form": "".join(results), "away_avg_scored": round(avg_s, 2), "away_avg_conceded": round(avg_c, 2)})

            if losses >= 4:
                scores["home_win"] += 20; scores["asian_handicap"] += 15
                reasoning.append(f"Away poor form: {losses}/6 losses")
            if avg_c > 2.0:
                scores["over_2.5"] += 15; scores["btts_yes"] += 10
                reasoning.append(f"Away conceding {avg_c:.1f} goals/game")

        # Injuries
        stats.update({"home_injuries": len(home_inj), "away_injuries": len(away_inj)})
        if len(away_inj) > len(home_inj) + 2:
            scores["home_win"] += 15; scores["draw_no_bet"] += 10
            reasoning.append(f"Away missing {len(away_inj)} players")
        elif len(home_inj) > len(away_inj) + 2:
            scores["away_win"] += 10
            reasoning.append(f"Home missing {len(home_inj)} players")

        # Standings
        if standings:
            home_pos, _, _ = self._get_team_position(standings, home_id)
            away_pos, _, _ = self._get_team_position(standings, away_id)
            if home_pos and away_pos:
                stats.update({"home_position": home_pos, "away_position": away_pos})
                if away_pos - home_pos >= 5:
                    scores["home_win"] += 20; scores["asian_handicap"] += 15
                    reasoning.append(f"Home #{home_pos} vs Away #{away_pos} in table")
                elif home_pos - away_pos >= 5:
                    scores["away_win"] += 15
                    reasoning.append(f"Away #{away_pos} significantly higher in table")

        # API predictions
        if predictions:
            winner = predictions.get("predictions", {}).get("winner", {})
            if winner.get("id") == home_id:
                scores["home_win"] += 15
                reasoning.append(f"Prediction: {winner.get('comment', 'Home favored')}")
            elif winner.get("id") == away_id:
                scores["away_win"] += 15
                reasoning.append("Prediction: Away favored")

        # Pick best bet
        best_bet = max(scores, key=scores.get)
        confidence = min(scores[best_bet], 100)

        if confidence < MIN_CONFIDENCE_SCORE:
            best_bet = "double_chance"
            confidence = 30

        return {"confidence": confidence, "bet": best_bet, "reasoning": reasoning[:4], "stats": stats}


# ─────────────────────────────────────────
# 2. ODDS ENGINE (EXPANDED)
# ─────────────────────────────────────────

class OddsEngine:
    BASE = "https://api.the-odds-api.com/v4"
    SPORTS = [
        "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
        "soccer_france_ligue_one", "soccer_germany_bundesliga",
        "soccer_netherlands_eredivisie", "soccer_turkey_super_league"
    ]
    MARKETS = "h2h,totals,btts,asian_handicaps,double_chance,draw_no_bet"

    def __init__(self):
        self.key = ODDS_API_KEY.strip()

    def get_odds(self, regions="eu"):
        all_odds = []
        for sport in self.SPORTS:
            try:
                r = requests.get(f"{self.BASE}/sports/{sport}/odds", params={
                    "apiKey": self.key, "regions": regions,
                    "markets": self.MARKETS, "bookmakers": "unibet"
                }, timeout=10)
                if r.status_code == 200:
                    all_odds.extend(r.json())
            except Exception as e:
                log.warning(f"Odds fetch failed {sport}: {e}")
        return all_odds

    def find_odds_for_fixture(self, home, away, bet_type, odds_data):
        for game in odds_data:
            h = game.get("home_team", "").lower()
            a = game.get("away_team", "").lower()
            if home.lower()[:5] in h or away.lower()[:5] in a:
                for bookmaker in game.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        result = self._extract(market, bet_type, game)
                        if result:
                            return result
        return None

    def _extract(self, market, bet_type, game):
        key = market["key"]
        outcomes = market["outcomes"]

        if bet_type == "home_win" and key == "h2h":
            for o in outcomes:
                if o["name"] == game["home_team"]: return o["price"]
        elif bet_type == "away_win" and key == "h2h":
            for o in outcomes:
                if o["name"] == game["away_team"]: return o["price"]
        elif bet_type == "draw" and key == "h2h":
            for o in outcomes:
                if o["name"] == "Draw": return o["price"]
        elif bet_type == "over_2.5" and key == "totals":
            for o in outcomes:
                if o["name"] == "Over" and o.get("point") == 2.5: return o["price"]
        elif bet_type == "btts_yes" and key == "btts":
            for o in outcomes:
                if o["name"] == "Yes": return o["price"]
        elif bet_type == "draw_no_bet" and key == "draw_no_bet":
            for o in outcomes:
                if o["name"] == game["home_team"]: return o["price"]
        elif bet_type == "double_chance" and key == "double_chance":
            for o in outcomes:
                if game["home_team"][:5] in o["name"]: return o["price"]
        elif bet_type == "asian_handicap" and key == "asian_handicaps":
            for o in outcomes:
                if o["name"] == game["home_team"] and o.get("point", 0) in [-0.5, -1.0]: return o["price"]
        return None


# ─────────────────────────────────────────
# 3. SLIP BUILDER
# ─────────────────────────────────────────

class SlipBuilder:
    def __init__(self, research_engine, odds_engine):
        self.research = research_engine
        self.odds = odds_engine

    def build_slip(self):
        log.info("Building bet slip...")
        fixtures = self.research.get_fixtures_today()
        if not fixtures:
            return None

        odds_data = self.odds.get_odds()
        selections = []

        for fixture in fixtures[:25]:
            try:
                analysis = self.research.analyze_fixture(fixture)
                if analysis["confidence"] < MIN_CONFIDENCE_SCORE:
                    continue

                odds = self.odds.find_odds_for_fixture(
                    analysis["home"], analysis["away"], analysis["recommended_bet"], odds_data
                )
                if not odds:
                    odds = self.odds.find_odds_for_fixture(
                        analysis["home"], analysis["away"], "double_chance", odds_data
                    )
                    if odds:
                        analysis["recommended_bet"] = "double_chance"

                if odds and odds >= MIN_ODDS:
                    selections.append({**analysis, "odds": odds})
                    log.info(f"✅ {analysis['home']} vs {analysis['away']} — {analysis['recommended_bet']} @ {odds}")
            except Exception as e:
                log.warning(f"Skipped: {e}")

        selections.sort(key=lambda x: x["confidence"], reverse=True)
        slip = selections[:MAX_LEGS]
        if not slip:
            return None

        combined_odds = 1
        for s in slip:
            combined_odds *= s["odds"]

        result = {
            "selections": slip,
            "combined_odds": round(combined_odds, 2),
            "stake": DEFAULT_STAKE,
            "potential_payout": round(combined_odds * DEFAULT_STAKE, 2),
            "built_at": datetime.utcnow().isoformat()
        }

        with open("last_slip.json", "w") as f:
            json.dump(result, f, indent=2)

        return result


# ─────────────────────────────────────────
# 4. UNIBET AUTO PLACER
# ─────────────────────────────────────────

class UnibetPlacer:
    URL = "https://www.unibet.com"
    BET_SELECTORS = {
        "home_win": "[data-outcome='home'], [class*='HomeWin']",
        "away_win": "[data-outcome='away'], [class*='AwayWin']",
        "draw": "[data-outcome='draw'], [class*='Draw']",
        "over_2.5": "[data-outcome='over'], [class*='Over25']",
        "btts_yes": "[data-outcome='btts-yes'], [class*='BothScore']",
        "draw_no_bet": "[data-outcome='dnb-home'], [class*='DNB']",
        "double_chance": "[data-outcome='dc-home'], [class*='DoubleChance']",
        "asian_handicap": "[data-outcome='ah-home'], [class*='AsianHandicap']",
    }

    def __init__(self):
        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.wait = WebDriverWait(self.driver, 15)

    def login(self):
        self.driver.get(self.URL)
        time.sleep(3)
        self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "[data-test='login-button'], .login-button, [class*='login']")
        )).click()
        time.sleep(2)
        u = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[name='username'], input[type='email'], #username")
        ))
        u.clear(); u.send_keys(UNIBET_USERNAME)
        p = self.driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password']")
        p.clear(); p.send_keys(UNIBET_PASSWORD)
        self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(4)

    def place_bet(self, slip):
        try:
            self.login()
            for sel in slip["selections"]:
                self._add_selection(sel)
                time.sleep(2)
            self._set_stake(slip["stake"])
            self._confirm_bet()
            return True
        except Exception as e:
            log.error(f"❌ Failed: {e}")
            self.driver.save_screenshot("error_screenshot.png")
            return False
        finally:
            self.driver.quit()

    def _add_selection(self, selection):
        bet_type = selection["recommended_bet"]
        selector = self.BET_SELECTORS.get(bet_type, self.BET_SELECTORS["home_win"])
        self.driver.get(f"{self.URL}/en/sports/football")
        time.sleep(2)
        try:
            s = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type='search'], [placeholder*='Search']")
            ))
            s.clear(); s.send_keys(selection["home"])
            time.sleep(2)
            self.wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, ".search-result, [class*='fixture']")
            )).click()
            time.sleep(2)
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector))).click()
        except Exception as e:
            log.warning(f"Could not add {selection['home']}: {e}")

    def _set_stake(self, stake):
        try:
            inp = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[class*='stake'], .betslip-stake input")
            ))
            inp.clear(); inp.send_keys(str(stake))
            time.sleep(1)
        except Exception as e:
            log.error(f"Stake error: {e}")

    def _confirm_bet(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "[class*='place-bet'], .betslip-submit")
        )).click()
        time.sleep(3)


# ─────────────────────────────────────────
# 5. TELEGRAM NOTIFIER
# ─────────────────────────────────────────

class TelegramNotifier:
    def __init__(self):
        self.token = TELEGRAM_TOKEN.strip()
        self.chat_id = TELEGRAM_CHAT_ID.strip()
        self.base = f"https://api.telegram.org/bot{self.token}"

    def send(self, message):
        try:
            requests.post(f"{self.base}/sendMessage", json={
                "chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"
            })
        except Exception as e:
            log.error(f"Telegram error: {e}")

    def notify_slip(self, slip):
        lines = [f"🎯 *New Bet Slip* — {slip['built_at'][:10]}\n"]
        for i, sel in enumerate(slip["selections"], 1):
            lines.append(
                f"{i}. *{sel['home']} vs {sel['away']}*\n"
                f"   `{sel['recommended_bet'].replace('_',' ').upper()}` @ *{sel['odds']}*\n"
                f"   Confidence: {sel['confidence']}% | _{sel.get('league','')}_\n"
                f"   _{', '.join(sel['reasoning'][:2])}_\n"
            )
        lines += [
            "━━━━━━━━━━━━━━━",
            f"📊 Odds: *{slip['combined_odds']}x*",
            f"💰 Stake: *€{slip['stake']}*",
            f"🏆 Potential: *€{slip['potential_payout']}*"
        ]
        self.send("\n".join(lines))

    def notify_result(self, success, slip):
        if success:
            self.send(f"✅ *Bet Placed!*\nStake: €{slip['stake']} | Potential: €{slip['potential_payout']}")
        else:
            self.send("❌ *Bet placement failed.* Check logs.")


# ─────────────────────────────────────────
# 6. MAIN RUNNER
# ─────────────────────────────────────────

def run():
    log.info("🤖 Betting bot v2 starting...")
    notifier = TelegramNotifier()
    try:
        slip = SlipBuilder(ResearchEngine(), OddsEngine()).build_slip()
        if not slip:
            notifier.send("⚠️ No qualifying bets found today.")
            return
        notifier.notify_slip(slip)
        success = UnibetPlacer().place_bet(slip)
        notifier.notify_result(success, slip)
    except Exception as e:
        log.error(f"Bot error: {e}")
        notifier.send(f"❌ Bot crashed: `{str(e)}`")


if __name__ == "__main__":
    run()
