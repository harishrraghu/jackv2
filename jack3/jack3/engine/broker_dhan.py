"""
Dhan broker implementation of the BrokerAPI interface.

Uses the dhanhq SDK (pip install dhanhq) for live trading.
In paper_mode=True, all orders are simulated in memory.

NOTE: Install dhanhq when ready to go live: pip install dhanhq
"""
import uuid
import time
from typing import Optional
from datetime import datetime, timedelta

from engine.broker import BrokerAPI

# dhanhq is optional -- system works in paper mode without it
try:
    from dhanhq import dhanhq as DhanHQ
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False


class DhanBroker(BrokerAPI):
    """
    Dhan broker implementation.

    In paper_mode: simulates all orders, tracks virtual positions.
    In live_mode: routes all orders through the Dhan REST API.
    """

    def __init__(self, client_id: str, access_token: str, paper_mode: bool = True):
        self.client_id = client_id
        self.access_token = access_token
        self.paper_mode = paper_mode

        # Paper trading state
        self._paper_orders: dict = {}
        self._paper_positions: list = []
        self._paper_order_counter = 0

        # Always connect to Dhan SDK (for historical candle data, even in paper mode)
        if not DHAN_AVAILABLE:
            raise ImportError("dhanhq package not installed. Run: pip install dhanhq")
        from dhanhq import DhanContext
        ctx = DhanContext(client_id, access_token)
        self._dhan = DhanHQ(ctx)

        print(f"[DhanBroker] Initialized in {'PAPER' if paper_mode else 'LIVE'} mode")

    # ─────────────────────────────────────────────────
    #  Core order methods
    # ─────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        qty: int,
        direction: str,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> str:
        """Place a regular order. Returns order_id."""
        if self.paper_mode:
            return self._paper_place_order(symbol, qty, direction, order_type, price)

        transaction_type = "BUY" if direction == "LONG" else "SELL"
        dhan_order_type = "MARKET" if order_type == "MARKET" else "LIMIT"

        response = self._dhan.place_order(
            security_id=symbol,
            exchange_segment="NSE_FNO",
            transaction_type=transaction_type,
            quantity=qty,
            order_type=dhan_order_type,
            product_type="INTRA",
            price=price if dhan_order_type == "LIMIT" else 0,
        )

        if response.get("status") == "success":
            return response["data"]["orderId"]
        raise RuntimeError(f"Order placement failed: {response}")

    def place_super_order(
        self,
        symbol: str,
        qty: int,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target: float,
    ) -> str:
        """
        Place a Dhan Super Order -- entry + SL + target in one order.
        Returns order_id.
        """
        if self.paper_mode:
            order_id = self._paper_place_order(symbol, qty, direction, "SUPER", entry_price)
            self._paper_orders[order_id]["stop_loss"] = stop_loss
            self._paper_orders[order_id]["target"] = target
            return order_id

        transaction_type = "BUY" if direction == "LONG" else "SELL"

        response = self._dhan.place_order(
            security_id=symbol,
            exchange_segment="NSE_FNO",
            transaction_type=transaction_type,
            quantity=qty,
            order_type="LIMIT",
            product_type="INTRA",
            price=entry_price,
            bo_profit_value=abs(target - entry_price),
            bo_stop_loss_value=abs(entry_price - stop_loss),
        )

        if response.get("status") == "success":
            return response["data"]["orderId"]
        raise RuntimeError(f"Super order placement failed: {response}")

    def modify_order(
        self,
        order_id: str,
        price: float = None,
        qty: int = None,
        trigger_price: float = None,
    ) -> bool:
        """Modify a pending order's price or quantity."""
        if self.paper_mode:
            if order_id in self._paper_orders:
                if price is not None:
                    self._paper_orders[order_id]["price"] = price
                if qty is not None:
                    self._paper_orders[order_id]["qty"] = qty
                if trigger_price is not None:
                    self._paper_orders[order_id]["trigger_price"] = trigger_price
                return True
            return False

        order = self._paper_orders.get(order_id, {})
        response = self._dhan.modify_order(
            order_id=order_id,
            order_type="LIMIT",
            leg_name="ENTRY_LEG",
            quantity=qty or order.get("qty", 0),
            price=price or 0,
            trigger_price=trigger_price or 0,
            disclosed_quantity=0,
            validity="DAY",
        )
        return response.get("status") == "success"

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if self.paper_mode:
            if order_id in self._paper_orders:
                self._paper_orders[order_id]["status"] = "CANCELLED"
                return True
            return False

        response = self._dhan.cancel_order(order_id)
        return response.get("status") == "success"

    def get_positions(self) -> list:
        """Get all open positions."""
        if self.paper_mode:
            return self._paper_positions

        response = self._dhan.get_positions()
        if response.get("status") == "success":
            return response.get("data", [])
        return []

    def get_order_status(self, order_id: str) -> dict:
        """Get status of a specific order."""
        if self.paper_mode:
            return self._paper_orders.get(order_id, {"status": "NOT_FOUND"})

        response = self._dhan.get_order_by_id(order_id)
        if response.get("status") == "success":
            return response.get("data", {})
        return {"status": "ERROR", "message": str(response)}

    def get_ltp(self, symbol: str) -> float:
        """
        Get last traded price. Fetches real price even in paper mode.
        Falls back to 0.0 if unavailable.
        """
        if self._dhan is None:
            # Paper mode without dhan SDK -- caller must supply price
            return 0.0

        try:
            response = self._dhan.ohlc_data({"NSE_FNO": [int(symbol)]})
            if response.get("status") == "success":
                data = response.get("data", {}).get("NSE_FNO", {})
                if str(symbol) in data:
                    return float(data[str(symbol)].get("last_price", 0))
        except Exception as e:
            print(f"[DhanBroker] get_ltp error for {symbol}: {e}")
        return 0.0

    def modify_stop_loss(self, order_id: str, new_stop_loss: float) -> bool:
        """Tighten the stop loss on an open super order."""
        if self.paper_mode:
            if order_id in self._paper_orders:
                old_sl = self._paper_orders[order_id].get("stop_loss", 0)
                direction = self._paper_orders[order_id].get("direction", "LONG")
                # Only allow tightening (moving SL closer to current price)
                if direction == "LONG" and new_stop_loss > old_sl:
                    self._paper_orders[order_id]["stop_loss"] = new_stop_loss
                    return True
                elif direction == "SHORT" and new_stop_loss < old_sl:
                    self._paper_orders[order_id]["stop_loss"] = new_stop_loss
                    return True
                return False
            return False

        return self.modify_order(order_id, trigger_price=new_stop_loss)

    # ─────────────────────────────────────────────────
    #  Historical data methods
    # ─────────────────────────────────────────────────

    def get_historical_daily(
        self,
        security_id: str,
        days: int = 60,
        exchange_segment: str = "NSE_FNO",
        instrument_type: str = "FUTIDX",
    ) -> "pd.DataFrame":
        """
        Fetch daily OHLCV data for the last N days.
        Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.
        """
        import pandas as pd
        from datetime import date, timedelta

        to_date = date.today().strftime("%Y-%m-%d")
        from_date = (date.today() - timedelta(days=days + 30)).strftime("%Y-%m-%d")

        if self._dhan is None:
            print("[DhanBroker] No dhan client -- returning empty DataFrame")
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

        try:
            response = self._dhan.historical_daily_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
            )

            if response.get("status") == "success":
                data = response.get("data", {})
                df = pd.DataFrame({
                    "Date": pd.to_datetime(data.get("timestamp", [])),
                    "Open": data.get("open", []),
                    "High": data.get("high", []),
                    "Low": data.get("low", []),
                    "Close": data.get("close", []),
                    "Volume": data.get("volume", []),
                })
                return df.tail(days).reset_index(drop=True)
        except Exception as e:
            print(f"[DhanBroker] get_historical_daily error: {e}")

        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

    def get_historical_intraday(
        self,
        security_id: str,
        interval: int = 5,
        days_back: int = 5,
        from_date: str = None,
        to_date: str = None,
        exchange_segment: str = "IDX_I",
        instrument_type: str = "INDEX",
    ) -> "pd.DataFrame":
        """
        Fetch intraday OHLCV data for BankNifty from Dhan v2 API.

        Uses IDX_I / INDEX for the BankNifty spot index (security_id=25).
        Dhan returns Unix timestamps (float seconds) -- converted to IST naive datetimes.
        Splits requests into 90-day chunks per Dhan v2 limits.

        Args:
            security_id: Dhan security ID (25 = BankNifty index).
            interval: Candle interval in minutes (1, 5, 15, 25, 60).
            days_back: Simple lookback in days (used if from_date/to_date not given).
            from_date: Start date "YYYY-MM-DD" (overrides days_back).
            to_date: End date "YYYY-MM-DD" (defaults to today).
            exchange_segment: "IDX_I" for index, "NSE_FNO" for futures/options.
            instrument_type: "INDEX" for spot index, "FUTIDX" for futures.

        Returns:
            DataFrame with columns: Datetime, Open, High, Low, Close, Volume.
            Datetime is IST naive (no timezone), sorted ascending.
        """
        import pandas as pd
        import time as time_mod
        from datetime import date as date_cls, timedelta

        # Resolve date range
        end = date_cls.fromisoformat(to_date) if to_date else date_cls.today()
        if from_date:
            start = date_cls.fromisoformat(from_date)
        else:
            start = end - timedelta(days=days_back + 2)

        # Split into 90-day chunks (Dhan v2 API limit per call)
        chunks = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=89), end)
            chunks.append((chunk_start, chunk_end))
            chunk_start = chunk_end + timedelta(days=1)

        all_frames = []
        for i, (cs, ce) in enumerate(chunks):
            try:
                response = self._dhan.intraday_minute_data(
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    instrument_type=instrument_type,
                    from_date=cs.strftime("%Y-%m-%d"),
                    to_date=ce.strftime("%Y-%m-%d"),
                    interval=interval,
                )
                if response.get("status") == "success":
                    data = response.get("data", {})
                    timestamps = data.get("timestamp", [])
                    if timestamps:
                        # Dhan returns Unix epoch floats -- convert to IST naive datetime
                        dt_series = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
                        df = pd.DataFrame({
                            "Datetime": dt_series,
                            "Open": data.get("open", []),
                            "High": data.get("high", []),
                            "Low": data.get("low", []),
                            "Close": data.get("close", []),
                            "Volume": data.get("volume", []),
                        })
                        all_frames.append(df)
                else:
                    print(f"[DhanBroker] Chunk {cs}->{ce} failed: {response.get('remarks', response)}")

                # Rate limiting: 1 request per 2 seconds for bulk fetches
                if len(chunks) > 1:
                    time_mod.sleep(2)

            except Exception as e:
                print(f"[DhanBroker] Chunk {cs}->{ce} error: {e}")

        if not all_frames:
            return pd.DataFrame(columns=["Datetime", "Open", "High", "Low", "Close", "Volume"])

        result = pd.concat(all_frames, ignore_index=True)
        result = result.drop_duplicates(subset=["Datetime"])
        result = result.sort_values("Datetime").reset_index(drop=True)
        return result

    def get_option_chain(
        self,
        underlying_id: str,
        expiry: str = None,
        exchange_segment: str = "IDX_I",
    ) -> dict:
        """
        Fetch live option chain for BankNifty from Dhan v2 API.

        Returns {} if Dhan market feed subscription is not active. The loop
        continues without option data rather than using fabricated values.

        Returns:
            {
              "last_price": float,
              "strikes": {strike: {"ce": {...greeks, ltp, oi, iv}, "pe": {...}}},
              "max_pain": float,
              "pcr": float,
              "atm_iv": float,
              "atm_strike": float,
            }
        """
        # Always attempt the real Dhan API -- no fake data
        try:
            # Get nearest expiry if not provided
            if not expiry:
                expiry_resp = self._dhan.expiry_list(
                    under_security_id=int(underlying_id),
                    under_exchange_segment=exchange_segment,
                )
                if expiry_resp.get("status") == "success":
                    # Dhan v2 wraps data in a nested dict: response["data"]["data"] = [expiry_list]
                    raw_data = expiry_resp.get("data", {})
                    if isinstance(raw_data, dict):
                        expiry_list = raw_data.get("data", [])
                    else:
                        expiry_list = raw_data if isinstance(raw_data, list) else []
                    if expiry_list:
                        expiry = expiry_list[0]  # nearest expiry
                    else:
                        print("[DhanBroker] WARNING: Option chain unavailable -- empty expiry list. "
                              "Proceeding without option data.")
                        return {}
                else:
                    print("[DhanBroker] WARNING: Option chain unavailable -- expiry list failed. "
                          "Dhan market feed subscription may be required for options data.")
                    return {}

            response = self._dhan.option_chain(
                under_security_id=int(underlying_id),
                under_exchange_segment=exchange_segment,
                expiry=expiry,
            )
            if response.get("status") == "success":
                # Dhan v2 wraps the actual data in a nested dict: response["data"]["data"]
                raw = response.get("data", {})
                if isinstance(raw, dict) and "data" in raw:
                    raw = raw["data"]
                return self._parse_option_chain(raw)
            else:
                print(f"[DhanBroker] WARNING: Option chain unavailable -- {response.get('remarks', 'no error detail')}. "
                      "Proceeding without option data.")
                return {}
        except Exception as e:
            print(f"[DhanBroker] Option chain error: {e}. Proceeding without option data.")
            return {}

    # ─────────────────────────────────────────────────
    #  Paper trading helpers
    # ─────────────────────────────────────────────────

    def _paper_place_order(self, symbol, qty, direction, order_type, price) -> str:
        self._paper_order_counter += 1
        order_id = f"PAPER_{self._paper_order_counter:06d}"
        self._paper_orders[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "qty": qty,
            "direction": direction,
            "order_type": order_type,
            "price": price,
            "status": "PENDING",
            "timestamp": datetime.now().isoformat(),
        }
        print(f"[DhanBroker:PAPER] Order placed: {order_id} | {direction} {qty} @ {price}")
        return order_id

    def paper_fill_order(self, order_id: str, fill_price: float) -> None:
        """Mark a paper order as filled at given price. Called by the loop."""
        if order_id in self._paper_orders:
            self._paper_orders[order_id]["status"] = "FILLED"
            self._paper_orders[order_id]["fill_price"] = fill_price
            self._paper_orders[order_id]["fill_time"] = datetime.now().isoformat()

    # ─────────────────────────────────────────────────
    #  Option chain parsing
    # ─────────────────────────────────────────────────

    def _parse_option_chain(self, raw: dict) -> dict:
        """Parse Dhan option chain response into unified format."""
        last_price = float(raw.get("last_price", 0))
        oc = raw.get("oc", {})

        strikes = {}
        total_ce_oi = 0
        total_pe_oi = 0

        for strike_str, data in oc.items():
            strike = float(strike_str)
            ce_data = data.get("ce", {})
            pe_data = data.get("pe", {})
            ce_greeks = ce_data.get("greeks", {})
            pe_greeks = pe_data.get("greeks", {})

            ce_oi = int(ce_data.get("oi", 0))
            pe_oi = int(pe_data.get("oi", 0))
            total_ce_oi += ce_oi
            total_pe_oi += pe_oi

            strikes[strike] = {
                "ce": {
                    "ltp": float(ce_data.get("last_price", 0)),
                    "oi": ce_oi,
                    "volume": int(ce_data.get("volume", 0)),
                    "iv": float(ce_data.get("implied_volatility", 0)),
                    "delta": float(ce_greeks.get("delta", 0)),
                    "theta": float(ce_greeks.get("theta", 0)),
                    "gamma": float(ce_greeks.get("gamma", 0)),
                    "vega": float(ce_greeks.get("vega", 0)),
                },
                "pe": {
                    "ltp": float(pe_data.get("last_price", 0)),
                    "oi": pe_oi,
                    "volume": int(pe_data.get("volume", 0)),
                    "iv": float(pe_data.get("implied_volatility", 0)),
                    "delta": float(pe_greeks.get("delta", 0)),
                    "theta": float(pe_greeks.get("theta", 0)),
                    "gamma": float(pe_greeks.get("gamma", 0)),
                    "vega": float(pe_greeks.get("vega", 0)),
                },
            }

        # ATM strike = nearest to last_price
        atm_strike = min(strikes.keys(), key=lambda s: abs(s - last_price)) if strikes else 0
        atm_iv = 0.0
        if atm_strike and atm_strike in strikes:
            ce_iv = strikes[atm_strike]["ce"]["iv"]
            pe_iv = strikes[atm_strike]["pe"]["iv"]
            atm_iv = (ce_iv + pe_iv) / 2

        # Max pain: strike where total option buyer loss is maximized
        max_pain = self._compute_max_pain(strikes)

        # PCR
        pcr = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else 1.0

        return {
            "last_price": last_price,
            "strikes": strikes,
            "max_pain": max_pain,
            "pcr": round(pcr, 3),
            "atm_iv": round(atm_iv, 2),
            "atm_strike": atm_strike,
        }

    def _compute_max_pain(self, strikes: dict) -> float:
        """Compute max pain strike: where total option buyer pain is highest."""
        if not strikes:
            return 0.0
        pain = {}
        strike_list = sorted(strikes.keys())
        for expiry_strike in strike_list:
            total_pain = 0
            for s, data in strikes.items():
                # CE buyer loss at expiry_strike
                ce_loss = max(0, expiry_strike - s) * data["ce"]["oi"]
                # PE buyer loss at expiry_strike
                pe_loss = max(0, s - expiry_strike) * data["pe"]["oi"]
                total_pain += ce_loss + pe_loss
            pain[expiry_strike] = total_pain
        return max(pain, key=pain.get) if pain else 0.0

