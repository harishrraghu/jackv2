"""
All AI prompts for Jack v3.

Optimized for gemini-3-flash: explicit JSON examples, short unambiguous
instructions, no implicit context. Each prompt tells the model exactly
what data means and exactly what JSON to return.
"""
import json


# ─────────────────────────────────────────────────
#  System prompts — kept short for flash models
# ─────────────────────────────────────────────────

INTRADAY_SYSTEM_PROMPT = """You are Jack, an algorithmic trading AI for BankNifty (Indian NSE index).

HARD RULES — never break these:
1. Respond ONLY in valid JSON. Zero prose outside the JSON.
2. Never invent price levels. Use only the numbers provided in the prompt.
3. Stop loss must be between 0.2% and 1.5% from entry price.
4. Target must give Reward:Risk >= 1.2 (target move >= 1.2x stop move).
5. BankNifty lot size = 15. Trades are index futures (not options).
6. When no clear signal exists, output action "HOLD". Do not force trades.
7. After 13:30 IST, only EXIT or HOLD — no new entries.
8. If a position is open and price hits stop_loss level, output "EXIT".

MARKET CONTEXT:
- BankNifty is an Indian bank sector index, currently trading 50,000–60,000.
- Normal daily range: 200–600 points. Volatile days: 600–1200 points.
- 09:15 open is often volatile — avoid entry before 09:30 unless thesis is very strong.
- VWAP is the key intraday level: above VWAP = bullish, below = bearish.
- RSI above 60 confirms momentum. RSI below 40 confirms selling pressure.
- PCR (Put-Call Ratio) > 1.2 = bullish sentiment. PCR < 0.8 = bearish sentiment."""

NIGHTLY_SYSTEM_PROMPT = """You are a post-trade analyst reviewing BankNifty trading results.

HARD RULES:
1. Respond ONLY in valid JSON. Zero prose outside the JSON.
2. Be specific with numbers. Bad: "widen stops". Good: "use 1.2x ATR stops".
3. Identify whether outcomes were skill (repeatable) or luck (one-off).
4. Proposed strategies must have exact, testable entry conditions with numbers.
5. Focus on actionable lessons — what to do differently tomorrow."""


# ─────────────────────────────────────────────────
#  Pre-market thesis prompt
# ─────────────────────────────────────────────────

