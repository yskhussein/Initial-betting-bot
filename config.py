import os

# ─────────────────────────────────────────
# API KEYS — reads from environment variables
# Set these as GitHub Secrets in your repo
# ─────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "YOUR_ODDS_API_KEY")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "YOUR_API_FOOTBALL_KEY")

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# ─────────────────────────────────────────
# UNIBET CREDENTIALS
# ─────────────────────────────────────────
UNIBET_USERNAME = os.getenv("UNIBET_USERNAME", "YOUR_UNIBET_EMAIL")
UNIBET_PASSWORD = os.getenv("UNIBET_PASSWORD", "YOUR_UNIBET_PASSWORD")

# ─────────────────────────────────────────
# BET SETTINGS
# ─────────────────────────────────────────
DEFAULT_STAKE = 1.00        # € stake per slip
MIN_ODDS = 1.40             # minimum odds per leg
MAX_LEGS = 5                # max legs per accumulator
MIN_CONFIDENCE_SCORE = 40   # minimum confidence % to include a selection
