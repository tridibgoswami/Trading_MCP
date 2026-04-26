# BankNifty Self-Evolving Trading Engine

AI-powered trading engine that analyzes market data,
discovers patterns, and evolves its own strategy rules automatically.

---

## What This Does

```
Every 5 min  → Ingests latest BankNifty candles
Every signal → Logs your indicator with full market context  
Every Sunday → AI analyzes 1-2 weeks of data and evolves rules
Every evening→ Sends daily report to Telegram
```

---

## One-Time Setup

```bash
# 1. Install everything
python setup.py

# 2. Fill in your credentials
notepad .env          # Windows
nano .env             # Mac/Linux

# 3. Start the engine
python start_engine.py
```

---

## .env File (fill these in)

```
ANGEL_API_KEY=your_angelone_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_MPIN=your_mpin
ANGEL_TOTP_SECRET=your_totp_secret
ANTHROPIC_API_KEY=your_claude_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token   (optional)
TELEGRAM_CHAT_ID=your_chat_id                (optional)
PAPER_TRADE=true                             (change to false for live)
```

---

## Daily Usage

```bash
# Start the engine every morning
python start_engine.py

# Run evolution manually (Sunday recommended)
python evolve.py --days 14
python evolve.py --days 30
```

---

## Connecting Your Indicator

When your indicator fires a signal, call this:

```python
from signal_logger import SignalLogger
from core.rule_engine import RuleEngine

sig = SignalLogger()

# Log BUY signal
signal_id = sig.log_signal({
    "type":           "BUY",       # BUY / SELL / EXIT_LONG / EXIT_SHORT
    "strength":       75.5,         # Your indicator value
    "price":          48250.0,      # Current price
    "rsi":            52.3,
    "above_vwap":     True,
    "volume_ratio":   1.4,
    "regime":         "TRENDING_UP",
    "rule_triggered": "your_rule_name"
})

# After trade closes, update outcome
sig.update_outcome(
    signal_id    = signal_id,
    entry_price  = 48250.0,
    exit_price   = 48510.0,
    holding_mins = 15,
    exit_reason  = "TARGET"
)
```

---

## File Structure

```
banknifty_engine/
├── start_engine.py       ← START HERE
├── evolve.py             ← Manual evolution
├── setup.py              ← One-time setup
├── config.py             ← Configuration
├── signal_logger.py      ← Log your signals
├── scheduler.py          ← Auto-scheduler
├── mcp_server.py         ← MCP tools
├── telegram_notifier.py  ← Alerts
├── core/
│   ├── angel_connect.py  ← AngelOne API
│   ├── market_memory.py  ← Data storage
│   └── rule_engine.py    ← Strategy rules
├── intelligence/
│   ├── pattern_discovery.py  ← Pattern finder
│   └── evolution_engine.py   ← AI brain
└── data_store/           ← SQLite databases (auto-created)
```

---

## How Evolution Works

```
Sunday 8 AM
    │
    ▼
Load 14 days of BankNifty candles
    │
    ▼
Scan 400+ condition combinations
Find patterns with >60% win rate
    │
    ▼
Analyze your indicator's performance
What conditions produce wins vs losses?
    │
    ▼
Send everything to Claude AI
"What should we add, modify, retire?"
    │
    ▼
Apply the changes to rule engine
Log every change with reasoning
    │
    ▼
Report sent to Telegram
```

---

## Safety

- `PAPER_TRADE=true` by default — no real orders until you change it
- Max daily loss limit configured in .env
- All changes logged with AI reasoning
- Full audit trail of every rule change

---

## Getting AngelOne API Access

1. Login to AngelOne → My Account → API Settings
2. Create new API key
3. Note the API key, Client ID
4. Set up TOTP authenticator app
5. Copy TOTP secret to .env

## Getting Anthropic API Key

1. Go to console.anthropic.com
2. API Keys → Create new key
3. Copy to .env

## Getting Telegram Bot (Optional)

1. Message @BotFather on Telegram
2. /newbot → follow instructions
3. Copy the bot token to .env
4. Message your bot, then get chat_id from:
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