def pre_market_thesis_prompt(
    dependents: dict,
    research: dict,
    recent_journal: list,
    strategy_rankings: list,
) -> str:
    """
    Build the pre-market thesis prompt for gemini-3-flash.
    Called once at 08:55 before market open.
    """
    dep = dependents or {}

    # Extract clean dependent values
    gift_chg = dep.get("gift_nifty", {}).get("pct_change", 0)
    sp500_chg = dep.get("sp500", {}).get("pct_change", 0)
    vix = dep.get("india_vix", {}).get("value", 0)
    fii_net = dep.get("fii_dii", {}).get("fii_net_cr", 0)
    usd_inr = dep.get("usd_inr", {}).get("pct_change", 0)
    crude_chg = dep.get("crude_oil", {}).get("pct_change", 0)
    weighted_bias = dep.get("weighted_bias", 0)
    bias_dir = dep.get("bias_direction", "NEUTRAL")

    # Summarize journal (last 5 days)
    journal_lines = []
    for e in (recent_journal or [])[:5]:
        d = e.get("date", "?")
        t = e.get("thesis", {})
        direction = t.get("direction", "?") if isinstance(t, dict) else "?"
        pnl = e.get("daily_review", {}).get("total_pnl", 0)
        lesson = e.get("lesson", "")
        journal_lines.append(f"  {d}: thesis={direction}, pnl=Rs.{pnl:.0f}, lesson={lesson!r}")
    journal_block = "\n".join(journal_lines) if journal_lines else "  No history yet."

    # Top ranked strategies
    strat_lines = []
    for s in (strategy_rankings or [])[:3]:
        name = s.get("strategy", "?")
        wr = s.get("win_rate_pct", 0)
        trades = s.get("total_trades", 0)
        strat_lines.append(f"  {name}: win_rate={wr:.0f}%, trades={trades}")
    strat_block = "\n".join(strat_lines) if strat_lines else "  No rankings yet."

    # News summary
    headlines = (research or {}).get("headlines", [])
    sentiment = (research or {}).get("sentiment", "NEUTRAL")
    key_events = (research or {}).get("key_events", [])
    news_block = f"  sentiment={sentiment}, events={key_events[:3]}, headlines={headlines[:3]}"

    return f"""TASK: Generate a BankNifty trading thesis for today based on pre-market data.

PRE-MARKET SIGNALS:
  gift_nifty_change={gift_chg:+.2f}%   (positive = BankNifty likely opens higher)
  sp500_change={sp500_chg:+.2f}%       (US market direction)
  india_vix={vix:.1f}              (VIX < 15 = calm, 15-20 = normal, > 20 = fearful)
  fii_net_buying=Rs.{fii_net:.0f}cr  (positive = foreign buyers, negative = sellers)
  usd_inr_change={usd_inr:+.2f}%      (negative = rupee strengthening = bullish)
  crude_oil_change={crude_chg:+.2f}%  (negative = lower crude = good for India)
  weighted_bias_score={weighted_bias:.2f}  (range -1.0 to +1.0: positive = bullish)
  overall_bias={bias_dir}

NEWS:
{news_block}

RECENT TRADING JOURNAL (most recent first):
{journal_block}

TOP STRATEGIES BY RECENT WIN RATE:
{strat_block}

INTERPRETATION GUIDE:
- weighted_bias > 0.3 AND gift_nifty > 0.3% = strong BULLISH thesis
- weighted_bias < -0.3 AND gift_nifty < -0.3% = strong BEARISH thesis
- VIX > 18 = high volatility, lower confidence, wider expected range
- FII buying > Rs.500cr = strong institutional support = bullish
- FII selling < Rs.-500cr = institutional exit = bearish

OUTPUT: Respond with EXACTLY this JSON and nothing else:
{{
  "direction": "BULLISH",
  "confidence": 0.72,
  "reasoning": "Gift Nifty up 0.4% and FII bought Rs.600cr yesterday. VIX at 14 signals calm open.",
  "key_factors": ["Gift Nifty positive", "FII net buying", "VIX low"],
  "suggested_strategy": "first_hour_verdict",
  "risk_note": "RBI meeting at 10:00 — avoid early entries",
  "expected_range_pts": 350,
  "bias_entry_after": "10:15"
}}

RULES FOR YOUR OUTPUT:
- direction: must be one of "BULLISH", "BEARISH", "NEUTRAL"
- confidence: float 0.0 to 1.0 (0.5 = uncertain, 0.8 = high conviction)
- reasoning: 1-2 sentences citing specific numbers from the data above
- key_factors: exactly 3 items from the data above
- suggested_strategy: one of [first_hour_verdict, gap_fill, vwap_reversion, streak_fade, bb_squeeze, gap_up_fade, theta_harvest] or null
- expected_range_pts: integer, typical BankNifty range is 200-600 pts
- bias_entry_after: "HH:MM" format, earliest time to enter (09:30 minimum, 10:15 if uncertain)

Now generate the thesis for today:"""


# ─────────────────────────────────────────────────
#  5-minute tick evaluation prompt
# ─────────────────────────────────────────────────

