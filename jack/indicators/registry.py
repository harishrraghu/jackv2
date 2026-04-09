"""
Indicator registry — auto-discovers and manages indicator modules.

Scans the indicators/ directory for .py files conforming to the indicator
contract (METADATA dict + compute function). Provides convenience methods
for computing indicators individually or in batch.
"""

import importlib
import importlib.util
import os
import sys
from typing import Optional

import pandas as pd

from indicators.base import validate_indicator_module

# Files to skip during auto-discovery
_SKIP_FILES = {"__init__.py", "registry.py", "base.py"}


class IndicatorRegistry:
    """
    Auto-discovers and manages trading indicators.

    Usage:
        reg = IndicatorRegistry("indicators/")
        df = reg.compute("ema", df, period=21)
        df = reg.compute_all(df, ["ema", "rsi", "atr"])
    """

    def __init__(self, indicators_dir: str = "indicators/"):
        self._indicators: dict = {}
        self._modules: dict = {}
        self._indicators_dir = indicators_dir
        self._scan(indicators_dir)

    def _scan(self, directory: str) -> None:
        """Scan directory for indicator modules and register valid ones."""
        if not os.path.isdir(directory):
            print(f"[registry] Warning: indicators directory not found: {directory}")
            return

        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".py") or filename in _SKIP_FILES:
                continue

            filepath = os.path.join(directory, filename)
            module_name = filename[:-3]  # Remove .py

            try:
                spec = importlib.util.spec_from_file_location(
                    f"indicators.{module_name}", filepath
                )
                if spec is None or spec.loader is None:
                    print(f"[registry] Warning: Cannot load {filename}, skipping")
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                valid, reason = validate_indicator_module(module)
                if not valid:
                    print(f"[registry] Warning: {filename} skipped — {reason}")
                    continue

                name = module.METADATA["name"]
                self._indicators[name] = module.METADATA
                self._modules[name] = module

            except Exception as e:
                print(f"[registry] Warning: Failed to load {filename}: {e}")

    def list_indicators(self) -> list[dict]:
        """Return metadata for all registered indicators."""
        return list(self._indicators.values())

    def get(self, name: str):
        """
        Return the module for a registered indicator.

        Args:
            name: Indicator name (e.g., "ema").

        Returns:
            The indicator module.

        Raises:
            KeyError: If indicator not found.
        """
        if name not in self._modules:
            available = ", ".join(sorted(self._modules.keys()))
            raise KeyError(
                f"Indicator '{name}' not found. Available: {available}"
            )
        return self._modules[name]

    def compute(self, name: str, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Compute a single indicator on a DataFrame.

        Args:
            name: Indicator name.
            df: Input DataFrame with OHLC data.
            **params: Override default parameters.

        Returns:
            DataFrame with indicator columns appended.
        """
        module = self.get(name)
        return module.compute(df, **params)

    def compute_all(
        self,
        df: pd.DataFrame,
        indicator_list: list[str],
        params_override: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Apply multiple indicators sequentially.

        Args:
            df: Input DataFrame.
            indicator_list: List of indicator names to compute.
            params_override: Dict like {"ema": {"period": 21}} to override defaults.

        Returns:
            DataFrame with all indicator columns appended.
        """
        if params_override is None:
            params_override = {}

        result = df.copy()
        for name in indicator_list:
            override = params_override.get(name, {})
            result = self.compute(name, result, **override)

        return result

    def search(self, query: str) -> list[dict]:
        """
        Fuzzy search indicators by name or display_name.

        Args:
            query: Search string (case-insensitive).

        Returns:
            List of matching indicator metadata dicts.
        """
        query_lower = query.lower()
        matches = []
        for meta in self._indicators.values():
            if (query_lower in meta["name"].lower() or
                    query_lower in meta["display_name"].lower()):
                matches.append(meta)
        return matches

    def has(self, name: str) -> bool:
        """Check if an indicator is registered."""
        return name in self._modules

    def get_metadata(self, name: str) -> dict:
        """Return metadata for a specific indicator."""
        if name not in self._indicators:
            raise KeyError(f"Indicator '{name}' not found.")
        return self._indicators[name]
