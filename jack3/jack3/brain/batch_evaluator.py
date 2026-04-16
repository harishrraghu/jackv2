"""
Batch AI Evaluator for historical backtesting.

Instead of making one API call per 5-minute candle (75 calls/day × N days),
this module sends ALL candles for N days in a SINGLE prompt and gets back
a complete JSON decision cache.

Usage:
    evaluator = BatchEvaluator(ai_client)
    cache = evaluator.evaluate_days(days_data)
    # cache is written to disk automatically

The cache format:
    {
      "2026-04-10": {
        "09:15": {"action": "HOLD", ...},
        "09:20": {"action": "ENTER_LONG", "entry_price": 52100, ...},
        ...
      },
      "2026-04-11": { ... }
    }

The regular Evaluator in evaluator.py checks this cache before making any
live API call — so the rest of the system (loop.py, journal, etc.) works
exactly as before, just reads from disk instead of calling the AI each time.
"""

import json
import os
from datetime import date
from typing import Optional

BATCH_SYSTEM_PROMPT = """You are Jack, an algorithmic trading AI for BankNifty (Indian NSE index).

You will receive multiple days of 5-minute candle data. For EACH candle on EACH day,
decide the trading action based on the market state at that moment.

HARD RULES — never break these:
1. Respond ONLY in valid JSON. Zero prose outside the JSON.
2. Never invent price levels. Use ONLY the numbers provided in the candle data.
3. Stop loss must be 40–150 points from entry (0.08%–0.3% for BankNifty at ~50000).
4. Target must give Reward:Risk >= 1.5 (target move >= 1.5x stop move).
5. BankNifty lot size = 15. Trades are index futures (not options).
6. When no clear signal exists, output action "HOLD". Do not force trades.
7. After 13:30 IST, only EXIT or HOLD — no new entries.
8. If a position is open and price hits stop_loss level, output action "EXIT".
9. Only ONE position can be open at a time. Once entered, do not ENTER again until EXIT.
10. Track position state across candles within the same day — if you entered at 10:00,
    the 10:05 candle should manage that position (EXIT / TIGHTEN_SL / HOLD).

MARKET CONTEXT:
- BankNifty is an Indian bank sector index, currently trading 50,000–60,000.
- Normal daily range: 200–600 points. Volatile days: 600–1200 points.
- 09:15 open is often volatile — avoid entry before 09:30 unless thesis is very strong.
- VWAP is the key intraday level: above VWAP = bullish, below = bearish.
- RSI above 60 confirms momentum. RSI below 40 confirms selling pressure.
- PCR (Put-Call Ratio) > 1.2 = bullish sentiment. PCR < 0.8 = bearish sentiment.

ENTRY RULES:
- ENTER_LONG: price above VWAP AND above EMA_20, RSI between 52–72, thesis=BULLISH
- ENTER_SHORT: price below VWAP AND below EMA_20, RSI between 28–48, thesis=BEARISH
- WAIT: first 15 min (09:15–09:29) or conflicting signals

STOP LOSS RULES:
- Minimum stop: 40 points. Maximum stop: 150 points.
- Preferred: 1.0x ATR as stop distance (ATR is provided per candle).

TARGET RULES:
- Minimum target: 1.5x stop distance. Ideal: 2x–3x stop distance.

POSITION MANAGEMENT:
- TIGHTEN_SL: move stop to breakeven when position profits by 1x ATR.
- EXIT: take profit at target, cut loss at stop, or exit all positions after 13:30."""


def build_batch_prompt(days_data: list[dict]) -> str:
    """
    Build the single mega-prompt containing all days and all candles.

    Args:
        days_data: List of day dicts, each with:
            {
              "date": "2026-04-10",
              "thesis": { "direction": "BULLISH", "confidence": 0.7, "reasoning": "..." },
              "candles": [
                {
                  "time": "09:15",
                  "open": 52100, "high": 52180, "low": 52080, "close": 52150,
                  "rsi": 54.2, "ema20": 52100, "vwap": 52120, "atr": 85,
                  "pcr": 1.1, "max_pain": 52000
                },
                ...
              ]
            }

    Returns:
        Prompt string ready to send to AI.
    """
    lines = []
    lines.append("BATCH BACKTEST EVALUATION")
    lines.append(f"Total days: {len(days_data)}")
    lines.append("")
    lines.append("For EACH candle on EACH day, provide a trading decision.")
    lines.append("Track position state within each day yourself.")
    lines.append("Each day starts with no open position.")
    lines.append("")

    for day in days_data:
        trade_date = day["date"]
        thesis = day.get("thesis", {})
        candles = day.get("candles", [])

        t_dir = thesis.get("direction", "NEUTRAL")
        t_conf = thesis.get("confidence", 0.5)
        t_reason = thesis.get("reasoning", "")[:120]

        lines.append(f"{'─'*60}")
        lines.append(f"DATE: {trade_date}")
        lines.append(f"THESIS: {t_dir} (confidence: {t_conf:.0%}) — {t_reason}")
        lines.append(f"CANDLES ({len(candles)} total):")
        lines.append("")

        # Header
        lines.append("  time  | open  | high  |  low  | close | rsi  |ema20 | vwap  | atr | pcr")
        lines.append("  " + "-"*80)

        for c in candles:
            t = c.get("time", "??:??")
            o = c.get("open", 0)
            h = c.get("high", 0)
            lo = c.get("low", 0)
            cl = c.get("close", 0)
            rsi = c.get("rsi", "N/A")
            ema20 = c.get("ema20", "N/A")
            vwap = c.get("vwap", "N/A")
            atr = c.get("atr", "N/A")
            pcr = c.get("pcr", "N/A")

            rsi_str = f"{rsi:.1f}" if isinstance(rsi, float) else str(rsi)
            ema_str = f"{ema20:.0f}" if isinstance(ema20, float) else str(ema20)
            vwap_str = f"{vwap:.0f}" if isinstance(vwap, float) else str(vwap)
            atr_str = f"{atr:.0f}" if isinstance(atr, float) else str(atr)
            pcr_str = f"{pcr:.2f}" if isinstance(pcr, float) else str(pcr)

            lines.append(
                f"  {t}  | {o:.0f} | {h:.0f} | {lo:.0f} | {cl:.0f} "
                f"| {rsi_str:>5} | {ema_str:>5} | {vwap_str:>5} | {atr_str:>3} | {pcr_str}"
            )

        lines.append("")

    lines.append("=" * 60)
    lines.append("REQUIRED OUTPUT FORMAT:")
    lines.append("")
    lines.append("Return ONLY this JSON structure (no prose, no markdown):")
    lines.append("""
{
  "YYYY-MM-DD": {
    "HH:MM": {
      "action": "HOLD",
      "entry_price": null,
      "stop_loss": null,
      "target": null,
      "thesis_update": "CONFIRMED",
      "confidence": 0.5,
      "reasoning": "brief reason max 100 chars"
    },
    "HH:MM": {
      "action": "ENTER_LONG",
      "entry_price": 52150,
      "stop_loss": 52060,
      "target": 52420,
      "thesis_update": "CONFIRMED",
      "confidence": 0.78,
      "reasoning": "price above VWAP, RSI 58, bullish thesis"
    }
  }
}

Valid actions: HOLD, ENTER_LONG, ENTER_SHORT, EXIT, TIGHTEN_SL, WAIT
For HOLD/WAIT/TIGHTEN_SL: entry_price, stop_loss, target = null
For EXIT: entry_price = null, stop_loss = null, target = null
""")

    return "\n".join(lines)


