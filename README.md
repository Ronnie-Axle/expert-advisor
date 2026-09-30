# NAS100 5-Minute Engulfing Scalper (Expert Advisor & Python Bot)

A high-performance algorithmic trading system for scalping **NAS100 / US100 / USTEC** on the 5-minute timeframe.

## Core Rules & Risk Architecture

| Parameter                 | Value            | Description                                                                                 |
| :------------------------ | :--------------- | :------------------------------------------------------------------------------------------ |
| **Instrument**            | `NAS100`         | Supports broker aliases: `US100`, `USTEC`, `NDX`, `NAS100USD`, `NAS100.cash`                |
| **Timeframe**             | `M5` (5 Minutes) | Evaluates on completed 5-minute candle closures (no repainting)                             |
| **Entry Pattern**         | Engulfing        | **Bullish Engulfing** $\rightarrow$ **BUY**<br>**Bearish Engulfing** $\rightarrow$ **SELL** |
| **Initial Setup**         | 2 Orders         | Enters with 2 simultaneous orders on the initial setup                                      |
| **Max Concurrent Orders** | 10 Orders        | Can scale up to 10 active entries as signals occur                                          |
| **Total Risk Ceiling**    | 10% of Balance   | Cumulative dollar risk across **all** active trades $\le$ 10% of balance                    |
| **Profit Target (TP)**    | 20% per Order    | Take Profit is dynamically calculated to capture 20% account balance gain per order         |
| **Daily Drawdown Limit**  | 20% Hard Stop    | If daily equity drops $\ge$ 20% from start of day: closes all trades & halts trading        |

---

## What is Included

1. **Python Trading Bot (`trading_bot/`)**:
   - Modern Python 3.11+ / 3.14 architecture with `uv`.
   - Dual execution engine: **Paper simulation** mode and **MetaTrader 5 live/demo** mode via `MetaTrader5` library.
   - FastAPI REST API for live monitoring, Swagger UI, and remote management.
   - Comprehensive test suite (17 unit and integration tests passing).

2. **Native MQL5 Expert Advisor (`mql5/NAS100_Engulfing_Scalper.mq5`)**:
   - For direct execution in the MetaTrader 5 terminal.
   - Compile in MetaEditor, drag onto the NAS100 M5 chart, and let it trade with on-chart HUD dashboard.

---

## Usage

### Flutter Dashboard

The Flutter control dashboard is in `flutter_app/`. It connects to the FastAPI service for account state, open positions, persistent database-backed traces, manual scans, and emergency close. See [`flutter_app/README.md`](flutter_app/README.md) for setup and device-specific API addresses. The backend remains the sole owner of the configured SQLite or PostgreSQL database.

### Option A: Python Bot

```powershell
cd trading_bot

# 1. Run automated test suite
uv run --extra test pytest

# 2. Run in Paper Mode (Simulation)
uv run python -m trading_bot.main --loop --mode paper

# 3. Run in Live / Demo MetaTrader 5 Mode
uv run python -m trading_bot.main --loop --mode mt5

# 4. Run REST API (FastAPI + Swagger docs at http://127.0.0.1:8000/docs)
uv run python -m trading_bot.main --api
```

### Option B: MetaTrader 5 Expert Advisor (.mq5)

1. Open MetaTrader 5 and open MetaEditor (`F4`).
2. Copy `mql5/NAS100_Engulfing_Scalper.mq5` into your MT5 `MQL5/Experts/` folder.
3. Click **Compile** (`F7`).
4. In MT5, open the `NAS100` (or `US100`) chart and set the timeframe to **M5**.
5. Drag `NAS100_Engulfing_Scalper` onto the chart, check **Allow Algo Trading**, and press OK.
