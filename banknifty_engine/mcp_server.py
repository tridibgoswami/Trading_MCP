# mcp_server.py
# ─────────────────────────────────────────────
# MCP Server — exposes all engine capabilities
# as tools that Claude can call.
# ─────────────────────────────────────────────

import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
import mcp.types as types
from loguru import logger

from core.market_memory import MarketMemory
from core.rule_engine import RuleEngine
from core.live_analyzer import LiveAnalyzer
from intelligence.evolution_engine import EvolutionEngine
from intelligence.pattern_discovery import PatternDiscovery
from signal_logger import SignalLogger
from telegram_notifier import TelegramNotifier
import config

# ── Initialize all components
server   = Server("banknifty-evolution-engine")
memory   = MarketMemory()
rules    = RuleEngine()
engine   = EvolutionEngine()
sig_log  = SignalLogger()
telegram = TelegramNotifier()
live     = LiveAnalyzer()


# ─────────────────────────────────────────────
# TOOL DEFINITIONS
# ─────────────────────────────────────────────
@server.list_tools()
async def list_tools():
    return [

        types.Tool(
            name="log_signal",
            description="Log a new signal from your indicator with full market context",
            inputSchema={
                "type": "object",
                "properties": {
                    "type":           {"type": "string", "enum": ["BUY","SELL","EXIT_LONG","EXIT_SHORT"]},
                    "strength":       {"type": "number", "description": "Indicator signal value"},
                    "price":          {"type": "number"},
                    "rsi":            {"type": "number"},
                    "ema_9":          {"type": "number"},
                    "ema_21":         {"type": "number"},
                    "above_vwap":     {"type": "boolean"},
                    "volume_ratio":   {"type": "number"},
                    "atr":            {"type": "number"},
                    "macd":           {"type": "number"},
                    "macd_signal":    {"type": "number"},
                    "vix":            {"type": "number"},
                    "regime":         {"type": "string"},
                    "trend_direction":{"type": "string"},
                    "rule_triggered": {"type": "string"},
                },
                "required": ["type", "price"]
            }
        ),

        types.Tool(
            name="update_trade_outcome",
            description="Update a signal with its final trade result",
            inputSchema={
                "type": "object",
                "properties": {
                    "signal_id":    {"type": "integer"},
                    "entry_price":  {"type": "number"},
                    "exit_price":   {"type": "number"},
                    "holding_mins": {"type": "integer"},
                    "exit_reason":  {"type": "string",
                                     "enum": ["TARGET","STOPLOSS","TIME","MANUAL"]}
                },
                "required": ["signal_id", "entry_price", "exit_price", "holding_mins"]
            }
        ),

        types.Tool(
            name="run_evolution_cycle",
            description="Analyze market data and evolve the strategy. Runs weekly or on demand.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "7=1week, 14=2weeks, 30=1month",
                        "default": 14
                    }
                }
            }
        ),

        types.Tool(
            name="discover_patterns",
            description="Scan price data and discover new tradeable patterns",
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer", "default": 14},
                    "min_edge":      {"type": "number", "default": 0.6,
                                      "description": "Minimum win rate (0.5-1.0)"},
                    "lookahead":     {"type": "integer", "default": 10,
                                      "description": "Candles ahead to measure move"}
                }
            }
        ),

        types.Tool(
            name="get_active_rules",
            description="Get all currently active trading rules with performance stats",
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="get_evolution_history",
            description="See what the AI has changed over time and why",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20}
                }
            }
        ),

        types.Tool(
            name="add_rule_manually",
            description="Manually add a trading rule to the engine",
            inputSchema={
                "type": "object",
                "properties": {
                    "name":       {"type": "string"},
                    "type":       {"type": "string", "enum": ["ENTRY","EXIT","FILTER"]},
                    "direction":  {"type": "string", "enum": ["LONG","SHORT","BOTH"]},
                    "conditions": {"type": "array", "items": {"type": "string"}},
                    "parameters": {"type": "object"},
                    "weight":     {"type": "number", "default": 1.0}
                },
                "required": ["name", "type", "direction", "conditions"]
            }
        ),

        types.Tool(
            name="retire_rule",
            description="Manually retire a rule that is no longer working",
            inputSchema={
                "type": "object",
                "properties": {
                    "name":   {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["name", "reason"]
            }
        ),

        types.Tool(
            name="get_daily_summary",
            description="Get today's trading summary — signals, wins, losses, PnL",
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="get_market_memory_stats",
            description="Show how much market data the engine has stored",
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="analyze_signal_performance",
            description="Deep analysis of your indicator's historical signals",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 30}
                }
            }
        ),

        # ── LIVE ANALYSIS TOOLS ──────────────────────────────────────────

        types.Tool(
            name="start_live_analysis",
            description=(
                "Connect to AngelOne WebSocket and start real-time market analysis. "
                "Must be called before using any other live_ tools. "
                "Starts live price feed + indicator refresh every 60 seconds."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="stop_live_analysis",
            description="Disconnect from the live feed and stop real-time analysis.",
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="get_live_market_state",
            description=(
                "Get a complete real-time snapshot of the market: "
                "live price (LTP), RSI, EMAs, VWAP, MACD, Bollinger Bands, "
                "ATR, volume ratio, market regime, trend direction, "
                "intraday high/low, session, and recent alerts."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="get_live_signals",
            description=(
                "Get the most recent signals detected from live price action: "
                "EMA crossovers, RSI bounces/reversals, MACD crosses, "
                "VWAP + volume surges, Bollinger Band touches, trend confirmations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "last_n": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of most recent signals to return"
                    }
                }
            }
        ),

        types.Tool(
            name="force_refresh_analysis",
            description=(
                "Force an immediate indicator refresh without waiting for the "
                "60-second cycle. Useful right after a major price move."
            ),
            inputSchema={"type": "object", "properties": {}}
        ),

    ]