class BatchEvaluator:
    """
    Makes a single AI call for N days of candle data.
    Writes a decision cache to disk that evaluator.py reads instead of calling the AI.
    """

    def __init__(self, ai_client, cache_dir: str = "cache/batch_decisions"):
        self.ai = ai_client
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def cache_path(self, start_date: str, end_date: str) -> str:
        return os.path.join(self.cache_dir, f"decisions_{start_date}_to_{end_date}.json")

    def evaluate_days(self, days_data: list[dict]) -> dict:
        """
        Send all days to AI in one call. Returns and saves the decision cache.

        Args:
            days_data: List of day dicts (see build_batch_prompt for format).

        Returns:
            cache dict: { "YYYY-MM-DD": { "HH:MM": {decision}, ... }, ... }
        """
        if not days_data:
            return {}

        dates = [d["date"] for d in days_data]
        start_date = dates[0]
        end_date = dates[-1]
        path = self.cache_path(start_date, end_date)

        # Return existing cache if already computed
        if os.path.exists(path):
            print(f"[BatchEval] Cache hit: {path}")
            with open(path) as f:
                return json.load(f)

        print(f"[BatchEval] Sending {len(days_data)} days ({sum(len(d['candles']) for d in days_data)} candles) to AI in one call...")

        prompt = build_batch_prompt(days_data)

        try:
            response = self.ai.ask(
                prompt=prompt,
                system=BATCH_SYSTEM_PROMPT,
                response_format="json",
            )
            content = response.get("content", {})
            if isinstance(content, str):
                import json as _json
                content = _json.loads(content)
        except Exception as e:
            print(f"[BatchEval] AI call failed: {e}")
            return {}

        # Validate and normalise the response
        cache = _normalize_cache(content, dates)

        # Save to disk
        with open(path, "w") as f:
            json.dump(cache, f, indent=2)

        total_decisions = sum(len(v) for v in cache.values())
        actions = {}
        for day_decisions in cache.values():
            for dec in day_decisions.values():
                a = dec.get("action", "HOLD")
                actions[a] = actions.get(a, 0) + 1

        print(f"[BatchEval] Cache saved: {path}")
        print(f"[BatchEval] {total_decisions} decisions | {actions}")

        return cache


def _normalize_cache(raw: dict, expected_dates: list[str]) -> dict:
    """
    Validate AI response and fill missing dates/times with safe HOLD defaults.
    Also converts any date keys that might be formatted differently.
    """
    result = {}

    for date_str in expected_dates:
        # Try to find this date in the raw response (AI might format slightly differently)
        day_data = raw.get(date_str, {})

        if not isinstance(day_data, dict):
            day_data = {}

        normalized_day = {}
        for time_str, decision in day_data.items():
            if not isinstance(decision, dict):
                continue

            action = decision.get("action", "HOLD")
            valid_actions = {"HOLD", "ENTER_LONG", "ENTER_SHORT", "EXIT", "TIGHTEN_SL", "WAIT"}
            if action not in valid_actions:
                action = "HOLD"

            normalized_day[time_str] = {
                "action": action,
                "entry_price": _safe_float(decision.get("entry_price")),
                "stop_loss": _safe_float(decision.get("stop_loss")),
                "target": _safe_float(decision.get("target")),
                "thesis_update": decision.get("thesis_update", "NEUTRAL"),
                "confidence": float(decision.get("confidence", 0.5)),
                "reasoning": str(decision.get("reasoning", ""))[:150],
            }

        result[date_str] = normalized_day

    return result


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
