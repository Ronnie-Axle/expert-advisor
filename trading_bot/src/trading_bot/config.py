"""Configuration loading and validation for the NAS100 scalping bot."""

import os
from typing import Literal
from pydantic import BaseModel, Field


class BotConfig(BaseModel):
    """Trading Bot parameters and risk controls."""

    # Instrument and Timeframe
    symbol: str = Field(default="NAS100", description="Target index or CFD symbol (e.g., NAS100, US100, USTEC)")
    symbol_aliases: list[str] = Field(
        default_factory=lambda: ["NAS100", "US100", "USTEC", "NDX", "NAS100USD", "US100.cash", "NAS100.cash", "US100Cash"],
        description="Candidate symbols to check on broker",
    )
    timeframe: str = Field(default="M5", description="Strategy timeframe: M5 (5 minutes)")

    # Scalping & Order Execution rules
    initial_orders_count: int = Field(default=2, ge=1, le=10, description="Number of orders to open on initial entry signal")
    max_active_orders: int = Field(default=10, ge=1, le=50, description="Maximum concurrent active orders")
    
    # Risk Management rules
    max_total_risk_pct: float = Field(
        default=0.10, ge=0.01, le=1.0, description="Maximum total risk allowed across all open orders (10% of account balance)"
    )
    profit_target_pct_per_order: float = Field(
        default=0.20, ge=0.01, le=5.0, description="Take profit target per order as percentage of account balance (20%)"
    )
    daily_drawdown_limit_pct: float = Field(
        default=0.20, ge=0.01, le=1.0, description="Max daily drawdown limit (20% of starting balance) before trading stops"
    )

    # Price / Stop Loss buffers
    sl_buffer_points: float = Field(default=5.0, ge=0.0, description="Buffer in points placed beyond the engulfing candle extreme")
    min_sl_distance_points: float = Field(default=10.0, ge=1.0, description="Minimum SL distance in index points to prevent ultra-tight stops")
    default_contract_size: float = Field(default=1.0, gt=0.0, description="Fallback contract size if not queried from broker")

    # Execution Mode
    mode: Literal["paper", "mt5"] = Field(
        default="paper", description="Execution mode: 'paper' (simulated) or 'mt5' (MetaTrader 5 live/demo)"
    )
    magic_number: int = Field(default=100500, description="Unique Magic Number for EA/Bot identification")
    database_url: str | None = Field(default=None, description="PostgreSQL or SQLite connection string / path")
    db_path: str = Field(default="data/traces.sqlite3", description="Path or URL to trace store")
    poll_interval_seconds: float = Field(default=3.0, ge=0.5, le=60.0, description="Polling interval in seconds")

    # MT5 Terminal Credentials (optional, uses currently logged in MT5 terminal if omitted)
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Instantiate config reading from environment variables with sensible defaults."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        mode_env = os.getenv("TRADING_BOT_MODE", "paper").lower()
        mode: Literal["paper", "mt5"] = "mt5" if mode_env == "mt5" else "paper"

        mt5_login_raw = os.getenv("MT5_LOGIN")
        mt5_login = int(mt5_login_raw) if mt5_login_raw and mt5_login_raw.isdigit() else None
        db_conn = os.getenv("DATABASE_URL") or os.getenv("TRADING_BOT_DB_PATH", "data/traces.sqlite3")

        return cls(
            symbol=os.getenv("TRADING_BOT_SYMBOL", "NAS100"),
            timeframe=os.getenv("TRADING_BOT_TIMEFRAME", "M5"),
            initial_orders_count=int(os.getenv("INITIAL_ORDERS_COUNT", "2")),
            max_active_orders=int(os.getenv("MAX_ACTIVE_ORDERS", "10")),
            max_total_risk_pct=float(os.getenv("MAX_TOTAL_RISK_PCT", "0.10")),
            profit_target_pct_per_order=float(os.getenv("PROFIT_TARGET_PCT_PER_ORDER", "0.20")),
            daily_drawdown_limit_pct=float(os.getenv("DAILY_DRAWDOWN_LIMIT_PCT", "0.20")),
            sl_buffer_points=float(os.getenv("SL_BUFFER_POINTS", "5.0")),
            min_sl_distance_points=float(os.getenv("MIN_SL_DISTANCE_POINTS", "10.0")),
            mode=mode,
            magic_number=int(os.getenv("MAGIC_NUMBER", "100500")),
            database_url=db_conn,
            db_path=db_conn,
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "3.0")),
            mt5_login=mt5_login,
            mt5_password=os.getenv("MT5_PASSWORD"),
            mt5_server=os.getenv("MT5_SERVER"),
            mt5_path=os.getenv("MT5_PATH"),
        )
