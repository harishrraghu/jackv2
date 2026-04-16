"""
Strategy effectiveness ranker.

Runs nightly. Reads journal data and/or backtests each strategy
against recent data. Produces lab/rankings.json with relative rankings.

Ranking formula: score = win_rate * sqrt(total_trades)
Balances accuracy with sample size — prevents ranking a strategy
#1 after a single lucky trade.
"""
import json
import math
import os
from datetime import date

import yaml


def run_ranking(config: dict, candle_data=None, daily_data=None) -> dict:
    """
    Rank all registered strategies by recent effectiveness.

    Args:
        config: Full settings.yaml config dict.
        candle_data: Optional pre-loaded intraday DataFrame (fetched if None).
        daily_data: Optional pre-loaded daily DataFrame (fetched if None).

    Returns:
        Full rankings dict (also written to lab/rankings.json).
    """
    lab_config = config.get("lab", {})
    lookback_days = lab_config.get("backtest_lookback_days", 20)
    min_trades = lab_config.get("min_trades_to_evaluate", 5)

    # Load registered strategies from registry.yaml
    strategy_names = _load_strategy_names()

    # Fetch data if not provided
    if candle_data is None or daily_data is None:
        candle_data, daily_data = _fetch_historical_data(config)

    rankings = []

    for strategy_name in strategy_names:
        print(f"[Ranker] Backtesting {strategy_name}...")
        try:
            from lab.backtester import backtest_strategy
            result = backtest_strategy(
                strategy_name=strategy_name,
                candle_data=candle_data,
                daily_data=daily_data,
                config=config,
            )

            total_trades = result.get("total_trades", 0)
            win_rate = result.get("win_rate", 0)

            if total_trades < min_trades:
                score = 0.0
                note = f"insufficient_data ({total_trades} trades)"
            else:
                # Ranking formula: win_rate * sqrt(total_trades)
                score = win_rate * math.sqrt(total_trades)
                note = "ok"

            rankings.append({
                "strategy": strategy_name,
                "score": round(score, 3),
                "rank": 0,  # Filled after sorting
                "win_rate": win_rate,
                "total_trades": total_trades,
                "avg_pnl": result.get("avg_pnl", 0),
                "total_pnl": result.get("total_pnl", 0),
                "sharpe": result.get("sharpe", 0),
                "max_drawdown_pct": result.get("max_drawdown_pct", 0),
                "note": note,
                "best_regime": _infer_best_regime(strategy_name),
                "worst_regime": _infer_worst_regime(strategy_name),
            })

        except Exception as e:
            print(f"[Ranker] Failed to rank {strategy_name}: {e}")
            rankings.append({
                "strategy": strategy_name,
                "score": 0.0,
                "rank": 0,
                "win_rate": 0,
                "total_trades": 0,
                "avg_pnl": 0,
                "note": f"error: {e}",
            })

    # Sort by score descending, assign ranks
    rankings.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    output = {
        "last_updated": str(date.today()),
        "lookback_days": lookback_days,
        "rankings": rankings,
    }

    # Write rankings file
    os.makedirs("lab", exist_ok=True)
    with open("lab/rankings.json", "w") as f:
        json.dump(output, f, indent=2)

    # Update registry.yaml effectiveness section
    _update_registry_effectiveness(rankings)

    print(f"[Ranker] Rankings saved. Top strategy: {rankings[0]['strategy'] if rankings else 'none'}")
    return output


def load_rankings() -> dict:
    """Load rankings from lab/rankings.json. Returns empty dict if not found."""
    if os.path.exists("lab/rankings.json"):
        try:
            with open("lab/rankings.json") as f:
                return json.load(f)
        except Exception:
            pass
    return {"rankings": [], "last_updated": None}


# ─────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────

def _load_strategy_names() -> list:
    """Load strategy names from strategies/registry.yaml."""
    registry_path = "strategies/registry.yaml"
    if os.path.exists(registry_path):
        try:
            with open(registry_path) as f:
                data = yaml.safe_load(f)
                return list(data.get("strategies", {}).keys())
        except Exception:
            pass
    # Fallback
    return [
        "first_hour_verdict", "gap_fill", "gap_up_fade", "streak_fade",
        "bb_squeeze", "vwap_reversion", "afternoon_breakout",
    ]


def _fetch_historical_data(config: dict):
    """Fetch historical intraday and daily data from Dhan."""
    try:
        from data.dhan_client import create_dhan_client
        client = create_dhan_client(config)
        security_id = config.get("dhan", {}).get("banknifty_index_id", "25")
        lookback = config.get("lab", {}).get("backtest_lookback_days", 20)

        print(f"[Ranker] Fetching {lookback} days of intraday data...")
        candle_data = client.get_historical_intraday(
            security_id=security_id, interval=5, days_back=lookback + 5
        )

        print("[Ranker] Fetching daily data...")
        daily_data = client.get_historical_daily(
            security_id=security_id, days=lookback + 30
        )

        return candle_data, daily_data

    except Exception as e:
        print(f"[Ranker] Data fetch failed: {e}. Using empty DataFrames.")
        import pandas as pd
        empty = pd.DataFrame()
        return empty, empty


def _infer_best_regime(strategy_name: str) -> str:
    """Look up best regime from registry.yaml."""
    registry_path = "strategies/registry.yaml"
    try:
        with open(registry_path) as f:
            data = yaml.safe_load(f)
        return data.get("strategies", {}).get(strategy_name, {}).get("effectiveness", {}).get("best_regime", "normal")
    except Exception:
        return "normal"


def _infer_worst_regime(strategy_name: str) -> str:
    """Infer worst regime (opposite of best)."""
    best = _infer_best_regime(strategy_name)
    opposites = {
        "trending_strong": "squeeze",
        "trending_weak": "ranging",
        "ranging": "trending_strong",
        "squeeze": "trending_strong",
        "normal": "squeeze",
    }
    return opposites.get(best, "squeeze")


def _update_registry_effectiveness(rankings: list) -> None:
    """Update the effectiveness section in strategies/registry.yaml."""
    registry_path = "strategies/registry.yaml"
    if not os.path.exists(registry_path):
        return
    try:
        with open(registry_path) as f:
            data = yaml.safe_load(f)

        for ranking in rankings:
            name = ranking["strategy"]
            if name in data.get("strategies", {}):
                data["strategies"][name].setdefault("effectiveness", {})
                data["strategies"][name]["effectiveness"].update({
                    "win_rate_20d": ranking.get("win_rate"),
                    "avg_rr": None,
                    "total_trades_20d": ranking.get("total_trades"),
                    "last_updated": str(date.today()),
                })

        with open(registry_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        print(f"[Ranker] Failed to update registry.yaml: {e}")
