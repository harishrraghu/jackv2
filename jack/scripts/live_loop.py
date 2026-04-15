"""
Jack Live Loop — Real-time paper trading with Claude Code CLI as the decision brain.

Runs every 5 minutes:
1. Fetches live Dhan data (spot, OI, option chain, OHLC)
2. Runs confluence scoring + entry checklist
3. Pipes structured market snapshot to `claude -p` (Claude Code CLI) for trade decision
4. Executes paper orders via DhanOrderManager (paper mode)
5. Monitors open positions for SL/target hits
6. Journals every decision with full reasoning

No API key needed — uses the already-authenticated Claude Code CLI session.

Usage:
    python -m scripts.live_loop
    python -m scripts.live_loop --symbol NIFTY
    python -m scripts.live_loop --interval 300  # seconds between loops
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── IST timezone ─────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_loop")

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "data" / "cache"
JOURNAL_DIR = ROOT / "journal" / "logs"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

# ── Market hours ──────────────────────────────────────────────────────────────
MARKET_OPEN  = "09:15"
MARKET_CLOSE = "15:30"
FORCE_EXIT   = "15:20"   # close all positions before market close

# ── Lot sizes ─────────────────────────────────────────────────────────────────
LOT_SIZES = {"BANKNIFTY": 15, "NIFTY": 75, "FINNIFTY": 40, "SENSEX": 10}

# ── Daily trade limits ────────────────────────────────────────────────────────
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS_RS  = 5000   # hard stop: blow this much, stop trading


# =============================================================================
# Claude Code CLI brain
# =============================================================================

def ask_claude(prompt: str, api_key: str = None) -> str:
    """
    Call the Claude Code CLI (`claude -p`) with the given prompt.
    Returns Claude's text response.
    No API key needed — uses the CLI's existing authenticated session.
    Works on Windows (claude.cmd) and Unix (claude).
    """
    # On Windows the shim is claude.cmd; shell=True handles this transparently
    result = subprocess.run(
        "claude -p --output-format json",
        input=prompt.encode("utf-8"),
        capture_output=True,
        timeout=120,
        shell=True,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI error: {result.stderr[:300]}")

    data = json.loads(result.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"Claude CLI returned error: {data.get('errors', data)}")

    return data.get("result", "")  # the model's text output


def build_decision_prompt(snapshot: dict) -> str:
    """
    Build the prompt sent to Claude every cycle.
    Returns a structured JSON with: action, direction, reasoning, confidence, notes.
    """
    now_str   = snapshot.get("time", "?")
    spot      = snapshot.get("spot", 0)
    open_p    = snapshot.get("open", spot)
    high      = snapshot.get("high", spot)
    low       = snapshot.get("low", spot)
    vix       = snapshot.get("vix", "N/A")
    pcr       = snapshot.get("pcr_value", "N/A")
    max_pain  = snapshot.get("max_pain_level", 0)
    mp_pull   = snapshot.get("max_pain_pull", "N/A")
    oi_bias   = snapshot.get("oi_bias", "N/A")
    oi_range  = snapshot.get("oi_range", "N/A")
    regime    = snapshot.get("regime", "normal")
    confluence_dir   = snapshot.get("confluence_direction", "NEUTRAL")
    confluence_score = snapshot.get("confluence_score", 0)
    conv_level       = snapshot.get("conviction_level", "low")
    checklist_result = snapshot.get("checklist", {})
    open_positions   = snapshot.get("open_positions", [])
    pnl_today        = snapshot.get("pnl_today", 0)
    trades_today     = snapshot.get("trades_today", 0)
    expiry           = snapshot.get("expiry", "?")
    days_to_expiry   = snapshot.get("days_to_expiry", "?")
    morning_thesis   = snapshot.get("morning_thesis", "No thesis available.")
    symbol           = snapshot.get("symbol", "BANKNIFTY")
    news             = snapshot.get("news", {})
    news_bias        = news.get("headline_bias", "N/A")
    news_summary     = news.get("summary", "No news data.")
    news_events      = news.get("key_events", [])
    news_risks       = news.get("risk_flags", [])
    fii_dii          = news.get("fii_dii", "N/A")
    us_overnight     = news.get("us_overnight", "N/A")
    # Intraday technicals
    rsi        = snapshot.get("rsi", "N/A")
    ema_9      = snapshot.get("ema_9", "N/A")
    ema_21     = snapshot.get("ema_21", "N/A")
    vwap       = snapshot.get("vwap", "N/A")
    ema_trend  = snapshot.get("ema_trend", "N/A")
    above_vwap = snapshot.get("above_vwap", "N/A")
    vwap_dist  = snapshot.get("vwap_dist_pct", "N/A")
    orb        = snapshot.get("orb", {})
    orb_signal = snapshot.get("orb_signal", "PENDING")
    orb_high     = orb.get("orb_high", "?")
    orb_low      = orb.get("orb_low", "?")
    orb_complete = orb.get("orb_complete", False)
    fhv          = snapshot.get("first_hour", {})
    fh_direction = fhv.get("FH_Direction", "N/A")
    fh_return    = fhv.get("FH_Return", "N/A")
    fh_strong    = fhv.get("FH_Strong", False)
    daily_rsi    = snapshot.get("daily_rsi", "N/A")
    vol_ratio    = snapshot.get("volume_ratio", "N/A")
    vol_spike    = snapshot.get("volume_spike", False)
    atm_ce_ltp   = snapshot.get("atm_ce_ltp", "N/A")
    atm_pe_ltp   = snapshot.get("atm_pe_ltp", "N/A")
    atm_ce_iv    = snapshot.get("atm_ce_iv", "N/A")
    atm_pe_iv    = snapshot.get("atm_pe_iv", "N/A")
    atm_strike   = snapshot.get("atm_strike", "N/A")

    open_pos_str = "None"
    if open_positions:
        lines = []
        for p in open_positions:
            pnl = p.get("unrealized_pnl", 0)
            lines.append(
                f"  - {p.get('direction','?')} {p.get('strike','?')}{p.get('option_type','?')} "
                f"entry=₹{p.get('entry_premium',0):.1f} "
                f"current=₹{p.get('current_premium',0):.1f} "
                f"SL=₹{p.get('stop_loss',0):.1f} TGT=₹{p.get('target',0):.1f} "
                f"uPnL=₹{pnl:.0f}"
            )
        open_pos_str = "\n".join(lines)

    checklist_str = "N/A"
    if checklist_result:
        gates = checklist_result.get("gates", [])
        passed = checklist_result.get("all_passed", False)
        checklist_str = f"{'GO' if passed else 'NO-GO'} ({checklist_result.get('passed_count',0)}/{checklist_result.get('total_gates',0)} gates)\n"
        for g in gates:
            mark = "✓" if g["passed"] else "✗"
            checklist_str += f"  {mark} {g['name']}: {g['reason']}\n"

    prompt = f"""You are Jack — an expert intraday options trader for {symbol}.
