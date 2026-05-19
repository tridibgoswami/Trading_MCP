# scheduler.py
# ─────────────────────────────────────────────
# Automated task scheduler for the trading engine.
# Handles data ingestion, evolution cycles,
# daily reports — all on schedule.
# ─────────────────────────────────────────────

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from datetime import datetime

from core.angel_connect import AngelOneConnect
from core.market_memory import MarketMemory
from intelligence.evolution_engine import EvolutionEngine
from signal_logger import SignalLogger
from telegram_notifier import TelegramNotifier
import config


class TradingScheduler:

    def __init__(self):
        self.scheduler = BlockingScheduler(timezone="Asia/Kolkata")
        self.angel     = AngelOneConnect()
        self.memory    = MarketMemory()
        self.engine    = EvolutionEngine()
        self.sig_log   = SignalLogger()
        self.telegram  = TelegramNotifier()
        self._setup_jobs()

    def _setup_jobs(self):

        # ── 1. Login to AngelOne daily at 9:00 AM
        self.scheduler.add_job(
            func    = self.morning_login,
            trigger = CronTrigger(day_of_week='mon-fri', hour=9, minute=0,
                                  timezone="Asia/Kolkata"),
            id      = 'morning_login',
            name    = 'Morning Login'
        )

        # ── 2. Ingest latest candles every 5 minutes during market hours
        self.scheduler.add_job(
            func    = self.ingest_candles,
            trigger = CronTrigger(day_of_week='mon-fri',
                                  hour='9-15', minute='*/5',
                                  timezone="Asia/Kolkata"),
            id      = 'ingest_candles',
            name    = 'Candle Ingestion'
        )

        # ── 3. EOD data fetch at 3:45 PM
        self.scheduler.add_job(
            func    = self.eod_ingest,
            trigger = CronTrigger(day_of_week='mon-fri', hour=15, minute=45,
                                  timezone="Asia/Kolkata"),
            id      = 'eod_ingest',
            name    = 'EOD Data Fetch'
        )

        # ── 4. Daily report at 4:00 PM
        self.scheduler.add_job(
            func    = self.send_daily_report,
            trigger = CronTrigger(day_of_week='mon-fri', hour=16, minute=0,
                                  timezone="Asia/Kolkata"),
            id      = 'daily_report',
            name    = 'Daily Report'
        )

        # ── 5. Weekly evolution — Sunday 8:00 AM
        self.scheduler.add_job(
            func    = self.run_weekly_evolution,
            trigger = CronTrigger(day_of_week='sun', hour=8, minute=0,
                                  timezone="Asia/Kolkata"),
            id      = 'weekly_evolution',
            name    = 'Weekly Evolution'
        )

        # ── 6. Bi-weekly evolution — Sunday 8:30 AM every 2nd week
        self.scheduler.add_job(
            func    = lambda: self.run_evolution(days=30),
            trigger = CronTrigger(day_of_week='sun', hour=8, minute=30,
                                  week='*/2',
                                  timezone="Asia/Kolkata"),
            id      = 'monthly_evolution',
            name    = 'Monthly Evolution (30 days)'
        )

        # ── 7. Expiry day special analysis (Thursday)
        self.scheduler.add_job(
            func    = self.expiry_day_analysis,
            trigger = CronTrigger(day_of_week='thu', hour=9, minute=10,
                                  timezone="Asia/Kolkata"),
            id      = 'expiry_analysis',
            name    = 'Expiry Day Analysis'
        )

        logger.info("All scheduled jobs configured")

    # ─────────────────────────────────────────
    # JOB FUNCTIONS
    # ─────────────────────────────────────────

    def morning_login(self):
        logger.info("⏰ Morning login starting...")
        if self.angel.login():
            self.telegram.system_status("✅ AngelOne login successful. Market hours: 9:15 AM - 3:30 PM")
        else:
            self.telegram.error_alert("❌ AngelOne login failed! Check credentials.")

    def ingest_candles(self):
        """Fetch and store latest candles for all three timeframes."""
        try:
            if not self.angel.is_connected:
                self.angel.login()
            for tf_key, tf_api in [("3min", "THREE_MINUTE"), ("5min", "FIVE_MINUTE"), ("15min", "FIFTEEN_MINUTE")]:
                df = self.angel.get_historical_data(interval=tf_api, days=2)
                if not df.empty:
                    new = self.memory.ingest_candles(df, timeframe=tf_key)
                    if new > 0:
                        logger.debug(f"Ingested {new} new {tf_key} candles")
        except Exception as e:
            logger.error(f"Candle ingestion error: {e}")

    def eod_ingest(self):
        """End of day — fetch full history for all three timeframes."""
        logger.info("📊 EOD data ingestion starting...")
        try:
            if not self.angel.is_connected:
                self.angel.login()
            ingests = [
                ("3min",  "THREE_MINUTE",   3),
                ("5min",  "FIVE_MINUTE",    3),
                ("15min", "FIFTEEN_MINUTE", 30),
            ]
            for tf_key, tf_api, days in ingests:
                df = self.angel.get_historical_data(interval=tf_api, days=days)
                if not df.empty:
                    self.memory.ingest_candles(df, timeframe=tf_key)
            logger.success("EOD ingestion complete — all timeframes updated")
        except Exception as e:
            logger.error(f"EOD ingestion error: {e}")
            self.telegram.error_alert(f"EOD ingest failed: {e}")

    def send_daily_report(self):
        """Send end-of-day trading summary to Telegram"""
        try:
            summary = self.sig_log.daily_summary()
            self.telegram.daily_report(summary)
            logger.info(f"Daily report sent: {summary}")
        except Exception as e:
            logger.error(f"Daily report error: {e}")

    def run_weekly_evolution(self):
        self.run_evolution(days=14)

    def run_evolution(self, days: int = 14):
        """Run the AI evolution cycle"""
        logger.info(f"🧠 Evolution cycle starting ({days} days)...")
        self.telegram.system_status(f"🧠 Starting evolution cycle ({days} days)...")
        try:
            result = self.engine.evolve(lookback_days=days)
            if 'error' not in result:
                logger.success(f"Evolution complete: {result['stats']}")
            else:
                logger.warning(f"Evolution issue: {result}")
        except Exception as e:
            logger.error(f"Evolution error: {e}")
            self.telegram.error_alert(f"Evolution failed: {e}")

    def expiry_day_analysis(self):
        """Special analysis on Bank Nifty expiry (Thursday)"""
        try:
            df   = self.memory.get_memory(days=30)
            if df.empty:
                return
            # Filter only Thursday data
            thu  = df[df['day_of_week'] == 'Thursday']
            if len(thu) < 10:
                return
            win_open = thu[thu['market_session'] == 'OPENING']['next_10_move'].mean()
            win_mid  = thu[thu['market_session'] == 'MID_SESSION']['next_10_move'].mean()
            win_clos = thu[thu['market_session'] == 'CLOSING']['next_10_move'].mean()
            msg = (
                f"📅 <b>EXPIRY DAY ANALYSIS (Thursday)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Opening avg move  : {win_open:+.3f}%\n"
                f"Mid-session move  : {win_mid:+.3f}%\n"
                f"Closing avg move  : {win_clos:+.3f}%\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Trade carefully on expiry day!"
            )
            self.telegram.send(msg)
        except Exception as e:
            logger.error(f"Expiry analysis error: {e}")

    # ─────────────────────────────────────────
    # START / STOP
    # ─────────────────────────────────────────
    def start(self):
        logger.info("🚀 Scheduler starting...")
        try:
            self.scheduler.start()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            self.scheduler.shutdown()

    def show_jobs(self):
        print("\n📋 Scheduled Jobs:")
        print("─" * 60)
        for job in self.scheduler.get_jobs():
            print(f"  {job.name:30s} | Next: {job.next_run_time}")
        print("─" * 60)


if __name__ == "__main__":
    sched = TradingScheduler()
    sched.show_jobs()
    sched.start()
