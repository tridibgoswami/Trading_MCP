# intelligence/pattern_discovery.py
# ─────────────────────────────────────────────
# Scans market memory and discovers conditions
# that statistically predict profitable moves.
# This is the engine's self-discovery capability.
# ─────────────────────────────────────────────

import pandas as pd
import numpy as np
from itertools import combinations
from loguru import logger
import config


class PatternDiscovery:

    def __init__(self, df: pd.DataFrame):
        """
        df = enriched candle DataFrame from MarketMemory.get_memory()
        """
        self.df = df.dropna(subset=['next_10_move']).copy()
        logger.info(f"PatternDiscovery initialized with {len(self.df)} candles")

    # ─────────────────────────────────────────
    # BUILD CONDITION MAP
    # ─────────────────────────────────────────
    def _build_conditions(self) -> dict:
        df = self.df
        return {
            # RSI zones
            "rsi_below_30":      df['rsi_14'] < 30,
            "rsi_30_to_40":      df['rsi_14'].between(30, 40),
            "rsi_40_to_50":      df['rsi_14'].between(40, 50),
            "rsi_50_to_60":      df['rsi_14'].between(50, 60),
            "rsi_60_to_70":      df['rsi_14'].between(60, 70),
            "rsi_above_70":      df['rsi_14'] > 70,

            # Price vs VWAP
            "above_vwap":        df['close'] > df['vwap'],
            "below_vwap":        df['close'] < df['vwap'],
            "near_vwap":         (df['close'] - df['vwap']).abs() / df['vwap'] < 0.001,

            # EMA alignment
            "ema9_above_21":     df['ema_9'] > df['ema_21'],
            "ema9_below_21":     df['ema_9'] < df['ema_21'],
            "ema21_above_50":    df['ema_21'] > df['ema_50'],
            "ema21_below_50":    df['ema_21'] < df['ema_50'],
            "all_emas_aligned_up":   (df['ema_9'] > df['ema_21']) & (df['ema_21'] > df['ema_50']),
            "all_emas_aligned_down": (df['ema_9'] < df['ema_21']) & (df['ema_21'] < df['ema_50']),

            # MACD
            "macd_bullish":      df['macd'] > df['macd_signal'],
            "macd_bearish":      df['macd'] < df['macd_signal'],
            "macd_zero_cross_up":   (df['macd'] > 0) & (df['macd'].shift(1) <= 0),
            "macd_zero_cross_down": (df['macd'] < 0) & (df['macd'].shift(1) >= 0),

            # Bollinger Bands
            "near_bb_upper":     df['close'] >= df['bb_upper'] * 0.998,
            "near_bb_lower":     df['close'] <= df['bb_lower'] * 1.002,
            "inside_bb":         (df['close'] < df['bb_upper']) & (df['close'] > df['bb_lower']),
            "bb_squeeze":        (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] < 0.02,

            # Candle patterns
            "bull_candle":       df['direction'] == 'BULL',
            "bear_candle":       df['direction'] == 'BEAR',
            "doji":              df['direction'] == 'DOJI',
            "strong_bull":       (df['direction'] == 'BULL') & (df['body_ratio'] > 0.7),
            "strong_bear":       (df['direction'] == 'BEAR') & (df['body_ratio'] > 0.7),
            "inside_bar":        df['inside_bar'] == 1,
            "swing_high":        df['swing_high'] == 1,
            "swing_low":         df['swing_low'] == 1,
            "higher_high":       df['higher_high'] == 1,
            "lower_low":         df['lower_low'] == 1,

            # Volume
            "high_volume":       df['volume_ratio'] > 1.5,
            "very_high_volume":  df['volume_ratio'] > 2.0,
            "low_volume":        df['volume_ratio'] < 0.7,
            "avg_volume":        df['volume_ratio'].between(0.8, 1.2),

            # Regime
            "trending_up":       df['regime'] == 'TRENDING_UP',
            "trending_down":     df['regime'] == 'TRENDING_DOWN',
            "choppy":            df['regime'] == 'CHOPPY',
            "volatile":          df['regime'] == 'VOLATILE',

            # Session
            "opening_session":   df['market_session'] == 'OPENING',
            "mid_session":       df['market_session'] == 'MID_SESSION',
            "closing_session":   df['market_session'] == 'CLOSING',

            # Day of week
            "monday":            df['day_of_week'] == 'Monday',
            "tuesday":           df['day_of_week'] == 'Tuesday',
            "wednesday":         df['day_of_week'] == 'Wednesday',
            "thursday":          df['day_of_week'] == 'Thursday',
            "friday":            df['day_of_week'] == 'Friday',
        }

    # ─────────────────────────────────────────
    # SINGLE + COMBO PATTERN SCAN
    # ─────────────────────────────────────────
    def discover_profitable_conditions(self,
                                        lookahead : int   = 10,
                                        min_edge  : float = config.MIN_PATTERN_EDGE,
                                        min_size  : int   = config.MIN_SAMPLE_SIZE
                                        ) -> list:
        """
        Scans all condition combinations and returns
        those with statistically significant edge.
        """
        conditions  = self._build_conditions()
        move_col    = f'next_{lookahead}_move'
        discovered  = []

        # ── Single conditions
        for name, mask in conditions.items():
            subset = self.df[mask]
            if len(subset) < min_size:
                continue
            result = self._evaluate(subset, move_col)
            if result['win_rate'] >= min_edge or result['win_rate'] <= (1 - min_edge):
                direction = "LONG" if result['win_rate'] >= 0.5 else "SHORT"
                discovered.append({
                    "type":        "SINGLE",
                    "conditions":  [name],
                    "direction":   direction,
                    "win_rate":    round(result['win_rate'] * 100, 2),
                    "avg_move":    round(result['avg_move'], 3),
                    "max_move":    round(result['max_move'], 3),
                    "sample_size": len(subset),
                    "edge":        round(abs(result['win_rate'] - 0.5) * 2, 3),
                    "consistency": round(result['consistency'], 3)
                })

        # ── 2-condition combos (stronger patterns)
        cond_keys = list(conditions.keys())
        for c1, c2 in combinations(cond_keys, 2):
            mask   = conditions[c1] & conditions[c2]
            subset = self.df[mask]
            if len(subset) < min_size:
                continue
            result = self._evaluate(subset, move_col)
            edge   = abs(result['win_rate'] - 0.5) * 2
            if edge >= (min_edge - 0.5) * 2 + 0.1:   # slightly higher bar
                direction = "LONG" if result['win_rate'] >= 0.5 else "SHORT"
                discovered.append({
                    "type":        "COMBO_2",
                    "conditions":  [c1, c2],
                    "direction":   direction,
                    "win_rate":    round(result['win_rate'] * 100, 2),
                    "avg_move":    round(result['avg_move'], 3),
                    "max_move":    round(result['max_move'], 3),
                    "sample_size": len(subset),
                    "edge":        round(edge, 3),
                    "consistency": round(result['consistency'], 3)
                })

        # Sort by edge
        discovered.sort(key=lambda x: (x['edge'], x['sample_size']), reverse=True)
        logger.info(f"Discovered {len(discovered)} patterns (top {min(20, len(discovered))} returned)")
        return discovered[:20]

    # ─────────────────────────────────────────
    # REGIME-SPECIFIC ANALYSIS
    # ─────────────────────────────────────────
    def detect_regime_specific_patterns(self) -> dict:
        """What works in each market regime?"""
        results = {}
        for regime in ['TRENDING_UP', 'TRENDING_DOWN', 'CHOPPY', 'VOLATILE']:
            subset = self.df[self.df['regime'] == regime]
            if len(subset) < 30:
                continue
            results[regime] = {
                "sample_size":     len(subset),
                "best_session":    self._best_by_col(subset, 'market_session'),
                "best_day":        self._best_by_col(subset, 'day_of_week'),
                "avg_atr":         round(subset['atr_14'].mean(), 2),
                "rsi_sweet_spot":  self._rsi_analysis(subset),
                "volume_edge":     self._volume_edge(subset),
                "vwap_edge":       self._vwap_edge(subset),
            }
        return results

    def analyze_signal_performance(self, signals_df: pd.DataFrame) -> dict:
        """
        Analyze YOUR indicator's signals against market data.
        signals_df = DataFrame from SignalLogger
        """
        if signals_df.empty:
            return {"error": "No signals to analyze"}

        winners = signals_df[signals_df['outcome'] == 'WIN']
        losers  = signals_df[signals_df['outcome'] == 'LOSS']
        total   = len(signals_df)

        return {
            "overview": {
                "total":        total,
                "win_rate":     round(len(winners) / total * 100, 2),
                "avg_win_pct":  round(winners['pnl_pct'].mean(), 3) if not winners.empty else 0,
                "avg_loss_pct": round(losers['pnl_pct'].mean(), 3) if not losers.empty else 0,
                "profit_factor":round(
                    abs(winners['pnl'].sum() / losers['pnl'].sum())
                    if not losers.empty and losers['pnl'].sum() != 0 else 999, 2
                ),
                "total_pnl":    round(signals_df['pnl'].sum(), 2)
            },
            "best_conditions": {
                "best_session":    self._best_by_col(winners, 'market_session'),
                "best_day":        self._best_by_col(winners, 'day_of_week'),
                "best_regime":     self._best_by_col(winners, 'regime'),
                "above_vwap_wr":   round(
                    len(signals_df[(signals_df['above_vwap']==1) & (signals_df['outcome']=='WIN')]) /
                    max(len(signals_df[signals_df['above_vwap']==1]), 1) * 100, 2
                ),
            },
            "worst_conditions": {
                "worst_session": self._best_by_col(losers, 'market_session'),
                "worst_day":     self._best_by_col(losers, 'day_of_week'),
                "worst_regime":  self._best_by_col(losers, 'regime'),
            }
        }

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _evaluate(self, subset: pd.DataFrame, move_col: str) -> dict:
        moves       = subset[move_col].dropna()
        win_rate    = (moves > 0).sum() / len(moves) if len(moves) > 0 else 0.5
        avg_move    = moves.mean()
        max_move    = moves.max()
        consistency = 1 - (moves.std() / (abs(avg_move) + 0.001))
        return {
            "win_rate":    win_rate,
            "avg_move":    avg_move,
            "max_move":    max_move,
            "consistency": max(consistency, 0)
        }

    def _best_by_col(self, df: pd.DataFrame, col: str) -> str:
        if col not in df.columns or df.empty:
            return "N/A"
        vc = df[col].value_counts()
        return str(vc.index[0]) if not vc.empty else "N/A"

    def _rsi_analysis(self, df: pd.DataFrame) -> dict:
        bins   = [0, 30, 40, 50, 60, 70, 100]
        labels = ['<30', '30-40', '40-50', '50-60', '60-70', '>70']
        df     = df.copy()
        df['rsi_zone'] = pd.cut(df['rsi_14'], bins=bins, labels=labels)
        by_zone = df.groupby('rsi_zone')['next_10_move'].mean()
        return {
            "best_long_zone":  str(by_zone.idxmax()) if not by_zone.empty else "N/A",
            "best_short_zone": str(by_zone.idxmin()) if not by_zone.empty else "N/A",
        }

    def _volume_edge(self, df: pd.DataFrame) -> bool:
        hv = df[df['volume_ratio'] > 1.5]['next_10_move'].mean()
        lv = df[df['volume_ratio'] < 0.7]['next_10_move'].mean()
        return bool(abs(hv - lv) > 0.1) if not (np.isnan(hv) or np.isnan(lv)) else False

    def _vwap_edge(self, df: pd.DataFrame) -> dict:
        above = df[df['close'] > df['vwap']]['next_10_move'].mean()
        below = df[df['close'] < df['vwap']]['next_10_move'].mean()
        return {
            "above_vwap_avg_move": round(above, 3) if not np.isnan(above) else 0,
            "below_vwap_avg_move": round(below, 3) if not np.isnan(below) else 0,
            "vwap_matters":        bool(abs(above - below) > 0.15)
        }