def five_min_evaluation_prompt(
    thesis: dict,
    current_candle: dict,
    option_chain_summary: dict,
    open_position: dict,
    indicators: dict,
    time: str,
    daily_pnl: float,
    ticks_below_vwap: int = 0,
) -> str:
    """
    Build the 5-minute tick evaluation prompt for gemini-3-flash.
    Called up to 75 times per day — kept compact.
    """
    # Candle values
    o = current_candle.get("open", current_candle.get("Open", 0))
    h = current_candle.get("high", current_candle.get("High", 0))
    l = current_candle.get("low", current_candle.get("Low", 0))
    c = current_candle.get("close", current_candle.get("Close", 0))

    # Key indicators only
    rsi = None
    ema20 = None
    vwap = None
    atr = None
    for k, v in (indicators or {}).items():
        kl = k.lower()
        try:
            fv = round(float(v), 2)
            if "rsi" in kl and rsi is None:
                rsi = fv
            elif "ema_20" in kl or kl == "ema20":
                ema20 = fv
            elif "vwap" in kl and "upper" not in kl and "lower" not in kl and vwap is None:
                vwap = fv
            elif "atr" in kl and atr is None:
                atr = fv
        except (TypeError, ValueError):
            pass

    # Option chain
    pcr = option_chain_summary.get("pcr", "N/A")
    max_pain = option_chain_summary.get("max_pain", "N/A")
    atm_iv = option_chain_summary.get("atm_iv", "N/A")

    # Open position
    pos_block = "None"
    if open_position:
        ep = open_position.get("entry_price", 0)
        sl = open_position.get("stop_loss", 0)
        tgt = open_position.get("target", 0)
        direction = open_position.get("direction", "")
        pnl_pts = (c - ep) * (1 if direction == "LONG" else -1)
        sl_distance = abs(c - sl)
        pos_block = (
            f"direction={direction}, entry={ep:.0f}, current={c:.0f}, "
            f"pnl_pts={pnl_pts:+.0f}, sl={sl:.0f} (distance={sl_distance:.0f}pts), target={tgt:.0f}"
        )

    # Price vs VWAP context
    vwap_note = ""
    if vwap and c:
        diff = c - vwap
        vwap_note = f" (price is {abs(diff):.0f}pts {'ABOVE' if diff > 0 else 'BELOW'} VWAP)"

    # Time-based rules
    time_note = ""
    h_int = int(time.split(":")[0]) if ":" in time else 9
    m_int = int(time.split(":")[1]) if ":" in time else 15
    if h_int > 13 or (h_int == 13 and m_int >= 30):
        time_note = " [AFTER 13:30 — only EXIT or HOLD allowed]"
    elif h_int == 9 and m_int < 30:
        time_note = " [FIRST 15 MIN — avoid new entries unless very high conviction]"

    thesis_dir = thesis.get("direction", "NEUTRAL")
    thesis_conf = thesis.get("confidence", 0.5)
    thesis_reason = thesis.get("reasoning", "")[:100]

    # Thesis override: sustained VWAP rejection flips available setups
    # 18 ticks = 90 minutes (18 x 5min) of price below VWAP
    override_block = ""
    if ticks_below_vwap >= 18 and thesis_dir == "BULLISH":
        override_block = f"""
THESIS OVERRIDE — ACTIVE:
  Price has been BELOW VWAP for {ticks_below_vwap * 5} minutes ({ticks_below_vwap} ticks).
  The market is REJECTING the bullish thesis. The real direction is BEARISH.
  You MUST treat this as a BEARISH day for entry purposes:
  - IGNORE all ENTER_LONG setups below.
  - Use ENTER_SHORT setups instead (Setup A/B/C for BEARISH direction apply now).
  - Set thesis_update to "FLIPPED".
  - A SHORT entry is valid if: price < VWAP AND RSI < 52 AND price < EMA_20.
"""
    elif ticks_below_vwap >= 12 and thesis_dir == "BULLISH":
        override_block = f"""
THESIS WARNING:
  Price has been BELOW VWAP for {ticks_below_vwap * 5} minutes ({ticks_below_vwap} ticks).
  The bullish thesis is weakening. Set thesis_update to "WEAKENING".
  Do NOT enter LONG. Consider ENTER_SHORT if RSI < 48 AND price < EMA_20.
"""

    return f"""TICK EVALUATION — TIME: {time}{time_note} | DAILY P&L: Rs.{daily_pnl:.0f}{override_block}

THESIS: {thesis_dir} (confidence: {thesis_conf:.0%}) — {thesis_reason}

CURRENT CANDLE: Open={o:.0f} High={h:.0f} Low={l:.0f} Close={c:.0f}

INDICATORS:
  RSI(14)={rsi if rsi is not None else 'N/A'}   (>60=bullish momentum, <40=bearish, 40-60=neutral)
  EMA_20={ema20 if ema20 is not None else 'N/A'}  (price above EMA = uptrend, below = downtrend)
  VWAP={vwap if vwap is not None else 'N/A'}{vwap_note}
  ATR(14)={atr if atr is not None else 'N/A'}  (typical 5-min candle size for stop placement)

OPTION CHAIN:
  PCR={pcr}  (>1.2=bullish, <0.8=bearish, 0.8-1.2=neutral)
  MaxPain={max_pain}  (market tends toward max pain near expiry)
  ATM_IV={atm_iv}%  (high IV = bigger expected move)

OPEN POSITION: {pos_block}

DECISION RULES:
- ENTER_LONG:
    Setup A (normal): price above VWAP AND above EMA_20, RSI between 52-72, thesis=BULLISH
    Setup B (momentum): RSI > 72 AND price > VWAP by less than 0.5%, thesis=BULLISH with conf>0.75 (ride the trend)
    Setup C (pullback): RSI between 40-55 AND price at or just crossed back above VWAP, thesis=BULLISH
- ENTER_SHORT:
    Setup A (normal): price below VWAP AND below EMA_20, RSI between 28-48, thesis=BEARISH
    Setup B (momentum): RSI < 28 AND price < VWAP, thesis=BEARISH with conf>0.75
    Setup C (pullback): RSI between 48-60 AND price just crossed below VWAP, thesis=BEARISH
- EXIT: position in loss beyond SL OR target reached OR thesis flipped OR after 13:30
- TIGHTEN_SL: position profitable by 1x ATR — move stop to breakeven
- HOLD: no clear setup matches, position is within planned range
- WAIT: first 15 minutes of session (09:15-09:30) or conflicting signals

STOP LOSS RULES:
- Minimum stop distance: 40 points (one ATR for BankNifty)
- Maximum stop distance: 150 points (1.5% of ~10,000 options lot value)
- If ATR is available: use 1.0x to 1.2x ATR as stop distance
- If ATR is NaN: use 80 points as default stop

TARGET RULES:
- Minimum target: 1.5x the stop distance (ensures R:R > 1.5)
- Ideal target: 2x to 3x the stop distance
- Example: stop=80pts → target minimum 120pts, ideal 160-240pts

For ENTER_LONG: entry_price=current_close, stop_loss=entry-stop_distance, target=entry+target_distance
For ENTER_SHORT: entry_price=current_close, stop_loss=entry+stop_distance, target=entry-target_distance

Respond with EXACTLY this JSON and nothing else:
{{
  "thesis_update": "CONFIRMED",
  "confidence": 0.75,
  "action": "HOLD",
  "entry_price": null,
  "stop_loss": null,
  "target": null,
  "reasoning": "Price below VWAP, waiting for reclaim"
}}

Valid values:
- thesis_update: "CONFIRMED" | "WEAKENING" | "FLIPPED" | "NEUTRAL"
- action: "HOLD" | "ENTER_LONG" | "ENTER_SHORT" | "EXIT" | "TIGHTEN_SL" | "WAIT"
- entry_price, stop_loss, target: exact numbers (not null) when action is ENTER_LONG or ENTER_SHORT
- reasoning: max 100 characters, cite a specific number"""


