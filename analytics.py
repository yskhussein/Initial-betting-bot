"""
Analytics Engine
- Daily/weekly/monthly P&L reports
- Win/loss streaks
- ROI by confidence level
- Best bet types and leagues
- Telegram report summaries
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


def filter_period(history, days):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = []
    for b in history:
        try:
            dt = datetime.fromisoformat(b.get("date", "2000-01-01"))
            if dt >= cutoff:
                result.append(b)
        except:
            pass
    return result


# ─────────────────────────────────────────
# CORE STATS
# ─────────────────────────────────────────

def compute_stats(bets):
    if not bets:
        return {
            "total": 0, "wins": 0, "losses": 0, "pending": 0,
            "win_rate": 0, "total_staked": 0, "total_returned": 0,
            "net_pl": 0, "roi": 0, "avg_odds": 0
        }

    settled = [b for b in bets if b.get("status") in ("win", "loss")]
    wins = [b for b in settled if b["status"] == "win"]
    losses = [b for b in settled if b["status"] == "loss"]
    pending = [b for b in bets if b.get("status") == "pending"]

    total_staked = sum(b.get("stake", 0) for b in settled)
    total_returned = sum(b.get("return", 0) for b in wins)
    net_pl = total_returned - total_staked
    win_rate = round(len(wins) / len(settled) * 100, 1) if settled else 0
    roi = round(net_pl / total_staked * 100, 1) if total_staked > 0 else 0
    avg_odds = round(sum(b.get("odds", 0) for b in bets) / len(bets), 2) if bets else 0

    return {
        "total": len(bets),
        "settled": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "pending": len(pending),
        "win_rate": win_rate,
        "total_staked": round(total_staked, 2),
        "total_returned": round(total_returned, 2),
        "net_pl": round(net_pl, 2),
        "roi": roi,
        "avg_odds": avg_odds
    }


# ─────────────────────────────────────────
# STREAK ANALYSIS
# ─────────────────────────────────────────

def compute_streaks(bets):
    settled = [b for b in bets if b.get("status") in ("win", "loss")]
    settled.sort(key=lambda b: b.get("date", ""))

    current_streak = 0
    current_type = None
    max_win_streak = 0
    max_loss_streak = 0
    temp_win = 0
    temp_loss = 0

    for b in settled:
        if b["status"] == "win":
            temp_win += 1
            temp_loss = 0
            max_win_streak = max(max_win_streak, temp_win)
        else:
            temp_loss += 1
            temp_win = 0
            max_loss_streak = max(max_loss_streak, temp_loss)

    # Current streak
    for b in reversed(settled):
        if current_type is None:
            current_type = b["status"]
            current_streak = 1
        elif b["status"] == current_type:
            current_streak += 1
        else:
            break

    return {
        "current_streak": current_streak,
        "current_type": current_type or "none",
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak
    }


# ─────────────────────────────────────────
# ROI BY CONFIDENCE LEVEL
# ─────────────────────────────────────────

def roi_by_confidence(bets):
    buckets = {
        "30-49": [], "50-64": [], "65-79": [], "80-100": []
    }
    for b in bets:
        conf = b.get("confidence", 0)
        if conf < 50:
            buckets["30-49"].append(b)
        elif conf < 65:
            buckets["50-64"].append(b)
        elif conf < 80:
            buckets["65-79"].append(b)
        else:
            buckets["80-100"].append(b)

    result = {}
    for label, group in buckets.items():
        settled = [b for b in group if b.get("status") in ("win", "loss")]
        if not settled:
            result[label] = {"bets": 0, "win_rate": 0, "roi": 0}
            continue
        wins = sum(1 for b in settled if b["status"] == "win")
        staked = sum(b.get("stake", 0) for b in settled)
        returned = sum(b.get("return", 0) for b in settled if b["status"] == "win")
        result[label] = {
            "bets": len(settled),
            "wins": wins,
            "win_rate": round(wins / len(settled) * 100, 1),
            "roi": round((returned - staked) / staked * 100, 1) if staked > 0 else 0
        }
    return result


# ─────────────────────────────────────────
# ROI BY BET TYPE
# ─────────────────────────────────────────

def roi_by_bet_type(bets):
    groups = defaultdict(list)
    for b in bets:
        for sel in b.get("selections", []):
            bet_type = sel.get("recommended_bet", "unknown")
            groups[bet_type].append({
                "status": b.get("status"),
                "stake": b.get("stake", 0) / max(len(b.get("selections", [1])), 1),
                "return": b.get("return", 0) if b.get("status") == "win" else 0
            })

    result = {}
    for bet_type, items in groups.items():
        settled = [i for i in items if i.get("status") in ("win", "loss")]
        if not settled:
            continue
        wins = sum(1 for i in settled if i["status"] == "win")
        staked = sum(i["stake"] for i in settled)
        returned = sum(i["return"] for i in settled if i["status"] == "win")
        result[bet_type] = {
            "bets": len(settled),
            "wins": wins,
            "win_rate": round(wins / len(settled) * 100, 1),
            "roi": round((returned - staked) / staked * 100, 1) if staked > 0 else 0
        }
    return dict(sorted(result.items(), key=lambda x: x[1]["roi"], reverse=True))


# ─────────────────────────────────────────
# ROI BY LEAGUE
# ─────────────────────────────────────────

def roi_by_league(bets):
    groups = defaultdict(list)
    for b in bets:
        for sel in b.get("selections", []):
            league = sel.get("league", "Unknown")
            groups[league].append({
                "status": b.get("status"),
                "stake": b.get("stake", 0) / max(len(b.get("selections", [1])), 1),
                "return": b.get("return", 0) if b.get("status") == "win" else 0
            })

    result = {}
    for league, items in groups.items():
        settled = [i for i in items if i.get("status") in ("win", "loss")]
        if len(settled) < 2:
            continue
        wins = sum(1 for i in settled if i["status"] == "win")
        staked = sum(i["stake"] for i in settled)
        returned = sum(i["return"] for i in settled if i["status"] == "win")
        result[league] = {
            "bets": len(settled),
            "wins": wins,
            "win_rate": round(wins / len(settled) * 100, 1),
            "roi": round((returned - staked) / staked * 100, 1) if staked > 0 else 0
        }
    return dict(sorted(result.items(), key=lambda x: x[1]["roi"], reverse=True)[:8])


# ─────────────────────────────────────────
# P&L CHART DATA
# ─────────────────────────────────────────

def pl_chart_data(bets, days=30):
    bets = filter_period(bets, days)
    bets.sort(key=lambda b: b.get("date", ""))

    points = []
    running = 0
    for b in bets:
        if b.get("status") == "win":
            running += b.get("return", 0) - b.get("stake", 0)
        elif b.get("status") == "loss":
            running -= b.get("stake", 0)
        points.append({
            "date": b.get("date", "")[:10],
            "pl": round(running, 2)
        })
    return points


# ─────────────────────────────────────────
# FULL REPORT
# ─────────────────────────────────────────

def generate_report(period="weekly"):
    history = load_history()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)
    bets = filter_period(history, days)

    return {
        "period": period,
        "generated_at": datetime.utcnow().isoformat(),
        "stats": compute_stats(bets),
        "streaks": compute_streaks(history),  # All-time streaks
        "roi_by_confidence": roi_by_confidence(bets),
        "roi_by_bet_type": roi_by_bet_type(bets),
        "roi_by_league": roi_by_league(bets),
        "pl_chart": pl_chart_data(history, days=30)
    }


# ─────────────────────────────────────────
# TELEGRAM REPORT FORMATTER
# ─────────────────────────────────────────

def format_telegram_report(period="weekly"):
    history = load_history()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)
    bets = filter_period(history, days)
    stats = compute_stats(bets)
    streaks = compute_streaks(history)
    conf_roi = roi_by_confidence(bets)
    bet_type_roi = roi_by_bet_type(bets)

    period_label = {"daily": "📅 Today", "weekly": "📆 This Week", "monthly": "🗓 This Month"}.get(period, "📆 This Week")
    pl_emoji = "🟢" if stats["net_pl"] >= 0 else "🔴"
    streak_emoji = "🔥" if streaks["current_type"] == "win" else "❄️"

    lines = [
        f"📊 *BetBot Report — {period_label}*",
        "━━━━━━━━━━━━━━━",
        f"🎯 Bets: *{stats['total']}* ({stats['wins']}W / {stats['losses']}L / {stats['pending']}P)",
        f"📈 Win Rate: *{stats['win_rate']}%*",
        f"💰 Staked: *€{stats['total_staked']}*",
        f"{pl_emoji} Net P&L: *{'+'if stats['net_pl']>=0 else''}€{stats['net_pl']}*",
        f"📉 ROI: *{stats['roi']}%*",
        f"🎲 Avg Odds: *{stats['avg_odds']}x*",
        "",
        f"{streak_emoji} *Current Streak:* {streaks['current_streak']} {streaks['current_type'].upper()}",
        f"🏆 Best Win Streak: {streaks['max_win_streak']}",
        f"💀 Worst Loss Streak: {streaks['max_loss_streak']}",
    ]

    # ROI by confidence
    if any(v["bets"] > 0 for v in conf_roi.values()):
        lines += ["", "🎯 *ROI by Confidence*"]
        for bucket, data in conf_roi.items():
            if data["bets"] > 0:
                roi_str = f"{'+'if data['roi']>=0 else''}{data['roi']}%"
                lines.append(f"  `{bucket}%` → {roi_str} ({data['bets']} bets, {data['win_rate']}% WR)")

    # Best bet types
    if bet_type_roi:
        lines += ["", "🏅 *Best Bet Types*"]
        for bet_type, data in list(bet_type_roi.items())[:3]:
            roi_str = f"{'+'if data['roi']>=0 else''}{data['roi']}%"
            lines.append(f"  `{bet_type.replace('_',' ').upper()}` → {roi_str} ({data['win_rate']}% WR)")

    lines += ["━━━━━━━━━━━━━━━", f"_Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC_"]
    return "\n".join(lines)
