"""
Jack FastAPI backend.

Endpoints:
  GET  /api/days/{split}          -> list of trading days with P&L summary
  GET  /api/day/{split}/{date}    -> candles + indicators + trades + market profile
  GET  /api/equity/{split}        -> equity curve
  GET  /api/metrics/{split}       -> strategy/dow stats
  GET  /api/shortcomings/{split}  -> shortcoming flags
  POST /api/run/{split}           -> trigger simulation
"""

import json
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

app = FastAPI(title="Jack Trading Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOURNAL_DIR = _ROOT / "journal" / "logs"
SPLITS = ("train", "test", "holdout")

# Primary intraday file (15-minute candles)
_INTRADAY_CSV = _ROOT / "data" / "raw" / "bank-nifty-15m-data.csv"
_DAILY_CSV    = _ROOT / "data" / "raw" / "bank-nifty-1d-data.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Data cache (loaded once, held in memory)
# ──────────────────────────────────────────────────────────────────────────────

def _load_intraday() -> pd.DataFrame:
    """Load & normalise the 15m intraday CSV. Returns rows sorted by datetime."""
    df = pd.read_csv(_INTRADAY_CSV)
    df.columns = [c.strip() for c in df.columns]
    df["Datetime"] = pd.to_datetime(
        df["Date"].astype(str) + " " + df["Time"].astype(str),
        dayfirst=True,
    )
    df = df.sort_values("Datetime").reset_index(drop=True)
    df["_date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_daily() -> pd.DataFrame:
    """Load & normalise the daily OHLC CSV."""
    df = pd.read_csv(_DAILY_CSV)
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.sort_values("Date").reset_index(drop=True)
    df["_date"] = df["Date"].dt.strftime("%Y-%m-%d")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# Module-level cache — loaded on first request
_intraday_df: pd.DataFrame | None = None
_daily_df: pd.DataFrame | None = None


def _get_intraday() -> pd.DataFrame:
    global _intraday_df
    if _intraday_df is None:
        _intraday_df = _load_intraday()
    return _intraday_df


def _get_daily() -> pd.DataFrame:
    global _daily_df
    if _daily_df is None:
        _daily_df = _load_daily()
    return _daily_df


# ──────────────────────────────────────────────────────────────────────────────
# Candle helpers
# ──────────────────────────────────────────────────────────────────────────────

def _candles_for_date(date: str) -> list[dict]:
    """Return lightweight-charts candle dicts for a single trading date."""
    df = _get_intraday()
    day = df[df["_date"] == date]
    if day.empty:
        return []
    candles = []
    for _, row in day.iterrows():
        # Convert IST datetime to UTC unix (subtract 5h30m)
        unix = int(row["Datetime"].timestamp()) - 19800
        candles.append({
            "time": unix,
            "open":  round(float(row["Open"]),  2),
            "high":  round(float(row["High"]),  2),
            "low":   round(float(row["Low"]),   2),
            "close": round(float(row["Close"]), 2),
        })
    return sorted(candles, key=lambda x: x["time"])


def _trading_dates_before(date: str, n: int = 5) -> list[str]:
    """Return up to n trading dates that appear in the intraday data before `date`."""
    df = _get_intraday()
    dates = sorted(df["_date"].unique())
    before = [d for d in dates if d < date]
    return before[-n:]


def _prev_trading_date(date: str) -> str | None:
    """Return the immediately preceding trading date, or None."""
    dates = _trading_dates_before(date, n=1)
    return dates[0] if dates else None


# ──────────────────────────────────────────────────────────────────────────────
# Indicator computation (no lookahead — applied to a closed set of candles)
# ──────────────────────────────────────────────────────────────────────────────

def _indicators_from_candles(candles: list[dict]) -> dict:
    if not candles:
        return {}
    closes = pd.Series([c["close"] for c in candles])
    highs  = pd.Series([c["high"]  for c in candles])
    lows   = pd.Series([c["low"]   for c in candles])
    times  = [c["time"] for c in candles]

    def to_series(values):
        return [
            {"time": t, "value": round(float(v), 2)}
            for t, v in zip(times, values)
            if pd.notna(v)
        ]

    ema9  = closes.ewm(span=9,  adjust=False).mean()
    ema21 = closes.ewm(span=21, adjust=False).mean()

    period = 20
    sma20  = closes.rolling(period).mean()
    std20  = closes.rolling(period).std()

    return {
        "ema9":      to_series(ema9),
        "ema21":     to_series(ema21),
        "bb_upper":  to_series(sma20 + 2 * std20),
        "bb_middle": to_series(sma20),
        "bb_lower":  to_series(sma20 - 2 * std20),
    }


def _vwap_from_candles(candles: list[dict]) -> list[dict]:
    """Compute session VWAP (assumes candles are from a single day)."""
    if not candles:
        return []
    closes  = pd.Series([c["close"] for c in candles])
    highs   = pd.Series([c["high"]  for c in candles])
    lows    = pd.Series([c["low"]   for c in candles])
    # Proxy volume = 1 since 15m data has no volume stored
    tp      = (highs + lows + closes) / 3
    vwap    = tp.cumsum() / pd.Series(range(1, len(tp) + 1))
    return [
        {"time": c["time"], "value": round(float(v), 2)}
        for c, v in zip(candles, vwap)
        if pd.notna(v)
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Market profile builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_market_profile(date: str, journal_entry: dict) -> dict:
    """
    Build a rich market profile for `date` by combining:
      - Previous day's OHLC, range, trend, key levels
      - Current day's gap, open, first-hour context
      - Rolling context: last 5 days win/loss streak, ATR trend
    """
    daily_df = _get_daily()

    # ── Current day open ──────────────────────────────────────────────────────
    today_candles = _candles_for_date(date)
    today_open  = today_candles[0]["open"]  if today_candles else None
    today_close = today_candles[-1]["close"] if today_candles else None

    # ── Prior days from daily data ────────────────────────────────────────────
    daily_before = daily_df[daily_df["_date"] < date].tail(10)

    prev_row  = daily_before.iloc[-1] if not daily_before.empty else None
    prev_date = str(prev_row["_date"]) if prev_row is not None else None

    prior_close = float(prev_row["Close"]) if prev_row is not None else None
    prior_open  = float(prev_row["Open"])  if prev_row is not None else None
    prior_high  = float(prev_row["High"])  if prev_row is not None else None
    prior_low   = float(prev_row["Low"])   if prev_row is not None else None

    # Gap
    gap_pts = round(today_open - prior_close, 2) if (today_open and prior_close) else None
    gap_pct = round(gap_pts / prior_close * 100, 3) if (gap_pts is not None and prior_close) else None

    gap_type = "flat"
    if gap_pct is not None:
        if   gap_pct >  0.75: gap_type = "large_up"
        elif gap_pct >  0.10: gap_type = "small_up"
        elif gap_pct < -0.75: gap_type = "large_down"
        elif gap_pct < -0.10: gap_type = "small_down"

    # Prior day character
    prior_range = round(prior_high - prior_low, 2) if (prior_high and prior_low) else None
    prior_bull  = (prior_close > prior_open) if (prior_close and prior_open) else None
    prior_body  = round(abs(prior_close - prior_open), 2) if (prior_close and prior_open) else None
    prior_body_pct = round(prior_body / prior_range * 100, 1) if (prior_body and prior_range) else None

    # Rolling 5-day context
    last5 = daily_before.tail(5)
    streak_bull = 0
    streak_bear = 0
    for _, row in last5.iloc[::-1].iterrows():
        if float(row["Close"]) > float(row["Open"]):
            if streak_bear == 0: streak_bull += 1
            else: break
        else:
            if streak_bull == 0: streak_bear += 1
            else: break

    # ATR(5) on prior days
    if len(daily_before) >= 2:
        hi = daily_before["High"]
        lo = daily_before["Low"]
        cl = daily_before["Close"]
        tr = pd.concat([
            hi - lo,
            (hi - cl.shift()).abs(),
            (lo - cl.shift()).abs(),
        ], axis=1).max(axis=1)
        atr5 = round(float(tr.tail(5).mean()), 2)
    else:
        atr5 = None

    # Pivot levels from prior day
    if prior_high and prior_low and prior_close:
        pp = round((prior_high + prior_low + prior_close) / 3, 2)
        r1 = round(2 * pp - prior_low, 2)
        r2 = round(pp + (prior_high - prior_low), 2)
        s1 = round(2 * pp - prior_high, 2)
        s2 = round(pp - (prior_high - prior_low), 2)
    else:
        pp = r1 = r2 = s1 = s2 = None

    # First hour from journal or recompute from intraday
    fh = journal_entry.get("first_hour", {})
    if not fh.get("FH_Return") and today_candles:
        fh_candles = [c for c in today_candles if _unix_to_hhmm(c["time"]) <= "10:15"]
        if fh_candles and today_open:
            fh_close = fh_candles[-1]["close"]
            fh_high  = max(c["high"] for c in fh_candles)
            fh_low   = min(c["low"]  for c in fh_candles)
            fh_ret   = round((fh_close - today_open) / today_open * 100, 3)
            fh = {
                "FH_Return":    fh_ret,
                "FH_Range":     round(fh_high - fh_low, 2),
                "FH_Direction": 1 if fh_ret > 0 else -1,
                "FH_Strong":    abs(fh_ret) >= 0.3,
                "FH_High":      fh_high,
                "FH_Low":       fh_low,
            }

    # Previous day intraday candles summary (for prev-day range visual)
    prev_candles = _candles_for_date(prev_date) if prev_date else []
    prev_vwap = None
    if prev_candles:
        closes = [c["close"] for c in prev_candles]
        highs  = [c["high"]  for c in prev_candles]
        lows   = [c["low"]   for c in prev_candles]
        tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        prev_vwap = round(sum(tp) / len(tp), 2)

    return {
        # Today
        "today_open":   today_open,
        "today_close":  today_close,
        "gap_pts":      gap_pts,
        "gap_pct":      gap_pct,
        "gap_type":     gap_type,

        # Prior day
        "prev_date":    prev_date,
        "prev_open":    prior_open,
        "prev_high":    prior_high,
        "prev_low":     prior_low,
        "prev_close":   prior_close,
        "prev_range":   prior_range,
        "prev_bull":    prior_bull,
        "prev_body_pct": prior_body_pct,
        "prev_vwap":    prev_vwap,

        # Key levels (pivot)
        "pivot":  pp,
        "r1": r1, "r2": r2,
        "s1": s1, "s2": s2,

        # Rolling context
        "streak_bull":  streak_bull,
        "streak_bear":  streak_bear,
        "atr5":         atr5,

        # First hour
        "first_hour":   fh,

        # Previous day candles (for prior-day range overlay)
        "prev_candles": prev_candles,
    }


def _unix_to_hhmm(unix: int) -> str:
    """Convert UTC unix (IST adjusted) back to HH:MM string for comparison."""
    # We stored unix as IST - 19800, so add back to get IST
    ist = datetime.utcfromtimestamp(unix + 19800)
    return ist.strftime("%H:%M")


# ──────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_entry_unix(date: str, time_str: str) -> int | None:
    """'YYYY-MM-DD' + 'HH:MM' -> UTC unix with IST offset removed."""
    try:
        dt = datetime.strptime(f"{date} {time_str[:5]}", "%Y-%m-%d %H:%M")
        return int(dt.timestamp()) - 19800
    except Exception:
        return None


def _results_path(split: str) -> Path:
    return JOURNAL_DIR / f"results_{split}.json"


def _load_results(split: str) -> dict:
    p = _results_path(split)
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def _day_log_path(date: str) -> Path:
    return JOURNAL_DIR / f"{date}.json"


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/days/{split}")
def get_days(split: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    results   = _load_results(split)
    trade_log = results.get("trade_log", [])

    day_map: dict[str, dict] = {}

    for trade in trade_log:
        date = trade.get("entry_date") or trade.get("date") or ""
        if not date:
            continue
        date = date[:10]
        if date not in day_map:
            day_map[date] = {"date": date, "has_trade": True, "net_pnl": 0.0}
        day_map[date]["net_pnl"] += float(trade.get("net_pnl", 0))

    # Supplement with journal day logs
    if JOURNAL_DIR.exists():
        for log_file in sorted(JOURNAL_DIR.glob("????-??-??.json")):
            date = log_file.stem
            if date not in day_map:
                try:
                    with open(log_file) as f:
                        entry = json.load(f)
                    day_map[date] = {
                        "date":      date,
                        "has_trade": bool(entry.get("trades")),
                        "net_pnl":   float(entry.get("daily_review", {}).get("total_pnl", 0)),
                    }
                except Exception:
                    day_map[date] = {"date": date, "has_trade": False, "net_pnl": 0.0}

    return sorted(day_map.values(), key=lambda d: d["date"])


@app.get("/api/day/{split}/{date}")
def get_day(split: str, date: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    # ── Journal log ───────────────────────────────────────────────────────────
    log_path = _day_log_path(date)
    journal_entry = {}
    if log_path.exists():
        with open(log_path) as f:
            journal_entry = json.load(f)

    # ── Candles ───────────────────────────────────────────────────────────────
    candles    = _candles_for_date(date)
    indicators = _indicators_from_candles(candles)
    vwap       = _vwap_from_candles(candles)
    if vwap:
        indicators["vwap"] = vwap

    # ── Market profile (includes prev-day context) ────────────────────────────
    profile = _build_market_profile(date, journal_entry)

    # ── Trades ────────────────────────────────────────────────────────────────
    trades = []
    for t in journal_entry.get("trades", []):
        entry_unix = _to_entry_unix(date, t.get("entry_time", ""))
        exit_unix  = _to_entry_unix(date, t.get("exit_time", ""))
        trades.append({
            "strategy":       t.get("strategy", ""),
            "direction":      t.get("direction", ""),
            "entry_time":     t.get("entry_time", ""),
            "entry_time_unix": entry_unix,
            "exit_time":      t.get("exit_time", ""),
            "exit_time_unix":  exit_unix,
            "entry_price":    t.get("entry_price", 0),
            "exit_price":     t.get("exit_price", 0),
            "stop_loss":      t.get("stop_loss", 0),
            "target":         t.get("target", 0),
            "net_pnl":        t.get("net_pnl", 0),
            "exit_reason":    t.get("exit_reason", ""),
        })

    return {
        "date":       date,
        "candles":    candles,
        "indicators": indicators,
        "trades":     trades,
        "profile":    profile,       # <- rich market context
        "decision_log":         journal_entry.get("strategies_evaluated", []),
        "missed_opportunities": journal_entry.get("missed_opportunities", []),
        "morning_scan":         journal_entry.get("morning_scan", {}),
        "capital":              journal_entry.get("capital", {}),
    }


@app.get("/api/equity/{split}")
def get_equity(split: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    results      = _load_results(split)
    equity_curve = results.get("equity_curve", [])

    if equity_curve and isinstance(equity_curve[0], dict):
        return equity_curve
    elif equity_curve:
        return [{"index": i, "capital": v} for i, v in enumerate(equity_curve)]
    return []


@app.get("/api/metrics/{split}")
def get_metrics(split: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    results     = _load_results(split)
    by_strategy = results.get("by_strategy", {})
    trade_log   = results.get("trade_log", [])

    dow_map = {d: {"trades": 0, "wins": 0, "win_rate": 0.0}
               for d in ["MON", "TUE", "WED", "THU", "FRI"]}

    for trade in trade_log:
        date_str = (trade.get("entry_date") or trade.get("date") or "")[:10]
        try:
            dt  = datetime.strptime(date_str, "%Y-%m-%d")
            dow = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dt.weekday()]
            if dow not in dow_map:
                continue
            dow_map[dow]["trades"] += 1
            if float(trade.get("net_pnl", 0)) > 0:
                dow_map[dow]["wins"] += 1
        except Exception:
            continue

    for data in dow_map.values():
        if data["trades"] > 0:
            data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1)

    return {
        "by_strategy":    by_strategy,
        "by_day_of_week": dow_map,
        "summary": {
            "total_trades":    results.get("total_trades", 0),
            "win_rate":        results.get("win_rate", 0),
            "net_pnl":         results.get("net_pnl", 0),
            "return_pct":      results.get("return_pct", 0),
            "max_drawdown_pct": results.get("max_drawdown_pct", 0),
            "sharpe_ratio":    results.get("sharpe_ratio", 0),
        },
    }


@app.get("/api/shortcomings/{split}")
def get_shortcomings(split: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    results = _load_results(split)
    flags   = []

    wr = results.get("win_rate", 0)
    if wr and wr < 45:
        flags.append({
            "severity": "HIGH", "category": "Win Rate",
            "message": f"Win rate is {wr:.1f}% — below the 45% threshold needed for profitability at 2:1 R:R.",
            "recommendation": "Review strategy entry filters. Consider raising the score threshold.",
        })
    elif wr and wr < 55:
        flags.append({
            "severity": "MEDIUM", "category": "Win Rate",
            "message": f"Win rate is {wr:.1f}% — marginal. System is profitable but fragile.",
            "recommendation": "Focus on the top-performing strategy and disable weaker ones.",
        })

    dd = results.get("max_drawdown_pct", 0)
    if dd and abs(dd) > 20:
        flags.append({
            "severity": "HIGH", "category": "Drawdown",
            "message": f"Max drawdown is {dd:.1f}% — exceeds safe threshold.",
            "recommendation": "Reduce position size or add a daily loss limit rule.",
        })
    elif dd and abs(dd) > 10:
        flags.append({
            "severity": "MEDIUM", "category": "Drawdown",
            "message": f"Max drawdown is {dd:.1f}% — moderate risk.",
            "recommendation": "Consider a trailing stop on daily loss > 2% of capital.",
        })

    for name, data in results.get("by_strategy", {}).items():
        s_wr     = data.get("win_rate", 0)
        s_pnl    = data.get("net_pnl", 0)
        s_trades = data.get("trades", 0)
        if s_trades >= 5 and s_pnl < 0:
            flags.append({
                "severity": "MEDIUM",
                "category": f"Strategy: {name}",
                "message": f"{name.replace('_', ' ').title()} is net negative (Rs{s_pnl:,.0f}) over {s_trades} trades.",
                "recommendation": f"Disable or retune {name}. Check its entry conditions.",
            })
        elif s_trades >= 5 and s_wr < 40:
            flags.append({
                "severity": "LOW",
                "category": f"Strategy: {name}",
                "message": f"{name.replace('_', ' ').title()} win rate is {s_wr:.1f}% ({s_trades} trades).",
                "recommendation": "Tighten entry filters or raise the minimum score threshold.",
            })

    if not results:
        flags.append({
            "severity": "LOW", "category": "Data",
            "message": f"No simulation results for the {split} split.",
            "recommendation": "Press R or click 'Run' to execute the simulation.",
        })

    return {"flags": flags}


@app.post("/api/run/{split}")
def run_simulation(split: str):
    if split not in SPLITS:
        raise HTTPException(400, f"Invalid split: {split}")

    try:
        from engine.simulator import Simulator

        sim     = Simulator(config_path=str(_ROOT / "config" / "settings.yaml"))
        results = sim.run(split=split, verbose=False)

        out_path = JOURNAL_DIR / f"results_{split}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        safe = {k: v for k, v in results.items() if not isinstance(v, pd.DataFrame)}
        with open(out_path, "w") as f:
            json.dump(safe, f, indent=2, default=str)

        return {
            "status":       "ok",
            "total_trades": results.get("total_trades", 0),
            "net_pnl":      results.get("net_pnl", 0),
            "win_rate":     results.get("win_rate", 0),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── LIVE SYSTEM ENDPOINTS ─────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True if current IST time is within market hours (9:15–15:30)."""
    now_ist = datetime.now()
    h, m = now_ist.hour, now_ist.minute
    return (9, 15) <= (h, m) <= (15, 30)


@app.get("/api/live/status")
def get_live_status():
    """Trader phase, open positions count, today's P&L, last signal, market hours."""
    try:
        from brain.agent_state import AgentStateManager
        trader_state = AgentStateManager.load("trader").state
    except Exception as e:
        trader_state = {"phase": "UNKNOWN", "error": str(e)}

    positions = []
    today_pnl = 0.0
    funds_ok = False
    dhan_error = None

    try:
        from data.dhan_client import DhanClient
        client = DhanClient()
        raw_positions = client.get_positions()
        if isinstance(raw_positions, dict) and raw_positions.get("data"):
            positions = raw_positions["data"]
        elif isinstance(raw_positions, list):
            positions = raw_positions
        for pos in positions:
            today_pnl += float(pos.get("unrealizedProfit", pos.get("pnl", 0)) or 0)
        funds_ok = True
    except Exception as e:
        dhan_error = str(e)

    return {
        "phase":         trader_state.get("phase", "IDLE"),
        "last_active":   trader_state.get("last_active"),
        "current_task":  trader_state.get("current_task"),
        "open_positions": len(positions),
        "today_pnl":     round(today_pnl, 2),
        "market_open":   _is_market_hours(),
        "dhan_connected": funds_ok,
        "dhan_error":    dhan_error,
        "last_signal":   trader_state.get("context", {}).get("last_signal"),
        "session_id":    trader_state.get("session_id"),
    }


@app.get("/api/live/positions")
def get_live_positions():
    """Open positions from Dhan API."""
    try:
        from data.dhan_client import DhanClient
        client = DhanClient()
        result = client.get_positions()
        if isinstance(result, dict):
            if result.get("status") == "failure":
                return {"status": "offline", "reason": result.get("remarks", "Dhan API error"), "positions": []}
            return {"status": "ok", "positions": result.get("data", [])}
        return {"status": "ok", "positions": result or []}
    except Exception as e:
        return {"status": "offline", "reason": str(e), "positions": []}


@app.get("/api/live/orders")
def get_live_orders():
    """Today's order book from Dhan API."""
    try:
        from data.dhan_client import DhanClient
        client = DhanClient()
        result = client.get_order_list()
        if isinstance(result, dict):
            if result.get("status") == "failure":
                return {"status": "offline", "reason": result.get("remarks", "Dhan API error"), "orders": []}
            return {"status": "ok", "orders": result.get("data", [])}
        return {"status": "ok", "orders": result or []}
    except Exception as e:
        return {"status": "offline", "reason": str(e), "orders": []}


@app.get("/api/live/funds")
def get_live_funds():
    """Account balance, margin, and available funds from Dhan API."""
    try:
        from data.dhan_client import DhanClient
        client = DhanClient()
        result = client.get_fund_limits()
        if isinstance(result, dict):
            if result.get("status") == "failure":
                return {"status": "offline", "reason": result.get("remarks", "Dhan API error")}
            data = result.get("data", result)
            return {"status": "ok", "funds": data}
        return {"status": "offline", "reason": "Unexpected response format"}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}


@app.get("/api/live/price/{symbol}")
def get_live_price(symbol: str):
    """Live spot price and OHLC for a symbol."""
    try:
        from data.dhan_fetcher import DhanFetcher
        fetcher = DhanFetcher()
        # Try get_spot_ohlc first; fall back to get_spot_price
        if hasattr(fetcher, "get_spot_ohlc"):
            result = fetcher.get_spot_ohlc(symbol.upper())
        else:
            price = fetcher.get_spot_price(symbol.upper())
            result = {"ltp": price, "symbol": symbol.upper()}
        if result is None:
            return {"status": "offline", "reason": "No data returned", "symbol": symbol.upper()}
        return {"status": "ok", "symbol": symbol.upper(), "data": result}
    except Exception as e:
        return {"status": "offline", "reason": str(e), "symbol": symbol.upper()}


@app.get("/api/live/option-chain/{symbol}")
def get_live_option_chain(symbol: str):
    """Parsed option chain with OI, IV, and Greeks."""
    try:
        from data.dhan_fetcher import DhanFetcher
        fetcher = DhanFetcher()
        df = fetcher.get_option_chain_df(symbol.upper())
        if df is None or (hasattr(df, "empty") and df.empty):
            return {"status": "offline", "reason": "Empty option chain", "symbol": symbol.upper(), "chain": []}
        if hasattr(df, "to_dict"):
            chain = df.to_dict(orient="records")
        else:
            chain = df
        return {"status": "ok", "symbol": symbol.upper(), "chain": chain}
    except Exception as e:
        return {"status": "offline", "reason": str(e), "symbol": symbol.upper(), "chain": []}


# ── KNOWLEDGE BASE ENDPOINTS ──────────────────────────────────────────────────

def _get_kb(market: str = "BANKNIFTY"):
    from kb.reader import KBReader
    return KBReader(market)


@app.get("/api/kb/strategies")
def get_kb_strategies():
    """All active strategies with win rates, conditions, and notes."""
    try:
        kb = _get_kb()
        strategies = kb.get_active_strategies()
        candidates = kb.get_candidate_strategies()
        return {
            "status": "ok",
            "active": strategies,
            "candidates": candidates,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e), "active": {}, "candidates": {}}


@app.get("/api/kb/behavior/{pattern}")
def get_kb_behavior(pattern: str):
    """A specific behavior pattern YAML (gap_patterns, day_of_week, etc.)."""
    try:
        kb = _get_kb()
        data = kb.get_behavior(pattern)
        if not data:
            return {"status": "not_found", "pattern": pattern, "data": {}}
        return {"status": "ok", "pattern": pattern, "data": data}
    except Exception as e:
        return {"status": "error", "reason": str(e), "pattern": pattern, "data": {}}


@app.get("/api/kb/behaviors")
def get_kb_behaviors():
    """All behavior patterns as a dict."""
    try:
        kb = _get_kb()
        data = kb.get_all_behaviors()
        return {"status": "ok", "behaviors": data}
    except Exception as e:
        return {"status": "error", "reason": str(e), "behaviors": {}}


@app.get("/api/kb/risk")
def get_kb_risk():
    """Risk rules, circuit breakers, and event rules."""
    try:
        kb = _get_kb()
        return {
            "status": "ok",
            "rules":            kb.get_risk_rules(),
            "circuit_breakers": kb.get_circuit_breakers(),
            "events":           kb.get_risk_events(),
        }
    except Exception as e:
        return {"status": "error", "reason": str(e), "rules": {}, "circuit_breakers": {}, "events": {}}


@app.get("/api/kb/performance")
def get_kb_performance(days: int = 30):
    """Recent trade performance from _performance.db."""
    try:
        import sqlite3 as _sqlite3
        kb = _get_kb()
        conn = kb.get_db_connection()
        limit = max(1, days * 10)  # rough upper bound on rows
        cur = conn.cursor()
        cur.execute(
            "SELECT date, strategy, direction, pnl, exit_reason "
            "FROM trades ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        cols = ["date", "strategy", "direction", "pnl", "exit_reason"]
        trades = [dict(zip(cols, row)) for row in rows]

        # Also pull daily_metrics if available
        daily = []
        try:
            cur.execute(
                "SELECT * FROM daily_metrics ORDER BY date DESC LIMIT ?",
                (days,),
            )
            d_rows = cur.fetchall()
            d_cols = [desc[0] for desc in cur.description]
            daily = [dict(zip(d_cols, r)) for r in d_rows]
        except Exception:
            pass

        conn.close()
        return {"status": "ok", "days": days, "trades": trades, "daily_metrics": daily}
    except Exception as e:
        return {"status": "error", "reason": str(e), "trades": [], "daily_metrics": []}


@app.get("/api/kb/discoveries")
def get_kb_discoveries():
    """Pending and validated sources for the Learner panel."""
    try:
        kb = _get_kb()
        pending   = kb.get_sources("pending")
        validated = kb.get_sources("validated")
        return {
            "status":    "ok",
            "pending":   pending,
            "validated": validated,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e), "pending": [], "validated": []}


# ── AGENT INBOX ENDPOINTS ─────────────────────────────────────────────────────

_VALID_AGENTS = {"trader", "learner", "builder", "charting"}


@app.get("/api/inbox/{agent}")
def get_inbox(agent: str):
    """Unread messages in an agent's inbox."""
    if agent not in _VALID_AGENTS:
        raise HTTPException(400, f"Invalid agent: {agent}. Must be one of {sorted(_VALID_AGENTS)}")
    try:
        from brain.messages import MessageBus
        bus = MessageBus()
        messages = bus.read_inbox(agent, unread_only=True)
        # Strip internal filepath fields before returning
        clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
        return {"status": "ok", "agent": agent, "count": len(clean), "messages": clean}
    except Exception as e:
        return {"status": "error", "reason": str(e), "agent": agent, "messages": []}


@app.delete("/api/inbox/{agent}/{msg_id}")
def delete_inbox_message(agent: str, msg_id: str):
    """Mark a message as processed (moves it out of the inbox)."""
    if agent not in _VALID_AGENTS:
        raise HTTPException(400, f"Invalid agent: {agent}")
    try:
        from brain.messages import MessageBus
        bus = MessageBus()
        success = bus.mark_processed(agent, msg_id)
        if success:
            return {"status": "ok", "msg_id": msg_id, "processed": True}
        return {"status": "not_found", "msg_id": msg_id, "processed": False}
    except Exception as e:
        return {"status": "error", "reason": str(e), "msg_id": msg_id}


class SendMessageRequest(BaseModel):
    from_agent: str
    to_agent: str
    type: str
    subject: str
    body: dict = {}
    priority: str = "normal"


@app.post("/api/inbox/send")
def send_inbox_message(req: SendMessageRequest):
    """Send a message via the MessageBus."""
    if req.to_agent not in _VALID_AGENTS:
        raise HTTPException(400, f"Invalid to_agent: {req.to_agent}")
    try:
        from brain.messages import MessageBus
        bus = MessageBus()
        msg_id = bus.send(
            from_agent=req.from_agent,
            to_agent=req.to_agent,
            msg_type=req.type,
            subject=req.subject,
            body=req.body,
            priority=req.priority,
        )
        return {"status": "ok", "msg_id": msg_id}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ── TIME MACHINE ENDPOINTS ────────────────────────────────────────────────────

_CACHE_DIR = _ROOT / "data" / "cache"


def _replay_cache_path(start_date: str, end_date: str) -> Path:
    return _CACHE_DIR / f"replay_{start_date}_{end_date}.json"


def _serialize_replay_results(results: dict) -> dict:
    """Deep-serialize TimeMachine results for JSON response."""
    import math

    def _convert(obj):
        if hasattr(obj, "to_dict") and callable(obj.to_dict):
            return _convert(obj.to_dict())
        if hasattr(obj, "tolist"):
            return obj.tolist()
        if isinstance(obj, float):
            if math.isinf(obj) or math.isnan(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(i) for i in obj]
        return obj

    return _convert(results)


class TimeMachineRequest(BaseModel):
    start_date: str
    end_date: str
    kb_freeze_date: str | None = None


@app.post("/api/timemachine/run")
def run_timemachine(req: TimeMachineRequest):
    """Run TimeMachine replay over a date range and cache the result."""
    cache_path = _replay_cache_path(req.start_date, req.end_date)
    try:
        from charting.time_machine import TimeMachine
        tm = TimeMachine("BANKNIFTY")
        results = tm.replay(req.start_date, req.end_date)
        safe_results = _serialize_replay_results(results)

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(safe_results, f, indent=2, default=str)

        return {"status": "ok", "start_date": req.start_date, "end_date": req.end_date, "results": safe_results}
    except Exception as e:
        return {"status": "error", "reason": str(e), "start_date": req.start_date, "end_date": req.end_date}


@app.get("/api/timemachine/results/{start_date}/{end_date}")
def get_timemachine_results(start_date: str, end_date: str):
    """Return cached replay results if available."""
    cache_path = _replay_cache_path(start_date, end_date)
    if not cache_path.exists():
        return {"status": "not_found", "start_date": start_date, "end_date": end_date, "results": None}
    try:
        with open(cache_path) as f:
            results = json.load(f)
        return {"status": "ok", "start_date": start_date, "end_date": end_date, "results": results}
    except Exception as e:
        return {"status": "error", "reason": str(e), "start_date": start_date, "end_date": end_date}


@app.get("/api/timemachine/replay-day/{date}")
def replay_single_day(date: str):
    """Run a single-day replay and return a detailed decision log."""
    try:
        from charting.time_machine import TimeMachine
        tm = TimeMachine("BANKNIFTY")
        results = tm.replay(date, date)
        safe_results = _serialize_replay_results(results)

        # Check if no data was found for the date
        summary = safe_results.get("summary", {})
        if summary.get("trading_days", 0) == 0:
            return {
                "status": "error",
                "reason": f"No market data available for {date}. CSV data covers 2005-2024. "
                          f"Run 'python scripts/fetch_dhan_history.py' to fetch recent data from Dhan API.",
                "date": date,
            }

        return {"status": "ok", "date": date, "results": safe_results}
    except Exception as e:
        return {"status": "error", "reason": str(e), "date": date}


# ──────────────────────────────────────────────────────────────────────────────
# Full Day Agent Simulation
# ──────────────────────────────────────────────────────────────────────────────

class FullDayTestRequest(BaseModel):
    date: str
    kb_freeze: bool = True


@app.post("/api/simulate-day")
def simulate_full_day(req: FullDayTestRequest):
    """Simulate a full trading day with all agents communicating.

    1. Learner sends KB context (strategies, behaviors, risk rules)
    2. Charting runs the Time Machine replay
    3. Trader processes the replay results and makes decisions
    4. Builder evaluates strategy performance and suggests improvements

    All communication happens via the MessageBus inbox system.
    """
    from charting.time_machine import TimeMachine
    from brain.messages import MessageBus
    from kb.reader import KBReader

    bus = MessageBus()
    date = req.date

    # --- Step 1: Learner provides KB context ---
    try:
        kb = KBReader("BANKNIFTY")
        strategies = kb.get("strategies", [])
        behaviors = kb.get("behaviors", [])
        risk_rules = kb.get("risk", {})
    except Exception:
        strategies, behaviors, risk_rules = [], [], {}

    bus.send("learner", "trader", "day_briefing",
             subject=f"KB briefing for {date}",
             body={"date": date, "strategies_count": len(strategies),
                   "behaviors_count": len(behaviors),
                   "risk_rules": risk_rules},
             priority="high")

    bus.send("learner", "charting", "replay_request",
             subject=f"Run replay for {date}",
             body={"date": date, "kb_freeze": req.kb_freeze})

    # --- Step 2: Charting runs Time Machine ---
    try:
        tm = TimeMachine("BANKNIFTY")
        freeze_date = date if req.kb_freeze else None
        results = tm.replay(date, date, kb_freeze_date=freeze_date, verbose=True)

        safe_results = _serialize_replay_results(results)
    except Exception as e:
        return {"status": "error", "reason": f"Time Machine failed: {e}"}

    summary = safe_results.get("summary", {})
    daily = safe_results.get("daily_results", [{}])[0] if safe_results.get("daily_results") else {}

    # --- Step 3: Charting reports to Trader ---
    bus.send("charting", "trader", "replay_complete",
             subject=f"Replay done for {date}: {summary.get('total_trades', 0)} trades",
             body={"date": date, "trades": summary.get("total_trades", 0),
                   "win_rate": summary.get("win_rate", 0),
                   "pnl": summary.get("total_pnl", 0),
                   "direction_flow": [s.get("direction") for s in daily.get("confluence_snapshots", [])[:5]]},
             priority="high")

    # --- Step 4: Trader processes results ---
    trade_count = summary.get("total_trades", 0)
    pnl = summary.get("total_pnl", 0)
    trader_assessment = "profitable" if pnl > 0 else ("breakeven" if pnl == 0 else "loss")

    bus.send("trader", "builder", "day_review",
             subject=f"Day {date} review: {trader_assessment} ({trade_count} trades, PnL={pnl:,.0f})",
             body={"date": date, "assessment": trader_assessment,
                   "trades": trade_count, "pnl": pnl,
                   "win_rate": summary.get("win_rate", 0),
                   "strategy_breakdown": summary.get("strategy_breakdown", {})},
             priority="normal")

    # --- Step 5: Builder evaluates ---
    bus.send("builder", "learner", "performance_feedback",
             subject=f"Strategy performance for {date}",
             body={"date": date, "strategies_used": list(summary.get("strategy_breakdown", {}).keys()),
                   "overall_pnl": pnl, "suggestions": []})

    return {
        "status": "ok",
        "date": date,
        "results": safe_results,
        "agent_messages": {
            "learner_to_trader": f"KB briefing sent ({len(strategies)} strategies)",
            "charting_to_trader": f"Replay complete: {trade_count} trades",
            "trader_to_builder": f"Day review: {trader_assessment}",
            "builder_to_learner": "Performance feedback sent",
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Dhan Data Fetch
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/fetch-dhan-data")
def fetch_dhan_data(years: int = 5):
    """Fetch historical BankNifty data from Dhan API and save to CSV."""
    try:
        from scripts.fetch_dhan_history import fetch_daily_history, merge_with_existing
        from data.dhan_client import DhanClient

        client = DhanClient()
        if not client.is_configured():
            return {"status": "error", "reason": "Dhan API credentials not configured in config/.env"}

        daily_df = fetch_daily_history(client, years)
        if daily_df.empty:
            return {"status": "error", "reason": "No data returned from Dhan API"}

        csv_path = str(_ROOT / "data" / "raw" / "bank-nifty-1d-data.csv")
        merged = merge_with_existing(daily_df, csv_path)
        merged.to_csv(csv_path, index=False)

        return {
            "status": "ok",
            "rows_fetched": len(daily_df),
            "total_rows": len(merged),
            "csv_path": csv_path,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}


@app.get("/api/data-range")
def get_data_range():
    """Return the date range available in CSV data."""
    try:
        daily = _load_daily()
        if daily.empty:
            return {"status": "ok", "min_date": None, "max_date": None, "rows": 0}
        return {
            "status": "ok",
            "min_date": str(daily["Date"].min().date()),
            "max_date": str(daily["Date"].max().date()),
            "rows": len(daily),
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}
