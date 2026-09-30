# NAS100 5-Minute Engulfing Scalper Trading Bot

An institutional-grade algorithmic trading bot designed specifically for scalping **NAS100** (NASDAQ 100 Index / US100 / USTEC) on the 5-minute timeframe with strict capital preservation and risk sizing.

## Key Features

1. **5-Minute Candlestick Engulfing Strategy (`M5`)**:
   - **Bullish Engulfing**: A confirmed green candle whose body fully engulfs the preceding red candle's body triggers a **BUY** order. Stop loss is set below the setup's lowest price minus a safety buffer.
   - **Bearish Engulfing**: A confirmed red candle whose body fully engulfs the preceding green candle's body triggers a **SELL** order. Stop loss is set above the setup's highest price plus a safety buffer.
   - Evaluates strictly on confirmed bar closures to prevent repainting.

2. **10% Account Balance Maximum Total Risk**:
   - Total cumulative risk across all open positions is strictly capped at **10% of account balance**.
   - Lot sizes are dynamically computed from Stop Loss distance:
     $$\text{Lot Size} = \frac{\text{Risk Budget (\$) }}{\text{SL Distance} \times \text{Contract Size}}$$

3. **Multiple Entries & Twin Orders**:
   - **Initial Entry**: Opens **2 orders** simultaneously on the first valid engulfing signal.
   - **Scaling In**: Can scale into subsequent signals with multiple entries up to a maximum of **10 active orders**, with total active risk mathematically bounded within the 10% balance ceiling.

4. **20% Profit Target Per Order**:
   - Take Profit (TP) for every order is dynamically placed at the price target that delivers a **20% gain on the account balance** upon execution:
     $$\text{Target Profit (\$) } = 0.20 \times \text{Balance}$$
     $$\text{Distance to TP} = \frac{\text{Target Profit (\$) }}{\text{Lot Size} \times \text{Contract Size}}$$

5. **20% Daily Drawdown Circuit Breaker**:
   - Benchmarks account balance at the start of each trading day (00:00 UTC).
   - If current equity drops by **20% or more** from the day's baseline:
     1. Automatically liquidates all open positions immediately.
     2. Engages the circuit breaker to block all new trades for the rest of the day.
     3. Emits a high-priority `CIRCUIT_BREAKER_TRIGGERED` trace event.

6. **Dual Execution Modes**:
   - **Paper / Simulation Mode (`paper`)**: Full in-memory backtesting and simulation with zero capital risk.
   - **MetaTrader 5 Mode (`mt5`)**: Native Python integration via `MetaTrader5` to execute directly on live or demo broker accounts. Auto-resolves broker symbol aliases (`NAS100`, `US100`, `USTEC`, `NDX`, `NAS100USD`, etc.).

---

## Directory Structure

```text
expert-advisor/
├── mql5/
│   └── NAS100_Engulfing_Scalper.mq5   # Native MT5 Expert Advisor script
└── trading_bot/
    ├── src/trading_bot/
    │   ├── config.py                  # Bot & risk parameters (Pydantic)
    │   ├── engine.py                  # Central trading engine & lifecycle
    │   ├── api.py                     # FastAPI REST API & bot controls
    │   ├── main.py                    # Standalone bot loop / CLI entry point
    │   ├── strategy/
    │   │   ├── base.py                # Candle, Signal, and Strategy contracts
    │   │   └── user_strategy.py       # 5M Bullish & Bearish Engulfing detector
    │   ├── risk/
    │   │   └── manager.py             # 10% risk cap, 20% TP, & 20% daily drawdown
    │   ├── execution/
    │   │   └── broker.py              # BaseBroker, PaperBroker, and MT5Broker
    │   └── data/
    │       ├── market_data.py         # MT5DataFeed & PaperDataFeed
    │       └── trace_store.py         # SQLite audit trace history
    └── tests/
        ├── test_strategy.py           # Unit tests for engulfing logic
        ├── test_risk_manager.py       # Unit tests for risk sizing & drawdown
        ├── test_engine.py             # Integration tests for execution
        ├── test_api.py                # HTTP API and bot control tests
        └── test_trace_store.py        # SQLite trace tests
```

---

## Quickstart

### 1. Run Tests

Verify all 17 unit and integration tests:

```powershell
cd trading_bot
uv run --extra test pytest
```

### 2. Run the Bot Loop (Paper Mode)

Start the automated scanner in safe simulation mode:

```powershell
uv run python -m trading_bot.main --loop --mode paper
```

### 3. Connect to Live / Demo MetaTrader 5

1. Open your MetaTrader 5 desktop terminal and log in to your account.
2. In MT5, ensure **Algo Trading** is enabled in the top toolbar.
3. In `trading_bot/.env` (copy from `.env.example`), set:
   ```env
   TRADING_BOT_MODE=mt5
   TRADING_BOT_SYMBOL=NAS100
   ```
4. Run the bot:
   ```powershell
   uv run python -m trading_bot.main --loop --mode mt5
   ```

### 4. Run the REST API

Launch FastAPI to monitor bot status and send manual triggers:

```powershell
uv run python -m trading_bot.main --api
```

- Health: `GET http://127.0.0.1:8000/health`
- Bot Status: `GET http://127.0.0.1:8000/api/v1/bot/status`
- Immediate Scan: `POST http://127.0.0.1:8000/api/v1/bot/scan-now`
- Emergency Liquidate: `POST http://127.0.0.1:8000/api/v1/bot/emergency-close-all`
- Swagger UI: `http://127.0.0.1:8000/docs`