Today is {datetime.now(IST).strftime('%Y-%m-%d %A')}.
Current IST time: {now_str}

## Morning Thesis
{morning_thesis}

## Market News (Claude WebSearch)
- Bias: {news_bias}
- US Overnight: {us_overnight}
- FII/DII: {fii_dii}
- Summary: {news_summary}
- Key Events: {"; ".join(news_events) if news_events else "None"}
- Risk Flags: {"; ".join(news_risks) if news_risks else "None"}

## Live Market Snapshot
- Spot: Rs{spot:,.2f}  |  Open: Rs{open_p:,.2f}  High: Rs{high:,.2f}  Low: Rs{low:,.2f}
- India VIX: {vix}
- Nearest Expiry: {expiry} ({days_to_expiry} days)

## Intraday Technicals (5m candles, {snapshot.get("candle_count",0)} candles)
- Intraday RSI(14): {rsi}  |  Daily RSI: {daily_rsi}
- EMA-9: {ema_9}  |  EMA-21: {ema_21}  |  EMA Trend: {ema_trend}
- VWAP: {vwap}  |  Price: {"ABOVE" if above_vwap else "BELOW"} VWAP ({vwap_dist}%)
- Opening Range: High=Rs{orb_high}  Low=Rs{orb_low}  ({"COMPLETE" if orb_complete else "IN PROGRESS"})
- ORB Breakout Signal: {orb_signal}
- First Hour (9:15-10:15): {fh_direction} {fh_return}%  {"[STRONG]" if fh_strong else "[WEAK]"}
- Last candle volume ratio: {vol_ratio}x avg  {"[SPIKE!]" if vol_spike else ""}

## ATM Options Live Prices (Strike Rs{atm_strike})
- CE LTP: Rs{atm_ce_ltp}  IV: {atm_ce_iv}%
- PE LTP: Rs{atm_pe_ltp}  IV: {atm_pe_iv}%

## Options Data
- PCR (OI): {pcr}
- Max Pain: Rs{max_pain:,} (pull: {mp_pull})
- OI Bias: {oi_bias}
- OI Range: {oi_range}
- Regime: {regime}

## Confluence Engine
- Direction: {confluence_dir}  Conviction: {confluence_score:.3f} ({conv_level})

## Entry Checklist ({confluence_dir})
{checklist_str}

## Open Positions
{open_pos_str}

## Session P&L
- Trades taken: {trades_today}/{MAX_TRADES_PER_DAY}
- Day P&L: ₹{pnl_today:,.0f}  (hard stop at -₹{MAX_DAILY_LOSS_RS:,})