# ─────────────────────────────────────────────────
#  Post-trade journal entry prompt
# ─────────────────────────────────────────────────

def journal_entry_prompt(trade: dict, market_context: dict) -> str:
    """Prompt for single-trade post-trade AI review by gemini-3-flash."""

    direction = trade.get("direction", "?")
    entry_price = trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    net_pnl = trade.get("net_pnl", 0)
    exit_reason = trade.get("exit_reason", "unknown")
    duration = trade.get("duration_minutes", "?")

    thesis = market_context.get("thesis", {})
    thesis_dir = thesis.get("direction", "?") if isinstance(thesis, dict) else "?"
    thesis_conf = thesis.get("confidence", 0) if isinstance(thesis, dict) else 0
    matched = market_context.get("direction_matched_thesis", False)

    move_pts = (exit_price - entry_price) * (1 if direction == "LONG" else -1)

    return f"""TASK: Write a trading journal entry for this completed BankNifty trade.

TRADE DETAILS:
  direction={direction}
  entry_price={entry_price:.0f}
  exit_price={exit_price:.0f}
  price_move={move_pts:+.0f}pts
  net_pnl=Rs.{net_pnl:.0f}
  exit_reason={exit_reason}
  held_for={duration} minutes

PRE-MARKET THESIS:
  direction={thesis_dir} (confidence={thesis_conf:.0%})
  trade_matched_thesis={matched}

QUESTIONS TO ANSWER:
1. Was the entry well-timed? (Did price move favorably immediately, or did it struggle?)
2. Was the exit appropriate? (Was it stopped out, hit target, or force-closed?)
3. Did the trade align with the thesis?
4. What is the single most important lesson?

Respond with EXACTLY this JSON and nothing else:
{{
  "summary": "LONG from 56200 stopped out at 56120 for Rs.-1200 loss. Entry was premature before VWAP confirmation.",
  "entry_quality": "poor",
  "exit_quality": "good",
  "what_worked": "Stop loss protected capital, limited loss to planned amount",
  "what_failed": "Entered before price reclaimed VWAP, thesis not yet confirmed",
  "lesson": "Wait for price to close above VWAP before entering LONG trades",
  "strategy_note": "Reduce position size in first 30 minutes when volatility is high",
  "market_read_accuracy": "partial"
}}

Valid values:
- entry_quality / exit_quality: "good" | "fair" | "poor"
- market_read_accuracy: "accurate" | "partial" | "wrong"
- lesson: ONE sentence, specific and actionable, with numbers where possible"""


