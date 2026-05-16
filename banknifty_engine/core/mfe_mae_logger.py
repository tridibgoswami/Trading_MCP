# core/mfe_mae_logger.py
# ─────────────────────────────────────────────
# Tracks Maximum Favorable Excursion (MFE) and
# Maximum Adverse Excursion (MAE) for every
# signal that comes in from the Pine Script indicator.
#
# After each signal:
#   → polls LTP every 10 s for up to 60 minutes
#   → records best unrealized profit (MFE)
#   → records worst unrealized drawdown (MAE)
#   → records time-to-MFE and time-to-MAE
#   → records where in the 1-hour range the entry was
#
# Stops early when /outcome webhook is received.
# All data is stored back into the signals table
# for later analysis via get_mfe_mae_analysis.
# ─────────────────────────────────────────────

import threading
import time
import sqlite3
from datetime import datetime
from loguru import logger

from core.market_memory import MarketMemory
import config

# Angel instance injected from webhook_receiver / start_engine
_angel = None

def set_angel(angel):
    global _angel
    _angel = angel


class MFEMAELogger:

    POLL_INTERVAL_SECS = 10
    TRACK_MINUTES      = 60

    def __init__(self):
        self.memory  = MarketMemory()
        self._active = {}        # signal_id → threading.Event
        self._lock   = threading.Lock()
        self._migrate_db()

    # ─────────────────────────────────────────
    # DB MIGRATION
    # ─────────────────────────────────────────
    def _migrate_db(self):
        """Add MFE/MAE columns to existing signals table."""
        new_cols = [
            ("mfe_points",             "REAL"),
            ("mae_points",             "REAL"),
            ("mfe_time_mins",          "INTEGER"),
            ("mae_time_mins",          "INTEGER"),
            ("mfe_pct",                "REAL"),
            ("mae_pct",                "REAL"),
            ("range_position",         "REAL"),   # 0-100: where in 1-hr range
            ("tracking_duration_mins", "INTEGER"),
        ]
        conn = sqlite3.connect(config.SIGNALS_DB)
        for col_name, col_type in new_cols:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass   # column already exists
        conn.close()

    # ─────────────────────────────────────────
    # PUBLIC: START TRACKING
    # ─────────────────────────────────────────
    def start_tracking(self, signal_id: int, signal_type: str, entry_price: float):
        """
        Called immediately after a signal is logged.
        Spawns a daemon thread that polls LTP and tracks MFE/MAE.
        """
        stop_event = threading.Event()
        with self._lock:
            self._active[signal_id] = stop_event

        range_pos = self._range_position(entry_price)

        t = threading.Thread(
            target  = self._track_loop,
            args    = (signal_id, signal_type, entry_price, range_pos, stop_event),
            name    = f"mfemae-{signal_id}",
            daemon  = True,
        )
        t.start()

        logger.info(
            f"[MFE/MAE] Tracking started | id={signal_id} | "
            f"{signal_type} @ ₹{entry_price} | "
            f"range_pos={range_pos:.1f}%"
        )

    # ─────────────────────────────────────────
    # PUBLIC: STOP TRACKING EARLY
    # ─────────────────────────────────────────
    def stop_tracking(self, signal_id: int):
        """
        Call this when the trade outcome is logged so the tracker
        finalises immediately rather than running the full 60 minutes.
        """
        with self._lock:
            ev = self._active.get(signal_id)
        if ev:
            ev.set()
            logger.debug(f"[MFE/MAE] Tracking stopped early | id={signal_id}")

    # ─────────────────────────────────────────
    # BACKGROUND POLL LOOP
    # ─────────────────────────────────────────
    def _track_loop(self, signal_id, signal_type, entry_price,
                    range_pos, stop_event):
        mfe_pts  = 0.0
        mae_pts  = 0.0
        mfe_time = 0       # minutes from entry when MFE was hit
        mae_time = 0       # minutes from entry when MAE was hit
        elapsed  = 0       # seconds elapsed

        is_buy = signal_type in ("BUY", "EXIT_SHORT")
        limit  = self.TRACK_MINUTES * 60

        while not stop_event.is_set() and elapsed < limit:
            time.sleep(self.POLL_INTERVAL_SECS)
            elapsed += self.POLL_INTERVAL_SECS

            ltp = self._get_ltp()
            if ltp is None:
                continue

            mins = elapsed / 60

            # Excursion in our direction (positive = favorable)
            move = (ltp - entry_price) if is_buy else (entry_price - ltp)

            # MFE — best move in our direction
            if move > mfe_pts:
                mfe_pts  = move
                mfe_time = int(mins)

            # MAE — worst move against us (stored as positive number)
            adverse = -move
            if adverse > mae_pts:
                mae_pts  = adverse
                mae_time = int(mins)

        # Save to DB
        tracked_mins = int(elapsed / 60)
        self._save(
            signal_id    = signal_id,
            entry_price  = entry_price,
            mfe_pts      = mfe_pts,
            mae_pts      = mae_pts,
            mfe_time     = mfe_time,
            mae_time     = mae_time,
            range_pos    = range_pos,
            tracked_mins = tracked_mins,
        )

        with self._lock:
            self._active.pop(signal_id, None)

    # ─────────────────────────────────────────
    # SAVE RESULTS
    # ─────────────────────────────────────────
    def _save(self, signal_id, entry_price, mfe_pts, mae_pts,
              mfe_time, mae_time, range_pos, tracked_mins):
        mfe_pct = round(mfe_pts / entry_price * 100, 4) if entry_price else 0
        mae_pct = round(mae_pts / entry_price * 100, 4) if entry_price else 0

        conn = sqlite3.connect(config.SIGNALS_DB)
        conn.execute("""
            UPDATE signals SET
                mfe_points             = ?,
                mae_points             = ?,
                mfe_time_mins          = ?,
                mae_time_mins          = ?,
                mfe_pct                = ?,
                mae_pct                = ?,
                range_position         = ?,
                tracking_duration_mins = ?
            WHERE id = ?
        """, (
            round(mfe_pts, 2),
            round(mae_pts, 2),
            mfe_time,
            mae_time,
            mfe_pct,
            mae_pct,
            round(range_pos, 1) if range_pos is not None else None,
            tracked_mins,
            signal_id,
        ))
        conn.commit()
        conn.close()

        logger.success(
            f"[MFE/MAE] Saved | id={signal_id} | "
            f"MFE={mfe_pts:.1f}pts @{mfe_time}min | "
            f"MAE={mae_pts:.1f}pts @{mae_time}min | "
            f"tracked={tracked_mins}min"
        )

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _get_ltp(self) -> float | None:
        """Fetch current BankNifty LTP from AngelOne."""
        global _angel
        if _angel is None:
            return None
        try:
            if not _angel.is_connected:
                _angel.login()
            ltp = _angel.get_ltp(
                exchange = config.EXCHANGE,
                symbol   = config.BANKNIFTY_SYMBOL,
                token    = config.BANKNIFTY_TOKEN,
            )
            return ltp if ltp and ltp > 0 else None
        except Exception as e:
            logger.debug(f"[MFE/MAE] LTP fetch error: {e}")
            return None

    def _range_position(self, price: float) -> float:
        """
        Where is this entry price within the last 12 × 5-min candles (1 hour)?
        Returns 0–100.  0 = at the bottom of the range, 100 = at the top.
        A reading > 80 or < 20 is "near an extreme" — the key hypothesis to test.
        """
        try:
            df = self.memory.get_recent_candles(12)
            if df.empty:
                return 50.0
            high = df["high"].max()
            low  = df["low"].min()
            if high == low:
                return 50.0
            pos = (price - low) / (high - low) * 100
            return round(max(0.0, min(100.0, pos)), 1)
        except Exception:
            return 50.0

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
