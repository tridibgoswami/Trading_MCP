#!/usr/bin/env python3
# start_engine.py
# ─────────────────────────────────────────────
# ONE COMMAND to start the entire trading engine
# python start_engine.py
# ─────────────────────────────────────────────

import sys
import time
import subprocess
import threading
from datetime import datetime
from loguru import logger

# ── Configure logging
logger.remove()
logger.add(sys.stdout, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/engine_{time:YYYY-MM-DD}.log", rotation="1 day",
           retention="30 days", level="DEBUG")


def print_banner():
    print("""
╔════════════════════════════════════════════════════╗
║       BANKNIFTY SELF-EVOLVING TRADING ENGINE       ║
║           Powered by Claude AI + MCP               ║
╠════════════════════════════════════════════════════╣
║  Mode    : {}                               ║
║  Started : {}                     ║
╚════════════════════════════════════════════════════╝
""".format(
        "📄 PAPER TRADE" if True else "⚡ LIVE TRADE",
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ))


def check_environment():
    """Validate all requirements before starting"""
    logger.info("Checking environment...")

    # Check .env file
    import os
    if not os.path.exists('.env'):
        logger.error(".env file not found!")
        logger.error("Run: cp .env.example .env  and fill in your credentials")
        return False

    # Validate config
    try:
        from config import validate_config
        validate_config()
        logger.success("Config validated ✓")
    except EnvironmentError as e:
        logger.error(f"Config error: {e}")
        return False

    # Check DB directories
    from config import DATA_DIR, LOG_DIR, REPORT_DIR
    logger.success(f"Data directory: {DATA_DIR} ✓")

    return True


def start_mcp_server():
    """Start MCP server in background thread"""
    logger.info("Starting MCP Server...")
    try:
        import asyncio
        from mcp_server import main as mcp_main
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mcp_main())
    except Exception as e:
        logger.error(f"MCP Server error: {e}")


def start_webhook_server():
    """Start TradingView webhook receiver"""
    logger.info("Starting Webhook Receiver...")
    try:
        from core.webhook_receiver import start as webhook_start
        from core.live_analyzer import LiveAnalyzer
        from core import webhook_receiver
        import config

        live = LiveAnalyzer()
        webhook_receiver.set_live_analyzer(live)
        webhook_start(port=config.WEBHOOK_PORT)
        logger.success(f"Webhook receiver started on port {config.WEBHOOK_PORT} ✓")
        logger.info(f"  TradingView webhook URL: http://<your-ip>:{config.WEBHOOK_PORT}/signal")
    except Exception as e:
        logger.error(f"Webhook server error: {e}")


def start_scheduler():
    """Start the task scheduler"""
    logger.info("Starting Scheduler...")
    try:
        from scheduler import TradingScheduler
        sched = TradingScheduler()
        sched.show_jobs()
        sched.start()
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


def initial_data_load():
    """
    First run: Load initial market data.
    Subsequent runs: Just top up latest candles.
    """
    from core.angel_connect import AngelOneConnect
    from core.market_memory import MarketMemory

    angel  = AngelOneConnect()
    memory = MarketMemory()

    total = memory.total_candles()
    logger.info(f"Market memory has {total} candles")

    if not angel.login():
        logger.error("Cannot login to AngelOne. Check credentials.")
        return False

    if total < 100:
        logger.info("First run detected — loading 30 days of history...")
        df = angel.get_historical_data(interval="FIVE_MINUTE", days=30)
        if not df.empty:
            inserted = memory.ingest_candles(df)
            logger.success(f"Initial data load: {inserted} candles stored")
        # Also load 15-min for better patterns
        df15 = angel.get_historical_data(interval="FIFTEEN_MINUTE", days=60)
        if not df15.empty:
            memory.ingest_candles(df15)
    else:
        logger.info("Loading latest candles (last 3 days)...")
        df = angel.get_historical_data(interval="FIVE_MINUTE", days=3)
        if not df.empty:
            inserted = memory.ingest_candles(df)
            logger.info(f"Updated with {inserted} new candles")

    angel.stop_live_feed()
    return True


def run_quick_analysis():
    """Run a quick pattern analysis and show current rules"""
    from core.rule_engine import RuleEngine
    from core.market_memory import MarketMemory
    from intelligence.pattern_discovery import PatternDiscovery

    rules  = RuleEngine()
    memory = MarketMemory()

    active = rules.get_active_rules()
    logger.info(f"\n📋 Active Rules: {len(active)}")
    for r in active[:5]:
        logger.info(f"  • {r['name']} | Weight: {r['weight']} | WR: {r.get('win_rate',0):.1f}%")

    df = memory.get_memory(days=7)
    if not df.empty:
        disc     = PatternDiscovery(df)
        patterns = disc.discover_profitable_conditions(min_edge=0.58)
        logger.info(f"\n🔍 Top patterns (last 7 days):")
        for p in patterns[:3]:
            logger.info(
                f"  • {', '.join(p['conditions'])} → "
                f"{p['direction']} | WR: {p['win_rate']}% | n={p['sample_size']}"
            )


def main():
    print_banner()

    # ── Validate environment
    if not check_environment():
        sys.exit(1)

    # ── Load/update market data
    logger.info("\n" + "─" * 50)
    logger.info("PHASE 1: Market Data")
    logger.info("─" * 50)
    if not initial_data_load():
        logger.warning("Could not load market data. Will retry via scheduler.")

    # ── Quick analysis
    logger.info("\n" + "─" * 50)
    logger.info("PHASE 2: Quick Analysis")
    logger.info("─" * 50)
    try:
        run_quick_analysis()
    except Exception as e:
        logger.warning(f"Quick analysis skipped: {e}")

    # ── Start MCP Server in background
    logger.info("\n" + "─" * 50)
    logger.info("PHASE 3: Starting Services")
    logger.info("─" * 50)

    webhook_thread = threading.Thread(target=start_webhook_server, daemon=True)
    webhook_thread.start()
    time.sleep(1)

    mcp_thread = threading.Thread(target=start_mcp_server, daemon=True)
    mcp_thread.start()
    logger.success("MCP Server started ✓")
    time.sleep(1)

    # ── Start scheduler (blocking)
    logger.success("All systems GO! Starting scheduler...\n")
    logger.info("Press Ctrl+C to stop the engine\n")

    try:
        start_scheduler()
    except KeyboardInterrupt:
        logger.info("\n🛑 Engine stopped by user")
        logger.info("Saving state and shutting down...")


if __name__ == "__main__":
    main()
