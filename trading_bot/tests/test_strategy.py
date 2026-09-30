"""Unit tests for the 5-Minute Bullish and Bearish Engulfing Scalping Strategy."""

from datetime import datetime, timedelta, timezone
from trading_bot.strategy.base import Candle, SignalType
from trading_bot.strategy.user_strategy import EngulfingScalperStrategy


def create_candle(t_offset_minutes: int, open_: float, high: float, low: float, close: float) -> Candle:
    base_time = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    return Candle(
        time=base_time + timedelta(minutes=t_offset_minutes),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_bullish_engulfing_signal():
    strategy = EngulfingScalperStrategy(sl_buffer_points=5.0, min_sl_distance_points=10.0)

    # Candle 0: Bearish (Open 20100, Close 20050)
    c0 = create_candle(0, open_=20100.0, high=20110.0, low=20040.0, close=20050.0)
    # Candle 1: Bullish Engulfing (Open 20045, Close 20120) - completely engulfs c0 body
    c1 = create_candle(5, open_=20045.0, high=20125.0, low=20040.0, close=20120.0)

    signal = strategy.evaluate([c0, c1], symbol="NAS100")

    assert signal is not None
    assert signal.signal_type == SignalType.BUY
    assert signal.entry_price == 20120.0
    # Expected SL = min(c1.low, c0.low) - buffer = 20040.0 - 5.0 = 20035.0
    assert signal.suggested_sl == 20035.0
    assert "Bullish Engulfing" in signal.reason


def test_bearish_engulfing_signal():
    strategy = EngulfingScalperStrategy(sl_buffer_points=5.0, min_sl_distance_points=10.0)

    # Candle 0: Bullish (Open 20050, Close 20100)
    c0 = create_candle(0, open_=20050.0, high=20105.0, low=20045.0, close=20100.0)
    # Candle 1: Bearish Engulfing (Open 20105, Close 20040) - completely engulfs c0 body
    c1 = create_candle(5, open_=20105.0, high=20110.0, low=20035.0, close=20040.0)

    signal = strategy.evaluate([c0, c1], symbol="NAS100")

    assert signal is not None
    assert signal.signal_type == SignalType.SELL
    assert signal.entry_price == 20040.0
    # Expected SL = max(c1.high, c0.high) + buffer = 20110.0 + 5.0 = 20115.0
    assert signal.suggested_sl == 20115.0
    assert "Bearish Engulfing" in signal.reason


def test_no_signal_on_non_engulfing_candles():
    strategy = EngulfingScalperStrategy()

    # Both Bullish candles
    c0 = create_candle(0, open_=20000.0, high=20050.0, low=19990.0, close=20040.0)
    c1 = create_candle(5, open_=20040.0, high=20080.0, low=20030.0, close=20070.0)
    assert strategy.evaluate([c0, c1], symbol="NAS100") is None

    # Inside bar (c1 smaller body inside c0)
    c2 = create_candle(10, open_=20060.0, high=20065.0, low=20050.0, close=20055.0)
    assert strategy.evaluate([c1, c2], symbol="NAS100") is None


def test_no_duplicate_signal_on_same_candle():
    strategy = EngulfingScalperStrategy()

    c0 = create_candle(0, open_=20100.0, high=20110.0, low=20040.0, close=20050.0)
    c1 = create_candle(5, open_=20045.0, high=20125.0, low=20040.0, close=20120.0)

    sig1 = strategy.evaluate([c0, c1], symbol="NAS100")
    assert sig1 is not None

    # Call again with the same candle time
    sig2 = strategy.evaluate([c0, c1], symbol="NAS100")
    assert sig2 is None
