"""
Knowledge Base Reader — Python API to read KB YAML and SQLite.

Used by all agents to read KB state. The KB is the shared brain
that all agents read from and (some) write to.

Usage:
    from kb.reader import KBReader
    kb = KBReader("BANKNIFTY")
    strategies = kb.get_active_strategies()
    gap_patterns = kb.get_behavior("gap_patterns")
    risk_rules = kb.get_risk_rules()
"""

import os
import sqlite3
import yaml
import logging
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

KB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)))


class KBReader:
    """Read-only interface to the Knowledge Base."""

    def __init__(self, market: str = "BANKNIFTY"):
        """
        Args:
            market: Market identifier (directory name under kb/).
        """
        self.market = market
        self.market_dir = os.path.join(KB_ROOT, market)
        self.global_dir = os.path.join(KB_ROOT, "_global")
        self._cache = {}  # YAML cache to avoid re-reading

    def _load_yaml(self, path: str, use_cache: bool = True) -> dict:
        """Load a YAML file, with optional caching."""
        if use_cache and path in self._cache:
            return self._cache[path]

        if not os.path.exists(path):
            logger.warning(f"KB file not found: {path}")
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if use_cache:
                self._cache[path] = data
            return data
        except Exception as e:
            logger.error(f"Failed to load KB file {path}: {e}")
            return {}

    def clear_cache(self):
        """Clear the YAML cache to force re-reads."""
        self._cache.clear()

    # =========================================================================
    # Identity
    # =========================================================================

    def get_identity(self) -> dict:
        """Get market identity."""
        path = os.path.join(self.market_dir, "identity.yaml")
        return self._load_yaml(path)

    # =========================================================================
    # Behavior
    # =========================================================================

    def get_behavior(self, pattern_name: str) -> dict:
        """
        Get a behavior pattern from the KB.

        Args:
            pattern_name: One of: gap_patterns, expiry_patterns, day_of_week,
                         regime_behavior, time_of_day, seasonal
        """
        path = os.path.join(self.market_dir, "behavior", f"{pattern_name}.yaml")
        return self._load_yaml(path)

    def get_all_behaviors(self) -> dict:
        """Load all behavior YAML files."""
        behavior_dir = os.path.join(self.market_dir, "behavior")
        result = {}
        if os.path.isdir(behavior_dir):
            for f in os.listdir(behavior_dir):
                if f.endswith(".yaml"):
                    name = f.replace(".yaml", "")
                    result[name] = self._load_yaml(os.path.join(behavior_dir, f))
        return result

    # =========================================================================
    # Strategies
    # =========================================================================

    def get_active_strategies(self) -> dict:
        """Get all active strategies."""
        path = os.path.join(self.market_dir, "strategies", "active.yaml")
        data = self._load_yaml(path)
        return data.get("strategies", {})

    def get_strategy(self, name: str) -> Optional[dict]:
        """Get a specific active strategy."""
        strategies = self.get_active_strategies()
        return strategies.get(name)

    def get_candidate_strategies(self) -> dict:
        """Get strategies being tested."""
        path = os.path.join(self.market_dir, "strategies", "candidates.yaml")
        data = self._load_yaml(path)
        return data.get("candidates", {})

    def get_disabled_strategies(self) -> dict:
        """Get disabled strategies."""
        path = os.path.join(self.market_dir, "strategies", "disabled.yaml")
        data = self._load_yaml(path)
        return data.get("disabled", {})

    # =========================================================================
    # Indicators
    # =========================================================================

    def get_indicator_kb(self, name: str) -> dict:
        """Get indicator knowledge (best_by_regime, custom_thresholds)."""
        path = os.path.join(self.market_dir, "indicators", f"{name}.yaml")
        return self._load_yaml(path)

    # =========================================================================
    # Risk
    # =========================================================================

    def get_risk_rules(self) -> dict:
        """Get risk rules."""
        path = os.path.join(self.market_dir, "risk", "rules.yaml")
        return self._load_yaml(path)

    def get_risk_events(self) -> dict:
        """Get event-based risk rules."""
        path = os.path.join(self.market_dir, "risk", "events.yaml")
        return self._load_yaml(path)

    def get_circuit_breakers(self) -> dict:
        """Get circuit breaker rules."""
        path = os.path.join(self.market_dir, "risk", "circuit_breakers.yaml")
        return self._load_yaml(path)

    # =========================================================================
    # Sources
    # =========================================================================

    def get_sources(self, status: str = "all") -> list:
        """
        Get source entries.

        Args:
            status: "validated", "pending", "rejected", or "all"
        """
        if status == "all":
            result = []
            for s in ["validated", "pending", "rejected"]:
                result.extend(self.get_sources(s))
            return result

        path = os.path.join(self.market_dir, "sources", f"{status}.yaml")
        data = self._load_yaml(path, use_cache=False)
        return data.get(status, []) or []

    # =========================================================================
    # Global
    # =========================================================================

    def get_global(self, name: str) -> dict:
        """Get global KB entry (market_relationships, risk_rules, etc.)."""
        path = os.path.join(self.global_dir, f"{name}.yaml")
        return self._load_yaml(path)

    # =========================================================================
    # Schema
    # =========================================================================

    def get_schema(self) -> dict:
        """Get KB schema and rules."""
        path = os.path.join(KB_ROOT, "_schema.yaml")
        return self._load_yaml(path)

    # =========================================================================
    # SQLite Performance Database
    # =========================================================================

    def get_db_connection(self) -> sqlite3.Connection:
        """Get a connection to the performance SQLite database."""
        db_path = os.path.join(self.market_dir, "_performance.db")
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Performance DB not found: {db_path}")
        return sqlite3.connect(db_path)

    def query_db(self, sql: str, params: tuple = ()) -> list[dict]:
        """
        Run a SQL query on the performance database.

        Returns:
            List of dicts (rows).
        """
        try:
            conn = self.get_db_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except FileNotFoundError:
            logger.warning("Performance DB not found")
            return []
        except Exception as e:
            logger.error(f"DB query failed: {e}")
            return []

    # =========================================================================
    # Context Builder — builds full context for Trader agent
    # =========================================================================

    def build_trading_context(self, date: str = None, 
                              day_of_week: str = None,
                              is_expiry: bool = False) -> dict:
        """
        Build a comprehensive trading context from the KB.

        This is what the Trader agent reads at startup to understand
        what it knows about today's trading conditions.

        Args:
            date: Today's date string.
            day_of_week: Day name (Monday, Tuesday, etc.)
            is_expiry: Whether today is expiry day.

        Returns:
            Dict with all relevant KB knowledge for trading today.
        """
        context = {
            "market": self.market,
            "date": date,
            "identity": self.get_identity(),
            "active_strategies": self.get_active_strategies(),
            "risk_rules": self.get_risk_rules(),
            "circuit_breakers": self.get_circuit_breakers(),
        }

        # Day-specific behavior
        if day_of_week:
            dow_patterns = self.get_behavior("day_of_week")
            context["day_behavior"] = dow_patterns.get("day_of_week", {}).get(day_of_week, {})

        # Time-of-day patterns
        context["time_patterns"] = self.get_behavior("time_of_day")

        # Gap patterns (always useful)
        context["gap_patterns"] = self.get_behavior("gap_patterns")

        # Regime behavior
        context["regime_behavior"] = self.get_behavior("regime_behavior")

        # Expiry-specific
        if is_expiry:
            context["expiry_patterns"] = self.get_behavior("expiry_patterns")

        # Seasonal
        context["seasonal"] = self.get_behavior("seasonal")

        # Event risks
        context["event_risks"] = self.get_risk_events()

        # Indicator thresholds
        context["indicator_thresholds"] = self.get_indicator_kb("custom_thresholds")

        return context


