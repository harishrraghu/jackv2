"""
Zerodha Kite Connect Implementation.

Requires 'kiteconnect' installed. Handles orders for Kite platform.
"""

import sys
from engine.broker import BrokerAPI

try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False


class ZerodhaBroker(BrokerAPI):
    """Zerodha Kite Connect broker implementation."""

    def __init__(self, api_key: str, access_token: str):
        if not KITE_AVAILABLE:
            raise ImportError("kiteconnect not installed. Please install it to use ZerodhaBroker.")
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(access_token)

    def place_order(self, symbol: str, qty: int, direction: str, order_type: str, price: float = None) -> str:
        transaction_type = self.kite.TRANSACTION_TYPE_BUY if direction == "LONG" else self.kite.TRANSACTION_TYPE_SELL
        
        kite_order_type = self.kite.ORDER_TYPE_MARKET
        if order_type == "LIMIT":
            kite_order_type = self.kite.ORDER_TYPE_LIMIT
        elif order_type == "SL":
            kite_order_type = self.kite.ORDER_TYPE_SL

        try:
            order_id = self.kite.place_order(
                tradingsymbol=symbol,
                exchange=self.kite.EXCHANGE_NFO,
                transaction_type=transaction_type,
                quantity=qty,
                order_type=kite_order_type,
                product=self.kite.PRODUCT_MIS, # Intraday
                price=price,
                variety=self.kite.VARIETY_REGULAR
            )
            return order_id
        except Exception as e:
            print(f"[Broker] Failed to place order: {e}", file=sys.stderr)
            return ""

    def modify_order(self, order_id: str, price: float = None, qty: int = None) -> bool:
        try:
            self.kite.modify_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id,
                price=price,
                quantity=qty
            )
            return True
        except Exception:
            return False

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.kite.cancel_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id
            )
            return True
        except Exception:
            return False

    def get_positions(self) -> list[dict]:
        try:
            pos = self.kite.positions()
            return pos.get("net", [])
        except Exception:
            return []

    def get_order_status(self, order_id: str) -> dict:
        try:
            orders = self.kite.orders()
            for o in orders:
                if o["order_id"] == order_id:
                    return {"status": o["status"], "filled_qty": o["filled_quantity"]}
            return {"status": "UNKNOWN", "filled_qty": 0}
        except Exception:
            return {"status": "ERROR", "filled_qty": 0}

    def get_ltp(self, symbol: str) -> float:
        try:
            q = self.kite.quote([f"NFO:{symbol}"])
            return float(q[f"NFO:{symbol}"]["last_price"])
        except Exception:
            return 0.0
