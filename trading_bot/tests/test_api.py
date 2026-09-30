from datetime import datetime, timezone

from fastapi.testclient import TestClient

from trading_bot.api import create_app
from trading_bot.data.trace_store import TraceStore


def test_health_and_trace_endpoints(tmp_path):
    client = TestClient(create_app(tmp_path / "traces.sqlite3"))

    assert client.get("/health").json() == {"status": "ok"}

    created = client.post(
        "/api/v1/traces",
        json={
            "event_type": " signal ",
            "symbol": "XYZ",
            "payload": {"side": "buy", "price": 100},
        },
    )
    assert created.status_code == 201
    assert created.json()["event_type"] == "signal"
    assert created.json()["symbol"] == "XYZ"
    assert created.json()["payload"] == {"side": "buy", "price": 100}

    listed = client.get("/api/v1/traces", params={"symbol": "XYZ", "limit": 1})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == created.json()["id"]


def test_trace_endpoint_validates_input_and_filters(tmp_path):
    client = TestClient(create_app(tmp_path / "traces.sqlite3"))

    assert client.post("/api/v1/traces", json={"event_type": "  "}).status_code == 422
    assert client.get("/api/v1/traces", params={"limit": 0}).status_code == 422
    assert client.get(
        "/api/v1/traces",
        params={"since": "2026-09-30T12:00:00", "until": "2026-09-30T13:00:00"},
    ).status_code == 422


def test_create_trace_returns_inserted_row_when_history_contains_future_timestamp(tmp_path):
    database_path = tmp_path / "traces.sqlite3"
    TraceStore(database_path).add_trace(
        "imported",
        {},
        recorded_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    client = TestClient(create_app(database_path))

    response = client.post("/api/v1/traces", json={"event_type": "signal"})

    assert response.status_code == 201
    assert response.json()["event_type"] == "signal"


def test_bot_management_endpoints(tmp_path):
    client = TestClient(create_app(tmp_path / "traces.sqlite3"))

    # Test status endpoint
    status_res = client.get("/api/v1/bot/status")
    assert status_res.status_code == 200
    data = status_res.json()
    assert data["symbol"] == "NAS100"
    assert data["daily_drawdown_limit_pct"] == 20.0
    assert data["max_total_risk_pct"] == 10.0
    assert data["profit_target_pct_per_order"] == 20.0
    assert data["max_active_orders"] == 10

    # Test scan-now endpoint
    scan_res = client.post("/api/v1/bot/scan-now")
    assert scan_res.status_code == 200
    assert "status" in scan_res.json()

    # Test emergency close all
    close_res = client.post("/api/v1/bot/emergency-close-all")
    assert close_res.status_code == 200
    assert close_res.json()["status"] == "success"