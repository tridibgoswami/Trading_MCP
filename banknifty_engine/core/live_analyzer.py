# core/live_analyzer.py
# ─────────────────────────────────────────────
# Real-time market analysis engine.
# Connects to AngelOne WebSocket for live price,
# rebuilds indicators every 60 seconds,
# and detects signals as price moves occur.
# ─────────────────────────────────────────────

import threading
import time
from datetime import datetime
from collections import deque

import numpy as np
import pandas as pd
import ta
from loguru import logger

from core.angel_connect import AngelOneConnect
from core.market_memory import MarketMemory
from core.rule_engine import RuleEngine
import config


class LiveAnalyzer:

    REFRESH_INTERVAL = 60  # seconds between indicator refreshes

    def __init__(self, angel: AngelOneConnect = None):
        self.angel  = angel or AngelOneConnect()
        self.memory = MarketMemory()
        self.rules  = RuleEngine()

        self._running        = False
        self._lock           = threading.Lock()
        self._refresh_thread = None
        self._recent_signals = deque(maxlen=50)

        # Live state — read by MCP tools at any time
        self._state = {
            "ltp":             None,
            "ltp_updated_at":  None,
            "open":            None,
            "high":            None,
            "low":             None,
            "prev_close":      None,
            "change_pct":      None,
            "rsi":             None,
            "ema_9":           None,
            "ema_21":          None,
            "ema_50":          None,
            "vwap":            None,
            "atr":             None,
            "macd":            None,
            "macd_signal":     None,
            "bb_upper":        None,
            "bb_lower":        None,
            "volume_ratio":    None,
            "regime":          "UNKNOWN",
            "trend":           "NEUTRAL",
            "htf_trend":       "UNKNOWN",   # 15-min higher timeframe trend
            "htf_regime":      "UNKNOWN",   # 15-min regime
            "brahmAstra_bias": "NEUTRAL",   # combined HTF bias for BrahmAstra filter
            "above_vwap":      None,
            "market_session":  None,
            "candles_loaded":  0,
            "signals":         [],
            "alerts":          [],
        }

        self._preload_history()

    # ─────────────────────────────────────────
    # STARTUP / SHUTDOWN
    # ─────────────────────────────────────────
    def _preload_history(self):
        df = self.memory.get_recent_candles(100)
        if not df.empty:
            with self._lock:
                self._state["candles_loaded"] = len(df)
            logger.info(f"LiveAnalyzer: pre-loaded {len(df)} candles for indicator context")

    def start(self) -> bool:
        if self._running:
            logger.warning("LiveAnalyzer already running")
            return True

        if not self.angel.is_connected:
            if not self.angel.login():
                logger.error("LiveAnalyzer: AngelOne login failed")
                return False

        self._running = True

        # Register our tick handler and open WebSocket
        self.angel.register_tick_callback(self._on_tick)
        self.angel.start_live_feed()

        # Background thread: refresh indicators every 60 s
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name="live-indicator-refresh",
            daemon=True
        )
        self._refresh_thread.start()

        # Immediate first refresh so state isn't empty
        threading.Thread(
            target=self._refresh_indicators,
            daemon=True
        ).start()

        logger.success("LiveAnalyzer started — real-time analysis active")
        return True

    def stop(self):
        self._running = False
        self.angel.stop_live_feed()
        logger.info("LiveAnalyzer stopped")

    # ─────────────────────────────────────────
    # WEBSOCKET TICK HANDLER
    # ─────────────────────────────────────────
    def _on_tick(self, tick: dict):
        """
        Called on every price tick from the AngelOne WebSocket.
        Updates LTP and intraday high/low instantly.
        Detects rapid price moves (> 0.3%) as alerts.
        """
        try:
            # SmartWebSocketV2 delivers price in paise (integer) in LTP mode
            raw = (tick.get("last_traded_price")
                   or tick.get("ltp")
                   or tick.get("close_price"))
            if not raw:
                return

            ltp = float(raw)
            if ltp > 100_000:          # paise → rupees
                ltp /= 100.0

            with self._lock:
                prev_ltp = self._state["ltp"]

                self._state["ltp"]           = ltp
                self._state["ltp_updated_at"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._state["market_session"] = self._session_name()

                # Intraday open / high / low
                if self._state["open"] is None:
                    self._state["open"] = ltp
                if self._state["high"] is None or ltp > self._state["high"]:
                    self._state["high"] = ltp
                if self._state["low"] is None or ltp < self._state["low"]:
                    self._state["low"] = ltp

                # VWAP relationship
                if self._state["vwap"]:
                    self._state["above_vwap"] = ltp > self._state["vwap"]

                # PnL-from-prev-close
                if self._state["prev_close"]:
                    self._state["change_pct"] = round(
                        (ltp - self._state["prev_close"]) / self._state["prev_close"] * 100, 3
                    )

                # Rapid-move alert (tick-to-tick)
                if prev_ltp and prev_ltp > 0:
                    move_pct = (ltp - prev_ltp) / prev_ltp * 100
                    if abs(move_pct) >= 0.3:
                        alert = {
                            "time":      self._state["ltp_updated_at"],
                            "type":      "RAPID_MOVE",
                            "price":     ltp,
                            "move_pct":  round(move_pct, 3),
                            "direction": "UP" if move_pct > 0 else "DOWN",
                        }
                        self._state["alerts"].append(alert)
                        if len(self._state["alerts"]) > 20:
                            self._state["alerts"] = self._state["alerts"][-20:]

        except Exception as e:
            logger.debug(f"Tick handler error: {e}")

    # ─────────────────────────────────────────
    # INDICATOR REFRESH LOOP
    # ─────────────────────────────────────────
    def _refresh_loop(self):
        while self._running:
            try:
                if self._is_market_hours():
                    self._refresh_indicators()
                time.sleep(self.REFRESH_INTERVAL)
            except Exception as e:
                logger.error(f"Refresh loop error: {e}")
                time.sleep(self.REFRESH_INTERVAL)

    def _refresh_indicators(self):
        """
        Fetches the latest 5-min candles, recomputes all indicators,
        runs signal detection, and updates _state atomically.
        """
        try:
            df = self.angel.get_historical_data(interval="FIVE_MINUTE", days=2)
            if df.empty or len(df) < 20:
                logger.warning("LiveAnalyzer: insufficient candles for indicator refresh")
                return

            df = self._compute_indicators(df)
            latest = df.iloc[-1]
            prev   = df.iloc[-2] if len(df) > 1 else df.iloc[-1]

            new_signals = self._detect_signals(df)

            with self._lock:
                ltp = self._state["ltp"] or float(latest["close"])

                self._state.update({
                    "prev_close":   self._f(df.iloc[-2]["close"]) if len(df) > 1 else None,
                    "rsi":          self._f(latest.get("rsi_14")),
                    "ema_9":        self._f(latest.get("ema_9")),
                    "ema_21":       self._f(latest.get("ema_21")),
                    "ema_50":       self._f(latest.get("ema_50")),
                    "vwap":         self._f(latest.get("vwap")),
                    "atr":          self._f(latest.get("atr_14")),
                    "macd":         self._f(latest.get("macd")),
                    "macd_signal":  self._f(latest.get("macd_signal")),
                    "bb_upper":     self._f(latest.get("bb_upper")),
                    "bb_lower":     self._f(latest.get("bb_lower")),
                    "volume_ratio": self._f(latest.get("volume_ratio")),
                    "regime":       str(latest.get("regime", "UNKNOWN")),
                    "trend":        self._trend_label(latest),
                    "above_vwap":   bool(ltp > (self._f(latest.get("vwap")) or 0)),
                    "candles_loaded": len(df),
                    **self._htf_state(),   # inject 15-min trend fields
                })

                if self._state["prev_close"]:
                    self._state["change_pct"] = round(
                        (ltp - self._state["prev_close"]) / self._state["prev_close"] * 100, 3
                    )

                for sig in new_signals:
                    self._recent_signals.appendleft(sig)
                self._state["signals"] = list(self._recent_signals)[:10]

            logger.debug(
                f"Indicators refreshed | LTP: {ltp} | "
                f"RSI: {self._state['rsi']} | "
                f"Regime: {self._state['regime']}"
            )

        except Exception as e:
            logger.error(f"_refresh_indicators error: {e}")

    # ─────────────────────────────────────────
    # INDICATOR COMPUTATION
    # ─────────────────────────────────────────
    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().sort_values("timestamp").reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        df["rsi_14"]  = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        df["ema_9"]   = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
        df["ema_21"]  = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
        df["ema_50"]  = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
        df["atr_14"]  = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=14
        ).average_true_range()

        macd = ta.trend.MACD(df["close"])
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()

        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()

        df["volume_sma20"] = df["volume"].rolling(20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma20"].replace(0, np.nan)

        # VWAP — resets each day
        typical   = (df["high"] + df["low"] + df["close"]) / 3
        df["date"] = df["timestamp"].dt.date
        df["vwap"] = (
            df.groupby("date", group_keys=False)
              .apply(lambda g: (typical.loc[g.index] * g["volume"]).cumsum()
                               / g["volume"].cumsum())
        ).values

        df["regime"] = self._detect_regime(df)
        return df

    def _detect_regime(self, df: pd.DataFrame) -> list:
        regimes = []
        for i in range(len(df)):
            try:
                e9  = df["ema_9"].iloc[i]
                e21 = df["ema_21"].iloc[i]
                e50 = df["ema_50"].iloc[i]
                atr = df["atr_14"].iloc[i]
                cl  = df["close"].iloc[i]
                if pd.isna(e50) or cl == 0:
                    regimes.append("UNKNOWN"); continue
                atr_pct = (atr / cl) * 100
                if atr_pct > 1.5:          regimes.append("VOLATILE")
                elif e9 > e21 > e50:       regimes.append("TRENDING_UP")
                elif e9 < e21 < e50:       regimes.append("TRENDING_DOWN")
                else:                      regimes.append("CHOPPY")
            except Exception:
                regimes.append("UNKNOWN")
        return regimes

    # ─────────────────────────────────────────
    # SIGNAL DETECTION
    # ─────────────────────────────────────────
    def _detect_signals(self, df: pd.DataFrame) -> list:
        """
        Evaluates a fixed set of well-known conditions on the
        last two completed candles and returns new signals.
        """
        if len(df) < 3:
            return []

        signals = []
        c  = df.iloc[-1]   # current (latest completed) candle
        p  = df.iloc[-2]   # previous candle
        ltp = self._state.get("ltp") or float(c["close"])

        rsi    = self._f(c.get("rsi_14"));   prev_rsi  = self._f(p.get("rsi_14"))
        ema9   = self._f(c.get("ema_9"));    prev_ema9  = self._f(p.get("ema_9"))
        ema21  = self._f(c.get("ema_21"));   prev_ema21 = self._f(p.get("ema_21"))
        macd   = self._f(c.get("macd"));     prev_macd  = self._f(p.get("macd"))
        macd_s = self._f(c.get("macd_signal")); prev_ms = self._f(p.get("macd_signal"))
        vwap   = self._f(c.get("vwap"))
        vol_r  = self._f(c.get("volume_ratio"))
        regime = str(c.get("regime", "UNKNOWN"))
        bb_u   = self._f(c.get("bb_upper"))
        bb_l   = self._f(c.get("bb_lower"))

        def sig(name, direction):
            return {
                "time":         datetime.now().strftime("%H:%M:%S"),
                "signal":       name,
                "direction":    direction,
                "price":        round(ltp, 2),
                "rsi":          round(rsi, 1) if rsi else None,
                "regime":       regime,
                "volume_ratio": round(vol_r, 2) if vol_r else None,
            }

        # RSI oversold bounce
        if rsi and prev_rsi and prev_rsi < 35 < rsi:
            signals.append(sig("RSI_OVERSOLD_BOUNCE", "BUY"))

        # RSI overbought reversal
        if rsi and prev_rsi and prev_rsi > 70 > rsi:
            signals.append(sig("RSI_OVERBOUGHT_REVERSAL", "SELL"))

        # EMA 9/21 crossover
        if ema9 and ema21 and prev_ema9 and prev_ema21:
            if prev_ema9 < prev_ema21 and ema9 > ema21:
                signals.append(sig("EMA9_21_BULLISH_CROSS", "BUY"))
            elif prev_ema9 > prev_ema21 and ema9 < ema21:
                signals.append(sig("EMA9_21_BEARISH_CROSS", "SELL"))

        # MACD crossover
        if macd and macd_s and prev_macd and prev_ms:
            if prev_macd < prev_ms and macd > macd_s:
                signals.append(sig("MACD_BULLISH_CROSS", "BUY"))
            elif prev_macd > prev_ms and macd < macd_s:
                signals.append(sig("MACD_BEARISH_CROSS", "SELL"))

        # VWAP + volume surge
        if vwap and vol_r and vol_r > 1.5:
            if ltp > vwap:
                signals.append(sig("ABOVE_VWAP_VOLUME_SURGE", "BUY"))
            else:
                signals.append(sig("BELOW_VWAP_VOLUME_SURGE", "SELL"))

        # Bollinger Band touch
        if bb_l and ltp <= bb_l * 1.001:
            signals.append(sig("BB_LOWER_BAND_TOUCH", "BUY"))
        if bb_u and ltp >= bb_u * 0.999:
            signals.append(sig("BB_UPPER_BAND_TOUCH", "SELL"))

        # Strong trend confirmation
        ema50 = self._f(c.get("ema_50"))
        if ema9 and ema21 and ema50:
            if ema9 > ema21 > ema50 and vol_r and vol_r > 1.2:
                signals.append(sig("STRONG_UPTREND_CONFIRMED", "BUY"))
            elif ema9 < ema21 < ema50 and vol_r and vol_r > 1.2:
                signals.append(sig("STRONG_DOWNTREND_CONFIRMED", "SELL"))

        return signals

    # ─────────────────────────────────────────
    # PUBLIC API (called by MCP tools)
    # ─────────────────────────────────────────
    def get_market_state(self) -> dict:
        """Full snapshot of live market state."""
        with self._lock:
            state = dict(self._state)
        state["is_running"]       = self._running
        state["is_market_hours"]  = self._is_market_hours()
        state["snapshot_at"]      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return state

    def get_live_signals(self, last_n: int = 10) -> list:
        with self._lock:
            return list(self._recent_signals)[:last_n]

    def force_refresh(self):
        """Trigger an immediate indicator refresh outside the schedule."""
        if self.angel.is_connected:
            threading.Thread(
                target=self._refresh_indicators,
                daemon=True
            ).start()
        else:
            logger.warning("Cannot refresh — not connected to AngelOne")

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _f(self, val, default=None):
        """Safe float conversion — returns None for NaN/Inf."""
        try:
            f = float(val)
            return None if (np.isnan(f) or np.isinf(f)) else round(f, 4)
        except Exception:
            return default

    def _htf_state(self) -> dict:
        """
        Fetch 15-min trend from market memory and derive BrahmAstra bias.
        brahmAstra_bias: LONG_ONLY | SHORT_ONLY | NEUTRAL | AVOID
        """
        try:
            htf    = self.memory.get_htf_trend()
            trend  = htf.get("trend", "UNKNOWN")
            regime = htf.get("regime", "UNKNOWN")
            if trend in ("STRONG_UP", "UP"):       bias = "LONG_ONLY"
            elif trend in ("STRONG_DOWN", "DOWN"): bias = "SHORT_ONLY"
            elif regime == "VOLATILE":             bias = "AVOID"
            else:                                  bias = "NEUTRAL"
            return {"htf_trend": trend, "htf_regime": regime, "brahmAstra_bias": bias}
        except Exception:
            return {"htf_trend": "UNKNOWN", "htf_regime": "UNKNOWN", "brahmAstra_bias": "NEUTRAL"}

    def _trend_label(self, row) -> str:
        e9  = self._f(row.get("ema_9"))
        e21 = self._f(row.get("ema_21"))
        e50 = self._f(row.get("ema_50"))
        if not all([e9, e21, e50]):
            return "NEUTRAL"
        if e9 > e21 > e50:   return "STRONG_UP"
        if e9 > e21:         return "UP"
        if e9 < e21 < e50:   return "STRONG_DOWN"
        if e9 < e21:         return "DOWN"
        return "NEUTRAL"

    def _is_market_hours(self) -> bool:
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return 555 <= t <= 930   # 9:15 AM – 3:30 PM IST

    def _session_name(self) -> str:
        t = datetime.now().hour * 60 + datetime.now().minute
        if   t < 555: return "PRE_OPEN"
        elif t < 630: return "OPENING"
        elif t < 840: return "MID_SESSION"
        elif t < 930: return "CLOSING"
        else:         return "POST_MARKET"
