"""
Analytics Engine
- Daily/weekly/monthly P&L reports
- Win/loss streaks
- ROI by confidence level
- Telegram report summary
"""

import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

log = logging.getLogger(__name__)


def load_history():
    try:
        with open("bet_history.json") as f:
            return json.load(f)
    except:
        return []


# ─────────────────────────────────────────
# P&L REPORTS
# ─────────────────────────────────────────

def get_pl_report(period="daily"):
    history = load_history()
    if not history:
        return None

    now = datetime.utcnow()

    if period == "daily":
        cutoff = now - timedelta(days=1)
        label = "Daily"
    elif period == "weekly":
        cutoff = now - timedelta(days=7)
        label = "Weekly"
    elif period == "monthly":
        cutoff = now - timedelta(days=30)
        label = "Monthly"
    else:
        cutoff = datetime.min
        label = "All Time"

    filtered = []
    for b in history:
        try:
            date = datetime.strptime(b.get("date_full", b.get("date", "")), "%Y-%m-%d")
            if date >= cutoff:
                filtered.append(b)
        except:
            filtered.append(b)

    if not filtered:
        return {"period": label, "total": 0, "wins": 0, "losses": 0,
                "staked": 0, "returned": 0, "net_pl": 0, "win_rate": 0, "roi": 0}

    total = len(filtered)
    wins = sum(1 for b in filtered if b["status"] == "win")
    losses = sum(1 for b in filtered if b["status"] == "loss")
    staked = sum(b.get("stake", 0) for b in filtered)
    returned = sum(b.get("return", 0) for b in filtered)
    net_pl = returned - staked
    win_rate = round(wins / total * 100, 1) if total else 0
    roi = round(net_pl / staked * 100, 1) if staked else 0

    return {
        "period": label,
        "total": total,
        "wins": wins,
        "losses": losses,
        "pending": sum(1 for b in filtered if b["status"] == "pending"),
        "staked": round(staked, 2),
        "returned": round(returned, 2),
        "net_pl": round(net_pl, 2),
        "win_rate": win_rate,
        "roi": roi
    }


# ─────────────────────────────────────────
# WIN/LOSS STREAKS
# ─────────────────────────────────────────

def get_streaks():
    history = [b for b in load_history() if b["status"] in ("win", "loss")]
    if not history:
        return {"current_streak": 0, "current_type": None,
                "best_win_streak": 0, "worst_loss_streak": 0, "streak_history": []}

    current_streak = 1
    current_type = history[-1]["status"]
    best_win = 0
    worst_loss = 0
    temp = 1

    for i in range(len(history) - 2, -1, -1):
        if history[i]["status"] == history[i + 1]["status"]:
            if i == len(history) - 2:
                current_streak += 1
            temp += 1
        else:
            if history[i + 1]["status"] == "win":
                best_win = max(best_win, temp)
            else:
                worst_loss = max(worst_loss, temp)
            temp = 1

    # Final
    if history[-1]["status"] == "win":
        best_win = max(best_win, current_streak)
    else:
        worst_loss = max(worst_loss, current_streak)

    # Streak history (last 20)
    streak_history = []
    i = 0
    bets = history[-20:]
    while i < len(bets):
        t = bets[i]["status"]
        count = 1
        while i + count < len(bets) and bets[i + count]["status"] == t:
            count += 1
        streak_history.append({"type": t, "count": count})
        i += count

    return {
        "current_streak": current_streak,
        "current_type": current_type,
        "best_win_streak": best_win,
        "worst_loss_streak": worst_loss,
        "streak_history": streak_history
    }


# ─────────────────────────────────────────
# ROI BY CONFIDENCE
# ─────────────────────────────────────────

def get_roi_by_confidence():
    history = load_history()
    buckets = {
        "30-40%": {"wins": 0, "total": 0, "staked": 0, "returned": 0},
        "40-50%": {"wins": 0, "total": 0, "staked": 0, "returned": 0},
        "50-60%": {"wins": 0, "total": 0, "staked": 0, "returned": 0},
        "60-70%": {"wins": 0, "total": 0, "staked": 0, "returned": 0},
        "70-80%": {"wins": 0, "total": 0, "staked": 0, "returned": 0},
        "80%+":   {"wins": 0, "total": 0, "staked": 0, "returned": 0},
    }

    for b in history:
        conf = b.get("avg_confidence", 50)
        if conf < 40:   key = "30-40%"
        elif conf < 50: key = "40-50%"
        elif conf < 60: key = "50-60%"
        elif conf < 70: key = "60-70%"
        elif conf < 80: key = "70-80%"
        else:           key = "80%+"

        buckets[key]["total"] += 1
        buckets[key]["staked"] += b.get("stake", 0)
        buckets[key]["returned"] += b.get("return", 0)
        if b["status"] == "win":
            buckets[key]["wins"] += 1

    result = []
    for label, data in buckets.items():
        if data["total"] > 0:
            roi = round((data["returned"] - data["staked"]) / data["staked"] * 100, 1) if data["staked"] else 0
            win_rate = round(data["wins"] / data["total"] * 100, 1)
            result.append({
                "confidence": label,
                "total": data["total"],
                "wins": data["wins"],
                "win_rate": win_rate,
                "roi": roi
            })

    return result


# ─────────────────────────────────────────
# FULL REPORT (for Telegram)
# ─────────────────────────────────────────

def generate_telegram_report(period="weekly"):
    pl = get_pl_report(period)
    streaks = get_streaks()
    roi_conf = get_roi_by_confidence()

    if not pl:
        return "📊 No data available yet."

    pl_sign = "+" if pl["net_pl"] >= 0 else ""
    pl_emoji = "📈" if pl["net_pl"] >= 0 else "📉"

    lines = [
        f"📊 *{pl['period']} Report*\n",
        f"🎰 Bets: *{pl['total']}* ({pl['wins']}W / {pl['losses']}L)",
        f"📈 Win Rate: *{pl['win_rate']}%*",
        f"💰 Staked: *€{pl['staked']}*",
        f"💵 Returned: *€{pl['returned']}*",
        f"{pl_emoji} Net P&L: *{pl_sign}€{pl['net_pl']}*",
        f"📊 ROI: *{pl_sign}{pl['roi']}%*\n",
        f"🔥 *Streaks*",
        f"Current: *{streaks['current_streak']} {streaks['current_type'] or 'N/A'}{'s' if streaks['current_streak'] > 1 else ''}*",
        f"Best Win Streak: *{streaks['best_win_streak']}*",
        f"Worst Loss Streak: *{streaks['worst_loss_streak']}*\n",
    ]

    if roi_conf:
        lines.append("🎯 *ROI by Confidence*")
        for r in roi_conf:
            roi_sign = "+" if r["roi"] >= 0 else ""
            lines.append(f"`{r['confidence']}` — {r['win_rate']}% WR | {roi_sign}{r['roi']}% ROI ({r['total']} bets)")

    return "\n".join(lines)


# ─────────────────────────────────────────
# API ENDPOINTS DATA
# ─────────────────────────────────────────

def get_full_analytics():
    return {
        "daily": get_pl_report("daily"),
        "weekly": get_pl_report("weekly"),
        "monthly": get_pl_report("monthly"),
        "all_time": get_pl_report("all"),
        "streaks": get_streaks(),
        "roi_by_confidence": get_roi_by_confidence()
    }
