# intelligence/evolution_engine.py
# ─────────────────────────────────────────────
# The self-evolving AI brain.
# Studies market data, discovers patterns,
# updates strategy rules automatically.
# ─────────────────────────────────────────────

import json
import sqlite3
from datetime import datetime
from loguru import logger
import anthropic

from core.market_memory import MarketMemory
from core.rule_engine import RuleEngine
from intelligence.pattern_discovery import PatternDiscovery
from signal_logger import SignalLogger
import config


class EvolutionEngine:

    def __init__(self):
        self.memory      = MarketMemory()
        self.rule_engine = RuleEngine()
        self.logger      = SignalLogger()
        self.client      = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._init_evolution_log()

    def _init_evolution_log(self):
        conn = sqlite3.connect(config.EVOLUTION_LOG_DB)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evolution_cycles (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at          TEXT,
                lookback_days   INTEGER,
                candles_analyzed INTEGER,
                patterns_found  INTEGER,
                rules_added     INTEGER,
                rules_modified  INTEGER,
                rules_retired   INTEGER,
                ai_summary      TEXT,
                full_plan       TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    # MAIN EVOLUTION CYCLE
    # ─────────────────────────────────────────
    def evolve(self, lookback_days: int = config.DEFAULT_LOOKBACK_DAYS) -> dict:
        """
        Full evolution cycle:
        1. Load market memory
        2. Discover patterns
        3. Analyze signal performance
        4. Ask Claude AI for evolution plan
        5. Apply the plan
        6. Log everything
        """
        sep = "=" * 60
        logger.info(f"\n{sep}")
        logger.info(f"  EVOLUTION CYCLE — Analyzing last {lookback_days} days")
        logger.info(f"{sep}")

        # ── Step 1: Load data
        df = self.memory.get_memory(days=lookback_days)
        if df.empty or len(df) < 50:
            logger.warning(f"Insufficient data: {len(df)} candles. Need at least 50.")
            return {"error": "insufficient_data", "candles": len(df)}

        logger.info(f"[1/6] Loaded {len(df)} enriched candles from memory")

        # ── Step 2: Discover market patterns
        discovery    = PatternDiscovery(df)
        new_patterns = discovery.discover_profitable_conditions()
        regime_data  = discovery.detect_regime_specific_patterns()
        logger.info(f"[2/6] Discovered {len(new_patterns)} candidate patterns")

        # ── Step 3: Analyze signal performance
        signals_df   = self.logger.get_signals_with_outcomes(days=lookback_days)
        signal_stats = discovery.analyze_signal_performance(signals_df)
        logger.info(f"[3/6] Analyzed {len(signals_df)} historical signals")

        # ── Step 4: Get existing rules performance
        existing_rules = self.rule_engine.get_active_rules()
        rule_perf      = self.rule_engine.get_performance_summary()
        logger.info(f"[4/6] Evaluated {len(existing_rules)} active rules")

        # ── Step 5: Claude AI makes the plan
        logger.info(f"[5/6] Consulting Claude AI for evolution plan...")
        plan = self._get_ai_plan(
            new_patterns   = new_patterns,
            regime_data    = regime_data,
            signal_stats   = signal_stats,
            existing_rules = existing_rules,
            rule_perf      = rule_perf,
            lookback_days  = lookback_days,
            candle_count   = len(df)
        )

        # ── Step 6: Apply the plan
        logger.info(f"[6/6] Applying evolution plan...")
        results = self._apply_plan(plan)

        # ── Log this cycle
        self._log_cycle(lookback_days, len(df), len(new_patterns), plan, results)

        logger.info(f"\n📋 EVOLUTION COMPLETE")
        logger.info(f"   {plan.get('optimization_summary', 'No summary')}")
        logger.info(sep)

        return {
            "plan":    plan,
            "results": results,
            "stats": {
                "candles":          len(df),
                "patterns_found":   len(new_patterns),
                "rules_added":      results['added'],
                "rules_modified":   results['modified'],
                "rules_retired":    results['retired'],
            }
        }

    # ─────────────────────────────────────────
    # AI PLAN GENERATION
    # ─────────────────────────────────────────
    def _get_ai_plan(self, new_patterns, regime_data, signal_stats,
                     existing_rules, rule_perf, lookback_days, candle_count) -> dict:
        """
        Sends all market intelligence to Claude and gets
        a structured evolution plan back.
        """

        prompt = f"""
You are an expert quantitative trading strategist specializing in Bank Nifty (Indian NSE index).

You are running the WEEKLY SELF-EVOLUTION CYCLE for a live trading system.
Your job is to analyze all available market intelligence and produce a precise
evolution plan to MAXIMIZE PROFITABILITY while controlling risk.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANALYSIS PERIOD: Last {lookback_days} days
CANDLES ANALYZED: {candle_count}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. NEWLY DISCOVERED MARKET PATTERNS (top patterns by statistical edge):
{json.dumps(new_patterns[:15], indent=2)}

2. REGIME-SPECIFIC ANALYSIS (what works in each market condition):
{json.dumps(regime_data, indent=2)}

3. YOUR INDICATOR'S SIGNAL PERFORMANCE:
{json.dumps(signal_stats, indent=2)}

4. EXISTING ACTIVE RULES + PERFORMANCE:
{json.dumps(existing_rules[:10], indent=2)}

5. ALL RULES PERFORMANCE SUMMARY:
{json.dumps(rule_perf, indent=2)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTIONS:
- Only recommend adding rules with sample_size >= 20 and edge >= 0.10
- Only retire rules with clear evidence of degradation (loss_streak > 5 or win_rate < 40%)
- Consider regime changes — what worked last month may not work now
- Consider Indian market specific factors (FII activity, expiry days, RBI events)
- Thursday is Bank Nifty expiry — treat separately
- Be specific with conditions and parameters

Return ONLY valid JSON, no explanation, no markdown:
{{
  "market_assessment": {{
    "dominant_regime": "TRENDING_UP|TRENDING_DOWN|CHOPPY|VOLATILE",
    "regime_changing": true|false,
    "key_observation": "Most important insight from the data",
    "risk_level": "LOW|MEDIUM|HIGH",
    "market_bias": "BULLISH|BEARISH|NEUTRAL",
    "expiry_week_note": "Any observation about expiry behavior"
  }},
  "new_rules_to_add": [
    {{
      "name": "descriptive_rule_name",
      "type": "ENTRY|EXIT|FILTER",
      "direction": "LONG|SHORT",
      "conditions": ["condition1", "condition2"],
      "parameters": {{"threshold": 0.0}},
      "weight": 0.8,
      "reasoning": "Why this has statistical edge"
    }}
  ],
  "rules_to_modify": [
    {{
      "name": "existing_rule_name",
      "change_description": "what exactly to change",
      "new_parameters": {{}},
      "new_weight": 0.7,
      "reasoning": "Evidence-based reason for change"
    }}
  ],
  "rules_to_retire": [
    {{
      "name": "existing_rule_name",
      "reasoning": "Statistical evidence for retirement"
    }}
  ],
  "new_filters_to_add": [
    {{
      "name": "filter_name",
      "condition": "when to block signals",
      "reasoning": "How this reduces losses"
    }}
  ],
  "optimization_summary": "3-4 sentence summary of what changed and why",
  "next_week_focus": "What to watch for in the coming week"
}}
"""

        try:
            response = self.client.messages.create(
                model      = "claude-opus-4-5",
                max_tokens = 3000,
                messages   = [{"role": "user", "content": prompt}]
            )
            raw   = response.content[0].text.strip()
            clean = raw.replace("```json", "").replace("```", "").strip()
            plan  = json.loads(clean)
            logger.success("AI evolution plan received successfully")
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return self._fallback_plan()
        except Exception as e:
            logger.error(f"AI plan generation error: {e}")
            return self._fallback_plan()

    # ─────────────────────────────────────────
    # APPLY PLAN
    # ─────────────────────────────────────────
    def _apply_plan(self, plan: dict) -> dict:
        added = modified = retired = 0

        # ── Add new rules
        for rule in plan.get('new_rules_to_add', []):
            if self.rule_engine.add_rule(rule, origin="AI_DISCOVERED"):
                logger.success(f"  ✅ NEW RULE: {rule['name']}")
                logger.info(f"     → {rule.get('reasoning', '')}")
                added += 1

        # ── Add filters as rules
        for f in plan.get('new_filters_to_add', []):
            filter_rule = {
                "name":       f['name'],
                "type":       "FILTER",
                "direction":  "BOTH",
                "conditions": [f['condition']],
                "parameters": {},
                "weight":     0.9,
                "reasoning":  f['reasoning']
            }
            if self.rule_engine.add_rule(filter_rule, origin="AI_FILTER"):
                logger.success(f"  🔒 NEW FILTER: {f['name']}")
                added += 1

        # ── Modify existing rules
        for mod in plan.get('rules_to_modify', []):
            try:
                updates = {}
                if mod.get('new_parameters'):
                    updates['parameters'] = mod['new_parameters']
                if mod.get('new_weight'):
                    updates['weight'] = mod['new_weight']
                if updates:
                    self.rule_engine.modify_rule(
                        mod['name'], updates, mod.get('reasoning', '')
                    )
                    logger.info(f"  🔧 MODIFIED: {mod['name']}")
                    logger.info(f"     → {mod.get('change_description', '')}")
                    modified += 1
            except Exception as e:
                logger.warning(f"  Could not modify {mod.get('name')}: {e}")

        # ── Retire weak rules
        for ret in plan.get('rules_to_retire', []):
            try:
                self.rule_engine.retire_rule(ret['name'], ret.get('reasoning', ''))
                logger.warning(f"  ❌ RETIRED: {ret['name']}")
                logger.info(f"     → {ret.get('reasoning', '')}")
                retired += 1
            except Exception as e:
                logger.warning(f"  Could not retire {ret.get('name')}: {e}")

        return {"added": added, "modified": modified, "retired": retired}

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _fallback_plan(self) -> dict:
        """Return safe empty plan if AI fails"""
        return {
            "market_assessment": {
                "dominant_regime": "UNKNOWN",
                "key_observation": "AI analysis unavailable",
                "risk_level": "HIGH"
            },
            "new_rules_to_add":    [],
            "rules_to_modify":     [],
            "rules_to_retire":     [],
            "new_filters_to_add":  [],
            "optimization_summary": "Evolution cycle ran but AI analysis failed. No changes made.",
            "next_week_focus": "Check API connectivity and retry."
        }

    def _log_cycle(self, lookback_days, candles, patterns, plan, results):
        conn = sqlite3.connect(config.EVOLUTION_LOG_DB)
        conn.execute("""
            INSERT INTO evolution_cycles
            (run_at, lookback_days, candles_analyzed, patterns_found,
             rules_added, rules_modified, rules_retired, ai_summary, full_plan)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(),
            lookback_days, candles, patterns,
            results['added'], results['modified'], results['retired'],
            plan.get('optimization_summary', ''),
            json.dumps(plan)
        ))
        conn.commit()
        conn.close()

    def get_evolution_history(self, limit: int = 10) -> list:
        conn  = sqlite3.connect(config.EVOLUTION_LOG_DB)
        rows  = conn.execute("""
            SELECT run_at, lookback_days, candles_analyzed,
                   rules_added, rules_modified, rules_retired, ai_summary
            FROM evolution_cycles
            ORDER BY run_at DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [
            {
                "run_at":    r[0],
                "period":    r[1],
                "candles":   r[2],
                "added":     r[3],
                "modified":  r[4],
                "retired":   r[5],
                "summary":   r[6]
            }
            for r in rows
        ]