if __name__ == "__main__":
    """Quick test of KB reader."""
    kb = KBReader("BANKNIFTY")
    
    print("=== Market Identity ===")
    identity = kb.get_identity()
    print(f"  Name: {identity.get('identity', {}).get('name')}")
    print(f"  Lot Size: {identity.get('identity', {}).get('lot_size')}")
    
    print("\n=== Active Strategies ===")
    strategies = kb.get_active_strategies()
    for name, s in strategies.items():
        print(f"  {name}: WR={s.get('win_rate')}, Status={s.get('status')}")
    
    print("\n=== Risk Rules ===")
    rules = kb.get_risk_rules()
    ps = rules.get("position_sizing", {})
    print(f"  Max risk/trade: {ps.get('base_risk_per_trade_pct')}%")
    print(f"  Max daily DD: {ps.get('max_daily_drawdown_pct')}%")
    
    print("\n=== Gap Patterns ===")
    gaps = kb.get_behavior("gap_patterns")
    gf = gaps.get("gap_fill", {})
    small = gf.get("small_gap_up", {})
    print(f"  Small gap up fill prob: {small.get('fill_probability')}")
    
    print("\n=== Trading Context (Wednesday, Expiry) ===")
    ctx = kb.build_trading_context(
        date="2026-04-16",
        day_of_week="Wednesday",
        is_expiry=True
    )
    print(f"  Strategies available: {list(ctx['active_strategies'].keys())}")
    if ctx.get('expiry_patterns'):
        print(f"  Expiry note: Reduce size to {ctx['expiry_patterns'].get('expiry_day', {}).get('general', {}).get('size_multiplier', '?')}x")
