"""Core bot engine coordinating data feeds, engulfing strategy, risk controls, and broker execution."""

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from trading_bot.config import BotConfig
from trading_bot.data.market_data import MarketDataFeed, MT5DataFeed, PaperDataFeed
from trading_bot.data.trace_store import TraceStore
from trading_bot.execution.broker import BaseBroker, MT5Broker, PaperBroker
from trading_bot.risk.manager import RiskManager
from trading_bot.strategy.base import SignalType
from trading_bot.strategy.user_strategy import EngulfingScalperStrategy

logger = logging.getLogger(__name__)


class TradingBotEngine:
    """Orchestrates NAS100 5-Minute Engulfing Scalping with strict 10% risk & 20% drawdown limits."""

    def __init__(
        self,
        config: BotConfig,
        data_feed: MarketDataFeed | None = None,
        broker: BaseBroker | None = None,
        trace_store: TraceStore | None = None,
    ) -> None:
        self.config = config
        self.trace_store = trace_store or TraceStore(config.db_path)
        self.risk_manager = RiskManager(config)
        self.strategy = EngulfingScalperStrategy(
            sl_buffer_points=config.sl_buffer_points,
            min_sl_distance_points=config.min_sl_distance_points,
        )

        # Initialize Broker and Data Feed based on mode
        if broker is not None and data_feed is not None:
            self.broker = broker
            self.data_feed = data_feed
        elif config.mode == "mt5":
            logger.info("Initializing MT5 Broker and Data Feed...")
            mt5_broker = MT5Broker(config)
            connected = False
            try:
                connected = mt5_broker.connect()
            except Exception as e:
                logger.warning("Could not connect to live MT5 terminal (%s). Falling back to PaperBroker.", e)

            if connected:
                self.broker = mt5_broker
                self.data_feed = MT5DataFeed()
            else:
                logger.warning("MT5 terminal unavailable. Using PaperBroker for safe paper trading.")
                self.broker = PaperBroker()
                self.data_feed = PaperDataFeed()
        else:
            self.broker = PaperBroker()
            self.data_feed = PaperDataFeed()

        self.is_running = False

    def step(self) -> dict[str, Any]:
        """Execute a single evaluation step.
        
        1. Checks account and 20% daily drawdown.
        2. Liquidates if circuit breaker tripped.
        3. Scans 5-minute candles for Bullish / Bearish Engulfing.
        4. Calculates sizing strictly <= 10% balance risk with 20% profit target per order.
        5. Executes twin orders / scaled orders up to 10 max.
        """
        balance, equity = self.broker.get_account_state()
        now = datetime.now(timezone.utc)

        # 1. Hard Daily Drawdown Check (20% Limit)
        breached, dd_pct, dd_msg = self.risk_manager.check_daily_drawdown(balance, equity, now)
        if breached:
            closed_count = self.broker.close_all_positions(self.config.symbol)
            event_payload = {
                "balance": balance,
                "equity": equity,
                "day_start_balance": self.risk_manager.day_start_balance,
                "drawdown_pct": round(dd_pct * 100, 2),
                "closed_positions_count": closed_count,
                "reason": dd_msg,
            }
            self.trace_store.add_trace("CIRCUIT_BREAKER_TRIGGERED", event_payload, symbol=self.config.symbol, recorded_at=now)
            logger.critical("EMERGENCY EXIT: %s. Closed %d positions.", dd_msg, closed_count)
            return {
                "status": "CIRCUIT_BREAKER_TRIPPED",
                "details": event_payload,
            }

        # 2. Get Open Positions
        open_positions = self.broker.get_open_positions(self.config.symbol)
        active_risk_usd = self.risk_manager.calculate_active_risk(open_positions)
        active_risk_pct = (active_risk_usd / balance * 100.0) if balance > 0 else 0.0

        # If already at max 10 orders or risk budget full, skip entries
        if len(open_positions) >= self.config.max_active_orders:
            return {
                "status": "MAX_ORDERS_REACHED",
                "active_orders": len(open_positions),
                "active_risk_usd": round(active_risk_usd, 2),
                "active_risk_pct": round(active_risk_pct, 2),
            }

        # 3. Fetch latest completed 5-minute candles
        candles = self.data_feed.get_latest_candles(self.config.symbol, count=15)
        if len(candles) < 2:
            return {
                "status": "WAITING_FOR_DATA",
                "candles_available": len(candles),
            }

        # 4. Strategy evaluation
        signal = self.strategy.evaluate(candles, self.config.symbol)
        if signal is None:
            return {
                "status": "NO_SIGNAL",
                "last_candle_time": candles[-1].time.isoformat() if candles else None,
                "active_orders": len(open_positions),
                "active_risk_usd": round(active_risk_usd, 2),
                "active_risk_pct": round(active_risk_pct, 2),
            }

        # 5. Risk Assessment & Position Sizing
        sym_props = self.broker.get_symbol_properties(self.config.symbol)
        risk_result = self.risk_manager.evaluate_new_order_setup(
            balance=balance,
            equity=equity,
            open_positions=open_positions,
            signal_type=signal.signal_type,
            entry_price=signal.entry_price,
            stop_loss=signal.suggested_sl,
            contract_size=sym_props.get("contract_size", self.config.default_contract_size),
            min_lot=sym_props.get("min_lot", 0.01),
            max_lot=sym_props.get("max_lot", 100.0),
            lot_step=sym_props.get("lot_step", 0.01),
            current_time=now,
        )

        if not risk_result.is_allowed or risk_result.plan is None:
            logger.warning("Trade rejected by RiskManager: %s", risk_result.reason)
            self.trace_store.add_trace(
                "TRADE_REJECTED",
                {"signal": signal.signal_type.value, "reason": risk_result.reason, "balance": balance},
                symbol=self.config.symbol,
                recorded_at=now,
            )
            return {
                "status": "RISK_REJECTED",
                "reason": risk_result.reason,
            }

        plan = risk_result.plan
        placed_tickets: list[int] = []

        # 6. Execute Orders (Twin trades at beginning, up to 10 max entries)
        for i in range(plan.num_orders):
            comment = f"NAS100 #{i+1}/{plan.num_orders} {signal.signal_type.value}"
            ticket = self.broker.place_order(
                symbol=self.config.symbol,
                signal_type=signal.signal_type,
                lots=plan.lots_per_order,
                price=plan.entry_price,
                sl=plan.stop_loss,
                tp=plan.take_profit,
                comment=comment,
            )
            if ticket > 0:
                placed_tickets.append(ticket)
                self.trace_store.add_trace(
                    "ORDER_PLACED",
                    {
                        "ticket": ticket,
                        "order_index": i + 1,
                        "symbol": self.config.symbol,
                        "type": signal.signal_type.value,
                        "lots": plan.lots_per_order,
                        "entry": plan.entry_price,
                        "sl": plan.stop_loss,
                        "tp": plan.take_profit,
                        "risk_usd": plan.risk_per_order_usd,
                        "target_profit_usd": plan.target_profit_per_order_usd,
                    },
                    symbol=self.config.symbol,
                    recorded_at=now,
                )

        summary = {
            "status": "ORDERS_EXECUTED",
            "signal": signal.signal_type.value,
            "placed_orders_count": len(placed_tickets),
            "tickets": placed_tickets,
            "lots_per_order": plan.lots_per_order,
            "sl": plan.stop_loss,
            "tp": plan.take_profit,
            "total_risk_usd": plan.total_new_risk_usd,
            "risk_pct_of_balance": round((plan.total_new_risk_usd / balance) * 100, 2),
            "target_profit_per_order_usd": plan.target_profit_per_order_usd,
            "target_profit_pct": round((plan.target_profit_per_order_usd / balance) * 100, 2),
        }

        self.trace_store.add_trace(
            "SETUP_EXECUTED",
            summary,
            symbol=self.config.symbol,
            recorded_at=now,
        )

        return summary
