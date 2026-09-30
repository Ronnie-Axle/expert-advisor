"""5-Minute Engulfing Scalping Strategy for NAS100."""

import logging
from datetime import datetime
from trading_bot.strategy.base import Candle, SignalType, Strategy, StrategySignal

logger = logging.getLogger(__name__)


class EngulfingScalperStrategy:
    """Detects 5-minute Bullish and Bearish Engulfing patterns on NAS100."""

    def __init__(
        self,
        sl_buffer_points: float = 5.0,
        min_sl_distance_points: float = 10.0,
    ) -> None:
        self.sl_buffer_points = sl_buffer_points
        self.min_sl_distance_points = min_sl_distance_points
        self._last_processed_candle_time: datetime | None = None

    def evaluate(self, candles: list[Candle], symbol: str) -> StrategySignal | None:
        """Evaluate closed candles for Bullish or Bearish Engulfing pattern.
        
        Expects at least 2 completed candles in chronological order.
        """
        if len(candles) < 2:
            logger.debug("Insufficient candles to evaluate engulfing pattern (%d < 2)", len(candles))
            return None

        prev = candles[-2]
        curr = candles[-1]

        # Do not fire multiple signals on the same closed candle
        if self._last_processed_candle_time is not None and curr.time <= self._last_processed_candle_time:
            return None

        # Check for Bullish Engulfing:
        # 1. Previous candle is bearish
        # 2. Current candle is bullish
        # 3. Current body fully engulfs previous body (curr.open <= prev.close and curr.close >= prev.open)
        if prev.is_bearish and curr.is_bullish:
            if curr.open <= (prev.close + 0.1) and curr.close >= (prev.open - 0.1):
                raw_sl = min(curr.low, prev.low) - self.sl_buffer_points
                entry_price = curr.close
                sl_distance = entry_price - raw_sl
                if sl_distance < self.min_sl_distance_points:
                    raw_sl = entry_price - self.min_sl_distance_points

                self._last_processed_candle_time = curr.time
                reason = (
                    f"Bullish Engulfing confirmed at {curr.time.isoformat()}: "
                    f"curr(O={curr.open:.2f}, C={curr.close:.2f}) engulfed prev(O={prev.open:.2f}, C={prev.close:.2f})"
                )
                logger.info("[%s] %s -> BUY signal at %.2f (SL: %.2f)", symbol, reason, entry_price, raw_sl)
                return StrategySignal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    entry_price=entry_price,
                    suggested_sl=raw_sl,
                    candle_time=curr.time,
                    reason=reason,
                )

        # Check for Bearish Engulfing:
        # 1. Previous candle is bullish
        # 2. Current candle is bearish
        # 3. Current body fully engulfs previous body (curr.open >= prev.close and curr.close <= prev.open)
        if prev.is_bullish and curr.is_bearish:
            if curr.open >= (prev.close - 0.1) and curr.close <= (prev.open + 0.1):
                raw_sl = max(curr.high, prev.high) + self.sl_buffer_points
                entry_price = curr.close
                sl_distance = raw_sl - entry_price
                if sl_distance < self.min_sl_distance_points:
                    raw_sl = entry_price + self.min_sl_distance_points

                self._last_processed_candle_time = curr.time
                reason = (
                    f"Bearish Engulfing confirmed at {curr.time.isoformat()}: "
                    f"curr(O={curr.open:.2f}, C={curr.close:.2f}) engulfed prev(O={prev.open:.2f}, C={prev.close:.2f})"
                )
                logger.info("[%s] %s -> SELL signal at %.2f (SL: %.2f)", symbol, reason, entry_price, raw_sl)
                return StrategySignal(
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    entry_price=entry_price,
                    suggested_sl=raw_sl,
                    candle_time=curr.time,
                    reason=reason,
                )

        return None
