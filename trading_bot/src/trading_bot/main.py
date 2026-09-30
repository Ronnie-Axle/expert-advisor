"""Entry point for the NAS100 Scalper Trading Bot (API and standalone live loop)."""

import argparse
import asyncio
import logging
import os
import sys
import time

from trading_bot.api import create_app
from trading_bot.config import BotConfig
from trading_bot.engine import TradingBotEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trading_bot")

app = create_app()


def run_continuous_bot(config: BotConfig | None = None) -> None:
    """Run continuous bot scan loop."""
    cfg = config or BotConfig.from_env()
    logger.info(
        "Starting NAS100 Scalper Bot in %s mode (Symbol: %s, Max Risk: %.1f%%, Daily DD Limit: %.1f%%)",
        cfg.mode.upper(),
        cfg.symbol,
        cfg.max_total_risk_pct * 100,
        cfg.daily_drawdown_limit_pct * 100,
    )
    engine = TradingBotEngine(cfg)

    try:
        while True:
            try:
                result = engine.step()
                if result.get("status") == "CIRCUIT_BREAKER_TRIPPED":
                    logger.critical(
                        "Circuit breaker tripped! Trading locked for today. Sleeping for 60 seconds before next check..."
                    )
                    time.sleep(60)
                elif result.get("status") == "ORDERS_EXECUTED":
                    logger.info("Setup executed successfully: %s", result)
                    time.sleep(cfg.poll_interval_seconds)
                else:
                    time.sleep(cfg.poll_interval_seconds)
            except KeyboardInterrupt:
                logger.info("Bot stopped by user.")
                break
            except Exception as e:
                logger.error("Error during bot cycle: %s", e, exc_info=True)
                time.sleep(cfg.poll_interval_seconds)
    finally:
        engine.broker.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NAS100 Engulfing Scalper Trading Bot")
    parser.add_argument("--api", action="store_true", help="Launch FastAPI server")
    parser.add_argument("--loop", action="store_true", help="Launch continuous trading bot loop")
    parser.add_argument("--mode", choices=["paper", "mt5"], help="Execution mode override")
    parser.add_argument("--symbol", help="Symbol override (e.g. NAS100, US100)")
    args = parser.parse_args()

    cfg = BotConfig.from_env()
    if args.mode:
        cfg.mode = args.mode
    if args.symbol:
        cfg.symbol = args.symbol

    if args.api:
        import uvicorn
        uvicorn.run(
            "trading_bot.main:app",
            host=os.getenv("TRADING_BOT_API_HOST", "127.0.0.1"),
            port=int(os.getenv("TRADING_BOT_API_PORT", "8000")),
            reload=False,
        )
    else:
        # Default action is running the bot loop
        run_continuous_bot(cfg)
