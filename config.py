import os

# ─────────────────────────────────────────
# API KEYS — reads from environment variables
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
DEFAULT_STAKE = 1.00
MIN_ODDS = 1.40
MAX_LEGS = 5
MIN_CONFIDENCE_SCORE = 40
