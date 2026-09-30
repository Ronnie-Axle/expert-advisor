"""FastAPI application for health checks, trace-history access, and bot management."""

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from trading_bot.config import BotConfig
from trading_bot.data.trace_store import TraceRecord, TraceStore
from trading_bot.engine import TradingBotEngine


class TraceCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    symbol: str | None = Field(default=None, max_length=64)

    @field_validator("event_type")
    @classmethod
    def normalize_event_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("event_type must not be empty")
        return value


class TraceResponse(BaseModel):
    id: int
    recorded_at: datetime
    event_type: str
    symbol: str | None
    payload: dict[str, Any]

    @classmethod
    def from_record(cls, record: TraceRecord) -> "TraceResponse":
        return cls(**asdict(record))


def _get_trace_store(request: Request) -> TraceStore:
    return request.app.state.trace_store


def _get_engine(request: Request) -> TradingBotEngine:
    return request.app.state.engine


def create_app(
    database_path: str | Path | None = None,
    config: BotConfig | None = None,
) -> FastAPI:
    """Build the API app with trace store and NAS100 trading engine."""
    bot_config = config or BotConfig.from_env()
    db_target = (
        database_path
        or bot_config.database_url
        or os.getenv("DATABASE_URL")
        or os.getenv("TRADING_BOT_DB_PATH", "data/traces.sqlite3")
    )

    app = FastAPI(title="NAS100 Scalper Trading Bot API", version="0.1.0")
    app.state.trace_store = TraceStore(db_target)
    app.state.engine = TradingBotEngine(
        config=bot_config,
        trace_store=app.state.trace_store,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/bot/status")
    def get_bot_status(engine: Annotated[TradingBotEngine, Depends(_get_engine)]) -> dict[str, Any]:
        balance, equity = engine.broker.get_account_state()
        open_positions = engine.broker.get_open_positions(engine.config.symbol)
        active_risk_usd = engine.risk_manager.calculate_active_risk(open_positions)
        active_risk_pct = (active_risk_usd / balance * 100.0) if balance > 0 else 0.0
        
        dd_dollars = engine.risk_manager.day_start_balance - equity if engine.risk_manager.day_start_balance > 0 else 0.0
        dd_pct = (dd_dollars / engine.risk_manager.day_start_balance * 100.0) if engine.risk_manager.day_start_balance > 0 else 0.0

        return {
            "symbol": engine.config.symbol,
            "mode": engine.config.mode,
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "day_start_balance": round(engine.risk_manager.day_start_balance, 2),
            "current_drawdown_pct": round(dd_pct, 2),
            "daily_drawdown_limit_pct": engine.config.daily_drawdown_limit_pct * 100,
            "circuit_breaker_tripped": engine.risk_manager.circuit_breaker_tripped,
            "circuit_breaker_reason": engine.risk_manager.circuit_breaker_reason,
            "active_orders_count": len(open_positions),
            "max_active_orders": engine.config.max_active_orders,
            "active_risk_usd": round(active_risk_usd, 2),
            "active_risk_pct": round(active_risk_pct, 2),
            "max_total_risk_pct": engine.config.max_total_risk_pct * 100,
            "profit_target_pct_per_order": engine.config.profit_target_pct_per_order * 100,
            "open_positions": [asdict(p) for p in open_positions],
        }

    @app.post("/api/v1/bot/scan-now")
    def scan_now(engine: Annotated[TradingBotEngine, Depends(_get_engine)]) -> dict[str, Any]:
        """Trigger an immediate scan cycle."""
        result = engine.step()
        return result

    @app.post("/api/v1/bot/emergency-close-all")
    def emergency_close_all(engine: Annotated[TradingBotEngine, Depends(_get_engine)]) -> dict[str, Any]:
        """Liquidate all open positions for NAS100 immediately."""
        closed = engine.broker.close_all_positions(engine.config.symbol)
        now = datetime.now(timezone.utc)
        engine.trace_store.add_trace(
            "MANUAL_EMERGENCY_CLOSE",
            {"closed_count": closed},
            symbol=engine.config.symbol,
            recorded_at=now,
        )
        return {"status": "success", "closed_positions": closed}

    @app.post(
        "/api/v1/traces",
        response_model=TraceResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_trace(
        trace: TraceCreate,
        store: Annotated[TraceStore, Depends(_get_trace_store)],
    ) -> TraceResponse:
        recorded_at = datetime.now(timezone.utc)
        trace_id = store.add_trace(
            trace.event_type,
            trace.payload,
            symbol=trace.symbol,
            recorded_at=recorded_at,
        )
        return TraceResponse(
            id=trace_id,
            recorded_at=recorded_at,
            event_type=trace.event_type,
            symbol=trace.symbol,
            payload=trace.payload,
        )

    @app.get("/api/v1/traces", response_model=list[TraceResponse])
    def list_traces(
        store: Annotated[TraceStore, Depends(_get_trace_store)],
        event_type: str | None = None,
        symbol: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[TraceResponse]:
        for timestamp in (since, until):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="since and until must include a timezone",
                )
        if since is not None and until is not None and since > until:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="since must not be later than until",
            )

        records = store.get_traces(
            event_type=event_type,
            symbol=symbol,
            since=since,
            until=until,
            limit=limit,
        )
        return [TraceResponse.from_record(record) for record in records]

    return app