"""
Broker API Interface.

Abstract base class defining the standard broker integration for Jack.
"""

from abc import ABC, abstractmethod


class BrokerAPI(ABC):
    """Abstract interface for live broker integrations."""

    @abstractmethod
    def place_order(self, symbol: str, qty: int, direction: str, order_type: str, price: float = None) -> str:
        pass

    @abstractmethod
    def modify_order(self, order_id: str, price: float = None, qty: int = None) -> bool:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_positions(self) -> list[dict]:
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict:
        pass

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        pass
