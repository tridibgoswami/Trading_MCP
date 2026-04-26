# config.py
# ─────────────────────────────────────────────
# Central configuration for BankNifty Engine
# ─────────────────────────────────────────────

import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ── Base paths
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data_store"
LOG_DIR     = BASE_DIR / "logs"
REPORT_DIR  = BASE_DIR / "reports"

# Auto-create directories
for d in [DATA_DIR, LOG_DIR, REPORT_DIR]:
    d.mkdir(exist_ok=True)

# ── AngelOne credentials
ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY")
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID")
ANGEL_MPIN        = os.getenv("ANGEL_MPIN")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

# ── Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Telegram
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── Trading settings (analysis-only mode — order placement is disabled)
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", 1000))
MAX_DAILY_LOSS     = float(os.getenv("MAX_DAILY_LOSS", 3000))

# ── Instrument config
BANKNIFTY_TOKEN   = "99926009"   # AngelOne token for BankNifty Index
BANKNIFTY_SYMBOL  = "NIFTY BANK"
EXCHANGE          = "NSE"

# ── Market hours (IST)
MARKET_OPEN_H,  MARKET_OPEN_M  = 9,  15
MARKET_CLOSE_H, MARKET_CLOSE_M = 15, 30
PRE_OPEN_H,     PRE_OPEN_M     = 9,  0

# ── Database paths
SIGNALS_DB      = str(DATA_DIR / "signals.db")
MARKET_MEMORY_DB= str(DATA_DIR / "market_memory.db")
RULES_DB        = str(DATA_DIR / "rules.db")
EVOLUTION_LOG_DB= str(DATA_DIR / "evolution_log.db")

# ── Evolution settings
DEFAULT_LOOKBACK_DAYS = 14
MIN_PATTERN_EDGE      = 0.60    # 60% win rate minimum
MIN_SAMPLE_SIZE       = 20      # Minimum occurrences to trust pattern

# ── Validate critical credentials
def validate_config():
    missing = []
    for name, val in [
        ("ANGEL_API_KEY",     ANGEL_API_KEY),
        ("ANGEL_CLIENT_ID",   ANGEL_CLIENT_ID),
        ("ANGEL_MPIN",        ANGEL_MPIN),
        ("ANGEL_TOTP_SECRET", ANGEL_TOTP_SECRET),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ]:
        if not val:
            missing.append(name)
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Please copy .env.example to .env and fill in your values."
        )
    return True
