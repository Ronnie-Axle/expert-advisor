"""Broker execution adapters: Abstract BaseBroker, PaperBroker, and MT5Broker."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from trading_bot.config import BotConfig
from trading_bot.risk.manager import PositionInfo
from trading_bot.strategy.base import SignalType

logger = logging.getLogger(__name__)


class BaseBroker(ABC):
    """Abstract execution adapter."""

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def get_account_state(self) -> tuple[float, float]:
        """Return (balance, equity)."""
        pass

    @abstractmethod
    def get_symbol_properties(self, symbol: str) -> dict[str, float]:
        """Return dict with keys: contract_size, min_lot, max_lot, lot_step, point."""
        pass

    @abstractmethod
    def get_open_positions(self, symbol: str | None = None) -> list[PositionInfo]:
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        signal_type: SignalType,
        lots: float,
        price: float,
        sl: float,
        tp: float,
        comment: str = "",
    ) -> int:
        """Execute a market order. Returns position/order ticket id (>0 if successful)."""
        pass

    @abstractmethod
    def close_position(self, ticket: int) -> bool:
        pass

    @abstractmethod
    def close_all_positions(self, symbol: str | None = None) -> int:
        """Emergency liquidate all open positions. Returns count of closed positions."""
        pass


class PaperBroker(BaseBroker):
    """High-fidelity simulated paper broker for local development and backtesting."""

    def __init__(
        self,
        initial_balance: float = 10000.0,
        contract_size: float = 1.0,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        lot_step: float = 0.01,
    ) -> None:
        self.balance: float = initial_balance
        self.equity: float = initial_balance
        self.contract_size = contract_size
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.lot_step = lot_step
        self._ticket_counter = 1000
        self.positions: dict[int, PositionInfo] = {}

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def get_account_state(self) -> tuple[float, float]:
        self._update_equity()
        return self.balance, self.equity

    def get_symbol_properties(self, symbol: str) -> dict[str, float]:
        return {
            "contract_size": self.contract_size,
            "min_lot": self.min_lot,
            "max_lot": self.max_lot,
            "lot_step": self.lot_step,
            "point": 0.01,
        }

    def get_open_positions(self, symbol: str | None = None) -> list[PositionInfo]:
        if symbol is None:
            return list(self.positions.values())
        return [p for p in self.positions.values() if p.symbol.upper() == symbol.upper()]

    def place_order(
        self,
        symbol: str,
        signal_type: SignalType,
        lots: float,
        price: float,
        sl: float,
        tp: float,
        comment: str = "",
    ) -> int:
        self._ticket_counter += 1
        ticket = self._ticket_counter
        pos = PositionInfo(
            ticket=ticket,
            symbol=symbol,
            order_type=signal_type,
            lots=lots,
            open_price=price,
            sl=sl,
            tp=tp,
            current_profit=0.0,
        )
        self.positions[ticket] = pos
        logger.info(
            "[PAPER BROKER] Opened %s #%d: %.2f lots @ %.2f (SL=%.2f, TP=%.2f) - %s",
            signal_type.value, ticket, lots, price, sl, tp, comment
        )
        return ticket

    def close_position(self, ticket: int) -> bool:
        if ticket in self.positions:
            pos = self.positions.pop(ticket)
            self.balance += pos.current_profit
            self._update_equity()
            logger.info("[PAPER BROKER] Closed #%d with PnL $%.2f", ticket, pos.current_profit)
            return True
        return False

    def close_all_positions(self, symbol: str | None = None) -> int:
        targets = [t for t, p in self.positions.items() if symbol is None or p.symbol.upper() == symbol.upper()]
        closed = 0
        for ticket in targets:
            if self.close_position(ticket):
                closed += 1
        return closed

    def update_market_price(self, symbol: str, current_price: float) -> list[int]:
        """Update floating profit and check SL/TP for open positions. Returns triggered tickets."""
        closed_tickets: list[int] = []
        for ticket, pos in list(self.positions.items()):
            if pos.symbol.upper() != symbol.upper():
                continue

            if pos.order_type == SignalType.BUY:
                pos.current_profit = pos.lots * self.contract_size * (current_price - pos.open_price)
                if pos.sl > 0 and current_price <= pos.sl:
                    # SL Hit
                    pos.current_profit = pos.lots * self.contract_size * (pos.sl - pos.open_price)
                    self.close_position(ticket)
                    closed_tickets.append(ticket)
                elif pos.tp > 0 and current_price >= pos.tp:
                    # TP Hit
                    pos.current_profit = pos.lots * self.contract_size * (pos.tp - pos.open_price)
                    self.close_position(ticket)
                    closed_tickets.append(ticket)

            elif pos.order_type == SignalType.SELL:
                pos.current_profit = pos.lots * self.contract_size * (pos.open_price - current_price)
                if pos.sl > 0 and current_price >= pos.sl:
                    # SL Hit
                    pos.current_profit = pos.lots * self.contract_size * (pos.open_price - pos.sl)
                    self.close_position(ticket)
                    closed_tickets.append(ticket)
                elif pos.tp > 0 and current_price <= pos.tp:
                    # TP Hit
                    pos.current_profit = pos.lots * self.contract_size * (pos.open_price - pos.tp)
                    self.close_position(ticket)
                    closed_tickets.append(ticket)

        self._update_equity()
        return closed_tickets

    def _update_equity(self) -> None:
        floating = sum(p.current_profit for p in self.positions.values())
        self.equity = self.balance + floating


class MT5Broker(BaseBroker):
    """Direct integration with MetaTrader 5 terminal."""

    def __init__(self, config: BotConfig, mt5_module: Any | None = None) -> None:
        self.config = config
        self.resolved_symbol: str | None = None
        if mt5_module is not None:
            self._mt5 = mt5_module
        else:
            try:
                import MetaTrader5 as mt5
                self._mt5 = mt5
            except ImportError:
                self._mt5 = None

    def connect(self) -> bool:
        if self._mt5 is None:
            raise RuntimeError("MetaTrader5 package is not installed")

        init_args: dict[str, Any] = {}
        if self.config.mt5_path:
            init_args["path"] = self.config.mt5_path
        if self.config.mt5_login:
            init_args["login"] = self.config.mt5_login
        if self.config.mt5_password:
            init_args["password"] = self.config.mt5_password
        if self.config.mt5_server:
            init_args["server"] = self.config.mt5_server

        if not self._mt5.initialize(**init_args):
            err = self._mt5.last_error()
            logger.error("Failed to initialize MT5: %s", err)
            return False

        account = self._mt5.account_info()
        if account is None:
            logger.error("Failed to get MT5 account info: %s", self._mt5.last_error())
            return False

        logger.info("Connected to MT5 account #%d (Server: %s, Balance: $%.2f)", account.login, account.server, account.balance)
        self.resolve_symbol()
        return True

    def disconnect(self) -> None:
        if self._mt5:
            self._mt5.shutdown()

    def resolve_symbol(self) -> str:
        """Scan available symbols to find the broker's exact NAS100 ticker."""
        if self.resolved_symbol:
            return self.resolved_symbol

        candidates = [self.config.symbol] + self.config.symbol_aliases
        for sym in candidates:
            info = self._mt5.symbol_info(sym)
            if info is not None:
                if not info.visible:
                    self._mt5.symbol_select(sym, True)
                self.resolved_symbol = sym
                logger.info("Broker symbol resolved to: %s", sym)
                return sym

        logger.warning("Could not automatically resolve symbol from aliases; defaulting to %s", self.config.symbol)
        self.resolved_symbol = self.config.symbol
        return self.resolved_symbol

    def get_account_state(self) -> tuple[float, float]:
        acc = self._mt5.account_info()
        if acc is None:
            raise ConnectionError(f"Failed to fetch account info: {self._mt5.last_error()}")
        return float(acc.balance), float(acc.equity)

    def get_symbol_properties(self, symbol: str) -> dict[str, float]:
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return {
                "contract_size": self.config.default_contract_size,
                "min_lot": 0.01,
                "max_lot": 100.0,
                "lot_step": 0.01,
                "point": 0.01,
            }
        return {
            "contract_size": float(info.trade_contract_size),
            "min_lot": float(info.volume_min),
            "max_lot": float(info.volume_max),
            "lot_step": float(info.volume_step),
            "point": float(info.point),
        }

    def get_open_positions(self, symbol: str | None = None) -> list[PositionInfo]:
        sym = symbol or self.resolve_symbol()
        positions = self._mt5.positions_get(symbol=sym)
        if positions is None:
            return []

        results: list[PositionInfo] = []
        for p in positions:
            # Check magic number if matching bot's magic
            if p.magic == self.config.magic_number or self.config.magic_number == 0:
                sig_type = SignalType.BUY if p.type == self._mt5.ORDER_TYPE_BUY else SignalType.SELL
                results.append(
                    PositionInfo(
                        ticket=int(p.ticket),
                        symbol=p.symbol,
                        order_type=sig_type,
                        lots=float(p.volume),
                        open_price=float(p.price_open),
                        sl=float(p.sl),
                        tp=float(p.tp),
                        current_profit=float(p.profit),
                    )
                )
        return results

    def _determine_filling_mode(self, symbol: str) -> int:
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return self._mt5.ORDER_FILLING_IOC
        # Check filling mode flags
        filling = info.filling_mode
        if filling & 1:  # FOK
            return self._mt5.ORDER_FILLING_FOK
        elif filling & 2:  # IOC
            return self._mt5.ORDER_FILLING_IOC
        return self._mt5.ORDER_FILLING_RETURN

    def place_order(
        self,
        symbol: str,
        signal_type: SignalType,
        lots: float,
        price: float,
        sl: float,
        tp: float,
        comment: str = "",
    ) -> int:
        sym = self.resolve_symbol()
        order_type = self._mt5.ORDER_TYPE_BUY if signal_type == SignalType.BUY else self._mt5.ORDER_TYPE_SELL
        filling_mode = self._determine_filling_mode(sym)

        # Get fresh ask/bid for market execution
        tick = self._mt5.symbol_info_tick(sym)
        exec_price = tick.ask if signal_type == SignalType.BUY else tick.bid

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(lots),
            "type": order_type,
            "price": float(exec_price),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": comment or "NAS100 Engulfing Scalper",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = self._mt5.order_send(request)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            err_msg = f"Order failed: retcode={getattr(result, 'retcode', 'None')} comment={getattr(result, 'comment', 'None')}"
            logger.error("[%s] %s (last error: %s)", sym, err_msg, self._mt5.last_error())
            return 0

        logger.info("[%s] MT5 Order opened successfully: deal=%d, order=%d", sym, result.deal, result.order)
        return int(result.order)

    def close_position(self, ticket: int) -> bool:
        positions = self._mt5.positions_get(ticket=ticket)
        if not positions or len(positions) == 0:
            return False

        pos = positions[0]
        sym = pos.symbol
        tick = self._mt5.symbol_info_tick(sym)
        opposite_type = self._mt5.ORDER_TYPE_SELL if pos.type == self._mt5.ORDER_TYPE_BUY else self._mt5.ORDER_TYPE_BUY
        price = tick.bid if opposite_type == self._mt5.ORDER_TYPE_SELL else tick.ask
        filling_mode = self._determine_filling_mode(sym)

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": pos.volume,
            "type": opposite_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": "Circuit Breaker / Scalp Exit",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = self._mt5.order_send(request)
        return result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE

    def close_all_positions(self, symbol: str | None = None) -> int:
        positions = self.get_open_positions(symbol)
        closed_count = 0
        for pos in positions:
            if self.close_position(pos.ticket):
                closed_count += 1
        logger.warning("Closed %d open positions in emergency liquidation", closed_count)
        return closed_count
