"""End-to-end integration tests for TradingBotEngine."""

from datetime import datetime, timedelta, timezone
from trading_bot.config import BotConfig
from trading_bot.data.market_data import PaperDataFeed
from trading_bot.data.trace_store import TraceStore
from trading_bot.execution.broker import PaperBroker
from trading_bot.engine import TradingBotEngine
from trading_bot.strategy.base import Candle, SignalType


def test_engine_executes_twin_orders_on_engulfing(tmp_path):
    db_path = tmp_path / "traces.sqlite3"
    trace_store = TraceStore(db_path)
    config = BotConfig(
        symbol="NAS100",
        initial_orders_count=2,
        max_active_orders=10,
        max_total_risk_pct=0.10,
        profit_target_pct_per_order=0.20,
        daily_drawdown_limit_pct=0.20,
    )
    broker = PaperBroker(initial_balance=10000.0)
    data_feed = PaperDataFeed(initial_price=20000.0)

    # Bullish engulfing candles
    t0 = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    c0 = Candle(time=t0, open=20100.0, high=20110.0, low=20040.0, close=20050.0, volume=100.0)
    c1 = Candle(time=t0 + timedelta(minutes=5), open=20045.0, high=20125.0, low=20040.0, close=20120.0, volume=100.0)
    data_feed.set_candles([c0, c1])

    engine = TradingBotEngine(
        config=config,
        data_feed=data_feed,
        broker=broker,
        trace_store=trace_store,
    )

    result = engine.step()
    assert result["status"] == "ORDERS_EXECUTED"
    assert result["placed_orders_count"] == 2
    assert len(result["tickets"]) == 2

    # Check broker has 2 open positions
    open_positions = broker.get_open_positions("NAS100")
    assert len(open_positions) == 2

    # Check total risk does not exceed 10% ($1,000)
    total_risk = engine.risk_manager.calculate_active_risk(open_positions)
    assert total_risk <= 1000.0

    # Check that traces were stored
    traces = trace_store.get_traces()
    event_types = [t.event_type for t in traces]
    assert "ORDER_PLACED" in event_types
    assert "SETUP_EXECUTED" in event_types


def test_engine_drawdown_circuit_breaker_liquidates_positions(tmp_path):
    db_path = tmp_path / "traces.sqlite3"
    trace_store = TraceStore(db_path)
    config = BotConfig(
        symbol="NAS100",
        daily_drawdown_limit_pct=0.20,
    )
    broker = PaperBroker(initial_balance=10000.0)
    data_feed = PaperDataFeed()

    engine = TradingBotEngine(
        config=config,
        data_feed=data_feed,
        broker=broker,
        trace_store=trace_store,
    )

    # Place an open position
    ticket = broker.place_order(
        symbol="NAS100",
        signal_type=SignalType.BUY,
        lots=1.0,
        price=20000.0,
        sl=19900.0,
        tp=20400.0,
    )
    assert len(broker.get_open_positions("NAS100")) == 1

    # Simulate equity crashing by 22% ($7,800 <= $8,000 threshold)
    broker.positions[ticket].current_profit = -2200.0
    broker.equity = 7800.0

    result = engine.step()
    assert result["status"] == "CIRCUIT_BREAKER_TRIPPED"

    # All positions must be closed immediately
    assert len(broker.get_open_positions("NAS100")) == 0

    # Trace must be logged
    cb_traces = trace_store.get_traces(event_type="CIRCUIT_BREAKER_TRIGGERED")
    assert len(cb_traces) >= 1
