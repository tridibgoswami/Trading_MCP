# signal_logger.py
# ─────────────────────────────────────────────
# Captures every signal from your indicator
# with full market context.
# ─────────────────────────────────────────────

import sqlite3
import json
from datetime import datetime
from loguru import logger
import config


class SignalLogger:

    def __init__(self, db_path: str = config.SIGNALS_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT,
                signal_type      TEXT,       -- BUY / SELL / EXIT_LONG / EXIT_SHORT
                signal_strength  REAL,       -- Your indicator value (0-100 or any scale)

                -- Price context at signal time
                price            REAL,
                high_of_day      REAL,
                low_of_day       REAL,

                -- Indicators at signal time
                rsi              REAL,
                ema_9            REAL,
                ema_21           REAL,
                above_vwap       INTEGER,    -- 1 or 0
                volume_ratio     REAL,
                atr              REAL,
                macd             REAL,
                macd_signal      REAL,

                -- Market context
                vix              REAL,
                regime           TEXT,
                market_session   TEXT,
                day_of_week      TEXT,
                trend_direction  TEXT,

                -- Trade outcome (filled after trade closes)
                entry_price      REAL,
                exit_price       REAL,
                pnl              REAL,
                pnl_pct          REAL,
                outcome          TEXT,       -- WIN / LOSS / BREAKEVEN
                holding_time     INTEGER,    -- minutes
                exit_reason      TEXT,       -- TARGET / STOPLOSS / TIME / MANUAL

                -- Metadata
                rule_triggered   TEXT,       -- which rule fired this signal
                indicator_name   TEXT,       -- which indicator sent this signal
                signal_name      TEXT,       -- specific BrahmAstra signal (e.g. S1_BUY, TREND_SELL)
                extra_context    TEXT,       -- JSON blob

                created_at       TEXT
            )
        """)
        for col in ["indicator_name TEXT", "signal_name TEXT"]:
            try:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col}")
                conn.commit()
            except Exception:
                pass  # column already exists
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    # LOG SIGNAL
    # ─────────────────────────────────────────
    def log_signal(self, data: dict) -> int:
        """
        Log a new indicator signal.
        Returns the signal ID for later outcome update.

        Required keys: type, strength, price
        Optional keys: rsi, ema_9, ema_21, above_vwap, volume_ratio,
                       atr, macd, macd_signal, vix, regime, trend_direction,
                       rule_triggered, extra
        """
        conn = sqlite3.connect(self.db_path)
        cur  = conn.execute("""
            INSERT INTO signals (
                timestamp, signal_type, signal_strength,
                price, rsi, ema_9, ema_21, above_vwap,
                volume_ratio, atr, macd, macd_signal,
                vix, regime, market_session, day_of_week, trend_direction,
                rule_triggered, indicator_name, signal_name, extra_context, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(),
            data['type'],
            data.get('strength', 0),
            data['price'],
            data.get('rsi'),
            data.get('ema_9'),
            data.get('ema_21'),
            1 if data.get('above_vwap') else 0,
            data.get('volume_ratio'),
            data.get('atr'),
            data.get('macd'),
            data.get('macd_signal'),
            data.get('vix'),
            data.get('regime'),
            self._get_session(),
            datetime.now().strftime('%A'),
            data.get('trend_direction'),
            data.get('rule_triggered'),
            data.get('indicator_name'),
            data.get('signal_name'),
            json.dumps(data.get('extra', {})),
            datetime.now().isoformat()
        ))
        signal_id = cur.lastrowid
        conn.commit()
        conn.close()

        logger.info(
            f"[SIGNAL] {data['type']} | Price: {data['price']} | "
            f"Strength: {data.get('strength', 0):.2f} | ID: {signal_id}"
        )
        return signal_id

    # ─────────────────────────────────────────
    # UPDATE OUTCOME
    # ─────────────────────────────────────────
    def update_outcome(self,
                       signal_id    : int,
                       entry_price  : float,
                       exit_price   : float,
                       holding_mins : int,
                       exit_reason  : str = "MANUAL") -> dict:
        """Update trade result after position closes"""
        pnl     = exit_price - entry_price
        pnl_pct = (pnl / entry_price) * 100
        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE signals SET
                entry_price  = ?,
                exit_price   = ?,
                pnl          = ?,
                pnl_pct      = ?,
                outcome      = ?,
                holding_time = ?,
                exit_reason  = ?
            WHERE id = ?
        """, (entry_price, exit_price, pnl, pnl_pct,
              outcome, holding_mins, exit_reason, signal_id))
        conn.commit()
        conn.close()

        logger.info(
            f"[OUTCOME] Signal {signal_id} | {outcome} | "
            f"PnL: ₹{pnl:.2f} ({pnl_pct:.2f}%) | {exit_reason}"
        )
        return {"outcome": outcome, "pnl": pnl, "pnl_pct": pnl_pct}

    # ─────────────────────────────────────────
    # QUERIES
    # ─────────────────────────────────────────
    def get_signals_with_outcomes(self, days: int = 30):
        import pandas as pd
        from datetime import timedelta
        since = (datetime.now() - timedelta(days=days)).isoformat()
        conn  = sqlite3.connect(self.db_path)
        df    = pd.read_sql(
            "SELECT * FROM signals WHERE outcome IS NOT NULL AND timestamp >= ?",
            conn, params=(since,)
        )
        conn.close()
        return df

    def get_today_signals(self):
        import pandas as pd
        today = datetime.now().strftime('%Y-%m-%d')
        conn  = sqlite3.connect(self.db_path)
        df    = pd.read_sql(
            "SELECT * FROM signals WHERE timestamp LIKE ?",
            conn, params=(f"{today}%",)
        )
        conn.close()
        return df

    def get_open_signals(self):
        """Signals without outcomes yet (open trades)"""
        import pandas as pd
        conn = sqlite3.connect(self.db_path)
        df   = pd.read_sql(
            "SELECT * FROM signals WHERE outcome IS NULL ORDER BY timestamp",
            conn
        )
        conn.close()
        return df

    def daily_summary(self) -> dict:
        """Summary of today's trading"""
        df = self.get_today_signals()
        if df.empty:
            return {"total": 0, "wins": 0, "losses": 0, "pnl": 0}
        closed = df[df['outcome'].notna()]
        return {
            "total_signals": len(df),
            "closed_trades": len(closed),
            "wins":          len(closed[closed['outcome'] == 'WIN']),
            "losses":        len(closed[closed['outcome'] == 'LOSS']),
            "total_pnl":     round(closed['pnl'].sum(), 2) if not closed.empty else 0,
            "win_rate":      round(
                len(closed[closed['outcome']=='WIN']) / max(len(closed), 1) * 100, 1
            )
        }

    def _get_session(self) -> str:
        t = datetime.now().hour * 60 + datetime.now().minute
        if   t < 555: return "PRE_OPEN"
        elif t < 630: return "OPENING"
        elif t < 840: return "MID_SESSION"
        elif t < 930: return "CLOSING"
        else:         return "POST_MARKET"