# ─────────────────────────────────────────────
# TOOL HANDLERS
# ─────────────────────────────────────────────
@server.call_tool()
async def call_tool(name: str, arguments: dict):

    try:

        # ── LOG SIGNAL ──────────────────────────────────────
        if name == "log_signal":
            sid = sig_log.log_signal(arguments)
            telegram.signal_alert(
                signal_type = arguments['type'],
                price       = arguments['price'],
                strength    = arguments.get('strength', 0),
                regime      = arguments.get('regime', 'UNKNOWN'),
                session     = sig_log._get_session()
            )
            return [types.TextContent(type="text",
                    text=json.dumps({"signal_id": sid, "status": "logged"}))]

        # ── UPDATE OUTCOME ───────────────────────────────────
        elif name == "update_trade_outcome":
            result = sig_log.update_outcome(
                signal_id    = arguments['signal_id'],
                entry_price  = arguments['entry_price'],
                exit_price   = arguments['exit_price'],
                holding_mins = arguments['holding_mins'],
                exit_reason  = arguments.get('exit_reason', 'MANUAL')
            )
            telegram.trade_closed(
                signal_type = "TRADE",
                entry       = arguments['entry_price'],
                exit_       = arguments['exit_price'],
                pnl         = result['pnl'],
                reason      = arguments.get('exit_reason', 'MANUAL')
            )
            return [types.TextContent(type="text", text=json.dumps(result))]

        # ── EVOLUTION CYCLE ──────────────────────────────────
        elif name == "run_evolution_cycle":
            days   = arguments.get('lookback_days', 14)
            result = engine.evolve(lookback_days=days)
            if 'plan' in result:
                telegram.evolution_report(result['results'], result['plan'])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # ── DISCOVER PATTERNS ────────────────────────────────
        elif name == "discover_patterns":
            days     = arguments.get('lookback_days', 14)
            df       = memory.get_memory(days=days)
            if df.empty:
                return [types.TextContent(type="text",
                        text='{"error": "No market data. Run ingest first."}')]
            disc     = PatternDiscovery(df)
            patterns = disc.discover_profitable_conditions(
                lookahead = arguments.get('lookahead', 10),
                min_edge  = arguments.get('min_edge', 0.6)
            )
            return [types.TextContent(type="text", text=json.dumps(patterns, indent=2))]

        # ── GET ACTIVE RULES ─────────────────────────────────
        elif name == "get_active_rules":
            active = rules.get_active_rules()
            return [types.TextContent(type="text", text=json.dumps(active, indent=2))]

        # ── EVOLUTION HISTORY ────────────────────────────────
        elif name == "get_evolution_history":
            hist = engine.get_evolution_history(limit=arguments.get('limit', 20))
            return [types.TextContent(type="text", text=json.dumps(hist, indent=2))]

        # ── ADD RULE MANUALLY ────────────────────────────────
        elif name == "add_rule_manually":
            ok = rules.add_rule(arguments, origin="MANUAL")
            return [types.TextContent(type="text",
                    text=json.dumps({"status": "added" if ok else "failed",
                                     "name": arguments.get('name')}))]

        # ── RETIRE RULE ──────────────────────────────────────
        elif name == "retire_rule":
            rules.retire_rule(arguments['name'], arguments['reason'])
            return [types.TextContent(type="text",
                    text=json.dumps({"status": "retired", "name": arguments['name']}))]

        # ── DAILY SUMMARY ────────────────────────────────────
        elif name == "get_daily_summary":
            summary = sig_log.daily_summary()
            return [types.TextContent(type="text", text=json.dumps(summary, indent=2))]

        # ── MARKET MEMORY STATS ──────────────────────────────
        elif name == "get_market_memory_stats":
            total   = memory.total_candles()
            recent  = memory.get_recent_candles(5).to_dict(orient='records')
            return [types.TextContent(type="text",
                    text=json.dumps({"total_candles": total,
                                     "recent_5": recent}, indent=2, default=str))]

        # ── SIGNAL PERFORMANCE ANALYSIS ──────────────────────
        elif name == "analyze_signal_performance":
            days       = arguments.get('days', 30)
            signals_df = sig_log.get_signals_with_outcomes(days=days)
            df         = memory.get_memory(days=days)
            if df.empty:
                return [types.TextContent(type="text",
                        text='{"error": "No market data available"}')]
            disc    = PatternDiscovery(df)
            result  = disc.analyze_signal_performance(signals_df)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # ── START LIVE ANALYSIS ──────────────────────────────────────
        elif name == "start_live_analysis":
            ok = live.start()
            return [types.TextContent(type="text",
                    text=json.dumps({
                        "status":  "started" if ok else "failed",
                        "message": (
                            "Real-time analysis active. "
                            "Indicators refresh every 60 seconds. "
                            "Use get_live_market_state to query current data."
                        ) if ok else "Failed to connect. Check AngelOne credentials in .env"
                    }))]

        # ── STOP LIVE ANALYSIS ───────────────────────────────────────
        elif name == "stop_live_analysis":
            live.stop()
            return [types.TextContent(type="text",
                    text=json.dumps({"status": "stopped"}))]

        # ── GET LIVE MARKET STATE ────────────────────────────────────
        elif name == "get_live_market_state":
            state = live.get_market_state()
            return [types.TextContent(type="text",
                    text=json.dumps(state, indent=2, default=str))]

        # ── GET LIVE SIGNALS ─────────────────────────────────────────
        elif name == "get_live_signals":
            signals = live.get_live_signals(last_n=arguments.get("last_n", 10))
            return [types.TextContent(type="text",
                    text=json.dumps({
                        "count":   len(signals),
                        "signals": signals
                    }, indent=2))]

        # ── FORCE REFRESH ────────────────────────────────────────────
        elif name == "force_refresh_analysis":
            live.force_refresh()
            return [types.TextContent(type="text",
                    text=json.dumps({
                        "status":  "refresh_triggered",
                        "message": "Indicators updating now. Query get_live_market_state in ~5 seconds."
                    }))]

        else:
            return [types.TextContent(type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        return [types.TextContent(type="text",
                text=json.dumps({"error": str(e), "tool": name}))]


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
async def main():
    logger.info("Starting BankNifty Evolution MCP Server...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name    = "banknifty-evolution-engine",
                server_version = "1.0.0",
                capabilities   = server.get_capabilities(
                    notification_options = None,
                    experimental_capabilities = {}
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
