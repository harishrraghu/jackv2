import pytest
import datetime
import numpy as np
import math
from analysis.performance import PerformanceAnalyzer

def test_sharpe_calculations():
    # Create a mock trade log spanning 3 months with 1 trade per month
    # Start: Jan 2020. Capital: 100,000
    
    trade_log = [
        {
            "entry_date": "2020-01-15",
            "exit_date": "2020-01-15",
            "net_pnl": 5000  # End of Jan Cap = 105,000 -> Return = +5%
        },
        {
            "entry_date": "2020-02-15",
            "exit_date": "2020-02-15",
            "net_pnl": -2100  # End of Feb Cap = 102,900 -> Return = -2%
        },
        {
            "entry_date": "2020-03-15",
            "exit_date": "2020-03-15",
            "net_pnl": 3087  # End of Mar Cap = 105,987 -> Return = +3%
        }
    ]
    
    analyzer = PerformanceAnalyzer(trade_log, initial_capital=100000)
    results = analyzer.compute_all()
    
    # Hand calculation:
    returns = [0.05, -0.02, 0.03]
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    risk_free = 0.065 / 12
    # sharpe_monthly matches hand calculation
    expected_sharpe = (mean_ret - risk_free) / std_ret * math.sqrt(12)
    
    assert math.isclose(results["sharpe_monthly"], expected_sharpe, rel_tol=1e-3)
    
    # Verify sharpe_monthly < sharpe_all_days for sparse trading
    # Wait, sharpe_all_days is renamed to sharpe_inflated_DO_NOT_USE
    # In our sparse log, we only have 3 days of trading over 3 months.
    # The true daily returns over those 3 days won't give 0 return days though,
    # because _compute_daily_returns in PerformanceAnalyzer only tracks days WITH trades!
    # Ah! But let's check what the performance analyzer actually computed.
    assert "sharpe_inflated_DO_NOT_USE" in results
    # Since inflated uses daily returns without zeros and annualizes with sqrt(252),
    # its standard value will be wildly different usually. 
    # For a sparse curve, std_ret_daily handles 0s if they are included.
    # Since PerformanceAnalyzer._compute_daily_returns only computes days with trades,
    # we expect sharpe_monthly to be less inflated than what standard daily-inflated gives
    # if daily-inflated were computed over all days. But since we track "sharpe_inflated_DO_NOT_USE"
    # as the PREVIOUS implementation, let's verify it matches the logic requirements.
    
    assert results["sharpe_monthly"] < results["sharpe_inflated_DO_NOT_USE"]

def test_sparse_trading_sharpe_comparison():
    # Simulate high density vs sparse
    trade_log = [
        {"exit_date": "2020-01-05", "net_pnl": 1000},
        {"exit_date": "2020-03-10", "net_pnl": 1500},
        {"exit_date": "2020-06-15", "net_pnl": 1000},
        {"exit_date": "2020-12-20", "net_pnl": 2000},
    ]
    analyzer = PerformanceAnalyzer(trade_log, initial_capital=100000)
    results = analyzer.compute_all()
    
    assert results["sharpe_monthly"] < results["sharpe_inflated_DO_NOT_USE"]
