import os

# ─────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ─────────────────────────────────────────
# UNIBET CREDENTIALS
# ─────────────────────────────────────────
UNIBET_USERNAME = os.getenv("UNIBET_USERNAME", "").strip()
UNIBET_PASSWORD = os.getenv("UNIBET_PASSWORD", "").strip()

# ─────────────────────────────────────────
# BET SETTINGS
# ─────────────────────────────────────────
DEFAULT_STAKE = float(os.getenv("DEFAULT_STAKE", "1.00"))
MIN_ODDS = float(os.getenv("MIN_ODDS", "1.40"))
MAX_LEGS = int(os.getenv("MAX_LEGS", "5"))
MIN_CONFIDENCE_SCORE = int(os.getenv("MIN_CONFIDENCE_SCORE", "40"))

# ─────────────────────────────────────────
# BET TYPES ENABLED
# ─────────────────────────────────────────
ENABLED_BET_TYPES = [
    "home_win",
    "away_win",
    "draw",
    "over_2.5",
    "btts_yes",
    "draw_no_bet",
    "double_chance",
    "asian_handicap",
]

# ─────────────────────────────────────────
# RESEARCH SETTINGS
# ─────────────────────────────────────────
FORM_GAMES = int(os.getenv("FORM_GAMES", "6"))       # Last N games for form
H2H_GAMES = int(os.getenv("H2H_GAMES", "10"))        # Last N H2H games
MAX_FIXTURES = int(os.getenv("MAX_FIXTURES", "25"))   # Max fixtures to analyze per day
