from datetime import datetime, timedelta, timezone

import pytest

from trading_bot.data.trace_store import TraceStore


def test_trace_store_persists_and_returns_newest_matches_chronologically(tmp_path):
    database_path = tmp_path / "history" / "traces.sqlite3"
    timestamp = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    store = TraceStore(database_path)

    first_id = store.add_trace(
        "signal", {"side": "buy", "price": 100}, symbol="XYZ", recorded_at=timestamp
    )
    store.add_trace(
        "signal", {"side": "sell"}, symbol="ABC", recorded_at=timestamp + timedelta(minutes=2)
    )
    store.add_trace(
        "order", {"status": "submitted"}, symbol="XYZ", recorded_at=timestamp + timedelta(minutes=1)
    )

    reopened_store = TraceStore(database_path)
    traces = reopened_store.get_traces(symbol="XYZ", limit=1)
    all_traces = reopened_store.get_traces()

    assert len(traces) == 1
    assert traces[0].id == first_id + 2
    assert traces[0].event_type == "order"
    assert traces[0].payload == {"status": "submitted"}
    assert traces[0].recorded_at == timestamp + timedelta(minutes=1)
    assert [trace.recorded_at for trace in all_traces] == [
        timestamp,
        timestamp + timedelta(minutes=1),
        timestamp + timedelta(minutes=2),
    ]


def test_trace_store_filters_by_type_and_time_range(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")
    timestamp = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    store.add_trace("signal", {"n": 1}, recorded_at=timestamp)
    store.add_trace("signal", {"n": 2}, recorded_at=timestamp + timedelta(minutes=1))
    store.add_trace("order", {"n": 3}, recorded_at=timestamp + timedelta(minutes=2))

    traces = store.get_traces(
        event_type="signal",
        since=timestamp + timedelta(seconds=30),
        until=timestamp + timedelta(minutes=1),
    )

    assert [trace.payload["n"] for trace in traces] == [2]


def test_trace_store_rejects_naive_timestamps_and_invalid_limits(tmp_path):
    store = TraceStore(tmp_path / "traces.sqlite3")

    with pytest.raises(ValueError, match="timezone"):
        store.add_trace("signal", {}, recorded_at=datetime(2026, 9, 30))
    with pytest.raises(ValueError, match="greater than zero"):
        store.get_traces(limit=0)


def test_trace_store_postgres_integration():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url or not db_url.startswith(("postgresql://", "postgres://")):
        pytest.skip("DATABASE_URL not configured for PostgreSQL")

    store = TraceStore(db_url)
    t = datetime.now(timezone.utc)
    trace_id = store.add_trace(
        "postgres_test_event",
        {"status": "connected", "database": "neon"},
        symbol="NAS100",
        recorded_at=t,
    )
    assert trace_id > 0

    traces = store.get_traces(event_type="postgres_test_event", symbol="NAS100", limit=1)
    assert len(traces) == 1
    assert traces[0].event_type == "postgres_test_event"
    assert traces[0].symbol == "NAS100"
    assert traces[0].payload == {"status": "connected", "database": "neon"}