# ─────────────────────────────────────────────────
#  Nightly comprehensive review prompt
# ─────────────────────────────────────────────────

def nightly_review_prompt(journal_entries: list, strategy_performance: list) -> str:
    """
    Nightly review prompt optimized for gemini-3-flash.
    Called by run_nightly.py after market close.
    """
    # Summarize journal entries compactly
    journal_compact = []
    for e in (journal_entries or [])[:10]:
        d = e.get("date", "?")
        dr = e.get("daily_review", {})
        trades = dr.get("trades_taken", 0)
        pnl = dr.get("total_pnl", 0)
        wins = dr.get("wins", 0)
        thesis = e.get("thesis", {})
        t_dir = thesis.get("direction", "?") if isinstance(thesis, dict) else "?"
        lessons = [tr.get("ai_review", {}).get("lesson", "") for tr in e.get("trades", []) if tr.get("ai_review")]
        journal_compact.append({
            "date": d,
            "thesis": t_dir,
            "trades": trades,
            "wins": wins,
            "pnl": round(pnl),
            "lessons": lessons[:2],
        })

    # Strategy performance summary
    strat_compact = []
    for s in (strategy_performance or [])[:6]:
        strat_compact.append({
            "strategy": s.get("strategy", "?"),
            "win_rate": f"{s.get('win_rate_pct', 0):.0f}%",
            "avg_pnl": round(s.get("avg_pnl", 0)),
            "trades": s.get("total_trades", 0),
        })

    total_pnl = sum(e.get("daily_review", {}).get("total_pnl", 0) for e in (journal_entries or []))
    total_trades = sum(e.get("daily_review", {}).get("trades_taken", 0) for e in (journal_entries or []))
    total_wins = sum(e.get("daily_review", {}).get("wins", 0) for e in (journal_entries or []))
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    return f"""TASK: Review the last {len(journal_entries or [])} trading days and provide actionable analysis.

PERFORMANCE SUMMARY:
  total_pnl=Rs.{total_pnl:.0f}
  total_trades={total_trades}
  wins={total_wins}
  win_rate={win_rate:.1f}%

DAILY JOURNAL (most recent last):
{json.dumps(journal_compact, indent=2)}

STRATEGY PERFORMANCE (last 20 days):
{json.dumps(strat_compact, indent=2)}

ANALYSIS REQUIRED:
1. Is the system profitable? What is driving wins/losses?
2. Which strategies are working and which should be avoided?
3. What parameter adjustments would improve performance? (use specific numbers)
4. What new pattern or strategy should be explored?
5. What is the expected market regime tomorrow?

Respond with EXACTLY this JSON and nothing else:
{{
  "performance_summary": "System made Rs.12000 over 10 days with 55% win rate. Profitable days cluster on high-VIX trend days. Losses come from ranging market entries.",
  "parameter_adjustments": [
    {{
      "strategy": "vwap_reversion",
      "parameter": "rsi_threshold",
      "current_value": 30,
      "suggested_value": 35,
      "reasoning": "Current threshold misses entries when RSI bounces at 33-35"
    }}
  ],
  "new_strategy_proposal": {{
    "name": "opening_range_breakout",
    "description": "Enter on breakout of first 15-min high/low with volume confirmation",
    "entry_conditions": ["price breaks first_15min_high", "volume > 1.5x average", "RSI > 55"],
    "indicators_needed": ["rsi", "vwap", "atr"],
    "time_window": "09:30-10:30",
    "expected_win_rate_pct": 58,
    "confidence": "medium"
  }},
  "regime_insights": "Last 10 days = choppy range-bound market. VWAP reversion worked better than trend-following. Reduce position size until clear trend resumes.",
  "tomorrow_bias": "NEUTRAL",
  "tomorrow_note": "No major events. Watch 56000 as key support. A break below = bearish, hold above = range continuation."
}}

RULES:
- parameter_adjustments: list of 0-3 adjustments. Only suggest if you have clear evidence.
- new_strategy_proposal: one specific idea or null if nothing obvious
- tomorrow_bias: "BULLISH" | "BEARISH" | "NEUTRAL"
- be specific with numbers in all fields"""