---

## Your Task
Based on ALL the above, decide what to do RIGHT NOW.
Reply in this EXACT JSON format (no markdown, just raw JSON):

{{
  "action": "ENTER" | "HOLD" | "EXIT_ALL" | "NO_TRADE",
  "direction": "LONG" | "SHORT" | null,
  "reasoning": "2-3 sentence explanation of what you see and why",
  "confidence": 1-10,
  "risk_note": "one line about main risk to this trade",
  "journal_thought": "honest reflection — what are you seeing in the tape, any hesitation?"
}}

Rules:
- ENTER only if: conviction >= 0.25 AND checklist passes AND trades_today < {MAX_TRADES_PER_DAY} AND pnl_today > -{MAX_DAILY_LOSS_RS}
- ORB FILTER: if ORB is COMPLETE — only go LONG if orb_signal=LONG (price above ORB high), only go SHORT if orb_signal=SHORT. If INSIDE, wait.
- RSI FILTER: avoid LONG if RSI > 72, avoid SHORT if RSI < 28 (already extended)
- VWAP FILTER: prefer LONG when above VWAP, SHORT when below VWAP
- EXIT_ALL if reversal signs in open positions OR past 15:10 IST
- HOLD if open positions are running well within SL/target range
- NO_TRADE if nothing is set up or conditions are unclear
- Current time is {now_str}. If after 15:10 IST, do NOT enter new trades.
"""
    return prompt


# =============================================================================
# Market data fetcher
# =============================================================================

def fetch_market_snapshot(symbol: str, morning_context: dict) -> dict:
    """Fetch all live data and return a unified snapshot dict."""
    snapshot = {
        "time": datetime.now(IST).strftime("%H:%M"),
        "symbol": symbol,
        "morning_thesis": morning_context.get("morning_thesis", ""),
        "pnl_today": 0,
        "trades_today": 0,
        "open_positions": [],
    }

    try:
        from data.dhan_fetcher import DhanFetcher
        from data.live_candles import LiveCandleFetcher
        from indicators.oi_analysis import OIAnalyzer
        from engine.confluence import ConfluenceScorer
        from engine.entry_checklist import EntryChecklist

        fetcher = DhanFetcher(symbol=symbol)
        candle_fetcher = LiveCandleFetcher(symbol=symbol)

        # ── Spot price ────────────────────────────────────────────────────────
        spot = fetcher.get_spot_price()
        if not spot or spot <= 0:
            logger.warning("No spot price — market may be closed")
            return snapshot

        ohlc = fetcher.get_spot_ohlc() or {}
        snapshot.update({
            "spot": spot,
            "open": ohlc.get("open", spot),
            "high": ohlc.get("high", spot),
            "low":  ohlc.get("low", spot),
        })

        # ── Expiry + Option chain first (needed for ATM LTP) ─────────────────
        expiry = fetcher.get_nearest_expiry()
        chain  = None
        if expiry:
            dte = fetcher.get_days_to_expiry(expiry)
            snapshot["expiry"]         = expiry
            snapshot["days_to_expiry"] = round(dte, 1) if dte else "?"
            chain = fetcher.get_option_chain_df(expiry=expiry)

        # ── Live 5m candles: RSI, EMA, VWAP, ORB, FH, Volume, ATM LTP ───────
        intraday = candle_fetcher.get_full_context(spot=spot, chain_df=chain)
        if intraday:
            fhv = intraday.get("first_hour", {})
            orb = intraday.get("orb", {})
            snapshot.update({
                "rsi":              intraday.get("rsi"),
                "daily_rsi":        intraday.get("daily_rsi"),
                "ema_9":            intraday.get("ema_9"),
                "ema_21":           intraday.get("ema_21"),
                "vwap":             intraday.get("vwap"),
                "above_vwap":       intraday.get("above_vwap"),
                "vwap_dist_pct":    intraday.get("vwap_dist_pct"),
                "ema_trend":        intraday.get("trend"),
                "orb":              orb,
                "orb_signal":       orb.get("orb_signal", "PENDING"),
                "first_hour":       fhv,
                "volume_ratio":     intraday.get("volume_ratio"),
                "volume_spike":     intraday.get("volume_spike"),
                "last_candle_time": intraday.get("last_candle_time"),
                "candle_count":     intraday.get("candle_count", 0),
                # ATM option live prices
                "atm_strike":  intraday.get("atm_strike"),
                "atm_ce_ltp":  intraday.get("atm_ce_ltp"),
                "atm_pe_ltp":  intraday.get("atm_pe_ltp"),
                "atm_ce_iv":   intraday.get("atm_ce_iv"),
                "atm_pe_iv":   intraday.get("atm_pe_iv"),
            })
            # Feed into confluence context — these are the key missing inputs
            morning_context.update({
                "rsi":         intraday.get("rsi"),
                "ema_9":       intraday.get("ema_9"),
                "ema_21":      intraday.get("ema_21"),
                "vwap":        intraday.get("vwap"),
                "first_hour":  fhv,   # weight 0.18 in confluence!
            })
            if intraday.get("daily_rsi"):
                morning_context["daily_rsi"] = intraday["daily_rsi"]
            if intraday.get("vix"):
                snapshot["vix"] = intraday["vix"]
                morning_context["vix"] = intraday["vix"]

            logger.info(
                f"Candles={intraday.get('candle_count')} | "
                f"RSI={intraday.get('rsi')} dRSI={intraday.get('daily_rsi')} | "
                f"EMA9={intraday.get('ema_9')} EMA21={intraday.get('ema_21')} | "
                f"VWAP={intraday.get('vwap')} | "
                f"ORB={orb.get('orb_signal')} | "
                f"FH={fhv.get('FH_Direction')} {fhv.get('FH_Return')}% | "
                f"VolRatio={intraday.get('volume_ratio')} | "
                f"ATM CE={intraday.get('atm_ce_ltp')} PE={intraday.get('atm_pe_ltp')}"
            )

        # ── Option chain + OI (already fetched above) ─────────────────────────
        if chain is not None and not chain.empty:
            from indicators.oi_analysis import OIAnalyzer
            analyzer = OIAnalyzer()
            oi = analyzer.full_analysis(chain, spot)

            pcr_data   = oi.get("pcr_oi", {})
            mp_data    = oi.get("max_pain", {})
            buildup    = oi.get("buildup", {})
            levels     = oi.get("oi_levels", {})
            imm        = levels.get("immediate_range", {})

            snapshot.update({
                "pcr_value":       pcr_data.get("pcr", "N/A"),
                "pcr_interp":      pcr_data.get("interpretation", ""),
                "max_pain_level":  mp_data.get("max_pain", 0),
                "max_pain_pull":   mp_data.get("pull_direction", "N/A"),
                "oi_bias":         buildup.get("classification", "N/A"),
                "oi_range":        (
                    f"Rs{imm.get('lower',0):,.0f} - Rs{imm.get('upper',0):,.0f}"
                    if imm else "N/A"
                ),
            })

            # Pass OI data into confluence context
            morning_context.update({
                "option_chain_snapshot": True,
                "pcr":        pcr_data,
                "max_pain":   mp_data,
                "oi_buildup": buildup,
                "oi_levels":  levels,
            })

        # ── VIX fallback ─────────────────────────────────────────────────────
        if not snapshot.get("vix"):
            snapshot["vix"] = morning_context.get("vix", "N/A")

        # ── News into snapshot ────────────────────────────────────────────────
        snapshot["news"] = morning_context.get("news", {})

        # ── Confluence ────────────────────────────────────────────────────────
        morning_context["spot"]         = spot
        morning_context["current_time"] = snapshot["time"]

        scorer = ConfluenceScorer()
        conf   = scorer.score(morning_context)
        snapshot.update({
            "confluence_direction": conf.get("direction", "NEUTRAL"),
            "confluence_score":     conf.get("conviction", 0),
            "conviction_level":     conf.get("conviction_level", "low"),
            "regime":               morning_context.get("regime", "normal"),
        })

        # ── Entry checklist ───────────────────────────────────────────────────
        direction = conf.get("direction", "NEUTRAL")
        if direction != "NEUTRAL":
            checklist = EntryChecklist()
            cl_result = checklist.evaluate(direction, morning_context)
            snapshot["checklist"] = cl_result
        else:
            snapshot["checklist"] = {}

    except Exception as e:
        logger.error(f"Snapshot fetch error: {e}", exc_info=True)

    return snapshot


# =============================================================================
# Trade executor
# =============================================================================

def execute_trade(decision: dict, snapshot: dict, order_mgr,
                  symbol: str, journal: list) -> dict | None:
    """Select strike and place a paper bracket order."""
    direction = decision.get("direction")
    if not direction:
        return None

    spot    = snapshot.get("spot", 0)
    expiry  = snapshot.get("expiry")
    dte     = snapshot.get("days_to_expiry", 1)

    strike_data = None
    chain       = None

    try:
        from data.dhan_fetcher import DhanFetcher
        from engine.strike_selector import StrikeSelectorV2

        fetcher = DhanFetcher(symbol=symbol)
        if expiry:
            chain = fetcher.get_option_chain_df(expiry=expiry)

        selector   = StrikeSelectorV2(
            lot_size=LOT_SIZES.get(symbol, 15),
            strike_interval=100 if symbol in ("BANKNIFTY", "SENSEX") else 50,
        )
        strike_data = selector.select_best(
            chain, spot, direction,
            days_to_expiry=dte if isinstance(dte, float) else 1.0
        )

    except Exception as e:
        logger.error(f"Strike selection error: {e}")
        # Fallback: simple ATM selection
        interval = 100 if symbol in ("BANKNIFTY", "SENSEX") else 50
        atm = round(spot / interval) * interval
        opt_type = "CE" if direction == "LONG" else "PE"
        strike_data = {
            "strike": atm,
            "option_type": opt_type,
            "premium": 0,
            "suggested_sl": 0,
            "suggested_target": 0,
        }

    if not strike_data:
        logger.warning("No strike data — skipping trade")
        return None

    strike    = int(strike_data["strike"])
    opt_type  = strike_data["option_type"]
    premium   = strike_data.get("premium", 0) or 0
    sl        = strike_data.get("suggested_sl", premium * 0.7)  or premium * 0.7
    target    = strike_data.get("suggested_target", premium * 1.4) or premium * 1.4

    # Look up Dhan security ID
    sec_id = None
    try:
        from data.dhan_client import get_client
        client = get_client()
        sym_fmt = f"{symbol}-{_expiry_label(expiry)}-{strike}-{opt_type}"
        sec_id  = client.lookup_security_id(sym_fmt) or 99999   # fallback
    except Exception:
        sec_id = 99999

    lot_size = LOT_SIZES.get(symbol, 15)
    qty      = lot_size  # 1 lot

    order_id = order_mgr.place_bracket_order(
        transaction_type="BUY",
        security_id=sec_id,
        quantity=qty,
        price=max(premium, 0.05),
        stop_loss=max(sl, 0.05),
        target=max(target, 0.05),
        tag=f"JACK_{direction[:1]}{opt_type}",
    )

    trade = {
        "timestamp":   datetime.now(IST).isoformat(),
        "order_id":    order_id,
        "symbol":      symbol,
        "direction":   direction,
        "strike":      strike,
        "option_type": opt_type,
        "entry_premium": premium,
        "sl":          sl,
        "target":      target,
        "lot_size":    lot_size,
        "security_id": sec_id,
        "reasoning":   decision.get("reasoning", ""),
        "confidence":  decision.get("confidence", 0),
        "risk_note":   decision.get("risk_note", ""),
        "journal_thought": decision.get("journal_thought", ""),
        "spot_at_entry": spot,
        "status":      "open",
        "entry_checklist": snapshot.get("checklist", {}),
        "confluence":  {
            "direction":  snapshot.get("confluence_direction"),
            "score":      snapshot.get("confluence_score"),
        },
        "oi_context": {
            "pcr":      snapshot.get("pcr_value"),
            "max_pain": snapshot.get("max_pain_level"),
            "oi_bias":  snapshot.get("oi_bias"),
        },
    }

    journal.append(trade)
    return trade


def _expiry_label(expiry: str) -> str:
    """Convert '2026-04-17' to 'Apr2026' for Dhan symbol lookup."""
    if not expiry:
        return "Apr2026"
    try:
        dt = datetime.strptime(expiry, "%Y-%m-%d")
        return dt.strftime("%b%Y")
    except Exception:
        return expiry


# =============================================================================
# Position monitor (simple — tracks in memory)
# =============================================================================

def monitor_positions(open_trades: list, snapshot: dict,
                      order_mgr, journal: list) -> float:
    """
    Check each open position against current market price.
    Uses the ATM premium as a proxy for current price.
    Returns realized P&L from closed positions this cycle.
    """
    spot = snapshot.get("spot", 0)
    now  = snapshot.get("time", "00:00")
    pnl  = 0.0

    for trade in list(open_trades):
        if trade["status"] != "open":
            continue

        # Try to get current premium from chain (simplified: use BS proxy)
        current_premium = _estimate_premium(trade, spot, snapshot)
        trade["current_premium"] = current_premium

        entry  = trade["entry_premium"]
        sl     = trade["sl"]
        target = trade["target"]
        lot_sz = trade["lot_size"]

        exit_reason = None
        if current_premium <= sl:
            exit_reason = "STOP_LOSS_HIT"
        elif current_premium >= target:
            exit_reason = "TARGET_HIT"
        elif now >= FORCE_EXIT:
            exit_reason = "TIME_EXIT_15:20"

        if exit_reason:
            realized_pnl = (current_premium - entry) * lot_sz
            pnl += realized_pnl
            trade["status"]       = "closed"
            trade["exit_premium"] = current_premium
            trade["exit_time"]    = now
            trade["exit_reason"]  = exit_reason
            trade["realized_pnl"] = realized_pnl

            # What went right/wrong analysis
            if realized_pnl > 0:
                trade["post_trade_verdict"] = (
                    f"WIN ₹{realized_pnl:.0f} — "
                    f"Exited via {exit_reason}. "
                    f"Entry thesis: {trade.get('reasoning','')[:100]}"
                )
            else:
                trade["post_trade_verdict"] = (
                    f"LOSS ₹{realized_pnl:.0f} — "
                    f"Exited via {exit_reason}. "
                    f"Risk note was: {trade.get('risk_note','')[:100]}"
                )

            open_trades.remove(trade)
            print(f"\n{'='*55}")
            print(f"  POSITION CLOSED — {exit_reason}")
            print(f"  {trade['direction']} {trade['strike']}{trade['option_type']}")
            print(f"  Entry: ₹{entry:.1f} → Exit: ₹{current_premium:.1f}")
            print(f"  P&L: ₹{realized_pnl:,.0f} | Lot size: {lot_sz}")
            print(f"  Verdict: {trade['post_trade_verdict']}")
            print(f"{'='*55}\n")

    return pnl


def _estimate_premium(trade: dict, spot: float, snapshot: dict) -> float:
    """
    Very rough premium estimate for position monitoring.
    In a real system, you'd fetch the live option LTP from Dhan.
    """
    entry  = trade["entry_premium"]
    strike = trade["strike"]
    opt    = trade["option_type"]

    # Intrinsic value proxy
    if opt == "CE":
        intrinsic = max(0, spot - strike)
    else:
        intrinsic = max(0, strike - spot)

    # Entry premium decomposed: assume intrinsic at entry was similar
    spot_at_entry = trade.get("spot_at_entry", spot)
    if opt == "CE":
        intrinsic_at_entry = max(0, spot_at_entry - strike)
    else:
        intrinsic_at_entry = max(0, strike - spot_at_entry)

    time_value_at_entry = max(0, entry - intrinsic_at_entry)
    # Decay time value slightly (rough theta proxy)
    time_value_now = time_value_at_entry * 0.95

    estimated = intrinsic + time_value_now
    return max(estimated, entry * 0.3)   # floor at 30% of entry


# =============================================================================
# Journal writer
# =============================================================================

def save_journal(all_trades: list, daily_pnl: float, symbol: str):
    """Write the day's full journal to disk."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    path  = JOURNAL_DIR / f"{today}_live.json"

    summary = {
        "date":       today,
        "symbol":     symbol,
        "mode":       "PAPER",
        "daily_pnl":  daily_pnl,
        "trades":     all_trades,
        "generated":  datetime.now(IST).isoformat(),
    }

    with open(path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Journal saved → {path}")
    return path


# =============================================================================
# Main loop
# =============================================================================

def is_market_open(now: datetime) -> bool:
    t = now.strftime("%H:%M")
    return MARKET_OPEN <= t <= MARKET_CLOSE


def run_live_loop(symbol: str = "BANKNIFTY",
                  interval_sec: int = 300,
                  api_key: str = None):
    """
    Main loop. Runs until market close or KeyboardInterrupt.
    Uses the Claude Code CLI (`claude -p`) as the AI brain — no separate API key needed.
    """
    print("\n" + "="*60)
    print(f"  JACK LIVE LOOP — {symbol}  [PAPER MODE]")
    print(f"  Interval: {interval_sec}s ({interval_sec//60}m)")
    print(f"  AI Brain: Claude Code CLI (`claude -p`)")
    print(f"  Started: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("="*60 + "\n")

    # Verify claude CLI is accessible
    try:
        test = subprocess.run("claude --version", capture_output=True, text=True, timeout=10, shell=True)
        print(f"  Claude CLI: {test.stdout.strip() or 'OK'}")
    except Exception:
        print("ERROR: `claude` CLI not found in PATH.")
        print("  Make sure Claude Code is installed and on your PATH.")
        sys.exit(1)

    # ── Morning prep (once) ───────────────────────────────────────────────────
    print("Running morning prep...")
    from scripts.morning_prep import morning_prep
    morning_context = morning_prep(symbol=symbol, mode="live")

    if morning_context.get("blocked"):
        print(f"Trading blocked: {morning_context.get('reason')}")
        sys.exit(0)

    # ── News fetch (separate Claude instance with WebSearch) ─────────────────
    print("  Fetching market news via Claude WebSearch...")
    from data.news_fetcher import fetch_market_news
    news = fetch_market_news(symbol=symbol)
    morning_context["news"] = news
    print(f"  News bias: {news.get('headline_bias')} | {news.get('summary','')[:120]}")

    # Ensure morning_context has a live spot (morning_prep may return 0 if parser was stale)
    if not morning_context.get("spot") or morning_context["spot"] <= 0:
        try:
            from data.dhan_fetcher import DhanFetcher
            _f = DhanFetcher(symbol=symbol)
            _spot = _f.get_spot_price()
            if _spot and _spot > 0:
                morning_context["spot"] = _spot
                print(f"  Live spot override: Rs{_spot:,.2f}")
        except Exception:
            pass

    # ── Order manager ─────────────────────────────────────────────────────────
    from data.dhan_orders import DhanOrderManager
    order_mgr = DhanOrderManager(mode="paper")

    # ── State ─────────────────────────────────────────────────────────────────
    all_trades:    list  = []
    open_trades:   list  = []
    daily_pnl:     float = 0.0
    trades_today:  int   = 0
    cycle_num:     int   = 0

    try:
        while True:
            now_ist = datetime.now(IST)

            if not is_market_open(now_ist):
                if now_ist.strftime("%H:%M") > MARKET_CLOSE:
                    print("\nMarket closed. Saving journal and exiting.")
                    break
                print(f"  Market not open yet ({now_ist.strftime('%H:%M')} IST). "
                      f"Waiting {interval_sec}s...")
                time.sleep(interval_sec)
                continue

            cycle_num += 1
            print(f"\n{'─'*60}")
            print(f"  CYCLE {cycle_num}  |  {now_ist.strftime('%H:%M:%S IST')}")
            print(f"{'─'*60}")

            # ── Fetch market snapshot ─────────────────────────────────────────
            print("  Fetching live market data...")
            snapshot = fetch_market_snapshot(symbol, morning_context)
            snapshot["open_positions"] = open_trades
            snapshot["pnl_today"]      = daily_pnl
            snapshot["trades_today"]   = trades_today

            spot = snapshot.get("spot", 0)
            if not spot:
                print("  No spot price. Skipping cycle.")
                time.sleep(interval_sec)
                continue

            print(f"  Spot: ₹{spot:,.2f}  |  PCR: {snapshot.get('pcr_value','N/A')}  "
                  f"|  OI Bias: {snapshot.get('oi_bias','N/A')}")
            print(f"  Confluence: {snapshot.get('confluence_direction','?')} "
                  f"({snapshot.get('conviction_level','?')} "
                  f"{snapshot.get('confluence_score',0):.3f})")

            # ── Monitor existing positions ────────────────────────────────────
            if open_trades:
                closed_pnl = monitor_positions(
                    open_trades, snapshot, order_mgr, all_trades
                )
                daily_pnl += closed_pnl

            # ── Hard stop check ───────────────────────────────────────────────
            if daily_pnl < -MAX_DAILY_LOSS_RS:
                print(f"\n  HARD STOP HIT: Day P&L ₹{daily_pnl:,.0f}. No more trades.")
                save_journal(all_trades, daily_pnl, symbol)
                time.sleep(interval_sec)
                continue

            # ── Ask Claude ────────────────────────────────────────────────────
            print("  Consulting Claude Code CLI...")
            try:
                prompt   = build_decision_prompt(snapshot)
                raw_resp = ask_claude(prompt)

                # Parse JSON — strip markdown fences robustly
                clean = raw_resp.strip()
                # Find first { and last } to extract JSON
                start = clean.find("{")
                end   = clean.rfind("}")
                if start != -1 and end != -1:
                    clean = clean[start:end + 1]
                decision = json.loads(clean)

            except json.JSONDecodeError as e:
                print(f"  Claude response not valid JSON: {e}")
                print(f"  Raw: {raw_resp[:300]}")
                decision = {"action": "NO_TRADE", "reasoning": "parse error"}
            except Exception as e:
                print(f"  Claude API error: {e}")
                decision = {"action": "NO_TRADE", "reasoning": str(e)}

            action    = decision.get("action", "NO_TRADE")
            direction = decision.get("direction")

            print(f"\n  CLAUDE DECISION: {action}")
            print(f"  Direction:  {direction or 'N/A'}")
            print(f"  Reasoning:  {decision.get('reasoning','')}")
            print(f"  Confidence: {decision.get('confidence','?')}/10")
            print(f"  Risk note:  {decision.get('risk_note','')}")
            print(f"  Thought:    {decision.get('journal_thought','')}")

            # ── Execute ───────────────────────────────────────────────────────
            if action == "ENTER" and direction and trades_today < MAX_TRADES_PER_DAY:
                print(f"\n  Executing PAPER {direction} order...")
                trade = execute_trade(
                    decision, snapshot, order_mgr, symbol, all_trades
                )
                if trade:
                    open_trades.append(trade)
                    trades_today += 1
                    print(f"  ORDER PLACED: {trade['strike']}{trade['option_type']} "
                          f"entry=₹{trade['entry_premium']:.1f} "
                          f"SL=₹{trade['sl']:.1f} TGT=₹{trade['target']:.1f}")

            elif action == "EXIT_ALL" and open_trades:
                print("  Claude says EXIT ALL — closing all positions at market.")
                for trade in list(open_trades):
                    trade["status"]       = "closed"
                    trade["exit_premium"] = trade.get("current_premium", trade["entry_premium"])
                    trade["exit_time"]    = now_ist.strftime("%H:%M")
                    trade["exit_reason"]  = "AI_EXIT_SIGNAL"
                    pnl = (trade["exit_premium"] - trade["entry_premium"]) * trade["lot_size"]
                    trade["realized_pnl"] = pnl
                    trade["post_trade_verdict"] = (
                        f"AI EXIT: P&L ₹{pnl:.0f} | "
                        f"Journal: {decision.get('journal_thought','')}"
                    )
                    daily_pnl += pnl
                    open_trades.remove(trade)
                    print(f"  Closed {trade['strike']}{trade['option_type']} "
                          f"P&L: ₹{pnl:,.0f}")

            else:
                print(f"  Action: {action} — no order placed.")

            # ── Status line ───────────────────────────────────────────────────
            print(f"\n  Session: {trades_today} trades | "
                  f"Open: {len(open_trades)} | "
                  f"Day P&L: ₹{daily_pnl:,.0f}")

            # ── Auto-save journal every cycle ─────────────────────────────────
            save_journal(all_trades, daily_pnl, symbol)

            # ── Sleep ─────────────────────────────────────────────────────────
            next_at = datetime.now(IST) + timedelta(seconds=interval_sec)
            print(f"  Next cycle at {next_at.strftime('%H:%M:%S')}")
            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")

    # ── End of day wrap-up ────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  END OF DAY SUMMARY")
    print("="*60)

    # Force-close any remaining positions
    for trade in list(open_trades):
        trade["status"]       = "closed"
        trade["exit_time"]    = datetime.now(IST).strftime("%H:%M")
        trade["exit_reason"]  = "EOD_CLOSE"
        trade["exit_premium"] = trade.get("current_premium", trade["entry_premium"])
        pnl = (trade["exit_premium"] - trade["entry_premium"]) * trade["lot_size"]
        trade["realized_pnl"] = pnl
        trade["post_trade_verdict"] = f"EOD close. P&L: ₹{pnl:.0f}"
        daily_pnl += pnl
        print(f"  EOD Close: {trade['strike']}{trade['option_type']} P&L ₹{pnl:,.0f}")

    print(f"\n  Total trades: {trades_today}")
    print(f"  Final day P&L: ₹{daily_pnl:,.0f}")

    # ── Final journal ──────────────────────────────────────────────────────────
    journal_path = save_journal(all_trades, daily_pnl, symbol)
    print(f"  Journal: {journal_path}")

    # ── Ask Claude for end-of-day retrospective ───────────────────────────────
    if all_trades:
        print("\n  Generating AI post-market retrospective (Claude Code CLI)...")
        try:
            retro_prompt = f"""You are Jack. Today's paper trading session just ended.

Symbol: {symbol}
Date: {datetime.now(IST).strftime('%Y-%m-%d')}
Final P&L: ₹{daily_pnl:,.0f}
Trades taken: {trades_today}

Trade details:
{json.dumps(all_trades, indent=2, default=str)}

Write a concise post-market retrospective (max 300 words):
1. What did I see correctly today?
2. What did I miss or get wrong?
3. Were the entry/exit timing decisions sound?
4. What should I do differently tomorrow?
5. One specific system improvement to consider.
"""
            retro = ask_claude(retro_prompt)
            print("\n  POST-MARKET RETROSPECTIVE (Claude):")
            print("  " + "\n  ".join(retro.split("\n")))

            # Save to journal
            retro_path = JOURNAL_DIR / f"{datetime.now(IST).strftime('%Y-%m-%d')}_retro.md"
            with open(retro_path, "w") as f:
                f.write(f"# Jack Retrospective — {datetime.now(IST).strftime('%Y-%m-%d')}\n\n")
                f.write(f"**Day P&L:** ₹{daily_pnl:,.0f}\n")
                f.write(f"**Trades:** {trades_today}\n\n")
                f.write(retro)
            print(f"\n  Retrospective saved → {retro_path}")

        except Exception as e:
            print(f"  Retrospective error: {e}")

    print("\n  Done. Goodbye.\n")


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Jack Live Loop — paper trading with Claude AI")
    parser.add_argument("--symbol",   default="BANKNIFTY", choices=["BANKNIFTY", "NIFTY", "FINNIFTY"])
    parser.add_argument("--interval", type=int, default=300, help="Seconds between cycles (default 300 = 5min)")
    args = parser.parse_args()

    run_live_loop(
        symbol=args.symbol,
        interval_sec=args.interval,
    )
