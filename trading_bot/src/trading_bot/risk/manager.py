"""Risk Manager enforcing the 10% maximum total risk and 20% daily drawdown limit."""

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from trading_bot.config import BotConfig
from trading_bot.strategy.base import SignalType

logger = logging.getLogger(__name__)


@dataclass
class PositionInfo:
    """Snapshot of an open position for risk aggregation."""
    ticket: int
    symbol: str
    order_type: SignalType
    lots: float
    open_price: float
    sl: float
    tp: float
    current_profit: float = 0.0


@dataclass
class OrderRiskPlan:
    """Pre-calculated order parameters conforming to risk limits."""
    num_orders: int
    lots_per_order: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_per_order_usd: float
    total_new_risk_usd: float
    target_profit_per_order_usd: float


@dataclass
class RiskCheckResult:
    """Outcome of pre-trade risk evaluation."""
    is_allowed: bool
    reason: str
    plan: OrderRiskPlan | None = None


class RiskManager:
    """Enforces strict account preservation:
    1. Maximum 10% total risk across all active trades.
    2. Scalable entries up to 10 orders (starting with 2 orders).
    3. Take profit targeting 20% account balance gain per order.
    4. Hard 20% daily drawdown circuit breaker.
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.day_start_balance: float = 0.0
        self.current_trading_date: date | None = None
        self.circuit_breaker_tripped: bool = False
        self.circuit_breaker_reason: str = ""

    def update_day_baseline(self, current_balance: float, current_time: datetime | None = None) -> None:
        """Reset or maintain the daily balance benchmark for drawdown tracking."""
        today = (current_time or datetime.now(timezone.utc)).date()
        if self.current_trading_date != today:
            self.current_trading_date = today
            self.day_start_balance = current_balance
            self.circuit_breaker_tripped = False
            self.circuit_breaker_reason = ""
            logger.info("New trading day [%s]: Benchmark balance set to $%.2f", today, current_balance)
        elif self.day_start_balance <= 0.0:
            self.day_start_balance = current_balance

    def check_daily_drawdown(self, balance: float, equity: float, current_time: datetime | None = None) -> tuple[bool, float, str]:
        """Check if equity dropped by 20% or more from day-start baseline.
        
        Returns:
            (is_breached, current_dd_pct, reason)
        """
        self.update_day_baseline(balance, current_time)

        if self.day_start_balance <= 0:
            return False, 0.0, "Baseline balance not initialized"

        drawdown_dollars = self.day_start_balance - equity
        current_dd_pct = drawdown_dollars / self.day_start_balance

        if current_dd_pct >= self.config.daily_drawdown_limit_pct:
            self.circuit_breaker_tripped = True
            self.circuit_breaker_reason = (
                f"Daily drawdown limit hit: {current_dd_pct * 100:.2f}% >= "
                f"{self.config.daily_drawdown_limit_pct * 100:.1f}% "
                f"(Start: ${self.day_start_balance:.2f}, Equity: ${equity:.2f})"
            )
            logger.critical("CIRCUIT BREAKER TRIGGERED: %s", self.circuit_breaker_reason)
            return True, current_dd_pct, self.circuit_breaker_reason

        return False, current_dd_pct, "Drawdown within allowable limit"

    def calculate_active_risk(
        self, open_positions: list[PositionInfo], contract_size: float | None = None
    ) -> float:
        """Sum the dollar risk of all open positions based on their Stop Losses."""
        c_size = contract_size or self.config.default_contract_size
        total_risk_usd = 0.0

        for pos in open_positions:
            if pos.sl > 0:
                price_distance = abs(pos.open_price - pos.sl)
                order_risk = pos.lots * c_size * price_distance
                total_risk_usd += order_risk
            else:
                # If an open position lacks a formal SL, assume at least default buffer risk
                order_risk = pos.lots * c_size * self.config.min_sl_distance_points
                total_risk_usd += order_risk

        return total_risk_usd

    def evaluate_new_order_setup(
        self,
        balance: float,
        equity: float,
        open_positions: list[PositionInfo],
        signal_type: SignalType,
        entry_price: float,
        stop_loss: float,
        contract_size: float = 1.0,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        lot_step: float = 0.01,
        current_time: datetime | None = None,
    ) -> RiskCheckResult:
        """Validate and size new orders against 10% risk, max orders, and 20% daily drawdown."""
        # 1. Daily drawdown check
        breached, dd_pct, dd_msg = self.check_daily_drawdown(balance, equity, current_time)
        if breached or self.circuit_breaker_tripped:
            return RiskCheckResult(
                is_allowed=False,
                reason=f"Trading locked: {self.circuit_breaker_reason or dd_msg}",
            )

        # 2. Max active orders check (can enter up to 10 orders)
        current_order_count = len(open_positions)
        if current_order_count >= self.config.max_active_orders:
            return RiskCheckResult(
                is_allowed=False,
                reason=f"Maximum concurrent orders reached ({current_order_count}/{self.config.max_active_orders})",
            )

        # 3. Determine how many orders to place in this setup
        # If no active trades, start with initial_orders_count (default 2); otherwise fill available slots up to max_active_orders
        available_slots = self.config.max_active_orders - current_order_count
        if current_order_count == 0:
            num_orders = min(self.config.initial_orders_count, available_slots)
        else:
            num_orders = min(1, available_slots)

        if num_orders <= 0:
            return RiskCheckResult(is_allowed=False, reason="No available order slots")

        # 4. Total Risk budget (Max 10% of account balance)
        max_allowable_risk_usd = balance * self.config.max_total_risk_pct
        current_active_risk_usd = self.calculate_active_risk(open_positions, contract_size)
        remaining_risk_budget_usd = max_allowable_risk_usd - current_active_risk_usd

        if remaining_risk_budget_usd <= 0:
            return RiskCheckResult(
                is_allowed=False,
                reason=(
                    f"Risk limit reached: active risk ${current_active_risk_usd:.2f} >= "
                    f"budget ${max_allowable_risk_usd:.2f} ({self.config.max_total_risk_pct * 100:.1f}% of balance)"
                ),
            )

        # 5. Stop Loss distance
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance < self.config.min_sl_distance_points:
            sl_distance = self.config.min_sl_distance_points
            stop_loss = (
                entry_price - sl_distance
                if signal_type == SignalType.BUY
                else entry_price + sl_distance
            )

        # Risk budget allocated per new order in this setup
        risk_per_order_usd = remaining_risk_budget_usd / num_orders

        # Raw lot calculation: Risk = Lots * ContractSize * SL_Distance
        raw_lot = risk_per_order_usd / (sl_distance * contract_size)

        # Normalize to broker lot step and bounds
        lots_stepped = math.floor(raw_lot / lot_step) * lot_step
        lots_per_order = round(max(min_lot, min(lots_stepped, max_lot)), 2)

        # Check if min_lot would breach total allowable risk
        actual_total_new_risk = num_orders * (lots_per_order * contract_size * sl_distance)
        if (current_active_risk_usd + actual_total_new_risk) > (max_allowable_risk_usd * 1.05):
            # Allow at most 5% rounding tolerance, otherwise reject
            return RiskCheckResult(
                is_allowed=False,
                reason=(
                    f"Calculated lot {lots_per_order} exceeds remaining risk budget "
                    f"(${actual_total_new_risk:.2f} > ${remaining_risk_budget_usd:.2f})"
                ),
            )

        # 6. Take profit calculation (20% balance gain per order)
        # Target Profit = 0.20 * Balance = Lots * ContractSize * TP_Distance
        target_profit_per_order_usd = balance * self.config.profit_target_pct_per_order
        tp_distance = target_profit_per_order_usd / (lots_per_order * contract_size)

        if signal_type == SignalType.BUY:
            take_profit = round(entry_price + tp_distance, 2)
        else:
            take_profit = round(entry_price - tp_distance, 2)

        plan = OrderRiskPlan(
            num_orders=num_orders,
            lots_per_order=lots_per_order,
            entry_price=entry_price,
            stop_loss=round(stop_loss, 2),
            take_profit=take_profit,
            risk_per_order_usd=round(lots_per_order * contract_size * sl_distance, 2),
            total_new_risk_usd=round(actual_total_new_risk, 2),
            target_profit_per_order_usd=round(target_profit_per_order_usd, 2),
        )

        return RiskCheckResult(
            is_allowed=True,
            reason=f"Approved: {num_orders} orders x {lots_per_order} lots risking ${actual_total_new_risk:.2f} (<= 10% balance)",
            plan=plan,
        )
