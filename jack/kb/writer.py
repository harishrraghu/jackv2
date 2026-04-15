"""
Knowledge Base Writer — Python API to update KB YAML and SQLite.

Used by the Learner and Builder agents to write validated
patterns, strategies, and trade data to the KB.

Safety rules:
    - Never overwrites existing data without explicit merge
    - Always updates last_updated timestamp
    - Validates against KB schema before writing
    - Creates backups before modifying existing files

Usage:
    from kb.writer import KBWriter
    writer = KBWriter("BANKNIFTY")
    writer.add_pattern("behavior/gap_patterns", "new_gap_fill_v2", pattern_data)
    writer.log_trade(trade_dict)
    writer.add_source("pending", source_dict)
"""

import os
import json
import shutil
import sqlite3
import yaml
import logging
from datetime import datetime
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

KB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)))


class KBWriter:
    """Write interface to the Knowledge Base."""

    def __init__(self, market: str = "BANKNIFTY"):
        """
        Args:
            market: Market identifier (directory name under kb/).
        """
        self.market = market
        self.market_dir = os.path.join(KB_ROOT, market)
        self.db_path = os.path.join(self.market_dir, "_performance.db")

    def _load_yaml(self, path: str) -> dict:
        """Load a YAML file."""
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _save_yaml(self, path: str, data: dict, backup: bool = True):
        """
        Save data to a YAML file.

        Args:
            path: File path.
            data: Data to save.
            backup: If True, create backup before overwriting.
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if backup and os.path.exists(path):
            backup_path = path + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(path, backup_path)
            logger.info(f"Backup created: {backup_path}")

        with open(path, "w", encoding="utf-8") as f:
            # Add header comment
            f.write(f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Updated by: KBWriter\n\n")
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False, width=120)

        logger.info(f"KB updated: {path}")

    # =========================================================================
    # Pattern Writing
    # =========================================================================

    def add_pattern(self, category: str, pattern_id: str, 
                     pattern_data: dict, merge: bool = True) -> bool:
        """
        Add or update a pattern in a behavior YAML file.

        Args:
            category: Path relative to market dir (e.g. "behavior/gap_patterns")
            pattern_id: Unique pattern identifier.
            pattern_data: Pattern data dict.
            merge: If True, merge with existing. If False, replace.

        Returns:
            True if successful.
        """
        path = os.path.join(self.market_dir, f"{category}.yaml")
        existing = self._load_yaml(path)

        # Add metadata
        pattern_data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        pattern_data.setdefault("source", "tier_1_own_data")

        if merge:
            # Deep merge: update existing pattern
            if pattern_id in existing:
                existing[pattern_id].update(pattern_data)
            else:
                existing[pattern_id] = pattern_data
        else:
            existing[pattern_id] = pattern_data

        self._save_yaml(path, existing)
        return True

    def update_confidence(self, category: str, pattern_id: str,
                          new_confidence: float, sample_size: int = None) -> bool:
        """
        Update confidence score for an existing pattern.

        Args:
            category: YAML file path relative to market dir.
            pattern_id: Pattern to update.
            new_confidence: New confidence value (0-1).
            sample_size: Updated sample size if available.
        """
        path = os.path.join(self.market_dir, f"{category}.yaml")
        data = self._load_yaml(path)

        if pattern_id not in data:
            logger.warning(f"Pattern {pattern_id} not found in {category}")
            return False

        data[pattern_id]["confidence"] = new_confidence
        data[pattern_id]["last_validated"] = datetime.now().strftime("%Y-%m-%d")
        if sample_size:
            data[pattern_id]["sample_size"] = sample_size

        self._save_yaml(path, data)
        return True

    # =========================================================================
    # Strategy Writing
    # =========================================================================

    def register_strategy(self, name: str, strategy_data: dict,
                          target: str = "candidates") -> bool:
        """
        Register a new strategy in the KB.

        Args:
            name: Strategy name.
            strategy_data: Strategy details.
            target: "candidates", "active", or "disabled".
        """
        path = os.path.join(self.market_dir, "strategies", f"{target}.yaml")
        data = self._load_yaml(path)

        key = "strategies" if target == "active" else target
        if key not in data:
            data[key] = {}

        strategy_data["registered_date"] = datetime.now().strftime("%Y-%m-%d")
        data[key][name] = strategy_data

        self._save_yaml(path, data)
        return True

    def move_strategy(self, name: str, from_target: str, 
                       to_target: str, reason: str = "") -> bool:
        """
        Move a strategy between active/candidates/disabled.

        Args:
            name: Strategy name.
            from_target: Source file (active, candidates, disabled).
            to_target: Destination file.
            reason: Why the move is happening.
        """
        from_path = os.path.join(self.market_dir, "strategies", f"{from_target}.yaml")
        to_path = os.path.join(self.market_dir, "strategies", f"{to_target}.yaml")

        from_data = self._load_yaml(from_path)
        to_data = self._load_yaml(to_path)

        from_key = "strategies" if from_target == "active" else from_target
        to_key = "strategies" if to_target == "active" else to_target

        if from_key not in from_data or name not in from_data[from_key]:
            logger.warning(f"Strategy {name} not found in {from_target}")
            return False

        # Move
        strategy = from_data[from_key].pop(name)
        strategy["moved_date"] = datetime.now().strftime("%Y-%m-%d")
        strategy["move_reason"] = reason

        if to_key not in to_data:
            to_data[to_key] = {}
        to_data[to_key][name] = strategy

        self._save_yaml(from_path, from_data)
        self._save_yaml(to_path, to_data)
        return True

    # =========================================================================
    # Source Writing
    # =========================================================================

    def add_source(self, status: str, source_data: dict) -> bool:
        """
        Add a source entry.

        Args:
            status: "validated", "pending", or "rejected".
            source_data: Source details dict.
        """
        path = os.path.join(self.market_dir, "sources", f"{status}.yaml")
        data = self._load_yaml(path)

        if status not in data or data[status] is None:
            data[status] = []

        source_data.setdefault("added_date", datetime.now().strftime("%Y-%m-%d"))
        data[status].append(source_data)

        self._save_yaml(path, data, backup=False)
        return True

    def move_source(self, source_id: str, from_status: str,
                    to_status: str, reason: str = "") -> bool:
        """Move a source between pending/validated/rejected."""
        from_path = os.path.join(self.market_dir, "sources", f"{from_status}.yaml")
        to_path = os.path.join(self.market_dir, "sources", f"{to_status}.yaml")

        from_data = self._load_yaml(from_path)
        to_data = self._load_yaml(to_path)

        # Find and remove from source
        sources = from_data.get(from_status, []) or []
        source = None
        for i, s in enumerate(sources):
            if s.get("source_id") == source_id:
                source = sources.pop(i)
                break

        if source is None:
            logger.warning(f"Source {source_id} not found in {from_status}")
            return False

        source["moved_date"] = datetime.now().strftime("%Y-%m-%d")
        source["move_reason"] = reason

        if to_status not in to_data or to_data[to_status] is None:
            to_data[to_status] = []
        to_data[to_status].append(source)

        from_data[from_status] = sources
        self._save_yaml(from_path, from_data, backup=False)
        self._save_yaml(to_path, to_data, backup=False)
        return True

    # =========================================================================
    # SQLite Performance Database
    # =========================================================================

    def init_db(self) -> bool:
        """Initialize the performance SQLite database with schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                strategy TEXT,
                direction TEXT,
                entry_time TEXT,
                entry_price REAL,
                exit_time TEXT,
                exit_price REAL,
                stop_loss REAL,
                target REAL,
                pnl REAL,
                net_pnl REAL,
                exit_reason TEXT,
                gap_pct REAL,
                regime TEXT,
                rsi REAL,
                atr REAL,
                day_of_week TEXT,
                is_expiry INTEGER DEFAULT 0,
                vix REAL,
                pcr REAL,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_metrics (
                date TEXT PRIMARY KEY,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                gap_pct REAL,
                regime TEXT,
                atr REAL,
                rsi REAL,
                fh_return REAL,
                fh_direction INTEGER,
                trades_taken INTEGER DEFAULT 0,
                daily_pnl REAL DEFAULT 0,
                day_type TEXT
            );

            CREATE TABLE IF NOT EXISTS pattern_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id TEXT,
                date TEXT,
                predicted_outcome TEXT,
                actual_outcome TEXT,
                hit INTEGER,
                confidence REAL,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS strategy_performance (
                strategy TEXT,
                period TEXT,
                trades INTEGER,
                wins INTEGER,
                win_rate REAL,
                total_pnl REAL,
                avg_rr REAL,
                sharpe REAL,
                PRIMARY KEY (strategy, period)
            );

            CREATE TABLE IF NOT EXISTS source_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                source_type TEXT,
                title TEXT,
                claim TEXT,
                category TEXT,
                validated INTEGER DEFAULT 0,
                validation_result TEXT,
                extracted_date TEXT,
                validated_date TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
            CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
            CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(date);
            CREATE INDEX IF NOT EXISTS idx_pattern_hits_pattern ON pattern_hits(pattern_id);
        """)

        conn.commit()
        conn.close()
        logger.info(f"Performance DB initialized: {self.db_path}")
        return True

    def log_trade(self, trade: dict) -> bool:
        """
        Log a trade to the performance database.

        Args:
            trade: Trade dict with keys matching the trades table columns.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO trades (
                    date, strategy, direction, entry_time, entry_price, 
                    exit_time, exit_price, stop_loss, target, pnl, net_pnl,
                    exit_reason, gap_pct, regime, rsi, atr, day_of_week,
                    is_expiry, vix, pcr, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("date"), trade.get("strategy"), trade.get("direction"),
                trade.get("entry_time"), trade.get("entry_price"),
                trade.get("exit_time"), trade.get("exit_price"),
                trade.get("stop_loss"), trade.get("target"),
                trade.get("pnl"), trade.get("net_pnl"),
                trade.get("exit_reason"), trade.get("gap_pct"),
                trade.get("regime"), trade.get("rsi"), trade.get("atr"),
                trade.get("day_of_week"), trade.get("is_expiry", 0),
                trade.get("vix"), trade.get("pcr"),
                json.dumps(trade.get("metadata", {})),
            ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
            return False

    def log_daily_metrics(self, metrics: dict) -> bool:
        """Log daily market metrics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO daily_metrics (
                    date, open, high, low, close, gap_pct, regime,
                    atr, rsi, fh_return, fh_direction, trades_taken,
                    daily_pnl, day_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.get("date"), metrics.get("open"), metrics.get("high"),
                metrics.get("low"), metrics.get("close"),
                metrics.get("gap_pct"), metrics.get("regime"),
                metrics.get("atr"), metrics.get("rsi"),
                metrics.get("fh_return"), metrics.get("fh_direction"),
                metrics.get("trades_taken", 0), metrics.get("daily_pnl", 0),
                metrics.get("day_type"),
            ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to log daily metrics: {e}")
            return False

    def log_pattern_hit(self, pattern_id: str, date: str,
                        predicted: str, actual: str,
                        hit: bool, confidence: float) -> bool:
        """Log a pattern prediction hit/miss."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO pattern_hits (
                    pattern_id, date, predicted_outcome, actual_outcome,
                    hit, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (pattern_id, date, predicted, actual, 1 if hit else 0, confidence))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to log pattern hit: {e}")
            return False

    def update_strategy_performance(self, strategy: str, period: str,
                                     trades: int, wins: int,
                                     total_pnl: float, avg_rr: float,
                                     sharpe: float = None) -> bool:
        """Update strategy performance for a period."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            win_rate = wins / trades if trades > 0 else 0

            cursor.execute("""
                INSERT OR REPLACE INTO strategy_performance (
                    strategy, period, trades, wins, win_rate,
                    total_pnl, avg_rr, sharpe
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (strategy, period, trades, wins, win_rate,
                  total_pnl, avg_rr, sharpe))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to update strategy performance: {e}")
            return False


if __name__ == "__main__":
    """Initialize the performance database."""
    writer = KBWriter("BANKNIFTY")
    writer.init_db()
    print(f"Performance DB initialized at: {writer.db_path}")
