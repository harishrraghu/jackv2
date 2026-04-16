"""
Options strike selection utilities.

Works with real Dhan option chain data. Returns None when option chain
data is unavailable (e.g., no market feed subscription) — strategies
must handle this gracefully by not firing.
"""


class StrikeSelector:
    """
    Selects option strikes from a live Dhan option chain.

    All methods return None if option_chain is empty/unavailable,
    so strategies can skip entry rather than using fabricated data.
    """

    def __init__(self, option_chain: dict):
        """
        Args:
            option_chain: Dict returned by DhanBroker.get_option_chain().
                          Empty dict if data is unavailable.
        """
        self.chain = option_chain
        self.available = bool(option_chain and option_chain.get("strikes"))

    @property
    def atm_strike(self) -> float | None:
        """ATM strike from real option chain. None if unavailable."""
        return self.chain.get("atm_strike") if self.available else None

    @property
    def spot_price(self) -> float | None:
        """Underlying spot price from option chain. None if unavailable."""
        return self.chain.get("last_price") if self.available else None

    def otm_call_strike(self, points_otm: float) -> float | None:
        """
        Nearest call strike at least `points_otm` above ATM.

        Returns None if option chain is unavailable.
        """
        if not self.available or not self.atm_strike:
            return None
        target = self.atm_strike + points_otm
        strikes = sorted(self.chain["strikes"].keys())
        candidates = [s for s in strikes if s >= target]
        return candidates[0] if candidates else None

    def otm_put_strike(self, points_otm: float) -> float | None:
        """
        Nearest put strike at least `points_otm` below ATM.

        Returns None if option chain is unavailable.
        """
        if not self.available or not self.atm_strike:
            return None
        target = self.atm_strike - points_otm
        strikes = sorted(self.chain["strikes"].keys(), reverse=True)
        candidates = [s for s in strikes if s <= target]
        return candidates[0] if candidates else None

    def strike_data(self, strike: float) -> dict | None:
        """
        Returns {"ce": {...}, "pe": {...}} for a given strike.

        Returns None if strike not in chain or chain unavailable.
        """
        if not self.available:
            return None
        return self.chain["strikes"].get(float(strike))

    def pcr(self) -> float | None:
        """Put/Call ratio from real OI data. None if unavailable."""
        return self.chain.get("pcr") if self.available else None

    def max_pain(self) -> float | None:
        """Max pain strike. None if unavailable."""
        return self.chain.get("max_pain") if self.available else None

    def atm_iv(self) -> float | None:
        """ATM implied volatility. None if unavailable."""
        return self.chain.get("atm_iv") if self.available else None
