"""Storage layer for append-only bot trace history supporting PostgreSQL (Neon) and SQLite."""

import json
import logging
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


def normalize_postgres_url(url: str) -> str:
    """Sanitize PostgreSQL URLs for cloud poolers (e.g. Neon PgBouncer).
    
    Removes channel_binding which can trigger TLS negotiation resets with poolers.
    """
    try:
        parsed = urlparse(url)
        if not parsed.scheme.startswith(("postgres", "postgresql")):
            return url
        params = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() != "channel_binding"]
        new_query = urlencode(params)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


@dataclass(frozen=True)
class TraceRecord:
    """A trace event read from the database."""

    id: int
    recorded_at: datetime
    event_type: str
    symbol: str | None
    payload: dict[str, object]


class TraceStore:
    """Append and query trace events in PostgreSQL or SQLite."""

    def __init__(self, location: str | Path) -> None:
        self.raw_location = str(location)
        self.is_postgres = self.raw_location.startswith(("postgresql://", "postgres://"))
        self._pg_conn = None

        if self.is_postgres:
            self.database_url = normalize_postgres_url(self.raw_location)
            try:
                import psycopg
                self._psycopg = psycopg
            except ImportError as e:
                raise ImportError(
                    "psycopg is required for PostgreSQL connections: install via `uv add 'psycopg[binary]'`"
                ) from e

            # Initialize schema in PostgreSQL
            with self._get_postgres_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS trace_history (
                            id SERIAL PRIMARY KEY,
                            recorded_at TIMESTAMPTZ NOT NULL,
                            event_type VARCHAR(128) NOT NULL,
                            symbol VARCHAR(64),
                            payload JSONB NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS idx_trace_history_recorded_at ON trace_history(recorded_at);
                        CREATE INDEX IF NOT EXISTS idx_trace_history_event_type ON trace_history(event_type);
                        CREATE INDEX IF NOT EXISTS idx_trace_history_symbol ON trace_history(symbol);
                        """
                    )
                conn.commit()
            logger.info("TraceStore connected to PostgreSQL database at %s", urlparse(self.database_url).netloc)
        else:
            self.database_path = Path(location)
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS trace_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            recorded_at TEXT NOT NULL,
                            event_type TEXT NOT NULL,
                            symbol TEXT,
                            payload TEXT NOT NULL
                        )
                        """
                    )
            logger.info("TraceStore initialized with SQLite backend at %s", self.database_path)

    def _get_postgres_connection(self) -> Any:
        """Provide an active connection to PostgreSQL, reconnecting if needed."""
        if self._pg_conn is None or self._pg_conn.closed:
            self._pg_conn = self._psycopg.connect(self.database_url)
        return self._pg_conn

    def add_trace(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        symbol: str | None = None,
        recorded_at: datetime | None = None,
    ) -> int:
        """Append an event and return its database ID."""
        if not event_type.strip():
            raise ValueError("event_type must not be empty")

        timestamp = recorded_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        timestamp = timestamp.astimezone(timezone.utc)

        if self.is_postgres:
            payload_json = json.dumps(dict(payload))
            conn = self._get_postgres_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trace_history (recorded_at, event_type, symbol, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (timestamp, event_type, symbol, payload_json),
                )
                row = cursor.fetchone()
                inserted_id = int(row[0])
            conn.commit()
            return inserted_id
        else:
            payload_json = json.dumps(dict(payload), separators=(",", ":"))
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    cursor = connection.execute(
                        """
                        INSERT INTO trace_history (recorded_at, event_type, symbol, payload)
                        VALUES (?, ?, ?, ?)
                        """,
                        (timestamp.isoformat(), event_type, symbol, payload_json),
                    )
                    return int(cursor.lastrowid)

    def get_traces(
        self,
        *,
        event_type: str | None = None,
        symbol: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[TraceRecord]:
        """Return matching events chronologically; limit selects newest matches."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than zero")

        if self.is_postgres:
            conditions: list[str] = []
            parameters: list[Any] = []
            if event_type is not None:
                conditions.append("event_type = %s")
                parameters.append(event_type)
            if symbol is not None:
                conditions.append("symbol = %s")
                parameters.append(symbol)
            if since is not None:
                conditions.append("recorded_at >= %s")
                parameters.append(since.astimezone(timezone.utc))
            if until is not None:
                conditions.append("recorded_at <= %s")
                parameters.append(until.astimezone(timezone.utc))

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            limit_clause = " LIMIT %s" if limit is not None else ""
            if limit is not None:
                parameters.append(limit)

            order = "DESC, id DESC" if limit is not None else "ASC, id ASC"
            query = (
                "SELECT id, recorded_at, event_type, symbol, payload "
                f"FROM trace_history {where_clause} "
                f"ORDER BY recorded_at {order}{limit_clause}"
            )

            conn = self._get_postgres_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, parameters)
                rows = cursor.fetchall()

            if limit is not None:
                rows.reverse()

            results: list[TraceRecord] = []
            for row in rows:
                p_load = row[4] if isinstance(row[4], dict) else json.loads(row[4])
                rec_dt = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(row[1])
                results.append(
                    TraceRecord(
                        id=row[0],
                        recorded_at=rec_dt,
                        event_type=row[2],
                        symbol=row[3],
                        payload=p_load,
                    )
                )
            return results
        else:
            conditions = []
            param_list: list[object] = []
            if event_type is not None:
                conditions.append("event_type = ?")
                param_list.append(event_type)
            if symbol is not None:
                conditions.append("symbol = ?")
                param_list.append(symbol)
            if since is not None:
                conditions.append("recorded_at >= ?")
                param_list.append(self._format_timestamp(since))
            if until is not None:
                conditions.append("recorded_at <= ?")
                param_list.append(self._format_timestamp(until))

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            limit_clause = " LIMIT ?" if limit is not None else ""
            if limit is not None:
                param_list.append(limit)
            order = "DESC, id DESC" if limit is not None else "ASC, id ASC"
            query = (
                "SELECT id, recorded_at, event_type, symbol, payload "
                f"FROM trace_history {where_clause} "
                f"ORDER BY recorded_at {order}{limit_clause}"
            )

            with closing(sqlite3.connect(self.database_path)) as connection:
                rows = connection.execute(query, param_list).fetchall()

            if limit is not None:
                rows.reverse()
            return [
                TraceRecord(
                    id=row[0],
                    recorded_at=datetime.fromisoformat(row[1]),
                    event_type=row[2],
                    symbol=row[3],
                    payload=json.loads(row[4]),
                )
                for row in rows
            ]

    @staticmethod
    def _format_timestamp(timestamp: datetime) -> str:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return timestamp.astimezone(timezone.utc).isoformat()