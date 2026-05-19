# core/market_memory.py
# ─────────────────────────────────────────────
# Stores all OHLCV candles with full technical
# context. This is the AI's long-term memory.
# ─────────────────────────────────────────────

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
import ta

import config


class MarketMemory:

    def __init__(self, db_path: str = config.MARKET_MEMORY_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        # Create tables for each timeframe — same schema, separate tables
        for tf in ("candles_3min", "candles_5min", "candles_15min"):
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {tf} (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp        TEXT UNIQUE,
                    open             REAL,
                    high             REAL,
                    low              REAL,
                    close            REAL,
                    volume           REAL,
                    candle_body      REAL,
                    candle_range     REAL,
                    body_ratio       REAL,
                    direction        TEXT,
                    rsi_14           REAL,
                    ema_9            REAL,
                    ema_21           REAL,
                    ema_50           REAL,
                    vwap             REAL,
                    atr_14           REAL,
                    volume_sma20     REAL,
                    volume_ratio     REAL,
                    macd             REAL,
                    macd_signal      REAL,
                    bb_upper         REAL,
                    bb_lower         REAL,
                    bb_mid           REAL,
                    swing_high       INTEGER DEFAULT 0,
                    swing_low        INTEGER DEFAULT 0,
                    higher_high      INTEGER DEFAULT 0,
                    lower_low        INTEGER DEFAULT 0,
                    inside_bar       INTEGER DEFAULT 0,
                    market_session   TEXT,
                    day_of_week      TEXT,
                    week_number      INTEGER,
                    regime           TEXT,
                    next_5_move      REAL,
                    next_10_move     REAL,
                    next_20_move     REAL,
                    ingested_at      TEXT
                )
            """)
        # Keep original candles table for backward compatibility (maps to 5min)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT UNIQUE,
                open             REAL,
                high             REAL,
                low              REAL,
                close            REAL,
                volume           REAL,

                -- Candle structure
                candle_body      REAL,
                candle_range     REAL,
                body_ratio       REAL,
                direction        TEXT,

                -- Indicators
                rsi_14           REAL,
                ema_9            REAL,
                ema_21           REAL,
                ema_50           REAL,
                vwap             REAL,
                atr_14           REAL,
                volume_sma20     REAL,
                volume_ratio     REAL,
                macd             REAL,
                macd_signal      REAL,
                bb_upper         REAL,
                bb_lower         REAL,
                bb_mid           REAL,

                -- Market structure
                swing_high       INTEGER DEFAULT 0,
                swing_low        INTEGER DEFAULT 0,
                higher_high      INTEGER DEFAULT 0,
                lower_low        INTEGER DEFAULT 0,
                inside_bar       INTEGER DEFAULT 0,

                -- Session context
                market_session   TEXT,
                day_of_week      TEXT,
                week_number      INTEGER,

                -- Regime
                regime           TEXT,

                -- Forward returns (filled after candle closes)
                next_5_move      REAL,
                next_10_move     REAL,
                next_20_move     REAL,

                ingested_at      TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    # INGEST CANDLES
    # ─────────────────────────────────────────
    def ingest_candles(self, df: pd.DataFrame, timeframe: str = "5min") -> int:
        """
        Feed OHLCV DataFrame into memory.
        Automatically computes all indicators & context.
        Returns number of new rows inserted.
        """
        if df.empty:
            logger.warning("Empty DataFrame — nothing to ingest")
            return 0

        df = df.copy()
        df = df.sort_values('timestamp').reset_index(drop=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # ── Candle structure
        df['candle_body']  = (df['close'] - df['open']).abs()
        df['candle_range'] = df['high'] - df['low']
        df['body_ratio']   = df['candle_body'] / df['candle_range'].replace(0, np.nan)
        df['direction']    = np.where(df['close'] > df['open'], 'BULL',
                             np.where(df['close'] < df['open'], 'BEAR', 'DOJI'))

        # ── RSI
        df['rsi_14'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

        # ── EMAs
        df['ema_9']  = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator()
        df['ema_21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()

        # ── ATR
        df['atr_14'] = ta.volatility.AverageTrueRange(
            df['high'], df['low'], df['close'], window=14
        ).average_true_range()

        # ── Bollinger Bands
        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_mid']   = bb.bollinger_mavg()

        # ── MACD
        macd = ta.trend.MACD(df['close'])
        df['macd']        = macd.macd()
        df['macd_signal'] = macd.macd_signal()

        # ── Volume
        df['volume_sma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma20'].replace(0, np.nan)

        # ── VWAP (daily reset)
        df['vwap'] = self._compute_vwap(df)

        # ── Market structure
        df['swing_high']  = self._detect_swing_high(df).astype(int)
        df['swing_low']   = self._detect_swing_low(df).astype(int)
        df['higher_high'] = (df['high'] > df['high'].shift(1)).astype(int)
        df['lower_low']   = (df['low']  < df['low'].shift(1)).astype(int)
        df['inside_bar']  = (
            (df['high'] < df['high'].shift(1)) &
            (df['low']  > df['low'].shift(1))
        ).astype(int)

        # ── Session + time
        df['market_session'] = df['timestamp'].apply(self._get_session)
        df['day_of_week']    = df['timestamp'].dt.strftime('%A')
        df['week_number']    = df['timestamp'].dt.isocalendar().week.astype(int)

        # ── Regime
        df['regime'] = self._detect_regime(df)

        # ── Forward returns
        df['next_5_move']  = df['close'].pct_change(5).shift(-5)  * 100
        df['next_10_move'] = df['close'].pct_change(10).shift(-10) * 100
        df['next_20_move'] = df['close'].pct_change(20).shift(-20) * 100

        df['ingested_at'] = datetime.now().isoformat()
        df['timestamp']   = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # ── Route to correct table based on timeframe
        tf_map   = {"3min": "candles_3min", "5min": "candles_5min", "15min": "candles_15min"}
        table    = tf_map.get(timeframe, "candles_5min")

        conn     = sqlite3.connect(self.db_path)
        inserted = 0
        sql = f"""
            INSERT OR IGNORE INTO {table} (
                timestamp, open, high, low, close, volume,
                candle_body, candle_range, body_ratio, direction,
                rsi_14, ema_9, ema_21, ema_50, vwap, atr_14,
                volume_sma20, volume_ratio, macd, macd_signal,
                bb_upper, bb_lower, bb_mid,
                swing_high, swing_low, higher_high, lower_low, inside_bar,
                market_session, day_of_week, week_number, regime,
                next_5_move, next_10_move, next_20_move, ingested_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        # Also mirror 5min data into legacy candles table for backward compatibility
        sql_legacy = sql.replace(f"INTO {table}", "INTO candles") if table == "candles_5min" else None

        for _, row in df.iterrows():
            params = (
                row['timestamp'], row['open'], row['high'], row['low'],
                row['close'], row['volume'],
                row.get('candle_body'),   row.get('candle_range'),
                row.get('body_ratio'),    row.get('direction'),
                row.get('rsi_14'),        row.get('ema_9'),
                row.get('ema_21'),        row.get('ema_50'),
                row.get('vwap'),          row.get('atr_14'),
                row.get('volume_sma20'),  row.get('volume_ratio'),
                row.get('macd'),          row.get('macd_signal'),
                row.get('bb_upper'),      row.get('bb_lower'),
                row.get('bb_mid'),
                row.get('swing_high', 0), row.get('swing_low', 0),
                row.get('higher_high', 0),row.get('lower_low', 0),
                row.get('inside_bar', 0),
                row.get('market_session'),row.get('day_of_week'),
                row.get('week_number'),   row.get('regime'),
                row.get('next_5_move'),   row.get('next_10_move'),
                row.get('next_20_move'),  row.get('ingested_at')
            )
            try:
                conn.execute(sql, params)
                inserted += 1
            except Exception as e:
                logger.debug(f"Row insert skipped ({table}): {e}")
            if sql_legacy:
                try:
                    conn.execute(sql_legacy, params)
                except Exception:
                    pass
        conn.commit()
        conn.close()
        logger.info(f"MarketMemory [{timeframe}]: {inserted} new candles ingested → {table}")
        return inserted

    def get_memory_tf(self, timeframe: str = "5min", days: int = 14) -> pd.DataFrame:
        """Retrieve last N days from a specific timeframe table."""
        tf_map = {"3min": "candles_3min", "5min": "candles_5min", "15min": "candles_15min"}
        table  = tf_map.get(timeframe, "candles_5min")
        since  = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        conn   = sqlite3.connect(self.db_path)
        df     = pd.read_sql(
            f"SELECT * FROM {table} WHERE timestamp >= ? AND next_10_move IS NOT NULL ORDER BY timestamp",
            conn, params=(since,)
        )
        conn.close()
        return df

    def get_htf_trend(self) -> dict:
        """
        Return the current higher-timeframe (15-min) trend direction.
        Used by the live analyzer to filter BrahmAstra signals.
        """
        conn = sqlite3.connect(self.db_path)
        df   = pd.read_sql(
            "SELECT ema_9, ema_21, ema_50, regime, close FROM candles_15min ORDER BY timestamp DESC LIMIT 3",
            conn
        )
        conn.close()
        if df.empty:
            return {"trend": "UNKNOWN", "regime": "UNKNOWN"}
        row = df.iloc[0]
        e9, e21, e50 = row.get("ema_9"), row.get("ema_21"), row.get("ema_50")
        if all(v and not pd.isna(v) for v in [e9, e21, e50]):
            if e9 > e21 > e50:   trend = "STRONG_UP"
            elif e9 > e21:       trend = "UP"
            elif e9 < e21 < e50: trend = "STRONG_DOWN"
            elif e9 < e21:       trend = "DOWN"
            else:                trend = "NEUTRAL"
        else:
            trend = "UNKNOWN"
        return {"trend": trend, "regime": str(row.get("regime", "UNKNOWN"))}

    # ─────────────────────────────────────────
    # RETRIEVE
    # ─────────────────────────────────────────
    def get_memory(self, days: int = 14) -> pd.DataFrame:
        """Retrieve last N days of enriched candle data"""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        conn  = sqlite3.connect(self.db_path)
        df    = pd.read_sql(
            f"SELECT * FROM candles WHERE timestamp >= ? AND next_10_move IS NOT NULL ORDER BY timestamp",
            conn, params=(since,)
        )
        conn.close()
        return df

    def get_recent_candles(self, n: int = 50) -> pd.DataFrame:
        """Get last N candles regardless of date"""
        conn = sqlite3.connect(self.db_path)
        df   = pd.read_sql(
            f"SELECT * FROM candles ORDER BY timestamp DESC LIMIT {n}",
            conn
        )
        conn.close()
        return df.sort_values('timestamp').reset_index(drop=True)

    def total_candles(self) -> int:
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        conn.close()
        return count

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _compute_vwap(self, df: pd.DataFrame) -> pd.Series:
        typical = (df['high'] + df['low'] + df['close']) / 3
        # Reset VWAP at start of each day
        df2 = df.copy()
        df2['typical'] = typical
        df2['date']    = pd.to_datetime(df['timestamp']).dt.date
        vwap = (
            df2.groupby('date', group_keys=False)
               .apply(lambda g: (g['typical'] * g['volume']).cumsum() /
                                 g['volume'].cumsum())
        )
        return vwap.values

    def _detect_swing_high(self, df: pd.DataFrame, window: int = 3) -> pd.Series:
        return df['high'] == df['high'].rolling(window * 2 + 1, center=True).max()

    def _detect_swing_low(self, df: pd.DataFrame, window: int = 3) -> pd.Series:
        return df['low'] == df['low'].rolling(window * 2 + 1, center=True).min()

    def _detect_regime(self, df: pd.DataFrame) -> list:
        regimes = []
        for i in range(len(df)):
            try:
                e9  = df['ema_9'].iloc[i]
                e21 = df['ema_21'].iloc[i]
                e50 = df['ema_50'].iloc[i]
                atr = df['atr_14'].iloc[i]
                cl  = df['close'].iloc[i]
                if pd.isna(e50) or cl == 0:
                    regimes.append('UNKNOWN')
                    continue
                atr_pct = (atr / cl) * 100
                if atr_pct > 1.5:
                    regimes.append('VOLATILE')
                elif e9 > e21 > e50:
                    regimes.append('TRENDING_UP')
                elif e9 < e21 < e50:
                    regimes.append('TRENDING_DOWN')
                else:
                    regimes.append('CHOPPY')
            except Exception:
                regimes.append('UNKNOWN')
        return regimes

    def _get_session(self, ts) -> str:
        t = ts.hour * 60 + ts.minute
        if   t < 555: return "PRE_OPEN"
        elif t < 630: return "OPENING"
        elif t < 840: return "MID_SESSION"
        elif t < 930: return "CLOSING"
        else:         return "POST_MARKET"
