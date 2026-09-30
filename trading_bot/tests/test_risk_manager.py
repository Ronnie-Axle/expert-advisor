"""Unit tests for the RiskManager (10% total risk ceiling, 20% per order TP, 20% daily drawdown limit)."""

from datetime import datetime, timezone
from trading_bot.config import BotConfig
from trading_bot.risk.manager import PositionInfo, RiskManager
from trading_bot.strategy.base import SignalType


def test_initial_order_sizing_and_risk_limit():
    config = BotConfig(
        initial_orders_count=2,
        max_active_orders=10,
        max_total_risk_pct=0.10,  # 10% max risk
        profit_target_pct_per_order=0.20,  # 20% per order TP
        default_contract_size=1.0,
    )
    rm = RiskManager(config)
    balance = 10000.0
    equity = 10000.0

    entry_price = 20000.0
    stop_loss = 19950.0  # 50 points distance

    res = rm.evaluate_new_order_setup(
        balance=balance,
        equity=equity,
        open_positions=[],
        signal_type=SignalType.BUY,
        entry_price=entry_price,
        stop_loss=stop_loss,
        contract_size=1.0,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
    )

    assert res.is_allowed is True
    plan = res.plan
    assert plan is not None
    # 2 orders at beginning
    assert plan.num_orders == 2

    # Total risk budget = 10% of 10,000 = $1,000
    # For 2 orders, each order risks at most $500
    # Distance = 50 pts => Lots = 500 / (50 * 1) = 10.0 lots per order
    # Total risk = 2 * 10 * 50 = $1,000 (10% of 10,000)
    assert plan.total_new_risk_usd <= 1000.0
    assert plan.total_new_risk_usd == 1000.0
    assert plan.lots_per_order == 10.0

    # Profit target = 20% of account balance = 20% of 10,000 = $2,000 per order
    # Distance TP = 2000 / (10 * 1) = 200 points
    # BUY TP = 20000 + 200 = 20200
    assert plan.target_profit_per_order_usd == 2000.0
    assert plan.take_profit == 20200.0


def test_risk_budget_exhaustion_rejects_excess_orders():
    config = BotConfig(
        max_total_risk_pct=0.10,  # $1,000 on $10,000
        max_active_orders=10,
    )
    rm = RiskManager(config)
    balance = 10000.0
    equity = 10000.0

    # Simulate existing active positions already risking $1000 (10% of balance)
    existing_positions = [
        PositionInfo(
            ticket=101,
            symbol="NAS100",
            order_type=SignalType.BUY,
            lots=10.0,
            open_price=20000.0,
            sl=19900.0,  # 100 pts * 10 lots = $1000 risk
            tp=22000.0,
        )
    ]

    res = rm.evaluate_new_order_setup(
        balance=balance,
        equity=equity,
        open_positions=existing_positions,
        signal_type=SignalType.BUY,
        entry_price=20050.0,
        stop_loss=20000.0,
        contract_size=1.0,
    )

    assert res.is_allowed is False
    assert "Risk limit reached" in res.reason


def test_max_active_orders_limit():
    config = BotConfig(max_active_orders=10)
    rm = RiskManager(config)
    balance = 50000.0
    equity = 50000.0

    # 10 existing small positions
    positions = [
        PositionInfo(ticket=i, symbol="NAS100", order_type=SignalType.BUY, lots=0.1, open_price=20000.0, sl=19980.0, tp=20100.0)
        for i in range(10)
    ]

    res = rm.evaluate_new_order_setup(
        balance=balance,
        equity=equity,
        open_positions=positions,
        signal_type=SignalType.BUY,
        entry_price=20000.0,
        stop_loss=19950.0,
        contract_size=1.0,
    )

    assert res.is_allowed is False
    assert "Maximum concurrent orders reached" in res.reason


def test_daily_drawdown_circuit_breaker():
    config = BotConfig(
        daily_drawdown_limit_pct=0.20,  # 20% limit
    )
    rm = RiskManager(config)
    t0 = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)

    # Day starts with $10,000 balance
    rm.update_day_baseline(current_balance=10000.0, current_time=t0)
    assert rm.day_start_balance == 10000.0

    # Equity drops to $8,500 (15% drawdown -> allowed)
    breached, dd_pct, msg = rm.check_daily_drawdown(balance=10000.0, equity=8500.0, current_time=t0)
    assert breached is False
    assert round(dd_pct, 2) == 0.15

    # Equity drops to $7,900 (21% drawdown -> breached!)
    breached, dd_pct, msg = rm.check_daily_drawdown(balance=10000.0, equity=7900.0, current_time=t0)
    assert breached is True
    assert round(dd_pct, 2) == 0.21
    assert rm.circuit_breaker_tripped is True
    assert "Daily drawdown limit hit" in msg

    # Any new trade evaluation is immediately blocked
    res = rm.evaluate_new_order_setup(
        balance=10000.0,
        equity=7900.0,
        open_positions=[],
        signal_type=SignalType.BUY,
        entry_price=20000.0,
        stop_loss=19950.0,
        current_time=t0,
    )
    assert res.is_allowed is False
    assert "Trading locked" in res.reason
