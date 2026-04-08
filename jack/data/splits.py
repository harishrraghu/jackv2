"""Train/test/holdout split management with leakage prevention."""

from __future__ import annotations

import pandas as pd
import yaml
from tabulate import tabulate

# Quarantine rules: each split may only see data up to its own end date,
# and only from 2015-01-01 onward.
_QUARANTINE: dict[str, tuple[str, str]] = {
    "train":   ("2015-01-01", "2020-12-31"),
    "test":    ("2015-01-01", "2022-12-31"),
    "holdout": ("2015-01-01", "2024-04-12"),
}


class DataLeakageError(Exception):
    """Raised when a date violates a split's quarantine boundary."""


class DataSplits:
    """Reads split configuration and exposes range helpers."""

    def __init__(self, config_path: str = "config/settings.yaml") -> None:
        with open(config_path, "r") as fh:
            cfg = yaml.safe_load(fh)
        splits = cfg["splits"]
        self._train = (str(splits["train"]["start"]), str(splits["train"]["end"]))
        self._test = (str(splits["test"]["start"]), str(splits["test"]["end"]))
        self._holdout = (str(splits["holdout"]["start"]), str(splits["holdout"]["end"]))

    def get_train_range(self) -> tuple[str, str]:
        return self._train

    def get_test_range(self) -> tuple[str, str]:
        return self._test

    def get_holdout_range(self) -> tuple[str, str]:
        return self._holdout


def validate_no_leakage(split: str, data_dates: list[pd.Timestamp]) -> bool:
    """Check that all dates in data_dates fall within the allowed range for split.

    Raises DataLeakageError on the first violation; returns True if all pass.
    """
    if split not in _QUARANTINE:
        raise ValueError(f"Unknown split '{split}'. Choose from {list(_QUARANTINE)}")

    allowed_start, allowed_end_str = _QUARANTINE[split]
    allowed_start_ts = pd.Timestamp(allowed_start)
    allowed_end_ts = pd.Timestamp(allowed_end_str)

    for ts in data_dates:
        if ts < allowed_start_ts or ts > allowed_end_ts:
            raise DataLeakageError(
                f"Date {ts.date()} violates {split} split boundary ({allowed_start} to {allowed_end_str})"
            )

    return True


# Display ranges use each split's actual start (not the cumulative quarantine start).
_DISPLAY_RANGES: dict[str, tuple[str, str]] = {
    "train":   ("2015-01-01", "2020-12-31"),
    "test":    ("2021-01-01", "2022-12-31"),
    "holdout": ("2023-01-01", "2024-04-12"),
}


def print_split_summary(data: dict[str, pd.DataFrame]) -> None:
    """Print a summary table of each split across all loaded timeframes."""
    rows = []
    for split, (start_str, end_str) in _DISPLAY_RANGES.items():
        start = pd.Timestamp(start_str)
        end = pd.Timestamp(end_str)
        row: list = [split, start_str, end_str]

        trading_days = 0
        if "1d" in data:
            mask = (data["1d"]["Date"] >= start) & (data["1d"]["Date"] <= end)
            trading_days = mask.sum()
        row.append(trading_days)

        for tf in ["2h", "1h", "15m", "5m", "1m"]:
            if tf in data:
                mask = (data[tf]["Date"] >= start) & (data[tf]["Date"] <= end)
                row.append(mask.sum())
            else:
                row.append("N/A")

        rows.append(row)

        if trading_days < 200:
            print(f"WARNING: '{split}' split has only {trading_days} trading days (< 200).")

    headers = ["Split", "Start", "End", "1d days", "2h", "1h", "15m", "5m", "1m"]
    print(tabulate(rows, headers=headers, tablefmt="github"))
