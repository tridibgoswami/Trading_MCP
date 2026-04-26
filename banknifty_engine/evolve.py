#!/usr/bin/env python3
# evolve.py
# ─────────────────────────────────────────────
# Run the AI evolution cycle manually.
# Usage:
#   python evolve.py           → last 14 days
#   python evolve.py --days 7  → last 7 days
#   python evolve.py --days 30 → last 30 days
# ─────────────────────────────────────────────

import sys
import argparse
from loguru import logger

logger.remove()
logger.add(sys.stdout, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/evolution_{time:YYYY-MM-DD}.log", rotation="1 week", level="DEBUG")

def main():
    parser = argparse.ArgumentParser(description="Run AI Evolution Cycle")
    parser.add_argument('--days', type=int, default=14,
                        help='Lookback period in days (7, 14, or 30)')
    args = parser.parse_args()

    if args.days not in [7, 14, 21, 30]:
        logger.warning(f"Unusual lookback: {args.days} days. Typical: 7, 14, or 30.")

    logger.info(f"Starting Evolution Cycle — last {args.days} days")

    try:
        from config import validate_config
        validate_config()
    except EnvironmentError as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)

    from intelligence.evolution_engine import EvolutionEngine
    engine = EvolutionEngine()
    result = engine.evolve(lookback_days=args.days)

    if 'error' in result:
        logger.error(f"Evolution failed: {result['error']}")
        sys.exit(1)

    stats = result.get('stats', {})
    plan  = result.get('plan', {})

    print("\n" + "=" * 60)
    print("  EVOLUTION RESULTS")
    print("=" * 60)
    print(f"  Candles analyzed : {stats.get('candles', 0)}")
    print(f"  Patterns found   : {stats.get('patterns_found', 0)}")
    print(f"  Rules added      : {stats.get('rules_added', 0)}")
    print(f"  Rules modified   : {stats.get('rules_modified', 0)}")
    print(f"  Rules retired    : {stats.get('rules_retired', 0)}")
    print("─" * 60)
    print(f"  Market regime    : {plan.get('market_assessment', {}).get('dominant_regime', 'N/A')}")
    print(f"  Risk level       : {plan.get('market_assessment', {}).get('risk_level', 'N/A')}")
    print("─" * 60)
    print(f"  Summary: {plan.get('optimization_summary', '')}")
    print(f"  Next week: {plan.get('next_week_focus', '')}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
