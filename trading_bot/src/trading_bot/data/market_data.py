"""Market data provider interfaces and MT5 / Paper implementations."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from trading_bot.strategy.base import Candle

logger = logging.getLogger(__name__)


class MarketDataFeed(ABC):
    """Abstract interface for candle and tick market data."""

    @abstractmethod
    def get_latest_candles(self, symbol: str, count: int = 10) -> list[Candle]:
        """Fetch the most recent closed/completed candles in chronological order."""
        pass

    @abstractmethod
    def get_current_price(self, symbol: str) -> tuple[float, float]:
        """Return (bid, ask) for the given symbol."""
        pass


class PaperDataFeed(MarketDataFeed):
    """Simulated/Paper data feed for local development, tests, and backtesting."""

    def __init__(self, initial_price: float = 20000.0) -> None:
        self.current_bid = initial_price
        self.current_ask = initial_price + 1.0  # typical 1.0 point spread on NAS100
        self.candles: list[Candle] = []

    def set_candles(self, candles: list[Candle]) -> None:
        self.candles = list(candles)
        if self.candles:
            self.current_bid = self.candles[-1].close
            self.current_ask = self.current_bid + 1.0

    def add_candle(self, candle: Candle) -> None:
        self.candles.append(candle)
        self.current_bid = candle.close
        self.current_ask = self.current_bid + 1.0

    def get_latest_candles(self, symbol: str, count: int = 10) -> list[Candle]:
        return self.candles[-count:] if len(self.candles) >= count else list(self.candles)

    def get_current_price(self, symbol: str) -> tuple[float, float]:
        return self.current_bid, self.current_ask


class MT5DataFeed(MarketDataFeed):
    """Fetches real-time candles and price quotes from MetaTrader 5."""

    def __init__(self, mt5_module: Any | None = None) -> None:
        if mt5_module is not None:
            self._mt5 = mt5_module
        else:
            try:
                import MetaTrader5 as mt5
                self._mt5 = mt5
            except ImportError:
                self._mt5 = None

    def _ensure_connected(self) -> None:
        if self._mt5 is None:
            raise RuntimeError("MetaTrader5 package is not available")
        # Check if terminal is already initialized
        terminal_info = self._mt5.terminal_info()
        if terminal_info is None:
            if not self._mt5.initialize():
                err = self._mt5.last_error()
                raise ConnectionError(f"Failed to connect to MetaTrader 5: {err}")

    def get_latest_candles(self, symbol: str, count: int = 10) -> list[Candle]:
        self._ensure_connected()
        # Request count + 1 rates to exclude the currently open/unclosed bar (index 0)
        rates = self._mt5.copy_rates_from_pos(symbol, self._mt5.TIMEFRAME_M5, 1, count)
        if rates is None or len(rates) == 0:
            logger.warning("No rates returned by MT5 for symbol %s (error: %s)", symbol, self._mt5.last_error())
            return []

        candles: list[Candle] = []
        for r in rates:
            c_time = datetime.fromtimestamp(r["time"], tz=timezone.utc)
            candles.append(
                Candle(
                    time=c_time,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r.get("tick_volume", 0.0) if hasattr(r, "get") else r["tick_volume"]),
                )
            )
        return candles

    def get_current_price(self, symbol: str) -> tuple[float, float]:
        self._ensure_connected()
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ValueError(f"Failed to get price tick for symbol {symbol}: {self._mt5.last_error()}")
        return float(tick.bid), float(tick.ask)
